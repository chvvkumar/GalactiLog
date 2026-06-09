"""Arp catalog service - load CSV and match to targets."""
from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.arp_catalog import ArpEntry
from app.services.openngc import normalize_ngc_name
from app.services.catalog_membership import upsert_membership
from app.services.catalog_base import load_catalog_csv, find_target_by_ngc

logger = logging.getLogger(__name__)

CSV_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "catalogs" / "arp.csv"


def load_arp_csv(session: Session) -> int:
    """Load the bundled Arp CSV into the arp_catalog table.

    Returns the number of rows loaded.
    """
    def build_entry(row: dict) -> dict:
        return {
            "arp_id": row.get("arp_id", "").strip(),
            "ngc_ic_ids": row.get("ngc_ic_ids", "").strip() or None,
            "peculiarity_class": row.get("peculiarity_class", "").strip() or None,
            "peculiarity_description": row.get("peculiarity_description", "").strip() or None,
        }

    return load_catalog_csv(
        session,
        csv_path=CSV_PATH,
        model=ArpEntry,
        key_field="arp_id",
        conflict_index="arp_id",
        build_entry=build_entry,
        label="Arp",
        logger=logger,
    )


def match_arp_targets(session: Session) -> int:
    """Match Arp entries to existing targets.

    One Arp entry can match multiple targets (e.g. interacting galaxy pairs).
    Returns the number of matches created.
    """
    entries = session.execute(select(ArpEntry)).scalars().all()
    matched = 0

    for entry in entries:
        if not entry.ngc_ic_ids:
            continue

        # Parse arp_number from arp_id (e.g. "Arp 77" -> 77)
        arp_number = None
        parts = entry.arp_id.split()
        if len(parts) == 2:
            try:
                arp_number = int(parts[1])
            except ValueError:
                pass

        # Split comma-separated NGC/IC identifiers
        ids = [s.strip() for s in entry.ngc_ic_ids.split(",") if s.strip()]

        for ngc_ic_id in ids:
            normalized = normalize_ngc_name(ngc_ic_id)
            target = find_target_by_ngc(session, normalized)

            if target:
                metadata = {"peculiarity_class": entry.peculiarity_class}
                if arp_number is not None:
                    metadata["arp_number"] = arp_number
                upsert_membership(
                    session,
                    target_id=target.id,
                    catalog_name="arp",
                    catalog_number=entry.arp_id,
                    metadata=metadata,
                )
                matched += 1

    session.flush()
    logger.info("Matched %d Arp targets", matched)
    return matched
