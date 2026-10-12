"""Unified cache layer: in-memory TTL+LRU with optional Redis backend (GAP-003).

One pattern instead of four hand-rolled copies. Thread-safe, capped,
TTL-based, with prefix invalidation so writes can bust related keys
without knowing every key derived from them.

Backends (CacheProxy, feature-flagged):
- memory (default)  — TTLCache below, per-process
- redis             — shared across workers when USE_REDIS_CACHE=true and the
                      server is reachable; ANY Redis failure permanently
                      degrades that proxy to its in-memory fallback for the
                      process (cache must never break the app).

Values are stored by reference (memory) or pickled (redis) — only cache
immutable snapshots (dict/list copies, not objects other code mutates).
"""
from __future__ import annotations

import logging
import pickle
import threading
import time
import weakref
from collections import OrderedDict
from typing import Any, Callable

LOGGER = logging.getLogger(__name__)

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


class RedisCache:
    """Redis-backed cache with the TTLCache interface (GAP-003).

    Shared across workers. Values are pickled; keys are namespaced
    (``inv:cache:{name}:{key}``) so they can never collide with the
    rate-limit keys that may share the same Redis server.
    """

    def __init__(self, name: str, ttl: float, redis_url: str):
        self.name = name
        self.ttl = ttl
        self.redis_url = redis_url
        self._client = None
        self._lock = threading.Lock()
        # Local per-key locks for get_or_set herd protection (same pattern
        # as TTLCache; cross-process herd is mitigated by the shared store).
        self._rebuild_locks: weakref.WeakValueDictionary[str, threading.Lock] = (
            weakref.WeakValueDictionary()
        )

    def _key(self, key: str) -> str:
        return f"inv:cache:{self.name}:{key}"

    def client(self):
        """Connect + ping once; raises on failure (caller decides fallback)."""
        if self._client is None:
            import redis as redis_lib

            client = redis_lib.Redis.from_url(
                self.redis_url, socket_connect_timeout=2, socket_timeout=2
            )
            client.ping()
            self._client = client
        return self._client

    def get(self, key: str, default=None):
        raw = self.client().get(self._key(key))
        if raw is None:
            return default
        return pickle.loads(raw)

    def set(self, key: str, value: Any, ttl: float | None = None) -> None:
        self.client().setex(
            self._key(key), int(ttl or self.ttl), pickle.dumps(value)
        )

    def get_or_set(self, key: str, producer: Callable[[], Any]) -> Any:
        value = self.get(key, _SENTINEL)
        if value is not _SENTINEL:
            return value
        with self._lock:
            key_lock = self._rebuild_locks.get(key)
            if key_lock is None:
                key_lock = threading.Lock()
                self._rebuild_locks[key] = key_lock
        with key_lock:
            value = self.get(key, _SENTINEL)
            if value is not _SENTINEL:
                return value
            value = producer()
            self.set(key, value)
            return value

    def invalidate(self, prefix: str) -> int:
        client = self.client()
        pattern = self._key(prefix) + "*"
        removed = 0
        cursor = 0
        while True:
            cursor, keys = client.scan(cursor=cursor, match=pattern, count=500)
            if keys:
                client.delete(*keys)
                removed += len(keys)
            if cursor == 0:
                break
        return removed

    def clear(self) -> None:
        self.invalidate("")

    def stats(self) -> dict:
        return {
            "backend": "redis",
            "ttl": self.ttl,
            "entries": -1,  # unknown without a full SCAN; not worth the cost
        }


class CacheProxy:
    """Backend selector: Redis when flagged + reachable, else in-memory.

    All existing ``from ..utils.cache import products_cache`` imports keep
    working — the proxy exposes the exact TTLCache interface. Resolution is
    lazy (needs app config) and sticky: once Redis fails, the proxy uses its
    in-memory fallback for the rest of the process (logged once).
    """

    def __init__(self, name: str, ttl: float, max_entries: int = 50):
        self.name = name
        self.ttl = ttl
        self.max_entries = max_entries
        self._memory = TTLCache(ttl, max_entries)
        self._redis: RedisCache | None = None
        self._mode: str | None = None  # None=unresolved | "redis" | "memory"

    # ── backend resolution ────────────────────────────────────────

    def _resolve_redis(self) -> RedisCache | None:
        """Return a working RedisCache or None (flag off / unreachable)."""
        if self._mode == "memory":
            return None
        if self._redis is not None:
            return self._redis
        try:
            from flask import current_app

            if not current_app:
                return None
            if not current_app.config.get("USE_REDIS_CACHE"):
                self._mode = "memory"
                return None
            url = current_app.config.get("REDIS_CACHE_URL") or "redis://localhost:6379/1"
            candidate = RedisCache(self.name, self.ttl, url)
            candidate.client()  # ping — raises if unreachable
            self._redis = candidate
            self._mode = "redis"
            LOGGER.info("Cache '%s' using Redis backend (%s)", self.name, url)
            return self._redis
        except Exception as exc:  # noqa: BLE001 — Redis is optional
            LOGGER.warning(
                "Cache '%s': Redis unavailable (%s) — using in-memory fallback",
                self.name, exc,
            )
            self._mode = "memory"
            return None

    def _degrade(self, exc: Exception) -> TTLCache:
        """Permanent per-process fallback after a mid-flight Redis failure."""
        LOGGER.warning(
            "Cache '%s': Redis failure (%s) — degrading to in-memory for this process",
            self.name, exc,
        )
        self._mode = "memory"
        self._redis = None
        return self._memory

    # ── delegated interface ───────────────────────────────────────

    def get(self, key: str, default=None):
        backend = self._resolve_redis()
        if backend is not None:
            try:
                return backend.get(key, default)
            except Exception as exc:  # noqa: BLE001
                backend = self._degrade(exc)
        return self._memory.get(key, default)

    def set(self, key: str, value: Any, ttl: float | None = None) -> None:
        backend = self._resolve_redis()
        if backend is not None:
            try:
                backend.set(key, value, ttl)
                return
            except Exception as exc:  # noqa: BLE001
                backend = self._degrade(exc)
        self._memory.set(key, value, ttl)

    def get_or_set(self, key: str, producer: Callable[[], Any]) -> Any:
        backend = self._resolve_redis()
        if backend is not None:
            try:
                return backend.get_or_set(key, producer)
            except Exception as exc:  # noqa: BLE001
                backend = self._degrade(exc)
        return self._memory.get_or_set(key, producer)

    def invalidate(self, prefix: str) -> int:
        backend = self._resolve_redis()
        if backend is not None:
            try:
                return backend.invalidate(prefix)
            except Exception as exc:  # noqa: BLE001
                backend = self._degrade(exc)
        return self._memory.invalidate(prefix)

    def clear(self) -> None:
        backend = self._resolve_redis()
        if backend is not None:
            try:
                backend.clear()
                return
            except Exception as exc:  # noqa: BLE001
                backend = self._degrade(exc)
        self._memory.clear()

    def stats(self) -> dict:
        backend = self._resolve_redis()
        if backend is not None:
            try:
                return backend.stats()
            except Exception as exc:  # noqa: BLE001
                backend = self._degrade(exc)
        stats = self._memory.stats()
        stats["backend"] = "memory"
        return stats


# ── Named caches, one per concern ─────────────────────────────────
# Writes call cache_bust_* so stale data never outlives a mutation.
# Each is a CacheProxy: in-memory by default, Redis when
# USE_REDIS_CACHE=true and the server is reachable (GAP-003).

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