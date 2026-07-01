"""Layer 1 — Voice Layer / STT (PRD §3 Layer 1) — Tier 2 / Stretch.

NOT wired into the Tier-1 (text-only) pipeline. Provided as a contract-complete
stub so the architecture is whole and STT can be added without reshaping the
pipeline. It converts an audio payload to text and emits the shared envelope with
`payload.text` populated; on failed/low-confidence transcription it returns
status "error" with code STT_LOW_CONFIDENCE and does not forward to Layer 2.

Inject a `transcriber(audio) -> (text, confidence)` callable to enable real STT.
Future (not MVP): streaming STT, barge-in, voice activity detection.
"""

from __future__ import annotations

from typing import Any, Callable, Protocol

from pydantic import BaseModel

from backend.envelope import Envelope
from backend.errors import ErrorCode, LayerError
from backend.layers.base import Layer

# Minimum transcription confidence to accept and forward downstream.
_MIN_CONFIDENCE = 0.6


class Transcriber(Protocol):
    def __call__(self, audio: Any) -> tuple[str, float]:  # (text, confidence)
        ...


class _VoiceInput(BaseModel):
    # Reference to audio (path/handle/bytes); opaque to this layer.
    audio: Any


class VoiceLayer(Layer):
    name = "voice"

    def __init__(self, transcriber: Transcriber | None = None) -> None:
        self._transcriber = transcriber

    def handle(self, envelope: Envelope) -> dict[str, Any]:
        data = self.parse(_VoiceInput, envelope.payload)
        if self._transcriber is None:
            raise LayerError(
                ErrorCode.STT_LOW_CONFIDENCE,
                "Voice input (STT) is not enabled in this MVP build (Tier 2).",
            )
        text, confidence = self._transcriber(data.audio)
        if not text or confidence < _MIN_CONFIDENCE:
            raise LayerError(
                ErrorCode.STT_LOW_CONFIDENCE,
                "Could not transcribe the audio with sufficient confidence.",
            )
        return {"text": text}
