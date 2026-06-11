"""Celery task: drain buffered log records from Redis into app_logs."""
from __future__ import annotations

import json
import logging
from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.config import settings, get_sync_redis
from app.models.app_log import AppLog
from app.services.log_capture import BUFFER_KEY
from app.worker.celery_app import celery_app

logger = logging.getLogger(__name__)

_sync_url = settings.database_url.replace("+asyncpg", "+psycopg2")
_sync_engine = create_engine(_sync_url, pool_pre_ping=True, pool_size=2, max_overflow=2, pool_recycle=1800)

_BATCH = 500
_MAX_ITERATIONS = 40  # cap one run at ~20k rows


def _drain_once(redis, batch: int = _BATCH) -> list[dict]:
    """RPOP up to ``batch`` oldest entries, return parsed dicts (malformed skipped)."""
    raw = redis.rpop(BUFFER_KEY, batch)
    if raw is None:
        return []
    if isinstance(raw, (str, bytes)):
        raw = [raw]
    rows = []
    for item in raw:
        try:
            rows.append(json.loads(item))
        except (ValueError, TypeError):
            continue
    return rows


def _parse_ts(value):
    """Parse an ISO timestamp string; return None on failure so the DB default applies."""
    if value is None:
        return None
    try:
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None


@celery_app.task(name="app.worker.drain_logs.drain_app_logs")
def drain_app_logs() -> dict:
    redis = get_sync_redis()
    total = 0
    try:
        for _ in range(_MAX_ITERATIONS):
            rows = _drain_once(redis, _BATCH)
            if not rows:
                break
            mappings = []
            for r in rows:
                mapping = {
                    "level": r.get("level", "info"),
                    "source": r.get("source", "api"),
                    "logger": (r.get("logger") or "")[:128],
                    "message": r.get("message", ""),
                    "traceback": r.get("traceback"),
                }
                ts = _parse_ts(r.get("timestamp"))
                if ts is not None:
                    mapping["timestamp"] = ts
                mappings.append(mapping)
            with Session(_sync_engine) as session:
                session.bulk_insert_mappings(AppLog, mappings)
                session.commit()
            total += len(rows)
            if len(rows) < _BATCH:
                break
        return {"status": "complete", "drained": total}
    except Exception as exc:
        logger.exception("drain_app_logs failed: %s", exc)
        return {"status": "error", "error": str(exc)}
    finally:
        try:
            redis.close()
        except Exception:
            pass
