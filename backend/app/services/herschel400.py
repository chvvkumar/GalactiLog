"""Herschel 400 catalog service - load CSV and match to targets."""
from __future__ import annotations

import csv
import logging
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.models.herschel400_catalog import Herschel400Entry
from app.models.target import Target
from app.services.openngc import normalize_ngc_name
from app.services.catalog_membership import upsert_membership

logger = logging.getLogger(__name__)

CSV_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "catalogs" / "herschel400.csv"


def load_herschel400_csv(session: Session) -> int:
    """Load the bundled Herschel 400 CSV into the herschel400_catalog table.

    Returns the number of rows loaded.
    """
    if not CSV_PATH.exists():
        logger.error("Herschel 400 CSV not found at %s", CSV_PATH)
        return 0

    count = 0
    with open(CSV_PATH, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ngc_id = row.get("ngc_id", "").strip()
            if not ngc_id:
                continue

            def _parse_float(val: str | None) -> float | None:
                if not val or not val.strip():
                    return None
                try:
                    return float(val.strip())
                except ValueError:
                    return None

            entry = {
                "ngc_id": ngc_id,
                "object_type": row.get("object_type", "").strip() or None,
                "constellation": row.get("constellation", "").strip() or None,
                "magnitude": _parse_float(row.get("magnitude")),
            }

            stmt = pg_insert(Herschel400Entry).values(**entry).on_conflict_do_update(
                index_elements=["ngc_id"],
                set_=entry,
            )
            session.execute(stmt)
            count += 1

    session.flush()
    logger.info("Loaded %d Herschel 400 entries", count)
    return count


def match_herschel400_targets(session: Session) -> int:
    """Match Herschel 400 entries to existing targets.

    Returns the number of matches created.
    """
    entries = session.execute(select(Herschel400Entry)).scalars().all()
    matched = 0

    for entry in entries:
        normalized = normalize_ngc_name(entry.ngc_id)

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
            upsert_membership(
                session,
                target_id=target.id,
                catalog_name="herschel400",
                catalog_number="H400",
                metadata={
                    "constellation": entry.constellation,
                    "type": entry.object_type,
                    "magnitude": entry.magnitude,
                },
            )
            matched += 1

    session.flush()
    logger.info("Matched %d Herschel 400 targets", matched)
    return matched
