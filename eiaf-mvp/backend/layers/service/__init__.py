"""Layer 5 — Service Layer: Security & Governance (PRD §3 Layer 5).

The most security-critical layer. It enforces authorization, defense-in-depth
validation, rate limits, and audit logging on the validated business query.

TRUST BOUNDARY (§3 Layer 5, §7 Q2)
----------------------------------
MVP assumes the caller is already authenticated upstream (e.g. a session token
validated by the API gateway / front-end). This layer therefore TRUSTS the
`user_id` and `role` carried in the envelope — but only because they are expected
to be set by a trusted upstream component. If the entry point is ever exposed
without that upstream guarantee, authentication MUST be added before this layer.

Contract (pass-through on approval):
    in/out payload: {"entity": "sales", "metric": "total_sales",
                     "filters": {"period": "this_week"}}
    plus identity (user_id, role) read from the envelope.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, model_validator

from backend.audit import AuditLogger
from backend.config_loader import ConfigStore, config as default_config
from backend.envelope import Envelope
from backend.errors import ErrorCode, LayerError
from backend.layers.base import Layer
from backend.layers.semantic import SemanticLayer
from backend.layers.service.rate_limiter import RateLimiter


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


class _ServiceInput(BaseModel):
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


class ServiceLayer(Layer):
    name = "service"

    def __init__(
        self,
        config: ConfigStore | None = None,
        audit: AuditLogger | None = None,
        rate_limiter: RateLimiter | None = None,
    ) -> None:
        self._config = config or default_config
        self._audit = audit or AuditLogger(self._config.settings()["audit"]["log_path"])
        self._semantic = SemanticLayer(self._config)  # defense-in-depth re-validation
        if rate_limiter is None:
            rl = self._config.settings()["rate_limit"]
            rate_limiter = RateLimiter(rl["max_requests"], rl["window_seconds"])
        self._rate_limiter = rate_limiter

    def handle(self, envelope: Envelope) -> dict[str, Any]:
        data = self.parse(_ServiceInput, envelope.payload)
        entity = data.entity

        # 1. Authorization (RBAC) — a real config lookup, never a bypass.
        if not self._role_allows(envelope.role, entity):
            self._reject(
                envelope, data,
                ErrorCode.RBAC_DENIED,
                f"Role '{envelope.role}' is not permitted to access entity '{entity}'.",
            )

        # 2. Defense in depth — re-validate against the same semantic config (§3 L5).
        try:
            self._semantic.validate(data)
        except LayerError as exc:
            self._reject(envelope, data, exc.code, exc.message)

        # 3. Query/rate limits — enforced per user even with a single role.
        if not self._rate_limiter.check_and_consume(envelope.user_id):
            self._reject(
                envelope, data,
                ErrorCode.RATE_LIMIT_EXCEEDED,
                "Rate limit exceeded. Please retry shortly.",
            )

        # Approved — record and pass the query through unchanged.
        self._audit.record(
            request_id=envelope.request_id,
            user_id=envelope.user_id,
            role=envelope.role,
            entity=entity,
            metric=", ".join(data.select.metrics),
            filters={f.field: f.value for f in data.filters},
            decision="approved",
        )
        if not data.select.dimensions and len(data.select.metrics) == 1 and len(data.filters) == 1 and data.filters[0].field == "period":
            return {
                "entity": data.entity,
                "metric": data.select.metrics[0],
                "filters": {"period": data.filters[0].value}
            }
        return data.model_dump()

    # --- helpers ---------------------------------------------------------------
    def _role_allows(self, role: str, entity: str) -> bool:
        role_def = self._config.roles().get("roles", {}).get(role)
        if role_def is None:
            return False
        return entity in role_def.get("allowed_entities", [])

    def _reject(
        self,
        envelope: Envelope,
        data: _ServiceInput,
        code: ErrorCode,
        message: str,
    ) -> None:
        """Audit the rejection (with reason code) and halt the pipeline (§6.3)."""
        self._audit.record(
            request_id=envelope.request_id,
            user_id=envelope.user_id,
            role=envelope.role,
            entity=data.entity,
            metric=", ".join(data.select.metrics),
            filters={f.field: f.value for f in data.filters},
            decision="rejected",
            reason=f"{code.value}: {message}",
        )
        raise LayerError(code, message)
