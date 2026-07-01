"""Shared test fixtures.

Tests use the real YAML config but isolated, deterministic runtime state: a
freshly seeded temp SQLite DB, a fixed "today" so rolling windows are stable, a
temp audit log, and a generous rate limiter so unrelated tests never trip it.
"""

from __future__ import annotations

from datetime import date

import pytest

from backend.audit import AuditLogger
from backend.config_loader import config
from backend.database.mysql import build_engine
from backend.envelope import Envelope
from backend.layers.data import DataLayer
from backend.layers.intent import IntentLayer
from backend.layers.orchestrator import OrchestrationLayer
from backend.layers.response import ResponseLayer
from backend.layers.semantic import SemanticLayer
from backend.layers.service import ServiceLayer
from backend.layers.service.rate_limiter import RateLimiter
from backend.pipeline import Pipeline
from backend.seed import seed

# Fixed reference date so "this_week" / "this_month" windows are deterministic.
FROZEN_TODAY = date(2024, 6, 19)


@pytest.fixture
def frozen_today() -> date:
    return FROZEN_TODAY


@pytest.fixture
def engine(tmp_path):
    eng = build_engine(f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
    seed(engine=eng, today=FROZEN_TODAY)
    return eng


@pytest.fixture
def audit_logger(tmp_path) -> AuditLogger:
    return AuditLogger(tmp_path / "audit.jsonl")


@pytest.fixture
def rate_limiter() -> RateLimiter:
    return RateLimiter(max_requests=1000, window_seconds=60)


@pytest.fixture
def pipeline(engine, audit_logger, rate_limiter, frozen_today) -> Pipeline:
    return Pipeline(
        [
            IntentLayer(config),
            OrchestrationLayer(config),
            SemanticLayer(config),
            ServiceLayer(config, audit=audit_logger, rate_limiter=rate_limiter),
            DataLayer(config, engine=engine, today=frozen_today),
            ResponseLayer(config),
        ]
    )


def make_envelope(text: str, *, role: str = "admin", user_id: str = "admin-user") -> Envelope:
    return Envelope.create(user_id=user_id, role=role, payload={"text": text})
