"""Detect and repair pre-b9c61a6 SIMBAD cache rows.

Those rows stored quote-wrapped aliases (literal `"` characters) that
curate_aliases then dropped, leaving empty common_name/aliases. catalog_id is
still derivable from main_id, so identity matching does not depend on this
repair, but display, search, and the name-fallback match path all benefit from
restoring correct labels. Re-fetching is idempotent and rate-limited.
"""
import logging
import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.simbad_cache import SimbadCache
from app.services.simbad import _query_simbad_raw, save_simbad_cache, _run_async

logger = logging.getLogger(__name__)


def _query_simbad_raw_sync(main_id: str):
    """Sync wrapper over the async SIMBAD raw query (for Celery workers)."""
    return _run_async(_query_simbad_raw(main_id))


def _row_is_corrupted(row: SimbadCache) -> bool:
    """A positive cache row whose raw_aliases contain a literal quote char."""
    if row.main_id is None:
        return False
    for alias in (row.raw_aliases or []):
        if alias is not None and '"' in alias:
            return True
    return False


def repair_corrupted_simbad_cache(
    session: Session, *, limit: int = 5000, sleep: float = 0.3,
) -> dict:
    """Re-fetch corrupted positive cache rows. Returns a summary dict."""
    rows = session.execute(
        select(SimbadCache).where(SimbadCache.main_id.isnot(None)).limit(limit)
    ).scalars().all()

    corrupted = [r for r in rows if _row_is_corrupted(r)]
    repaired = 0
    failed = 0

    for row in corrupted:
        fresh = _query_simbad_raw_sync(row.main_id)
        if fresh is None:
            failed += 1
            logger.warning("simbad_repair: re-fetch failed for '%s'", row.main_id)
            continue
        save_simbad_cache(row.query_name, fresh, session)
        session.commit()
        repaired += 1
        time.sleep(sleep)

    logger.info("simbad_repair: %d repaired, %d failed of %d corrupted",
                repaired, failed, len(corrupted))
    return {"corrupted": len(corrupted), "repaired": repaired, "failed": failed}
