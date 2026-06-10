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
    normalize_catalog_id,
    resolve_target_name_cached,
    _PANEL_RE,
)
from app.services.sesame import resolve_sesame_cached
from app.services.openngc import enrich_target_from_openngc
from app.services.vizier import enrich_target_from_vizier
from app.services.sac import enrich_target_from_sac

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


def match_target_by_identity(
    resolved: dict, object_name: str, session: Session,
) -> "Target | None":
    """Find an existing target for a resolved identity, identity-first.

    Order:
      1. Normalized catalog identity (catalog_id_normalized) -- stable, primary.
      2. Name fallback via find_target_by_name (aliases / primary_name) for
         non-catalog objects or when identity is not yet populated.

    On a match, the normalized incoming OBJECT string is recorded as an alias so
    future direct lookups hit and the linkage is visible. Returns the Target or
    None. Never creates.
    """
    cat_norm = normalize_catalog_id(resolved.get("catalog_id"))
    target: "Target | None" = None

    if cat_norm:
        target = session.execute(
            select(Target).where(
                Target.merged_into_id.is_(None),
                Target.catalog_id_normalized == cat_norm,
            )
        ).scalar_one_or_none()

    if target is None:
        target = find_target_by_name(object_name, session)

    if target is not None:
        incoming = _PANEL_RE.sub("", normalize_object_name(object_name)).strip()
        if incoming and incoming not in [a.upper() for a in (target.aliases or [])]:
            # Reassign to trigger ORM change tracking on the ARRAY column.
            target.aliases = list(target.aliases or []) + [incoming]

    return target


def _create_target(
    simbad_result: dict, normalized_name: str, session: Session,
) -> str | None:
    """Enrich the resolved identity, match an existing target, else create one.

    Order (eliminates the insert-then-rename-then-collide class):
      1. Enrich the in-memory identity from OpenNGC so primary_name is final.
      2. Match an existing target by catalog identity (then name fallback).
         If found, link to it (and record the incoming OBJECT as an alias).
      3. Otherwise insert. The IntegrityError net re-queries by the FINAL
         post-enrichment primary_name AND by catalog identity, never returning
         None for a name that resolved.
    """
    aliases = simbad_result.get("aliases", [])
    # Strip panel suffixes from the FITS-derived lookup name before adding as alias
    clean_name = _PANEL_RE.sub("", normalized_name).strip()
    if clean_name and clean_name not in [a.upper() for a in aliases]:
        aliases.append(clean_name)

    target = Target(
        primary_name=simbad_result["primary_name"],
        catalog_id=simbad_result.get("catalog_id"),
        catalog_id_normalized=normalize_catalog_id(simbad_result.get("catalog_id")),
        common_name=simbad_result.get("common_name"),
        aliases=aliases,
        ra=simbad_result.get("ra"),
        dec=simbad_result.get("dec"),
        object_type=simbad_result.get("object_type"),
    )

    # Enrich the detached instance so primary_name / catalog_id are final BEFORE
    # any match or insert. enrich_target_from_openngc reads target.catalog_id and
    # may rewrite primary_name; it does not change catalog_id, so the normalized
    # identity computed above stays correct.
    enrich_target_from_openngc(session, target)

    # Match by final identity. If an existing target carries this identity, link
    # to it rather than inserting a colliding row.
    existing = match_target_by_identity(simbad_result, normalized_name, session)
    if existing is not None:
        session.commit()
        return str(existing.id)

    try:
        session.add(target)
        session.flush()
        session.commit()
        if target.size_major is None:
            enrich_target_from_vizier(session, target)
            session.commit()
        enrich_target_from_sac(session, target)
        session.commit()
        return str(target.id)
    except IntegrityError:
        session.rollback()
        # Race: another worker inserted this identity/name. Re-query by the
        # FINAL post-enrichment primary_name, then by catalog identity.
        cat_norm = normalize_catalog_id(simbad_result.get("catalog_id"))
        existing = session.execute(
            select(Target).where(Target.primary_name == target.primary_name)
        ).scalar_one_or_none()
        if existing is None and cat_norm:
            existing = session.execute(
                select(Target).where(
                    Target.merged_into_id.is_(None),
                    Target.catalog_id_normalized == cat_norm,
                )
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
