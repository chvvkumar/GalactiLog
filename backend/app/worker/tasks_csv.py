"""CSV metric backfill: backfill_csv_metrics."""
import logging
from pathlib import Path

from sqlalchemy import select, update as sa_update

from app.config import settings
from app.models import Image
from app.services.csv_metadata import parse_image_metadata_csv, parse_weather_csv
from app.worker.celery_app import celery_app
from app.worker.tasks_common import _sync_engine
from app.services.scan_state import set_idle_sync, set_ingesting_sync, increment_completed_sync, increment_failed_sync

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, name="app.worker.tasks.backfill_csv_metrics")
def backfill_csv_metrics(self):
    """Walk FITS tree and backfill Image rows with CSV metric data."""
    import redis as _redis

    # decode_responses=True to match every other Redis connection in this
    # module (app.config.get_sync_redis()) - without it, check_complete_sync's
    # str-keyed hgetall() lookups below never match this connection's
    # bytes-keyed results, which would silently defeat the kind="csv_backfill"
    # cascade-suppression below (AUD-030).
    redis_conn = _redis.from_url(settings.redis_url, decode_responses=True)
    root = Path(settings.fits_data_path)

    # Collect all directories containing ImageMetaData.csv
    csv_dirs = [csv_file.parent for csv_file in root.rglob("ImageMetaData.csv")]

    if not csv_dirs:
        set_idle_sync(redis_conn)
        return {"updated": 0, "dirs": 0}

    set_ingesting_sync(redis_conn, total=len(csv_dirs), kind="csv_backfill")
    total_updated = 0

    with _sync_engine.connect() as conn:
        for csv_dir in csv_dirs:
            try:
                # Parse CSV data for this directory
                image_data = parse_image_metadata_csv(csv_dir)
                if not image_data:
                    increment_completed_sync(redis_conn)
                    continue

                weather_data = parse_weather_csv(csv_dir)

                # Query images in this directory missing CSV data
                dir_prefix = str(csv_dir)
                stmt = select(Image.id, Image.file_name).where(
                    Image.file_path.like(f"{dir_prefix}%"),
                    Image.detected_stars.is_(None),
                )
                rows = conn.execute(stmt).fetchall()

                for row in rows:
                    img_entry = image_data.get(row.file_name)
                    if img_entry is None:
                        continue

                    # Build update dict from image CSV data
                    update_data = dict(img_entry)

                    # Join weather data by ExposureStartUTC
                    exposure_start = update_data.pop("_exposure_start_utc", None)
                    if exposure_start and weather_data:
                        weather_entry = weather_data.get(exposure_start)
                        if weather_entry:
                            update_data.update(weather_entry)

                    if update_data:
                        conn.execute(
                            sa_update(Image)
                            .where(Image.id == row.id)
                            .values(**update_data)
                        )
                        total_updated += 1

                conn.commit()
                increment_completed_sync(redis_conn)

            except Exception:
                # Log the directory and traceback so a CSV that silently fails
                # to backfill can be diagnosed instead of vanishing.
                logger.warning(
                    "backfill_csv_metrics: failed to process CSV directory %s",
                    csv_dir, exc_info=True,
                )
                increment_failed_sync(redis_conn)
                conn.rollback()

    set_idle_sync(redis_conn)
    return {"updated": total_updated, "dirs": len(csv_dirs)}
