"""Add-a-question wizard (authoring aid — NOT part of the request path).

Asks a few plain-language questions and writes the answers into the layer YAML
files for you — so adding a new question doesn't mean hand-editing six files and
keeping names in sync. Comments in the existing files are preserved (ruamel.yaml).

Usage:
    python -m backend.add_question

After it finishes it runs the consistency checker automatically. The only thing
it can't do is create your database table — it reminds you which table/columns
the new question expects.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap
from ruamel.yaml.scalarstring import DoubleQuotedScalarString as DQ
from ruamel.yaml.scalarstring import SingleQuotedScalarString as SQ

from backend.check_config import run_checks
from backend.config_loader import ConfigStore, config as default_config

_AGGREGATIONS = ["COUNT", "SUM", "AVG", "MIN", "MAX"]
_VALUE_FORMATS = ["number", "currency"]


@dataclass
class QuestionSpec:
    """Everything needed to wire one question across all layers."""

    intent: str
    patterns: list[str]
    entity: str
    metric: str
    table: str
    column: str
    aggregation: str
    template: str
    value_format: str
    date_column: str | None = None
    periods: list[str] = field(default_factory=lambda: ["today", "this_week", "this_month"])
    roles: list[str] = field(default_factory=lambda: ["admin"])
    description: str = ""


# --- writing the YAML files ---------------------------------------------------
def _yaml() -> YAML:
    y = YAML()
    y.preserve_quotes = True
    y.indent(mapping=2, sequence=4, offset=2)
    y.width = 4096  # don't wrap long template strings
    return y


def _insert_into_map(cmap, key, value) -> None:
    """Insert after the first key so the new entry stays above any trailing
    section comment ruamel attaches to the *last* key (keeps files readable)."""
    if len(cmap) >= 1:
        cmap.insert(1, key, value)
    else:
        cmap[key] = value


def _insert_into_list(seq, item) -> None:
    """Insert before the last element, for the same comment-placement reason."""
    if len(seq) >= 1:
        seq.insert(len(seq) - 1, item)
    else:
        seq.append(item)


def apply_spec(spec: QuestionSpec, base_dir: Path) -> list[str]:
    """Write `spec` into every layer file under `base_dir`. Returns a change log.

    Raises ValueError if the intent or metric already exists (so re-runs don't
    silently duplicate entries).
    """
    yaml = _yaml()
    changes: list[str] = []

    def load(rel: str):
        return yaml.load((base_dir / rel).read_text(encoding="utf-8"))

    def save(rel: str, data) -> None:
        with (base_dir / rel).open("w", encoding="utf-8") as fh:
            yaml.dump(data, fh)
        changes.append(f"updated {rel}")

    # 1. intent_patterns.yaml — phrases -> intent
    patterns_doc = load("config/intent_patterns.yaml")
    if any(i["name"] == spec.intent for i in patterns_doc["intents"]):
        raise ValueError(f"intent '{spec.intent}' already exists in intent_patterns.yaml")
    intent_entry = CommentedMap()
    intent_entry["name"] = spec.intent
    intent_entry["description"] = DQ(spec.description or f"{spec.metric} over a time period.")
    intent_entry["patterns"] = [SQ(p) for p in spec.patterns]
    _insert_into_list(patterns_doc["intents"], intent_entry)
    save("config/intent_patterns.yaml", patterns_doc)

    # 2. orchestration.yaml — intent -> {entity, metric}
    orch = load("config/orchestration.yaml")
    if spec.intent in orch["intents"]:
        raise ValueError(f"intent '{spec.intent}' already mapped in orchestration.yaml")
    mapping = CommentedMap()
    mapping["entity"] = spec.entity
    mapping["metric"] = spec.metric
    _insert_into_map(orch["intents"], spec.intent, mapping)
    save("config/orchestration.yaml", orch)

    # 3. semantic/entities/<entity>.yaml — declare metric + allowed periods
    entity_rel = f"semantic/entities/{spec.entity}.yaml"
    if (base_dir / entity_rel).is_file():
        entity_doc = load(entity_rel)
        if spec.metric not in entity_doc.get("metrics", []):
            entity_doc["metrics"].append(spec.metric)
        period_list = entity_doc.setdefault("filters", {}).setdefault("period", [])
        for p in spec.periods:
            if p not in period_list:
                period_list.append(p)
        save(entity_rel, entity_doc)
    else:
        (base_dir / entity_rel).write_text(_new_entity_yaml(spec), encoding="utf-8")
        changes.append(f"created {entity_rel}")

    # 4. schema_registry/mappings.yaml — metric -> column + aggregation
    mappings = load("schema_registry/mappings.yaml")
    if spec.metric in mappings["metrics"]:
        raise ValueError(f"metric '{spec.metric}' already exists in mappings.yaml")
    metric_map = CommentedMap()
    metric_map["table"] = spec.table
    metric_map["column"] = spec.column
    metric_map["aggregation"] = spec.aggregation
    if spec.date_column:
        metric_map["date_column"] = spec.date_column  # per-metric period column
    _insert_into_map(mappings["metrics"], spec.metric, metric_map)
    save("schema_registry/mappings.yaml", mappings)

    # 5. response_templates.yaml — metric -> wording + value format
    response = load("config/response_templates.yaml")
    if spec.metric in response.get("metrics", {}):
        raise ValueError(f"metric '{spec.metric}' already has a response template")
    resp_entry = CommentedMap()
    resp_entry["template"] = DQ(spec.template)
    resp_entry["format"] = spec.value_format
    _insert_into_map(response["metrics"], spec.metric, resp_entry)
    save("config/response_templates.yaml", response)

    # 6. roles.yaml — grant the entity to the chosen roles
    roles_doc = load("config/roles.yaml")
    for role in spec.roles:
        role_def = roles_doc["roles"].get(role)
        if role_def is None:
            role_def = CommentedMap()
            role_def["allowed_entities"] = [spec.entity]
            roles_doc["roles"][role] = role_def
        else:
            allowed = role_def.setdefault("allowed_entities", [])
            if spec.entity not in allowed:
                _insert_into_list(allowed, spec.entity)
    save("config/roles.yaml", roles_doc)

    return changes


def _new_entity_yaml(spec: QuestionSpec) -> str:
    periods = "\n".join(f"    - {p}" for p in spec.periods)
    return (
        "# Semantic entity definition (PRD §3 Layer 4) — generated by add_question.\n"
        "# Knows ONLY business concepts: metrics + allowed filters. Zero SQL, zero\n"
        "# physical column names (those live in the schema registry).\n"
        f"entity: {spec.entity}\n\n"
        "metrics:\n"
        f"  - {spec.metric}\n\n"
        "filters:\n"
        "  period:\n"
        f"{periods}\n"
    )


# --- interactive collection ---------------------------------------------------
def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _patterns_from_keywords(keywords: list[str]) -> list[str]:
    out = []
    for kw in keywords:
        esc = re.escape(kw.strip())
        out.append(rf"\b{esc}\b" if kw.strip().endswith("s") else rf"\b{esc}s?\b")
    return out


def collect_spec(
    cfg: ConfigStore,
    prompt: Callable[[str], str] = input,
    out: Callable[[str], None] = print,
) -> QuestionSpec:
    """Gather a QuestionSpec interactively, with smart defaults at each step."""

    def ask(label: str, default: str = "") -> str:
        suffix = f" [{default}]" if default else ""
        answer = prompt(f"{label}{suffix}: ").strip()
        return answer or default

    known_periods = cfg.settings().get("periods", {})

    out("\nAdd a new question — answer the prompts (press Enter to accept [defaults]).\n")

    question = ""
    while not question:
        question = prompt("1) The question, e.g. 'How many orders did we get today?': ").strip()

    detected = [p for p in known_periods if p.replace("_", " ") in question.lower()] or None

    kw_default = " ".join(w for w in re.findall(r"[a-zA-Z]+", question)
                          if w.lower() in {"orders", "order", "customers", "customer",
                                           "sales", "revenue", "refunds", "returns"}) or ""
    keywords = ask("2) Keyword(s) that identify it (comma-separated)", kw_default)
    keyword_list = [k for k in (s.strip() for s in keywords.split(",")) if k]
    patterns = _patterns_from_keywords(keyword_list) if keyword_list else []

    default_slug = _slug(keyword_list[0]) if keyword_list else _slug(question)[:24]
    intent = ask("3) Short name for this question (slug)", default_slug)

    db_tables = []
    inspector = None
    try:
        from sqlalchemy import inspect
        from backend.database.mysql import get_engine
        engine = get_engine()
        inspector = inspect(engine)
        db_tables = inspector.get_table_names()
    except Exception:
        pass

    existing = _existing_entities(cfg)
    if existing:
        out(f"   existing entities: {', '.join(existing)}")
    entity = ask("4) Entity (business object) this belongs to", _slug(intent))

    use_existing = False
    table = ""
    column = ""
    aggregation = ""
    date_column = ""

    if db_tables:
        use_existing_ans = ask("5) Do you want to map this question to an existing database table? (y/n)", "y").lower()
        use_existing = use_existing_ans in {"y", "yes"}

    if use_existing and db_tables:
        out("\n   Available tables:")
        for idx, tbl in enumerate(db_tables, 1):
            out(f"     {idx}) {tbl}")
        
        table_choice = ""
        while not table_choice:
            ans = ask("   Choose a table (number or name)", db_tables[0])
            if ans.isdigit():
                idx = int(ans) - 1
                if 0 <= idx < len(db_tables):
                    table_choice = db_tables[idx]
            elif ans in db_tables:
                table_choice = ans
            else:
                confirm = ask(f"   Table '{ans}' does not exist in the database. Use this custom table name anyway? (y/n)", "n").lower()
                if confirm in {"y", "yes"}:
                    table_choice = ans
        
        table = table_choice

        # Get columns
        db_columns = []
        if inspector:
            try:
                db_columns = [col["name"] for col in inspector.get_columns(table)]
            except Exception:
                pass
        
        # Column selection
        if db_columns:
            out(f"\n   Available columns in '{table}':")
            for idx, col_name in enumerate(db_columns, 1):
                out(f"     {idx}) {col_name}")
            
            col_choice = ""
            default_col = "id" if "id" in db_columns else db_columns[0]
            while not col_choice:
                ans = ask("6) Choose column to aggregate (number or name)", default_col)
                if ans.isdigit():
                    idx = int(ans) - 1
                    if 0 <= idx < len(db_columns):
                        col_choice = db_columns[idx]
                elif ans in db_columns:
                    col_choice = ans
                else:
                    confirm = ask(f"   Column '{ans}' does not exist in table '{table}'. Use this custom column anyway? (y/n)", "n").lower()
                    if confirm in {"y", "yes"}:
                        col_choice = ans
            column = col_choice
        else:
            column = ask("6) Column to aggregate (for COUNT use the id/name column)", "id")

        # Aggregation selection
        out("\n   Available aggregations:")
        for idx, agg in enumerate(_AGGREGATIONS, 1):
            out(f"     {idx}) {agg}")
        agg_choice = ""
        while not agg_choice:
            ans = ask("7) Choose aggregation (number or name)", "COUNT").upper()
            if ans.isdigit():
                idx = int(ans) - 1
                if 0 <= idx < len(_AGGREGATIONS):
                    agg_choice = _AGGREGATIONS[idx]
            elif ans in _AGGREGATIONS:
                agg_choice = ans
            if not agg_choice:
                out(f"   Invalid choice. Please choose from: {', '.join(_AGGREGATIONS)}")
        aggregation = agg_choice

        # Date column selection
        if db_columns:
            date_default = "created_at" if "created_at" in db_columns else None
            if not date_default:
                date_cols = [c for c in db_columns if any(x in c.lower() for x in ["date", "time", "at", "stamp"])]
                if date_cols:
                    date_default = date_cols[0]
            if not date_default:
                date_default = db_columns[-1]

            out(f"\n   Available columns for date filter in '{table}':")
            for idx, col_name in enumerate(db_columns, 1):
                out(f"     {idx}) {col_name}")

            date_choice = ""
            while not date_choice:
                ans = ask("8) Choose date column for time filter (number or name)", date_default)
                if ans.isdigit():
                    idx = int(ans) - 1
                    if 0 <= idx < len(db_columns):
                        date_choice = db_columns[idx]
                elif ans in db_columns:
                    date_choice = ans
                else:
                    confirm = ask(f"   Column '{ans}' does not exist in table '{table}'. Use this custom date column anyway? (y/n)", "n").lower()
                    if confirm in {"y", "yes"}:
                        date_choice = ans
            date_column = date_choice
        else:
            date_column = ask("8) Date column used for the time filter", "created_at")

    else:
        # Fallback to manual prompts
        default_table = _entity_table(cfg, entity) or entity
        table = ask("5) Database table name", default_table)
        column = ask("6) Column to aggregate (for COUNT use the id/name column)", "id")
        
        aggregation = ask(f"7) Aggregation {('/'.join(_AGGREGATIONS))}", "COUNT").upper()
        while aggregation not in _AGGREGATIONS:
            aggregation = ask(f"   choose one of {('/'.join(_AGGREGATIONS))}", "COUNT").upper()
            
        date_default = _entity_date_column(cfg, entity) or "created_at"
        date_column = ask("8) Date column used for the time filter", date_default)

    fmt_default = "currency" if aggregation in {"SUM", "AVG"} else "number"
    value_format = ask(f"9) Value format {('/'.join(_VALUE_FORMATS))}", fmt_default)
    while value_format not in _VALUE_FORMATS:
        value_format = ask(f"   choose one of {('/'.join(_VALUE_FORMATS))}", fmt_default)

    metric = _slug(intent)
    out("   wording placeholders: {value} (the number), {period} (e.g. 'this month'),"
        " {period_possessive} (e.g. \"month's\")")
    template = ask("10) Answer sentence",
                   f"The {metric.replace('_', ' ')} {{period}} is {{value}}.")

    periods_default = ",".join(detected or list(known_periods.keys()) or
                              ["today", "this_week", "this_month"])
    periods = [p.strip() for p in ask("11) Allowed time periods (comma-separated)",
                                      periods_default).split(",") if p.strip()]

    roles = [r.strip() for r in ask("12) Roles allowed to ask it (comma-separated)",
                                    "admin").split(",") if r.strip()]

    return QuestionSpec(
        intent=intent, patterns=patterns, entity=entity, metric=metric,
        table=table, column=column, aggregation=aggregation, template=template,
        value_format=value_format, date_column=date_column, periods=periods, roles=roles,
        description=f"{question}",
    )


def _existing_entities(cfg: ConfigStore) -> list[str]:
    d = cfg.base_dir / "semantic" / "entities"
    return sorted(p.stem for p in d.glob("*.yaml")) if d.is_dir() else []


def _entity_table(cfg: ConfigStore, entity: str) -> str | None:
    try:
        ent = cfg.semantic_entity(entity)
    except FileNotFoundError:
        return None
    metrics = ent.get("metrics", [])
    mappings = cfg.schema_mappings().get("metrics", {})
    for m in metrics:
        if m in mappings:
            return mappings[m].get("table")
    return None


def _entity_date_column(cfg: ConfigStore, entity: str) -> str | None:
    table = _entity_table(cfg, entity)
    if table is None:
        return None
    dim = cfg.schema_mappings().get("dimensions", {}).get("period", {})
    return dim.get("column") if dim.get("table") == table else None


def main(cfg: ConfigStore | None = None) -> int:
    cfg = cfg or default_config
    spec = collect_spec(cfg)

    print("\nReview:")
    for k, v in vars(spec).items():
        print(f"  {k:12} {v}")
    if input("\nWrite these changes? [y/N]: ").strip().lower() not in {"y", "yes"}:
        print("Aborted — no files changed.")
        return 1

    try:
        changes = apply_spec(spec, cfg.base_dir)
    except ValueError as exc:
        print(f"\nNot written: {exc}")
        return 1
    for c in changes:
        print(f"  {c}")

    cfg.reload()  # re-read the files we just wrote
    errors, warnings = run_checks(cfg)
    for w in warnings:
        print(f"WARN  {w}")
    for e in errors:
        print(f"ERROR {e}")

    print(
        f"\nNext steps:\n"
        f"  - Make sure table '{spec.table}' exists with column '{spec.column}'"
        f" and date column '{spec.date_column}'.\n"
        f"  - Restart the server: uvicorn backend.main:app --port 8080\n"
        f"  - Ask: \"{spec.description}\""
    )
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
