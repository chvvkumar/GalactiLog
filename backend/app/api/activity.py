from __future__ import annotations

import base64
import json
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_admin
from app.database import get_session
from app.models.activity_event import ActivityEvent
from app.models.user import User
from app.schemas.activity import ActivityItem, PaginatedActivityResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/activity", tags=["activity"])

_VALID_SEVERITIES = {"info", "warning", "error"}
_VALID_CATEGORIES = {
    "scan", "rebuild", "thumbnail", "enrichment",
    "mosaic", "migration", "user_action", "system",
}


def _encode_cursor(ts: datetime, row_id: int) -> str:
    payload = json.dumps({"ts": ts.isoformat(), "id": row_id})
    return base64.urlsafe_b64encode(payload.encode()).decode()


def _decode_cursor(cursor: str) -> tuple[datetime, int] | None:
    try:
        payload = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
        return datetime.fromisoformat(payload["ts"]), int(payload["id"])
    except Exception:
        return None


@router.get("", response_model=PaginatedActivityResponse)
async def list_activity(
    severity: list[str] = Query(default=[]),
    category: list[str] = Query(default=[]),
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = Query(default=None),
    since: datetime | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Return paginated activity events, newest first.

    Only top-level events (parent_id IS NULL) are returned. Children are
    batch-loaded and nested under their parent's `children` field.
    """
    top_level_filter = ActivityEvent.parent_id.is_(None)

    count_q = select(func.count(ActivityEvent.id)).where(top_level_filter)
    items_q = select(ActivityEvent).where(top_level_filter)

    valid_sev = [s for s in severity if s in _VALID_SEVERITIES]
    if valid_sev:
        count_q = count_q.where(ActivityEvent.severity.in_(valid_sev))
        items_q = items_q.where(ActivityEvent.severity.in_(valid_sev))

    valid_cat = [c for c in category if c in _VALID_CATEGORIES]
    if valid_cat:
        count_q = count_q.where(ActivityEvent.category.in_(valid_cat))
        items_q = items_q.where(ActivityEvent.category.in_(valid_cat))

    if since is not None:
        count_q = count_q.where(ActivityEvent.timestamp > since)
        items_q = items_q.where(ActivityEvent.timestamp > since)

    total = (await session.execute(count_q)).scalar_one()

    if cursor:
        decoded = _decode_cursor(cursor)
        if decoded:
            cursor_ts, cursor_id = decoded
            items_q = items_q.where(
                (ActivityEvent.timestamp < cursor_ts)
                | (
                    (ActivityEvent.timestamp == cursor_ts)
                    & (ActivityEvent.id < cursor_id)
                )
            )

    items_q = (
        items_q
        .order_by(ActivityEvent.timestamp.desc(), ActivityEvent.id.desc())
        .limit(limit)
    )

    result = await session.execute(items_q)
    rows = result.scalars().all()

    next_cursor = None
    if len(rows) == limit:
        last = rows[-1]
        next_cursor = _encode_cursor(last.timestamp, last.id)

    parent_ids = [r.id for r in rows]
    children_by_parent: dict[int, list[ActivityItem]] = {}
    if parent_ids:
        children_q = (
            select(ActivityEvent)
            .where(ActivityEvent.parent_id.in_(parent_ids))
            .order_by(ActivityEvent.timestamp.asc())
        )
        children_result = await session.execute(children_q)
        for child in children_result.scalars().all():
            children_by_parent.setdefault(child.parent_id, []).append(
                ActivityItem.model_validate(child)
            )

    items = []
    for r in rows:
        item = ActivityItem.model_validate(r)
        item.children = children_by_parent.get(r.id) or None
        items.append(item)

    return PaginatedActivityResponse(
        items=items,
        next_cursor=next_cursor,
        total=total,
    )


@router.delete("")
async def clear_activity(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_admin),
):
    """Delete all activity_events rows. Admin only."""
    await session.execute(delete(ActivityEvent))
    await session.commit()
    return {"status": "cleared"}
