"""Layer 8 — Text-to-Speech Layer (PRD §3 Layer 8) — Tier 2 / Stretch.

NOT wired into the Tier-1 (text-only) pipeline. Provided as a contract-complete
stub. It takes the Response Layer's text and produces an audio stream; out of
scope for Tier-1 acceptance, to be implemented only after Tier-1 sign-off.

Inject a `synthesizer(text) -> bytes` callable to enable real TTS.
"""

from __future__ import annotations

from typing import Any, Callable

from pydantic import BaseModel

from backend.envelope import Envelope
from backend.layers.base import Layer


class _TTSInput(BaseModel):
    text: str


class TTSLayer(Layer):
    name = "tts"

    def __init__(self, synthesizer: Callable[[str], bytes] | None = None) -> None:
        self._synthesizer = synthesizer

    def handle(self, envelope: Envelope) -> dict[str, Any]:
        data = self.parse(_TTSInput, envelope.payload)
        # When no synthesizer is configured, carry the text through unchanged with
        # an explicit null audio marker (Tier 2 not enabled) rather than failing.
        audio = self._synthesizer(data.text) if self._synthesizer else None
        return {"text": data.text, "audio": audio}
