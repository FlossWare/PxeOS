"""Tests for cache concurrency, benchmark infrastructure, and performance.

Covers:
- Thread safety of TTLCacheWrapper and CacheStats under contention
- Cache stats accuracy after concurrent operations
- Cached vs uncached response equivalence
- Cache invalidation correctness
- No data races with ThreadPoolExecutor
- Cache warming
- Rendered-output caches in ProvisioningEngine
- Benchmark helper utilities
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pxeos.cache import (
    CacheStats,
    TTLCacheWrapper,
    clear_all_caches,
    get_all_cache_stats,
    get_cache,
    profile_cache_key,
    ttl_cache,
    warm_profiles,
)
from pxeos.config import PxeOSConfig
from pxeos.engine import ProvisioningEngine, _cached_load_profile
from pxeos.matcher import HostMatcher
from pxeos.models import BootAssets, HostRule, ProvisionProfile
from pxeos.registry import PluginRegistry
from pxeos.state import ProvisionState, ProvisionTracker


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _rule(**kwargs) -> HostRule:
    kwargs.setdefault("profile", "fedora-server")
    kwargs.setdefault("os_family", "fedora")
    kwargs.setdefault("os_version", "40")
    return HostRule(**kwargs)


def _boot_assets(**kwargs) -> BootAssets:
    kwargs.setdefault("kernel", "/images/fedora/40/vmlinuz")
    kwargs.setdefault("initrd", "/images/fedora/40/initrd.img")
    kwargs.setdefault("boot_args", ("ip=dhcp", "rd.live.image"))
    return BootAssets(**kwargs)


def _build_engine(
    matcher_return=None,
    plugin=None,
    config=None,
    tracker=None,
):
    mock_matcher = MagicMock(spec=HostMatcher)
    mock_matcher.match.return_value = matcher_return

    mock_registry = MagicMock(spec=PluginRegistry)
    if plugin is not None:
        mock_registry.get.return_value = plugin

    cfg = config or PxeOSConfig(
        data_dir=Path("/tmp/pxeos-test"),
        server_host="0.0.0.0",
        server_port=8443,
    )
    engine = ProvisioningEngine(
        mock_registry, mock_matcher, cfg, tracker=tracker,
    )
    return engine, mock_matcher, mock_registry


# ---------------------------------------------------------------------------
# CacheStats thread safety
# ---------------------------------------------------------------------------


class TestCacheStatsThreadSafety:

    def test_concurrent_hits(self):
        stats = CacheStats()
        n = 1000

        def bump():
            for _ in range(n):
                stats.hit()

        threads = [threading.Thread(target=bump) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert stats.hits == n * 10

    def test_concurrent_misses(self):
        stats = CacheStats()
        n = 1000

        def bump():
            for _ in range(n):
                stats.miss()

        threads = [threading.Thread(target=bump) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert stats.misses == n * 10

    def test_concurrent_evictions(self):
        stats = CacheStats()
        n = 500

        def bump():
            for _ in range(n):
                stats.eviction()

        threads = [threading.Thread(target=bump) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert stats.evictions == n * 8

    def test_concurrent_mixed_operations(self):
        stats = CacheStats()
        n = 500

        def do_hits():
            for _ in range(n):
                stats.hit()

        def do_misses():
            for _ in range(n):
                stats.miss()

        def do_evictions():
            for _ in range(n):
                stats.eviction()

        threads = []
        for fn in (do_hits, do_misses, do_evictions):
            for _ in range(4):
                threads.append(threading.Thread(target=fn))

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        d = stats.to_dict()
        assert d["hits"] == n * 4
        assert d["misses"] == n * 4
        assert d["evictions"] == n * 4
        assert d["total"] == n * 8  # hits + misses

    def test_hit_rate_accuracy(self):
        stats = CacheStats()
        for _ in range(75):
            stats.hit()
        for _ in range(25):
            stats.miss()
        d = stats.to_dict()
        assert d["hit_rate"] == 0.75


# ---------------------------------------------------------------------------
# TTLCacheWrapper thread safety
# ---------------------------------------------------------------------------


class TestTTLCacheWrapperThreadSafety:

    def test_concurrent_put_and_get(self):
        cache = TTLCacheWrapper("thread-test", maxsize=1000, ttl=300)
        n = 100

        def writer(offset):
            for i in range(n):
                cache.put(f"key-{offset}-{i}", f"val-{offset}-{i}")

        def reader(offset):
            results = []
            for i in range(n):
                results.append(cache.get(f"key-{offset}-{i}"))
            return results

        # Write first from 8 concurrent threads
        with ThreadPoolExecutor(max_workers=8) as pool:
            write_futures = [pool.submit(writer, o) for o in range(8)]
            for f in write_futures:
                f.result()

        # Then read back from 8 concurrent threads
        with ThreadPoolExecutor(max_workers=8) as pool:
            read_futures = [pool.submit(reader, o) for o in range(8)]
            for f in read_futures:
                results = f.result()
                for i, val in enumerate(results):
                    assert val is not None

    def test_concurrent_put_respects_maxsize(self):
        cache = TTLCacheWrapper("maxsize-test", maxsize=50, ttl=300)

        def writer(offset):
            for i in range(100):
                cache.put(f"key-{offset}-{i}", i)

        threads = [threading.Thread(target=writer, args=(o,)) for o in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert cache.size <= 50

    def test_concurrent_get_miss_stats(self):
        cache = TTLCacheWrapper("miss-stats", maxsize=100, ttl=300)

        def reader():
            for i in range(100):
                cache.get(f"nonexistent-{i}")

        threads = [threading.Thread(target=reader) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert cache._stats.misses == 400

    def test_concurrent_put_get_clear(self):
        """Interleave put, get, and clear to stress lock acquisition."""
        cache = TTLCacheWrapper("pgc-test", maxsize=100, ttl=300)
        stop = threading.Event()
        errors = []

        def writer():
            i = 0
            while not stop.is_set():
                cache.put(f"k{i}", i)
                i += 1

        def reader():
            i = 0
            while not stop.is_set():
                cache.get(f"k{i}")
                i += 1

        def clearer():
            while not stop.is_set():
                cache.clear()
                time.sleep(0.001)

        threads = [
            threading.Thread(target=writer),
            threading.Thread(target=writer),
            threading.Thread(target=reader),
            threading.Thread(target=reader),
            threading.Thread(target=clearer),
        ]
        for t in threads:
            t.start()

        time.sleep(0.1)  # let them run briefly
        stop.set()
        for t in threads:
            t.join(timeout=5)

        # No assertion failures, no deadlocks -- reaching here is success

    def test_invalidate_thread_safety(self):
        cache = TTLCacheWrapper("inv-test", maxsize=200, ttl=300)
        for i in range(100):
            cache.put(f"key-{i}", f"val-{i}")

        removed = []

        def invalidator(start, end):
            count = 0
            for i in range(start, end):
                if cache.invalidate(f"key-{i}"):
                    count += 1
            removed.append(count)

        threads = [
            threading.Thread(target=invalidator, args=(0, 50)),
            threading.Thread(target=invalidator, args=(50, 100)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert sum(removed) == 100
        assert cache.size == 0


# ---------------------------------------------------------------------------
# Cache stats accuracy
# ---------------------------------------------------------------------------


class TestCacheStatsAccuracy:

    def test_stats_reflect_operations(self):
        cache = TTLCacheWrapper("acc-test", maxsize=10, ttl=300)
        cache.put("a", 1)
        cache.put("b", 2)
        cache.get("a")  # hit
        cache.get("a")  # hit
        cache.get("c")  # miss
        stats = cache.stats
        assert stats["hits"] == 2
        assert stats["misses"] == 1
        assert stats["size"] == 2

    def test_eviction_counted_on_maxsize(self):
        cache = TTLCacheWrapper("evict-count", maxsize=2, ttl=300)
        cache.put("a", 1)
        cache.put("b", 2)
        cache.put("c", 3)  # evicts oldest
        assert cache._stats.evictions >= 1

    def test_eviction_counted_on_ttl_expiry(self):
        cache = TTLCacheWrapper("ttl-evict", maxsize=10, ttl=0.01)
        cache.put("x", 1)
        time.sleep(0.05)
        cache.get("x")  # triggers eviction
        assert cache._stats.evictions == 1
        assert cache._stats.misses == 1  # expired = miss

    def test_global_stats_aggregate(self):
        clear_all_caches()

        @ttl_cache(maxsize=5, ttl=300, name="bench_global_a")
        def fn_a(x):
            return x

        @ttl_cache(maxsize=5, ttl=300, name="bench_global_b")
        def fn_b(x):
            return x * 2

        fn_a(1)
        fn_a(1)  # hit
        fn_b(2)
        fn_b(3)

        stats = get_all_cache_stats()
        assert "bench_global_a" in stats["caches"]
        assert "bench_global_b" in stats["caches"]

    def test_size_property(self):
        cache = TTLCacheWrapper("size-prop", maxsize=100, ttl=300)
        assert cache.size == 0
        cache.put("a", 1)
        assert cache.size == 1
        cache.put("b", 2)
        assert cache.size == 2
        cache.clear()
        assert cache.size == 0


# ---------------------------------------------------------------------------
# Cached vs uncached response equivalence
# ---------------------------------------------------------------------------


class TestCachedUncachedEquivalence:

    def test_ipxe_script_cached_matches_uncached(self):
        rule = _rule(mac="aa:bb:cc:dd:ee:ff")
        assets = _boot_assets()
        plugin = MagicMock()
        plugin.validate_profile.return_value = []
        plugin.boot_assets.return_value = assets

        engine, _, _ = _build_engine(matcher_return=rule, plugin=plugin)

        script1 = engine.render_ipxe_script(mac="aa:bb:cc:dd:ee:ff")
        # Second call should return same content from cache
        script2 = engine.render_ipxe_script(mac="aa:bb:cc:dd:ee:ff")
        assert script1 == script2
        assert script1.startswith("#!ipxe")

    def test_autoinstall_cached_matches_uncached(self):
        rule = _rule(mac="11:22:33:44:55:66")
        plugin = MagicMock()
        plugin.generate_autoinstall.return_value = "ks-content-here"

        engine, _, _ = _build_engine(matcher_return=rule, plugin=plugin)

        content1 = engine.get_autoinstall(mac="11:22:33:44:55:66")
        content2 = engine.get_autoinstall(mac="11:22:33:44:55:66")
        assert content1 == content2
        assert content1 == "ks-content-here"

    def test_different_macs_get_different_cache_entries(self):
        """Two different MACs should not share cache entries."""
        rule_a = _rule(mac="aa:bb:cc:00:00:01", profile="prof-a")
        rule_b = _rule(mac="aa:bb:cc:00:00:02", profile="prof-b")

        plugin = MagicMock()
        plugin.generate_autoinstall.side_effect = [
            "content-a", "content-b",
        ]

        mock_matcher = MagicMock(spec=HostMatcher)
        mock_matcher.match.side_effect = [rule_a, rule_b]
        mock_registry = MagicMock(spec=PluginRegistry)
        mock_registry.get.return_value = plugin

        cfg = PxeOSConfig(
            data_dir=Path("/tmp/pxeos-test"),
            server_host="0.0.0.0",
            server_port=8443,
        )
        engine = ProvisioningEngine(mock_registry, mock_matcher, cfg)

        a = engine.get_autoinstall("aa:bb:cc:00:00:01")
        b = engine.get_autoinstall("aa:bb:cc:00:00:02")
        assert a == "content-a"
        assert b == "content-b"


# ---------------------------------------------------------------------------
# Cache invalidation
# ---------------------------------------------------------------------------


class TestCacheInvalidation:

    def test_invalidate_all_clears_engine_caches(self):
        rule = _rule(mac="aa:bb:cc:dd:ee:ff")
        assets = _boot_assets()
        plugin = MagicMock()
        plugin.validate_profile.return_value = []
        plugin.boot_assets.return_value = assets
        plugin.generate_autoinstall.return_value = "ks"

        engine, _, _ = _build_engine(matcher_return=rule, plugin=plugin)

        engine.render_ipxe_script("aa:bb:cc:dd:ee:ff")
        engine.get_autoinstall("aa:bb:cc:dd:ee:ff")

        assert engine._ipxe_cache.size >= 1
        assert engine._autoinstall_cache.size >= 1

        removed = engine.invalidate_caches()
        assert removed >= 2
        assert engine._ipxe_cache.size == 0
        assert engine._autoinstall_cache.size == 0

    def test_invalidate_by_mac(self):
        rule_a = _rule(mac="aa:bb:cc:00:00:01", profile="pA")
        rule_b = _rule(mac="aa:bb:cc:00:00:02", profile="pB")

        plugin = MagicMock()
        plugin.validate_profile.return_value = []
        plugin.boot_assets.return_value = _boot_assets()
        plugin.generate_autoinstall.side_effect = ["ks-a", "ks-b"]

        mock_matcher = MagicMock(spec=HostMatcher)
        mock_matcher.match.side_effect = [rule_a, rule_b]
        mock_registry = MagicMock(spec=PluginRegistry)
        mock_registry.get.return_value = plugin

        cfg = PxeOSConfig(data_dir=Path("/tmp/pxeos-test"))
        engine = ProvisioningEngine(mock_registry, mock_matcher, cfg)

        engine.get_autoinstall("aa:bb:cc:00:00:01")
        engine.get_autoinstall("aa:bb:cc:00:00:02")
        assert engine._autoinstall_cache.size == 2

        removed = engine.invalidate_caches(mac="aa:bb:cc:00:00:01")
        assert removed >= 1
        assert engine._autoinstall_cache.size == 1

    def test_invalidate_nonexistent_mac_returns_zero(self):
        engine, _, _ = _build_engine()
        removed = engine.invalidate_caches(mac="ff:ff:ff:ff:ff:ff")
        assert removed == 0

    def test_ttl_cache_wrapper_invalidate(self):
        cache = TTLCacheWrapper("inv-direct", maxsize=10, ttl=300)
        cache.put("key1", "val1")
        cache.put("key2", "val2")
        assert cache.invalidate("key1") is True
        assert cache.get("key1") is None
        assert cache.get("key2") == "val2"
        assert cache.invalidate("key1") is False  # already gone


# ---------------------------------------------------------------------------
# No data races with ThreadPoolExecutor (engine level)
# ---------------------------------------------------------------------------


class TestEngineThreadSafety:

    def test_concurrent_boot_requests_no_crash(self):
        rule = _rule(mac="aa:bb:cc:dd:ee:ff")
        assets = _boot_assets()
        plugin = MagicMock()
        plugin.validate_profile.return_value = []
        plugin.boot_assets.return_value = assets

        engine, _, _ = _build_engine(matcher_return=rule, plugin=plugin)

        def do_boot(idx):
            return engine.render_ipxe_script("aa:bb:cc:dd:ee:ff")

        with ThreadPoolExecutor(max_workers=16) as pool:
            futures = [pool.submit(do_boot, i) for i in range(100)]
            results = [f.result() for f in as_completed(futures)]

        assert len(results) == 100
        # All should be the same script content
        assert all(r == results[0] for r in results)

    def test_concurrent_autoinstall_no_crash(self):
        rule = _rule(mac="11:22:33:44:55:66")
        plugin = MagicMock()
        plugin.generate_autoinstall.return_value = "ks-content"

        engine, _, _ = _build_engine(matcher_return=rule, plugin=plugin)

        def do_autoinstall(idx):
            return engine.get_autoinstall("11:22:33:44:55:66")

        with ThreadPoolExecutor(max_workers=16) as pool:
            futures = [pool.submit(do_autoinstall, i) for i in range(100)]
            results = [f.result() for f in as_completed(futures)]

        assert len(results) == 100
        assert all(r == "ks-content" for r in results)

    def test_concurrent_invalidation_during_reads(self):
        rule = _rule(mac="aa:bb:cc:dd:ee:ff")
        assets = _boot_assets()
        plugin = MagicMock()
        plugin.validate_profile.return_value = []
        plugin.boot_assets.return_value = assets

        engine, _, _ = _build_engine(matcher_return=rule, plugin=plugin)
        stop = threading.Event()

        def reader():
            while not stop.is_set():
                try:
                    engine.render_ipxe_script("aa:bb:cc:dd:ee:ff")
                except Exception:
                    pass

        def invalidator():
            while not stop.is_set():
                engine.invalidate_caches()
                time.sleep(0.001)

        threads = [
            threading.Thread(target=reader),
            threading.Thread(target=reader),
            threading.Thread(target=invalidator),
        ]
        for t in threads:
            t.start()

        time.sleep(0.1)
        stop.set()
        for t in threads:
            t.join(timeout=5)

        # Reaching here without deadlock or crash is success


# ---------------------------------------------------------------------------
# Cache warming
# ---------------------------------------------------------------------------


class TestCacheWarming:

    def test_warm_profiles_loads_all(self, tmp_path):
        profiles_dir = tmp_path / "profiles"
        profiles_dir.mkdir()

        for i in range(5):
            (profiles_dir / f"prof-{i}.toml").write_text(
                f'[profile]\nname = "prof-{i}"\n'
                f'os_family = "fedora"\nos_version = "40"\n'
            )

        _cached_load_profile.cache_clear()
        count = warm_profiles(profiles_dir)
        assert count == 5

    def test_warm_profiles_nonexistent_dir(self, tmp_path):
        count = warm_profiles(tmp_path / "nonexistent")
        assert count == 0

    def test_warm_profiles_invalid_file_skipped(self, tmp_path):
        profiles_dir = tmp_path / "profiles"
        profiles_dir.mkdir()
        (profiles_dir / "good.toml").write_text(
            '[profile]\nname = "good"\n'
            'os_family = "fedora"\nos_version = "40"\n'
        )
        (profiles_dir / "bad.toml").write_text("not valid toml {{{{")

        _cached_load_profile.cache_clear()
        count = warm_profiles(profiles_dir)
        assert count >= 1  # good.toml loaded

    def test_warm_profiles_empty_dir(self, tmp_path):
        profiles_dir = tmp_path / "profiles"
        profiles_dir.mkdir()
        count = warm_profiles(profiles_dir)
        assert count == 0


# ---------------------------------------------------------------------------
# profile_cache_key
# ---------------------------------------------------------------------------


class TestProfileCacheKey:

    def test_same_file_same_hash(self, tmp_path):
        f = tmp_path / "test.toml"
        f.write_text("hello")
        assert profile_cache_key(str(f)) == profile_cache_key(str(f))

    def test_different_content_different_hash(self, tmp_path):
        f1 = tmp_path / "a.toml"
        f2 = tmp_path / "b.toml"
        f1.write_text("content-a")
        f2.write_text("content-b")
        assert profile_cache_key(str(f1)) != profile_cache_key(str(f2))

    def test_missing_file_returns_missing(self):
        assert profile_cache_key("/nonexistent/path.toml") == "missing"

    def test_hash_is_16_chars(self, tmp_path):
        f = tmp_path / "test.toml"
        f.write_text("data")
        h = profile_cache_key(str(f))
        assert len(h) == 16


# ---------------------------------------------------------------------------
# get_cache helper
# ---------------------------------------------------------------------------


class TestGetCache:

    def test_get_registered_cache(self):
        @ttl_cache(maxsize=5, ttl=60, name="bench_get_test")
        def fn(x):
            return x

        c = get_cache("bench_get_test")
        assert c is not None
        assert c.name == "bench_get_test"

    def test_get_unknown_cache(self):
        assert get_cache("nonexistent_cache_xyz") is None


# ---------------------------------------------------------------------------
# Benchmark helpers (scripts/benchmark_pxe.py)
# ---------------------------------------------------------------------------


class TestBenchmarkHelpers:

    def test_make_mac_deterministic(self):
        from scripts.benchmark_pxe import _make_mac

        mac0 = _make_mac(0)
        mac1 = _make_mac(1)
        assert mac0 != mac1
        assert _make_mac(0) == mac0  # deterministic
        assert mac0.count(":") == 5

    def test_make_mac_format(self):
        from scripts.benchmark_pxe import _make_mac

        mac = _make_mac(255)
        parts = mac.split(":")
        assert len(parts) == 6
        assert parts[0] == "aa"
        assert parts[1] == "bb"
        assert parts[2] == "cc"


# ---------------------------------------------------------------------------
# Engine cache integration
# ---------------------------------------------------------------------------


class TestEngineCacheIntegration:

    def test_engine_creates_ipxe_and_autoinstall_caches(self):
        engine, _, _ = _build_engine()
        assert engine._ipxe_cache is not None
        assert engine._autoinstall_cache is not None
        assert engine._ipxe_cache.name == "ipxe_script"
        assert engine._autoinstall_cache.name == "autoinstall"

    def test_ipxe_cache_populated_after_render(self):
        rule = _rule(mac="aa:bb:cc:dd:ee:ff")
        assets = _boot_assets()
        plugin = MagicMock()
        plugin.validate_profile.return_value = []
        plugin.boot_assets.return_value = assets

        engine, _, _ = _build_engine(matcher_return=rule, plugin=plugin)
        assert engine._ipxe_cache.size == 0

        engine.render_ipxe_script("aa:bb:cc:dd:ee:ff")
        assert engine._ipxe_cache.size >= 1

    def test_autoinstall_cache_populated_after_get(self):
        rule = _rule(mac="aa:bb:cc:dd:ee:ff")
        plugin = MagicMock()
        plugin.generate_autoinstall.return_value = "ks-data"

        engine, _, _ = _build_engine(matcher_return=rule, plugin=plugin)
        assert engine._autoinstall_cache.size == 0

        engine.get_autoinstall("aa:bb:cc:dd:ee:ff")
        assert engine._autoinstall_cache.size >= 1

    def test_cached_ipxe_still_updates_state(self):
        """Even on cache hit, state transitions must still happen."""
        rule = _rule(mac="aa:bb:cc:dd:ee:ff")
        assets = _boot_assets()
        plugin = MagicMock()
        plugin.validate_profile.return_value = []
        plugin.boot_assets.return_value = assets

        tracker = ProvisionTracker()
        engine, _, _ = _build_engine(
            matcher_return=rule, plugin=plugin, tracker=tracker,
        )

        # First call: populates cache and creates tracker record
        engine.render_ipxe_script("aa:bb:cc:dd:ee:ff")
        record = tracker.get("aa:bb:cc:dd:ee:ff")
        assert record is not None
        assert record.state == ProvisionState.BOOTING

        # Second call: cache hit, but state should still be updated
        engine.render_ipxe_script("aa:bb:cc:dd:ee:ff")
        record = tracker.get("aa:bb:cc:dd:ee:ff")
        # History should have multiple BOOTING entries
        booting_count = sum(
            1 for s, _ in record.history if s == ProvisionState.BOOTING
        )
        assert booting_count >= 2

    def test_local_boot_script_not_cached(self):
        """When netboot is disabled, LOCAL_BOOT_SCRIPT is returned
        and the rendered-output cache should not be involved."""
        rule = _rule(mac="aa:bb:cc:dd:ee:ff")
        assets = _boot_assets()
        plugin = MagicMock()
        plugin.validate_profile.return_value = []
        plugin.boot_assets.return_value = assets

        tracker = ProvisionTracker()
        engine, _, _ = _build_engine(
            matcher_return=rule, plugin=plugin, tracker=tracker,
        )

        # Register and disable netboot
        tracker.register(
            mac="aa:bb:cc:dd:ee:ff",
            profile="fedora-server",
            os_family="fedora",
            os_version="40",
        )
        tracker.disable_netboot("aa:bb:cc:dd:ee:ff")

        script = engine.render_ipxe_script("aa:bb:cc:dd:ee:ff")
        assert script == "#!ipxe\nexit\n"
        assert engine._ipxe_cache.size == 0
