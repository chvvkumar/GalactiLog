"""Herschel 400 catalog service - load CSV and match to targets."""
from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy.orm import Session

from app.models.herschel400_catalog import Herschel400Entry
from app.services.catalog_base import (
    load_catalog_csv, match_ngc_catalog, match_ngc_catalog_for_target, parse_float,
)

logger = logging.getLogger(__name__)

CSV_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "catalogs" / "herschel400.csv"


def load_herschel400_csv(session: Session) -> int:
    """Load the bundled Herschel 400 CSV into the herschel400_catalog table.

    Returns the number of rows loaded.
    """
    def build_entry(row: dict) -> dict:
        return {
            "ngc_id": row.get("ngc_id", "").strip(),
            "object_type": row.get("object_type", "").strip() or None,
            "constellation": row.get("constellation", "").strip() or None,
            "magnitude": parse_float(row.get("magnitude")),
        }

    return load_catalog_csv(
        session,
        csv_path=CSV_PATH,
        model=Herschel400Entry,
        key_field="ngc_id",
        conflict_index="ngc_id",
        build_entry=build_entry,
        label="Herschel 400",
        logger=logger,
    )


def match_herschel400_targets(session: Session) -> int:
    """Match Herschel 400 entries to existing targets.

    Returns the number of matches created.
    """
    return match_ngc_catalog(
        session,
        model=Herschel400Entry,
        catalog_name="herschel400",
        ngc_field="ngc_id",
        get_catalog_number=lambda entry: "H400",
        build_metadata=lambda entry: {
            "constellation": entry.constellation,
            "type": entry.object_type,
            "magnitude": entry.magnitude,
        },
        label="Herschel 400",
        logger=logger,
        require_ngc=False,
    )


def match_herschel400_for_target(session: Session, target) -> int:
    """Match Herschel 400 entries to a single target. Returns matches created."""
    return match_ngc_catalog_for_target(
        session,
        target,
        model=Herschel400Entry,
        catalog_name="herschel400",
        ngc_field="ngc_id",
        get_catalog_number=lambda entry: "H400",
        build_metadata=lambda entry: {
            "constellation": entry.constellation,
            "type": entry.object_type,
            "magnitude": entry.magnitude,
        },
    )
