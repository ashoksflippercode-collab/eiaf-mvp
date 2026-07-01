"""Orchestration Layer unit tests (PRD §3 Layer 3)."""

from backend.config_loader import config
from backend.envelope import Envelope
from backend.layers.orchestrator import OrchestrationLayer


def _run(payload: dict) -> Envelope:
    env = Envelope.create(user_id="u", role="admin", payload=payload)
    return OrchestrationLayer(config).process(env)


def test_maps_intent_to_entity_metric_and_filters():
    out = _run({"intent": "sales_amount", "period": "this_week"})
    assert out.ok
    assert out.payload == {
        "entity": "sales",
        "metric": "total_sales",
        "filters": {"period": "this_week"},
    }


def test_unknown_intent_fails_fast_as_not_registered():
    out = _run({"intent": "headcount", "period": "this_week"})
    assert not out.ok
    assert out.error.code == "ENTITY_NOT_REGISTERED"
