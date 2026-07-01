"""Layer 2 — Intent Layer (PRD §3 Layer 2).

Determines intent + time period from free text using a versioned, rule-based
pattern table (NO LLM for MVP). The layer never guesses: any unrecognized intent
or period yields INTENT_NOT_FOUND.

Contract:
    in : {"text": "How much sales did I do this week?"}
    out: {"intent": "sales_amount", "period": "this_week"}
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel

from backend.config_loader import ConfigStore, config as default_config
from backend.envelope import Envelope
from backend.errors import ErrorCode, LayerError
from backend.layers.base import Layer


class _IntentInput(BaseModel):
    text: str


# Common English words/keywords recognized by EIAF
RECOGNIZED_WORDS = {
    "who", "are", "the", "by", "made", "highest", "of", "in", "what", "is", "for",
    "did", "we", "get", "show", "all", "on", "above", "greater", "than", "and", "per",
    "sales", "revenue", "product", "customers", "week", "today", "yesterday", "orders",
    "customer", "sell", "sold", "purchases", "purchase", "amount", "new", "most", "selling",
    "top", "day", "average", "avg", "value", "this", "past", "last", "days", "month",
    # maintenance-domain vocabulary
    "store", "stores", "info", "information", "details", "phone", "number", "manager",
    "managers", "manages", "employee", "employees", "staff", "works", "roster", "at",
    "fail", "failed", "failing", "torque", "calibration", "calibrations", "check",
    "checks", "not", "didn", "submit", "submitted", "missing", "equipment", "issue",
    "issues", "reported", "report", "were", "weekly", "facility", "maintenance", "log",
    "history", "service", "any", "with", "patterns", "pattern", "to", "it",
}


def is_garbage_word(word: str) -> bool:
    if word in RECOGNIZED_WORDS or word.isdigit():
        return False
    # Check vowel ratio
    vowels = sum(1 for c in word if c in "aeiou")
    if len(word) >= 5 and vowels == 0:
        return True
    if len(word) >= 7 and vowels / len(word) < 0.2:
        return True
    if len(word) > 15:
        return True
    return False


class IntentLayer(Layer):
    name = "intent"

    def __init__(self, config: ConfigStore | None = None) -> None:
        self._config = config or default_config

    def handle(self, envelope: Envelope) -> dict[str, Any]:
        data = self.parse(_IntentInput, envelope.payload)
        text = data.text.strip()
        if not text:
            raise LayerError(ErrorCode.INTENT_NOT_FOUND, "Empty input text.")

        # 1. Heuristic Garbage Filter
        words = [w.lower() for w in re.findall(r"\b[a-zA-Z0-9_]+\b", text)]
        if not words:
            raise LayerError(ErrorCode.INTENT_NOT_FOUND, "No valid words found in query.")
        
        garbage_words = [w for w in words if is_garbage_word(w)]
        if garbage_words and len(garbage_words) / len(words) > 0.3:
            raise LayerError(
                ErrorCode.INTENT_NOT_FOUND,
                "Query contains too many unrecognized or garbage terms.",
            )

        table = self._config.intent_patterns()
        intent, extracted = self._match_intent(text, table["intents"])
        period = self._match_period(text, table["periods"])

        if intent is None:
            raise LayerError(
                ErrorCode.INTENT_NOT_FOUND,
                "Could not recognize the question as a supported intent.",
            )
        
        # Default period if not explicitly matched in query
        if period is None:
            if intent in {"sales_amount", "orders", "new_customers"}:
                raise LayerError(
                    ErrorCode.INTENT_NOT_FOUND,
                    "Could not recognize the question as a supported intent and period.",
                )
            if intent == "torque_not_submitted":
                period = "today"
            else:
                period = "this_month"

        res = {
            "intent": intent,
            "period": period,
        }
        if extracted:
            res["extracted"] = extracted
        return res

    @staticmethod
def _match_intent(
    text: str,
    intents: list[dict[str, Any]],
) -> tuple[str | None, dict[str, Any]]:

    for intent in intents:

        entity_name = intent.get("entity")

        for pattern in intent["patterns"]:

            match = re.search(pattern, text, re.IGNORECASE)

            if not match:
                continue

            extracted: dict[str, Any] = {}

            # Generic entity extraction
            if entity_name and match.groups():

                value = match.group(1).strip()

                if entity_name in {
                    "store_id",
                    "company_id",
                    "submission_id",
                    "log_id",
                    "task_id",
                    "check_item_id",
                }:
                    extracted[entity_name] = int(value)

                elif entity_name in {
                    "amount",
                    "hourly_rate",
                }:
                    extracted[entity_name] = float(
                        value.replace(",", "").replace("₹", "")
                    )

                else:
                    extracted[entity_name] = value

            # Optional limit support
            if "limit" in intent and "limit" not in extracted:
                extracted["limit"] = intent["limit"]

            return intent["name"], extracted

    return None, {}

    @staticmethod
    def _match_period(text: str, periods: list[dict[str, Any]]) -> str | None:
        # First match in declared (most-specific-first) order wins.
        for period in periods:
            for pattern in period["patterns"]:
                if re.search(pattern, text, re.IGNORECASE):
                    return period["value"]
        return None
