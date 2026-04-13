"""Caldwell catalog service - load CSV and match to targets."""
from __future__ import annotations

import csv
import logging
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.models.caldwell_catalog import CaldwellEntry
from app.models.target import Target
from app.services.openngc import normalize_ngc_name
from app.services.catalog_membership import upsert_membership

logger = logging.getLogger(__name__)

CSV_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "catalogs" / "caldwell.csv"


def load_caldwell_csv(session: Session) -> int:
    """Load the bundled Caldwell CSV into the caldwell_catalog table.

    Returns the number of rows loaded.
    """
    if not CSV_PATH.exists():
        logger.error("Caldwell CSV not found at %s", CSV_PATH)
        return 0

    count = 0
    with open(CSV_PATH, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            catalog_id = row.get("catalog_id", "").strip()
            if not catalog_id:
                continue

            entry = {
                "catalog_id": catalog_id,
                "ngc_ic_id": row.get("ngc_ic_id", "").strip() or None,
                "object_type": row.get("object_type", "").strip() or None,
                "constellation": row.get("constellation", "").strip() or None,
                "common_name": row.get("common_name", "").strip() or None,
            }

            stmt = pg_insert(CaldwellEntry).values(**entry).on_conflict_do_update(
                index_elements=["catalog_id"],
                set_=entry,
            )
            session.execute(stmt)
            count += 1

    session.flush()
    logger.info("Loaded %d Caldwell entries", count)
    return count


def match_caldwell_targets(session: Session) -> int:
    """Match Caldwell entries to existing targets.

    Returns the number of matches created.
    """
    entries = session.execute(select(CaldwellEntry)).scalars().all()
    matched = 0

    for entry in entries:
        if not entry.ngc_ic_id:
            continue

        normalized = normalize_ngc_name(entry.ngc_ic_id)

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
            caldwell_num = entry.catalog_id[1:]  # Strip 'C' prefix
            upsert_membership(
                session,
                target_id=target.id,
                catalog_name="caldwell",
                catalog_number=entry.catalog_id,
                metadata={
                    "caldwell_number": int(caldwell_num),
                    "ngc_ic": entry.ngc_ic_id,
                },
            )
            matched += 1

    session.flush()
    logger.info("Matched %d Caldwell targets", matched)
    return matched
