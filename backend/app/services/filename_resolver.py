"""Filename resolution pipeline -- match extracted target names to existing DB targets.

Takes an extracted target name (from filename parsing) and tries to match it
to an existing target using a cascade of strategies.
"""

import logging
import re
from typing import Any

from sqlalchemy import text as sa_text
from sqlalchemy.orm import Session

from app.services.target_resolver import find_target_by_name
from app.services.simbad import (
    COMMON_NAME_MAP,
    normalize_object_name,
    resolve_target_name_cached,
)
from app.services.sesame import resolve_sesame_cached

logger = logging.getLogger(__name__)

_SQUISHED_RE = re.compile(r"^([A-Za-z]+)(\d+.*)$")


def resolve_filename_candidate(
    extracted_name: str,
    session: Session,
    *,
    redis=None,
) -> dict[str, Any]:
    """Resolve an extracted target name to an existing DB target.

    Tries strategies in order: direct alias, common name map, space insertion,
    SIMBAD/SESAME, trigram similarity. Returns on first match.

    Returns:
        Dict with extracted_name, suggested_target_id, suggested_target_name,
        method, and confidence.
    """
    def _result(target=None, method="none", confidence=0.0, target_name=None):
        return {
            "extracted_name": extracted_name,
            "suggested_target_id": str(target.id) if target else None,
            "suggested_target_name": (
                target.primary_name if target else target_name
            ),
            "method": method,
            "confidence": confidence,
        }

    # 1. Direct DB lookup (alias match)
    target = find_target_by_name(extracted_name, session)
    if target:
        return _result(target, method="alias_match", confidence=1.0)

    # 2. Common name map
    mapped = COMMON_NAME_MAP.get(extracted_name.lower())
    if mapped:
        target = find_target_by_name(mapped, session)
        if target:
            return _result(target, method="common_name", confidence=0.95)

    # 3. Space inserter -- letters immediately followed by digits
    m = _SQUISHED_RE.match(extracted_name.strip())
    if m:
        spaced = f"{m.group(1)} {m.group(2)}"
        if spaced != extracted_name:
            target = find_target_by_name(spaced, session)
            if target:
                return _result(target, method="space_insert", confidence=0.9)

    # 4. SIMBAD / SESAME
    simbad_result = resolve_target_name_cached(extracted_name, session)
    if not simbad_result:
        simbad_result = resolve_sesame_cached(extracted_name, session)
    session.commit()

    if simbad_result:
        catalog_id = simbad_result.get("catalog_id")
        simbad_aliases = [
            normalize_object_name(a) for a in simbad_result.get("aliases", [])
        ]
        if catalog_id:
            simbad_aliases.append(normalize_object_name(catalog_id))

        if simbad_aliases:
            alias_match_query = sa_text("""
                SELECT t.id, t.primary_name
                FROM targets t
                WHERE t.merged_into_id IS NULL
                  AND (
                    upper(t.catalog_id) = ANY(:aliases)
                    OR EXISTS (
                      SELECT 1 FROM unnest(t.aliases) a
                      WHERE upper(a) = ANY(:aliases)
                    )
                  )
                LIMIT 1
            """)
            row = session.execute(
                alias_match_query, {"aliases": simbad_aliases}
            ).first()
            if row:
                target_id, target_name = row
                return {
                    "extracted_name": extracted_name,
                    "suggested_target_id": str(target_id),
                    "suggested_target_name": target_name,
                    "method": "simbad",
                    "confidence": 1.0,
                }

        # SIMBAD resolved but no existing target matched
        primary_name = simbad_result.get("primary_name") or simbad_result.get(
            "catalog_id"
        )
        return _result(
            method="simbad_new",
            confidence=0.9,
            target_name=primary_name,
        )

    # 5. Trigram similarity (pg_trgm)
    try:
        trgm_query = sa_text("""
            SELECT t.id, t.primary_name,
                   GREATEST(
                       word_similarity(:name, t.primary_name),
                       (SELECT COALESCE(MAX(word_similarity(:name, a)), 0)
                        FROM unnest(t.aliases) a)
                   ) AS score
            FROM targets t
            WHERE t.merged_into_id IS NULL
              AND (
                  word_similarity(:name, t.primary_name) >= :threshold
                  OR EXISTS (
                      SELECT 1 FROM unnest(t.aliases) a
                      WHERE word_similarity(:name, a) >= :threshold
                  )
              )
            ORDER BY score DESC
            LIMIT 1
        """)
        row = session.execute(
            trgm_query,
            {"name": extracted_name, "threshold": 0.4},
        ).first()
        if row:
            target_id, target_name, score = row
            return {
                "extracted_name": extracted_name,
                "suggested_target_id": str(target_id),
                "suggested_target_name": target_name,
                "method": "trigram",
                "confidence": float(score),
            }
    except Exception:
        logger.debug(
            "Trigram similarity unavailable for %r (pg_trgm not installed?)",
            extracted_name,
        )

    # 6. No match
    return _result()
