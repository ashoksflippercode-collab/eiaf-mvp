"""Shared error vocabulary (PRD §6.4).

`ErrorCode` is the closed set of structured error codes every layer may raise.
`LayerError` is the exception a layer raises to halt the pipeline with one of
these codes; `Layer.process()` (see layers/base.py) catches it and converts it
into the envelope's `error` object — a raw exception or DB message must never
reach the caller.

NOTE: this file was not included in the originally-uploaded zip ("only required
files" were attached) and has been reconstructed here from every `ErrorCode.*`
reference actually used across the layers, so the pipeline is importable and
runnable end-to-end. If your full repository already has a different/canonical
errors.py, prefer that one instead and discard this reconstruction.
"""

from __future__ import annotations

from enum import Enum


class ErrorCode(str, Enum):
    INTENT_NOT_FOUND = "INTENT_NOT_FOUND"
    ENTITY_NOT_REGISTERED = "ENTITY_NOT_REGISTERED"
    SEMANTIC_VALIDATION_FAILED = "SEMANTIC_VALIDATION_FAILED"
    RBAC_DENIED = "RBAC_DENIED"
    RATE_LIMIT_EXCEEDED = "RATE_LIMIT_EXCEEDED"
    DATA_LAYER_FAILURE = "DATA_LAYER_FAILURE"
    CONTRACT_VIOLATION = "CONTRACT_VIOLATION"
    STT_LOW_CONFIDENCE = "STT_LOW_CONFIDENCE"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class LayerError(Exception):
    """Raised by a layer to halt the pipeline with a structured (code, message)."""

    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
