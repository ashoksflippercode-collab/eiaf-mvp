"""Config consistency checker (authoring aid — NOT part of the request path).

Adding a question is config-only (PRD §6.2), but the values are spread across
several layer files and a few names must match exactly. This tool verifies every
cross-reference and prints, in plain language, what is missing or misspelled and
*which file to fix* — so a non-engineer can edit, run one command, and get a
checklist instead of hunting a runtime rejection.

Usage:
    python -m backend.check_config        # checks the live config, exits 1 on error
"""

from __future__ import annotations

import sys

from backend.config_loader import ConfigStore, config as default_config

# Mirror the whitelists enforced at runtime so a bad value is caught here first.
_AGGREGATIONS = {"SUM", "COUNT", "AVG", "MIN", "MAX"}
_VALUE_FORMATS = {"currency", "number"}


def run_checks(cfg: ConfigStore) -> tuple[list[str], list[str]]:
    """Return (errors, warnings). Errors break a question; warnings are advisories.

    Each message names the offending value AND the file to edit.
    """
    errors: list[str] = []
    warnings: list[str] = []

    orch = cfg.orchestration().get("intents", {})
    patterns = cfg.intent_patterns()
    pattern_intents = {i["name"] for i in patterns.get("intents", [])}
    pattern_periods = {p["value"] for p in patterns.get("periods", [])}
    mappings = cfg.schema_mappings()
    metric_maps = mappings.get("metrics", {})
    settings_periods = cfg.settings().get("periods", {})
    response = cfg.response_templates()
    response_metrics = response.get("metrics", {})
    response_labels = response.get("period_labels", {})
    roles = cfg.roles().get("roles", {})

    # Schema registry must define how a period is constrained physically.
    if "period" not in mappings.get("dimensions", {}):
        errors.append(
            "schema_registry/mappings.yaml: no `dimensions.period` — the Data "
            "Layer cannot apply any time filter."
        )

    # --- one pass per answerable question (an orchestration mapping) -----------
    for intent, m in orch.items():
        where = f"orchestration.yaml intent '{intent}'"
        entity, metric = m.get("entity"), m.get("metric")
        if not entity or not metric:
            errors.append(f"{where}: must set both `entity` and `metric`.")
            continue

        # 1. The question must be recognizable (phrases exist).
        if intent not in pattern_intents:
            errors.append(
                f"{where}: no matching intent in intent_patterns.yaml, so the "
                f"question can never be recognized. Add an intent named '{intent}' "
                f"with `patterns:` there."
            )

        # 2. The entity must be declared in the Semantic Layer.
        try:
            entity_def = cfg.semantic_entity(entity)
        except FileNotFoundError:
            errors.append(
                f"{where}: entity '{entity}' has no semantic definition. Create "
                f"semantic/entities/{entity}.yaml declaring its metrics + filters."
            )
            entity_def = None

        # 3. The metric must be declared for that entity.
        if entity_def is not None and metric not in entity_def.get("metrics", []):
            errors.append(
                f"{where}: metric '{metric}' is not listed under `metrics:` in "
                f"semantic/entities/{entity}.yaml."
            )

        # 4. The metric must be mapped to a column + a whitelisted aggregation.
        if metric not in metric_maps:
            errors.append(
                f"{where}: metric '{metric}' has no entry under `metrics:` in "
                f"schema_registry/mappings.yaml (needs table/column/aggregation)."
            )
        else:
            agg = str(metric_maps[metric].get("aggregation", "")).upper()
            if agg not in _AGGREGATIONS:
                errors.append(
                    f"schema_registry/mappings.yaml: metric '{metric}' has "
                    f"aggregation '{agg or '(missing)'}', not one of "
                    f"{sorted(_AGGREGATIONS)}."
                )

        # 5. The metric must have wording + a value format.
        if metric not in response_metrics:
            errors.append(
                f"{where}: metric '{metric}' has no entry under `metrics:` in "
                f"response_templates.yaml (needs a `template` and `format`)."
            )
        else:
            fmt = response_metrics[metric].get("format")
            if fmt not in _VALUE_FORMATS:
                errors.append(
                    f"response_templates.yaml: metric '{metric}' has format "
                    f"'{fmt}', not one of {sorted(_VALUE_FORMATS)}."
                )

        # 6. Some role must grant the entity, or every request is RBAC_DENIED.
        if not any(entity in r.get("allowed_entities", []) for r in roles.values()):
            warnings.append(
                f"entity '{entity}' is not granted to any role in roles.yaml — "
                f"requests for it will be rejected with RBAC_DENIED."
            )

        # 7. Every allowed period needs a window (settings) and a label (response).
        if entity_def is not None:
            for period in entity_def.get("filters", {}).get("period", []):
                if period not in settings_periods:
                    errors.append(
                        f"semantic/entities/{entity}.yaml allows period '{period}' "
                        f"but settings.yaml defines no window for it."
                    )
                if period not in response_labels:
                    errors.append(
                        f"semantic/entities/{entity}.yaml allows period '{period}' "
                        f"but response_templates.yaml has no label for it."
                    )

    # --- advisories (won't break a question, but worth knowing) ----------------
    for intent in pattern_intents:
        if intent not in orch:
            warnings.append(
                f"intent '{intent}' in intent_patterns.yaml has no orchestration "
                f"mapping — it is recognized but cannot be answered."
            )
    for period in pattern_periods:
        if period not in settings_periods:
            warnings.append(
                f"period '{period}' in intent_patterns.yaml has no window in "
                f"settings.yaml — it is recognized but cannot be applied."
            )

    return errors, warnings


def main(cfg: ConfigStore | None = None) -> int:
    cfg = cfg or default_config
    errors, warnings = run_checks(cfg)

    for w in warnings:
        print(f"WARN  {w}")
    for e in errors:
        print(f"ERROR {e}")

    n_questions = len(cfg.orchestration().get("intents", {}))
    if errors:
        print(f"\n{len(errors)} error(s), {len(warnings)} warning(s). Fix the errors above.")
        return 1
    print(f"\nOK: {n_questions} question(s) wired consistently across all layers"
          f"{f' ({len(warnings)} warning(s))' if warnings else ''}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
