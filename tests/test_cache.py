"""Self-check for TTLCache: expiry, LRU eviction, prefix invalidation, thread safety."""
import sys
import time
import threading

sys.path.insert(0, ".")

from app.utils.cache import TTLCache, make_key, cache_bust_all, cache_bust_products


def test_basic():
    c = TTLCache(ttl=60, max_entries=5)
    c.set("a", 1)
    assert c.get("a") == 1
    assert c.get("missing") is None
    assert c.get("missing", "dflt") == "dflt"
    print("PASS basic get/set/miss-default")


def test_ttl_expiry():
    c = TTLCache(ttl=0.05, max_entries=5)
    c.set("k", "v")
    assert c.get("k") == "v"
    time.sleep(0.06)
    assert c.get("k") is None, "entry should expire after ttl"
    print("PASS ttl expiry")


def test_lru_eviction():
    c = TTLCache(ttl=60, max_entries=3)
    c.set("a", 1)
    c.set("b", 2)
    c.set("c", 3)
    c.get("a")              # touch a -> b is now LRU
    c.set("d", 4)           # evicts b
    assert c.get("b") is None, "LRU entry should be evicted"
    assert c.get("a") == 1 and c.get("c") == 3 and c.get("d") == 4
    print("PASS lru eviction")


def test_prefix_invalidation():
    c = TTLCache(ttl=60, max_entries=10)
    c.set("products:1", "x")
    c.set("products:2", "y")
    c.set("suppliers:1", "z")
    dropped = c.invalidate("products")
    assert dropped == 2
    assert c.get("products:1") is None and c.get("products:2") is None
    assert c.get("suppliers:1") == "z"
    print("PASS prefix invalidation")


def test_get_or_set():
    c = TTLCache(ttl=60, max_entries=5)
    calls = []
    def producer():
        calls.append(1)
        return "expensive"
    assert c.get_or_set("k", producer) == "expensive"
    assert c.get_or_set("k", producer) == "expensive"
    assert len(calls) == 1, "producer must run exactly once"
    print("PASS get_or_set read-through")


def test_thread_safety():
    c = TTLCache(ttl=60, max_entries=100)
    errors = []
    def worker(n):
        try:
            for i in range(200):
                c.set(f"k{n}-{i}", i)
                c.get(f"k{n}-{i}")
                c.invalidate("k0")
        except Exception as e:
            errors.append(e)
    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors, f"thread errors: {errors}"
    print("PASS thread safety (8 threads x 200 ops)")


def test_make_key():
    assert make_key(a="1", b="", c="x") == "a=1|c=x"
    assert make_key(a="1", c="x") == make_key(c="x", a="1")
    print("PASS make_key deterministic + skips falsy")


def test_bust_helpers():
    from app.utils import cache as mod
    mod.products_cache.set("foo", 1)
    mod.dashboard_cache.set("bar", 2)
    n = cache_bust_products()
    assert n >= 2 and mod.products_cache.get("foo") is None
    print("PASS cache_bust helpers clear cross-caches")


if __name__ == "__main__":
    test_basic()
    test_ttl_expiry()
    test_lru_eviction()
    test_prefix_invalidation()
    test_get_or_set()
    test_thread_safety()
    test_make_key()
    test_bust_helpers()
    cache_bust_all()
    print("\nAll TTLCache checks passed.")
