"""Unified in-memory TTL + LRU cache for the whole application.

One pattern instead of four hand-rolled copies. Thread-safe, capped,
TTL-based, with prefix invalidation so writes can bust related keys
without knowing every key derived from them.

Values are stored by reference — only cache immutable snapshots
(dict/list copies, not objects other code mutates in place).
"""
from __future__ import annotations

import threading
import time
from collections import OrderedDict
from typing import Any, Callable

_SENTINEL = object()


class TTLCache:
    """Thread-safe LRU cache where entries expire after `ttl` seconds."""

    def __init__(self, ttl: float, max_entries: int = 50):
        self.ttl = ttl
        self.max_entries = max_entries
        self._store: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str, default=None):
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return default
            ts, value = entry
            if time.time() - ts >= self.ttl:
                del self._store[key]
                return default
            self._store.move_to_end(key)
            return value

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self._store[key] = (time.time(), value)
            self._store.move_to_end(key)
            while len(self._store) > self.max_entries:
                self._store.popitem(last=False)

    def get_or_set(self, key: str, producer: Callable[[], Any]) -> Any:
        """Read-through: return cached value or call producer and cache it."""
        value = self.get(key, _SENTINEL)
        if value is not _SENTINEL:
            return value
        value = producer()
        if value is not None:
            self.set(key, value)
        return value

    def invalidate(self, prefix: str) -> int:
        """Drop every key starting with `prefix`. Returns count dropped."""
        with self._lock:
            doomed = [k for k in self._store if k.startswith(prefix)]
            for k in doomed:
                del self._store[k]
            return len(doomed)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()

    def stats(self) -> dict:
        with self._lock:
            return {"entries": len(self._store), "max_entries": self.max_entries, "ttl": self.ttl}


# ── Named caches, one per concern ─────────────────────────────────
# Writes call cache_bust_* so stale data never outlives a mutation.

products_cache = TTLCache(ttl=120, max_entries=50)   # lists + details
suppliers_cache = TTLCache(ttl=120, max_entries=50)  # lists + details
dashboard_cache = TTLCache(ttl=60, max_entries=10)   # dashboard context
reports_cache = TTLCache(ttl=300, max_entries=20)     # heavy report queries
global_cache = TTLCache(ttl=60, max_entries=10)       # reorder count etc.
api_cache = TTLCache(ttl=60, max_entries=50)          # REST GET responses
landing_cache = TTLCache(ttl=300, max_entries=5)      # public landing stats
monitoring_cache = TTLCache(ttl=30, max_entries=5)     # monitoring DB stats


def cache_bust_products() -> int:
    """Invalidate everything derived from product data."""
    n = products_cache.invalidate("")
    n += dashboard_cache.invalidate("")
    n += reports_cache.invalidate("")
    n += global_cache.invalidate("")          # reorder_count changes with stock
    n += api_cache.invalidate("products")
    n += landing_cache.invalidate("")          # landing shows stock/product stats
    return n


def cache_bust_suppliers() -> int:
    n = suppliers_cache.invalidate("")
    n += reports_cache.invalidate("")
    n += api_cache.invalidate("suppliers")
    n += landing_cache.invalidate("")
    return n


def cache_bust_movements() -> int:
    """Movements change stock → everything product/dashboard-ish is stale."""
    n = products_cache.invalidate("")
    n += dashboard_cache.invalidate("")
    n += reports_cache.invalidate("")
    n += global_cache.invalidate("")
    n += api_cache.invalidate("")
    n += landing_cache.invalidate("")
    return n


def cache_bust_purchase_orders() -> int:
    n = products_cache.invalidate("")          # PO delivery updates stock
    n += dashboard_cache.invalidate("")
    n += reports_cache.invalidate("")
    n += api_cache.invalidate("")
    return n


def cache_bust_settings() -> int:
    return global_cache.invalidate("") + api_cache.invalidate("settings")


def cache_bust_all() -> int:
    n = 0
    for c in (products_cache, suppliers_cache, dashboard_cache, reports_cache,
              global_cache, api_cache, landing_cache, monitoring_cache):
        n += c.invalidate("")
    return n


def make_key(**kwargs) -> str:
    """Deterministic cache key from filter params (falsy values skipped)."""
    return "|".join(f"{k}={v}" for k, v in sorted(kwargs.items()) if v)
