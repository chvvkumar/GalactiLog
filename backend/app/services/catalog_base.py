"""Shared helpers for static catalog services (load CSV + match to targets).

The Abell, Arp, Caldwell, and Herschel 400 services share a near-identical
structure: float/int parsing, a CSV load with a Postgres upsert, and a
match step that resolves targets by NGC/IC identifier. This module captures
the common flow so each service only declares its catalog-specific pieces.
"""
from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.models.target import Target
from app.services.openngc import normalize_ngc_name
from app.services.catalog_membership import upsert_membership


def parse_float(val: str | None) -> float | None:
    if not val or not val.strip():
        return None
    try:
        return float(val.strip())
    except ValueError:
        return None


def parse_int(val: str | None) -> int | None:
    if not val or not val.strip():
        return None
    try:
        return int(val.strip())
    except ValueError:
        return None


def load_catalog_csv(
    session: Session,
    *,
    csv_path: Path,
    model: type,
    key_field: str,
    conflict_index: str,
    build_entry: Callable[[dict], dict | None],
    label: str,
    logger: logging.Logger,
) -> int:
    """Load a bundled catalog CSV into its table with a Postgres upsert.

    ``build_entry`` receives the raw CSV row dict and returns the entry dict to
    upsert, or ``None`` to skip the row. Rows whose ``key_field`` is blank are
    skipped before ``build_entry`` is called. Returns the number of rows loaded.
    """
    if not csv_path.exists():
        logger.error("%s CSV not found at %s", label, csv_path)
        return 0

    count = 0
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            key = row.get(key_field, "").strip()
            if not key:
                continue

            entry = build_entry(row)
            if entry is None:
                continue

            stmt = pg_insert(model).values(**entry).on_conflict_do_update(
                index_elements=[conflict_index],
                set_=entry,
            )
            session.execute(stmt)
            count += 1

    session.flush()
    logger.info("Loaded %d %s entries", count, label)
    return count


def find_target_by_ngc(session: Session, normalized: str) -> Target | None:
    """Resolve a target by normalized NGC/IC name via catalog_id then aliases."""
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

    return target


def target_ngc_identifiers(target) -> set[str]:
    """Return the raw NGC/IC-bearing identifiers a target carries.

    Mirrors what ``find_target_by_ngc`` matches against: an entry whose
    normalized NGC name equals the target's ``catalog_id`` OR appears in its
    ``aliases``. Values are returned raw (un-normalized) so the caller compares
    ``normalize_ngc_name(entry_ngc)`` against this set, matching the bulk
    matcher's exact semantics without scanning the targets table.
    """
    ids: set[str] = set()
    if target.catalog_id:
        ids.add(target.catalog_id)
    for alias in (target.aliases or []):
        if alias:
            ids.add(alias)
    return ids


def match_ngc_catalog_for_target(
    session: Session,
    target,
    *,
    model: type,
    catalog_name: str,
    ngc_field: str,
    get_catalog_number: Callable[[object], str],
    build_metadata: Callable[[object], dict],
) -> int:
    """Per-target inverse of ``match_ngc_catalog`` (Caldwell, Herschel 400).

    Iterates the small static catalog table (not the targets table) and upserts
    a membership for every entry whose normalized NGC id is one of the target's
    identifiers. Idempotent via ``upsert_membership``. Returns matches created.
    """
    identifiers = target_ngc_identifiers(target)
    if not identifiers:
        return 0

    entries = session.execute(select(model)).scalars().all()
    matched = 0
    for entry in entries:
        ngc_value = getattr(entry, ngc_field)
        if not ngc_value:
            continue
        if normalize_ngc_name(ngc_value) in identifiers:
            upsert_membership(
                session,
                target_id=target.id,
                catalog_name=catalog_name,
                catalog_number=get_catalog_number(entry),
                metadata=build_metadata(entry),
            )
            matched += 1

    session.flush()
    return matched


def match_ngc_catalog(
    session: Session,
    *,
    model: type,
    catalog_name: str,
    ngc_field: str,
    get_catalog_number: Callable[[object], str],
    build_metadata: Callable[[object], dict],
    label: str,
    logger: logging.Logger,
    require_ngc: bool = True,
) -> int:
    """Match a single-NGC-id catalog (Caldwell, Herschel 400) to targets.

    For each entry, the value of ``ngc_field`` is normalized and resolved to a
    target by catalog_id or aliases. ``get_catalog_number`` and
    ``build_metadata`` produce the membership's catalog number and metadata.
    When ``require_ngc`` is True, entries with an empty ``ngc_field`` are
    skipped. Returns the number of matches created.
    """
    entries = session.execute(select(model)).scalars().all()
    matched = 0

    for entry in entries:
        ngc_value = getattr(entry, ngc_field)
        if require_ngc and not ngc_value:
            continue

        normalized = normalize_ngc_name(ngc_value)
        target = find_target_by_ngc(session, normalized)

        if target:
            upsert_membership(
                session,
                target_id=target.id,
                catalog_name=catalog_name,
                catalog_number=get_catalog_number(entry),
                metadata=build_metadata(entry),
            )
            matched += 1

    session.flush()
    logger.info("Matched %d %s targets", matched, label)
    return matched
