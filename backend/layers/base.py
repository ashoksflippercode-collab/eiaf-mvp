"""Base class shared by every pipeline layer (PRD §3, §5, §6.1, §6.4).

A layer's only public method is `process(envelope) -> envelope`. Subclasses
implement `handle()`, which reads what it needs from the payload and returns the
payload it produces for the next layer. The base guarantees the cross-cutting
contract:

  * A failed envelope is passed straight through (a layer never processes an
    already-errored request — the pipeline also enforces this).
  * `LayerError` is translated into the envelope's structured `error` object.
  * Any unexpected exception is caught and converted to INTERNAL_ERROR, so a raw
    exception or stack trace can never reach the caller (§6.4).
  * `parse()` validates the inbound payload against a Pydantic contract at the
    boundary (defense-in-depth schema validation, §6.1).
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from backend.envelope import Envelope
from backend.errors import ErrorCode, LayerError

logger = logging.getLogger("eiaf.layer")

_Model = TypeVar("_Model", bound=BaseModel)


class Layer(ABC):
    """Abstract pipeline layer."""

    #: Human-readable layer name, used in logs and generic error messages.
    name: str = "layer"

    @abstractmethod
    def handle(self, envelope: Envelope) -> dict[str, Any]:
        """Process the request and return the payload for the next layer.

        Raise `LayerError` to halt the pipeline with a structured error.
        """

    def process(self, envelope: Envelope) -> Envelope:
        if not envelope.ok:
            # Defensive: the pipeline short-circuits on error, but never trust that.
            return envelope
        try:
            new_payload = self.handle(envelope)
            return envelope.advanced(new_payload)
        except LayerError as exc:
            return envelope.failed(exc.code, exc.message)
        except Exception:  # noqa: BLE001 — deliberately broad; we must not leak internals
            logger.exception("Unexpected failure in %s layer", self.name)
            return envelope.failed(
                ErrorCode.INTERNAL_ERROR,
                f"An internal error occurred in the {self.name} layer.",
            )

    # --- helpers ---------------------------------------------------------------
    @staticmethod
    def parse(model: type[_Model], payload: dict[str, Any]) -> _Model:
        """Validate `payload` against a Pydantic contract (§6.1 boundary check)."""
        try:
            return model.model_validate(payload)
        except ValidationError as exc:
            raise LayerError(
                ErrorCode.CONTRACT_VIOLATION,
                f"Payload did not satisfy the expected contract: {exc.error_count()} issue(s).",
            ) from exc
