"""Backfill catalog_id, common_name, and curated aliases for all targets.

Re-queries SIMBAD TAP for clean aliases, applies catalog priority
hierarchy, and reconstructs primary_name as "CATALOG_ID - Common Name".
Also backfills resolved_target_id for unresolved images.
"""

import asyncio
import logging

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.models import Image, Target
from app.services.simbad import (
    resolve_target_name,
    normalize_object_name,
    _fetch_tap_aliases,
    _normalize_ws,
    curate_aliases,
    extract_catalog_id,
    extract_common_name,
    build_primary_name,
)

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)


async def backfill_existing_targets():
    """Re-process all existing targets: fetch clean aliases, set catalog_id/common_name."""
    engine = create_async_engine(settings.database_url)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        result = await session.execute(select(Target).where(Target.merged_into_id.is_(None)))
        targets = result.scalars().all()
        log.info("Processing %d targets", len(targets))

        for target in targets:
            # Get FITS OBJECT names linked to this target
            fits_result = await session.execute(
                text("""
                    SELECT DISTINCT raw_headers->>'OBJECT' AS obj
                    FROM images
                    WHERE resolved_target_id = :tid
                      AND raw_headers->>'OBJECT' IS NOT NULL
                """),
                {"tid": target.id},
            )
            fits_names = [row[0] for row in fits_result.all() if row[0]]

            # Extract a clean SIMBAD-compatible name for TAP lookup.
            # catalog_id may contain mangled values like "IC 1805 - Heart Nebula Panel 1"
            # from a previous backfill run — strip everything after " - " to get "IC 1805".
            raw_lookup = target.catalog_id or target.primary_name
            lookup_name = raw_lookup.split(" - ")[0].strip()
            raw_aliases = await _fetch_tap_aliases(lookup_name)

            if not raw_aliases:
                # TAP failed — try with normalized name
                raw_aliases = await _fetch_tap_aliases(_normalize_ws(lookup_name))
            if not raw_aliases and lookup_name != raw_lookup:
                # Try the full value as last resort
                raw_aliases = await _fetch_tap_aliases(raw_lookup)

            if raw_aliases:
                catalog_id = extract_catalog_id(raw_aliases, lookup_name)
                common_name = extract_common_name(raw_aliases, fits_names=fits_names)
                curated = curate_aliases(raw_aliases, fits_names=fits_names)
            else:
                # SIMBAD unavailable — do best-effort from existing data
                log.warning("  No TAP data for %s — using existing aliases", lookup_name)
                catalog_id = _normalize_ws(lookup_name)
                common_name = extract_common_name([], fits_names=fits_names)
                curated = [normalize_object_name(n) for n in fits_names]

            primary_name = build_primary_name(catalog_id, common_name)

            # Ensure FITS names are in aliases
            for name in fits_names:
                normalized = normalize_object_name(name)
                if normalized not in [a.upper() for a in curated]:
                    curated.append(normalized)

            target.primary_name = primary_name
            target.catalog_id = catalog_id
            target.common_name = common_name
            target.aliases = curated

            log.info("  %s -> %s (catalog=%s, common=%s, %d aliases)",
                     lookup_name, primary_name, catalog_id, common_name, len(curated))

            await asyncio.sleep(0.5)  # Rate limit

        await session.commit()
        log.info("Done! Updated %d targets", len(targets))

    await engine.dispose()


async def backfill_unresolved():
    """Resolve unresolved images (same as original backfill)."""
    engine = create_async_engine(settings.database_url)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        result = await session.execute(
            text("""
                SELECT raw_headers->>'OBJECT' AS obj, COUNT(*) AS cnt
                FROM images
                WHERE resolved_target_id IS NULL
                  AND raw_headers->>'OBJECT' IS NOT NULL
                  AND raw_headers->>'OBJECT' != ''
                GROUP BY raw_headers->>'OBJECT'
                ORDER BY cnt DESC
            """)
        )
        unresolved = result.all()
        log.info("Found %d unique unresolved object names", len(unresolved))

        resolved = 0
        failed = []

        for obj_name, img_count in unresolved:
            normalized = normalize_object_name(obj_name)

            # Check existing target by alias
            existing = await session.execute(
                select(Target).where(Target.aliases.any(normalized))
            )
            target = existing.scalar_one_or_none()

            if not target:
                # Query SIMBAD
                simbad_result = await resolve_target_name(obj_name)

                if simbad_result:
                    # Check if this target already exists by catalog_id
                    existing = await session.execute(
                        select(Target).where(Target.catalog_id == simbad_result.get("catalog_id"))
                    )
                    target = existing.scalar_one_or_none()

                    if not target:
                        target = Target(
                            primary_name=simbad_result["primary_name"],
                            catalog_id=simbad_result.get("catalog_id"),
                            common_name=simbad_result.get("common_name"),
                            aliases=simbad_result.get("aliases", []),
                            ra=simbad_result.get("ra"),
                            dec=simbad_result.get("dec"),
                            object_type=simbad_result.get("object_type"),
                        )
                        session.add(target)
                        await session.flush()
                    else:
                        # Add alias if missing
                        if normalized not in [a.upper() for a in target.aliases]:
                            target.aliases = [*target.aliases, normalized]
                            await session.flush()

                    await asyncio.sleep(0.5)
                else:
                    failed.append(obj_name)
                    log.info("  FAILED: %s (%d images)", obj_name, img_count)
                    await asyncio.sleep(0.5)
                    continue

            # Bulk-update images
            up = await session.execute(
                text("""
                    UPDATE images
                    SET resolved_target_id = :target_id
                    WHERE resolved_target_id IS NULL
                      AND raw_headers->>'OBJECT' = :obj_name
                """),
                {"target_id": target.id, "obj_name": obj_name},
            )
            resolved += 1
            log.info("  OK: %s -> %s (%d images)", obj_name, target.primary_name, up.rowcount)

        await session.commit()
        log.info("Resolved: %d, Failed: %d", resolved, len(failed))
        if failed:
            log.info("Failed names: %s", failed)

    await engine.dispose()


async def main():
    log.info("=== Phase 1: Backfill existing targets ===")
    await backfill_existing_targets()
    log.info("")
    log.info("=== Phase 2: Resolve unresolved images ===")
    await backfill_unresolved()


if __name__ == "__main__":
    asyncio.run(main())
