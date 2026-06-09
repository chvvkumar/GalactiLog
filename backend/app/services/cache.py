import json
import logging
from typing import Any, Awaitable, Callable

from app.config import async_redis

logger = logging.getLogger(__name__)


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
