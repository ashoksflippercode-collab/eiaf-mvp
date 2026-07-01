"""Database engine factory (PRD §3 Layer 6, §5).

Builds a SQLAlchemy engine from `settings.yaml`. The MVP defaults to a local
SQLite file for zero-setup runnability; production points the same `database.url`
at MySQL (`mysql+pymysql://...`). The Data Layer issues SELECT statements only,
but production should ALSO use a read-only DB credential as defense in depth —
the application layer must not have write access to `customers` for queries.
"""

from __future__ import annotations

from sqlalchemy import Engine, create_engine

from backend.config_loader import config as default_config


def build_engine(url: str, connect_timeout: int = 5) -> Engine:
    """Create a SQLAlchemy engine for `url`, applying a connect timeout."""
    if url.startswith("sqlite"):
        # SQLite has no network connect timeout; keep connect_args minimal.
        connect_args: dict = {}
    else:
        connect_args = {"connect_timeout": connect_timeout}
    return create_engine(url, connect_args=connect_args, pool_pre_ping=True, future=True)


_engine: Engine | None = None


def get_engine() -> Engine:
    """Return the process-wide engine, building it from settings on first use."""
    global _engine
    if _engine is None:
        db = default_config.settings()["database"]
        _engine = build_engine(db["url"], db.get("connect_timeout_seconds", 5))
    return _engine
