"""Layer 4 — Semantic Query Layer (PRD §3 Layer 4).

Translates the business request into a VALIDATED, SQL-free business query governed
by per-entity config. HARD RULE: this layer contains zero SQL — it only knows
entities, metrics, dimensions, and allowed filters as declared in config.

Any metric or filter not declared for the entity is rejected here with
SEMANTIC_VALIDATION_FAILED; the request never reaches the Service/Data layers.

Contract (pass-through on success — the validated business query):
    in/out: {"entity": "sales", "metric": "total_sales",
             "filters": {"period": "this_week"}}
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, model_validator

from backend.config_loader import ConfigStore, config as default_config
from backend.envelope import Envelope
from backend.errors import ErrorCode, LayerError
from backend.layers.base import Layer


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


class _SemanticInput(BaseModel):
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


class SemanticLayer(Layer):
    name = "semantic"

    def __init__(self, config: ConfigStore | None = None) -> None:
        self._config = config or default_config

    def handle(self, envelope: Envelope) -> dict[str, Any]:
        data = self.parse(_SemanticInput, envelope.payload)
        self.validate(data)
        if not data.select.dimensions and len(data.select.metrics) == 1 and len(data.filters) == 1 and data.filters[0].field == "period":
            return {
                "entity": data.entity,
                "metric": data.select.metrics[0],
                "filters": {"period": data.filters[0].value}
            }
        return data.model_dump()

    def validate(self, query: _SemanticInput) -> None:
        """Assert metrics and filters are declared for the entity, else raise."""
        entity = query.entity
        try:
            entity_def = self._config.semantic_entity(entity)
        except FileNotFoundError as exc:
            raise LayerError(
                ErrorCode.SEMANTIC_VALIDATION_FAILED,
                f"Unknown entity '{entity}'.",
            ) from exc

        # Validate metrics
        for metric in query.select.metrics:
            if metric not in entity_def.get("metrics", []):
                raise LayerError(
                    ErrorCode.SEMANTIC_VALIDATION_FAILED,
                    f"Metric '{metric}' is not declared for entity '{entity}'.",
                )

        # Validate filters
        allowed_filters = entity_def.get("filters", {})
        for filter_item in query.filters:
            field = filter_item.field
            if field not in allowed_filters:
                raise LayerError(
                    ErrorCode.SEMANTIC_VALIDATION_FAILED,
                    f"Filter field '{field}' is not declared for entity '{entity}'.",
                )

            # If it's a period filter, validate allowed period values
            if field == "period":
                period_val = filter_item.value
                allowed_periods = allowed_filters.get("period", [])
                if period_val not in allowed_periods:
                    raise LayerError(
                        ErrorCode.SEMANTIC_VALIDATION_FAILED,
                        f"Period '{period_val}' is not an allowed filter for entity '{entity}'.",
                    )
