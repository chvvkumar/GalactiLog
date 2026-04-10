import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.api.deps import require_admin
from app.models.user import User
from app.services.backup import (
    export_backup,
    validate_backup,
    restore_backup,
    ALL_SECTIONS,
)

router = APIRouter(prefix="/backup", tags=["backup"])


@router.post("/create")
async def create_backup(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_admin),
):
    data = await export_backup(session)
    content = json.dumps(data, indent=2, ensure_ascii=False)
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    filename = f"galactilog-backup-{date_str}.json"

    return Response(
        content=content,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/validate")
async def validate_backup_endpoint(
    file: UploadFile = File(...),
    mode: str = Form("merge"),
    sections: str = Form(""),
    user: User = Depends(require_admin),
):
    try:
        raw = await file.read()
        data = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {
            "valid": False,
            "meta": None,
            "preview": {},
            "warnings": [],
            "error": "File is not valid JSON",
        }

    section_list = [s.strip() for s in sections.split(",") if s.strip()] or None
    return validate_backup(data, sections=section_list, mode=mode)


@router.post("/restore")
async def restore_backup_endpoint(
    file: UploadFile = File(...),
    mode: str = Form("merge"),
    sections: str = Form(""),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_admin),
):
    try:
        raw = await file.read()
        data = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {
            "success": False,
            "applied": {},
            "temporary_passwords": {},
            "warnings": [],
            "error": "File is not valid JSON",
        }

    # Validate first
    section_list = [s.strip() for s in sections.split(",") if s.strip()] or None
    validation = validate_backup(data, sections=section_list, mode=mode)
    if not validation["valid"]:
        return {
            "success": False,
            "applied": {},
            "temporary_passwords": {},
            "warnings": [],
            "error": validation["error"],
        }

    try:
        result = await restore_backup(session, data, sections=section_list, mode=mode)
        await session.commit()
        return result
    except Exception as e:
        await session.rollback()
        return {
            "success": False,
            "applied": {},
            "temporary_passwords": {},
            "warnings": [],
            "error": f"Restore failed: {e}",
        }
