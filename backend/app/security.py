from __future__ import annotations

import time
from collections import deque


class LoginRateLimiter:
    def __init__(self, attempts: int, window_seconds: int) -> None:
        self.attempts = max(1, attempts)
        self.window_seconds = max(1, window_seconds)
        self._events: dict[str, deque[float]] = {}

    def is_allowed(self, key: str) -> bool:
        now = time.monotonic()
        bucket = self._events.setdefault(key, deque())
        threshold = now - self.window_seconds
        while bucket and bucket[0] < threshold:
            bucket.popleft()
        if len(bucket) >= self.attempts:
            return False
        bucket.append(now)
        return True
