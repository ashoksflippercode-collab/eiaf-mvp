"""Layer 3 — Orchestration Layer (PRD §3 Layer 3).

Maps an intent to the business service call to make, via a deterministic lookup
table (NO dynamic reasoning for MVP). It validates that the resolved
entity/metric pair is actually registered in the Semantic Layer (§3.4) and fails
fast with ENTITY_NOT_REGISTERED rather than letting Layer 4 discover the gap.

Contract:
    in : {"intent": "sales_amount", "period": "this_week"}
    out: {"entity": "sales", "metric": "total_sales", "filters": {"period": "this_week"}}
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from backend.config_loader import ConfigStore, config as default_config
from backend.envelope import Envelope
from backend.errors import ErrorCode, LayerError
from backend.layers.base import Layer


class _OrchestrationInput(BaseModel):
    intent: str
    period: str
    extracted: dict[str, Any] = {}


class OrchestrationLayer(Layer):
    name = "orchestration"

    def __init__(self, config: ConfigStore | None = None) -> None:
        self._config = config or default_config

    def handle(self, envelope: Envelope) -> dict[str, Any]:
        data = self.parse(_OrchestrationInput, envelope.payload)

        mapping = self._config.orchestration()["intents"].get(data.intent)
        if mapping is None:
            raise LayerError(
                ErrorCode.ENTITY_NOT_REGISTERED,
                f"No business mapping is configured for intent '{data.intent}'.",
            )

        entity, metric = mapping["entity"], mapping["metric"]
        self._assert_registered(entity, metric)

        # Build Unified Semantic Query Schema (USQS)
        select_metrics = [metric] if metric else []
        select_dims = []
        filters = []
        sorts = []
        limit = None

        _PERIOD_AWARE_INTENTS = {
            "failed_calibrations", "torque_not_submitted",
            "equipment_issues_reported", "most_reported_equipment",
            "facility_log_by_store",
        }
        if data.period and data.intent in _PERIOD_AWARE_INTENTS:
            filters.append({
                "field": "period",
                "operator": "EQUALS",
                "value": data.period
            })

        extracted = data.extracted

        if data.intent == "get_store_info":
            select_dims = [
                "store_name", "store_address", "store_city",
                "store_phone", "store_email", "manager_name", "manager_email",
            ]
            filters = self._store_id_filter(extracted, "store_id")

        elif data.intent == "get_store_manager":
            select_dims = ["store_name", "manager_name", "manager_email"]
            filters = self._store_id_filter(extracted, "store_id")

        elif data.intent == "list_employees_by_store":
            select_dims = ["first_name", "last_name", "job_code", "employee_phone"]
            filters = self._store_id_filter(extracted, "roster_store_id")
            filters.append({"field": "employee_status", "operator": "EQUALS", "value": 1})

        elif data.intent == "failed_calibrations":
            select_dims = [
                "calibration_store_id", "calibration_tech",
                "wrench_serial_number", "wrench_torque_reading",
            ]
            filters.append({"field": "wrench_result", "operator": "EQUALS", "value": "FAIL"})

        elif data.intent == "torque_not_submitted":
            # The Data Layer resolves this via an anti-join against `stores`
            # (strategy: anti_join in the schema registry) — no dimension
            # select needed, just the metric + period (already appended above).
            pass

        elif data.intent == "equipment_issues_reported":
            select_dims = [
                "equipment_store_id", "equipment_name", "check_name", "issue_description",
            ]
            filters.append({"field": "check_status", "operator": "EQUALS", "value": "Report Issue"})

        elif data.intent == "most_reported_equipment":
            select_metrics = ["issue_count"]
            select_dims = ["equipment_name"]
            filters.append({"field": "check_status", "operator": "EQUALS", "value": "Report Issue"})
            sorts.append({"field": "issue_count", "direction": "DESC"})
            limit = extracted.get("limit", 5)

        elif data.intent == "facility_log_by_store":
            select_dims = ["facility_date_completed", "facility_service_provider", "facility_notes"]
            filters = self._store_id_filter(extracted, "facility_store_id") + filters

        return {
            "entity": entity,
            "select": {
                "metrics": select_metrics,
                "dimensions": select_dims
            },
            "filters": filters,
            "sort": sorts,
            "limit": limit
        }

    @staticmethod
    def _store_id_filter(extracted: dict[str, Any], field: str) -> list[dict[str, Any]]:
        store_id = extracted.get("store_id")
        if store_id is None:
            return []
        return [{"field": field, "operator": "EQUALS", "value": store_id}]

    def _assert_registered(self, entity: str, metric: str) -> None:
        """Fail fast unless `entity` is registered and declares `metric` (§3.4)."""
        try:
            entity_def = self._config.semantic_entity(entity)
        except FileNotFoundError as exc:
            raise LayerError(
                ErrorCode.ENTITY_NOT_REGISTERED,
                f"Entity '{entity}' is not registered in the Semantic Layer.",
            ) from exc

        if metric and metric not in entity_def.get("metrics", []):
            raise LayerError(
                ErrorCode.ENTITY_NOT_REGISTERED,
                f"Metric '{metric}' is not registered for entity '{entity}'.",
            )
