"""Facade module for the Celery worker task domains.

Historically every task lived directly in this file. It has since been split
into per-domain modules (app/worker/tasks_*.py) to keep individual files
readable; this module now only imports and re-exports every task/helper so
that:

  1. `celery_app.autodiscover_tasks(["app.worker"])` -- which, per Celery's
     convention, imports only `app.worker.tasks` for the "app.worker" package
     -- still triggers registration of every task in every domain module
     (importing this file transitively imports all of them).
  2. Every existing `from app.worker.tasks import X` call site elsewhere in
     the codebase keeps working unchanged, since X is still an attribute of
     this module.

See app/worker/tasks_common.py for the shared engine/redis/session-helper
infrastructure, and the individual tasks_*.py modules for the actual task
implementations. Celery task names are unaffected by this split: every task
that relied on its old implicit `app.worker.tasks.<funcname>` dotted name now
carries that same name explicitly via `@celery_app.task(name=...)` in whichever
module it now lives in.
"""
from app.worker.tasks_common import (  # noqa: F401 (re-exported for existing importers)
    _sync_engine, _redis, _activity_session, _invalidate_stats_cache,
)
from app.worker.tasks_scan import (  # noqa: F401
    run_scan, auto_scan_tick, ingest_file, reingest_changed_file,
    _do_ingest, _is_unrecoverable, _thumbnail_referenced,
    SCAN_RUN_LOCK, SCAN_RUN_LOCK_TTL,
)
from app.worker.tasks_thumbnails import (  # noqa: F401
    regenerate_missing_thumbnails, purge_and_regenerate_thumbnails,
    regenerate_thumbnail, generate_reference_thumbnails,
)
from app.worker.tasks_target_dedup import (  # noqa: F401
    detect_duplicate_targets, backfill_catalog_identity,
)
from app.worker.tasks_target_rebuild import (  # noqa: F401
    rebuild_targets, retry_unresolved, smart_rebuild_targets,
    _smart_rebuild_inner, enrich_new_target_task,
    SMART_REBUILD_LOCK, SMART_REBUILD_LOCK_TTL,
)
from app.worker.tasks_mosaics import (  # noqa: F401
    detect_mosaic_panels_task, MOSAIC_DETECT_LOCK, MOSAIC_DETECT_LOCK_TTL,
)
from app.worker.tasks_csv import backfill_csv_metrics  # noqa: F401
from app.worker.tasks_migrations import (  # noqa: F401
    run_data_migrations, load_reference_catalogs_if_empty,
    _pickup_data_migration_job, _update_data_migration_job,
    DATA_MIGRATION_LOCK, DATA_MIGRATION_LOCK_TTL,
    REFERENCE_CATALOG_LOCK, REFERENCE_CATALOG_LOCK_TTL,
)
from app.worker.tasks_filenames import detect_filename_targets  # noqa: F401
from app.worker.tasks_sessions import (  # noqa: F401
    backfill_dark_hours, recompute_session_dates,
    DARK_HOURS_LOCK, DARK_HOURS_LOCK_TTL,
)
from app.worker.tasks_phd2 import (  # noqa: F401
    scan_phd2_logs, ingest_phd2_log, apply_profile_map,
)

# A handful of call sites (mostly tests, plus a couple of production modules
# that pre-date the split) reach for names that used to live directly in this
# file's own top-of-module imports (e.g. `tasks_mod.Session`,
# `tasks_mod.settings`, `tasks_mod.fitsio`). Re-export the most commonly
# referenced ones here too so `import app.worker.tasks as tasks_mod` still
# exposes them at the facade level for simple attribute reads (not for
# patch.object() call-through -- see individual domain modules for those).
from sqlalchemy.orm import Session  # noqa: F401
from app.config import settings  # noqa: F401
import fitsio  # noqa: F401
import logging as _logging

logger = _logging.getLogger(__name__)
