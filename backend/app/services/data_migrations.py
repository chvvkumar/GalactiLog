"""Auto data migrations - backfill logic that runs when DATA_VERSION advances.

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
from app.services.vizier import enrich_target_from_vizier, determine_vizier_catalog

logger = logging.getLogger(__name__)

# Current data version - bump this and add a migration function when
# code changes affect how stored target data is derived.
DATA_VERSION = 7


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
        # Try multiple cache lookup keys - the cache may be stored under
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


def _migrate_v4_vizier_and_common_names(session: Session) -> str:
    """Enrich un-enriched targets via VizieR and backfill OpenNGC common names."""
    import time
    from app.models import Target

    targets = session.execute(
        select(Target).where(Target.merged_into_id.is_(None))
    ).scalars().all()

    # Pass 1: Backfill OpenNGC common names for targets missing common_name
    names_added = 0
    for target in targets:
        if target.common_name is None:
            if enrich_target_from_openngc(session, target):
                names_added += 1

    session.flush()

    # Pass 2: VizieR enrichment for targets still missing size_major
    vizier_queried = 0
    vizier_enriched = 0
    for target in targets:
        if target.size_major is not None:
            continue
        if not target.catalog_id:
            continue
        if determine_vizier_catalog(target.catalog_id) is None:
            continue

        if enrich_target_from_vizier(session, target):
            vizier_enriched += 1
        vizier_queried += 1
        time.sleep(0.3)

    session.flush()

    parts = []
    if names_added:
        parts.append(f"{names_added} common names added from OpenNGC")
    if vizier_queried:
        parts.append(f"VizieR: {vizier_enriched}/{vizier_queried} targets enriched")
    return "; ".join(parts) if parts else "No changes needed"


def _migrate_v5_strip_panel_aliases(session: Session) -> str:
    """Remove 'Panel N' suffixed aliases from targets.

    These leaked in from FITS OBJECT headers like 'Andromeda Galaxy Panel 1'.
    The panel suffix is not meaningful as an alias - the base name is sufficient.
    """
    import re
    from app.models import Target

    panel_re = re.compile(r"\s+Panel\s+\d+$", re.IGNORECASE)

    targets = session.execute(
        select(Target).where(Target.merged_into_id.is_(None))
    ).scalars().all()

    updated = 0
    for target in targets:
        if not target.aliases:
            continue
        cleaned = []
        seen_upper: set[str] = set()
        for alias in target.aliases:
            stripped = panel_re.sub("", alias).strip()
            if not stripped:
                continue
            key = stripped.upper()
            if key not in seen_upper:
                seen_upper.add(key)
                cleaned.append(stripped)
        if cleaned != target.aliases:
            target.aliases = cleaned
            updated += 1

    session.flush()
    return f"{updated} targets had panel suffixes stripped from aliases"


def _migrate_v6_clear_negative_cache_and_reenrich(session: Session) -> str:
    """Clear negative VizieR cache, re-run enrichment, and compute constellations.

    After fixing ADQL quoting and LBN coordinate queries, negative cache entries
    are stale and must be cleared so VizieR enrichment can be retried.
    """
    import time
    from app.models import Target
    from app.models.vizier_cache import VizierCache
    from app.services.constellation import coords_to_constellation

    # Step 1: Clear negative cache entries (no size data)
    neg_deleted = session.execute(
        text(
            "DELETE FROM vizier_cache "
            "WHERE size_major IS NULL AND size_minor IS NULL"
        )
    ).rowcount
    session.flush()

    targets = session.execute(
        select(Target).where(Target.merged_into_id.is_(None))
    ).scalars().all()

    # Step 2: Re-run OpenNGC enrichment for all targets
    openngc_enriched = 0
    load_openngc_csv(session)
    for target in targets:
        if enrich_target_from_openngc(session, target):
            openngc_enriched += 1
    session.flush()

    # Step 3: VizieR enrichment for targets still missing size_major
    vizier_queried = 0
    vizier_enriched = 0
    for target in targets:
        if target.size_major is not None:
            continue
        if not target.catalog_id:
            continue
        if determine_vizier_catalog(target.catalog_id) is None:
            continue

        if enrich_target_from_vizier(session, target):
            vizier_enriched += 1
        vizier_queried += 1
        time.sleep(0.3)
    session.flush()

    # Step 4: Compute constellation for all targets missing it
    const_added = 0
    for target in targets:
        if target.constellation is not None:
            continue
        constellation = coords_to_constellation(target.ra, target.dec)
        if constellation:
            target.constellation = constellation
            const_added += 1
    session.flush()

    parts = []
    if neg_deleted:
        parts.append(f"{neg_deleted} negative cache entries cleared")
    if openngc_enriched:
        parts.append(f"{openngc_enriched} targets enriched from OpenNGC")
    if vizier_queried:
        parts.append(f"VizieR: {vizier_enriched}/{vizier_queried} targets enriched")
    if const_added:
        parts.append(f"{const_added} constellations computed")
    return "; ".join(parts) if parts else "No changes needed"


# Registry: version number -> (description, migration function)
# Version numbers must be sequential starting from 1.
MIGRATIONS: dict[int, tuple[str, Callable[[Session], str]]] = {
    1: ("Fix catalog designations (strip NAME prefix, re-derive from cache)", _migrate_v1_fix_catalog_designations),
    2: ("Re-derive designations with improved cache lookup (fixes targets v1 missed)", _migrate_v1_fix_catalog_designations),
    3: ("Load OpenNGC catalog and enrich targets with size/magnitude", _migrate_v3_load_openngc),
    4: ("VizieR enrichment and OpenNGC common name backfill", _migrate_v4_vizier_and_common_names),
    5: ("Strip panel suffixes from target aliases", _migrate_v5_strip_panel_aliases),
    6: ("Clear negative VizieR cache, re-enrich targets, compute constellations", _migrate_v6_clear_negative_cache_and_reenrich),
    7: ("Re-enrich after VizieR ADQL fix (drop unreferenceable computed columns)", _migrate_v6_clear_negative_cache_and_reenrich),
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
