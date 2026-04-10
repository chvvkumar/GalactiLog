import json
import logging
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
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/backup", tags=["backup"])


def _parse_sections(sections: str) -> list[str] | None:
    parsed = [s.strip() for s in sections.split(",") if s.strip()]
    return parsed or None


@router.post("/create")
async def create_backup(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_admin),
):
    data = await export_backup(session)
    content = json.dumps(data, indent=2, ensure_ascii=False)
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
    filename = f"galactilog-backup-{date_str}.json"
    logger.info("backup: create by user=%s", user.username)

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

    section_list = _parse_sections(sections)
    logger.info("backup: validate by user=%s mode=%s sections=%s", user.username, mode, sections or "all")
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
    section_list = _parse_sections(sections)
    validation = validate_backup(data, sections=section_list, mode=mode)
    if not validation["valid"]:
        logger.warning("backup: restore rejected at validate user=%s error=%s", user.username, validation.get("error"))
        return {
            "success": False,
            "applied": {},
            "temporary_passwords": {},
            "warnings": [],
            "error": validation["error"],
        }

    logger.info("backup: restore starting user=%s mode=%s sections=%s", user.username, mode, sections or "all")
    try:
        result = await restore_backup(
            session, data,
            sections=section_list,
            mode=mode,
            acting_user_id=user.id,
        )
        await session.commit()
        logger.info("backup: restore success user=%s applied=%s", user.username, list(result.get("applied", {}).keys()))
        return result
    except Exception as e:
        logger.exception("backup: restore failed user=%s mode=%s", user.username, mode)
        await session.rollback()
        return {
            "success": False,
            "applied": {},
            "temporary_passwords": {},
            "warnings": [],
            "error": "Restore failed - see server logs for details.",
        }
