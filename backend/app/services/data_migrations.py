"""Auto data migrations - backfill logic that runs when DATA_VERSION advances.

Each migration is a function that receives a sync SQLAlchemy Session and returns
a summary string. Register new migrations in MIGRATIONS with the next version number.
"""

import logging
import math
from typing import Callable

from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy import or_, select, text, update
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
DATA_VERSION = 17

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


def _header_float(headers: dict, key: str) -> float | None:
    """Read a header value out of raw_headers as a float, or None."""
    if not headers:
        return None
    val = headers.get(key)
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _classify_eccentricity_source(headers: dict, stored: float) -> str | None:
    """Infer which origin produced a stored eccentricity, from raw_headers.

    raw_headers captures every header verbatim, so it is the ground truth for
    what the scanner had to work with -- the same principle the AUD-007
    reclassification relies on. Replay the scanner's precedence and compare:

    - A native ECCENTRICITY equal to the stored value means the value came
      straight from the header ("header"). ECCENTRICITY wins outright in the
      scanner, so ELLIPTICITY is not even consulted when it is present.
    - Otherwise, an ELLIPTICITY whose transform reproduces the stored value
      means the value was derived ("ellipticity").
    - Anything else is unknown (None). Most importantly, a CSV-sourced
      eccentricity never enters raw_headers, so it is simply not recoverable;
      a mismatch against a present header is exactly what a CSV override looks
      like. NULL is informative here -- it means "unknown/pre-migration", not
      "no source".
    """
    ecc = _header_float(headers, "ECCENTRICITY")
    if ecc is not None:
        return "header" if abs(stored - ecc) <= 1e-6 else None

    ellip = _header_float(headers, "ELLIPTICITY")
    if ellip is None:
        return None
    axis_ratio = 1.0 - ellip
    val = 1.0 - axis_ratio * axis_ratio
    if val < 0:
        return None
    derived = math.sqrt(val)
    return "ellipticity" if abs(stored - derived) <= 1e-6 else None


def _migrate_v14_eccentricity_provenance(session: Session) -> str:
    """Backfill eccentricity_source and altitude_deg from raw_headers.

    Re-derives image-level values from raw_headers after two scanner changes,
    exactly as v12 did for exposure_time/median_fwhm:

    eccentricity_source: `eccentricity` collapsed three non-comparable origins
    (native ECCENTRICITY, a value converted from ELLIPTICITY, and the N.I.N.A.
    CSV) into one column. Provenance is recovered by replaying the scanner's
    transform against raw_headers and comparing to the stored value; see
    _classify_eccentricity_source. CSV-sourced values are not recoverable and
    stay NULL.

    altitude_deg: the frame-centre altitude (OBJCTALT, else CENTALT) was never
    read into a column, though existing rows carry it in raw_headers. Without
    it an eccentricity cannot be separated from atmospheric dispersion, which
    scales with tan(zenith distance). Backfilled here rather than left to wait
    on a full re-ingest, for the same reason v12 backfilled exposure_time: the
    data is already on hand and the column is useless empty.

    Idempotent: only rows still NULL in the respective column are selected, and
    the inference is a pure function of raw_headers, so replaying is a no-op.
    """
    from app.models import Image

    # --- eccentricity provenance ---
    ecc_rows = session.execute(
        select(Image.id, Image.eccentricity, Image.raw_headers).where(
            Image.eccentricity.isnot(None),
            Image.eccentricity_source.is_(None),
            or_(
                Image.raw_headers.has_key("ECCENTRICITY"),  # noqa: W601 (JSONB ?)
                Image.raw_headers.has_key("ELLIPTICITY"),   # noqa: W601
            ),
        )
    ).all()

    source_updates: list[dict] = []
    for img_id, stored, headers in ecc_rows:
        if not headers or stored is None:
            continue
        source = _classify_eccentricity_source(headers, stored)
        if source is not None:
            source_updates.append({"id": img_id, "eccentricity_source": source})

    if source_updates:
        session.bulk_update_mappings(Image, source_updates)
        session.flush()

    # --- altitude ---
    alt_rows = session.execute(
        select(Image.id, Image.raw_headers).where(
            Image.altitude_deg.is_(None),
            or_(
                Image.raw_headers.has_key("OBJCTALT"),  # noqa: W601
                Image.raw_headers.has_key("CENTALT"),   # noqa: W601
            ),
        )
    ).all()

    altitude_updates: list[dict] = []
    for img_id, headers in alt_rows:
        if not headers:
            continue
        # Mirror the scanner's precedence: OBJCTALT first, then CENTALT.
        alt = _header_float(headers, "OBJCTALT")
        if alt is None:
            alt = _header_float(headers, "CENTALT")
        if alt is not None:
            altitude_updates.append({"id": img_id, "altitude_deg": alt})

    if altitude_updates:
        session.bulk_update_mappings(Image, altitude_updates)
        session.flush()

    parts = []
    if source_updates:
        parts.append(f"{len(source_updates)} eccentricity sources recovered from raw_headers")
    if altitude_updates:
        parts.append(f"{len(altitude_updates)} altitudes backfilled from raw_headers")
    return "; ".join(parts) if parts else "No changes needed"


def _migrate_v15_arcsec_per_pixel(session: Session) -> str:
    """Backfill the materialized plate scale (arcsec_per_pixel) from raw_headers.

    Re-derives an image-level value from raw_headers after a schema change,
    exactly as v12/v14 did: alembic 0021 added images.arcsec_per_pixel so
    /api/stats aggregations no longer have to derive the plate scale per-row
    from JSONB (regex-guarded text casts, units.sql_arcsec_per_pixel), which
    is what made the cold path take tens of seconds. The scanner now sets the
    column at ingest; existing rows carry XPIXSZ/FOCALLEN in raw_headers, so
    the value is backfilled here rather than left to wait on a full re-ingest.

    Uses units.plate_scale_from_headers, the Python counterpart of the SQL
    expression, so the backfilled values match what the scanner writes and
    what the SQL derivation produced (same keyword semantics, None for
    missing/non-numeric/non-positive inputs).

    Idempotent: only rows still NULL in arcsec_per_pixel are selected, and the
    derivation is a pure function of raw_headers, so replaying is a no-op.
    """
    from app.models import Image
    from app.services.units import plate_scale_from_headers

    rows = session.execute(
        select(Image.id, Image.raw_headers).where(
            Image.arcsec_per_pixel.is_(None),
            Image.raw_headers.has_key("XPIXSZ"),    # noqa: W601 (JSONB ?)
            Image.raw_headers.has_key("FOCALLEN"),  # noqa: W601
        )
    ).all()

    updates: list[dict] = []
    for img_id, headers in rows:
        scale = plate_scale_from_headers(headers)
        if scale is not None:
            updates.append({"id": img_id, "arcsec_per_pixel": scale})

    if updates:
        session.bulk_update_mappings(Image, updates)
        session.flush()

    if updates:
        return f"{len(updates)} plate scales backfilled from raw_headers"
    return "No changes needed"


def _migrate_v16_guiding_rms_provenance(session: Session) -> str:
    """Stamp CSV guiding provenance, re-key the PHD2 profile map, fill history.

    GROUND TRUTH IS NOT raw_headers HERE. v12, v14 and v15 all re-derived an
    image value from the headers the scanner had captured verbatim. A frame's
    guiding RMS was never in its FITS header: it arrived from a N.I.N.A.
    sidecar CSV that this application does not retain, or it did not arrive at
    all. Two other facts stand in:

    1. Until alembic 0023 there was exactly one writer of guiding_rms_arcsec
       and its RA/Dec siblings - csv_metadata.IMAGE_COLUMN_MAP, fed by the
       N.I.N.A. sidecar. So every value already stored is CSV-sourced by
       construction, and stamping it "csv" is a statement about the code that
       wrote it, not an inference about the data.
    2. phd2_sessions and phd2_frames hold the full guide sample stream, which
       is what services/phd2_correlation reads. Frames still missing a value
       are exactly the ones the guide logs may be able to supply.

    Three steps, in this order because each depends on the last:

    (a) Re-key phd2_profile_map through the current equipment aliases, and
        re-point the stored sessions at the corrected values. A profile mapped
        before its telescope was grouped under a canonical name stores the raw
        name, and nothing ever rewrote it; query-time expansion
        (normalization.equipment_match_set) hides that on reads, but the
        correlation in (c) attributes on the stored value, so it has to be
        right before it runs. Doing it here means an existing install heals
        without the user having to re-save the equipment settings.

    (b) Stamp existing guiding values "csv" (see 1 above). Set-based UPDATE.

    (c) Correlate the full history. Only rows whose guiding_rms_arcsec is
        still NULL after (b) are candidates, so this never competes with the
        CSV, and correlate_dates in incremental mode visits only the nights
        holding both an unfilled frame and a guiding session.

    Idempotent: (a) rewrites only map values the alias map actually changes,
    (b) selects only rows still NULL in guiding_rms_source, and (c) selects
    only rows still NULL in guiding_rms_arcsec, so a replay does nothing.

    Bounded: (a) and (b) are single statements; (c) is proportional to the
    guide-log corpus, not to the image catalog - 34k images against 799
    sessions on the production clone is the sizing reference.
    """
    from app.models import Image
    from app.models.phd2 import Phd2Calibration, Phd2Session
    from app.models.user_settings import SETTINGS_ROW_ID, UserSettings
    from app.services.normalization import (
        build_equipment_alias_maps, normalize_equipment,
    )
    from app.services.phd2_correlation import (
        GUIDING_RMS_SOURCE_CSV, correlate_dates,
    )
    from app.services.phd2_profiles import rewrite_telescopes, telescope_map

    parts: list[str] = []

    # --- (a) re-key the profile map and the rows it wrote ---
    settings_row = session.get(UserSettings, SETTINGS_ROW_ID)
    rekeyed = 0
    if settings_row is not None:
        general = dict(settings_row.general or {})
        stored_map = general.get("phd2_profile_map") or {}
        if stored_map:
            _, tel_map = build_equipment_alias_maps(settings_row.equipment or {})
            # phd2_profiles owns the stored shape, and a map entry carries a
            # timezone and a site as well as a telescope. Rebuilding the map
            # here from bare names, as this step originally did, flattens both
            # away on an install that has already configured them, so the
            # rewrite goes through rewrite_telescopes: it moves only the
            # telescope field and leaves the rest of every entry intact. It
            # also absorbs the "an unrecognised name is left alone" fallback,
            # which is why no `or name` is written here.
            corrected = rewrite_telescopes(
                stored_map, lambda name: normalize_equipment(name, tel_map)
            )
            # Diffed on the telescope projection of both sides, never on the
            # stored value itself: a map still in the legacy string form always
            # differs from its canonical form, so comparing the raw shapes
            # would count a re-key on every install that has never been
            # normalized and re-point rows that nothing renamed.
            before = telescope_map(stored_map)
            for profile, canonical in telescope_map(corrected).items():
                if before.get(profile) != canonical:
                    rekeyed += 1
                    for model in (Phd2Session, Phd2Calibration):
                        session.execute(
                            update(model)
                            .where(model.equipment_profile == profile)
                            .values(telescope=canonical)
                            .execution_options(synchronize_session=False)
                        )
            if rekeyed:
                # Whole-value assignment, not a mutation of the stored dict:
                # SQLAlchemy tracks JSONB changes by identity, so mutating in
                # place would not be flushed.
                settings_row.general = {
                    **general, "phd2_profile_map": corrected,
                }
                session.flush()
                parts.append(f"{rekeyed} PHD2 profile mapping(s) re-keyed")

    # --- (b) stamp the existing CSV-sourced values ---
    stamped = session.execute(
        update(Image)
        .where(
            Image.guiding_rms_arcsec.isnot(None),
            Image.guiding_rms_source.is_(None),
        )
        .values(guiding_rms_source=GUIDING_RMS_SOURCE_CSV)
        .execution_options(synchronize_session=False)
    ).rowcount
    session.flush()
    if stamped:
        parts.append(f"{stamped} guiding RMS value(s) stamped as CSV-sourced")

    # --- (c) fill the remaining history from the guide logs ---
    result = correlate_dates(session, None)
    session.flush()
    if result.filled:
        parts.append(
            f"{result.filled} frame(s) given a guiding RMS from PHD2 logs "
            f"over {result.dates} night(s)"
        )

    return "; ".join(parts) if parts else "No changes needed"


def _dispatch_phd2_reparse() -> bool:
    """Queue a forced re-parse of every guide log already in the catalog.

    Returns True when the task was handed to the broker. A dev box or a
    single-container install may have no worker or no broker reachable, and a
    data migration that has already committed its own work must not fail on
    that, so the failure is logged and swallowed exactly as the settings
    endpoints' dispatches do.

    No new Celery task exists for this: `scan_phd2_logs(force=True)` is the
    same entry point a timezone save uses, and forcing bypasses the size/mtime
    short-circuit that would otherwise skip every stored log.

    Queued with a countdown rather than immediately because the migration's
    own transaction has not committed when this runs; the delay keeps the pass
    from reading the settings row while the rewrite of it is still in flight.
    """
    try:
        from app.worker.tasks import scan_phd2_logs

        scan_phd2_logs.apply_async(kwargs={"force": True}, countdown=15)
    except Exception:  # noqa: BLE001 - worker may not be available
        logger.warning(
            "data_migrations: could not queue the forced PHD2 re-parse; to "
            "pick it up by hand, change a timezone to a different value and "
            "save, then change it back and save again - either Settings > "
            "Library > Observer Location > Timezone or any PHD2 profile's own "
            "timezone will do, and each of those two saves queues a forced "
            "pass. Re-saving the same value queues nothing, and a library "
            "scan will not do it either: unchanged guide logs short-circuit "
            "on size and mtime before the new parser is reached",
            exc_info=True,
        )
        return False
    return True


def _migrate_v17_phd2_profile_map_shape(session: Session) -> str:
    """Give each PHD2 profile mapping its own timezone and site slot.

    The stored map used to be `{"Rig A": "Askar 120"}`: a profile name against
    a telescope name and nothing else, so every rig in the catalog was read
    under the one global observer timezone and the one global observer
    location. A user with a remote rig has neither. The map is now one entry
    per profile::

        {"Rig A": {"telescope": "Askar 120", "timezone": "America/Chicago",
                   "latitude": 30.27, "longitude": -97.74}}

    `services.phd2_profiles.normalize_profile_map` is the sole owner of that
    conversion and every reader already calls it, so this migration changes no
    behaviour on its own: it writes the canonical form into the settings row
    once, so the settings screen has a field to edit and the stored value stops
    being coerced on every read.

    Nothing is re-derived from the conversion itself. An upgraded profile
    carries an empty timezone and null coordinates, which mean "inherit the
    global values" - exactly what the install already did - so no stored
    instant moves and there is no correlation to redo.

    THE FORCED RE-PARSE BELOW IS NOT PART OF THAT, AND IS NOT REMOVABLE AS
    UNNECESSARY. It is here because the guide-log parser itself changed in the
    same release: it learned the ASIAIR banner, the pointing fields and the
    `Calibration step = ` prefix. Stored rows are therefore stale by
    construction, and the ones that suffer most are already held as
    `parse_status="empty"` with unchanged size and mtime, so ingest
    short-circuits to "unchanged" and never reaches the new parser. Only a
    forced pass re-reads them. It re-parses, re-keys and re-applies in the
    worker; this function performs no correlation of its own.

    Idempotent: the settings row is rewritten only when the stored map is not
    already canonical, and re-running the forced pass re-derives the same rows
    from the same files.
    """
    from app.models.user_settings import SETTINGS_ROW_ID, UserSettings
    from app.services.phd2_profiles import normalize_profile_map

    parts: list[str] = []

    settings_row = session.get(UserSettings, SETTINGS_ROW_ID)
    if settings_row is not None:
        general = dict(settings_row.general or {})
        stored_map = general.get("phd2_profile_map") or {}
        corrected = normalize_profile_map(stored_map)
        if corrected != stored_map:
            # Whole-value assignment, not a mutation of the stored dict:
            # SQLAlchemy tracks JSONB changes by identity, so mutating in
            # place would not be flushed (same reason as v16 step (a)).
            settings_row.general = {**general, "phd2_profile_map": corrected}
            session.flush()
            parts.append(
                f"{len(corrected)} PHD2 profile mapping(s) given a timezone "
                "and site of their own"
            )

    if _dispatch_phd2_reparse():
        parts.append("guide logs queued for a forced re-parse")

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
    14: ("Recover eccentricity provenance and backfill frame altitude from raw_headers", _migrate_v14_eccentricity_provenance),
    15: ("Backfill materialized plate scale (arcsec_per_pixel) from raw_headers", _migrate_v15_arcsec_per_pixel),
    16: ("Stamp CSV guiding provenance, re-key the PHD2 profile map, and correlate guiding to frames", _migrate_v16_guiding_rms_provenance),
    17: ("Give each PHD2 profile mapping its own timezone slot", _migrate_v17_phd2_profile_map_shape),
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
