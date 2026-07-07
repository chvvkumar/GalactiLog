"""Mosaic panel detection: detect_mosaic_panels_task."""
import logging

from app.config import settings
from app.models.user_settings import UserSettings, SETTINGS_ROW_ID
from app.worker.celery_app import celery_app
from app.worker.tasks_common import _redis, _activity_session
from app.services.activity import emit_sync as _emit_activity_sync

logger = logging.getLogger(__name__)

MOSAIC_DETECT_LOCK = "mosaic_detect:lock"
MOSAIC_DETECT_LOCK_TTL = 120  # 2 minutes


@celery_app.task(name="detect_mosaic_panels_task")
def detect_mosaic_panels_task(parent_activity_id: int | None = None):
    """Run mosaic panel detection as a background Celery task."""
    if not _redis.set(MOSAIC_DETECT_LOCK, "1", nx=True, ex=MOSAIC_DETECT_LOCK_TTL):
        logger.info("detect_mosaic_panels_task: already running, skipping")
        return {"status": "skipped", "reason": "already running"}

    try:
        import asyncio
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

        from app.services.mosaic_detection import detect_mosaic_panels

        async def _run():
            engine = create_async_engine(settings.database_url, pool_pre_ping=True)
            async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            async with async_session() as session:
                # Use the campaign-split setting so scan-triggered detection
                # produces the same suggestions as the manual /detect endpoint.
                settings_row = await session.get(UserSettings, SETTINGS_ROW_ID)
                general = settings_row.general if settings_row else {}
                gap_days = general.get("mosaic_campaign_gap_days", 0)
                count = await detect_mosaic_panels(session, gap_days=gap_days)
                await session.commit()
            await engine.dispose()
            return count

        count = asyncio.run(_run())
        logger.info("detect_mosaic_panels_task: found %d new suggestions", count)
        try:
            with _activity_session() as _db:
                _emit_activity_sync(
                    _db, redis=_redis, category="mosaic", severity="info",
                    event_type="mosaic_detection_complete",
                    message=f"Mosaic detection complete: {count} new suggestion{'s' if count != 1 else ''} found",
                    details={"candidates": count}, actor="system",
                    parent_id=parent_activity_id,
                )
        except Exception:
            logger.warning("detect_mosaic_panels_task: failed to emit mosaic_detection_complete")
        return {"status": "complete", "new_suggestions": count}
    finally:
        _redis.delete(MOSAIC_DETECT_LOCK)
