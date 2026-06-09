"""Caldwell catalog service - load CSV and match to targets."""
from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy.orm import Session

from app.models.caldwell_catalog import CaldwellEntry
from app.services.catalog_base import load_catalog_csv, match_ngc_catalog

logger = logging.getLogger(__name__)

CSV_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "catalogs" / "caldwell.csv"


def load_caldwell_csv(session: Session) -> int:
    """Load the bundled Caldwell CSV into the caldwell_catalog table.

    Returns the number of rows loaded.
    """
    def build_entry(row: dict) -> dict:
        return {
            "catalog_id": row.get("catalog_id", "").strip(),
            "ngc_ic_id": row.get("ngc_ic_id", "").strip() or None,
            "object_type": row.get("object_type", "").strip() or None,
            "constellation": row.get("constellation", "").strip() or None,
            "common_name": row.get("common_name", "").strip() or None,
        }

    return load_catalog_csv(
        session,
        csv_path=CSV_PATH,
        model=CaldwellEntry,
        key_field="catalog_id",
        conflict_index="catalog_id",
        build_entry=build_entry,
        label="Caldwell",
        logger=logger,
    )


def match_caldwell_targets(session: Session) -> int:
    """Match Caldwell entries to existing targets.

    Returns the number of matches created.
    """
    return match_ngc_catalog(
        session,
        model=CaldwellEntry,
        catalog_name="caldwell",
        ngc_field="ngc_ic_id",
        get_catalog_number=lambda entry: entry.catalog_id,
        build_metadata=lambda entry: {
            "caldwell_number": int(entry.catalog_id[1:]),  # Strip 'C' prefix
            "ngc_ic": entry.ngc_ic_id,
        },
        label="Caldwell",
        logger=logger,
    )
