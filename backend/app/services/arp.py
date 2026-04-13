"""Arp catalog service - load CSV and match to targets."""
from __future__ import annotations

import csv
import logging
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.models.arp_catalog import ArpEntry
from app.models.target import Target
from app.services.openngc import normalize_ngc_name
from app.services.catalog_membership import upsert_membership

logger = logging.getLogger(__name__)

CSV_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "catalogs" / "arp.csv"


def load_arp_csv(session: Session) -> int:
    """Load the bundled Arp CSV into the arp_catalog table.

    Returns the number of rows loaded.
    """
    if not CSV_PATH.exists():
        logger.error("Arp CSV not found at %s", CSV_PATH)
        return 0

    count = 0
    with open(CSV_PATH, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            arp_id = row.get("arp_id", "").strip()
            if not arp_id:
                continue

            entry = {
                "arp_id": arp_id,
                "ngc_ic_ids": row.get("ngc_ic_ids", "").strip() or None,
                "peculiarity_class": row.get("peculiarity_class", "").strip() or None,
                "peculiarity_description": row.get("peculiarity_description", "").strip() or None,
            }

            stmt = pg_insert(ArpEntry).values(**entry).on_conflict_do_update(
                index_elements=["arp_id"],
                set_=entry,
            )
            session.execute(stmt)
            count += 1

    session.flush()
    logger.info("Loaded %d Arp entries", count)
    return count


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

            # Find target by catalog_id or aliases
            target = session.execute(
                select(Target).where(
                    Target.merged_into_id.is_(None),
                    Target.catalog_id == normalized,
                )
            ).scalar_one_or_none()

            if not target:
                target = session.execute(
                    select(Target).where(
                        Target.merged_into_id.is_(None),
                        Target.aliases.any(normalized),
                    )
                ).scalars().first()

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
