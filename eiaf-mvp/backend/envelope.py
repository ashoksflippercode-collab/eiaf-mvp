"""The shared message envelope (PRD §3.0).

Every layer-to-layer call uses this single shape so layers stay swappable. The
`request_id` is generated once at the entry point and propagated unchanged
through all layers — it is the audit/correlation key (§6.3).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

from backend.errors import ErrorCode


class ErrorDetail(BaseModel):
    """Structured error object — the only way failures leave a layer (§6.4)."""

    code: str
    message: str


class Envelope(BaseModel):
    """The shared inter-layer envelope.

    `payload` accumulates the business context as the request flows through the
    pipeline (each layer reads the fields it needs and adds its own output). The
    identity and correlation fields stay constant end-to-end.
    """

    request_id: str
    timestamp: str  # ISO-8601, set once at the entry point
    user_id: str
    role: str
    payload: dict[str, Any] = Field(default_factory=dict)
    status: Literal["ok", "error"] = "ok"
    error: ErrorDetail | None = None

    @classmethod
    def create(
        cls,
        *,
        user_id: str,
        role: str,
        payload: dict[str, Any] | None = None,
    ) -> "Envelope":
        """Build the entry-point envelope, minting the correlation `request_id`."""
        return cls(
            request_id=str(uuid.uuid4()),
            timestamp=datetime.now(timezone.utc).isoformat(),
            user_id=user_id,
            role=role,
            payload=payload or {},
        )

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    def failed(self, code: ErrorCode, message: str) -> "Envelope":
        """Return a copy marked failed, preserving identity/correlation fields.

        The `payload` is carried through so the failing business context remains
        available for audit logging.
        """
        return self.model_copy(
            update={
                "status": "error",
                "error": ErrorDetail(code=code.value, message=message),
            }
        )

    def advanced(self, payload: dict[str, Any]) -> "Envelope":
        """Return a copy with the payload replaced by the next layer's output."""
        return self.model_copy(update={"payload": payload, "status": "ok", "error": None})
