"""Tests for app.services.cache.cached_json (ARCH-12)."""
import json
import pytest
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_cache_hit_returns_parsed_value():
    """On a cache hit, the stored JSON value is returned without calling compute."""
    payload = {"foo": "bar", "n": 42}

    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=json.dumps(payload))

    @asynccontextmanager
    async def _mock_async_redis():
        yield mock_redis

    compute = AsyncMock()

    with patch("app.services.cache.async_redis", _mock_async_redis):
        from app.services.cache import cached_json
        result = await cached_json("test:key", 60, compute)

    assert result == payload
    compute.assert_not_awaited()


@pytest.mark.asyncio
async def test_cache_miss_calls_compute_and_stores():
    """On a cache miss, compute() is called and the result is stored in Redis."""
    computed_value = {"hello": "world"}

    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=None)
    mock_redis.setex = AsyncMock()

    @asynccontextmanager
    async def _mock_async_redis():
        yield mock_redis

    compute = AsyncMock(return_value=computed_value)

    with patch("app.services.cache.async_redis", _mock_async_redis):
        from app.services.cache import cached_json
        result = await cached_json("test:key", 120, compute)

    assert result == computed_value
    compute.assert_awaited_once()
    mock_redis.setex.assert_awaited_once()
    stored_key, stored_ttl, stored_val = mock_redis.setex.await_args.args
    assert stored_key == "test:key"
    assert stored_ttl == 120
    assert json.loads(stored_val) == computed_value


@pytest.mark.asyncio
async def test_cache_read_error_falls_through_to_compute():
    """A Redis read failure must not raise; compute() is called instead."""
    computed_value = [1, 2, 3]

    call_count = 0

    @asynccontextmanager
    async def _mock_async_redis():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # First call (read): raise to simulate Redis unavailability.
            raise ConnectionError("redis down")
        mock_redis = AsyncMock()
        mock_redis.setex = AsyncMock()
        yield mock_redis

    compute = AsyncMock(return_value=computed_value)

    with patch("app.services.cache.async_redis", _mock_async_redis):
        from app.services.cache import cached_json
        result = await cached_json("test:key", 60, compute)

    assert result == computed_value
    compute.assert_awaited_once()


def _make_scan_iter(keys):
    """Return a callable matching AsyncRedis.scan_iter's async-generator signature."""
    async def _scan_iter(match=None):
        for k in keys:
            yield k
    return _scan_iter


@pytest.mark.asyncio
async def test_invalidate_stats_and_analysis_cache_deletes_both_key_families():
    """AUD-034: invalidation must delete the stats cache key and every
    galactilog:analysis:* key discovered via SCAN, not just one family."""
    analysis_keys = ["galactilog:analysis:correlation:abc", "galactilog:analysis:distribution:xyz"]

    mock_redis = AsyncMock()
    mock_redis.delete = AsyncMock()
    mock_redis.scan_iter = _make_scan_iter(analysis_keys)

    @asynccontextmanager
    async def _mock_async_redis():
        yield mock_redis

    with patch("app.services.cache.async_redis", _mock_async_redis):
        from app.services.cache import invalidate_stats_and_analysis_cache, GUIDING_STATS_CACHE_KEY, STATS_CACHE_KEY
        await invalidate_stats_and_analysis_cache()

    # First delete call clears the stats cache key.
    first_call_args = mock_redis.delete.await_args_list[0].args
    assert first_call_args == (STATS_CACHE_KEY, GUIDING_STATS_CACHE_KEY)
    # Second delete call clears every discovered analysis:* key.
    second_call_args = mock_redis.delete.await_args_list[1].args
    assert set(second_call_args) == set(analysis_keys)


@pytest.mark.asyncio
async def test_invalidate_stats_and_analysis_cache_no_analysis_keys_skips_second_delete():
    """When SCAN finds no analysis keys, only the stats cache delete runs."""
    mock_redis = AsyncMock()
    mock_redis.delete = AsyncMock()
    mock_redis.scan_iter = _make_scan_iter([])

    @asynccontextmanager
    async def _mock_async_redis():
        yield mock_redis

    with patch("app.services.cache.async_redis", _mock_async_redis):
        from app.services.cache import invalidate_stats_and_analysis_cache
        await invalidate_stats_and_analysis_cache()

    mock_redis.delete.assert_awaited_once()


@pytest.mark.asyncio
async def test_invalidate_stats_and_analysis_cache_swallows_redis_errors():
    """A Redis failure during invalidation must not raise (mirrors cached_json)."""
    @asynccontextmanager
    async def _mock_async_redis():
        raise ConnectionError("redis down")
        yield  # pragma: no cover - unreachable, keeps this an async generator

    with patch("app.services.cache.async_redis", _mock_async_redis):
        from app.services.cache import invalidate_stats_and_analysis_cache
        await invalidate_stats_and_analysis_cache()  # must not raise


@pytest.mark.asyncio
async def test_cache_write_error_does_not_raise():
    """A Redis write failure must not raise; the computed value is still returned."""
    computed_value = {"ok": True}

    mock_redis_read = AsyncMock()
    mock_redis_read.get = AsyncMock(return_value=None)

    call_count = 0

    @asynccontextmanager
    async def _mock_async_redis():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # First call: read miss.
            yield mock_redis_read
        else:
            # Second call: write failure.
            raise ConnectionError("redis down")

    compute = AsyncMock(return_value=computed_value)

    with patch("app.services.cache.async_redis", _mock_async_redis):
        from app.services.cache import cached_json
        result = await cached_json("test:key", 60, compute)

    assert result == computed_value
