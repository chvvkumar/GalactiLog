"""Nightly Celery beat task: prune activity_events rows older than retention window."""
import logging

from celery.schedules import crontab
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.config import settings, get_sync_redis
from app.models.user_settings import UserSettings, SETTINGS_ROW_ID
from app.models.app_log import AppLog  # noqa: F401  (registers the model / table)
from app.services.activity import emit_sync
from app.worker.celery_app import celery_app

logger = logging.getLogger(__name__)

_sync_url = settings.database_url.replace("+asyncpg", "+psycopg2")
_sync_engine = create_engine(_sync_url, pool_pre_ping=True, pool_size=2, max_overflow=2, pool_recycle=1800)

_DEFAULT_RETENTION_DAYS = 90
_DEFAULT_APP_LOG_RETENTION_DAYS = 14
_DEFAULT_APP_LOG_MAX_ROWS = 50000


def _compute_app_log_deletes(total_rows: int, max_rows: int) -> dict:
    """Return how many of the oldest rows to delete to honour the max-rows cap."""
    excess = max(0, total_rows - max_rows)
    return {"excess_rows": excess}


def _prune_app_logs(redis) -> dict:
    """Prune app_logs by retention days and a max-row cap (whichever hits first).

    Runs independently of the activity-event prune so a failure here does not
    block activity pruning. Emits a system activity event when rows are removed.
    """
    with Session(_sync_engine) as session:
        row = session.execute(
            select(UserSettings).where(UserSettings.id == SETTINGS_ROW_ID)
        ).scalar_one_or_none()
        general = (row.general or {}) if row else {}
        al_days = max(1, min(3650, int(general.get("app_log_retention_days", _DEFAULT_APP_LOG_RETENTION_DAYS))))
        al_max = max(1000, int(general.get("app_log_max_rows", _DEFAULT_APP_LOG_MAX_ROWS)))

        by_age = session.execute(
            text(f"DELETE FROM app_logs WHERE timestamp < now() - interval '{al_days} days'")
        ).rowcount
        session.commit()

        total_rows = session.execute(text("SELECT count(*) FROM app_logs")).scalar() or 0
        excess = _compute_app_log_deletes(total_rows, al_max)["excess_rows"]
        by_count = 0
        if excess > 0:
            by_count = session.execute(
                text(
                    "DELETE FROM app_logs WHERE id IN ("
                    "SELECT id FROM app_logs ORDER BY timestamp ASC, id ASC LIMIT :n)"
                ),
                {"n": excess},
            ).rowcount
            session.commit()

    total_deleted = (by_age or 0) + (by_count or 0)
    logger.info("prune app_logs: %d by age, %d by count", by_age or 0, by_count or 0)

    if total_deleted > 0:
        with Session(_sync_engine) as emit_session:
            emit_sync(
                emit_session,
                redis=redis,
                category="system",
                severity="info",
                event_type="app_logs_pruned",
                message=(
                    f"Application log pruned: {total_deleted} "
                    f"entr{'ies' if total_deleted != 1 else 'y'} removed "
                    f"({by_age or 0} by age, {by_count or 0} by row cap)"
                ),
                details={
                    "deleted_by_age": by_age or 0,
                    "deleted_by_count": by_count or 0,
                    "retention_days": al_days,
                    "max_rows": al_max,
                },
                actor="system",
            )
    return {"deleted_by_age": by_age or 0, "deleted_by_count": by_count or 0}


@celery_app.task(name="app.worker.prune_activity.prune_refresh_tokens", ignore_result=True)
def prune_refresh_tokens() -> dict:
    """Delete refresh_tokens rows that are expired or revoked.

    Production accumulates hundreds of stale rows per user (login/refresh
    rotation keeps every superseded token around indefinitely). Runs daily;
    failures here must not affect the activity/app_log prune tasks.
    """
    try:
        with Session(_sync_engine) as session:
            deleted = session.execute(
                text(
                    "DELETE FROM refresh_tokens "
                    "WHERE revoked = true OR expires_at < now()"
                )
            ).rowcount
            session.commit()

        logger.info("prune_refresh_tokens: deleted %d rows", deleted or 0)
        return {"status": "complete", "deleted": deleted or 0}
    except Exception as exc:
        logger.exception("prune_refresh_tokens: failed - %s", exc)
        return {"status": "error", "error": str(exc)}


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

        # Prune raw application logs independently so a failure here does not
        # affect the activity-event prune result above.
        app_log_result = {"deleted_by_age": 0, "deleted_by_count": 0}
        try:
            app_log_result = _prune_app_logs(redis)
        except Exception as exc:
            logger.exception("prune app_logs: failed - %s", exc)

        return {
            "status": "complete",
            "deleted": deleted,
            "retention_days": retention_days,
            "app_logs": app_log_result,
        }

    except Exception as exc:
        logger.exception("prune_activity_events: failed - %s", exc)
        return {"status": "error", "error": str(exc)}
    finally:
        try:
            redis.close()
        except Exception:
            logger.debug("prune_activity_events: failed to close Redis connection", exc_info=True)
