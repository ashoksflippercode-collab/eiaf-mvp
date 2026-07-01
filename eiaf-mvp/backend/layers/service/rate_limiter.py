"""Per-user sliding-window rate limiter (PRD §3 Layer 5, §7 Q3).

In-memory and single-process — sufficient for the MVP's single Admin user. For a
multi-process / multi-node deployment this would move to a shared store (e.g.
Redis), but the `RateLimiter` interface stays the same.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Callable, Deque


class RateLimiter:
    def __init__(
        self,
        max_requests: int,
        window_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._clock = clock
        self._hits: dict[str, Deque[float]] = defaultdict(deque)

    def check_and_consume(self, key: str) -> bool:
        """Return True and record the hit if under the limit; else False."""
        now = self._clock()
        window_start = now - self.window_seconds
        hits = self._hits[key]
        while hits and hits[0] <= window_start:
            hits.popleft()
        if len(hits) >= self.max_requests:
            return False
        hits.append(now)
        return True
