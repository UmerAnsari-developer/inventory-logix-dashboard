"""Batch 3 Phase 4 tests: cache layer hit/miss stats, backend marker, and
invalidation semantics."""
from __future__ import annotations

import pytest

from app.utils.cache import CacheProxy, TTLCache, cache_bust_products, make_key


@pytest.fixture(autouse=True)
def _clean_caches():
    """Isolate the shared named caches between tests."""
    from app.utils.cache import cache_bust_all

    cache_bust_all()
    yield
    cache_bust_all()


# ── TTLCache hit/miss observability ─────────────────────────────────────────

def test_ttl_cache_stats_count_hits_and_misses():
    cache = TTLCache(ttl=60, max_entries=10)
    cache.set("k", 1)
    cache.get("k")          # hit
    cache.get("k")          # hit
    cache.get("missing")    # miss
    stats = cache.stats()
    assert stats["hits"] == 2
    assert stats["misses"] == 1
    assert stats["entries"] == 1


def test_ttl_cache_set_with_custom_ttl():
    cache = TTLCache(ttl=60, max_entries=10)
    cache.set("k", "v", ttl=0.05)  # expires fast
    assert cache.get("k") == "v"
    import time

    time.sleep(0.06)
    assert cache.get("k", "expired") == "expired"


# ── CacheProxy: built-in in-process backend ────────────────────────────────

def test_proxy_uses_in_process_memory_backend():
    """The named-cache proxy is memory-only and exposes the full interface."""
    proxy = CacheProxy("probe_mem", ttl=60, max_entries=10)
    proxy.set("a", {"x": 1})
    assert proxy.get("a") == {"x": 1}
    assert proxy.get_or_set("b", lambda: 42) == 42
    calls = {"n": 0}

    def producer():
        calls["n"] += 1
        return "value"

    assert proxy.get_or_set("gk", producer) == "value"
    assert proxy.get_or_set("gk", producer) == "value"
    assert calls["n"] == 1, "producer must run once (cached)"
    assert proxy.invalidate("a") == 1
    assert proxy.get("a") is None
    assert proxy.stats()["backend"] == "memory"


# ── Invalidation semantics (regression: broad busts still correct) ──────────

def test_cache_bust_products_clears_product_keys(app):
    with app.app_context():
        from app.utils.cache import api_cache

        api_cache.set("product:123", {"id": 123})
        api_cache.set("products:search=a|page=1", [])
        api_cache.set("suppliers:all", [])  # must survive a product bust

        cache_bust_products()

        assert api_cache.get("product:123") is None
        assert api_cache.get("products:search=a|page=1") is None
        assert api_cache.get("suppliers:all") == [], "suppliers key must survive"


def test_make_key_prefix_and_falsy_skip():
    assert make_key(prefix="products", search="a", page=2, empty="") == (
        "products:page=2|search=a"
    )
    assert make_key(search="a") == "search=a"


