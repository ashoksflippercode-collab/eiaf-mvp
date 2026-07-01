"""Data Layer unit tests (PRD §3 Layer 6)."""

from datetime import date

import pytest
from sqlalchemy import create_engine

from backend.config_loader import config
from backend.envelope import Envelope
from backend.layers.data import DataLayer


def _run(engine, frozen_today, period: str) -> Envelope:
    payload = {"entity": "sales", "metric": "total_sales", "filters": {"period": period}}
    env = Envelope.create(user_id="u", role="admin", payload=payload)
    return DataLayer(config, engine=engine, today=frozen_today).process(env)


def test_this_week_matches_seeded_total(engine, frozen_today):
    out = _run(engine, frozen_today, "this_week")
    assert out.ok
    assert out.payload["result"]["total_sales"] == 63000


def test_period_windows_are_distinct(engine, frozen_today):
    assert _run(engine, frozen_today, "today").payload["result"]["total_sales"] == 20000
    assert _run(engine, frozen_today, "this_month").payload["result"]["total_sales"] == 93000


def test_db_failure_is_masked_as_data_layer_failure(frozen_today):
    # Point at an empty DB with no `customers` table -> SQLAlchemy error, which
    # must surface as DATA_LAYER_FAILURE with no raw error leaking (§6.4).
    empty = create_engine("sqlite://")  # in-memory, unseeded
    out = _run(empty, frozen_today, "this_week")
    assert not out.ok
    assert out.error.code == "DATA_LAYER_FAILURE"
    assert "customers" not in out.error.message.lower()  # no schema/SQL leakage
