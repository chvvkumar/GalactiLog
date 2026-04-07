import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, update, func, create_engine
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, Session as SyncSession

from app.database import get_session
from app.api.deps import get_current_user, require_admin
from app.config import settings
from app.models.user import User
from app.models.target import Target
from app.models.image import Image
from app.models.filename_candidate import FilenameCandidate
from app.schemas.filename_candidate import FilenameCandidateResponse, AcceptRequest

router = APIRouter(prefix="/filename-resolution", tags=["filename-resolution"])


@router.get("/candidates/count")
async def get_candidate_count(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Return count of pending filename candidates (for badge display)."""
    result = await session.execute(
        select(func.count(FilenameCandidate.id)).where(
            FilenameCandidate.status == "pending"
        )
    )
    count = result.scalar_one()
    return {"count": count}


@router.get("/candidates", response_model=list[FilenameCandidateResponse])
async def list_candidates(
    status: str = Query(default="pending"),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """List filename candidates, joined with suggested target name, ordered by confidence."""
    SuggestedTarget = aliased(Target)

    result = await session.execute(
        select(
            FilenameCandidate,
            SuggestedTarget.primary_name.label("suggested_target_name"),
        )
        .outerjoin(
            SuggestedTarget,
            FilenameCandidate.suggested_target_id == SuggestedTarget.id,
        )
        .where(FilenameCandidate.status == status)
        .order_by(FilenameCandidate.confidence.desc())
    )
    rows = result.all()

    return [
        FilenameCandidateResponse(
            id=fc.id,
            extracted_name=fc.extracted_name,
            suggested_target_id=fc.suggested_target_id,
            suggested_target_name=suggested_target_name,
            method=fc.method,
            confidence=fc.confidence,
            status=fc.status,
            file_count=fc.file_count,
            file_paths=fc.file_paths if isinstance(fc.file_paths, list) else [],
            created_at=fc.created_at.isoformat() if fc.created_at else "",
            resolved_at=fc.resolved_at.isoformat() if fc.resolved_at else None,
        )
        for fc, suggested_target_name in rows
    ]


@router.post("/candidates/{candidate_id}/accept")
async def accept_candidate(
    candidate_id: uuid.UUID,
    body: AcceptRequest,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_admin),
):
    """Accept a filename candidate: assign images to target."""
    candidate = await session.get(FilenameCandidate, candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")
    if candidate.status != "pending":
        raise HTTPException(status_code=400, detail="Candidate is not pending")

    now = datetime.now(timezone.utc)

    # Determine which target to assign to
    target_id = body.target_id or candidate.suggested_target_id

    # If create_new and method is simbad_new, resolve via SIMBAD to create the target
    if body.create_new and candidate.method == "simbad_new":
        from app.services.target_resolver import resolve_target

        sync_url = settings.database_url.replace("+asyncpg", "+psycopg2")
        sync_engine = create_engine(sync_url, pool_pre_ping=True)
        try:
            with SyncSession(sync_engine) as sync_session:
                resolved_id = resolve_target(candidate.extracted_name, sync_session)
                sync_session.commit()
            if resolved_id:
                target_id = uuid.UUID(resolved_id)
        finally:
            sync_engine.dispose()

    if not target_id:
        raise HTTPException(
            status_code=400, detail="No target_id provided and no suggested target"
        )

    # Filter image_ids to only those that still exist AND are unresolved
    if candidate.image_ids:
        existing_result = await session.execute(
            select(Image.id).where(
                Image.id.in_(candidate.image_ids),
                Image.resolved_target_id.is_(None),
            )
        )
        valid_image_ids = [row[0] for row in existing_result.all()]

        if valid_image_ids:
            await session.execute(
                update(Image)
                .where(Image.id.in_(valid_image_ids))
                .values(resolved_target_id=target_id)
            )

    # Update candidate
    candidate.status = "accepted"
    candidate.resolved_at = now
    candidate.suggested_target_id = target_id

    await session.commit()
    return {"status": "ok"}


@router.post("/candidates/{candidate_id}/dismiss")
async def dismiss_candidate(
    candidate_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_admin),
):
    """Dismiss a filename candidate."""
    candidate = await session.get(FilenameCandidate, candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")
    if candidate.status != "pending":
        raise HTTPException(status_code=400, detail=f"Candidate is already {candidate.status}")

    now = datetime.now(timezone.utc)
    candidate.status = "dismissed"
    candidate.resolved_at = now

    await session.commit()
    return {"status": "ok"}


@router.post("/candidates/{candidate_id}/revert")
async def revert_candidate(
    candidate_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_admin),
):
    """Revert an accepted filename candidate: unassign images and reset to pending."""
    candidate = await session.get(FilenameCandidate, candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")
    if candidate.status != "accepted":
        raise HTTPException(
            status_code=400, detail="Only accepted candidates can be reverted"
        )

    # Unset resolved_target_id for images matching image_ids AND the candidate's target
    if candidate.image_ids and candidate.suggested_target_id:
        await session.execute(
            update(Image)
            .where(
                Image.id.in_(candidate.image_ids),
                Image.resolved_target_id == candidate.suggested_target_id,
            )
            .values(resolved_target_id=None)
        )

    candidate.status = "pending"
    candidate.resolved_at = None

    await session.commit()
    return {"status": "ok"}


@router.post("/detect")
async def trigger_detection(user: User = Depends(require_admin)):
    """Trigger filename-based target detection via Celery."""
    from app.worker.tasks import detect_filename_targets

    task = detect_filename_targets.delay()
    return {"status": "queued", "task_id": task.id}
