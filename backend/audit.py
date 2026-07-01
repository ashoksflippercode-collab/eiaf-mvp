"""Append-only audit logger (PRD §3 Layer 5, §6.3).

Every approved or rejected query is recorded as one JSON line, keyed by the
envelope's `request_id` for end-to-end correlation. MVP writes to a local
JSONL file; production should point `log_path` at a write-once (WORM) sink —
the application only ever appends, never rewrites or deletes.

NOTE: reconstructed here because it was not included in the uploaded zip
("only required files" were attached). If your full repository already has a
canonical audit.py, prefer that one instead.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class AuditLogger:
    def __init__(self, log_path: str) -> None:
        self._path = Path(log_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def record(
        self,
        *,
        request_id: str,
        user_id: str,
        role: str,
        entity: str,
        metric: str,
        filters: dict[str, Any],
        decision: str,
        reason: str | None = None,
    ) -> None:
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "request_id": request_id,
            "user_id": user_id,
            "role": role,
            "entity": entity,
            "metric": metric,
            "filters": filters,
            "decision": decision,
            "reason": reason,
        }
        line = json.dumps(entry, default=str)
        with self._lock:
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
