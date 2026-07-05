"""Catalog membership service - load static catalogs and match to targets."""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.models.catalog_membership import TargetCatalogMembership

logger = logging.getLogger(__name__)


def upsert_membership(
    session: Session,
    target_id,
    catalog_name: str,
    catalog_number: str,
    metadata: dict | None = None,
) -> None:
    """Upsert a single TargetCatalogMembership record."""
    # pg_insert().values() uses ORM attribute names (metadata_),
    # but on_conflict_do_update set_ uses DB column names (metadata).
    stmt = pg_insert(TargetCatalogMembership).values(
        target_id=target_id,
        catalog_name=catalog_name,
        catalog_number=catalog_number,
        metadata_=metadata,
    ).on_conflict_do_update(
        constraint="uq_target_catalog",
        set_={
            "catalog_number": catalog_number,
            "metadata": metadata,
        },
    )
    session.execute(stmt)


def load_all_catalogs(session: Session) -> str:
    """Load all static catalog CSVs into their tables."""
    from app.services.caldwell import load_caldwell_csv
    from app.services.herschel400 import load_herschel400_csv
    from app.services.arp import load_arp_csv
    from app.services.abell import load_abell_csv

    results = []
    results.append(f"Caldwell: {load_caldwell_csv(session)} entries")
    results.append(f"Herschel 400: {load_herschel400_csv(session)} entries")
    results.append(f"Arp: {load_arp_csv(session)} entries")
    results.append(f"Abell: {load_abell_csv(session)} entries")

    summary = "Loaded catalogs: " + ", ".join(results)
    logger.info(summary)
    return summary


def match_all_memberships(session: Session) -> str:
    """Match all static catalogs to existing targets."""
    from app.services.caldwell import match_caldwell_targets
    from app.services.herschel400 import match_herschel400_targets
    from app.services.arp import match_arp_targets
    from app.services.abell import match_abell_targets

    results = []
    results.append(f"Caldwell: {match_caldwell_targets(session)} matches")
    results.append(f"Herschel 400: {match_herschel400_targets(session)} matches")
    results.append(f"Arp: {match_arp_targets(session)} matches")
    results.append(f"Abell: {match_abell_targets(session)} matches")

    summary = "Matched memberships: " + ", ".join(results)
    logger.info(summary)
    return summary


def match_target_memberships(session: Session, target) -> int:
    """Match all static catalogs to a single target.

    Per-target inverse of ``match_all_memberships``: each catalog is scanned for
    entries matching this one target's identifiers, so ingest never re-scans the
    whole targets table. Assumes the static catalogs are already loaded. All
    upserts are idempotent, so this is safe to re-run. Returns total matches.
    """
    from app.services.caldwell import match_caldwell_for_target
    from app.services.herschel400 import match_herschel400_for_target
    from app.services.arp import match_arp_for_target
    from app.services.abell import match_abell_for_target

    total = 0
    total += match_caldwell_for_target(session, target)
    total += match_herschel400_for_target(session, target)
    total += match_arp_for_target(session, target)
    total += match_abell_for_target(session, target)
    return total


def load_catalog_memberships(session: Session) -> str:
    """Load all static catalogs and match memberships."""
    load_summary = load_all_catalogs(session)
    match_summary = match_all_memberships(session)
    return f"{load_summary}\n{match_summary}"
