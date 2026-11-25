"""A small per-client limit for the open routes (scam console, check a message), so they cannot be used as a free
model proxy. In memory, one server process."""
from __future__ import annotations

import time
from collections import defaultdict, deque

PER_MINUTE = 20
_recent: dict[str, deque] = defaultdict(deque)


def allow(key: str, per_minute: int | None = None) -> bool:
    limit = PER_MINUTE if per_minute is None else per_minute
    now = time.monotonic()
    q = _recent[key]
    while q and now - q[0] > 60:
        q.popleft()
    if len(q) >= limit:
        return False
    q.append(now)
    return True


def reset() -> None:
    _recent.clear()
