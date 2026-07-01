"""Seed the demo database (dev/test tooling, not part of the request path).

Creates the `customers` table and inserts sample rows whose rolling-7-day total
is exactly ₹63,000 — the PRD §2.4 success value. Table and column names are read
from the Schema Registry, so this stays consistent with the app and survives a
column rename (acceptance §8.3).

Usage:  python -m backend.seed
"""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import Column, Date, Engine, MetaData, Numeric, String, Table, func, select

from backend.config_loader import ConfigStore, config as default_config
from backend.database.mysql import get_engine


def seed(
    engine: Engine | None = None,
    today: date | None = None,
    cfg: ConfigStore | None = None,
) -> None:
    engine = engine or get_engine()
    today = today or date.today()
    cfg = cfg or default_config

    mappings = cfg.schema_mappings()
    table_name = mappings["metrics"]["total_sales"]["table"]
    value_col = mappings["metrics"]["total_sales"]["column"]
    date_col = mappings["dimensions"]["period"]["column"]

    metadata = MetaData()
    customers = Table(
        table_name,
        metadata,
        Column("customer_name", String(255)),
        Column("product", String(255)),
        Column(date_col, Date),
        Column(value_col, Numeric(12, 2)),
    )
    metadata.drop_all(engine)
    metadata.create_all(engine)

    # Rolling windows from "today":
    #   this_week  (>= today-7)  -> 20000 + 18000 + 25000          = 63,000
    #   this_month (>= today-30) -> 63000 + 30000                  = 93,000
    #   today      (>= today)    -> 20000
    rows = [
        _row("Asha Verma", "Widget", today, 20000, date_col, value_col),
        _row("Ravi Kumar", "Gadget", today - timedelta(days=2), 18000, date_col, value_col),
        _row("Meena Iyer", "Widget", today - timedelta(days=5), 25000, date_col, value_col),
        _row("Vijay Rao", "Gizmo", today - timedelta(days=15), 30000, date_col, value_col),
        _row("Sara Khan", "Widget", today - timedelta(days=45), 40000, date_col, value_col),
    ]
    with engine.begin() as conn:
        conn.execute(customers.insert(), rows)

    with engine.connect() as conn:
        week_total = conn.execute(
            select(func.sum(customers.c[value_col])).where(
                customers.c[date_col] >= today - timedelta(days=7)
            )
        ).scalar()
    print(f"Seeded {len(rows)} rows into '{table_name}'. Rolling 7-day total = {week_total}")


def _row(name, product, day, amount, date_col, value_col):
    return {"customer_name": name, "product": product, date_col: day, value_col: amount}


if __name__ == "__main__":
    seed()
