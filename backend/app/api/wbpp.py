"""WBPP session export router."""
import uuid
from datetime import date as date_type

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.api.deps import get_current_user
from app.config import settings
from app.models import Image, Target
from app.models.user import User
from app.schemas.wbpp import (
    WbppPreviewRequest, WbppPreviewResponse, WbppSessionPreview,
    WbppGenerateRequest, WbppGenerateResponse, WbppCopyOperation, WbppFolderLevel,
)
from app.services.wbpp_export import (
    detect_os, compute_session_levels, pick_default_level,
    disambiguate_staging_names, generate_powershell_script, generate_shell_script,
)

router = APIRouter(prefix="/wbpp", tags=["wbpp"])


async def _fetch_session_paths(target_id, session_dates, db):
    parsed = [date_type.fromisoformat(d) for d in session_dates]
    q = select(Image.file_path, Image.session_date).where(
        Image.resolved_target_id == target_id,
        Image.image_type == "LIGHT",
        Image.session_date.in_(parsed),
    )
    rows = (await db.execute(q)).all()
    result = {d: [] for d in session_dates}
    for row in rows:
        file_path, session_date = row[0], row[1]
        key = str(session_date)
        if key in result:
            result[key].append(file_path)
    return result


async def _fetch_all_paths_for_contamination(db):
    q = (
        select(Image.file_path, Image.session_date, Target.primary_name)
        .join(Target, Image.resolved_target_id == Target.id)
        .where(Image.image_type == "LIGHT", Image.session_date.isnot(None))
    )
    rows = (await db.execute(q)).all()
    result = {}
    for file_path, session_date, target_name in rows:
        result.setdefault((target_name, str(session_date)), []).append(file_path)
    return result


@router.post("/preview", response_model=WbppPreviewResponse)
async def wbpp_preview(
    payload: WbppPreviewRequest,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    try:
        target_id = uuid.UUID(payload.target_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid target_id")

    target_os = payload.target_os or detect_os(payload.library_root)
    fits_root = settings.fits_data_path
    session_paths = await _fetch_session_paths(target_id, payload.session_dates, db)
    all_paths = await _fetch_all_paths_for_contamination(db)

    previews = []
    for d in payload.session_dates:
        fps = session_paths.get(d, [])
        levels = compute_session_levels(d, fps, all_paths, fits_root, payload.library_root, target_os)
        previews.append(WbppSessionPreview(
            session_date=d,
            levels=[WbppFolderLevel(**lv.__dict__) for lv in levels],
            default_level_index=pick_default_level(levels),
            total_frame_count=len(fps),
        ))
    return WbppPreviewResponse(sessions=previews, target_os=target_os)


@router.post("/generate", response_model=WbppGenerateResponse)
async def wbpp_generate(
    payload: WbppGenerateRequest,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    try:
        target_id = uuid.UUID(payload.target_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid target_id")

    target_os = payload.target_os or detect_os(payload.library_root)
    sep = "\\" if target_os == "windows" else "/"
    fits_root = settings.fits_data_path
    session_paths = await _fetch_session_paths(target_id, payload.session_dates, db)
    all_paths = await _fetch_all_paths_for_contamination(db)

    staging_root = payload.staging_path
    if not staging_root:
        lib = payload.library_root.rstrip("/\\")
        staging_root = lib + sep + "_WBPP_staging" + sep + payload.target_name.replace(" ", "_")

    sources = []
    used_dates = []
    for d in payload.session_dates:
        fps = session_paths.get(d, [])
        levels = compute_session_levels(d, fps, all_paths, fits_root, payload.library_root, target_os)
        if not levels:
            continue
        idx = payload.chosen_levels.get(d, pick_default_level(levels))
        idx = max(0, min(idx, len(levels) - 1))
        sources.append(levels[idx].path)
        used_dates.append(d)

    if not sources:
        raise HTTPException(status_code=422, detail="No valid source folders for selected sessions")

    names = disambiguate_staging_names(sources, used_dates)
    copy_ops = list(zip(sources, names))
    safe = payload.target_name.replace(" ", "_")

    staging_base = staging_root.rstrip("/\\")
    operations = [
        WbppCopyOperation(
            session_date=d,
            source=src,
            destination=staging_base + sep + entry_name,
        )
        for d, (src, entry_name) in zip(used_dates, copy_ops)
    ]

    if target_os == "windows":
        filename = f"wbpp_{safe}.ps1"
        script = generate_powershell_script(copy_ops, staging_root, payload.target_name, payload.exclusions, used_dates, filename)
    else:
        filename = f"wbpp_{safe}.sh"
        script = generate_shell_script(copy_ops, staging_root, payload.target_name, payload.exclusions, used_dates, filename)

    return WbppGenerateResponse(
        filename=filename,
        target_os=target_os,
        staging_root=staging_root,
        script=script,
        operations=operations,
    )
