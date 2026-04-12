"""SAC (Saguaro Astronomy Club) catalog service - load CSV, lookup, and enrich targets."""
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

from app.models.sac_catalog import SACEntry

logger = logging.getLogger(__name__)

CSV_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "catalogs" / "sac.csv"

_NGC_IC_RE = re.compile(r"^(NGC|IC)\s*0*(\d+)([A-Z]?)$", re.IGNORECASE)
_MESSIER_RE = re.compile(r"^M\s*0*(\d+)$", re.IGNORECASE)


def _normalize_sac_name(name: str) -> str:
    """Normalize SAC object names to match GalactiLog conventions.

    'NGC0031' -> 'NGC 31', 'IC0002' -> 'IC 2', 'M031' -> 'M 31'.
    """
    stripped = name.strip()

    m = _NGC_IC_RE.match(stripped)
    if m:
        prefix = m.group(1).upper()
        number = m.group(2)
        suffix = m.group(3)
        return f"{prefix} {number}{suffix}"

    m = _MESSIER_RE.match(stripped)
    if m:
        number = m.group(1)
        return f"M {number}"

    return stripped


def _parse_float(val: str | None) -> float | None:
    """Parse a float from a CSV field, returning None for empty/invalid."""
    if not val or not val.strip():
        return None
    try:
        return float(val.strip())
    except ValueError:
        return None


def load_sac_csv(session: Session) -> int:
    """Load the bundled SAC CSV into the sac_catalog table.

    Returns the number of rows loaded.
    """
    if not CSV_PATH.exists():
        logger.error("SAC CSV not found at %s", CSV_PATH)
        return 0

    count = 0

    # Try utf-8 first, fall back to latin-1
    for encoding in ("utf-8", "latin-1"):
        try:
            f = open(CSV_PATH, "r", encoding=encoding)
            # Read a small chunk to verify encoding works
            f.read(1024)
            f.seek(0)
            break
        except UnicodeDecodeError:
            f.close()
            continue
    else:
        logger.error("SAC CSV could not be decoded with utf-8 or latin-1")
        return 0

    try:
        reader = csv.DictReader(f, delimiter=",")
        for row in reader:
            raw_name = row.get("Object", "").strip()
            if not raw_name:
                continue

            object_name = _normalize_sac_name(raw_name)

            entry = {
                "object_name": object_name,
                "object_type": row.get("Type", "").strip() or None,
                "constellation": row.get("Con", "").strip() or None,
                "magnitude": _parse_float(row.get("Mag")),
                "size": row.get("Size", "").strip() or None,
                "description": row.get("Notes", "").strip() or None,
                "notes": row.get("Other", "").strip() or None,
            }

            stmt = pg_insert(SACEntry).values(**entry).on_conflict_do_update(
                index_elements=["object_name"],
                set_=entry,
            )
            session.execute(stmt)
            count += 1
    finally:
        f.close()

    session.flush()
    logger.info("Loaded %d SAC entries", count)
    return count


def lookup_sac(
    session: Session,
    catalog_id: str | None,
    aliases: list[str] | None = None,
) -> SACEntry | None:
    """Look up a SAC entry by catalog_id or aliases.

    Tries matching catalog_id directly against SACEntry.object_name,
    then the normalized version, then each alias.
    """
    if catalog_id:
        # Direct match
        entry = session.execute(
            select(SACEntry).where(SACEntry.object_name == catalog_id)
        ).scalar_one_or_none()
        if entry:
            return entry

        # Normalized match
        normalized = _normalize_sac_name(catalog_id)
        if normalized != catalog_id:
            entry = session.execute(
                select(SACEntry).where(SACEntry.object_name == normalized)
            ).scalar_one_or_none()
            if entry:
                return entry

    # Try aliases
    if aliases:
        for alias in aliases:
            if not alias:
                continue
            entry = session.execute(
                select(SACEntry).where(SACEntry.object_name == alias.strip())
            ).scalar_one_or_none()
            if entry:
                return entry

            normalized_alias = _normalize_sac_name(alias)
            if normalized_alias != alias.strip():
                entry = session.execute(
                    select(SACEntry).where(SACEntry.object_name == normalized_alias)
                ).scalar_one_or_none()
                if entry:
                    return entry

    return None


def enrich_target_from_sac(session: Session, target: Target) -> bool:
    """Look up SAC data for a target and populate enrichment fields.

    Returns True if any fields were updated.
    """
    entry = lookup_sac(session, target.catalog_id, target.aliases)
    if not entry:
        return False

    updated = False

    if entry.description and getattr(target, "sac_description", None) is None:
        target.sac_description = entry.description
        updated = True

    if entry.notes and getattr(target, "sac_notes", None) is None:
        target.sac_notes = entry.notes
        updated = True

    return updated
