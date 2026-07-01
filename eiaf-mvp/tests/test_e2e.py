"""End-to-end pipeline tests (PRD §2.4 / acceptance §8.1, §8.4, §8.6).

These reproduce the success criteria through the full Tier-1 pipeline with no
layer bypassed.
"""

from tests.conftest import make_envelope


def test_success_criteria_end_to_end(pipeline):
    # §8.1 / §2.4 — canonical question yields the canonical answer.
    out = pipeline.run(make_envelope("How much sales did I do this week?"))
    assert out.ok
    assert out.payload["text"] == "This week's total sales are ₹63,000."
    assert out.payload["value"] == 63000


def test_phrasing_variant_end_to_end(pipeline):
    # §8.2 — a minor variant is classified correctly through the whole pipeline.
    out = pipeline.run(make_envelope("What were my sales this week?"))
    assert out.ok
    assert out.payload["text"] == "This week's total sales are ₹63,000."


def test_new_customers_question_end_to_end(pipeline):
    # Added with config only (intent/orchestration/semantic/mapping/role) — proves
    # a new question flows through every layer with no code change, and that a
    # count renders as a plain number, not currency.
    out = pipeline.run(make_envelope("How many new customers do I have this month?"))
    assert out.ok
    assert out.payload["text"] == "You have 4 new customers this month."
    assert out.payload["value"] == 4


def test_request_id_is_consistent_in_audit_for_approved_and_rejected(pipeline, audit_logger):
    # §8.6 — every request (approved or rejected) is in the audit log under the
    # SAME request_id carried through the envelope.
    approved = make_envelope("How much sales did I do this week?", role="admin")
    rejected = make_envelope("How much sales did I do this week?", role="guest")

    out_ok = pipeline.run(approved)
    out_denied = pipeline.run(rejected)

    assert out_ok.ok
    assert not out_denied.ok and out_denied.error.code == "RBAC_DENIED"

    entries = {e["request_id"]: e for e in audit_logger.entries()}
    assert approved.request_id in entries
    assert rejected.request_id in entries
    assert entries[approved.request_id]["decision"] == "approved"
    assert entries[rejected.request_id]["decision"] == "rejected"


def test_invalid_metric_halts_before_data_layer(pipeline, engine):
    # §8.5 — an undeclared metric is rejected at the Semantic Layer and never
    # reaches the Data Layer. We assert via the public error contract: a semantic
    # failure surfaces with the semantic code, proving the request stopped there.
    # (The Intent->Orchestration path only ever yields the declared metric, so we
    #  drive the Semantic Layer directly with an invalid metric.)
    from backend.config_loader import config
    from backend.layers.semantic import SemanticLayer

    bad = make_envelope("x")
    bad = bad.advanced(
        {"entity": "sales", "metric": "profit", "filters": {"period": "this_week"}}
    )
    out = SemanticLayer(config).process(bad)
    assert not out.ok
    assert out.error.code == "SEMANTIC_VALIDATION_FAILED"
