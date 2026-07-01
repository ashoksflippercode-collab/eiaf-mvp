"""Tests for the config consistency checker (authoring aid)."""

from __future__ import annotations

import shutil

import yaml

from backend.check_config import run_checks
from backend.config_loader import ConfigStore, config


def test_live_config_is_consistent():
    # The shipped config (both wired questions) must pass with zero errors.
    errors, _ = run_checks(config)
    assert errors == [], errors


def _config_copy(tmp_path) -> ConfigStore:
    """A writable copy of the real config tree, loadable via its own store."""
    for sub in ("config", "semantic", "schema_registry"):
        shutil.copytree(config.base_dir / sub, tmp_path / sub)
    return ConfigStore(base_dir=tmp_path)


def test_detects_metric_missing_from_schema_registry(tmp_path):
    cfg = _config_copy(tmp_path)
    mappings_path = tmp_path / "schema_registry" / "mappings.yaml"
    data = yaml.safe_load(mappings_path.read_text(encoding="utf-8"))
    del data["metrics"]["new_customer_count"]  # break one cross-reference
    mappings_path.write_text(yaml.safe_dump(data), encoding="utf-8")

    errors, _ = run_checks(cfg)
    assert any("new_customer_count" in e and "mappings.yaml" in e for e in errors), errors


def test_detects_intent_without_patterns(tmp_path):
    cfg = _config_copy(tmp_path)
    patterns_path = tmp_path / "config" / "intent_patterns.yaml"
    data = yaml.safe_load(patterns_path.read_text(encoding="utf-8"))
    data["intents"] = [i for i in data["intents"] if i["name"] != "new_customers"]
    patterns_path.write_text(yaml.safe_dump(data), encoding="utf-8")

    errors, _ = run_checks(cfg)
    assert any("intent_patterns.yaml" in e and "new_customers" in e for e in errors), errors
