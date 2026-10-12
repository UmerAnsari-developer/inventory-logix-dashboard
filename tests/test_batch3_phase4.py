"""Batch 3 Phase 4 tests: Redis cache layer fallback (GAP-003), hit/miss
stats, cache-status endpoint RBAC, and invalidation semantics."""
from __future__ import annotations

import pytest

from app.repositories import UserRepository
from app.utils.cache import CacheProxy, TTLCache, cache_bust_products, make_key


@pytest.fixture(autouse=True)
def _clean_caches():
    """Isolate the shared named caches between tests."""
    from app.utils.cache import cache_bust_all

    cache_bust_all()
    yield
    cache_bust_all()


def _session_client(app, username: str):
    """Authenticated client (proven pattern — client used OUTSIDE app_context)."""
    from flask_login.utils import _create_identifier

    with app.app_context():
        user = UserRepository.find_by_username(username)
        assert user is not None, f"missing user {username}"
        uid = user.id

    c = app.test_client()
    ident_box: dict = {}

    def _capture():
        ident_box["id"] = _create_identifier()

    app.before_request_funcs.setdefault(None, []).append(_capture)
    try:
        assert c.get("/static/img/favicon.svg").status_code == 200
    finally:
        app.before_request_funcs[None].remove(_capture)

    with c.session_transaction() as sess:
        sess["_user_id"] = str(uid)
        sess["_fresh"] = True
        sess["_id"] = ident_box["id"]
    return c


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


# ── CacheProxy: memory mode (flag off) ──────────────────────────────────────

def test_proxy_memory_mode_when_flag_off(app):
    """USE_REDIS_CACHE=False (TestingConfig) -> proxy uses the memory backend."""
    proxy = CacheProxy("probe_mem", ttl=60, max_entries=10)
    with app.app_context():
        assert proxy._resolve_redis() is None
        assert proxy._mode == "memory"

        proxy.set("a", {"x": 1})
        assert proxy.get("a") == {"x": 1}
        assert proxy.get_or_set("b", lambda: 42) == 42
        assert proxy.invalidate("a") == 1
        assert proxy.get("a") is None
        stats = proxy.stats()
        assert stats["backend"] == "memory"


# ── CacheProxy: graceful degradation (flag on, Redis unreachable) ───────────

def test_proxy_degrades_to_memory_when_redis_unreachable(app, monkeypatch):
    """Flag on + dead Redis -> proxy falls back to memory and still works."""
    proxy = CacheProxy("probe_dead", ttl=60, max_entries=10)
    with app.app_context():
        app.config["USE_REDIS_CACHE"] = True
        app.config["REDIS_CACHE_URL"] = "redis://127.0.0.1:6399/9"  # nothing there
        try:
            assert proxy._resolve_redis() is None
            assert proxy._mode == "memory"

            # Full interface works on the fallback
            proxy.set("k", [1, 2, 3])
            assert proxy.get("k") == [1, 2, 3]
            calls = {"n": 0}

            def producer():
                calls["n"] += 1
                return "value"

            assert proxy.get_or_set("gk", producer) == "value"
            assert proxy.get_or_set("gk", producer) == "value"
            assert calls["n"] == 1, "producer must run once (cached)"
            assert proxy.invalidate("gk") == 1
            assert proxy.get_or_set("gk", producer) == "value"
            assert calls["n"] == 2
        finally:
            app.config["USE_REDIS_CACHE"] = False


def test_proxy_degrades_midflight_on_redis_failure(app, monkeypatch):
    """A Redis error AFTER resolution permanently degrades to memory."""
    proxy = CacheProxy("probe_mid", ttl=60, max_entries=10)

    class _Broken:
        def get(self, key, default=None):
            raise ConnectionError("redis gone")

        def set(self, key, value, ttl=None):
            raise ConnectionError("redis gone")

        def get_or_set(self, key, producer):
            raise ConnectionError("redis gone")

        def invalidate(self, prefix):
            raise ConnectionError("redis gone")

        def clear(self):
            raise ConnectionError("redis gone")

        def stats(self):
            raise ConnectionError("redis gone")

    with app.app_context():
        app.config["USE_REDIS_CACHE"] = True
        try:
            proxy._redis = _Broken()
            proxy._mode = "redis"
            # First op fails -> degrade -> retried on memory
            assert proxy.get_or_set("k", lambda: "fallback") == "fallback"
            assert proxy._mode == "memory"
            assert proxy._redis is None
            # Subsequent ops go straight to memory
            proxy.set("k2", "v2")
            assert proxy.get("k2") == "v2"
        finally:
            app.config["USE_REDIS_CACHE"] = False


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


# ── Endpoint RBAC ───────────────────────────────────────────────────────────

def test_cache_status_endpoint_manager_ok_viewer_forbidden(app):
    manager_resp = _session_client(app, "manager").get("/ai/monitoring/cache-status")
    assert manager_resp.status_code == 200
    body = manager_resp.get_json()
    assert body["success"] is True
    data = body["data"]
    assert set(data) >= {"products", "api", "dashboard", "reports"}
    assert data["products"]["backend"] == "memory"  # hermetic test config

    viewer_resp = _session_client(app, "viewer").get("/ai/monitoring/cache-status")
    assert viewer_resp.status_code == 403