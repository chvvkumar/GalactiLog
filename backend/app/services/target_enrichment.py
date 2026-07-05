"""Per-target follow-up enrichment (AUD-006).

`_create_target` (the live ingest path) only enriches a new target via
OpenNGC/VizieR/SAC. The Gaia distance, HyperLEDA morphology/inclination,
catalog-membership matching, and coordinate-based constellation fallback that
the data migrations apply once when DATA_VERSION advances are never run for a
target created after the last migration, so it can permanently diverge from a
target that existed at migration time.

`enrich_new_target` closes exactly those gaps for a single target, reusing the
same gated enrichers the migrations use. It is dispatched asynchronously as a
Celery follow-up so ingest is not blocked on network latency, and it is re-run
by the v13 data migration to backfill targets created since v11. Every step is
idempotent / non-destructive, so retries and replays are safe.
"""
from __future__ import annotations

import logging

from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def enrich_new_target(session: Session, target) -> dict:
    """Run the narrow post-create enrichment gaps for one target, idempotently.

    Steps (each gated / non-destructive):
      1. Coordinate-based constellation fallback, ONLY when constellation is
         still None after the OpenNGC/VizieR chain.
      2. Per-target catalog membership matching (Herschel 400 / Caldwell / Arp /
         Abell) against the already-loaded static catalogs -- never scans the
         targets table.
      3. Gaia distance (the cluster gate lives inside enrich_target_from_gaia).
      4. HyperLEDA morphology/inclination (the galaxy gate + cache pre-check
         live inside enrich_target_from_hyperleda).

    Returns a summary dict. ``queried_network`` is True when step 3 or 4 will
    make a live HTTP call on a cache miss, so a batch caller (the v13 migration)
    can pace and chunk-commit exactly as the v8/v11 loops do.
    """
    from app.services.constellation import coords_to_constellation
    from app.services.catalog_membership import match_target_memberships
    from app.services.gaia import (
        _is_cluster_type, enrich_target_from_gaia, get_cached_gaia,
    )
    from app.services.hyperleda import (
        _is_galaxy_type, enrich_target_from_hyperleda, get_cached_hyperleda,
    )

    result = {
        "constellation": False,
        "memberships": 0,
        "gaia": False,
        "hyperleda": False,
        "queried_network": False,
    }

    # 1. Constellation fallback (final resort after OpenNGC/VizieR).
    if (
        target.constellation is None
        and target.ra is not None
        and target.dec is not None
    ):
        constellation = coords_to_constellation(target.ra, target.dec)
        if constellation:
            target.constellation = constellation
            result["constellation"] = True

    # 2. Per-target catalog memberships (idempotent upserts).
    result["memberships"] = match_target_memberships(session, target)

    # 3. Gaia distance (cluster gate inside). Pre-check the cache so the batch
    #    caller only paces when a real HTTP call will be made.
    if (
        _is_cluster_type(target.object_type)
        and target.ra is not None
        and target.dec is not None
        and get_cached_gaia(target.id, session) is None
    ):
        result["queried_network"] = True
    if enrich_target_from_gaia(session, target):
        result["gaia"] = True

    # 4. HyperLEDA morphology/inclination (galaxy gate + cache pre-check inside).
    if (
        _is_galaxy_type(target.object_type)
        and bool(target.catalog_id)
        and get_cached_hyperleda(target.catalog_id, session) is None
    ):
        result["queried_network"] = True
    try:
        if enrich_target_from_hyperleda(session, target):
            result["hyperleda"] = True
    except SoftTimeLimitExceeded:
        # Must propagate so a batch runner can roll back its uncommitted tail
        # and write a terminal state instead of running on to the hard kill.
        raise
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "HyperLEDA enrichment failed for %s: %s",
            target.catalog_id or target.primary_name, exc,
        )

    return result
