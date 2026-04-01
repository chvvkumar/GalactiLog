"""Auto data migrations — backfill logic that runs when DATA_VERSION advances.

Each migration is a function that receives a sync SQLAlchemy Session and returns
a summary string. Register new migrations in MIGRATIONS with the next version number.
"""

import logging
from typing import Callable

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models.app_metadata import AppMetadata
from app.services.simbad import (
    curate_simbad_result, get_cached_simbad, normalize_object_name,
)
from app.services.openngc import load_openngc_csv, enrich_target_from_openngc

logger = logging.getLogger(__name__)

# Current data version — bump this and add a migration function when
# code changes affect how stored target data is derived.
DATA_VERSION = 3


def _migrate_v1_fix_catalog_designations(session: Session) -> str:
    """Re-derive catalog_id/common_name/primary_name from SIMBAD cache.

    Fixes: NAME prefix in catalog_id fallback, primary_name showing
    combined catalog + common name in designation column.
    """
    from app.models import Target

    targets = session.execute(
        select(Target).where(Target.merged_into_id.is_(None))
    ).scalars().all()

    updated = 0
    for target in targets:
        # Try multiple cache lookup keys — the cache may be stored under
        # the FITS object name, the catalog_id, or the primary_name
        fits_result = session.execute(text("""
            SELECT DISTINCT raw_headers->>'OBJECT'
            FROM images
            WHERE resolved_target_id = :tid
              AND raw_headers->>'OBJECT' IS NOT NULL
        """), {"tid": target.id})
        fits_names = [r[0] for r in fits_result.all() if r[0]]

        lookup_candidates = []
        cat_id = str(target.catalog_id) if target.catalog_id else ""
        if cat_id:
            lookup_candidates.append(cat_id)
            # Strip NAME prefix for cache lookup
            if cat_id.upper().startswith("NAME "):
                lookup_candidates.append(cat_id[5:].strip())
        if target.primary_name:
            lookup_candidates.append(str(target.primary_name))
        for fn in fits_names:
            lookup_candidates.append(str(fn))

        cached = None
        for candidate in lookup_candidates:
            cached = get_cached_simbad(normalize_object_name(candidate), session)
            if cached and not cached.get("_negative"):
                break
            cached = None

        if cached:
            curated = curate_simbad_result(cached, fits_names=fits_names)
            new_primary = curated["primary_name"]
            new_catalog = curated["catalog_id"]
            new_common = curated["common_name"]

            if (target.primary_name != new_primary or
                    target.catalog_id != new_catalog or
                    target.common_name != new_common):
                target.catalog_id = new_catalog
                target.common_name = new_common
                target.primary_name = new_primary
                updated += 1

    # Flush ORM changes so the raw SQL below sees updated catalog_id/common_name
    session.flush()

    # Also rebuild any primary_names that are inconsistent
    result = session.execute(text("""
        UPDATE targets
        SET primary_name = CASE
            WHEN catalog_id IS NOT NULL AND common_name IS NOT NULL
                THEN catalog_id || ' - ' || common_name
            WHEN catalog_id IS NOT NULL THEN catalog_id
            WHEN common_name IS NOT NULL THEN common_name
            ELSE 'Unknown'
        END
        WHERE merged_into_id IS NULL
          AND primary_name != CASE
            WHEN catalog_id IS NOT NULL AND common_name IS NOT NULL
                THEN catalog_id || ' - ' || common_name
            WHEN catalog_id IS NOT NULL THEN catalog_id
            WHEN common_name IS NOT NULL THEN common_name
            ELSE 'Unknown'
        END
    """))
    names_rebuilt = result.rowcount

    parts = []
    if updated:
        parts.append(f"{updated} targets re-derived from cache")
    if names_rebuilt:
        parts.append(f"{names_rebuilt} names rebuilt")
    return "; ".join(parts) if parts else "No changes needed"


def _migrate_v3_load_openngc(session: Session) -> str:
    """Load OpenNGC catalog and enrich existing targets with size/magnitude data."""
    from app.models import Target

    loaded = load_openngc_csv(session)

    targets = session.execute(
        select(Target).where(Target.merged_into_id.is_(None))
    ).scalars().all()

    enriched = 0
    for target in targets:
        if enrich_target_from_openngc(session, target):
            enriched += 1

    session.flush()
    return f"Loaded {loaded} OpenNGC entries, enriched {enriched}/{len(targets)} targets"


# Registry: version number -> (description, migration function)
# Version numbers must be sequential starting from 1.
MIGRATIONS: dict[int, tuple[str, Callable[[Session], str]]] = {
    1: ("Fix catalog designations (strip NAME prefix, re-derive from cache)", _migrate_v1_fix_catalog_designations),
    2: ("Re-derive designations with improved cache lookup (fixes targets v1 missed)", _migrate_v1_fix_catalog_designations),
    3: ("Load OpenNGC catalog and enrich targets with size/magnitude", _migrate_v3_load_openngc),
}


def get_current_data_version(session: Session) -> int:
    """Read the current data version from the DB. Returns 0 if not set."""
    row = session.execute(
        select(AppMetadata).where(AppMetadata.key == "data_version")
    ).scalar_one_or_none()
    if row is None:
        return 0
    # value is stored as a JSON number
    try:
        return int(row.value)
    except (TypeError, ValueError):
        return 0


def set_data_version(session: Session, version: int) -> None:
    """Update the data version in the DB."""
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    stmt = pg_insert(AppMetadata).values(
        key="data_version", value=version
    ).on_conflict_do_update(
        index_elements=["key"],
        set_={"value": version},
    )
    session.execute(stmt)


def get_pending_migrations(current_version: int) -> list[tuple[int, str, Callable]]:
    """Return migrations that need to run, in order."""
    pending = []
    for ver in sorted(MIGRATIONS.keys()):
        if ver > current_version:
            desc, func = MIGRATIONS[ver]
            pending.append((ver, desc, func))
    return pending
