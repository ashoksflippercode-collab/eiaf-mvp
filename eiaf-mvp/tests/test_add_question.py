"""Tests for the add-a-question wizard (authoring aid).

Drives the wizard exactly as a user would (simulated keystrokes), then proves the
generated config is consistent AND that the brand-new question — on a brand-new
table — answers correctly through the full pipeline with zero code changes.
"""

from __future__ import annotations

import shutil
from datetime import date

from sqlalchemy import Column, Date, Integer, MetaData, Table

from backend.add_question import apply_spec, collect_spec
from backend.check_config import run_checks
from backend.config_loader import ConfigStore, config
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
from backend.audit import AuditLogger

FROZEN_TODAY = date(2024, 6, 19)


def _config_copy(tmp_path) -> ConfigStore:
    for sub in ("config", "semantic", "schema_registry"):
        shutil.copytree(config.base_dir / sub, tmp_path / sub)
    # Clean up pre-existing orders config so the test wizard can add it cleanly
    import yaml
    ip_path = tmp_path / "config" / "intent_patterns.yaml"
    if ip_path.is_file():
        with ip_path.open("r", encoding="utf-8") as f:
            ip = yaml.safe_load(f)
        ip["intents"] = [i for i in ip.get("intents", []) if i.get("name") != "orders"]
        with ip_path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(ip, f)
    
    orch_path = tmp_path / "config" / "orchestration.yaml"
    if orch_path.is_file():
        with orch_path.open("r", encoding="utf-8") as f:
            orch = yaml.safe_load(f)
        if "orders" in orch.get("intents", {}):
            del orch["intents"]["orders"]
        with orch_path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(orch, f)

    mappings_path = tmp_path / "schema_registry" / "mappings.yaml"
    if mappings_path.is_file():
        with mappings_path.open("r", encoding="utf-8") as f:
            mappings = yaml.safe_load(f)
        if "orders" in mappings.get("metrics", {}):
            del mappings["metrics"]["orders"]
        with mappings_path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(mappings, f)

    response_path = tmp_path / "config" / "response_templates.yaml"
    if response_path.is_file():
        with response_path.open("r", encoding="utf-8") as f:
            response = yaml.safe_load(f)
        if "orders" in response.get("metrics", {}):
            del response["metrics"]["orders"]
        with response_path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(response, f)

    return ConfigStore(base_dir=tmp_path)


def _scripted_prompt(answers):
    it = iter(answers)

    def prompt(_label):
        return next(it)

    return prompt


# Simulated user session: "How many orders did we get today?" on a NEW orders table.
_ANSWERS = [
    "How many orders did we get today?",  # 1) question
    "",                                    # 2) keywords  -> default "orders"
    "",                                    # 3) slug      -> "orders"
    "",                                    # 4) entity    -> "orders"
    "n",                                   # 5) Do you want to map to an existing table? -> No
    "",                                    # 6) table     -> "orders"
    "",                                    # 7) column    -> "id"
    "",                                    # 8) aggregation -> COUNT
    "order_date",                          # 9) date column
    "",                                    # 10) format    -> number
    "We got {value} orders {period}.",    # 11) wording
    "",                                    # 12) periods  -> detected "today"
    "",                                    # 13) roles    -> admin
]


def test_wizard_writes_consistent_config(tmp_path):
    cfg = _config_copy(tmp_path)
    spec = collect_spec(cfg, prompt=_scripted_prompt(_ANSWERS), out=lambda *_: None)

    assert spec.intent == "orders"
    assert spec.patterns == [r"\borders\b"]
    assert spec.date_column == "order_date"

    apply_spec(spec, cfg.base_dir)
    cfg.reload()

    errors, _ = run_checks(cfg)
    assert errors == [], errors


def test_wizard_question_answers_through_pipeline(tmp_path):
    cfg = _config_copy(tmp_path)
    spec = collect_spec(cfg, prompt=_scripted_prompt(_ANSWERS), out=lambda *_: None)
    apply_spec(spec, cfg.base_dir)
    cfg.reload()

    # Create the new table the question expects and add 3 orders "today", 1 earlier.
    engine = build_engine(f"sqlite:///{(tmp_path / 'orders.db').as_posix()}")
    md = MetaData()
    orders = Table("orders", md, Column("id", Integer, primary_key=True), Column("order_date", Date))
    md.create_all(engine)
    with engine.begin() as conn:
        conn.execute(orders.insert(), [
            {"id": 1, "order_date": FROZEN_TODAY},
            {"id": 2, "order_date": FROZEN_TODAY},
            {"id": 3, "order_date": FROZEN_TODAY},
            {"id": 4, "order_date": date(2024, 6, 1)},  # outside "today"
        ])

    pipeline = Pipeline([
        IntentLayer(cfg),
        OrchestrationLayer(cfg),
        SemanticLayer(cfg),
        ServiceLayer(cfg, audit=AuditLogger(tmp_path / "audit.jsonl"),
                     rate_limiter=RateLimiter(1000, 60)),
        DataLayer(cfg, engine=engine, today=FROZEN_TODAY),
        ResponseLayer(cfg),
    ])

    out = pipeline.run(Envelope.create(user_id="u", role="admin",
                                       payload={"text": "How many orders did we get today?"}))
    assert out.ok, out.error
    assert out.payload["text"] == "We got 3 orders today."
    assert out.payload["value"] == 3
