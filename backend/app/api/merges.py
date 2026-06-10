import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, update, func, delete, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from app.database import get_session
from app.api.deps import get_current_user, require_admin
from app.models.user import User
from app.models.target import Target
from app.models.image import Image
from app.models.merge_candidate import MergeCandidate
from app.schemas.target import MergeCandidateResponse, MergedTargetResponse, MergeRequest, OrphanPreviewRequest, OrphanPreviewResponse, OrphanCreateRequest, MergePreviewRequest, MergePreviewResponse, TargetIdentityRequest, TargetIdentityResponse, StatusResponse, MergeCandidateCountResponse, DuplicateDetectionResponse, OrphanCreateResponse, CustomTargetCreateRequest, CustomTargetCreateResponse
from app.services.simbad import normalize_catalog_id
from app.models.simbad_cache import SimbadCache
from app.models.sesame_cache import SesameCache
from app.config import async_redis
from app.services.target_merge import (
    merge_targets as _merge_targets_service,
    merge_preview as _merge_preview_service,
    unmerge_target as _unmerge_target_service,
)

router = APIRouter(prefix="/targets", tags=["merges"])


@router.post("/merge", response_model=StatusResponse)
async def merge_targets(
    body: MergeRequest,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_admin),
):
    """Merge a loser target into a winner target."""
    return await _merge_targets_service(body, session)


@router.post("/merge-preview", response_model=MergePreviewResponse)
async def merge_preview(
    body: MergePreviewRequest,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_admin),
):
    """Preview the effect of a merge without making any changes."""
    return await _merge_preview_service(body, session)


@router.post("/detect-duplicates", response_model=DuplicateDetectionResponse)
async def trigger_duplicate_detection(user: User = Depends(require_admin)):
    """Manually trigger duplicate target detection."""
    from app.worker.tasks import detect_duplicate_targets
    task = detect_duplicate_targets.delay()
    return {"status": "queued", "task_id": task.id}


@router.post("/{target_id}/unmerge", response_model=StatusResponse)
async def unmerge_target(
    target_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_admin),
):
    """Restore a soft-deleted (merged) target."""
    return await _unmerge_target_service(target_id, session)


@router.get("/merge-candidates/count", response_model=MergeCandidateCountResponse)
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
            resolved_at=mc.resolved_at.isoformat() if mc.resolved_at else None,
            reason_text=mc.reason_text,
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
    import asyncio
    from app.services.simbad import normalize_object_name, resolve_target_name_cached
    from app.services.sesame import resolve_sesame_cached
    from sqlalchemy.orm import Session as SyncSession
    from app.database import sync_engine

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

    async with async_redis() as redis:
        await redis.srem("target_resolver:negative", normalized)

    def _resolve_sync():
        with SyncSession(sync_engine) as sync_db:
            result = resolve_target_name_cached(source, sync_db)
            if result is None:
                result = resolve_sesame_cached(source, sync_db)
            return result

    simbad_result = await asyncio.to_thread(_resolve_sync)

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
        ra_str = hdrs.get("RA") or hdrs.get("OBJCTRA")
        dec_str = hdrs.get("DEC") or hdrs.get("OBJCTDEC")
        if ra_str and dec_str:
            try:
                fallback_ra = float(ra_str)
                fallback_dec = float(dec_str)
            except (ValueError, TypeError):
                fallback_ra = _parse_sexa_ra(str(ra_str))
                fallback_dec = _parse_sexa_dec(str(dec_str))

    return OrphanPreviewResponse(
        source_name=source,
        resolved=False,
        primary_name=source,
        ra=fallback_ra,
        dec=fallback_dec,
    )


def _enrich_new_target(target_id) -> None:
    """Best-effort catalog enrichment for a newly created target."""
    try:
        from sqlalchemy.orm import Session as SyncSession
        from app.database import sync_engine
        from app.services.openngc import enrich_target_from_openngc
        from app.services.sac import enrich_target_from_sac
        from app.services.vizier import enrich_target_from_vizier

        with SyncSession(sync_engine) as sync_db:
            db_target = sync_db.get(Target, target_id)
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


@router.post("/orphan-create", response_model=OrphanCreateResponse)
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

    names_upper = {body.primary_name.strip().upper()}
    aliases: list[str] = []
    for raw in [candidate.source_name, *body.aliases]:
        a = (raw or "").strip()
        if a and a.upper() not in names_upper:
            aliases.append(a)
            names_upper.add(a.upper())

    target = Target(
        primary_name=body.primary_name,
        catalog_id=body.catalog_id,
        catalog_id_normalized=normalize_catalog_id(body.catalog_id),
        aliases=aliases,
        ra=body.ra,
        dec=body.dec,
        object_type=body.object_type,
        user_defined=body.user_defined,
        name_locked=body.user_defined,
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

    if not body.user_defined:
        _enrich_new_target(target.id)

    return {"target_id": str(target.id)}


@router.post("/custom", response_model=CustomTargetCreateResponse)
async def create_custom_target(
    body: CustomTargetCreateRequest,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_admin),
):
    """Create a target manually, unattached to any merge candidate.

    Used for custom objects (planets, comets) and pre-creating targets before
    their images are scanned. Retro-links any pending orphan candidates whose
    source name matches the new target's names.
    """
    name = body.primary_name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Primary name is required")

    names_upper = {name.upper()}
    aliases: list[str] = []
    for raw in body.aliases:
        a = raw.strip()
        if a and a.upper() not in names_upper:
            aliases.append(a)
            names_upper.add(a.upper())

    # A target conflicts if its primary name or any alias collides with any of
    # the new names (case-insensitive on primary name, exact on aliases).
    all_names = sorted({name, *aliases, *(n for n in names_upper)})
    conflict = (await session.execute(
        select(Target).where(
            Target.merged_into_id.is_(None),
            or_(
                func.upper(Target.primary_name).in_(names_upper),
                *[Target.aliases.any(n) for n in all_names],
            ),
        )
    )).scalars().first()
    if conflict:
        raise HTTPException(
            status_code=409,
            detail=f'Name already in use by "{conflict.primary_name}"',
        )

    cat_norm = normalize_catalog_id(body.catalog_id)
    if cat_norm:
        dup = (await session.execute(
            select(Target).where(
                Target.merged_into_id.is_(None),
                Target.catalog_id_normalized == cat_norm,
            )
        )).scalars().first()
        if dup:
            raise HTTPException(
                status_code=409,
                detail=f'Catalog ID already belongs to "{dup.primary_name}"',
            )

    target = Target(
        primary_name=name,
        catalog_id=body.catalog_id,
        catalog_id_normalized=cat_norm,
        aliases=aliases,
        ra=body.ra,
        dec=body.dec,
        object_type=body.object_type,
        user_defined=body.user_defined,
        name_locked=True,
    )
    session.add(target)
    await session.flush()

    # Retro-link pending orphan candidates whose source name matches, and
    # resolve their images, so pre-created targets absorb existing orphans.
    pending = (await session.execute(
        select(MergeCandidate).where(
            MergeCandidate.status == "pending",
            func.upper(MergeCandidate.source_name).in_(names_upper),
        )
    )).scalars().all()

    now = datetime.now(timezone.utc)
    linked_images = 0
    for cand in pending:
        result = await session.execute(
            update(Image)
            .where(
                Image.raw_headers["OBJECT"].astext == cand.source_name,
                Image.resolved_target_id.is_(None),
            )
            .values(resolved_target_id=target.id)
        )
        linked_images += result.rowcount or 0
        cand.suggested_target_id = target.id
        cand.status = "accepted"
        cand.resolved_at = now

    await session.commit()

    if not body.user_defined:
        _enrich_new_target(target.id)

    return {
        "target_id": str(target.id),
        "linked_candidates": len(pending),
        "linked_images": linked_images,
    }


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


@router.get("/{target_id:path}/merge-history", response_model=list[MergedTargetResponse])
async def get_merge_history(
    target_id: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Return all targets that were merged into a given target."""
    # Synthetic "obj:<name>" pseudo-targets (and any non-UUID id) have no DB row
    # and can never have merge history, so return an empty list rather than 422.
    try:
        target_id = uuid.UUID(target_id)
    except ValueError:
        return []

    target = await session.get(Target, target_id)
    if not target:
        raise HTTPException(status_code=404, detail="Target not found")

    winner_alias = aliased(Target, name="winner")

    result = await session.execute(
        select(
            Target,
            winner_alias.primary_name.label("merged_into_name"),
            func.count(Image.id).label("image_count"),
        )
        .join(winner_alias, Target.merged_into_id == winner_alias.id)
        .outerjoin(Image, Image.resolved_target_id == winner_alias.id)
        .where(Target.merged_into_id == target_id)
        .group_by(Target.id, winner_alias.primary_name)
        .order_by(Target.merged_at.desc())
    )
    rows = result.all()

    return [
        MergedTargetResponse(
            id=loser.id,
            primary_name=loser.primary_name,
            merged_into_id=loser.merged_into_id,
            merged_into_name=merged_into_name,
            merged_at=loser.merged_at.isoformat() if loser.merged_at else "",
            image_count=image_count,
        )
        for loser, merged_into_name, image_count in rows
    ]


@router.post("/merge-candidates/{candidate_id}/revert", response_model=StatusResponse)
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


@router.put("/{target_id}/identity", response_model=TargetIdentityResponse)
async def update_target_identity(
    target_id: uuid.UUID,
    body: TargetIdentityRequest,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_admin),
):
    """Rename a target or change its object type, optionally re-resolving via SIMBAD."""
    target = await session.get(Target, target_id)
    if not target or target.merged_into_id is not None:
        raise HTTPException(status_code=404, detail="Target not found")

    if body.re_resolve:
        import asyncio
        from app.services.simbad import resolve_target_name_cached, normalize_object_name
        from sqlalchemy.orm import Session as SyncSession
        from app.database import sync_engine

        lookup_name = target.catalog_id or target.primary_name or (
            target.aliases[0] if target.aliases else None
        )

        # Delete negative cache entries for all of this target's aliases
        all_names = [lookup_name] + list(target.aliases or [])
        for name in all_names:
            n = normalize_object_name(name)
            await session.execute(
                delete(SimbadCache).where(
                    SimbadCache.query_name == n,
                    SimbadCache.main_id.is_(None),
                )
            )
            await session.execute(
                delete(SesameCache).where(
                    SesameCache.query_name == n,
                    SesameCache.main_id.is_(None),
                )
            )
        await session.flush()

        async with async_redis() as redis:
            for name in all_names:
                n = normalize_object_name(name)
                await redis.srem("target_resolver:negative", n)

        def _resolve_sync():
            with SyncSession(sync_engine) as sync_db:
                return resolve_target_name_cached(lookup_name, sync_db)

        result = await asyncio.to_thread(_resolve_sync)

        if result:
            target.primary_name = result.get("primary_name") or target.primary_name
            target.catalog_id = result.get("catalog_id")
            target.common_name = result.get("common_name")
            if result.get("object_type"):
                target.object_type = result["object_type"]
            existing_norm = {a.upper() for a in (target.aliases or [])}
            new_aliases = list(target.aliases or [])
            for alias in result.get("aliases", []):
                if alias.upper() not in existing_norm:
                    new_aliases.append(alias)
                    existing_norm.add(alias.upper())
            target.aliases = new_aliases

        if not target.common_name and target.catalog_id:
            from app.services.openngc import lookup_openngc, extract_openngc_common_name
            from app.services.simbad import build_primary_name

            def _enrich_openngc():
                with SyncSession(sync_engine) as sync_db:
                    entry = lookup_openngc(sync_db, target.catalog_id)
                    if entry and entry.common_names:
                        return extract_openngc_common_name(entry.common_names)
                    return None

            ngc_common = await asyncio.to_thread(_enrich_openngc)
            if ngc_common:
                target.common_name = ngc_common
                target.primary_name = build_primary_name(target.catalog_id, ngc_common)

        target.name_locked = False

    else:
        category_to_simbad = {
            "Emission Nebula": "HII",
            "Reflection Nebula": "RNe",
            "Dark Nebula": "DNe",
            "Planetary Nebula": "PN",
            "Supernova Remnant": "SNR",
            "Galaxy": "G",
            "Open Cluster": "OpC",
            "Globular Cluster": "GlC",
            "Star": "*",
            "Other": "Other",
        }

        if body.primary_name is not None:
            target.primary_name = body.primary_name
            target.name_locked = True

        if body.object_type is not None:
            target.object_type = category_to_simbad.get(body.object_type, body.object_type)

    await session.commit()
    await session.refresh(target)

    return TargetIdentityResponse(
        id=target.id,
        primary_name=target.primary_name,
        catalog_id=target.catalog_id,
        common_name=target.common_name,
        object_type=target.object_type,
        name_locked=target.name_locked,
    )


@router.post("/merge-candidates/{candidate_id}/dismiss", response_model=StatusResponse)
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
