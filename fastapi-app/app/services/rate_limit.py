"""Simple in-memory rate limiter (per user, sliding window). Thread-safe."""

from __future__ import annotations

import time
from collections import defaultdict
from threading import Lock

_store: dict[str, list[float]] = defaultdict(list)
_lock = Lock()


def check(key: str, limit: int, window_secs: int = 60) -> tuple[bool, int]:
    """Return (allowed, retry_after_seconds). Does NOT raise — callers decide."""
    now = time.monotonic()
    with _lock:
        times = [t for t in _store[key] if now - t < window_secs]
        _store[key] = times
        if len(times) >= limit:
            retry_after = int(window_secs - (now - min(times))) + 1
            return False, retry_after
        _store[key].append(now)
        return True, 0
