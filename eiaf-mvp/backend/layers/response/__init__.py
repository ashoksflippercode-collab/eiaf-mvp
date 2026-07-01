"""Layer 7 — Response Layer (PRD §3 Layer 7).

Converts raw data into a human-readable answer using a config-driven template
(NO LLM for MVP). The sentence template AND the value formatting are selected
per metric from config, never inline string logic — so a new question's wording
is a config change, not a code change (§6.2). Numbers use locale-correct Indian
formatting via Babel (currency for amounts, plain integer for counts).

Contract:
    in : {"metric": "total_sales", "filters": {"period": "this_week"},
          "result": {"total_sales": 63000}, ...}
    out: {"text": "This week's total sales are ₹63,000.", "value": 63000}
"""

from __future__ import annotations

from typing import Any

from babel.numbers import format_currency, format_decimal
from pydantic import BaseModel

from backend.config_loader import ConfigStore, config as default_config
from backend.envelope import Envelope
from backend.errors import ErrorCode, LayerError
from backend.layers.base import Layer


class _Filters(BaseModel):
    period: str


class _ResponseInput(BaseModel):
    metric: str
    filters: _Filters
    result: Any


class ResponseLayer(Layer):
    name = "response"

    def __init__(self, config: ConfigStore | None = None) -> None:
        self._config = config or default_config

    def handle(self, envelope: Envelope) -> dict[str, Any]:
        data = self.parse(_ResponseInput, envelope.payload)
        period = data.filters.period
        result = data.result

        # Handle list of rows (tabular data)
        if isinstance(result, list):
            text = self._format_table(result)
            return {"text": text, "value": result}

        # Otherwise handle scalar value
        value = result.get(data.metric, 0) if isinstance(result, dict) else result

        templates = self._config.response_templates()

        metric_cfg = templates.get("metrics", {}).get(data.metric)
        if metric_cfg is None:
            # Fallback if no template is defined
            return {"text": f"Result: {value}", "value": value}

        labels = templates["period_labels"].get(period)
        if labels is None:
            # Fallback label
            labels = {"possessive": f"{period}'s", "plain": period}

        text = metric_cfg["template"].format(
            period=labels["plain"],
            period_possessive=labels["possessive"],
            value=self._format_value(value, metric_cfg.get("format", "number")),
        )
        return {"text": text, "value": value}

    def _format_table(self, rows: list[dict[str, Any]]) -> str:
        if not rows:
            return "No data found."

        if len(rows) == 1:
            row = rows[0]
            items = []
            for k, v in row.items():
                fmt_v = self._format_value_by_key(k, v)
                items.append(f"{k.replace('_', ' ').capitalize()}: {fmt_v}")
            return ", ".join(items)

        # Check if first column has date
        first_row = rows[0]
        keys = list(first_row.keys())

        lines = []
        for idx, row in enumerate(rows, 1):
            parts = []
            for k in keys:
                v = row[k]
                fmt_v = self._format_value_by_key(k, v)
                parts.append(fmt_v)
            if len(parts) >= 2:
                # E.g. "Vijay Rao: ₹30,000"
                lines.append(f"{idx}. {parts[0]}: " + " - ".join(parts[1:]))
            else:
                lines.append(f"- {parts[0]}")
        return "\n".join(lines)

    def _format_value_by_key(self, key: str, val: Any) -> str:
        if val is None:
            return ""
        if isinstance(val, (int, float)):
            if any(x in key.lower() for x in ["sales", "amount", "revenue", "purchase"]):
                return self._format_value(val, "currency")
            return self._format_value(val, "number")
        return str(val)

    def _format_value(self, value: Any, fmt: str) -> str:
        if isinstance(value, str):
            return value
        locale_cfg = self._config.settings()["locale"]
        if fmt == "currency":
            try:
                float(value)
            except (ValueError, TypeError):
                return str(value)
            return format_currency(
                value,
                locale_cfg["currency"],
                format=locale_cfg["currency_format"],
                locale=locale_cfg["code"],
                currency_digits=False,
            )
        if fmt == "number":
            try:
                float(value)
            except (ValueError, TypeError):
                return str(value)
            return format_decimal(value, locale=locale_cfg["code"])
        raise LayerError(
            ErrorCode.INTERNAL_ERROR,
            f"Unknown value format '{fmt}' in response config.",
        )
