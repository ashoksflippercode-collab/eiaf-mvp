"""Semantic Layer unit tests (PRD §3 Layer 4, acceptance §8.5)."""

from backend.config_loader import config
from backend.envelope import Envelope
from backend.layers.semantic import SemanticLayer


def _run(payload: dict) -> Envelope:
    env = Envelope.create(user_id="u", role="admin", payload=payload)
    return SemanticLayer(config).process(env)


def test_valid_business_query_passes_through():
    payload = {"entity": "sales", "metric": "total_sales", "filters": {"period": "this_week"}}
    out = _run(payload)
    assert out.ok
    assert out.payload == payload


def test_undeclared_metric_is_rejected():
    # §8.5 — invalid metric stops here, never reaches the Data Layer.
    out = _run({"entity": "sales", "metric": "profit_margin", "filters": {"period": "this_week"}})
    assert not out.ok
    assert out.error.code == "SEMANTIC_VALIDATION_FAILED"


def test_undeclared_filter_is_rejected():
    out = _run({"entity": "sales", "metric": "total_sales", "filters": {"period": "this_year"}})
    assert not out.ok
    assert out.error.code == "SEMANTIC_VALIDATION_FAILED"
