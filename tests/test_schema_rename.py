"""Acceptance §8.3 — renaming a DB column requires changing ONLY the Schema
Registry mapping. No layer code and no other config changes; output is identical.
"""

import copy

from backend.audit import AuditLogger
from backend.config_loader import ConfigStore
from backend.database.mysql import build_engine
from backend.layers.data import DataLayer
from backend.layers.intent import IntentLayer
from backend.layers.orchestrator import OrchestrationLayer
from backend.layers.response import ResponseLayer
from backend.layers.semantic import SemanticLayer
from backend.layers.service import ServiceLayer
from backend.layers.service.rate_limiter import RateLimiter
from backend.pipeline import Pipeline
from backend.seed import seed

from tests.conftest import FROZEN_TODAY, make_envelope


def test_column_rename_is_a_single_file_change(tmp_path):
    # The ONLY change vs. production config: purchase_amount -> amount in the
    # Schema Registry. Everything else (semantic, orchestration, response) is the
    # real, unmodified config loaded from disk.
    store = ConfigStore()
    mappings = copy.deepcopy(store.schema_mappings())
    mappings["metrics"]["total_sales"]["column"] = "amount"
    store._cache["schema_registry/mappings.yaml"] = mappings  # simulate the edited file

    # Seed a DB whose value column is physically named `amount` (the DB-side rename).
    engine = build_engine(f"sqlite:///{(tmp_path / 'renamed.db').as_posix()}")
    seed(engine=engine, today=FROZEN_TODAY, cfg=store)

    pipeline = Pipeline(
        [
            IntentLayer(store),
            OrchestrationLayer(store),
            SemanticLayer(store),
            ServiceLayer(store, audit=AuditLogger(tmp_path / "audit.jsonl"),
                         rate_limiter=RateLimiter(1000, 60)),
            DataLayer(store, engine=engine, today=FROZEN_TODAY),
            ResponseLayer(store),
        ]
    )

    out = pipeline.run(make_envelope("How much sales did I do this week?"))
    assert out.ok
    assert out.payload["text"] == "This week's total sales are ₹63,000."
