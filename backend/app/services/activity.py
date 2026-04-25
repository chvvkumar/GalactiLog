"""Activity event emit helpers.

emit()      - async, for FastAPI route handlers.
emit_sync() - sync, for Celery tasks.

Neither function raises to the caller (except for validation errors in
development env). Failures are logged only.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.config import async_redis
from app.models.activity_event import ActivityEvent

logger = logging.getLogger(__name__)

VALID_SEVERITIES = frozenset({"info", "warning", "error"})
VALID_CATEGORIES = frozenset({
    "scan", "rebuild", "thumbnail", "enrichment",
    "mosaic", "migration", "user_action", "system",
})

_ENV = os.environ.get("GALACTILOG_ENV", "production")


def _validate(severity: str, category: str) -> bool:
    ok = True
    if severity not in VALID_SEVERITIES:
        msg = f"Invalid severity '{severity}'. Must be one of {sorted(VALID_SEVERITIES)}"
        if _ENV == "development":
            raise ValueError(msg)
        logger.warning("activity.emit: %s", msg)
        ok = False
    if category not in VALID_CATEGORIES:
        msg = f"Invalid category '{category}'. Must be one of {sorted(VALID_CATEGORIES)}"
        if _ENV == "development":
            raise ValueError(msg)
        logger.warning("activity.emit: %s", msg)
        ok = False
    return ok


def _build_event(
    *,
    category: str,
    severity: str,
    event_type: str,
    message: str,
    details: dict[str, Any] | None = None,
    target_id: UUID | None = None,
    actor: str | None = None,
    duration_ms: int | None = None,
    parent_id: int | None = None,
) -> ActivityEvent:
    return ActivityEvent(
        severity=severity,
        category=category,
        event_type=event_type,
        message=message,
        details=details,
        target_id=target_id,
        actor=actor,
        duration_ms=duration_ms,
        parent_id=parent_id,
    )


def _pubsub_payload(event: ActivityEvent) -> str:
    return json.dumps({
        "event_type": event.event_type,
        "severity": event.severity,
        "category": event.category,
        "message": event.message,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })


async def emit(
    db: AsyncSession,
    *,
    category: str,
    severity: str,
    event_type: str,
    message: str,
    details: dict[str, Any] | None = None,
    target_id: UUID | None = None,
    actor: str | None = None,
    duration_ms: int | None = None,
    parent_id: int | None = None,
) -> int | None:
    """Insert one ActivityEvent row and publish to Redis pubsub activity:new."""
    if not _validate(severity, category):
        return None
    event = _build_event(
        category=category, severity=severity, event_type=event_type,
        message=message, details=details, target_id=target_id,
        actor=actor, duration_ms=duration_ms, parent_id=parent_id,
    )
    try:
        db.add(event)
        await db.flush()
        event_id = event.id
        await db.commit()
    except Exception:
        logger.exception("activity.emit: DB insert failed for event_type=%s", event_type)
        return None
    try:
        async with async_redis() as r:
            await r.publish("activity:new", _pubsub_payload(event))
    except Exception:
        logger.warning("activity.emit: Redis publish failed for event_type=%s", event_type)
    return event_id


def emit_sync(
    db: Session,
    *,
    redis,
    category: str,
    severity: str,
    event_type: str,
    message: str,
    details: dict[str, Any] | None = None,
    target_id: UUID | None = None,
    actor: str | None = None,
    duration_ms: int | None = None,
    parent_id: int | None = None,
) -> int | None:
    """Sync version of emit() for Celery tasks."""
    if not _validate(severity, category):
        return None
    event = _build_event(
        category=category, severity=severity, event_type=event_type,
        message=message, details=details, target_id=target_id,
        actor=actor, duration_ms=duration_ms, parent_id=parent_id,
    )
    try:
        db.add(event)
        db.flush()
        event_id = event.id
        db.commit()
    except Exception:
        logger.exception("activity.emit_sync: DB insert failed for event_type=%s", event_type)
        return None
    try:
        redis.publish("activity:new", _pubsub_payload(event))
    except Exception:
        logger.warning("activity.emit_sync: Redis publish failed for event_type=%s", event_type)
    return event_id
