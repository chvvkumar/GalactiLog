"""Target duplicate/identity detection: detect_duplicate_targets,
backfill_catalog_identity."""
import logging
import time

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.target_resolver import resolve_target, match_target_by_identity
from app.services.simbad import (
    normalize_object_name, resolve_target_name_cached,
)
from app.services.simbad_repair import repair_corrupted_simbad_cache
from app.services.mosaic_detection import recompute_panel_membership_for_images_sync
from app.worker.celery_app import celery_app
from app.worker.tasks_common import _sync_engine, _redis
from app.services.scan_state import (
    clear_cancel_sync, is_cancel_requested_sync,
    set_rebuild_running_sync, set_rebuild_progress_sync, set_rebuild_complete_sync,
    set_rebuild_cancelled_sync,
)

logger = logging.getLogger(__name__)


@celery_app.task(name="detect_duplicate_targets")
def detect_duplicate_targets(parent_activity_id: int | None = None):
    """Detect potential duplicate targets by comparing unresolved names against resolved targets.

    Strategy:
    1. Try SIMBAD resolution to find the canonical catalog ID, then match against existing targets.
    2. Fall back to trigram similarity if SIMBAD doesn't resolve or match.
    """
    from sqlalchemy import text as sa_text, select as sa_select, func as sa_func
    from app.models.target import Target
    from app.models.image import Image
    from app.models.merge_candidate import MergeCandidate
    from app.services.simbad import resolve_target_name_cached, normalize_object_name

    with Session(_sync_engine) as db:
        # Find distinct unresolved OBJECT names with image counts
        unresolved_query = (
            sa_select(
                Image.raw_headers["OBJECT"].astext.label("object_name"),
                sa_func.count(Image.id).label("img_count"),
            )
            .where(
                Image.resolved_target_id.is_(None),
                Image.image_type == "LIGHT",
                Image.raw_headers["OBJECT"].astext.isnot(None),
            )
            .group_by(Image.raw_headers["OBJECT"].astext)
        )
        unresolved = db.execute(unresolved_query).all()

        # Get existing candidates to avoid duplicates. Include "dismissed" so
        # suggestions the user explicitly rejected don't come back on re-runs
        # triggered by scans, manual matches, or smart rebuilds.
        existing = db.execute(
            sa_select(MergeCandidate.source_name).where(
                MergeCandidate.status.in_(["pending", "accepted", "dismissed"])
            )
        )
        existing_names = {row[0] for row in existing.all()}

        candidates_found = 0
        orphan_count = 0

        for obj_name, img_count in unresolved:
            if not obj_name or obj_name in existing_names:
                continue

            matched = False

            # Strategy 1: SIMBAD resolution - resolve the name and match against existing targets
            simbad_result = resolve_target_name_cached(obj_name, db)
            if simbad_result:
                catalog_id = simbad_result.get("catalog_id")
                simbad_aliases = [normalize_object_name(a) for a in simbad_result.get("aliases", [])]
                if catalog_id:
                    simbad_aliases.append(normalize_object_name(catalog_id))

                # Check if any existing target shares the same catalog_id or aliases
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
                    result = db.execute(alias_match_query, {"aliases": simbad_aliases}).first()
                    if result:
                        target_id, target_name = result
                        db.add(MergeCandidate(
                            source_name=obj_name,
                            source_image_count=img_count,
                            suggested_target_id=target_id,
                            similarity_score=1.0,
                            method="simbad",
                            reason_text=f'SIMBAD resolves "{obj_name}" to the same object as "{target_name}"',
                        ))
                        candidates_found += 1
                        matched = True

            if matched:
                continue

            # SIMBAD resolved the name but no existing target matched - create the target
            # and resolve images directly instead of suggesting a wrong trigram match.
            if simbad_result:
                logger.info("detect_duplicates: '%s' resolved by SIMBAD to '%s' - creating target and resolving images",
                            obj_name, simbad_result.get("primary_name"))
                target_id = resolve_target(obj_name, db, redis=_redis)
                if target_id:
                    from sqlalchemy import update as sa_update
                    resolved_ids = db.execute(
                        sa_update(Image)
                        .where(
                            Image.raw_headers["OBJECT"].astext == obj_name,
                            Image.resolved_target_id.is_(None),
                        )
                        .values(resolved_target_id=target_id)
                        .returning(Image.id)
                    ).scalars().all()
                    recompute_panel_membership_for_images_sync(db, resolved_ids)
                    db.commit()
                    logger.info("detect_duplicates: resolved %d images for '%s' to target %s",
                                img_count, obj_name, target_id)
                continue

            # Strategy 2: Trigram similarity fallback (only for names SIMBAD can't resolve)
            trgm_query = sa_text("""
                SELECT t.id, t.primary_name,
                       GREATEST(
                           similarity(t.primary_name, :name),
                           COALESCE((SELECT MAX(similarity(a, :name)) FROM unnest(t.aliases) a), 0)
                       ) AS score
                FROM targets t
                WHERE t.merged_into_id IS NULL
                  AND GREATEST(
                      similarity(t.primary_name, :name),
                      COALESCE((SELECT MAX(similarity(a, :name)) FROM unnest(t.aliases) a), 0)
                  ) > 0.4
                ORDER BY score DESC
                LIMIT 1
            """)
            result = db.execute(trgm_query, {"name": obj_name}).first()

            if result:
                target_id, target_name, score = result
                db.add(MergeCandidate(
                    source_name=obj_name,
                    source_image_count=img_count,
                    suggested_target_id=target_id,
                    similarity_score=float(score),
                    method="trigram",
                    reason_text=f'Name is {int(float(score) * 100)}% similar to "{target_name}"',
                ))
                candidates_found += 1
            else:
                db.add(MergeCandidate(
                    source_name=obj_name,
                    source_image_count=img_count,
                    suggested_target_id=None,
                    similarity_score=0.0,
                    method="orphan",
                    status="pending",
                    reason_text="No match found in SIMBAD or existing targets",
                ))
                candidates_found += 1
                orphan_count += 1

        db.commit()

        # --- Pass 2: Detect active targets sharing the same normalized name or overlapping aliases ---
        # Re-fetch existing candidate names after the commit above so we skip
        # anything just created in Pass 1.
        existing_pass2 = db.execute(
            sa_select(MergeCandidate.source_name).where(
                MergeCandidate.status.in_(["pending", "accepted", "dismissed"])
            )
        )
        existing_names_p2 = {row[0] for row in existing_pass2.all()}

        # Load all active (non-merged) targets with their image counts.
        # Use a LEFT JOIN to a grouped aggregate instead of a correlated subquery
        # so the planner can execute a single hash-join rather than N index scans.
        active_targets_query = sa_text("""
            SELECT t.id, t.primary_name, t.aliases,
                   COALESCE(ic.img_count, 0) AS img_count
            FROM targets t
            LEFT JOIN (
                SELECT resolved_target_id, COUNT(*) AS img_count
                FROM images
                GROUP BY resolved_target_id
            ) ic ON ic.resolved_target_id = t.id
            WHERE t.merged_into_id IS NULL
        """)
        active_rows = db.execute(active_targets_query).all()

        # Build a mapping from each normalized name to the list of targets that use it
        # (either as primary_name or as an alias)
        from collections import defaultdict
        name_to_targets: dict[str, list[tuple]] = defaultdict(list)
        for row in active_rows:
            tid, pname, aliases, img_count = row
            norm_primary = normalize_object_name(pname)
            name_to_targets[norm_primary].append((tid, pname, img_count))
            if aliases:
                for alias in aliases:
                    norm_alias = normalize_object_name(alias)
                    name_to_targets[norm_alias].append((tid, pname, img_count))

        # Find groups of targets that share any normalized name.
        # Use union-find to merge overlapping groups.

        # Map target id to its info
        target_info = {row[0]: (row[1], row[3]) for row in active_rows}  # id -> (primary_name, img_count)

        # For each normalized name that maps to multiple distinct targets, union them
        visited_targets: dict = {}  # target_id -> group leader id

        def find_leader(tid):
            while visited_targets.get(tid, tid) != tid:
                visited_targets[tid] = visited_targets.get(visited_targets[tid], visited_targets[tid])
                tid = visited_targets[tid]
            return tid

        def union(tid1, tid2):
            l1 = find_leader(tid1)
            l2 = find_leader(tid2)
            if l1 != l2:
                visited_targets[l2] = l1

        # Also track a representative shared name for each group leader
        group_shared_name: dict = {}  # leader_id -> norm_name that triggered the union

        for norm_name, target_list in name_to_targets.items():
            # Deduplicate target ids within this name
            unique_ids = list({t[0] for t in target_list})
            if len(unique_ids) < 2:
                continue
            # Union all targets sharing this name
            for i in range(1, len(unique_ids)):
                union(unique_ids[0], unique_ids[i])
            # Record a shared name for this group (first one encountered wins)
            leader_after = find_leader(unique_ids[0])
            if leader_after not in group_shared_name:
                group_shared_name[leader_after] = norm_name

        # Collect groups
        groups: dict[str, list] = defaultdict(list)
        for tid in target_info:
            leader = find_leader(tid)
            if leader != tid or visited_targets.get(tid) is not None:
                groups[find_leader(tid)].append(tid)

        # Only keep groups with 2+ members
        dup_candidates_found = 0
        for leader, members in groups.items():
            if len(members) < 2:
                continue

            # Pick the target with the most images as the suggested winner
            members_with_info = [(tid, *target_info[tid]) for tid in members]
            members_with_info.sort(key=lambda x: x[2], reverse=True)  # sort by img_count desc
            winner_id = members_with_info[0][0]
            winner_name = members_with_info[0][1]
            shared_name = group_shared_name.get(leader, "")

            for tid, pname, img_count in members_with_info[1:]:
                if pname in existing_names_p2:
                    continue
                db.add(MergeCandidate(
                    source_name=pname,
                    source_image_count=img_count,
                    suggested_target_id=winner_id,
                    similarity_score=1.0,
                    method="duplicate",
                    status="pending",
                    reason_text=f'Shares alias "{shared_name}" with "{winner_name}"',
                ))
                existing_names_p2.add(pname)
                dup_candidates_found += 1
                candidates_found += 1

        if dup_candidates_found > 0:
            db.commit()
            logger.info("detect_duplicates: found %d duplicate-name candidates", dup_candidates_found)

    # Update scan summary in Redis with duplicates_found and unresolved_names counts
    try:
        import json as _json
        raw = _redis.get("galactilog:scan_summary")
        if raw:
            _summary = _json.loads(raw)
            _summary["duplicates_found"] = candidates_found
            _summary["unresolved_names"] = orphan_count
            _redis.set("galactilog:scan_summary", _json.dumps(_summary))
    except Exception:
        logger.warning("detect_duplicate_targets: failed to update scan_summary in Redis")

    return {"candidates_found": candidates_found}


@celery_app.task(bind=True, name="app.worker.tasks.backfill_catalog_identity")
def backfill_catalog_identity(self) -> dict:
    """Re-link catalog orphans by identity and repair corrupted SIMBAD cache.

    Phase 1 (required): repair pre-b9c61a6 SIMBAD cache rows whose quote-
    corrupted aliases curate to empty.
    Phase 2: for each distinct unlinked LIGHT OBJECT name, resolve it and match
    an existing target by catalog identity; link the images if matched. Names
    that resolve to nothing or to no existing target stay orphaned for
    duplicate-detection plus manual accept. One-time and safely re-runnable.
    """
    logger.info("backfill_catalog_identity: starting")
    clear_cancel_sync(_redis)
    set_rebuild_running_sync(
        _redis, "backfill", "Repairing SIMBAD cache...",
        task="backfill", step=0, total_steps=0,
    )

    # Phase 1: corrupted-cache repair.
    with Session(_sync_engine) as session:
        repair_summary = repair_corrupted_simbad_cache(session)
    logger.info("backfill_catalog_identity: cache repair %s", repair_summary)

    # Phase 2: distinct unlinked LIGHT OBJECT names.
    with Session(_sync_engine) as session:
        rows = session.execute(text("""
            SELECT raw_headers->>'OBJECT' AS obj, COUNT(*) AS cnt
            FROM images
            WHERE resolved_target_id IS NULL
              AND image_type = 'LIGHT'
              AND raw_headers->>'OBJECT' IS NOT NULL
              AND raw_headers->>'OBJECT' != ''
            GROUP BY raw_headers->>'OBJECT'
            ORDER BY cnt DESC
        """)).all()

    total = len(rows)
    set_rebuild_progress_sync(
        _redis, f"Linking 0/{total} orphaned names...",
        task="backfill", step=0, total_steps=total,
    )
    linked = 0
    skipped = 0

    for i, (obj_name, img_count) in enumerate(rows):
        if is_cancel_requested_sync(_redis):
            details = {"linked": linked, "skipped": skipped, "total": total, "processed": i}
            set_rebuild_cancelled_sync(
                _redis, f"Cancelled after {i}/{total} names", details,
            )
            return {"status": "cancelled", **details}

        with Session(_sync_engine) as session:
            resolved = resolve_target_name_cached(obj_name, session)
            session.commit()
            target = match_target_by_identity(resolved, obj_name, session) if resolved else None
            if target is not None:
                target_id = target.id
                session.commit()  # persist alias addition from the matcher
                linked_ids = session.execute(text("""
                    UPDATE images
                    SET resolved_target_id = :tid
                    WHERE resolved_target_id IS NULL
                      AND raw_headers->>'OBJECT' = :obj
                    RETURNING id
                """), {"tid": target_id, "obj": obj_name}).scalars().all()
                recompute_panel_membership_for_images_sync(session, linked_ids)
                session.commit()
                linked += 1
                logger.info("backfill: linked %d images for '%s' -> %s",
                            img_count, obj_name, target_id)
            else:
                skipped += 1

        if (i + 1) % 5 == 0 or i + 1 == total:
            set_rebuild_progress_sync(
                _redis, f"Linking {i + 1}/{total} orphaned names...",
                task="backfill", step=i + 1, total_steps=total,
            )
        time.sleep(0.1)

    details = {
        "linked": linked, "skipped": skipped, "total": total,
        "cache_repaired": repair_summary["repaired"],
    }
    set_rebuild_complete_sync(
        _redis,
        f"Re-linked {linked} catalog orphans, {skipped} left unresolved "
        f"({repair_summary['repaired']} cache rows repaired)",
        details,
        task="backfill", step=total, total_steps=total,
    )
    logger.info("backfill_catalog_identity: complete %s", details)
    return {"status": "complete", **details}
