"""Auto data migrations - backfill logic that runs when DATA_VERSION advances.

Each migration is a function that receives a sync SQLAlchemy Session and returns
a summary string. Register new migrations in MIGRATIONS with the next version number.
"""

import logging
from typing import Callable

from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy import or_, select, text
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
DATA_VERSION = 13

# Migrations whose per-target loops make external network calls (VizieR, Gaia,
# SAC, HyperLEDA) with pacing sleeps commit their work every this many queried
# targets. On a large catalog such a loop can exceed the Celery time limit and
# be interrupted; committing in chunks makes the completed enrichment durable so
# the next run resumes from where it stopped (the per-target enrichers skip
# already-enriched targets) instead of rolling the whole version back and
# replaying it every boot (AUD-035).
_MIGRATION_COMMIT_CHUNK = 25


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
        if getattr(target, "user_defined", False):
            continue
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
          AND user_defined = FALSE
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
        if vizier_queried % _MIGRATION_COMMIT_CHUNK == 0:
            session.commit()  # persist partial enrichment so a timeout resumes cheaply
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
        if vizier_queried % _MIGRATION_COMMIT_CHUNK == 0:
            session.commit()  # persist partial enrichment so a timeout resumes cheaply
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


def _migrate_v8_tier1_and_catalogs(session: Session) -> str:
    """Load static catalogs, match memberships, and enrich from Gaia/SAC."""
    import time
    from app.models import Target
    from app.services.sac import load_sac_csv, enrich_target_from_sac
    from app.services.gaia import enrich_target_from_gaia
    from app.services.catalog_membership import load_catalog_memberships

    parts = []

    # Step 1: Load SAC catalog
    sac_loaded = load_sac_csv(session)
    if sac_loaded:
        parts.append(f"{sac_loaded} SAC entries loaded")
    session.flush()

    # Step 2: Load static catalogs and match memberships
    membership_summary = load_catalog_memberships(session)
    parts.append(membership_summary)
    session.flush()

    # Step 3: Enrich targets
    targets = session.execute(
        select(Target).where(Target.merged_into_id.is_(None))
    ).scalars().all()

    sac_enriched = 0
    gaia_enriched = 0

    for i, target in enumerate(targets):
        # SAC enrichment (all targets)
        if enrich_target_from_sac(session, target):
            sac_enriched += 1

        # Gaia enrichment (cluster gate inside)
        if enrich_target_from_gaia(session, target):
            gaia_enriched += 1
        time.sleep(0.5)

        if (i + 1) % 10 == 0:
            session.commit()  # persist partial enrichment so a timeout resumes cheaply
            logger.info("Enrichment progress: %d/%d targets", i + 1, len(targets))

    session.flush()

    if sac_enriched:
        parts.append(f"SAC: {sac_enriched} targets enriched")
    if gaia_enriched:
        parts.append(f"Gaia: {gaia_enriched} clusters got distances")

    return "; ".join(parts) if parts else "No changes needed"


def _migrate_v8_fix_question_mark_galaxy(session: Session) -> str:
    """Fix wrong SIMBAD cache mapping for Question Mark Galaxy.

    The COMMON_NAME_MAP previously mapped "question mark galaxy" to NGC 4258
    (M106), but the correct object is NGC 5194 (M51). Clear the stale cache
    entry so it gets re-resolved, and remove the alias from M106 if present.
    """
    from app.models import Target

    # Clear the stale SIMBAD cache entry so it re-resolves to NGC 5194
    deleted = session.execute(
        text("DELETE FROM simbad_cache WHERE query_name = 'QUESTION MARK GALAXY'")
    ).rowcount
    session.flush()

    # Remove "QUESTION MARK GALAXY" from M106's aliases if it snuck in
    m106 = session.execute(
        select(Target).where(
            Target.catalog_id == "NGC 4258",
            Target.merged_into_id.is_(None),
        )
    ).scalar_one_or_none()

    alias_removed = False
    if m106 and m106.aliases:
        cleaned = [a for a in m106.aliases if a.upper() != "QUESTION MARK GALAXY"]
        if len(cleaned) != len(m106.aliases):
            m106.aliases = cleaned
            alias_removed = True
            session.flush()

    parts = []
    if deleted:
        parts.append(f"{deleted} stale cache entry cleared for QUESTION MARK GALAXY")
    if alias_removed:
        parts.append("removed QUESTION MARK GALAXY alias from NGC 4258")
    return "; ".join(parts) if parts else "No changes needed"


def _migrate_v9_stellarium_names(session: Session) -> str:
    """Clear SIMBAD cache entries for common names that now resolve differently via Stellarium."""
    from app.services.stellarium_names import get_stellarium_names
    from app.models.simbad_cache import SimbadCache

    stellarium = get_stellarium_names()
    cleared = 0

    for common_name, simbad_id in stellarium.items():
        normalized = normalize_object_name(common_name)
        cached = session.execute(
            select(SimbadCache).where(SimbadCache.query_name == normalized)
        ).scalar_one_or_none()

        if cached and cached.main_id and cached.main_id != simbad_id:
            session.delete(cached)
            cleared += 1

    if cleared:
        session.flush()

    return f"Cleared {cleared} stale SIMBAD cache entries for Stellarium name corrections"


def _migrate_v10_openngc_messier_common_names(session: Session) -> str:
    """Re-enrich targets from OpenNGC after fixing Messier zero-padding lookup."""
    from app.models import Target

    load_openngc_csv(session)

    targets = session.execute(
        select(Target).where(
            Target.merged_into_id.is_(None),
            Target.common_name.is_(None),
        )
    ).scalars().all()

    total = len(targets)
    enriched = 0
    for target in targets:
        if enrich_target_from_openngc(session, target):
            enriched += 1

    session.flush()
    return f"Re-enriched {enriched}/{total} targets with OpenNGC data (Messier fix)"


def _migrate_v11_hyperleda_galaxies(session: Session) -> str:
    """Backfill HyperLEDA morphological type and inclination for galaxies.

    enrich_target_from_hyperleda is a no-op for non-galaxy targets, so the
    galaxy gate inside it filters the full target list. This re-triggers the
    enrichment that v8 never ran (it predated wiring HyperLEDA in).
    """
    import time
    from app.models import Target
    from app.services.hyperleda import (
        _is_galaxy_type, enrich_target_from_hyperleda, get_cached_hyperleda,
    )

    targets = session.execute(
        select(Target).where(Target.merged_into_id.is_(None))
    ).scalars().all()

    queried = 0
    enriched = 0
    for target in targets:
        # enrich_target_from_hyperleda only hits the network on a cache miss
        # for a galaxy target with a catalog_id. Pre-check those cheap,
        # side-effect-free conditions so the pacing sleep runs only when an
        # actual HTTP call will be made, not for every target.
        will_query = (
            _is_galaxy_type(target.object_type)
            and bool(target.catalog_id)
            and get_cached_hyperleda(target.catalog_id, session) is None
        )

        try:
            if enrich_target_from_hyperleda(session, target):
                enriched += 1
        except SoftTimeLimitExceeded:
            # The Celery soft-limit signal can land inside the HyperLEDA HTTP
            # call. It must propagate to run_data_migrations so the runner can
            # roll back the uncommitted tail and emit the data_upgrade_paused
            # event; swallowing it here would let the task run on to the hard
            # kill with no terminal state written (AUD-035).
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "HyperLEDA enrichment failed for %s: %s",
                target.catalog_id or target.primary_name, exc,
            )

        # Pace network queries to avoid hammering the HyperLEDA endpoint,
        # matching the per-target sleep used by the Gaia/SAC enrichment loop.
        # Skip the sleep for non-galaxies and cache hits, which make no call.
        if will_query:
            queried += 1
            if queried % _MIGRATION_COMMIT_CHUNK == 0:
                session.commit()  # persist partial enrichment so a timeout resumes cheaply
            time.sleep(0.5)

    session.flush()
    return f"HyperLEDA: {enriched} galaxies enriched ({queried} network queries)"


def _migrate_v12_exposure_and_metric_split(session: Session) -> str:
    """Backfill exposure_time and split mislabeled FWHM out of median_hfr.

    Re-derives image-level values from raw_headers after two scanner fixes:

    AUD-001: files carrying only the standard FITS `EXPOSURE` keyword (not
    `EXPTIME`) previously stored exposure_time = NULL, silently zeroing their
    integration in every aggregation. Backfill from raw_headers (EXPTIME first,
    then EXPOSURE) wherever exposure_time is still NULL.

    AUD-007: the scanner previously routed FWHM/MEANFWHM header values into the
    median_hfr column, conflating two different metrics. Move those mislabeled
    values into the new median_fwhm column. raw_headers is the ground truth for
    which source keyword produced each stored value: a row whose headers carry
    no HFR key but do carry MEANFWHM/FWHM, and whose stored median_hfr equals
    that FWHM value, was populated from FWHM and is reclassified. Rows whose
    median_hfr came from a real HFR keyword, the filename, or CSV enrichment
    (value will not match the header FWHM) are left untouched.
    """
    from app.models import Image

    def _to_float(val) -> float | None:
        if val is None:
            return None
        try:
            return float(val)
        except (ValueError, TypeError):
            return None

    # --- AUD-001: backfill NULL exposure_time from raw_headers ---
    exposure_rows = session.execute(
        select(Image.id, Image.raw_headers).where(
            Image.exposure_time.is_(None),
            or_(
                Image.raw_headers.has_key("EXPTIME"),   # noqa: W601 (JSONB ?)
                Image.raw_headers.has_key("EXPOSURE"),  # noqa: W601
            ),
        )
    ).all()

    exposure_updates: list[dict] = []
    for img_id, headers in exposure_rows:
        if not headers:
            continue
        val = _to_float(headers.get("EXPTIME"))
        if val is None:
            val = _to_float(headers.get("EXPOSURE"))
        if val is not None:
            exposure_updates.append({"id": img_id, "exposure_time": val})

    if exposure_updates:
        session.bulk_update_mappings(Image, exposure_updates)
        session.flush()

    # --- AUD-007: reclassify FWHM values mislabeled as median_hfr ---
    hfr_rows = session.execute(
        select(Image.id, Image.median_hfr, Image.raw_headers).where(
            Image.median_hfr.isnot(None),
            Image.median_fwhm.is_(None),
            ~Image.raw_headers.has_key("HFR"),          # noqa: W601
            or_(
                Image.raw_headers.has_key("MEANFWHM"),  # noqa: W601
                Image.raw_headers.has_key("FWHM"),      # noqa: W601
            ),
        )
    ).all()

    metric_updates: list[dict] = []
    for img_id, median_hfr, headers in hfr_rows:
        if not headers or median_hfr is None:
            continue
        # Mirror the old scanner priority: MEANFWHM first, then FWHM.
        fwhm_val = _to_float(headers.get("MEANFWHM"))
        if fwhm_val is None:
            fwhm_val = _to_float(headers.get("FWHM"))
        if fwhm_val is None:
            continue
        # Only reclassify when the stored median_hfr actually came from that
        # FWHM value. A mismatch means the value was a real HFR (CSV/filename),
        # so leave it alone.
        if abs(median_hfr - fwhm_val) <= 1e-6:
            metric_updates.append({
                "id": img_id,
                "median_fwhm": fwhm_val,
                "median_hfr": None,
            })

    if metric_updates:
        session.bulk_update_mappings(Image, metric_updates)
        session.flush()

    parts = []
    if exposure_updates:
        parts.append(f"{len(exposure_updates)} exposures backfilled from raw_headers")
    if metric_updates:
        parts.append(f"{len(metric_updates)} FWHM values moved from median_hfr to median_fwhm")
    return "; ".join(parts) if parts else "No changes needed"


def _migrate_v13_enrich_created_targets(session: Session) -> str:
    """Backfill the per-target enrichment gaps for targets created since v11.

    A target ingested after the last data migration ran only got OpenNGC/VizieR/
    SAC enrichment; it never received the coordinate-based constellation
    fallback, catalog memberships, cluster-gated Gaia distance, or galaxy-gated
    HyperLEDA morphology that migration-time targets got (AUD-006). Prod evidence
    shows 7 of 32 galaxy targets missing hubble_t_type and 95 non-user targets
    with zero catalog memberships, so post-migration creations are demonstrably
    missing enrichment.

    Reuses the exact same per-target logic (enrich_new_target) that the new
    async follow-up task runs, so a migration-time target and a freshly ingested
    one converge. Every step is idempotent, so this migration is safe to replay:
    the per-target enrichers skip already-enriched fields and the membership
    upserts are conflict-updates. Commits every _MIGRATION_COMMIT_CHUNK network
    queries so a timeout resumes cheaply, and re-raises SoftTimeLimitExceeded so
    the runner can write a terminal state (AUD-035).
    """
    import time
    from app.models import Target
    from app.services.catalog_membership import load_all_catalogs
    from app.services.target_enrichment import enrich_new_target

    # Ensure the static catalogs are loaded so per-target membership matching
    # has data to match against (idempotent upserts).
    load_all_catalogs(session)
    session.flush()

    targets = session.execute(
        select(Target).where(Target.merged_into_id.is_(None))
    ).scalars().all()

    const_added = 0
    membership_added = 0
    gaia_added = 0
    hyperleda_added = 0
    queried = 0
    for target in targets:
        if getattr(target, "user_defined", False):
            continue

        try:
            res = enrich_new_target(session, target)
        except SoftTimeLimitExceeded:
            # Propagate so run_data_migrations rolls back the uncommitted tail
            # and emits data_upgrade_paused instead of hitting the hard kill.
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "v13 enrichment failed for %s: %s",
                target.catalog_id or target.primary_name, exc,
            )
            continue

        const_added += 1 if res["constellation"] else 0
        membership_added += res["memberships"]
        gaia_added += 1 if res["gaia"] else 0
        hyperleda_added += 1 if res["hyperleda"] else 0

        # Pace + chunk-commit only when a real network query was made, matching
        # the v8/v11 loops (non-galaxies, non-clusters, and cache hits are free).
        if res["queried_network"]:
            queried += 1
            if queried % _MIGRATION_COMMIT_CHUNK == 0:
                session.commit()  # persist partial enrichment so a timeout resumes cheaply
            time.sleep(0.5)

    session.flush()

    parts = []
    if const_added:
        parts.append(f"{const_added} constellations computed")
    if membership_added:
        parts.append(f"{membership_added} catalog memberships matched")
    if gaia_added:
        parts.append(f"Gaia: {gaia_added} clusters got distances")
    if hyperleda_added:
        parts.append(f"HyperLEDA: {hyperleda_added} galaxies enriched")
    if queried:
        parts.append(f"{queried} network queries")
    return "; ".join(parts) if parts else "No changes needed"


def reference_catalogs_are_empty(session: Session) -> bool:
    """Return True if the static OpenNGC catalog table has no rows.

    OpenNGC is the anchor catalog every other static catalog (SAC, Caldwell,
    Herschel 400, Arp, Abell) and target enrichment depend on, so an empty
    ``openngc_catalog`` table is a reliable signal that the static reference
    data has never been loaded on this database (e.g. a fresh install whose
    baseline seeds a current data_version, so the data-migration functions
    that used to load these catalogs never run - see load_reference_catalogs).
    """
    from app.models.openngc import OpenNGCEntry

    return session.execute(select(OpenNGCEntry.name).limit(1)).first() is None


def load_reference_catalogs(session: Session) -> str:
    """Load all static reference catalogs independent of the data-version gate.

    OpenNGC, SAC, Caldwell, Herschel 400, Arp, and Abell were historically
    loaded only as a side effect of data migrations v3/v7/v13
    (_migrate_v3_load_openngc, _migrate_v8_tier1_and_catalogs,
    _migrate_v13_enrich_created_targets). The v2.0 baseline seeds fresh
    databases at the current data_version so the upgrade gate holds, which
    means those data migrations never run on a fresh install and the catalog
    tables stay permanently empty. This function loads and matches the same
    catalogs directly so boot can call it unconditionally.

    Every loader is a Postgres upsert keyed on a natural key (see
    load_openngc_csv, load_sac_csv, load_catalog_csv, upsert_membership), so
    this is safe to call repeatedly: re-running it updates existing rows in
    place rather than duplicating them.
    """
    from app.services.sac import load_sac_csv
    from app.services.catalog_membership import load_catalog_memberships

    openngc_loaded = load_openngc_csv(session)
    session.flush()

    sac_loaded = load_sac_csv(session)
    session.flush()

    membership_summary = load_catalog_memberships(session)
    session.flush()

    return (
        f"OpenNGC: {openngc_loaded} entries; SAC: {sac_loaded} entries; "
        f"{membership_summary}"
    )


# Registry: version number -> (description, migration function)
# Version numbers must be sequential starting from 1.
MIGRATIONS: dict[int, tuple[str, Callable[[Session], str]]] = {
    1: ("Fix catalog designations (strip NAME prefix, re-derive from cache)", _migrate_v1_fix_catalog_designations),
    2: ("Re-derive designations with improved cache lookup (fixes targets v1 missed)", _migrate_v1_fix_catalog_designations),
    3: ("Load OpenNGC catalog and enrich targets with size/magnitude", _migrate_v3_load_openngc),
    4: ("VizieR enrichment and OpenNGC common name backfill", _migrate_v4_vizier_and_common_names),
    5: ("Strip panel suffixes from target aliases", _migrate_v5_strip_panel_aliases),
    6: ("Clear negative VizieR cache, re-enrich targets, compute constellations", _migrate_v6_clear_negative_cache_and_reenrich),
    7: ("Load Tier 1 catalogs, match memberships, enrich from Gaia/SAC", _migrate_v8_tier1_and_catalogs),
    8: ("Fix Question Mark Galaxy mapping from NGC 4258 to NGC 5194 (M51)", _migrate_v8_fix_question_mark_galaxy),
    9: ("Stellarium common name cache refresh", _migrate_v9_stellarium_names),
    10: ("Re-enrich targets from OpenNGC (Messier lookup fix)", _migrate_v10_openngc_messier_common_names),
    11: ("Backfill HyperLEDA morphological type and inclination for galaxies", _migrate_v11_hyperleda_galaxies),
    12: ("Backfill exposure_time from EXPOSURE keyword and split FWHM out of median_hfr", _migrate_v12_exposure_and_metric_split),
    13: ("Backfill per-target enrichment (constellation, memberships, Gaia, HyperLEDA) for targets created since v11", _migrate_v13_enrich_created_targets),
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
