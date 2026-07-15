"""CSV metric backfill: backfill_csv_metrics."""
import logging
from pathlib import Path

from sqlalchemy import select, update as sa_update

from app.config import settings
from app.models import Image
from app.services.csv_metadata import (
    IMAGE_COLUMN_MAP,
    WEATHER_COLUMN_MAP,
    merge_csv_metrics,
    parse_image_metadata_csv,
    parse_weather_csv,
)
from app.worker.celery_app import celery_app
from app.worker.tasks_common import _sync_engine
from app.services.scan_state import set_idle_sync, set_ingesting_sync, increment_completed_sync, increment_failed_sync

logger = logging.getLogger(__name__)


# Every Image column a parsed CSV row can speak about, derived from the column
# maps rather than restated, so a column added to the parser is backfilled
# without anyone remembering to touch this list too. dict.fromkeys dedupes
# while keeping a stable order.
CSV_MERGE_COLUMNS: tuple[str, ...] = tuple(
    dict.fromkeys(
        [db_col for db_col, _ in IMAGE_COLUMN_MAP.values()]
        + [db_col for db_col, _ in WEATHER_COLUMN_MAP.values()]
    )
)

# Written by merge_csv_metrics as a consequence of the merge, not read from any
# CSV column, so it is selected and diffed alongside the mergeable columns but
# is not one of them.
_PROVENANCE_COLUMNS: tuple[str, ...] = ("eccentricity_source",)


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

                # Query images in this directory missing CSV data. The row's
                # current values come back too, not just its identity: this is
                # an UPDATE over rows that already hold header-derived numbers,
                # so deciding what a CSV cell may overwrite is impossible
                # without knowing what is already there.
                dir_prefix = str(csv_dir)
                selected = CSV_MERGE_COLUMNS + _PROVENANCE_COLUMNS
                stmt = select(
                    Image.id,
                    Image.file_name,
                    *(getattr(Image, col) for col in selected),
                ).where(
                    Image.file_path.like(f"{dir_prefix}%"),
                    Image.detected_stars.is_(None),
                )
                rows = conn.execute(stmt).fetchall()

                for row in rows:
                    img_entry = image_data.get(row.file_name)
                    if img_entry is None:
                        continue

                    # Flatten the CSV row: image metrics plus the weather row
                    # joined on ExposureStartUTC. Mirrors get_csv_metrics, which
                    # is what the ingest path feeds merge_csv_metrics.
                    csv_metrics = dict(img_entry)
                    exposure_start = csv_metrics.pop("_exposure_start_utc", None)
                    if exposure_start and weather_data:
                        weather_entry = weather_data.get(exposure_start)
                        if weather_entry:
                            csv_metrics.update(weather_entry)

                    # Same merge the two ingest paths use, seeded with the row's
                    # stored values instead of a freshly parsed header. The rule
                    # it encodes -- a CSV None means "the CSV says nothing here",
                    # never "the value is nothing" -- is exactly what this path
                    # needs, because `values(**dict(img_entry))` used to write
                    # every blank cell as a NULL straight over a real stored
                    # eccentricity or HFR. It also owns eccentricity_source, so
                    # a backfilled CSV eccentricity stops being labelled
                    # "header".
                    before = {col: getattr(row, col) for col in selected}
                    merged = merge_csv_metrics(dict(before), csv_metrics)

                    # Only what actually changed. On ingest, writing a key the
                    # header never set as None is free -- the row is new. Here
                    # the row exists, so every no-op column is dropped rather
                    # than rewritten, which also keeps `updated` counting rows
                    # the backfill really changed.
                    update_data = {
                        col: value for col, value in merged.items()
                        if value != before[col]
                    }

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
