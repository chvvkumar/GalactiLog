"""Centralized target resolution - the single authority for FITS OBJECT name → Target.

Usage:
    target_id = resolve_target(object_name, db_session, redis=redis_client)
"""

import logging

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Target
from app.services.simbad import (
    normalize_object_name,
    resolve_target_name_cached,
    _PANEL_RE,
)
from app.services.sesame import resolve_sesame_cached
from app.services.openngc import enrich_target_from_openngc
from app.services.vizier import enrich_target_from_vizier

logger = logging.getLogger(__name__)

NEGATIVE_CACHE_KEY = "target_resolver:negative"
NEGATIVE_CACHE_TTL = 300  # 5 minutes

# SQL expression equivalent to normalize_object_name(x, upper=True).
# Use in bulk UPDATE/SELECT where per-row Python calls aren't practical.
NORMALIZE_SQL = "UPPER(REGEXP_REPLACE(TRIM({col}), '\\s+', ' ', 'g'))"


def normalize_sql_expr(column_expr: str) -> str:
    """Return SQL expression equivalent to normalize_object_name(column, upper=True)."""
    return NORMALIZE_SQL.format(col=column_expr)


def find_target_by_name(object_name: str, session: Session) -> Target | None:
    """Search for an existing target by normalized name in aliases, then primary_name.

    This is the single DB lookup function - all target matching goes through here.
    Also tries panel-stripped version (e.g. "M31 Panel 2" → "M31").
    """
    normalized = normalize_object_name(object_name)

    # Search aliases array (GIN-indexed, fast)
    target = session.execute(
        select(Target).where(
            Target.merged_into_id.is_(None),
            Target.aliases.any(normalized),
        )
    ).scalar_one_or_none()
    if target:
        return target

    # Try with panel suffix stripped
    stripped = _PANEL_RE.sub("", normalized).strip()
    if stripped != normalized:
        target = session.execute(
            select(Target).where(
                Target.merged_into_id.is_(None),
                Target.aliases.any(stripped),
            )
        ).scalar_one_or_none()
        if target:
            return target

    # Fallback: normalized case-preserving match on primary_name
    target = session.execute(
        select(Target).where(
            Target.merged_into_id.is_(None),
            Target.primary_name == normalize_object_name(object_name, upper=False),
        )
    ).scalar_one_or_none()
    return target


def _create_target(
    simbad_result: dict, normalized_name: str, session: Session,
) -> str | None:
    """Create a new Target from a SIMBAD result. Handles race conditions."""
    aliases = simbad_result.get("aliases", [])
    # Strip panel suffixes from the FITS-derived lookup name before adding as alias
    clean_name = _PANEL_RE.sub("", normalized_name).strip()
    if clean_name and clean_name not in [a.upper() for a in aliases]:
        aliases.append(clean_name)

    target = Target(
        primary_name=simbad_result["primary_name"],
        catalog_id=simbad_result.get("catalog_id"),
        common_name=simbad_result.get("common_name"),
        aliases=aliases,
        ra=simbad_result.get("ra"),
        dec=simbad_result.get("dec"),
        object_type=simbad_result.get("object_type"),
    )
    try:
        session.add(target)
        session.flush()
        enrich_target_from_openngc(session, target)
        if target.size_major is None:
            enrich_target_from_vizier(session, target)
        session.commit()
        return str(target.id)
    except IntegrityError:
        session.rollback()
        # Another worker inserted this target - re-query
        existing = session.execute(
            select(Target).where(Target.primary_name == simbad_result["primary_name"])
        ).scalar_one_or_none()
        return str(existing.id) if existing else None


def resolve_target(
    object_name: str, session: Session, *, redis=None,
) -> str | None:
    """Resolve a FITS OBJECT name to a target ID. Single entry point.

    Pipeline:
    1. Check Redis negative cache (fast reject for unresolvable names)
    2. Search existing targets by alias/primary_name
    3. Query SIMBAD (with persistent DB cache)
    4. Create target if SIMBAD resolves
    5. Add to negative cache if SIMBAD fails

    Returns target.id as string, or None if unresolvable.
    """
    normalized = normalize_object_name(object_name)

    # Fast reject from Redis negative cache
    if redis and redis.sismember(NEGATIVE_CACHE_KEY, normalized):
        return None

    # Search existing targets
    existing = find_target_by_name(object_name, session)
    if existing:
        return str(existing.id)

    # Resolve via SIMBAD (uses persistent DB cache)
    result = resolve_target_name_cached(object_name, session)
    session.commit()  # Persist cache entry

    # Fallback: try SESAME (queries NED + VizieR) when SIMBAD fails
    if result is None:
        result = resolve_sesame_cached(object_name, session)
        session.commit()

    if result is None:
        if redis:
            redis.sadd(NEGATIVE_CACHE_KEY, normalized)
            redis.expire(NEGATIVE_CACHE_KEY, NEGATIVE_CACHE_TTL)
        return None

    # Check again after SIMBAD - another worker may have created this target
    # while we were waiting on SIMBAD
    existing = find_target_by_name(result["primary_name"], session)
    if existing:
        return str(existing.id)

    return _create_target(result, normalized, session)
