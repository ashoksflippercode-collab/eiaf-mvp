"""Response Layer unit tests (PRD §3 Layer 7)."""

from backend.config_loader import config
from backend.envelope import Envelope
from backend.layers.response import ResponseLayer


def _run(period: str, amount) -> Envelope:
    payload = {
        "entity": "sales",
        "metric": "total_sales",
        "filters": {"period": period},
        "result": {"total_sales": amount},
    }
    env = Envelope.create(user_id="u", role="admin", payload=payload)
    return ResponseLayer(config).process(env)


def test_formats_week_answer_with_indian_currency():
    out = _run("this_week", 63000)
    assert out.ok
    assert out.payload["text"] == "This week's total sales are ₹63,000."


def test_period_label_comes_from_config():
    assert _run("today", 20000).payload["text"] == "This today's total sales are ₹20,000."
    assert _run("this_month", 93000).payload["text"] == "This month's total sales are ₹93,000."


def test_large_amount_uses_indian_grouping():
    assert _run("this_month", 100000).payload["text"] == "This month's total sales are ₹1,00,000."


def _run_count(period: str, count) -> Envelope:
    payload = {
        "entity": "customers",
        "metric": "new_customer_count",
        "filters": {"period": period},
        "result": {"new_customer_count": count},
    }
    env = Envelope.create(user_id="u", role="admin", payload=payload)
    return ResponseLayer(config).process(env)


def test_count_metric_uses_plain_number_not_currency():
    out = _run_count("this_month", 4)
    assert out.ok
    # A count renders as a plain number (no ₹) with its own wording.
    assert out.payload["text"] == "You have 4 new customers this month."
    assert out.payload["value"] == 4


def test_count_metric_uses_indian_grouping():
    assert _run_count("this_week", 100000).payload["text"] == (
        "You have 1,00,000 new customers this week."
    )
