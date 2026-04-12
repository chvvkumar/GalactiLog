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
    values = {
        "target_id": target_id,
        "catalog_name": catalog_name,
        "catalog_number": catalog_number,
        "metadata_": metadata,
    }
    stmt = pg_insert(TargetCatalogMembership).values(**values).on_conflict_do_update(
        constraint="uq_target_catalog",
        set_={
            "catalog_number": catalog_number,
            "metadata_": metadata,
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


def load_catalog_memberships(session: Session) -> str:
    """Load all static catalogs and match memberships."""
    load_summary = load_all_catalogs(session)
    match_summary = match_all_memberships(session)
    return f"{load_summary}\n{match_summary}"
