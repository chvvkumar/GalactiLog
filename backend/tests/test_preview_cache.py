from pathlib import Path

import pytest
import redis as sync_redis

from app.services.preview_cache import PreviewCache


@pytest.fixture
def redis_client():
    r = sync_redis.from_url("redis://localhost:6379/1", decode_responses=True)
    yield r
    for key in ("preview:lru", "preview:sizes", "preview:total_bytes"):
        r.delete(key)


@pytest.fixture
def cache_dir(tmp_path: Path) -> Path:
    d = tmp_path / "previews"
    d.mkdir()
    return d


def _make_file(cache_dir: Path, key: str, size: int) -> Path:
    p = cache_dir / key
    p.write_bytes(b"\0" * size)
    return p


def test_record_and_touch_updates_lru_score(redis_client, cache_dir):
    cache = PreviewCache(redis_client, cache_dir, cap_bytes=10_000)
    _make_file(cache_dir, "a.jpg", 100)
    cache.record("a.jpg", 100)
    first_score = redis_client.zscore("preview:lru", "a.jpg")
    assert first_score is not None

    cache.touch("a.jpg")
    second_score = redis_client.zscore("preview:lru", "a.jpg")
    assert second_score >= first_score


def test_total_bytes_tracks_usage(redis_client, cache_dir):
    cache = PreviewCache(redis_client, cache_dir, cap_bytes=10_000)
    _make_file(cache_dir, "a.jpg", 100)
    _make_file(cache_dir, "b.jpg", 200)
    cache.record("a.jpg", 100)
    cache.record("b.jpg", 200)
    assert cache.total_bytes() == 300


def test_eviction_drops_oldest_until_fits(redis_client, cache_dir):
    cache = PreviewCache(redis_client, cache_dir, cap_bytes=500)
    for key, size in [("a.jpg", 200), ("b.jpg", 200), ("c.jpg", 200)]:
        _make_file(cache_dir, key, size)
        cache.record(key, size)

    assert not (cache_dir / "a.jpg").exists()
    assert redis_client.zscore("preview:lru", "a.jpg") is None
    assert cache.total_bytes() == 400


def test_has_returns_true_for_cached_key(redis_client, cache_dir):
    cache = PreviewCache(redis_client, cache_dir, cap_bytes=10_000)
    _make_file(cache_dir, "a.jpg", 50)
    cache.record("a.jpg", 50)
    assert cache.has("a.jpg") is True
    assert cache.has("b.jpg") is False


def test_evict_noop_when_within_cap(redis_client, cache_dir):
    cache = PreviewCache(redis_client, cache_dir, cap_bytes=10_000)
    _make_file(cache_dir, "a.jpg", 100)
    cache.record("a.jpg", 100)
    cache.ensure_capacity_for(500)
    assert (cache_dir / "a.jpg").exists()


def test_record_same_key_twice_no_double_count(redis_client, cache_dir):
    cache = PreviewCache(redis_client, cache_dir, cap_bytes=10_000)
    _make_file(cache_dir, "a.jpg", 100)
    cache.record("a.jpg", 100)
    cache.record("a.jpg", 150)  # re-record with new size
    assert cache.total_bytes() == 150
    assert redis_client.hget("preview:sizes", "a.jpg") == "150"


def test_ensure_capacity_stops_when_no_progress(redis_client, cache_dir):
    """Drift scenario: TOTAL_KEY is high but no SIZES_KEY entries exist.

    Eviction cannot reduce TOTAL_KEY, so the loop must bail rather than
    drain the entire LRU set.
    """
    cache = PreviewCache(redis_client, cache_dir, cap_bytes=100)
    # Inject drift: LRU + TOTAL out of sync with SIZES (no size entries)
    redis_client.zadd("preview:lru", {"ghost1.jpg": 1.0, "ghost2.jpg": 2.0})
    redis_client.set("preview:total_bytes", 500)
    cache.ensure_capacity_for(50)
    # Loop should have evicted at most one entry before bailing
    remaining = redis_client.zcard("preview:lru")
    assert remaining >= 1  # did not drain the entire set


def test_reconcile_removes_orphans(redis_client, cache_dir):
    cache = PreviewCache(redis_client, cache_dir, cap_bytes=10_000)

    # Tracked but missing on disk
    redis_client.zadd("preview:lru", {"ghost.jpg": 1.0})
    redis_client.hset("preview:sizes", "ghost.jpg", 100)
    redis_client.set("preview:total_bytes", 100)

    # On disk but untracked
    _make_file(cache_dir, "stray.jpg", 50)

    # Legit tracked + present
    _make_file(cache_dir, "keep.jpg", 200)
    redis_client.zadd("preview:lru", {"keep.jpg": 2.0})
    redis_client.hset("preview:sizes", "keep.jpg", 200)
    redis_client.incrby("preview:total_bytes", 200)

    summary = cache.reconcile()
    assert summary["removed_orphan_metadata"] == 1
    assert summary["removed_orphan_files"] == 1
    assert summary["total_bytes"] == 200
    assert not (cache_dir / "stray.jpg").exists()
    assert (cache_dir / "keep.jpg").exists()
