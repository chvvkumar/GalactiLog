"""Detect and repair pre-b9c61a6 SIMBAD cache rows.

Those rows stored quote-wrapped aliases (literal `"` characters) that
curate_aliases then dropped, leaving empty common_name/aliases. catalog_id is
still derivable from main_id, so identity matching does not depend on this
repair, but display, search, and the name-fallback match path all benefit from
restoring correct labels. Re-fetching is idempotent and rate-limited.

Scans the ``catalog_cache`` table (source="simbad") rather than the old
``simbad_cache`` table: SIMBAD lookups have been ported onto the generic
cache wrapper (get_cached_simbad/save_simbad_cache), so new writes only ever
land in catalog_cache. Scanning the old table would forever re-fetch rows
that were already repaired there in a prior release, while never touching
corrupted rows the ported code has since written to catalog_cache.
"""
import logging
import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.catalog_cache import CatalogCache
from app.services.simbad import _query_simbad_raw, save_simbad_cache

logger = logging.getLogger(__name__)


def _query_simbad_raw_sync(main_id: str):
    """Thin wrapper over the (now plain-sync) SIMBAD raw query."""
    return _query_simbad_raw(main_id)


def _row_is_corrupted(row: CatalogCache) -> bool:
    """A positive cache row whose raw_aliases contain a literal quote char."""
    if row.negative or row.payload is None:
        return False
    if row.payload.get("main_id") is None:
        return False
    for alias in (row.payload.get("raw_aliases") or []):
        if alias is not None and '"' in alias:
            return True
    return False


def repair_corrupted_simbad_cache(
    session: Session, *, limit: int = 5000, sleep: float = 0.3,
) -> dict:
    """Re-fetch corrupted positive cache rows. Returns a summary dict."""
    rows = session.execute(
        select(CatalogCache)
        .where(CatalogCache.source == "simbad", CatalogCache.negative.is_(False))
        .limit(limit)
    ).scalars().all()

    corrupted = [r for r in rows if _row_is_corrupted(r)]
    repaired = 0
    failed = 0

    for row in corrupted:
        main_id = row.payload["main_id"]
        fresh = _query_simbad_raw_sync(main_id)
        if fresh is None:
            failed += 1
            logger.warning("simbad_repair: re-fetch failed for '%s'", main_id)
            continue
        save_simbad_cache(row.key, fresh, session)
        session.commit()
        repaired += 1
        time.sleep(sleep)

    logger.info("simbad_repair: %d repaired, %d failed of %d corrupted",
                repaired, failed, len(corrupted))
    return {"corrupted": len(corrupted), "repaired": repaired, "failed": failed}
