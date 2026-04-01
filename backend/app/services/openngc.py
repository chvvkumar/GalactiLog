"""OpenNGC catalog service — load CSV, lookup, and enrich targets."""
from __future__ import annotations

import csv
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.target import Target

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.models.openngc import OpenNGCEntry

logger = logging.getLogger(__name__)

CSV_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "catalogs" / "openngc.csv"

_NGC_IC_RE = re.compile(r"^(NGC|IC)\s*0*(\d+)([A-Z]?)$", re.IGNORECASE)


def normalize_ngc_name(name: str) -> str:
    """Normalize 'NGC0031' -> 'NGC 31', 'IC0002' -> 'IC 2'."""
    m = _NGC_IC_RE.match(name.strip())
    if m:
        prefix = m.group(1).upper()
        number = m.group(2)
        suffix = m.group(3)
        return f"{prefix} {number}{suffix}"
    return name.strip()


def parse_ra_hms(val: str | None) -> float | None:
    """Parse RA from HH:MM:SS.ss to decimal degrees."""
    if not val or not val.strip():
        return None
    parts = val.strip().split(":")
    if len(parts) != 3:
        return None
    try:
        h, m, s = float(parts[0]), float(parts[1]), float(parts[2])
        return (h + m / 60 + s / 3600) * 15
    except ValueError:
        return None


def parse_dec_dms(val: str | None) -> float | None:
    """Parse Dec from +DD:MM:SS.s to decimal degrees."""
    if not val or not val.strip():
        return None
    text = val.strip()
    sign = -1 if text.startswith("-") else 1
    text = text.lstrip("+-")
    parts = text.split(":")
    if len(parts) != 3:
        return None
    try:
        d, m, s = float(parts[0]), float(parts[1]), float(parts[2])
        return sign * (d + m / 60 + s / 3600)
    except ValueError:
        return None


def _parse_float(val: str | None) -> float | None:
    """Parse a float from a CSV field, returning None for empty/invalid."""
    if not val or not val.strip():
        return None
    try:
        return float(val.strip())
    except ValueError:
        return None


def load_openngc_csv(session: Session) -> int:
    """Load the bundled OpenNGC CSV into the openngc_catalog table.

    Returns the number of rows loaded.
    """
    if not CSV_PATH.exists():
        logger.error("OpenNGC CSV not found at %s", CSV_PATH)
        return 0

    count = 0
    with open(CSV_PATH, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            raw_name = row.get("Name", "").strip()
            if not raw_name:
                continue

            name = normalize_ngc_name(raw_name)
            messier_raw = row.get("M", "").strip()
            messier = f"M {messier_raw}" if messier_raw else None

            entry = {
                "name": name,
                "type": row.get("Type", "").strip() or None,
                "ra": parse_ra_hms(row.get("RA")),
                "dec": parse_dec_dms(row.get("Dec")),
                "major_axis": _parse_float(row.get("MajAx")),
                "minor_axis": _parse_float(row.get("MinAx")),
                "position_angle": _parse_float(row.get("PosAng")),
                "b_mag": _parse_float(row.get("B-Mag")),
                "v_mag": _parse_float(row.get("V-Mag")),
                "surface_brightness": _parse_float(row.get("SurfBr")),
                "common_names": row.get("Common names", "").strip() or None,
                "messier": messier,
            }

            stmt = pg_insert(OpenNGCEntry).values(**entry).on_conflict_do_update(
                index_elements=["name"],
                set_=entry,
            )
            session.execute(stmt)
            count += 1

    session.flush()
    logger.info("Loaded %d OpenNGC entries", count)
    return count


def lookup_openngc(session: Session, catalog_id: str | None) -> OpenNGCEntry | None:
    """Look up an OpenNGC entry by catalog_id (NGC/IC/Messier).

    Tries matching against OpenNGCEntry.name first, then OpenNGCEntry.messier.
    """
    if not catalog_id:
        return None

    normalized = normalize_ngc_name(catalog_id)

    entry = session.execute(
        select(OpenNGCEntry).where(OpenNGCEntry.name == normalized)
    ).scalar_one_or_none()
    if entry:
        return entry

    messier_match = re.match(r"^M\s*(\d+)$", catalog_id.strip(), re.IGNORECASE)
    if messier_match:
        m_name = f"M {messier_match.group(1)}"
        entry = session.execute(
            select(OpenNGCEntry).where(OpenNGCEntry.messier == m_name)
        ).scalar_one_or_none()
        if entry:
            return entry

    return None


def enrich_target_from_openngc(session: Session, target: Target) -> bool:
    """Look up OpenNGC data for a target and populate enrichment fields.

    Returns True if any fields were updated.
    """
    entry = lookup_openngc(session, target.catalog_id)
    if not entry:
        return False

    updated = False
    for target_field, ngc_field in [
        ("size_major", "major_axis"),
        ("size_minor", "minor_axis"),
        ("position_angle", "position_angle"),
        ("v_mag", "v_mag"),
        ("surface_brightness", "surface_brightness"),
    ]:
        ngc_val = getattr(entry, ngc_field)
        if ngc_val is not None and getattr(target, target_field, None) is None:
            setattr(target, target_field, ngc_val)
            updated = True

    return updated
