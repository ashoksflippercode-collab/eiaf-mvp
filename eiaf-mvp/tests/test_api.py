"""HTTP entry-point tests (PRD §3.0, §5).

Exercises the FastAPI surface: the entry point mints the request_id, returns the
shared envelope, and conveys failures inside the envelope (not as HTTP 5xx).
Uses the default (file) database, seeded for the current day so the rolling
7-day window equals ₹63,000.
"""

from fastapi.testclient import TestClient

from backend.database.mysql import get_engine
from backend.main import app
from backend.seed import seed


def setup_module() -> None:
    # Seed the default DB the app queries (relative to real "today").
    seed(engine=get_engine())


client = TestClient(app)


def test_ask_returns_envelope_with_answer():
    res = client.post("/ask", json={"text": "How much sales did I do this week?"})
    assert res.status_code == 200
    env = res.json()
    assert env["status"] == "ok"
    assert env["payload"]["text"] == "This week's total sales are ₹63,000."
    assert env["request_id"]  # correlation key minted at the entry point


def test_non_admin_is_rejected_in_envelope_not_http_error():
    res = client.post(
        "/ask",
        json={"text": "How much sales did I do this week?", "user_id": "g", "role": "guest"},
    )
    assert res.status_code == 200  # structured error contract (§6.4), not 5xx
    env = res.json()
    assert env["status"] == "error"
    assert env["error"]["code"] == "RBAC_DENIED"


def test_unrecognized_question_returns_intent_not_found():
    res = client.post("/ask", json={"text": "Tell me a joke"})
    env = res.json()
    assert env["status"] == "error"
    assert env["error"]["code"] == "INTENT_NOT_FOUND"


def test_health():
    assert client.get("/health").json()["status"] == "ok"
