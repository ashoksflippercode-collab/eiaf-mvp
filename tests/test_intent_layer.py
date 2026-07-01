"""Intent Layer unit tests (PRD §3 Layer 2, acceptance §8.2)."""

from backend.config_loader import config
from backend.envelope import Envelope
from backend.layers.intent import IntentLayer


def _run(text: str) -> Envelope:
    env = Envelope.create(user_id="u", role="admin", payload={"text": text})
    return IntentLayer(config).process(env)


def test_recognizes_canonical_question():
    out = _run("How much sales did I do this week?")
    assert out.ok
    assert out.payload == {"intent": "sales_amount", "period": "this_week"}


def test_recognizes_phrasing_variant():
    # §8.2 — a minor phrasing variant must be correctly classified, not dropped.
    out = _run("What were my sales this week?")
    assert out.ok
    assert out.payload["intent"] == "sales_amount"
    assert out.payload["period"] == "this_week"


def test_recognizes_today_and_month():
    assert _run("sales today").payload["period"] == "today"
    assert _run("revenue this month").payload["period"] == "this_month"


def test_unrelated_question_is_not_found():
    out = _run("What is the weather like today?")
    assert not out.ok
    assert out.error.code == "INTENT_NOT_FOUND"


def test_known_intent_without_period_is_not_found():
    # Period is required and must not be guessed.
    out = _run("How much sales did I do?")
    assert not out.ok
    assert out.error.code == "INTENT_NOT_FOUND"
