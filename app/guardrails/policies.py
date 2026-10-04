"""Bound per-identity request volume without retaining request content."""

from collections import deque
from threading import Lock
from time import monotonic


class SlidingWindowLimiter:
    """Per-process bound; a shared edge limiter is required for multi-worker use."""

    def __init__(self):
        self._lock = Lock()
        self._windows: dict[str, deque[float]] = {}

    def allow(self, key: str, *, limit: int, window_seconds: int = 60) -> bool:
        now = monotonic()
        with self._lock:
            # Bound memory even if many valid subjects arrive over time.
            if len(self._windows) > 10000:
                self._windows = {
                    name: bucket for name, bucket in self._windows.items()
                    if bucket and bucket[-1] > now - window_seconds
                }
            bucket = self._windows.setdefault(key, deque())
            while bucket and bucket[0] <= now - window_seconds:
                bucket.popleft()
            if len(bucket) >= limit:
                return False
            bucket.append(now)
            return True

    def clear(self) -> None:
        with self._lock:
            self._windows.clear()


request_limiter = SlidingWindowLimiter()
