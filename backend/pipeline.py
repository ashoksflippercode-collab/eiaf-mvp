"""The layer pipeline (PRD §3).

Runs layers in strict order, propagating one shared envelope. No layer is ever
bypassed: layers execute in sequence and the run halts at the first layer that
returns an error envelope (downstream layers are not reached). The same
`request_id` flows through unchanged for end-to-end auditability (§6.3).
"""

from __future__ import annotations

from backend.config_loader import ConfigStore, config as default_config
from backend.envelope import Envelope
from backend.layers.base import Layer
from backend.layers.data import DataLayer
from backend.layers.intent import IntentLayer
from backend.layers.orchestrator import OrchestrationLayer
from backend.layers.response import ResponseLayer
from backend.layers.semantic import SemanticLayer
from backend.layers.service import ServiceLayer


class Pipeline:
    def __init__(self, layers: list[Layer]) -> None:
        self._layers = layers

    def run(self, envelope: Envelope) -> Envelope:
        for layer in self._layers:
            envelope = layer.process(envelope)
            if not envelope.ok:
                return envelope  # halt — never bypass a downstream layer past an error
        return envelope


def build_tier1_pipeline(config: ConfigStore | None = None) -> Pipeline:
    """Construct the Tier-1 (text-in -> text-out) pipeline.

    Layer instances are created once and reused so stateful concerns (e.g. the
    Service Layer's rate limiter) persist across requests in the process.
    """
    cfg = config or default_config
    return Pipeline(
        [
            IntentLayer(cfg),
            OrchestrationLayer(cfg),
            SemanticLayer(cfg),
            ServiceLayer(cfg),
            DataLayer(cfg),
            ResponseLayer(cfg),
        ]
    )
