"""Central configuration loader (PRD §3.4, §6.2).

All YAML config — settings, RBAC, intent patterns, response templates, semantic
entity definitions, and the schema registry — is loaded through one store so the
load path is never hardcoded inside a layer. Configs are cached after first read;
`reload()` clears the cache, which is the seam a future hot-reload feature plugs
into (not required for MVP, but deliberately not blocked).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

# Base directory containing config/, semantic/, schema_registry/. Defaults to this
# package's directory; overridable via env so deployments can relocate configs.
_DEFAULT_BASE = Path(__file__).resolve().parent


class ConfigStore:
    """Loads and caches EIAF YAML configuration by relative path."""

    def __init__(self, base_dir: Path | None = None) -> None:
        env_override = os.environ.get("EIAF_CONFIG_DIR")
        self.base_dir = base_dir or (Path(env_override) if env_override else _DEFAULT_BASE)
        self._cache: dict[str, Any] = {}

    # --- generic loading -------------------------------------------------------
    def _load(self, relative_path: str) -> Any:
        if relative_path not in self._cache:
            full_path = self.base_dir / relative_path
            if not full_path.is_file():
                raise FileNotFoundError(f"EIAF config not found: {full_path}")
            with full_path.open("r", encoding="utf-8") as fh:
                self._cache[relative_path] = yaml.safe_load(fh)
        return self._cache[relative_path]

    def reload(self) -> None:
        """Drop all cached config (hot-reload seam)."""
        self._cache.clear()

    # --- typed accessors -------------------------------------------------------
    def settings(self) -> dict[str, Any]:
        return self._load("config/settings.yaml")

    def roles(self) -> dict[str, Any]:
        return self._load("config/roles.yaml")

    def intent_patterns(self) -> dict[str, Any]:
        return self._load("config/intent_patterns.yaml")

    def orchestration(self) -> dict[str, Any]:
        return self._load("config/orchestration.yaml")

    def response_templates(self) -> dict[str, Any]:
        return self._load("config/response_templates.yaml")

    def semantic_entity(self, entity: str) -> dict[str, Any]:
        """Load semantic/entities/<entity>.yaml. Raises if the entity is unknown."""
        return self._load(f"semantic/entities/{entity}.yaml")

    def schema_mappings(self) -> dict[str, Any]:
        return self._load("schema_registry/mappings.yaml")


# Default process-wide store. Tests/deployments may construct their own.
config = ConfigStore()
