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

        Evicts oldest entries first if needed to fit within cap. Safe to call
        with an already-tracked key (updates size and accounting atomically).
        """
        self.ensure_capacity_for(size)
        old = self.redis.hget(SIZES_KEY, key)
        old_size = int(old) if old else 0
        pipe = self.redis.pipeline()
        pipe.zadd(LRU_KEY, {key: time.time()})
        pipe.hset(SIZES_KEY, key, size)
        pipe.incrby(TOTAL_KEY, size - old_size)
        pipe.execute()

    def ensure_capacity_for(self, new_size: int) -> None:
        """Evict oldest entries until `total + new_size <= cap`.

        Breaks out if no progress is made (guards against metadata drift).
        """
        while self.total_bytes() + new_size > self.cap_bytes:
            oldest = self.redis.zrange(LRU_KEY, 0, 0)
            if not oldest:
                return
            key = oldest[0]
            before = self.total_bytes()
            self._evict(key)
            if self.total_bytes() >= before:
                # No progress — likely size metadata drift. Stop evicting.
                return

    def _evict(self, key: str) -> None:
        size_str = self.redis.hget(SIZES_KEY, key)
        size = int(size_str) if size_str else 0
        path = self.cache_dir / key
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        pipe = self.redis.pipeline()
        pipe.zrem(LRU_KEY, key)
        pipe.hdel(SIZES_KEY, key)
        pipe.decrby(TOTAL_KEY, size)
        pipe.execute()

    def reconcile(self) -> dict:
        """Reconcile Redis metadata against on-disk files.

        Removes metadata for files missing on disk. Removes on-disk files
        without metadata. Recomputes total_bytes from hash values.
        Returns a dict summary.
        """
        if not self.cache_dir.exists():
            return {"removed_orphan_metadata": 0, "removed_orphan_files": 0}

        tracked_keys = set(self.redis.hkeys(SIZES_KEY))
        on_disk = {p.name for p in self.cache_dir.iterdir() if p.is_file() and not p.name.startswith(".")}

        orphan_meta = tracked_keys - on_disk
        for key in orphan_meta:
            self.redis.zrem(LRU_KEY, key)
            self.redis.hdel(SIZES_KEY, key)

        orphan_files = on_disk - tracked_keys
        for name in orphan_files:
            try:
                (self.cache_dir / name).unlink(missing_ok=True)
            except OSError:
                pass

        remaining = self.redis.hgetall(SIZES_KEY)
        total = sum(int(v) for v in remaining.values())
        self.redis.set(TOTAL_KEY, total)

        return {
            "removed_orphan_metadata": len(orphan_meta),
            "removed_orphan_files": len(orphan_files),
            "total_bytes": total,
        }
