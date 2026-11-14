"""Centralized target resolution - the single authority for FITS OBJECT name → Target.

Usage:
    target_id = resolve_target(object_name, db_session, redis=redis_client)
"""

import logging

import httpx
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Target
from app.services import catalog_cache as cc
from app.services.upstream import error_details, human_error
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


def _unique_alias_match(alias: str, session: Session) -> Target | None:
    """The one live target carrying ``alias``, or None.

    Aliases are not unique across targets: an identity match appends the
    incoming name to the target it matched, so a name that once created an
    unresolved standalone target can later also land on the real one. Two
    hits is no match, not an error - scalar_one_or_none raised
    MultipleResultsFound here and every frame naming the object failed to
    ingest. The exact primary-name tier below decides instead, and duplicate
    detection is what merges the pair.
    """
    rows = session.execute(
        select(Target).where(
            Target.merged_into_id.is_(None),
            Target.aliases.any(alias),
        )
    ).scalars().all()
    if len(rows) == 1:
        return rows[0]
    if len(rows) > 1:
        logger.warning(
            "Alias %r is carried by %d live targets (%s); ignoring it for lookup",
            alias, len(rows), ", ".join(t.primary_name for t in rows[:5]),
        )
    return None


def find_target_by_name(object_name: str, session: Session) -> Target | None:
    """Search for an existing target by normalized name in aliases, then primary_name.

    This is the single DB lookup function - all target matching goes through here.
    Also tries panel-stripped version (e.g. "M31 Panel 2" → "M31").
    """
    normalized = normalize_object_name(object_name)

    # Search aliases array (GIN-indexed, fast)
    target = _unique_alias_match(normalized, session)
    if target:
        return target

    # Try with panel suffix stripped
    stripped = _PANEL_RE.sub("", normalized).strip()
    if stripped != normalized:
        target = _unique_alias_match(stripped, session)
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


def _dispatch_enrich_new_target(target_id: str) -> None:
    """Queue the async follow-up enrichment for a newly created target (AUD-006).

    Best-effort: enrichment is a non-critical follow-up (constellation fallback,
    catalog memberships, Gaia/HyperLEDA), so a broker hiccup must never fail
    ingest. The task is idempotent and the same gaps are also backfilled by the
    v13 data migration, so a dropped dispatch self-heals.
    """
    try:
        from app.worker.tasks import enrich_new_target_task
        enrich_new_target_task.delay(target_id)
    except Exception:  # noqa: BLE001
        logger.debug(
            "Failed to dispatch enrich_new_target_task for %s", target_id,
            exc_info=True,
        )


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
            # Best-effort: the target row is already committed, and a VizieR
            # outage must not fail the ingest of the file that named it.
            # (OpenNGC and SAC are local tables, no network.)
            try:
                enrich_target_from_vizier(session, target)
                session.commit()
            except (cc.NonTransientError, httpx.HTTPError) as exc:
                logger.warning(
                    "Size lookup for new target %s skipped, it can be filled in later: %s",
                    target.primary_name, human_error(exc), exc_info=True,
                )
        enrich_target_from_sac(session, target)
        session.commit()
        new_id = str(target.id)
        # Follow-up enrichment (Gaia/HyperLEDA/memberships/constellation) runs
        # async so ingest is not blocked on external network latency (AUD-006).
        _dispatch_enrich_new_target(new_id)
        return new_id
    except IntegrityError:
        session.rollback()
        # Race: another worker inserted this identity/name. Re-query by the
        # FINAL post-enrichment primary_name, then by catalog identity.
        cat_norm = normalize_catalog_id(simbad_result.get("catalog_id"))
        existing = session.execute(
            select(Target).where(
                Target.merged_into_id.is_(None),
                Target.primary_name == target.primary_name,
            )
        ).scalar_one_or_none()
        if existing is None and cat_norm:
            existing = session.execute(
                select(Target).where(
                    Target.merged_into_id.is_(None),
                    Target.catalog_id_normalized == cat_norm,
                )
            ).scalar_one_or_none()
        return str(existing.id) if existing else None


def lookup_catalogs(
    object_name: str, session: Session,
) -> tuple[dict | None, bool]:
    """Resolve a name via SIMBAD, then Sesame. Returns (result, confirmed_no_match).

    The single catalog lookup for both the OBJECT path (resolve_target) and
    the filename path (filename_resolver). A lookup returning None is
    ambiguous: the service may have answered "no such object", or it may be
    down (catalog_cache returns None for an outage and stores nothing).
    confirmed_no_match is True only when every service left a negative
    catalog_cache row for this name, which only a real answer does. Callers
    must not record a negative unless it is True.

    A service that raises (NonTransientError for a 4xx, or a raw httpx error)
    is logged and skipped, so one service being down neither fails the caller
    nor stops the next service from being asked.
    """
    normalized = normalize_object_name(object_name)
    confirmed = True
    for source, lookup in (
        ("simbad", resolve_target_name_cached),
        ("sesame", resolve_sesame_cached),
    ):
        try:
            result = lookup(object_name, session)
        except (cc.NonTransientError, httpx.HTTPError) as exc:
            logger.warning(
                "Catalog lookup for %r skipped, the name stays unresolved for now: %s (%s)",
                object_name, human_error(exc), error_details(exc)["error_chain"],
            )
            confirmed = False
            continue
        session.commit()  # Persist cache entry
        if result is not None:
            return result, False
        # ponytail: checks the name's own key only. A name SIMBAD rejected
        # under its mapped key reads as unconfirmed, costing a few cached DB
        # reads per file. Check the mapped key too if that shows up in scans.
        if cc.get_cached(session, source, normalized) is not cc.NEGATIVE:
            confirmed = False
    # While a source is marked unavailable get_or_fetch answers None without
    # asking it, so an older negative row proves nothing about this lookup.
    if cc.outage("simbad") or cc.outage("sesame"):
        confirmed = False
    return None, confirmed


def resolve_target(
    object_name: str, session: Session, *, redis=None,
) -> str | None:
    """Resolve a FITS OBJECT name to a target ID. Single entry point.

    Pipeline:
    1. Check Redis negative cache (fast reject for unresolvable names)
    2. Search existing targets by alias/primary_name
    3. Query SIMBAD (with persistent DB cache)
    4. Create target if SIMBAD resolves
    5. Add to negative cache if the catalogs answered and found nothing.
       An outage (no answer) is never negative-cached.

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

    # Resolve via SIMBAD, falling back to SESAME (NED + VizieR). Both use the
    # persistent DB cache.
    result, confirmed_no_match = lookup_catalogs(object_name, session)

    if result is None:
        # Only names the catalogs answered "no match" for are negative-cached.
        # After an outage the next file must ask again.
        if redis and confirmed_no_match:
            redis.sadd(NEGATIVE_CACHE_KEY, normalized)
            redis.expire(NEGATIVE_CACHE_KEY, NEGATIVE_CACHE_TTL)
        return None

    # The name resolved to a (possibly catalog) identity. Re-check via the shared
    # identity matcher in case a concurrent worker created the target while we
    # waited on SIMBAD. A resolved identity is NEVER negative-cached below, so a
    # single create-collision cannot cascade NULLs across the scan batch.
    existing = match_target_by_identity(result, object_name, session)
    if existing is not None:
        session.commit()
        return str(existing.id)

    return _create_target(result, normalized, session)
