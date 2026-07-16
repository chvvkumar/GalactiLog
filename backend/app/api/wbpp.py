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
    sanitize_script_name, fits_relative_path, map_excluded_to_ops,
)

router = APIRouter(prefix="/wbpp", tags=["wbpp"])


async def _fetch_session_paths(target_id, session_dates, db):
    """Return ({session_date: [container path]}, {container path: byte size or None}).

    The size map is deliberately raw: a NULL file_size stays None rather than
    collapsing to 0, so downstream can tell "unknown" from "empty".
    """
    parsed = [date_type.fromisoformat(d) for d in session_dates]
    q = select(Image.file_path, Image.session_date, Image.file_size).where(
        Image.resolved_target_id == target_id,
        Image.image_type == "LIGHT",
        Image.session_date.in_(parsed),
    )
    rows = (await db.execute(q)).all()
    result = {d: [] for d in session_dates}
    sizes: dict[str, int | None] = {}
    for row in rows:
        file_path, session_date, file_size = row[0], row[1], row[2]
        key = str(session_date)
        if key in result:
            result[key].append(file_path)
            sizes[file_path] = file_size
    return result, sizes


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
    session_paths, sizes_by_path = await _fetch_session_paths(target_id, payload.session_dates, db)
    all_paths = await _fetch_all_paths_for_contamination(db)

    excluded_set = set(payload.excluded_source_relatives)

    previews = []
    for d in payload.session_dates:
        fps = session_paths.get(d, [])
        levels = compute_session_levels(
            d, fps, all_paths, fits_root, payload.library_root, target_os,
            sizes_by_path=sizes_by_path,
        )
        excluded_count = sum(1 for fp in fps if fits_relative_path(fp, fits_root) in excluded_set)
        previews.append(WbppSessionPreview(
            session_date=d,
            levels=[WbppFolderLevel(**lv.__dict__) for lv in levels],
            default_level_index=pick_default_level(levels),
            total_frame_count=len(fps),
            excluded_frame_count=excluded_count,
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
    session_paths, _sizes = await _fetch_session_paths(target_id, payload.session_dates, db)
    all_paths = await _fetch_all_paths_for_contamination(db)

    staging_root = payload.staging_path
    if not staging_root:
        lib = payload.library_root.rstrip("/\\")
        staging_root = lib + sep + "_WBPP_staging" + sep + payload.target_name.replace(" ", "_")

    chosen = []  # (session_date, FolderLevel)
    for d in payload.session_dates:
        fps = session_paths.get(d, [])
        levels = compute_session_levels(d, fps, all_paths, fits_root, payload.library_root, target_os)
        if not levels:
            continue
        idx = payload.chosen_levels.get(d, pick_default_level(levels))
        idx = max(0, min(idx, len(levels) - 1))
        chosen.append((d, levels[idx]))

    if not chosen:
        raise HTTPException(status_code=422, detail="No valid source folders for selected sessions")

    used_dates = [d for d, _ in chosen]
    sources = [lv.path for _, lv in chosen]
    names = disambiguate_staging_names(sources, used_dates)
    copy_ops = list(zip(sources, names))
    safe = sanitize_script_name(payload.target_name)

    excluded_by_op = map_excluded_to_ops(payload.excluded_source_relatives, chosen)
    excluded_set = set(payload.excluded_source_relatives)
    light_total = 0
    light_excluded = 0
    for d in used_dates:
        for fp in session_paths.get(d, []):
            light_total += 1
            if fits_relative_path(fp, fits_root) in excluded_set:
                light_excluded += 1
    light_copied = light_total - light_excluded

    staging_base = staging_root.rstrip("/\\")

    operations = [
        WbppCopyOperation(
            session_date=d,
            source=lv.path,
            destination=staging_base + sep + name,
            source_relative=lv.relative_path,
            dest_entry=name,
        )
        for (d, lv), name in zip(chosen, names)
    ]

    if target_os == "windows":
        filename = f"wbpp_{safe}.ps1"
        script = generate_powershell_script(copy_ops, staging_root, payload.target_name, payload.exclusions, used_dates, filename, excluded_by_op=excluded_by_op)
    else:
        filename = f"wbpp_{safe}.sh"
        script = generate_shell_script(copy_ops, staging_root, payload.target_name, payload.exclusions, used_dates, filename, excluded_by_op=excluded_by_op)

    return WbppGenerateResponse(
        filename=filename,
        target_os=target_os,
        staging_root=staging_root,
        script=script,
        operations=operations,
        exclusions=payload.exclusions,
        light_total=light_total,
        light_excluded=light_excluded,
        light_copied=light_copied,
    )
