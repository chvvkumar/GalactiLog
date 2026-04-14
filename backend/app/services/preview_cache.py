import time
from pathlib import Path

import redis as sync_redis


LRU_KEY = "preview:lru"
SIZES_KEY = "preview:sizes"
TOTAL_KEY = "preview:total_bytes"


class PreviewCache:
    """Redis-backed LRU cache manager for on-disk preview JPEGs.

    Tracks access time in a sorted set (score = unix ts, member = cache key)
    and per-key sizes in a hash. Evicts oldest entries until a new write fits
    within the byte cap. Size accounting is authoritative via Redis; the total
    can be reconciled against on-disk reality by a separate housekeeping pass.
    """

    def __init__(self, redis: sync_redis.Redis, cache_dir: Path, cap_bytes: int):
        self.redis = redis
        self.cache_dir = cache_dir
        self.cap_bytes = cap_bytes

    def has(self, key: str) -> bool:
        return self.redis.zscore(LRU_KEY, key) is not None

    def touch(self, key: str) -> None:
        self.redis.zadd(LRU_KEY, {key: time.time()})

    def total_bytes(self) -> int:
        val = self.redis.get(TOTAL_KEY)
        return int(val) if val else 0

    def record(self, key: str, size: int) -> None:
        """Register a just-written cache file.

        Evicts oldest entries first if needed to fit within cap.
        """
        self.ensure_capacity_for(size)
        self.redis.zadd(LRU_KEY, {key: time.time()})
        self.redis.hset(SIZES_KEY, key, size)
        self.redis.incrby(TOTAL_KEY, size)

    def ensure_capacity_for(self, new_size: int) -> None:
        """Evict oldest entries until `total + new_size <= cap`."""
        while self.total_bytes() + new_size > self.cap_bytes:
            oldest = self.redis.zrange(LRU_KEY, 0, 0)
            if not oldest:
                return
            key = oldest[0]
            self._evict(key)

    def _evict(self, key: str) -> None:
        size_str = self.redis.hget(SIZES_KEY, key)
        size = int(size_str) if size_str else 0
        path = self.cache_dir / key
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        self.redis.zrem(LRU_KEY, key)
        self.redis.hdel(SIZES_KEY, key)
        self.redis.decrby(TOTAL_KEY, size)
