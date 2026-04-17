import time

from services.cache import TTLCache, cached


def test_set_and_get():
    c = TTLCache(maxsize=10, ttl=60)
    c.set("k", "v")
    assert c.get("k") == "v"


def test_missing():
    c = TTLCache()
    assert c.get("missing") is None


def test_ttl_expiry():
    c = TTLCache(maxsize=10, ttl=1)
    c.set("k", "v")
    assert c.get("k") == "v"
    time.sleep(1.2)
    assert c.get("k") is None


def test_lru_eviction():
    c = TTLCache(maxsize=2, ttl=60)
    c.set("a", 1)
    c.set("b", 2)
    c.get("a")  # makes "a" most recent
    c.set("c", 3)  # should evict "b"
    assert c.get("a") == 1
    assert c.get("b") is None
    assert c.get("c") == 3


def test_overwrite_preserves_recency():
    c = TTLCache(maxsize=2, ttl=60)
    c.set("a", 1)
    c.set("b", 2)
    c.set("a", 10)  # refresh "a"
    c.set("c", 3)   # should evict "b" not "a"
    assert c.get("a") == 10
    assert c.get("b") is None


def test_clear():
    c = TTLCache()
    c.set("k", "v")
    c.clear()
    assert c.get("k") is None
    assert len(c) == 0


def test_cached_decorator_hits_and_misses():
    c = TTLCache(maxsize=10, ttl=60)
    calls = {"n": 0}

    @cached(c, lambda x: f"key:{x}")
    def fn(x):
        calls["n"] += 1
        return x * 2

    assert fn(5) == 10
    assert fn(5) == 10
    assert calls["n"] == 1  # second call cached

    fn(7)
    assert calls["n"] == 2  # different key — new call


def test_cached_skips_none_results():
    c = TTLCache()

    @cached(c, lambda: "k")
    def fn_returns_none():
        return None

    fn_returns_none()
    assert c.get("k") is None
    assert len(c) == 0
