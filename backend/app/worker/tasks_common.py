"""Shared infrastructure for the app.worker.tasks_* domain modules.

Constructs the single sync SQLAlchemy engine and single sync Redis client used
by every Celery worker task, plus the small set of helpers (activity-session
factory, stats-cache invalidation) shared across 3+ domains. Every domain
module imports `_sync_engine` / `_redis` from here rather than constructing
its own -- there must be exactly one connection pool and one Redis client per
worker process, not one per domain module.
"""
import logging

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.config import settings, get_sync_redis

logger = logging.getLogger(__name__)

# Celery uses sync - create a sync engine for the worker
# Replace asyncpg with psycopg2 for sync operations
_sync_url = settings.database_url.replace("+asyncpg", "+psycopg2")
_sync_engine = create_engine(_sync_url, pool_pre_ping=True, pool_size=2, max_overflow=2, pool_recycle=1800)

_redis = get_sync_redis()


def _activity_session():
    """Return a context-managed sync Session for activity writes in Celery tasks."""
    return Session(_sync_engine)


def _invalidate_stats_cache():
    """Delete cached aggregates from Redis so the next request recomputes them.

    Covers the /stats response, the fits-keys list, and the catalog-wide "this
    rig overall" frame-quality baselines used by the session-detail endpoint --
    all of which are derived from the images table and go stale when a scan,
    rebuild, or ingest changes it.
    """
    try:
        _redis.delete(
            "galactilog:stats:cache",
            "galactilog:stats:guiding",
            "galactilog:fits_keys",
            "galactilog:rig_baselines:cache",
        )
    except Exception:
        logger.debug("_invalidate_stats_cache: Redis delete failed", exc_info=True)
