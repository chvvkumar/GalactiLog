"""Session-date maintenance: backfill_dark_hours, recompute_session_dates."""
import logging
from datetime import datetime

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.models import Image
from app.models.user_settings import UserSettings, SETTINGS_ROW_ID
from app.services.session_date import compute_session_date, extract_longitude, warn_imaging_night_fallback
from app.schemas.settings import GeneralSettings
from app.worker.celery_app import celery_app
from app.worker.tasks_common import _sync_engine, _redis

logger = logging.getLogger(__name__)

DARK_HOURS_LOCK = "dark_hours:lock"
DARK_HOURS_LOCK_TTL = 300  # 5 minutes


@celery_app.task(name="app.worker.tasks.backfill_dark_hours")
def backfill_dark_hours(parent_activity_id: int | None = None) -> dict:
    """Compute astronomical dark hours for all imaging dates missing from site_dark_hours.

    Extracts site coordinates from FITS headers, then batch-computes dark hours
    for every unique capture_date not yet in the table. Runs on startup and after scans.
    """
    from app.models.site_dark_hours import SiteDarkHours
    from app.services.astro_night import dark_hours_batch
    from app.api.stats import _extract_site_coords_sync
    from datetime import date as date_type

    # Prevent overlapping runs
    if not _redis.set(DARK_HOURS_LOCK, "1", nx=True, ex=DARK_HOURS_LOCK_TTL):
        return {"status": "skipped", "reason": "already running"}

    try:
        with Session(_sync_engine) as session:
            # Get site coordinates from FITS headers
            site_coords = _extract_site_coords_sync(session)
            if not site_coords:
                logger.info("dark_hours: no site coordinates in FITS headers, skipping")
                return {"status": "skipped", "reason": "no site coords"}

            lat, lon = site_coords.latitude, site_coords.longitude

            # Find unique capture dates that are missing from site_dark_hours
            existing_q = select(SiteDarkHours.date).where(
                SiteDarkHours.latitude == lat,
                SiteDarkHours.longitude == lon,
            )
            existing_dates = {row[0] for row in session.execute(existing_q).all()}

            all_dates_q = select(
                func.distinct(Image.session_date)
            ).where(
                Image.session_date.isnot(None),
                Image.image_type == "LIGHT",
            )
            all_imaging_dates = {row[0] for row in session.execute(all_dates_q).all()}

            missing = sorted(all_imaging_dates - existing_dates)
            if not missing:
                logger.info("dark_hours: all %d dates already computed", len(existing_dates))
                return {"status": "noop", "existing": len(existing_dates)}

            logger.info("dark_hours: computing %d missing dates (lat=%.2f, lon=%.2f)",
                        len(missing), lat, lon)

            # Batch compute in chunks to avoid memory issues
            CHUNK = 200
            computed = 0
            for i in range(0, len(missing), CHUNK):
                chunk = missing[i:i + CHUNK]
                dark_values = dark_hours_batch(chunk, lat, lon)
                for d, dh in zip(chunk, dark_values):
                    session.merge(SiteDarkHours(
                        date=d, dark_hours=dh, latitude=lat, longitude=lon,
                    ))
                session.commit()
                computed += len(chunk)
                logger.info("dark_hours: %d/%d dates computed", computed, len(missing))

            logger.info("dark_hours: backfill complete, %d dates added", computed)
            return {"status": "complete", "computed": computed, "total": len(all_imaging_dates)}
    except Exception:
        logger.exception("dark_hours: backfill failed")
        raise
    finally:
        _redis.delete(DARK_HOURS_LOCK)


@celery_app.task(name="recompute_session_dates", bind=True)
def recompute_session_dates(self):
    """Recompute session_date for all images and re-key session notes/custom values."""
    from collections import Counter
    from datetime import date as date_type, timedelta
    from app.models.session_note import SessionNote
    from app.models.custom_column import CustomColumnValue

    with Session(_sync_engine) as session:
        # Load settings
        settings_row = session.get(UserSettings, SETTINGS_ROW_ID)
        general = GeneralSettings(**(settings_row.general if settings_row and settings_row.general else {}))
        fallback_lon = general.observer_longitude
        use_night = general.use_imaging_night
        fallback_warned = False  # AUD-021: one warning per run, not per image

        # Phase 1: Recompute all image session_dates in batches.
        # Keyset pagination (WHERE id > :last ORDER BY id) instead of OFFSET,
        # which re-scans and discards all prior rows every page (O(N^2/batch)).
        # Each batch is flushed with a single UPDATE ... FROM (VALUES ...)
        # statement instead of one UPDATE round-trip per image (~90k on a large
        # catalog).
        BATCH = 5000
        last_id = None
        total = 0
        while True:
            q = (
                select(Image.id, Image.capture_date, Image.raw_headers)
                .where(Image.capture_date.isnot(None))
                .order_by(Image.id)
                .limit(BATCH)
            )
            if last_id is not None:
                q = q.where(Image.id > last_id)
            rows = session.execute(q).all()
            if not rows:
                break

            batch_updates = []
            for img_id, capture_date, raw_headers in rows:
                site_lon = extract_longitude(raw_headers)
                effective_lon = site_lon if site_lon is not None else fallback_lon
                if use_night and effective_lon is None and not fallback_warned:
                    # Warn once per recompute run, not once per image.
                    warn_imaging_night_fallback(logger)
                    fallback_warned = True
                new_date = compute_session_date(
                    capture_date,
                    use_imaging_night=use_night,
                    longitude=effective_lon,
                )
                batch_updates.append((img_id, new_date))

            # Single batched UPDATE for the whole page.
            value_rows = []
            params: dict = {}
            for i, (img_id, new_date) in enumerate(batch_updates):
                value_rows.append(f"(:id{i}, :d{i})")
                params[f"id{i}"] = str(img_id)
                params[f"d{i}"] = new_date
            session.execute(
                text(
                    "UPDATE images AS img SET session_date = data.new_date::date "
                    "FROM (VALUES " + ",".join(value_rows) + ") AS data(id, new_date) "
                    "WHERE img.id = data.id::uuid"
                ),
                params,
            )

            session.commit()
            total += len(rows)
            last_id = rows[-1][0]
            self.update_state(state="PROGRESS", meta={"images_updated": total})

        # Phase 2: Re-key SessionNote rows
        notes = session.execute(select(SessionNote)).scalars().all()
        for note in notes:
            old_date = note.session_date
            window_start = datetime.combine(old_date - timedelta(days=1), datetime.min.time())
            window_end = datetime.combine(old_date + timedelta(days=2), datetime.min.time())
            img_dates = session.execute(
                select(Image.session_date)
                .where(
                    Image.resolved_target_id == note.target_id,
                    Image.capture_date >= window_start,
                    Image.capture_date < window_end,
                    Image.session_date.isnot(None),
                )
            ).scalars().all()
            if img_dates:
                most_common = Counter(img_dates).most_common(1)[0][0]
                if most_common != note.session_date:
                    existing = session.execute(
                        select(SessionNote.id).where(
                            SessionNote.target_id == note.target_id,
                            SessionNote.session_date == most_common,
                            SessionNote.id != note.id,
                        )
                    ).scalar_one_or_none()
                    if existing is None:
                        note.session_date = most_common

        session.commit()

        # Phase 3: Re-key CustomColumnValue rows
        cvs = session.execute(
            select(CustomColumnValue).where(CustomColumnValue.session_date.isnot(None))
        ).scalars().all()
        for cv in cvs:
            old_date = cv.session_date
            window_start = datetime.combine(old_date - timedelta(days=1), datetime.min.time())
            window_end = datetime.combine(old_date + timedelta(days=2), datetime.min.time())
            img_dates = session.execute(
                select(Image.session_date)
                .where(
                    Image.resolved_target_id == cv.target_id,
                    Image.capture_date >= window_start,
                    Image.capture_date < window_end,
                    Image.session_date.isnot(None),
                )
            ).scalars().all()
            if img_dates:
                from sqlalchemy import func
                most_common = Counter(img_dates).most_common(1)[0][0]
                if most_common != cv.session_date:
                    existing = session.execute(
                        select(CustomColumnValue.id).where(
                            CustomColumnValue.column_id == cv.column_id,
                            CustomColumnValue.target_id == cv.target_id,
                            func.coalesce(CustomColumnValue.session_date, date_type(1970, 1, 1)) == most_common,
                            CustomColumnValue.id != cv.id,
                        )
                    ).scalar_one_or_none()
                    if existing is None:
                        cv.session_date = most_common

        session.commit()

        logger.info("recompute_session_dates: updated %d images", total)
        return {"status": "done", "images_updated": total}
