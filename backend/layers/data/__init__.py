"""Layer 6 — Data Layer (PRD §3 Layer 6).

The ONLY layer that constructs and executes SQL. It does so exclusively through
the Schema Registry (§4) using SQLAlchemy Core, so:

  * physical table/column names live only in the registry (acceptance §8.3);
  * the query is built from registry metadata, never by string-concatenating
    user-influenced values — all bound values are parameterized (§8.7);
  * a column rename is a one-file registry change with zero code impact.

EXTENSION (maintenance domain, multi-table joins)
--------------------------------------------------
The original MVP only ever queried a single table. The maintenance schema needs
cross-table answers (e.g. "failed calibrations" joins
torque_calibration_wrenches -> torque_calibration_submissions). This layer now:

  1. Resolves an entity's *base table* from `schema_registry.base_tables`.
  2. Collects every other physical table referenced by the requested
     metrics/dimensions/filters.
  3. Walks the registry's `joins:` edge list (a simple BFS) to connect each
     referenced table back to the base table, building explicit SQLAlchemy
     `.join()` clauses — never an implicit cartesian product.
  4. A metric may instead declare `strategy: anti_join`, handled as a dedicated
     code path (a NOT IN subquery) for "rows with no matching child row"
     questions (e.g. "stores that did NOT submit a torque check").

On any DB error/timeout the layer returns DATA_LAYER_FAILURE and never lets a raw
DB message or stack trace propagate onward (§6.4).

Contract:
    in : {"entity": "torque_calibration", "select": {"metrics": ["failed_calibration_count"], ...},
          "filters": [...], "sort": [...], "limit": ...}
    out: same, plus {"result": ...}
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, model_validator
from sqlalchemy import Engine, column, func, select, table as table_
from sqlalchemy.exc import SQLAlchemyError

from backend.config_loader import ConfigStore, config as default_config
from backend.database.mysql import get_engine
from backend.envelope import Envelope
from backend.errors import ErrorCode, LayerError
from backend.layers.base import Layer
import logging

logger = logging.getLogger(__name__)

# Whitelisted aggregations. The registry can only name one of these; anything
# else is a config error, not a SQL-injection vector.
_AGGREGATIONS = {
    "SUM": func.sum,
    "COUNT": func.count,
    "AVG": func.avg,
    "MIN": func.min,
    "MAX": func.max,
}


class _Select(BaseModel):
    metrics: list[str] = []
    dimensions: list[str] = []


class _FilterItem(BaseModel):
    field: str
    operator: str
    value: Any


class _SortItem(BaseModel):
    field: str
    direction: str


class _DataInput(BaseModel):
    entity: str
    select: _Select
    filters: list[_FilterItem] = []
    sort: list[_SortItem] = []
    limit: int | None = None

    @model_validator(mode="before")
    @classmethod
    def convert_legacy_payload(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        if "metric" in data and "select" not in data:
            metric = data.get("metric")
            filters_data = data.get("filters", {})
            period_val = ""
            if isinstance(filters_data, dict):
                period_val = filters_data.get("period", "")

            new_data = {
                "entity": data.get("entity"),
                "select": {
                    "metrics": [metric] if metric else [],
                    "dimensions": []
                },
                "filters": [],
                "sort": [],
                "limit": None
            }
            if period_val:
                new_data["filters"].append({
                    "field": "period",
                    "operator": "EQUALS",
                    "value": period_val
                })
            return new_data
        return data


class DataLayer(Layer):
    name = "data"

    def __init__(
        self,
        config: ConfigStore | None = None,
        engine: Engine | None = None,
        today: date | None = None,
    ) -> None:
        self._config = config or default_config
        self._engine = engine  # lazily resolved so tests can inject an in-memory DB
        self._today = today  # injectable "now" for deterministic period windows

    def handle(self, envelope: Envelope) -> dict[str, Any]:
        data = self.parse(_DataInput, envelope.payload)
        mappings = self._config.schema_mappings()

        # anti_join strategy metrics take a completely different query shape
        # (a NOT IN subquery), so they're dispatched before the generic builder.
        if len(data.select.metrics) == 1:
            metric_map = mappings["metrics"].get(data.select.metrics[0], {})
            if metric_map.get("strategy") == "anti_join":
                value = self._run_anti_join(data, metric_map)
                return self._envelope_out(data, value)

        value = self._run_query(data)
        return self._envelope_out(data, value)

    def _envelope_out(self, data: _DataInput, value: Any) -> dict[str, Any]:
        metric_name = data.select.metrics[0] if data.select.metrics else ""
        period_val = ""
        for f in data.filters:
            if f.field == "period":
                period_val = f.value
                break
        return {
            "entity": data.entity,
            "metric": metric_name,
            "filters": {"period": period_val},
            "result": value,
        }

    # --- anti-join strategy: "rows in base_table with no matching child row" --
    def _run_anti_join(self, query: _DataInput, metric_map: dict[str, Any]) -> Any:
        base_table = metric_map["base_table"]
        base_id_col = metric_map["base_id_column"]
        join_table = metric_map["join_table"]
        join_col = metric_map["join_column"]
        date_col = metric_map.get("date_column")

        base_tbl = table_(base_table, column(base_id_col), column("store_name"))
        join_tbl = table_(join_table, column(join_col), column(date_col) if date_col else column("id"))

        subq = select(getattr(join_tbl.c, join_col))
        period_val = None
        for f in query.filters:
            if f.field == "period":
                period_val = f.value
        if date_col and period_val:
            boundary = self._period_boundary(period_val)
            subq = subq.where(getattr(join_tbl.c, date_col) >= boundary)

        stmt = (
            select(
                getattr(base_tbl.c, base_id_col).label("store_id"),
                base_tbl.c.store_name.label("store_name"),
            )
            .select_from(base_tbl)
            .where(getattr(base_tbl.c, base_id_col).notin_(subq))
        )

        try:
            with self._get_engine().connect() as conn:
                rows = conn.execute(stmt).fetchall()
        except SQLAlchemyError as exc:
            print(exc)
            raise LayerError(
                ErrorCode.DATA_LAYER_FAILURE,
                "The data store could not be queried. Please try again later.",
            ) from exc

        return [
            {"store_id": self._coerce_number(r[0]), "store_name": r[1]}
            for r in rows
        ]

    # --- join-graph resolution ---------------------------------------------
    @staticmethod
    def _resolve_joins(
        base_table: str,
        needed_tables: set[str],
        join_edges: list[dict[str, Any]],
    ) -> list[tuple[str, str, str, str, str]]:
        """BFS the join graph from `base_table`, returning ordered join steps.

        Each step is (new_table, new_table_col, existing_table, existing_col,
        new_table). Raises DATA_LAYER_FAILURE if a needed table is unreachable
        (a registry config gap, not a user error).
        """
        joined = {base_table}
        steps: list[tuple[str, str, str, str, str]] = []
        remaining = set(needed_tables) - joined
        progressed = True
        while remaining and progressed:
            progressed = False
            for edge in join_edges:
                lt, lc, rt, rc = edge["left_table"], edge["left_column"], edge["right_table"], edge["right_column"]
                if lt in joined and rt in remaining:
                    steps.append((rt, rc, lt, lc, rt))
                    joined.add(rt)
                    remaining.discard(rt)
                    progressed = True
                elif rt in joined and lt in remaining:
                    steps.append((lt, lc, rt, rc, lt))
                    joined.add(lt)
                    remaining.discard(lt)
                    progressed = True
        if remaining:
            raise LayerError(
                ErrorCode.DATA_LAYER_FAILURE,
                f"No join path configured from '{base_table}' to {sorted(remaining)}. "
                "Add an edge to schema_registry/mappings.yaml `joins:`.",
            )
        return steps

    # --- query construction (Schema-Registry-driven only) ----------------------
    def _run_query(self, query: _DataInput) -> Any:
        mappings = self._config.schema_mappings()
        base_table = mappings.get("base_tables", {}).get(query.entity)
        if base_table is None:
            # Backward-compat fallback for single-table entities without an
            # explicit base_table entry: infer from the first referenced metric.
            for m in query.select.metrics:
                base_table = mappings["metrics"][m]["table"]
                break
        if base_table is None:
            raise LayerError(
                ErrorCode.DATA_LAYER_FAILURE,
                f"No base_table configured for entity '{query.entity}' in the schema registry.",
            )

        # Collect every (table, column) this query actually references.
        refs: list[tuple[str, str]] = []  # (table, column)
        for metric in query.select.metrics:
            m = mappings["metrics"][metric]
            refs.append((m["table"], m["column"]))
        for dim in query.select.dimensions:
            d = mappings["dimensions"][dim]
            refs.append((d["table"], d["column"]))
        for f in query.filters:
            if f.field == "period":
                continue  # resolved separately via period_columns below
            d = mappings["dimensions"].get(f.field)
            if d is not None:
                refs.append((d["table"], d["column"]))

        period_filter_val = None
        for f in query.filters:
            if f.field == "period":
                period_filter_val = f.value
        period_table = period_col = None
        if period_filter_val is not None:
            pc = mappings.get("period_columns", {}).get(query.entity)
            if pc is None:
                raise LayerError(
                    ErrorCode.DATA_LAYER_FAILURE,
                    f"No period_columns entry configured for entity '{query.entity}'.",
                )
            period_table, period_col = pc["table"], pc["column"]
            refs.append((period_table, period_col))

        needed_tables = {t for t, _ in refs}
        join_edges = mappings.get("joins", [])
        join_steps = self._resolve_joins(base_table, needed_tables, join_edges)

        # Join columns (the ON-clause FK/PK pair) must also be declared on
        # their respective Table objects, even if not otherwise selected.
        for new_table, new_col, existing_table, existing_col, _ in join_steps:
            refs.append((new_table, new_col))
            refs.append((existing_table, existing_col))

        # Build one SQLAlchemy Table object per referenced physical table,
        # each declaring only the columns this query actually touches.
        cols_by_table: dict[str, set[str]] = {}
        for t, c in refs:
            cols_by_table.setdefault(t, set()).add(c)
        cols_by_table.setdefault(base_table, set())

        tbl_objs: dict[str, Any] = {
            t: table_(t, *[column(c) for c in cols]) for t, cols in cols_by_table.items()
        }

        stmt_from = tbl_objs[base_table]
        joined_obj = tbl_objs[base_table]
        for new_table, new_col, existing_table, existing_col, _ in join_steps:
            new_obj = tbl_objs[new_table]
            existing_obj = tbl_objs[existing_table]
            onclause = getattr(new_obj.c, new_col) == getattr(existing_obj.c, existing_col)
            joined_obj = joined_obj.join(new_obj, onclause)

        # Build SELECT expressions.
        select_exprs = []
        for dim in query.select.dimensions:
            d = mappings["dimensions"][dim]
            select_exprs.append(getattr(tbl_objs[d["table"]].c, d["column"]).label(dim))

        for metric in query.select.metrics:
            m = mappings["metrics"][metric]
            agg = _AGGREGATIONS.get(m["aggregation"].upper())
            if agg is None:
                raise LayerError(
                    ErrorCode.DATA_LAYER_FAILURE,
                    f"Unsupported aggregation '{m['aggregation']}' for metric '{metric}'.",
                )
            select_exprs.append(agg(getattr(tbl_objs[m["table"]].c, m["column"])).label(metric))

        stmt = select(*select_exprs).select_from(joined_obj)

        # Filters.
        where_clauses = []
        for f in query.filters:
            if f.field == "period":
                boundary = self._period_boundary(f.value)
                where_clauses.append(getattr(tbl_objs[period_table].c, period_col) >= boundary)
            else:
                d = mappings["dimensions"].get(f.field)
                if d is None:
                    continue
                col_obj = getattr(tbl_objs[d["table"]].c, d["column"])
                if f.operator == "EQUALS":
                    where_clauses.append(col_obj == f.value)
                elif f.operator == "GREATER_THAN":
                    where_clauses.append(col_obj > f.value)
                elif f.operator == "LESS_THAN":
                    where_clauses.append(col_obj < f.value)
        if where_clauses:
            stmt = stmt.where(*where_clauses)

        # Group by (any dimension alongside an aggregated metric).
        if query.select.dimensions and query.select.metrics:
            group_cols = [
                getattr(tbl_objs[mappings["dimensions"][dim]["table"]].c, mappings["dimensions"][dim]["column"])
                for dim in query.select.dimensions
            ]
            stmt = stmt.group_by(*group_cols)

        # Sorting.
        for sort_item in query.sort:
            col_obj = None
            if sort_item.field in query.select.metrics:
                col_obj = column(sort_item.field)
            elif sort_item.field in query.select.dimensions:
                d = mappings["dimensions"][sort_item.field]
                col_obj = getattr(tbl_objs[d["table"]].c, d["column"])
            if col_obj is not None:
                stmt = stmt.order_by(col_obj.desc() if sort_item.direction == "DESC" else col_obj.asc())

        # Limit.
        if query.limit is not None:
            stmt = stmt.limit(query.limit)

        print(stmt)

        try:
            with self._get_engine().connect() as conn:
                cursor = conn.execute(stmt)
                raw_results = cursor.fetchall()
                keys = cursor.keys()
                metric_keys = set(query.select.metrics)
                results = []
                for r in raw_results:
                    row_dict = {}
                    for key, val in zip(keys, r):
                        row_dict[key] = self._coerce_number(val) if key in metric_keys else self._coerce_dimension(val)
                    results.append(row_dict)
        except SQLAlchemyError as exc:
            print(exc)
            raise LayerError(
                ErrorCode.DATA_LAYER_FAILURE,
                "The data store could not be queried. Please try again later.",
            ) from exc

        # For simple scalar queries, return compatible structure.
        if not query.select.dimensions and len(query.select.metrics) == 1:
            metric = query.select.metrics[0]
            val = results[0][metric] if results else 0
            return {metric: val}

        return results

    def _period_boundary(self, period: str) -> date:
        windows = self._config.settings()["periods"]
        days = windows[period]["days"]
        today = self._today or date.today()
        return today - timedelta(days=days)

    def _get_engine(self) -> Engine:
        return self._engine if self._engine is not None else get_engine()

    @staticmethod
    def _coerce_dimension(raw: Any) -> Any:
        """Normalize a plain (non-aggregated) selected/dimension value.

        Unlike `_coerce_number`, a NULL stays empty/None here — coercing it to
        0 would misrepresent e.g. a NULL `job_code` as the number zero.
        """
        if isinstance(raw, (date, datetime)):
            return raw.isoformat()
        if isinstance(raw, Decimal):
            return int(raw) if raw == raw.to_integral_value() else float(raw)
        return raw

    @staticmethod
    def _coerce_number(raw: Any) -> int | float | str:
        """Normalize an aggregate result to a JSON-safe number (None -> 0)."""
        if raw is None:
            return 0
        if isinstance(raw, (date, datetime)):
            return raw.isoformat()
        if isinstance(raw, Decimal):
            return int(raw) if raw == raw.to_integral_value() else float(raw)
        return raw
