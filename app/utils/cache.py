"""Unified cache layer: built-in in-process TTL+LRU cache.

One pattern instead of four hand-rolled copies. Thread-safe, capped,
TTL-based, with prefix invalidation so writes can bust related keys
without knowing every key derived from them.

Single-process by design: the deployment is pinned to one gunicorn worker
(render.yaml --workers 1), so no shared/external store is needed. Values
are stored by reference — only cache immutable snapshots (dict/list copies,
not objects other code mutates).
"""
from __future__ import annotations

import threading
import time
import weakref
from collections import OrderedDict
from typing import Any, Callable

_SENTINEL = object()


class TTLCache:
    """Thread-safe LRU cache where entries expire after `ttl` seconds."""

    def __init__(self, ttl: float, max_entries: int = 50):
        self.ttl = ttl
        self.max_entries = max_entries
        # Entries are (absolute_expiry, value) — per-set ttl overrides the
        # instance default (previously accepted but silently ignored).
        self._store: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self._lock = threading.Lock()
        # F5: weak-valued so per-key locks vanish once no get_or_set is using them
        self._rebuild_locks: weakref.WeakValueDictionary[str, threading.Lock] = (
            weakref.WeakValueDictionary()
        )
        # Observability (GAP-003): hit/miss counters for the stats endpoint
        self._hits = 0
        self._misses = 0

    def get(self, key: str, default=None):
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                self._misses += 1
                return default
            expiry, value = entry
            if time.time() >= expiry:
                del self._store[key]
                self._misses += 1
                return default
            self._store.move_to_end(key)
            self._hits += 1
            return value

    def set(self, key: str, value: Any, ttl: float | None = None) -> None:
        with self._lock:
            self._store[key] = (time.time() + (ttl if ttl is not None else self.ttl), value)
            self._store.move_to_end(key)
            while len(self._store) > self.max_entries:
                self._store.popitem(last=False)

    def get_or_set(self, key: str, producer: Callable[[], Any]) -> Any:
        """Read-through: return cached value or call producer and cache it.
        Per-key lock prevents thundering herd on cold cache."""
        value = self.get(key, _SENTINEL)
        if value is not _SENTINEL:
            return value
        # Per-key lock: only one thread rebuilds, others wait and read.
        # Strong local ref keeps the weak entry alive for the duration.
        with self._lock:
            key_lock = self._rebuild_locks.get(key)
            if key_lock is None:
                key_lock = threading.Lock()
                self._rebuild_locks[key] = key_lock
        with key_lock:
            # Double-check after acquiring lock
            value = self.get(key, _SENTINEL)
            if value is not _SENTINEL:
                return value
            value = producer()
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
            return {
                "entries": len(self._store),
                "max_entries": self.max_entries,
                "ttl": self.ttl,
                "hits": self._hits,
                "misses": self._misses,
            }


class CacheProxy(TTLCache):
    """Named in-process cache. A distinct type (not a bare TTLCache) so the
    named caches below read naturally and stats() advertises the backend."""

    def __init__(self, name: str, ttl: float, max_entries: int = 50):
        super().__init__(ttl, max_entries)
        self.name = name

    def stats(self) -> dict:
        stats = super().stats()
        stats["backend"] = "memory"
        return stats


# ── Named caches, one per concern ─────────────────────────────────
# Writes call cache_bust_* so stale data never outlives a mutation.
# Each is a CacheProxy: in-process only (single-worker deployment).

products_cache = CacheProxy("products", ttl=300, max_entries=100)      # lists + details (5 min)
suppliers_cache = CacheProxy("suppliers", ttl=300, max_entries=100)    # lists + details (5 min)
dashboard_cache = CacheProxy("dashboard", ttl=600, max_entries=20)     # dashboard context (10 min)
reports_cache = CacheProxy("reports", ttl=7200, max_entries=50)        # heavy report queries (2 hours)
global_cache = CacheProxy("global", ttl=600, max_entries=20)           # reorder count, settings, cross-request (10 min)
api_cache = CacheProxy("api", ttl=120, max_entries=100)                # REST GET responses (2 min)
landing_cache = CacheProxy("landing", ttl=600, max_entries=10)         # public landing stats (10 min)
monitoring_cache = CacheProxy("monitoring", ttl=60, max_entries=10)    # monitoring DB stats (1 min)


# DB-014: busts are intentionally broad (whole-cache invalidates) —
# correctness-safe (cold reads) at the cost of a cold cache after writes.
# NOTE (GAP-003 Phase 4): audited for narrowing — every busted cache is
# genuinely affected by its write path (stock/price feed lists, dashboard
# aggregates, report queries AND landing stats), so broad invalidation is
# already as narrow as correctness allows. Do not narrow further without
# key-level dependency tracking.
def cache_bust_products() -> int:
    """Invalidate everything derived from product data."""
    n = products_cache.invalidate("")
    n += dashboard_cache.invalidate("dashboard:")
    n += reports_cache.invalidate("")         # F2: reports keys may lack a prefix
    n += global_cache.invalidate("")          # reorder_count changes with stock
    n += api_cache.invalidate("product")      # matches "products:..." and "product:<id>"
    n += landing_cache.invalidate("")
    return n


def cache_bust_suppliers() -> int:
    n = suppliers_cache.invalidate("")
    n += reports_cache.invalidate("reports:")
    n += api_cache.invalidate("suppliers")
    n += landing_cache.invalidate("")
    return n


def cache_bust_movements() -> int:
    """Movements change stock → bust product/dashboard/reports/global caches."""
    n = products_cache.invalidate("")
    n += dashboard_cache.invalidate("dashboard:")
    n += reports_cache.invalidate("reports:")
    n += global_cache.invalidate("")          # reorder_count changes with stock
    n += api_cache.invalidate("movements")
    # DON'T bust: landing_cache, suppliers_cache
    return n


def cache_bust_purchase_orders() -> int:
    n = products_cache.invalidate("")          # PO delivery updates stock
    n += dashboard_cache.invalidate("dashboard:")
    n += reports_cache.invalidate("reports:")
    n += global_cache.invalidate("")          # reorder_count changes with stock
    n += api_cache.invalidate("purchase_orders")
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
    """Deterministic cache key from filter params (falsy values skipped).

    A `prefix` kwarg is emitted first as `prefix:...` so invalidate(prefix)
    can match the key; without it the body is unchanged.
    """
    prefix = kwargs.pop("prefix", "") or ""
    body = "|".join(f"{k}={v}" for k, v in sorted(kwargs.items()) if v)
    if prefix:
        # N1: always emit the colon so empty-body keys ("reports:") still
        # match invalidate("prefix:") busts used by movement/PO/supplier writes.
        return f"{prefix}:{body}"
    return body