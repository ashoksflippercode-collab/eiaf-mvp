"""Tests for the architecture improvements (Problem 1, 2, 3, and 4)."""

from __future__ import annotations

from datetime import date, timedelta
import pytest

from backend.config_loader import config
from backend.envelope import Envelope
from backend.layers.intent import IntentLayer
from backend.layers.orchestrator import OrchestrationLayer
from backend.layers.semantic import SemanticLayer
from backend.layers.service import ServiceLayer
from backend.layers.data import DataLayer
from backend.layers.response import ResponseLayer
from backend.pipeline import Pipeline
from backend.audit import AuditLogger
from backend.layers.service.rate_limiter import RateLimiter
from backend.database.mysql import get_engine
from backend.seed import seed

FROZEN_TODAY = date(2026, 6, 27)


@pytest.fixture(autouse=True)
def setup_db():
    engine = get_engine()
    seed(engine=engine, today=FROZEN_TODAY, cfg=config)


def _run_pipeline(text: str) -> Envelope:
    env = Envelope.create(user_id="admin-user", role="admin", payload={"text": text})
    pipeline = Pipeline([
        IntentLayer(config),
        OrchestrationLayer(config),
        SemanticLayer(config),
        ServiceLayer(config, audit=AuditLogger(config.base_dir / "audit_log.jsonl"),
                     rate_limiter=RateLimiter(1000, 60)),
        DataLayer(config, today=FROZEN_TODAY),
        ResponseLayer(config),
    ])
    return pipeline.run(env)


def test_garbage_intent_is_rejected():
    # Problem 4: Garbage detection heuristic
    out = _run_pipeline("sdfsdfsdfsdf sales dsfsdfsdfsdfsdfs this week")
    assert not out.ok
    assert out.error.code == "INTENT_NOT_FOUND"


def test_top_customers_query():
    # Problem 1 & 3: Top N customers ranking query
    out = _run_pipeline("Who are the top 3 customers by purchase amount?")
    assert out.ok
    text = out.payload["text"]
    assert "Vijay Rao" in text
    assert "Meena Iyer" in text
    assert "Asha Verma" in text
    assert "₹30,000" in text


def test_highest_sales_day_query():
    # Problem 1 & 3: Highest sales day query
    out = _run_pipeline("Which day had the highest sales?")
    assert out.ok
    text = out.payload["text"]
    # Vijay Rao had 30000 on today - 15 days
    expected_day = (FROZEN_TODAY - timedelta(days=15)).isoformat()
    assert expected_day in text
    assert "₹30,000" in text


def test_customer_purchases_filter():
    # Problem 1, 2: Filter by dimension values
    out = _run_pipeline("Show all purchases made by Asha Verma")
    assert out.ok
    text = out.payload["text"]
    assert "Asha Verma" in text
    assert "Widget" in text
    assert "₹20,000" in text


def test_high_value_purchases_filter():
    # Problem 1, 3: Filter by threshold comparison
    out = _run_pipeline("Which customers made purchases above 20000?")
    assert out.ok
    text = out.payload["text"]
    assert "Vijay Rao" in text
    assert "Meena Iyer" in text
    # Asha Verma (20000) is NOT above 20000 (strictly greater)
    assert "Asha Verma" not in text


def test_average_purchase_per_customer():
    # Problem 1: Average purchase per customer
    out = _run_pipeline("What is the average purchase amount per customer?")
    assert out.ok
    text = out.payload["text"]
    assert "Asha Verma" in text
    assert "₹20,000" in text
