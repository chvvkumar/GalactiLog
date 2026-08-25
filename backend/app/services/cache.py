import json
import logging
from typing import Any, Awaitable, Callable

from app.config import async_redis

logger = logging.getLogger(__name__)

STATS_CACHE_KEY = "galactilog:stats:cache"
# GET /api/stats/guiding: per-rig PHD2 aggregates, invalidated with the rest
# of the stats caches whenever a scan, ingest, or guide-log pass runs.
GUIDING_STATS_CACHE_KEY = "galactilog:stats:guiding"
GUIDING_STATS_CACHE_TTL = 300
ANALYSIS_CACHE_PATTERN = "galactilog:analysis:*"
# Cached "this rig overall" frame-quality baselines (target-independent,
# grouped by normalized telescope|camera|filter over every LIGHT frame). This
# scan touched the entire images table on every session-card open; the result
# only changes when the catalog does, so it is cached here and invalidated by
# the catalog-mutating tasks (see worker.tasks._invalidate_stats_cache).
RIG_BASELINES_CACHE_KEY = "galactilog:rig_baselines:cache"
RIG_BASELINES_CACHE_TTL = 3600


async def invalidate_stats_and_analysis_cache() -> None:
    """Delete the stats cache and all analysis:* caches.

    Merge, unmerge, revert, and rename all mutate target names/membership but
    previously left the cached `/stats` response and `analysis:*` entries
    stale for up to their TTL (AUD-034). Call this after committing any of
    those mutations so the Statistics and Analysis pages reflect the new
    state on the next request instead of waiting out the cache TTL.

    Redis failures are caught and logged at DEBUG level, matching the
    read/write failure handling in `cached_json` above -- a cache
    invalidation failure must never turn into a 500 for the caller.
    """
    try:
        async with async_redis() as r:
            await r.delete(STATS_CACHE_KEY, GUIDING_STATS_CACHE_KEY)
            keys = [key async for key in r.scan_iter(match=ANALYSIS_CACHE_PATTERN)]
            if keys:
                await r.delete(*keys)
    except Exception:
        logger.debug("Redis cache invalidation failed for stats/analysis caches", exc_info=True)


async def cached_json(
    key: str,
    ttl: int,
    compute: Callable[[], Awaitable[Any]],
) -> Any:
    """Return JSON-serializable data from Redis cache, or compute and cache it.

    On cache hit, the stored value is JSON-decoded and returned.
    On cache miss, ``compute()`` is awaited, the result is JSON-encoded and
    stored with ``ttl`` seconds expiry, then the result is returned.

    Redis read/write failures are caught and logged at DEBUG level so that
    cache errors never break the request.
    """
    try:
        async with async_redis() as r:
            cached = await r.get(key)
        if cached:
            logger.debug("Cache hit: %s", key)
            return json.loads(cached)
    except Exception:
        logger.debug("Redis cache read failed for key %s", key)

    result = await compute()

    try:
        async with async_redis() as r:
            await r.setex(key, ttl, json.dumps(result))
        logger.debug("Cache set: %s (ttl=%d)", key, ttl)
    except Exception:
        logger.debug("Redis cache write failed for key %s", key)

    return result
