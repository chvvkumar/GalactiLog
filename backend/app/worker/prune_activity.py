"""Nightly Celery beat task: prune activity_events rows older than retention window."""
import logging

from celery.schedules import crontab
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.config import settings, get_sync_redis
from app.models.user_settings import UserSettings, SETTINGS_ROW_ID
from app.services.activity import emit_sync
from app.worker.celery_app import celery_app

logger = logging.getLogger(__name__)

_sync_url = settings.database_url.replace("+asyncpg", "+psycopg2")
_sync_engine = create_engine(_sync_url, pool_pre_ping=True, pool_size=2, max_overflow=2, pool_recycle=1800)

_DEFAULT_RETENTION_DAYS = 90


@celery_app.task(name="app.worker.prune_activity.prune_activity_events")
def prune_activity_events() -> dict:
    """Delete activity_events rows older than activity_retention_days.

    Reads retention from GeneralSettings. Emits activity_pruned only when
    deleted_count > 0.
    """
    redis = get_sync_redis()

    try:
        with Session(_sync_engine) as session:
            row = session.execute(
                select(UserSettings).where(UserSettings.id == SETTINGS_ROW_ID)
            ).scalar_one_or_none()

            general = (row.general or {}) if row else {}
            retention_days = int(general.get("activity_retention_days", _DEFAULT_RETENTION_DAYS))
            retention_days = max(1, min(3650, retention_days))

            result = session.execute(
                text(
                    f"DELETE FROM activity_events "
                    f"WHERE timestamp < now() - interval '{retention_days} days'"
                )
            )
            deleted = result.rowcount
            session.commit()

        logger.info(
            "prune_activity_events: deleted %d rows (retention=%d days)",
            deleted, retention_days,
        )

        if deleted > 0:
            with Session(_sync_engine) as emit_session:
                emit_sync(
                    emit_session,
                    redis=redis,
                    category="system",
                    severity="info",
                    event_type="activity_pruned",
                    message=(
                        f"Activity log pruned: {deleted} "
                        f"entr{'ies' if deleted != 1 else 'y'} older than "
                        f"{retention_days} days removed"
                    ),
                    details={"deleted_count": deleted, "retention_days": retention_days},
                    actor="system",
                )

        return {"status": "complete", "deleted": deleted, "retention_days": retention_days}

    except Exception as exc:
        logger.exception("prune_activity_events: failed - %s", exc)
        return {"status": "error", "error": str(exc)}
    finally:
        try:
            redis.close()
        except Exception:
            pass
