import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
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
from app.schemas.backup import ValidateResponse, RestoreResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/backup", tags=["backup"])


_INVALID_BACKUP_ERROR = "Backup file is not valid - see server logs for details."


def _parse_sections(sections: str) -> list[str] | None:
    parsed = [s.strip() for s in sections.split(",") if s.strip()]
    return parsed or None


def _reject(result: dict, user: User, action: str) -> str:
    """Log a failed validation and return the client-facing stand-in message.

    `validate_backup` folds raw exception text into its `error` field (the
    pydantic ValidationError for a malformed payload, the ValueError from
    `apply_migrations`), so none of it is handed back to the browser
    (py/stack-trace-exposure). Both callers below go through here, which keeps
    the substitution at one choke point rather than per handler.
    """
    logger.warning(
        "backup: %s rejected user=%s error=%s",
        action, user.username, result.get("error"),
    )
    return _INVALID_BACKUP_ERROR


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


@router.post("/validate", response_model=ValidateResponse)
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
        raise HTTPException(status_code=400, detail="File is not valid JSON")

    section_list = _parse_sections(sections)
    logger.info("backup: validate by user=%s mode=%s sections=%s", user.username, mode, sections or "all")
    result = validate_backup(data, sections=section_list, mode=mode)
    if not result["valid"]:
        return ValidateResponse(valid=False, error=_reject(result, user, "validate"))
    return result


@router.post("/restore", response_model=RestoreResponse)
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
        raise HTTPException(status_code=400, detail="File is not valid JSON")

    # Validate first
    section_list = _parse_sections(sections)
    validation = validate_backup(data, sections=section_list, mode=mode)
    if not validation["valid"]:
        raise HTTPException(
            status_code=400,
            detail=_reject(validation, user, "restore"),
        )

    logger.info("backup: restore starting user=%s mode=%s sections=%s", user.username, mode, sections or "all")
    try:
        result = await restore_backup(
            session, data,
            sections=section_list,
            mode=mode,
            acting_user_id=user.id,
        )
        await session.commit()
        # Invalidate stats cache since restored data changes aggregates
        try:
            from app.config import async_redis
            from app.services.cache import RIG_BASELINES_CACHE_KEY
            async with async_redis() as r:
                await r.delete("galactilog:stats:cache", "galactilog:fits_keys", RIG_BASELINES_CACHE_KEY)
        except Exception:
            pass
        logger.info("backup: restore success user=%s applied=%s", user.username, list(result.get("applied", {}).keys()))
        return result
    except Exception:
        logger.exception("backup: restore failed user=%s mode=%s", user.username, mode)
        await session.rollback()
        raise HTTPException(
            status_code=500,
            detail="Restore failed - see server logs for details.",
        )
