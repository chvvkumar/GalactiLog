"""Session-date maintenance: backfill_dark_hours, recompute_session_dates."""
import logging
from collections.abc import Callable
from datetime import datetime

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.models import Image
from app.models.user_settings import UserSettings, SETTINGS_ROW_ID
from app.services.phd2_profiles import longitude_resolver
from app.services.session_date import compute_session_date, extract_longitude, warn_imaging_night_fallback
from app.schemas.settings import GeneralSettings
from app.worker.celery_app import celery_app
from app.worker.tasks_common import _sync_engine, _redis

logger = logging.getLogger(__name__)

DARK_HOURS_LOCK = "dark_hours:lock"
DARK_HOURS_LOCK_TTL = 300  # 5 minutes


@celery_app.task(name="app.worker.tasks.backfill_dark_hours")
def backfill_dark_hours(parent_activity_id: int | None = None) -> dict:
    """Fill site_dark_hours for every calendar night the timeline can render.

    Extracts site coordinates from FITS headers, then batch-computes dark hours
    for every date in the catalogue span that is not already in the table.

    The span is EVERY calendar date, not just the imaging dates. The timeline
    efficiency denominator counts the clouded-out nights too: a month with four
    clear nights out of thirty must read low, and it can only do that if those
    other twenty-six nights have a dark-hours row. Filling only the imaging
    dates made every night in the denominator a night that was actually used,
    which is how the percentages ran past 100.

    Runs on startup (main.py dispatches it with a 5 second countdown) and 45
    seconds after every scan completes. Both paths call this same function with
    no arguments, so the widened span takes effect on the very next invocation:
    on an existing install the first app restart after deploy backfills the
    historical gaps, with no manual step and no migration.

    Also on celery beat daily at 13:00 UTC ("backfill-dark-hours"), which is
    what keeps tonight's row present on a box that is neither restarted nor
    scanned. The span still runs 35 days into the future as belt and braces:
    if beat is down, or the worker is busy at 13:00, the rows for the coming
    month are already there.

    Idempotent: only dates absent from the table are computed, so a re-run on a
    fully populated table is a single SELECT.
    """
    from app.models.site_dark_hours import SiteDarkHours
    from app.services.astro_night import dark_hours_batch
    from app.api.stats import _extract_site_coords_sync
    from datetime import date as date_type, timedelta

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

            first_session, last_session = session.execute(
                select(
                    func.min(Image.session_date), func.max(Image.session_date)
                ).where(
                    Image.session_date.isnot(None),
                    Image.image_type == "LIGHT",
                )
            ).one()
            if first_session is None:
                logger.info("dark_hours: no imaging dates yet, skipping")
                return {"status": "skipped", "reason": "no imaging dates"}

            # Back up a week from the first session before snapping to the
            # first of that month: the ISO week holding the first imaging night
            # can start in the previous month, and the weekly timeline needs
            # all seven of its days.
            #
            # The end runs 35 days PAST today (or past the last session, if one
            # is dated ahead of the clock). Beat runs this daily, so "today"
            # normally advances on its own; the lead is what covers beat being
            # down or the worker being saturated at 13:00. Without it, the first
            # midnight after the last run leaves the current day with no row and
            # the stats timeline blanks the month and week in progress. 35 days
            # carries a full month plus the longest ISO week overhang. Dark
            # hours are a deterministic function of date and site, so computing
            # them ahead of time costs one vectorized batch and can never be
            # wrong.
            start = (first_session - timedelta(days=7)).replace(day=1)
            end = max(date_type.today(), last_session) + timedelta(days=35)
            wanted = {start + timedelta(days=i) for i in range((end - start).days + 1)}

            missing = sorted(wanted - existing_dates)
            if not missing:
                logger.info("dark_hours: all %d dates already computed", len(existing_dates))
                return {"status": "noop", "existing": len(existing_dates)}

            # Site coordinates are deliberately NOT logged: they are the
            # observer's home location (py/clear-text-logging-sensitive-data).
            # Their presence is already implied by reaching this line.
            logger.info("dark_hours: computing %d missing dates", len(missing))

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
            return {"status": "complete", "computed": computed, "total": len(wanted)}
    except Exception:
        logger.exception("dark_hours: backfill failed")
        raise
    finally:
        _redis.delete(DARK_HOURS_LOCK)


def _rekey_phd2_sessions(session, *, use_night: bool,
                         resolve_longitude: Callable[[str | None], float | None]) -> int:
    """Recompute session_date for every PHD2 session and calibration row.

    Simpler than the image-derived re-keying used for notes and custom values:
    a PHD2 row already carries its own absolute started_at_utc, so the night it
    belongs to is a direct computation rather than a vote among nearby frames.

    The longitude is resolved PER EQUIPMENT PROFILE, not once for the whole
    catalogue. A guide log carries no site headers, but it does name the
    equipment profile that wrote it, and a profile can hold coordinates of its
    own. That is what puts a rig taken twelve degrees west of home on the right
    night: same country, same timezone, forty-eight minutes of night boundary.
    Both models carry `equipment_profile`, so a calibration resolves exactly as
    a session does.

    `resolve_longitude` is built once per pass by
    `phd2_profiles.longitude_resolver`, which normalizes the stored map a
    single time and answers each lookup from a dict. This function must not
    normalize anything itself: it runs once per stored row.

    A resolved None means no longitude is known at either level and the row
    falls back to UTC-midnight grouping. NOTHING HERE TESTS A LONGITUDE FOR
    TRUTH. Zero is Greenwich, a real site with a real night boundary, and a
    falsy check would quietly file a prime-meridian rig under the user's own
    night.

    Returns the number of rows whose date changed. Caller commits.
    """
    from app.models.phd2 import Phd2Calibration, Phd2Session

    changed = 0
    for model in (Phd2Session, Phd2Calibration):
        for row in session.execute(select(model)).scalars().all():
            new_date = compute_session_date(
                row.started_at_utc,
                use_imaging_night=use_night,
                longitude=resolve_longitude(row.equipment_profile),
            )
            if row.session_date != new_date:
                row.session_date = new_date
                changed += 1
    return changed


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
        # Built once here, not once per PHD2 row: it normalizes the stored
        # profile map and precomputes every profile's answer, so phase 4's
        # lookup is a dict hit. Images keep resolving from their own headers
        # with fallback_lon behind them; this is the guide-log equivalent.
        resolve_phd2_longitude = longitude_resolver(
            general.phd2_profile_map, fallback_lon
        )

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

        # Phase 4: Re-key PHD2 guiding sessions and calibrations.
        # phd2_sessions is session_date-keyed exactly like session_notes and
        # custom_column_values above. Without this phase, toggling
        # imaging-night moves every image to a new night while the guiding
        # sessions stay on the old one, and the session-detail join quietly
        # returns nothing for every night in the catalog. Editing a single
        # profile's longitude moves that rig's nights and leaves every other
        # rig where it stands.
        phd2_rekeyed = _rekey_phd2_sessions(
            session, use_night=use_night,
            resolve_longitude=resolve_phd2_longitude,
        )
        session.commit()

        logger.info(
            "recompute_session_dates: updated %d images, re-keyed %d PHD2 rows",
            total, phd2_rekeyed,
        )
        return {
            "status": "done", "images_updated": total,
            "phd2_rows_rekeyed": phd2_rekeyed,
        }
