"""Simple thread-safe in-memory TTL cache for Flask applications."""

from __future__ import annotations

import threading
import time
from typing import Callable, Generic, TypeVar

T = TypeVar("T")


class TTLCache(Generic[T]):
    """In-memory cache with time-based expiry.

    Entries expire lazily: expired values are dropped on the next access.
    All public methods are safe to call from multiple threads.
    """

    def __init__(self, ttl: int):
        if ttl <= 0:
            raise ValueError("ttl must be a positive number of seconds")
        self.ttl = ttl
        self._data: dict[str, tuple[float, T]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> T | None:
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                return None
            ts, value = entry
            if time.monotonic() - ts > self.ttl:
                del self._data[key]
                return None
            return value

    def set(self, key: str, value: T) -> None:
        with self._lock:
            self._data[key] = (time.monotonic(), value)

    def get_or_set(self, key: str, factory: Callable[..., T], *args, **kwargs) -> T:
        """Return the cached value, or compute and cache it when missing/expired."""
        value = self.get(key)
        if value is not None:
            return value
        value = factory(*args, **kwargs)
        self.set(key, value)
        return value

    def delete(self, key: str) -> None:
        with self._lock:
            self._data.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()

    def __contains__(self, key: str) -> bool:
        return self.get(key) is not None

    def __len__(self) -> int:
        with self._lock:
            now = time.monotonic()
            expired = [k for k, (ts, _) in self._data.items() if now - ts > self.ttl]
            for k in expired:
                del self._data[k]
            return len(self._data)