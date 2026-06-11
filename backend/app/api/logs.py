from __future__ import annotations

import base64
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin
from app.database import get_session
from app.models.app_log import AppLog
from app.models.user import User
from app.schemas.app_log import AppLogItem, PaginatedAppLogResponse
from app.schemas.common import StatusResponse
from app.services.activity import emit

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/logs", tags=["logs"])

_VALID_LEVELS = {"debug", "info", "warning", "error", "critical"}
_VALID_SOURCES = {"api", "worker", "beat"}
_DOWNLOAD_CAP = 50000


def _encode_cursor(ts: datetime, _id: int) -> str:
    return base64.urlsafe_b64encode(f"{ts.isoformat()}|{_id}".encode()).decode()


def _decode_cursor(cursor: str):
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        ts_str, id_str = raw.rsplit("|", 1)
        return datetime.fromisoformat(ts_str), int(id_str)
    except Exception:
        return None


def _apply_filters(q, level, source, qtext, since):
    valid_lvl = [lv for lv in level if lv in _VALID_LEVELS]
    if valid_lvl:
        q = q.where(AppLog.level.in_(valid_lvl))
    valid_src = [s for s in source if s in _VALID_SOURCES]
    if valid_src:
        q = q.where(AppLog.source.in_(valid_src))
    if qtext:
        q = q.where(AppLog.message.ilike(f"%{qtext}%"))
    if since is not None:
        q = q.where(AppLog.timestamp > since)
    return q


@router.get("", response_model=PaginatedAppLogResponse)
async def list_logs(
    level: list[str] = Query(default=[]),
    source: list[str] = Query(default=[]),
    q: str | None = Query(default=None),
    since: datetime | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_admin),
):
    count_q = _apply_filters(select(func.count(AppLog.id)), level, source, q, since)
    total = (await session.execute(count_q)).scalar_one()

    items_q = _apply_filters(select(AppLog), level, source, q, since)
    if cursor:
        decoded = _decode_cursor(cursor)
        if decoded:
            cts, cid = decoded
            items_q = items_q.where(
                (AppLog.timestamp < cts) | ((AppLog.timestamp == cts) & (AppLog.id < cid))
            )
    items_q = items_q.order_by(AppLog.timestamp.desc(), AppLog.id.desc()).limit(limit)
    rows = (await session.execute(items_q)).scalars().all()

    next_cursor = None
    if len(rows) == limit:
        next_cursor = _encode_cursor(rows[-1].timestamp, rows[-1].id)

    return PaginatedAppLogResponse(
        items=[AppLogItem.model_validate(r) for r in rows],
        next_cursor=next_cursor,
        total=total,
    )


@router.get("/download")
async def download_logs(
    level: list[str] = Query(default=[]),
    source: list[str] = Query(default=[]),
    q: str | None = Query(default=None),
    since: datetime | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_admin),
):
    items_q = _apply_filters(select(AppLog), level, source, q, since)
    items_q = items_q.order_by(AppLog.timestamp.desc(), AppLog.id.desc()).limit(_DOWNLOAD_CAP + 1)
    rows = (await session.execute(items_q)).scalars().all()
    truncated = len(rows) > _DOWNLOAD_CAP
    rows = rows[:_DOWNLOAD_CAP]

    lines = []
    for r in reversed(rows):  # oldest first in the file
        lines.append(f"{r.timestamp.isoformat()} [{r.level.upper()}] ({r.source}) {r.logger}: {r.message}")
        if r.traceback:
            lines.append(r.traceback)
    if truncated:
        lines.append(f"# NOTE: output truncated to newest {_DOWNLOAD_CAP} rows")
    content = "\n".join(lines) + "\n"
    return PlainTextResponse(
        content,
        headers={"Content-Disposition": "attachment; filename=galactilog-app.log"},
    )


@router.delete("", response_model=StatusResponse)
async def clear_logs(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_admin),
):
    await session.execute(delete(AppLog))
    await session.commit()
    # Audit trail: record who cleared the application logs.
    await emit(
        session, category="system", severity="warning",
        event_type="app_logs_cleared",
        message="Application logs cleared",
        actor=user.username,
    )
    return {"status": "cleared"}
