import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, update, func, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from app.database import get_session
from app.api.deps import get_current_user, require_admin
from app.models.user import User
from app.models.target import Target
from app.models.image import Image
from app.models.merge_candidate import MergeCandidate
from app.models.mosaic_panel import MosaicPanel
from app.models.mosaic_suggestion import MosaicSuggestion
from app.schemas.target import MergeCandidateResponse, MergedTargetResponse, MergeRequest, OrphanPreviewRequest, OrphanPreviewResponse, OrphanCreateRequest
from app.models.simbad_cache import SimbadCache
from app.models.sesame_cache import SesameCache
from app.config import async_redis

router = APIRouter(prefix="/targets", tags=["merges"])


@router.post("/merge")
async def merge_targets(
    body: MergeRequest,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_admin),
):
    """Merge a loser target into a winner target."""
    # Load winner
    winner = await session.get(Target, body.winner_id)
    if not winner:
        raise HTTPException(status_code=404, detail="Winner target not found")

    now = datetime.now(timezone.utc)

    if body.loser_id is not None:
        # Merge by target ID: move images, merge aliases, soft-delete loser
        loser = await session.get(Target, body.loser_id)
        if not loser:
            raise HTTPException(status_code=404, detail="Loser target not found")
        if loser.id == winner.id:
            raise HTTPException(status_code=400, detail="Winner and loser must be different targets")

        # Move all images from loser to winner
        await session.execute(
            update(Image)
            .where(Image.resolved_target_id == loser.id)
            .values(resolved_target_id=winner.id)
        )

        # Merge aliases: add loser's primary_name and all its aliases to winner
        new_aliases = list(winner.aliases or [])
        if loser.primary_name not in new_aliases and loser.primary_name != winner.primary_name:
            new_aliases.append(loser.primary_name)
        for alias in (loser.aliases or []):
            if alias not in new_aliases and alias != winner.primary_name:
                new_aliases.append(alias)
        winner.aliases = new_aliases

        # Update mosaic panels: reassign panels from loser to winner
        loser_panels_q = select(MosaicPanel).where(MosaicPanel.target_id == loser.id)
        loser_panels = (await session.execute(loser_panels_q)).scalars().all()
        for panel in loser_panels:
            panel.target_id = winner.id

        # Update mosaic suggestions: replace loser id with winner id in target_ids arrays
        suggestions_q = select(MosaicSuggestion).where(
            MosaicSuggestion.status == "pending"
        )
        all_suggestions = (await session.execute(suggestions_q)).scalars().all()
        for sug in all_suggestions:
            if loser.id in sug.target_ids:
                sug.target_ids = [winner.id if t == loser.id else t for t in sug.target_ids]

        # Soft-delete loser
        loser.merged_into_id = winner.id
        loser.merged_at = now

        # Mark related merge_candidates as accepted (candidates pointing to winner where source_name matches loser names)
        loser_names = set([loser.primary_name] + list(loser.aliases or []))
        await session.execute(
            update(MergeCandidate)
            .where(
                MergeCandidate.suggested_target_id == winner.id,
                MergeCandidate.source_name.in_(loser_names),
                MergeCandidate.status == "pending",
            )
            .values(status="accepted", resolved_at=now)
        )
        # Also accept candidates where suggested_target is the loser
        await session.execute(
            update(MergeCandidate)
            .where(
                MergeCandidate.suggested_target_id == loser.id,
                MergeCandidate.status == "pending",
            )
            .values(status="accepted", resolved_at=now)
        )

    elif body.loser_name is not None:
        # Merge unresolved name: add as alias to winner, resolve images with that OBJECT header
        loser_name = body.loser_name
        new_aliases = list(winner.aliases or [])
        if loser_name not in new_aliases and loser_name != winner.primary_name:
            new_aliases.append(loser_name)
        winner.aliases = new_aliases

        # Resolve all images whose OBJECT header matches loser_name and have no target (or wrong target)
        await session.execute(
            update(Image)
            .where(
                Image.raw_headers["OBJECT"].astext == loser_name,
                Image.resolved_target_id.is_(None),
            )
            .values(resolved_target_id=winner.id)
        )

        # Mark related merge_candidates as accepted
        await session.execute(
            update(MergeCandidate)
            .where(
                MergeCandidate.suggested_target_id == winner.id,
                MergeCandidate.source_name == loser_name,
                MergeCandidate.status == "pending",
            )
            .values(status="accepted", resolved_at=now)
        )

        # Also accept orphan candidates for this source_name
        await session.execute(
            update(MergeCandidate)
            .where(
                MergeCandidate.source_name == loser_name,
                MergeCandidate.suggested_target_id.is_(None),
                MergeCandidate.status == "pending",
            )
            .values(status="accepted", resolved_at=now, suggested_target_id=winner.id)
        )

    else:
        raise HTTPException(status_code=400, detail="Either loser_id or loser_name must be provided")

    await session.commit()
    return {"status": "ok"}


@router.post("/detect-duplicates")
async def trigger_duplicate_detection(user: User = Depends(require_admin)):
    """Manually trigger duplicate target detection."""
    from app.worker.tasks import detect_duplicate_targets
    task = detect_duplicate_targets.delay()
    return {"status": "queued", "task_id": task.id}


@router.post("/{target_id}/unmerge")
async def unmerge_target(
    target_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_admin),
):
    """Restore a soft-deleted (merged) target."""
    loser = await session.get(Target, target_id)
    if not loser:
        raise HTTPException(status_code=404, detail="Target not found")
    if not loser.merged_into_id:
        raise HTTPException(status_code=400, detail="Target has not been merged")

    winner = await session.get(Target, loser.merged_into_id)
    if not winner:
        raise HTTPException(status_code=404, detail="Winner target not found")

    # Determine the names that belong to the loser (primary + aliases recorded at merge time)
    loser_names = set([loser.primary_name] + list(loser.aliases or []))

    # Reassign images back to loser based on OBJECT header matching loser's names
    for name in loser_names:
        await session.execute(
            update(Image)
            .where(
                Image.resolved_target_id == winner.id,
                Image.raw_headers["OBJECT"].astext == name,
            )
            .values(resolved_target_id=loser.id)
        )

    # Remove loser's names from winner's aliases
    winner_aliases = [a for a in (winner.aliases or []) if a not in loser_names]
    winner.aliases = winner_aliases

    # Revert mosaic panel reassignment: move panels back to loser
    # Only reassign panels whose object_pattern matches the loser's names
    winner_panels_q = select(MosaicPanel).where(MosaicPanel.target_id == winner.id)
    winner_panels = (await session.execute(winner_panels_q)).scalars().all()
    for panel in winner_panels:
        if panel.object_pattern:
            pattern_lower = panel.object_pattern.lower()
            for name in loser_names:
                if name.lower() in pattern_lower:
                    panel.target_id = loser.id
                    break

    # Clear merge fields on loser
    loser.merged_into_id = None
    loser.merged_at = None

    # Reset merge_candidates back to pending
    loser_names_list = list(loser_names)
    await session.execute(
        update(MergeCandidate)
        .where(
            MergeCandidate.suggested_target_id == winner.id,
            MergeCandidate.source_name.in_(loser_names_list),
            MergeCandidate.status == "accepted",
        )
        .values(status="pending", resolved_at=None)
    )
    await session.execute(
        update(MergeCandidate)
        .where(
            MergeCandidate.suggested_target_id == loser.id,
            MergeCandidate.status == "accepted",
        )
        .values(status="pending", resolved_at=None)
    )

    await session.commit()
    return {"status": "ok"}


@router.get("/merge-candidates/count")
async def get_merge_candidate_count(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Return count of pending merge candidates (for badge display)."""
    result = await session.execute(
        select(func.count(MergeCandidate.id)).where(MergeCandidate.status == "pending")
    )
    count = result.scalar_one()
    return {"count": count}


@router.get("/merge-candidates", response_model=list[MergeCandidateResponse])
async def list_merge_candidates(
    status: str = Query(default="pending"),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """List merge candidates, joined with suggested target name, ordered by similarity."""
    result = await session.execute(
        select(MergeCandidate, Target.primary_name.label("suggested_target_name"))
        .outerjoin(Target, MergeCandidate.suggested_target_id == Target.id)
        .where(MergeCandidate.status == status)
        .order_by(MergeCandidate.similarity_score.desc())
    )
    rows = result.all()

    return [
        MergeCandidateResponse(
            id=mc.id,
            source_name=mc.source_name,
            source_image_count=mc.source_image_count,
            suggested_target_id=mc.suggested_target_id,
            suggested_target_name=suggested_target_name,
            similarity_score=mc.similarity_score,
            method=mc.method,
            status=mc.status,
            created_at=mc.created_at.isoformat() if mc.created_at else "",
        )
        for mc, suggested_target_name in rows
    ]


@router.post("/orphan-preview", response_model=OrphanPreviewResponse)
async def orphan_preview(
    body: OrphanPreviewRequest,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_admin),
):
    """Preview metadata for creating a target from an unresolved OBJECT name."""
    from app.services.simbad import normalize_object_name, resolve_target_name_cached
    from app.services.sesame import resolve_sesame_cached
    from sqlalchemy.orm import Session as SyncSession
    from app.database import engine as async_engine

    source = body.source_name
    normalized = normalize_object_name(source)

    # Clear negative caches so the name gets a fresh attempt
    await session.execute(
        delete(SimbadCache).where(SimbadCache.query_name == normalized, SimbadCache.main_id.is_(None))
    )
    await session.execute(
        delete(SesameCache).where(SesameCache.query_name == normalized, SesameCache.main_id.is_(None))
    )
    await session.commit()

    redis = await async_redis()
    if redis:
        await redis.srem("target_resolver:negative", normalized)

    simbad_result = None
    with SyncSession(async_engine.sync_engine) as sync_db:
        simbad_result = resolve_target_name_cached(source, sync_db)
        if simbad_result is None:
            simbad_result = resolve_sesame_cached(source, sync_db)

    if simbad_result:
        return OrphanPreviewResponse(
            source_name=source,
            resolved=True,
            primary_name=simbad_result.get("primary_name", source),
            catalog_id=simbad_result.get("catalog_id"),
            ra=simbad_result.get("ra"),
            dec=simbad_result.get("dec"),
            object_type=simbad_result.get("object_type"),
            constellation=simbad_result.get("constellation"),
            size_major=simbad_result.get("size_major"),
            size_minor=simbad_result.get("size_minor"),
            position_angle=simbad_result.get("position_angle"),
            v_mag=simbad_result.get("v_mag"),
        )

    # Fallback: extract RA/DEC from FITS headers
    from app.api.targets import _parse_sexa_ra, _parse_sexa_dec

    img_result = await session.execute(
        select(Image)
        .where(
            Image.raw_headers["OBJECT"].astext == source,
            Image.image_type == "LIGHT",
        )
        .limit(1)
    )
    img = img_result.scalar_one_or_none()

    fallback_ra = None
    fallback_dec = None
    if img:
        hdrs = img.raw_headers or {}
        ra_str = hdrs.get("OBJCTRA") or hdrs.get("RA")
        dec_str = hdrs.get("OBJCTDEC") or hdrs.get("DEC")
        if ra_str and dec_str:
            parsed_ra = _parse_sexa_ra(str(ra_str))
            parsed_dec = _parse_sexa_dec(str(dec_str))
            if parsed_ra is not None and parsed_dec is not None:
                fallback_ra = parsed_ra
                fallback_dec = parsed_dec
            else:
                try:
                    fallback_ra = float(ra_str)
                    fallback_dec = float(dec_str)
                except (ValueError, TypeError):
                    pass

    return OrphanPreviewResponse(
        source_name=source,
        resolved=False,
        primary_name=source,
        ra=fallback_ra,
        dec=fallback_dec,
    )


@router.post("/orphan-create")
async def orphan_create(
    body: OrphanCreateRequest,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_admin),
):
    """Create a new target from an orphan merge candidate and resolve its images."""
    candidate = await session.get(MergeCandidate, body.candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Merge candidate not found")
    if candidate.status != "pending":
        raise HTTPException(status_code=400, detail="Candidate is not pending")

    now = datetime.now(timezone.utc)

    target = Target(
        primary_name=body.primary_name,
        catalog_id=body.catalog_id,
        aliases=[candidate.source_name] if candidate.source_name != body.primary_name else [],
        ra=body.ra,
        dec=body.dec,
        object_type=body.object_type,
    )
    session.add(target)
    await session.flush()

    await session.execute(
        update(Image)
        .where(
            Image.raw_headers["OBJECT"].astext == candidate.source_name,
            Image.resolved_target_id.is_(None),
        )
        .values(resolved_target_id=target.id)
    )

    candidate.suggested_target_id = target.id
    candidate.status = "accepted"
    candidate.resolved_at = now

    await session.commit()

    # Run enrichment (sync, non-critical)
    try:
        from sqlalchemy.orm import Session as SyncSession
        from app.database import engine as async_engine
        from app.services.openngc import enrich_target_from_openngc
        from app.services.sac import enrich_target_from_sac
        from app.services.vizier import enrich_target_from_vizier

        with SyncSession(async_engine.sync_engine) as sync_db:
            db_target = sync_db.get(Target, target.id)
            if db_target:
                enrich_target_from_openngc(sync_db, db_target)
                sync_db.commit()
                if db_target.size_major is None:
                    enrich_target_from_vizier(sync_db, db_target)
                    sync_db.commit()
                enrich_target_from_sac(sync_db, db_target)
                sync_db.commit()
    except Exception:
        pass

    return {"target_id": str(target.id)}


@router.get("/merged-targets", response_model=list[MergedTargetResponse])
async def list_merged_targets(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """List all soft-deleted (merged) targets with winner name and image count."""
    winner_alias = aliased(Target, name="winner")

    result = await session.execute(
        select(
            Target,
            winner_alias.primary_name.label("merged_into_name"),
            func.count(Image.id).label("image_count"),
        )
        .join(winner_alias, Target.merged_into_id == winner_alias.id)
        .outerjoin(Image, Image.resolved_target_id == winner_alias.id)
        .where(Target.merged_into_id.is_not(None))
        .group_by(Target.id, winner_alias.primary_name)
        .order_by(Target.merged_at.desc())
    )
    rows = result.all()

    return [
        MergedTargetResponse(
            id=target.id,
            primary_name=target.primary_name,
            merged_into_id=target.merged_into_id,
            merged_into_name=merged_into_name,
            merged_at=target.merged_at.isoformat() if target.merged_at else "",
            image_count=image_count,
        )
        for target, merged_into_name, image_count in rows
    ]


@router.post("/merge-candidates/{candidate_id}/revert")
async def revert_merge_candidate(
    candidate_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_admin),
):
    """Revert an accepted merge candidate: remove alias, un-resolve images, reset to pending."""
    candidate = await session.get(MergeCandidate, candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Merge candidate not found")
    if candidate.status != "accepted":
        raise HTTPException(status_code=400, detail="Only accepted candidates can be reverted")

    winner = await session.get(Target, candidate.suggested_target_id)
    if not winner:
        raise HTTPException(status_code=404, detail="Target not found")

    source_name = candidate.source_name

    if candidate.method == "orphan":
        await session.execute(
            update(Image)
            .where(
                Image.resolved_target_id == winner.id,
                Image.raw_headers["OBJECT"].astext == source_name,
            )
            .values(resolved_target_id=None)
        )
        remaining = await session.execute(
            select(func.count(Image.id)).where(Image.resolved_target_id == winner.id)
        )
        if remaining.scalar_one() == 0:
            await session.delete(winner)
        candidate.suggested_target_id = None
        candidate.status = "pending"
        candidate.resolved_at = None
    else:
        loser_result = await session.execute(
            select(Target).where(
                Target.merged_into_id == winner.id,
                Target.primary_name == source_name,
            )
        )
        loser = loser_result.scalar_one_or_none()

        if loser:
            loser_names = set([loser.primary_name] + list(loser.aliases or []))
            for name in loser_names:
                await session.execute(
                    update(Image)
                    .where(
                        Image.resolved_target_id == winner.id,
                        Image.raw_headers["OBJECT"].astext == name,
                    )
                    .values(resolved_target_id=loser.id)
                )
            winner.aliases = [a for a in (winner.aliases or []) if a not in loser_names]
            loser.merged_into_id = None
            loser.merged_at = None
        else:
            winner.aliases = [a for a in (winner.aliases or []) if a != source_name]
            await session.execute(
                update(Image)
                .where(
                    Image.resolved_target_id == winner.id,
                    Image.raw_headers["OBJECT"].astext == source_name,
                )
                .values(resolved_target_id=None)
            )

        candidate.status = "pending"
        candidate.resolved_at = None

    await session.commit()
    return {"status": "ok"}


@router.post("/merge-candidates/{candidate_id}/dismiss")
async def dismiss_merge_candidate(
    candidate_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_admin),
):
    """Set a merge candidate's status to dismissed."""
    candidate = await session.get(MergeCandidate, candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Merge candidate not found")

    now = datetime.now(timezone.utc)
    candidate.status = "dismissed"
    candidate.resolved_at = now

    await session.commit()
    return {"status": "ok"}
