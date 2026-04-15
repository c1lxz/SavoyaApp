from __future__ import annotations

import time
from collections import deque


class LoginRateLimiter:
    def __init__(self, attempts: int, window_seconds: int) -> None:
        self.attempts = max(1, attempts)
        self.window_seconds = max(1, window_seconds)
        self._events: dict[str, deque[float]] = {}

    def _prune(self, key: str) -> deque[float]:
        now = time.monotonic()
        bucket = self._events.get(key)
        if bucket is None:
            return deque()
        threshold = now - self.window_seconds
        while bucket and bucket[0] < threshold:
            bucket.popleft()
        if not bucket:
            self._events.pop(key, None)
            return deque()
        return bucket

    def is_allowed(self, key: str) -> bool:
        bucket = self._prune(key)
        return len(bucket) < self.attempts

    def record_failure(self, key: str) -> None:
        now = time.monotonic()
        bucket = self._prune(key)
        if not bucket:
            bucket = deque()
            self._events[key] = bucket
        bucket.append(now)

    def record_event(self, key: str) -> None:
        self.record_failure(key)

    def reset(self, key: str) -> None:
        self._events.pop(key, None)
