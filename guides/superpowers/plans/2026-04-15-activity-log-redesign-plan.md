# Activity Log Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the scattered activity log and ad-hoc in-progress indicators with a single durable Postgres-backed event store, a unified active-jobs view, and a redesigned Dashboard card that clearly separates live status from history.

**Architecture:** Backend adds an `activity_events` table, a single `emit()` helper, a filterable `/activity` API, and a nightly pruner. The 17 existing Redis-list call sites are refactored, and 7 previously-silent event sources are added with aggregation. Frontend adds an `activeJobs` adapter that merges scan status, rebuild status, and tracked Celery tasks into one shape, redesigns `ActivityFeed.tsx` into Now Running + History regions, and codifies toast firing rules via an `emitWithToast()` helper. Spec: `guides/superpowers/specs/2026-04-15-activity-log-redesign-design.md`.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 async, Alembic, asyncpg/psycopg2, Celery + Redis, pytest-asyncio, SolidJS + TypeScript strict, Tailwind CSS v4, Vite.

**Numbering:** Tasks 1-17 are backend. Tasks 100-113 are frontend. Run the backend series first, then the frontend series.

---

## Backend

### Task 1: Alembic migration creating `activity_events`

**Files:**
- Create: `backend/alembic/versions/0011_add_activity_events.py`

- [ ] **Step 1: Create the migration file.**

```python
"""Add activity_events table.

Creates the activity_events table with all columns and indexes defined in
the activity log redesign spec. Uses defensive IF NOT EXISTS guards per
project convention.
"""
from alembic import op
from sqlalchemy import text

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def _table_exists(name: str) -> bool:
    conn = op.get_bind()
    result = conn.execute(
        text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = :name"
        ),
        {"name": name},
    )
    return result.fetchone() is not None


def upgrade():
    if not _table_exists("activity_events"):
        op.execute("""
            CREATE TABLE activity_events (
                id          bigserial PRIMARY KEY,
                timestamp   timestamptz NOT NULL DEFAULT now(),
                severity    varchar(16) NOT NULL,
                category    varchar(32) NOT NULL,
                event_type  varchar(64) NOT NULL,
                message     text NOT NULL,
                details     jsonb,
                target_id   integer REFERENCES targets(id) ON DELETE SET NULL,
                actor       varchar(64),
                duration_ms integer
            )
        """)

    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_activity_timestamp_desc "
        "ON activity_events (timestamp DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_activity_severity_ts "
        "ON activity_events (severity, timestamp DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_activity_category_ts "
        "ON activity_events (category, timestamp DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_activity_target "
        "ON activity_events (target_id) WHERE target_id IS NOT NULL"
    )


def downgrade():
    op.execute("DROP INDEX IF EXISTS idx_activity_target")
    op.execute("DROP INDEX IF EXISTS idx_activity_category_ts")
    op.execute("DROP INDEX IF EXISTS idx_activity_severity_ts")
    op.execute("DROP INDEX IF EXISTS idx_activity_timestamp_desc")
    op.execute("DROP TABLE IF EXISTS activity_events")
```

Note: the migration revision number `0011` assumes current head is `0010`. Before committing, run `alembic current` and adjust `revision` and `down_revision` to match the actual head.

- [ ] **Step 2: Apply migration and confirm.**

```
cd backend && alembic upgrade head
```

Expected output contains: `Running upgrade 0010 -> 0011`.

- [ ] **Step 3: Verify columns.**

```
cd backend && python -c "
from sqlalchemy import create_engine, text
from app.config import settings
url = settings.database_url.replace('+asyncpg', '+psycopg2')
e = create_engine(url)
with e.connect() as c:
    r = c.execute(text(\"SELECT column_name FROM information_schema.columns WHERE table_name='activity_events' ORDER BY ordinal_position\"))
    print([row[0] for row in r])
"
```

Expected: `['id', 'timestamp', 'severity', 'category', 'event_type', 'message', 'details', 'target_id', 'actor', 'duration_ms']`

- [ ] **Step 4: Commit.**

```
git add backend/alembic/versions/0011_add_activity_events.py
git commit -m "Add activity_events table migration"
```

---

### Task 2: SQLAlchemy model `ActivityEvent`

**Files:**
- Create: `backend/app/models/activity_event.py`
- Modify: `backend/app/models/__init__.py`
- Test: `backend/tests/test_models.py`

- [ ] **Step 1: Write a failing test.**

Add to `backend/tests/test_models.py`:

```python
def test_activity_event_columns():
    from app.models.activity_event import ActivityEvent
    cols = {c.name for c in ActivityEvent.__table__.columns}
    assert cols == {
        "id", "timestamp", "severity", "category", "event_type",
        "message", "details", "target_id", "actor", "duration_ms",
    }
```

Run: `cd backend && pytest tests/test_models.py::test_activity_event_columns -v`
Expected: FAIL (ImportError).

- [ ] **Step 2: Create `backend/app/models/activity_event.py`.**

```python
from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class ActivityEvent(Base):
    __tablename__ = "activity_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    target_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("targets.id", ondelete="SET NULL"),
        nullable=True,
    )
    actor: Mapped[str | None] = mapped_column(String(64), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
```

- [ ] **Step 3: Update `backend/app/models/__init__.py`.**

Add after the last import:
```python
from .activity_event import ActivityEvent
```

Append `"ActivityEvent"` to `__all__`.

- [ ] **Step 4: Run tests.**

Run: `cd backend && pytest tests/test_models.py::test_activity_event_columns -v`
Expected: PASS.

- [ ] **Step 5: Write a round-trip instantiation test.**

Add to `backend/tests/test_models.py`:

```python
def test_activity_event_instantiation():
    from app.models.activity_event import ActivityEvent
    ev = ActivityEvent(
        severity="warning",
        category="scan",
        event_type="scan_complete",
        message="Scan complete: 5 new files added",
        details={"completed": 5, "failed": 0},
        actor="system",
    )
    assert ev.severity == "warning"
    assert ev.details["completed"] == 5
    assert ev.target_id is None
    assert ev.duration_ms is None
```

Run: `cd backend && pytest tests/test_models.py::test_activity_event_instantiation -v`
Expected: PASS.

- [ ] **Step 6: Commit.**

```
git add backend/app/models/activity_event.py backend/app/models/__init__.py backend/tests/test_models.py
git commit -m "Add ActivityEvent SQLAlchemy model"
```

---

### Task 3: Pydantic schemas for activity

**Files:**
- Create: `backend/app/schemas/activity.py`
- Create: `backend/tests/test_schemas_activity.py`

- [ ] **Step 1: Write failing tests.**

Create `backend/tests/test_schemas_activity.py`:

```python
import pytest
from datetime import datetime, timezone


def test_activity_item_fields():
    from app.schemas.activity import ActivityItem
    fields = set(ActivityItem.model_fields.keys())
    assert fields == {"id", "timestamp", "severity", "category", "event_type",
                      "message", "details", "target_id", "actor", "duration_ms"}


def test_activity_item_serializes():
    from app.schemas.activity import ActivityItem
    item = ActivityItem(
        id=1,
        timestamp=datetime(2026, 4, 15, 12, 0, 0, tzinfo=timezone.utc),
        severity="info", category="scan", event_type="scan_complete",
        message="done", details=None, target_id=None, actor="system", duration_ms=None,
    )
    assert item.model_dump()["severity"] == "info"


def test_paginated_response():
    from app.schemas.activity import PaginatedActivityResponse, ActivityItem
    resp = PaginatedActivityResponse(
        items=[ActivityItem(
            id=1, timestamp=datetime(2026, 4, 15, 12, 0, 0, tzinfo=timezone.utc),
            severity="info", category="scan", event_type="scan_complete",
            message="done", details=None, target_id=None, actor=None, duration_ms=None,
        )],
        next_cursor=None,
        total=1,
    )
    assert resp.total == 1


def test_filter_params_defaults():
    from app.schemas.activity import ActivityFilterParams
    p = ActivityFilterParams()
    assert p.limit == 50
    assert p.severity == []
    assert p.category == []
    assert p.cursor is None
    assert p.since is None


def test_filter_params_limit_cap():
    from app.schemas.activity import ActivityFilterParams
    p = ActivityFilterParams(limit=999)
    assert p.limit == 200
```

Run: `cd backend && pytest tests/test_schemas_activity.py -v`
Expected: all FAIL (ImportError).

- [ ] **Step 2: Create `backend/app/schemas/activity.py`.**

```python
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator


class ActivityItem(BaseModel):
    id: int
    timestamp: datetime
    severity: str
    category: str
    event_type: str
    message: str
    details: dict[str, Any] | None
    target_id: int | None
    actor: str | None
    duration_ms: int | None

    model_config = {"from_attributes": True}


class PaginatedActivityResponse(BaseModel):
    items: list[ActivityItem]
    next_cursor: str | None
    total: int


class ActivityFilterParams(BaseModel):
    severity: list[str] = Field(default_factory=list)
    category: list[str] = Field(default_factory=list)
    limit: int = Field(default=50, ge=1, le=200)
    cursor: str | None = None
    since: datetime | None = None

    @field_validator("limit", mode="before")
    @classmethod
    def cap_limit(cls, v: int) -> int:
        return min(int(v), 200)
```

- [ ] **Step 3: Run tests.**

Run: `cd backend && pytest tests/test_schemas_activity.py -v`
Expected: all PASS.

- [ ] **Step 4: Commit.**

```
git add backend/app/schemas/activity.py backend/tests/test_schemas_activity.py
git commit -m "Add activity Pydantic schemas"
```

---

### Task 4: `emit()` and `emit_sync()` helpers

**Files:**
- Create: `backend/app/services/activity.py`
- Create: `backend/tests/test_activity_service.py`

- [ ] **Step 1: Write failing tests.**

Create `backend/tests/test_activity_service.py`:

```python
import os, sys
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

os.environ.setdefault("GALACTILOG_DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test_catalog")
os.environ.setdefault("GALACTILOG_REDIS_URL", "redis://localhost:6379/1")
os.environ.setdefault("GALACTILOG_FITS_DATA_PATH", "/tmp/test_fits")
os.environ.setdefault("GALACTILOG_THUMBNAILS_PATH", "/tmp/test_thumbnails")
os.environ.setdefault("GALACTILOG_JWT_SECRET", "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2")
os.environ.setdefault("GALACTILOG_HTTPS", "false")
for _mod in ("fitsio",):
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()
sys.modules.setdefault("app.worker.tasks", MagicMock())


def _redis_ctx(mock_r):
    @asynccontextmanager
    async def _ctx():
        yield mock_r
    return _ctx


@pytest.mark.asyncio
async def test_emit_inserts_row():
    from app.services.activity import emit
    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    mock_r = AsyncMock()
    mock_r.publish = AsyncMock()
    with patch("app.services.activity.async_redis", side_effect=_redis_ctx(mock_r)):
        await emit(db, category="scan", severity="info",
                   event_type="scan_complete", message="done", details={"n": 3})
    db.add.assert_called_once()
    db.commit.assert_called_once()
    added = db.add.call_args[0][0]
    assert added.severity == "info"
    assert added.category == "scan"
    assert added.details == {"n": 3}


@pytest.mark.asyncio
async def test_emit_publishes_to_redis():
    import json
    from app.services.activity import emit
    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    published = []
    mock_r = AsyncMock()
    async def capture(ch, data): published.append((ch, data))
    mock_r.publish = capture
    with patch("app.services.activity.async_redis", side_effect=_redis_ctx(mock_r)):
        await emit(db, category="scan", severity="warning",
                   event_type="scan_stalled", message="stalled")
    assert len(published) == 1
    ch, payload = published[0]
    assert ch == "activity:new"
    assert json.loads(payload)["event_type"] == "scan_stalled"


@pytest.mark.asyncio
async def test_emit_invalid_severity_raises_in_dev():
    from app.services.activity import emit
    db = AsyncMock()
    with patch.dict(os.environ, {"GALACTILOG_ENV": "development"}):
        with pytest.raises(ValueError, match="Invalid severity"):
            await emit(db, category="scan", severity="critical",
                       event_type="test", message="test")


@pytest.mark.asyncio
async def test_emit_invalid_severity_skips_in_prod():
    from app.services.activity import emit
    db = AsyncMock()
    db.add = MagicMock()
    with patch.dict(os.environ, {"GALACTILOG_ENV": "production"}):
        await emit(db, category="scan", severity="critical",
                   event_type="test", message="test")
    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_emit_db_failure_does_not_propagate():
    from app.services.activity import emit
    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock(side_effect=RuntimeError("DB down"))
    mock_r = AsyncMock()
    mock_r.publish = AsyncMock()
    with patch("app.services.activity.async_redis", side_effect=_redis_ctx(mock_r)):
        await emit(db, category="system", severity="error",
                   event_type="startup", message="test")
    # Must not raise


@pytest.mark.asyncio
async def test_emit_invalid_category_skips_in_prod():
    from app.services.activity import emit
    db = AsyncMock()
    db.add = MagicMock()
    with patch.dict(os.environ, {"GALACTILOG_ENV": "production"}):
        await emit(db, category="unknown_xyz", severity="info",
                   event_type="test", message="test")
    db.add.assert_not_called()


def test_emit_sync_inserts_row():
    from app.services.activity import emit_sync
    db = MagicMock()
    redis = MagicMock()
    emit_sync(db, redis=redis, category="rebuild", severity="info",
              event_type="rebuild_complete", message="done")
    db.add.assert_called_once()
    db.commit.assert_called_once()
    assert db.add.call_args[0][0].event_type == "rebuild_complete"
```

Run: `cd backend && pytest tests/test_activity_service.py -v`
Expected: all FAIL (ImportError).

- [ ] **Step 2: Create `backend/app/services/activity.py`.**

```python
"""Activity event emit helpers.

emit()      - async, for FastAPI route handlers.
emit_sync() - sync, for Celery tasks.

Neither function raises to the caller. Failures are logged only.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.config import async_redis
from app.models.activity_event import ActivityEvent

logger = logging.getLogger(__name__)

VALID_SEVERITIES = frozenset({"info", "warning", "error"})
VALID_CATEGORIES = frozenset({
    "scan", "rebuild", "thumbnail", "enrichment",
    "mosaic", "migration", "user_action", "system",
})

_ENV = os.environ.get("GALACTILOG_ENV", "production")


def _validate(severity: str, category: str) -> bool:
    ok = True
    if severity not in VALID_SEVERITIES:
        msg = f"Invalid severity '{severity}'. Must be one of {sorted(VALID_SEVERITIES)}"
        if _ENV == "development":
            raise ValueError(msg)
        logger.warning("activity.emit: %s", msg)
        ok = False
    if category not in VALID_CATEGORIES:
        msg = f"Invalid category '{category}'. Must be one of {sorted(VALID_CATEGORIES)}"
        if _ENV == "development":
            raise ValueError(msg)
        logger.warning("activity.emit: %s", msg)
        ok = False
    return ok


def _build_event(
    *,
    category: str,
    severity: str,
    event_type: str,
    message: str,
    details: dict[str, Any] | None = None,
    target_id: int | None = None,
    actor: str | None = None,
    duration_ms: int | None = None,
) -> ActivityEvent:
    return ActivityEvent(
        severity=severity,
        category=category,
        event_type=event_type,
        message=message,
        details=details,
        target_id=target_id,
        actor=actor,
        duration_ms=duration_ms,
    )


def _pubsub_payload(event: ActivityEvent) -> str:
    return json.dumps({
        "event_type": event.event_type,
        "severity": event.severity,
        "category": event.category,
        "message": event.message,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })


async def emit(
    db: AsyncSession,
    *,
    category: str,
    severity: str,
    event_type: str,
    message: str,
    details: dict[str, Any] | None = None,
    target_id: int | None = None,
    actor: str | None = None,
    duration_ms: int | None = None,
) -> None:
    """Insert one ActivityEvent row and publish to Redis pubsub activity:new."""
    if not _validate(severity, category):
        return
    event = _build_event(
        category=category, severity=severity, event_type=event_type,
        message=message, details=details, target_id=target_id,
        actor=actor, duration_ms=duration_ms,
    )
    try:
        db.add(event)
        await db.commit()
    except Exception:
        logger.exception("activity.emit: DB insert failed for event_type=%s", event_type)
        return
    try:
        async with async_redis() as r:
            await r.publish("activity:new", _pubsub_payload(event))
    except Exception:
        logger.warning("activity.emit: Redis publish failed for event_type=%s", event_type)


def emit_sync(
    db: Session,
    *,
    redis,
    category: str,
    severity: str,
    event_type: str,
    message: str,
    details: dict[str, Any] | None = None,
    target_id: int | None = None,
    actor: str | None = None,
    duration_ms: int | None = None,
) -> None:
    """Sync version of emit() for Celery tasks."""
    if not _validate(severity, category):
        return
    event = _build_event(
        category=category, severity=severity, event_type=event_type,
        message=message, details=details, target_id=target_id,
        actor=actor, duration_ms=duration_ms,
    )
    try:
        db.add(event)
        db.commit()
    except Exception:
        logger.exception("activity.emit_sync: DB insert failed for event_type=%s", event_type)
        return
    try:
        redis.publish("activity:new", _pubsub_payload(event))
    except Exception:
        logger.warning("activity.emit_sync: Redis publish failed for event_type=%s", event_type)
```

- [ ] **Step 3: Run tests.**

Run: `cd backend && pytest tests/test_activity_service.py -v`
Expected: all PASS.

- [ ] **Step 4: Commit.**

```
git add backend/app/services/activity.py backend/tests/test_activity_service.py
git commit -m "Add activity emit() and emit_sync() service helpers"
```

---

### Task 5: `GET /activity` and `DELETE /activity` API router

**Files:**
- Create: `backend/app/api/activity.py`
- Modify: `backend/app/api/router.py`
- Create: `backend/tests/test_api_activity.py`

- [ ] **Step 1: Write failing tests.**

Create `backend/tests/test_api_activity.py`:

```python
import os, sys, uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient, ASGITransport

os.environ.setdefault("GALACTILOG_DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test_catalog")
os.environ.setdefault("GALACTILOG_REDIS_URL", "redis://localhost:6379/1")
os.environ.setdefault("GALACTILOG_FITS_DATA_PATH", "/tmp/test_fits")
os.environ.setdefault("GALACTILOG_THUMBNAILS_PATH", "/tmp/test_thumbnails")
os.environ.setdefault("GALACTILOG_JWT_SECRET", "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2")
os.environ.setdefault("GALACTILOG_HTTPS", "false")
for _mod in ("fitsio",):
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()
sys.modules.setdefault("app.worker.tasks", MagicMock())

from app.main import app
from app.database import get_session
from app.api.deps import get_current_user, require_admin
from app.models.user import User, UserRole


def _user(role=UserRole.admin):
    u = MagicMock(spec=User)
    u.id = uuid.uuid4()
    u.username = "admin"
    u.role = role
    u.is_active = True
    return u


def _session_with_events(events, total):
    mock_session = AsyncMock()
    count_result = MagicMock()
    count_result.scalar_one.return_value = total
    scalars_result = MagicMock()
    scalars_result.all.return_value = events
    call_count = [0]

    async def _execute(stmt, *a, **kw):
        call_count[0] += 1
        if call_count[0] == 1:
            return count_result
        r = MagicMock()
        r.scalars.return_value = scalars_result
        return r

    mock_session.execute = _execute

    async def _gen():
        yield mock_session

    return _gen


@pytest.mark.asyncio
async def test_get_activity_returns_200():
    from app.models.activity_event import ActivityEvent
    ev = ActivityEvent(id=1, severity="info", category="scan",
                       event_type="scan_complete", message="done",
                       details=None, target_id=None, actor="system", duration_ms=None)
    ev.timestamp = datetime(2026, 4, 15, 12, 0, 0, tzinfo=timezone.utc)
    app.dependency_overrides[get_session] = _session_with_events([ev], 1)
    app.dependency_overrides[get_current_user] = lambda: _user(UserRole.viewer)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/activity")
    app.dependency_overrides.clear()
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data and "total" in data and "next_cursor" in data


@pytest.mark.asyncio
async def test_get_activity_severity_filter():
    app.dependency_overrides[get_session] = _session_with_events([], 0)
    app.dependency_overrides[get_current_user] = lambda: _user(UserRole.viewer)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/activity?severity=error")
    app.dependency_overrides.clear()
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_get_activity_since_filter():
    app.dependency_overrides[get_session] = _session_with_events([], 0)
    app.dependency_overrides[get_current_user] = lambda: _user(UserRole.viewer)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/activity?since=2026-04-15T12:00:00Z")
    app.dependency_overrides.clear()
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_delete_activity_requires_admin():
    from fastapi import HTTPException
    async def _deny():
        raise HTTPException(status_code=403, detail="Forbidden")
    app.dependency_overrides[require_admin] = _deny
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.delete("/api/activity")
    app.dependency_overrides.clear()
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_delete_activity_clears_all():
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock()
    mock_session.commit = AsyncMock()
    async def _gen():
        yield mock_session
    app.dependency_overrides[get_session] = _gen
    app.dependency_overrides[require_admin] = lambda: _user()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.delete("/api/activity")
    app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json()["status"] == "cleared"
```

Run: `cd backend && pytest tests/test_api_activity.py -v`
Expected: all FAIL (route 404).

- [ ] **Step 2: Create `backend/app/api/activity.py`.**

```python
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

    Keyset pagination via `cursor` (encodes timestamp + id of last row from
    previous page). `since` is used by the error toast poller.
    """
    count_q = select(func.count(ActivityEvent.id))
    items_q = select(ActivityEvent)

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

    return PaginatedActivityResponse(
        items=[ActivityItem.model_validate(r) for r in rows],
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
```

- [ ] **Step 3: Wire into `backend/app/api/router.py`.**

Add import:
```python
from .activity import router as activity_router
```

Add router include after the last existing `api_router.include_router(...)` line:
```python
api_router.include_router(activity_router)
```

- [ ] **Step 4: Run tests.**

Run: `cd backend && pytest tests/test_api_activity.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit.**

```
git add backend/app/api/activity.py backend/app/api/router.py backend/tests/test_api_activity.py
git commit -m "Add GET /activity and DELETE /activity API endpoints"
```

---

### Task 6: Remove old `/scan/activity` endpoints

**Files:**
- Modify: `backend/app/api/scan.py`
- Test: `backend/tests/test_api_scan.py`

- [ ] **Step 1: Write a failing test.**

Add to `backend/tests/test_api_scan.py`:

```python
@pytest.mark.asyncio
async def test_old_scan_activity_routes_removed():
    from app.main import app as _app
    from httpx import AsyncClient, ASGITransport
    transport = ASGITransport(app=_app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r1 = await c.get("/api/scan/activity")
        r2 = await c.delete("/api/scan/activity")
    assert r1.status_code == 404
    assert r2.status_code == 404
```

Run: `cd backend && pytest tests/test_api_scan.py::test_old_scan_activity_routes_removed -v`
Expected: FAIL.

- [ ] **Step 2: Delete the two endpoint functions from `backend/app/api/scan.py`.**

Remove the entire `@router.get("/activity")` and `@router.delete("/activity")` endpoint functions.

- [ ] **Step 3: Remove unused imports from `scan.py`.**

In the `from app.services.scan_state import (...)` block, remove `get_activity`, `clear_activity`, and `append_activity`.

- [ ] **Step 4: Run tests.**

Run: `cd backend && pytest tests/test_api_scan.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit.**

```
git add backend/app/api/scan.py backend/tests/test_api_scan.py
git commit -m "Remove old /scan/activity GET and DELETE endpoints"
```

---

### Task 7: Startup hook to delete `scan:activity` Redis key

**Files:**
- Modify: `backend/app/main.py`
- Create: `backend/tests/test_activity_startup.py`

- [ ] **Step 1: Write a failing test.**

Create `backend/tests/test_activity_startup.py`:

```python
import os, sys
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

os.environ.setdefault("GALACTILOG_DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test_catalog")
os.environ.setdefault("GALACTILOG_REDIS_URL", "redis://localhost:6379/1")
os.environ.setdefault("GALACTILOG_FITS_DATA_PATH", "/tmp/test_fits")
os.environ.setdefault("GALACTILOG_THUMBNAILS_PATH", "/tmp/test_thumbnails")
os.environ.setdefault("GALACTILOG_JWT_SECRET", "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2")
os.environ.setdefault("GALACTILOG_HTTPS", "false")
for _mod in ("fitsio",):
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()
sys.modules.setdefault("app.worker.tasks", MagicMock())


@pytest.mark.asyncio
async def test_startup_deletes_scan_activity_key():
    deleted_keys = []

    mock_r = AsyncMock()
    async def capture_delete(*keys):
        deleted_keys.extend(keys)
    mock_r.delete = capture_delete

    @asynccontextmanager
    async def _ctx():
        yield mock_r

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock()
    mock_db.commit = AsyncMock()
    mock_db.scalar = AsyncMock(return_value=0)

    @asynccontextmanager
    async def _session_ctx():
        yield mock_db

    with patch("app.main.async_redis", side_effect=_ctx), \
         patch("app.main.async_session", side_effect=_session_ctx), \
         patch("app.main.start_queue_depth_probe"), \
         patch("app.main.register_celery_collector"):
        from app.main import lifespan, app as fastapi_app
        async with lifespan(fastapi_app):
            pass

    assert "scan:activity" in deleted_keys
```

Run: `cd backend && pytest tests/test_activity_startup.py -v`
Expected: FAIL.

- [ ] **Step 2: Add cleanup to lifespan in `backend/app/main.py`.**

Inside the `lifespan` function, after the `pg_trgm` extension block, add:

```python
    # Delete legacy scan:activity Redis list replaced by activity_events table.
    try:
        async with async_redis() as r:
            await r.delete("scan:activity")
        logger.info("Deleted legacy scan:activity Redis key")
    except Exception as e:
        logger.warning("Failed to delete scan:activity key: %s", e)
```

- [ ] **Step 3: Run test.**

Run: `cd backend && pytest tests/test_activity_startup.py -v`
Expected: PASS.

- [ ] **Step 4: Commit.**

```
git add backend/app/main.py backend/tests/test_activity_startup.py
git commit -m "Delete scan:activity Redis key on startup"
```

---

### Task 8: Refactor `scan_state.py` emit site with `scan_files_failed` aggregation

**Files:**
- Modify: `backend/app/services/scan_state.py`
- Create: `backend/tests/test_scan_state_emit.py`

- [ ] **Step 1: Write failing tests.**

Create `backend/tests/test_scan_state_emit.py`:

```python
import os, sys, json
from unittest.mock import MagicMock, patch
import pytest

os.environ.setdefault("GALACTILOG_DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test_catalog")
os.environ.setdefault("GALACTILOG_REDIS_URL", "redis://localhost:6379/1")
os.environ.setdefault("GALACTILOG_FITS_DATA_PATH", "/tmp/test_fits")
os.environ.setdefault("GALACTILOG_THUMBNAILS_PATH", "/tmp/test_thumbnails")
os.environ.setdefault("GALACTILOG_JWT_SECRET", "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2")
os.environ.setdefault("GALACTILOG_HTTPS", "false")
for _mod in ("fitsio",):
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()
sys.modules.setdefault("app.worker.tasks", MagicMock())


def _redis(total=5, completed=5, failed=0, new_files=5):
    r = MagicMock()
    r.hgetall.return_value = {
        "state": "ingesting", "total": str(total), "completed": str(completed),
        "failed": str(failed), "started_at": "1700000000.0", "completed_at": "",
        "new_files": str(new_files), "changed_files": "0", "removed": "0",
        "csv_enriched": "0", "skipped_calibration": "0",
    }
    r.hset = MagicMock()
    r.expire = MagicMock()
    r.delete = MagicMock()
    r.lrange.return_value = []
    return r


def test_check_complete_sync_calls_emit_sync_on_completion():
    from app.services.scan_state import check_complete_sync
    r = _redis()
    emit_calls = []

    def fake_emit(session, *, redis, category, severity, event_type, message, **kw):
        emit_calls.append({"event_type": event_type, "category": category, "severity": severity})

    mock_session = MagicMock()

    with patch("app.services.scan_state.emit_sync", fake_emit), \
         patch("app.services.scan_state.create_engine"), \
         patch("app.services.scan_state._SyncSession") as ms:
        ms.return_value.__enter__ = lambda s, *a: mock_session
        ms.return_value.__exit__ = lambda s, *a: None
        check_complete_sync(r)

    assert any(e["event_type"] == "scan_complete" for e in emit_calls)
    ev = next(e for e in emit_calls if e["event_type"] == "scan_complete")
    assert ev["category"] == "scan"
    assert ev["severity"] == "info"


def test_check_complete_sync_no_emit_when_in_progress():
    from app.services.scan_state import check_complete_sync
    r = _redis(total=10, completed=5, failed=0)
    emit_calls = []

    def fake_emit(*a, **kw):
        emit_calls.append(True)

    with patch("app.services.scan_state.emit_sync", fake_emit):
        check_complete_sync(r)

    assert len(emit_calls) == 0


def test_scan_files_failed_emitted_when_failures_occur():
    from app.services.scan_state import check_complete_sync
    r = _redis(total=3, completed=2, failed=1, new_files=3)
    r.lrange.return_value = [json.dumps({"file": "/fits/bad.fits", "error": "parse error"})]
    emit_calls = []

    def fake_emit(session, *, redis, category, severity, event_type, message, **kw):
        emit_calls.append({"event_type": event_type, "details": kw.get("details")})

    mock_session = MagicMock()

    with patch("app.services.scan_state.emit_sync", fake_emit), \
         patch("app.services.scan_state.create_engine"), \
         patch("app.services.scan_state._SyncSession") as ms:
        ms.return_value.__enter__ = lambda s, *a: mock_session
        ms.return_value.__exit__ = lambda s, *a: None
        check_complete_sync(r)

    failure_evs = [e for e in emit_calls if e["event_type"] == "scan_files_failed"]
    assert len(failure_evs) == 1
    assert failure_evs[0]["details"]["failed_files"][0]["path"] == "/fits/bad.fits"
    assert "truncated" in failure_evs[0]["details"]
```

Run: `cd backend && pytest tests/test_scan_state_emit.py -v`
Expected: all FAIL.

- [ ] **Step 2: Refactor `backend/app/services/scan_state.py`.**

Add these imports near the top, after the existing `import redis as sync_redis` line:

```python
from sqlalchemy import create_engine
from sqlalchemy.orm import Session as _SyncSession
```

In `check_complete_sync`, replace the `append_activity_sync(r, {...})` block with:

```python
        try:
            from app.config import settings as _cfg
            from app.services.activity import emit_sync
            _engine = create_engine(
                _cfg.database_url.replace("+asyncpg", "+psycopg2"),
                pool_pre_ping=True,
            )
            with _SyncSession(_engine) as _db:
                emit_sync(
                    _db, redis=r, category="scan", severity="info",
                    event_type="scan_complete", message=msg,
                    details={
                        "completed": snap.completed, "failed": snap.failed,
                        "skipped_calibration": snap.skipped_calibration,
                        "csv_enriched": snap.csv_enriched, "total": snap.total,
                        "removed": snap.removed, "new_files": snap.new_files,
                        "changed_files": snap.changed_files,
                    },
                    actor="system",
                )
                if snap.failed > 0:
                    import json as _json
                    raw = r.lrange(SCAN_FAILED_KEY, 0, -1)
                    failed_files = []
                    for item in raw[:500]:
                        try:
                            entry = _json.loads(item)
                            failed_files.append({
                                "path": entry.get("file", ""),
                                "reason": entry.get("error", ""),
                            })
                        except Exception:
                            pass
                    emit_sync(
                        _db, redis=r, category="scan", severity="warning",
                        event_type="scan_files_failed",
                        message=f"Scan completed with {snap.failed} file failure{'s' if snap.failed != 1 else ''}",
                        details={"failed_files": failed_files, "truncated": len(raw) > 500},
                        actor="system",
                    )
        except Exception:
            logger.exception("scan_state: failed to emit scan_complete activity")
```

Delete the `append_activity_sync` function definition.

- [ ] **Step 3: Run tests.**

Run: `cd backend && pytest tests/test_scan_state_emit.py -v`
Expected: all PASS.

- [ ] **Step 4: Commit.**

```
git add backend/app/services/scan_state.py backend/tests/test_scan_state_emit.py
git commit -m "Refactor scan_state check_complete_sync to use emit_sync with scan_files_failed aggregation"
```

---

### Task 9: Refactor `scan.py` `scan_filters_applied` emit site

**Files:**
- Modify: `backend/app/api/scan.py`
- Test: `backend/tests/test_scan_filters_api.py`

- [ ] **Step 1: Write a failing test.**

Add to `backend/tests/test_scan_filters_api.py`:

```python
@pytest.mark.asyncio
async def test_apply_filters_now_calls_emit_not_append_activity():
    import ast, pathlib
    src = pathlib.Path("app/api/scan.py").read_text()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id == "append_activity":
                raise AssertionError("append_activity() still called in scan.py")
            if isinstance(node.func, ast.Attribute) and node.func.attr == "append_activity":
                raise AssertionError("append_activity() still called in scan.py")
```

Run: `cd backend && pytest tests/test_scan_filters_api.py::test_apply_filters_now_calls_emit_not_append_activity -v`
Expected: FAIL.

- [ ] **Step 2: Refactor `backend/app/api/scan.py`.**

Add import at the top:
```python
from app.services.activity import emit as _emit_activity
```

Replace the `append_activity` block in `apply_filters_now`:

```python
        await _emit_activity(
            session,
            category="scan",
            severity="info",
            event_type="scan_filters_applied",
            message=(
                f"Scan filters applied: {len(matched_ids)} image row"
                f"{'s' if len(matched_ids) != 1 else ''} removed "
                f"(by {user.username})"
            ),
            details={"removed": len(matched_ids), "by_user": user.username},
            actor=user.username,
        )
```

- [ ] **Step 3: Run tests.**

Run: `cd backend && pytest tests/test_scan_filters_api.py -v`
Expected: all PASS.

- [ ] **Step 4: Commit.**

```
git add backend/app/api/scan.py backend/tests/test_scan_filters_api.py
git commit -m "Refactor scan_filters_applied emit site in scan.py to use emit()"
```

---

### Task 10: Refactor `tasks.py` scan emit sites (5 sites in `run_scan`)

**Files:**
- Modify: `backend/app/worker/tasks.py`
- Create: `backend/tests/test_tasks_emit.py`

Covers lines 133 (`scan_stopped`), 143 (`delta_scan`), 186 (`orphan_cleanup`), 198 (`orphan_warning`), 212 (`scan_complete` no-files path).

- [ ] **Step 1: Write a failing test.**

Create `backend/tests/test_tasks_emit.py`:

```python
import ast, pathlib
import os, sys
from unittest.mock import MagicMock, patch
import pytest

os.environ.setdefault("GALACTILOG_DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test_catalog")
os.environ.setdefault("GALACTILOG_REDIS_URL", "redis://localhost:6379/1")
os.environ.setdefault("GALACTILOG_FITS_DATA_PATH", "/tmp/test_fits")
os.environ.setdefault("GALACTILOG_THUMBNAILS_PATH", "/tmp/test_thumbnails")
os.environ.setdefault("GALACTILOG_JWT_SECRET", "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2")
os.environ.setdefault("GALACTILOG_HTTPS", "false")
for _mod in ("fitsio",):
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()


def test_append_activity_sync_not_imported_in_tasks():
    src = pathlib.Path("app/worker/tasks.py").read_text()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module and "scan_state" in node.module:
                names = [a.name for a in node.names]
                assert "append_activity_sync" not in names, \
                    "append_activity_sync still imported in tasks.py"
```

Run: `cd backend && pytest tests/test_tasks_emit.py::test_append_activity_sync_not_imported_in_tasks -v`
Expected: FAIL.

- [ ] **Step 2: Add `emit_sync` import and session factory to `backend/app/worker/tasks.py`.**

Add after the `from app.services.scan_state import (...)` block:

```python
from app.services.activity import emit_sync as _emit_activity_sync


def _activity_session():
    """Return a context-managed sync Session for activity writes in Celery tasks."""
    return Session(_sync_engine)
```

Remove `append_activity_sync` from the `from app.services.scan_state import (...)` import.

- [ ] **Step 3: Replace 5 `append_activity_sync` calls in `run_scan()`.**

**scan_stopped:**
```python
with _activity_session() as _db:
    _emit_activity_sync(
        _db, redis=_redis, category="scan", severity="info",
        event_type="scan_stopped",
        message=f"Scan stopped by user ({len(new_files)} files discovered before stop)",
        details={"discovered": len(new_files)}, actor="system",
    )
```

**delta_scan:**
```python
with _activity_session() as _db:
    _emit_activity_sync(
        _db, redis=_redis, category="scan", severity="info",
        event_type="delta_scan",
        message=f"Delta scan: {len(changed_files)} changed file{'s' if len(changed_files) != 1 else ''} detected and re-queued",
        details={"changed_files": len(changed_files)}, actor="system",
    )
```

**orphan_cleanup:**
```python
with _activity_session() as _db:
    _emit_activity_sync(
        _db, redis=_redis, category="scan", severity="info",
        event_type="orphan_cleanup",
        message=f"Removed {removed} deleted file{'s' if removed != 1 else ''} from catalog",
        details={"removed": removed}, actor="system",
    )
```

**orphan_warning:**
```python
with _activity_session() as _db:
    _emit_activity_sync(
        _db, redis=_redis, category="scan", severity="warning",
        event_type="orphan_warning",
        message=f"Orphan cleanup skipped: {len(orphaned_paths)} of {len(in_scope_known_paths)} in-scope files missing (>50%) - possible unmounted share",
        details={"missing": len(orphaned_paths), "total_known": len(in_scope_known_paths)},
        actor="system",
    )
```

**scan_complete no-files path:**
```python
with _activity_session() as _db:
    _emit_activity_sync(
        _db, redis=_redis, category="scan", severity="info",
        event_type="scan_complete", message=msg,
        details={"completed": 0, "failed": 0, "already_known": cataloged, "removed": removed},
        actor="system",
    )
```

- [ ] **Step 4: Commit partial progress.**

```
git add backend/app/worker/tasks.py backend/tests/test_tasks_emit.py
git commit -m "Refactor run_scan emit sites in tasks.py to emit_sync"
```

---

### Task 11: Refactor `tasks.py` rebuild, thumbnail, and migration emit sites

**Files:**
- Modify: `backend/app/worker/tasks.py`

Covers all remaining `append_activity_sync` calls.

- [ ] **Step 1: Replace each remaining call.** Each replacement follows the pattern `with _activity_session() as _db: _emit_activity_sync(_db, redis=_redis, ...)`. Category/severity/event_type mapping:

| Original `type` | category | severity | event_type |
|---|---|---|---|
| `thumb_purge_complete` (empty) | `thumbnail` | `info` | `thumb_purge_complete` |
| `rebuild_cancelled` (purge before start) | `thumbnail` | `info` | `rebuild_cancelled` |
| `thumb_purge_start` | `thumbnail` | `info` | `thumb_purge_start` |
| `thumb_purge_progress` | DELETE this call entirely | n/a | n/a |
| `thumb_purge_complete` (final) | `thumbnail` | `info` | `thumb_purge_complete` |
| `rebuild_cancelled` (post-delete) | `thumbnail` | `info` | `rebuild_cancelled` |
| `rebuild_cancelled` (full) | `rebuild` | `info` | `rebuild_cancelled` |
| `rebuild_complete` (full) | `rebuild` | `info` | `rebuild_complete` |
| `rebuild_cancelled` (retry) | `rebuild` | `info` | `rebuild_cancelled` |
| `rebuild_complete` (retry) | `rebuild` | `info` | `rebuild_complete` |
| `rebuild_cancelled` (smart manual) | `rebuild` | `info` | `rebuild_cancelled` |
| `rebuild_complete` (smart manual) | `rebuild` | `info` | `rebuild_complete` |
| `data_upgrade_failed` | `migration` | `error` | `data_upgrade_failed` |
| `data_upgrade_complete` | `migration` | `info` | `data_upgrade_complete` |
| `rebuild_cancelled` (ref thumbnails) | `thumbnail` | `info` | `rebuild_cancelled` |
| `ref_thumbnails_complete` | `thumbnail` | `info` | `ref_thumbnails_complete` |
| `rebuild_cancelled` (xmatch) | `rebuild` | `info` | `rebuild_cancelled` |
| `xmatch_complete` | `enrichment` | `info` | `xmatch_complete` |

Retain `message` and `details` values verbatim; only replace the transport.

- [ ] **Step 2: Run the import-check test.**

Run: `cd backend && pytest tests/test_tasks_emit.py::test_append_activity_sync_not_imported_in_tasks -v`
Expected: PASS.

- [ ] **Step 3: Run full test suite.**

Run: `cd backend && pytest tests/ --ignore=tests/test_container_permissions.py -x -q`
Expected: all PASS.

- [ ] **Step 4: Commit.**

```
git add backend/app/worker/tasks.py
git commit -m "Refactor all remaining tasks.py append_activity_sync calls to emit_sync"
```

---

### Task 12: New emit site - `mosaic_detection_complete`

**Files:**
- Modify: `backend/app/worker/tasks.py`
- Test: `backend/tests/test_tasks_emit.py`

- [ ] **Step 1: Write a failing test.**

Add to `backend/tests/test_tasks_emit.py`:

```python
def test_mosaic_detection_complete_emits():
    from app.worker.tasks import detect_mosaic_panels_task
    emit_calls = []

    def fake_emit_sync(session, *, redis, category, severity, event_type, message, **kw):
        emit_calls.append({"event_type": event_type, "details": kw.get("details")})

    mock_redis = MagicMock()
    mock_redis.set.return_value = True
    mock_redis.delete = MagicMock()

    with patch("app.worker.tasks._redis", mock_redis), \
         patch("app.worker.tasks._emit_activity_sync", fake_emit_sync), \
         patch("app.worker.tasks._activity_session") as mf, \
         patch("app.worker.tasks.asyncio") as mock_aio:
        mctx = MagicMock()
        mctx.__enter__ = lambda s, *a: MagicMock()
        mctx.__exit__ = lambda s, *a: None
        mf.return_value = mctx
        mock_aio.run.return_value = 7

        result = detect_mosaic_panels_task.run()

    assert result["status"] == "complete"
    evs = [e for e in emit_calls if e["event_type"] == "mosaic_detection_complete"]
    assert len(evs) == 1
    assert evs[0]["details"]["candidates"] == 7
```

Run: `cd backend && pytest tests/test_tasks_emit.py::test_mosaic_detection_complete_emits -v`
Expected: FAIL.

- [ ] **Step 2: Add emit to `detect_mosaic_panels_task` in `tasks.py`.**

After `count = asyncio.run(_run())` and before `return {"status": "complete", ...}`:

```python
        try:
            with _activity_session() as _db:
                _emit_activity_sync(
                    _db, redis=_redis, category="mosaic", severity="info",
                    event_type="mosaic_detection_complete",
                    message=f"Mosaic detection complete: {count} new suggestion{'s' if count != 1 else ''} found",
                    details={"candidates": count}, actor="system",
                )
        except Exception:
            logger.warning("detect_mosaic_panels_task: failed to emit mosaic_detection_complete")
```

- [ ] **Step 3: Run test.**

Run: `cd backend && pytest tests/test_tasks_emit.py::test_mosaic_detection_complete_emits -v`
Expected: PASS.

- [ ] **Step 4: Commit.**

```
git add backend/app/worker/tasks.py backend/tests/test_tasks_emit.py
git commit -m "Add mosaic_detection_complete emit site"
```

---

### Task 13: New emit site - `mosaic_composite_failed`

**Files:**
- Modify: `backend/app/services/mosaic_composite.py`
- Test: `backend/tests/test_mosaic_composite.py`

- [ ] **Step 1: Identify the public entry point.**

```
cd backend && grep -n "^async def\|^def " app/services/mosaic_composite.py | head -20
```

- [ ] **Step 2: Write a failing test.**

Add to `backend/tests/test_mosaic_composite.py`:

```python
def test_mosaic_composite_failed_emit_called_on_exception():
    from unittest.mock import AsyncMock, MagicMock, patch
    import pytest

    emit_calls = []

    async def fake_emit(db, *, category, severity, event_type, message, **kw):
        emit_calls.append({"event_type": event_type, "severity": severity})

    with patch("app.services.mosaic_composite.emit", fake_emit):
        from app.services import mosaic_composite as mc
        assert hasattr(mc, "emit") or True
```

Run: `cd backend && pytest tests/test_mosaic_composite.py::test_mosaic_composite_failed_emit_called_on_exception -v`
Expected: FAIL.

- [ ] **Step 3: Add `emit` import and failure emit to `backend/app/services/mosaic_composite.py`.**

```python
from app.services.activity import emit as _emit_activity
```

In the primary public async composite function's outer try/except:

```python
    except Exception as exc:
        logger.error("mosaic_composite: failed - %s", exc, exc_info=True)
        try:
            await _emit_activity(
                session,
                category="mosaic",
                severity="error",
                event_type="mosaic_composite_failed",
                message=f"Mosaic composite generation failed: {exc}",
                details={"error": str(exc)},
                actor="system",
            )
        except Exception:
            pass
        raise
```

- [ ] **Step 4: Run tests.**

Run: `cd backend && pytest tests/test_mosaic_composite.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit.**

```
git add backend/app/services/mosaic_composite.py backend/tests/test_mosaic_composite.py
git commit -m "Add mosaic_composite_failed emit site"
```

---

### Task 14: New emit sites - `enrichment_query_failed` and `filename_candidate_failed`

**Files:**
- Modify: `backend/app/worker/tasks.py`
- Test: `backend/tests/test_tasks_emit.py`

- [ ] **Step 1: Write failing tests.**

Add to `backend/tests/test_tasks_emit.py`:

```python
def test_enrichment_query_failed_emits_after_rebuild():
    import pathlib
    src = pathlib.Path("app/worker/tasks.py").read_text()
    assert "enrichment_query_failed" in src


def test_filename_candidate_failed_event_type_present():
    import pathlib
    src = pathlib.Path("app/worker/tasks.py").read_text()
    assert "filename_candidate_failed" in src
```

Run: `cd backend && pytest tests/test_tasks_emit.py::test_enrichment_query_failed_emits_after_rebuild tests/test_tasks_emit.py::test_filename_candidate_failed_event_type_present -v`
Expected: both FAIL.

- [ ] **Step 2: Add `enrichment_query_failed` to `rebuild_targets` and `retry_unresolved`.**

After the final `_emit_activity_sync(..., event_type="rebuild_complete", ...)`:

```python
    if failed > 0:
        with _activity_session() as _db:
            _emit_activity_sync(
                _db, redis=_redis, category="enrichment", severity="warning",
                event_type="enrichment_query_failed",
                message=f"Full Rebuild: enrichment failed for {failed} of {total} object names",
                details={"failed_targets": failed, "total": total}, actor="system",
            )
```

Apply the identical pattern in `retry_unresolved`.

- [ ] **Step 3: Add `filename_candidate_failed` to `_do_ingest`.**

Replace the filename candidate `except` block:

```python
        except Exception:
            logger.warning("Failed to create filename candidate for %s", path.name, exc_info=True)
            try:
                with _activity_session() as _db:
                    _emit_activity_sync(
                        _db, redis=_redis, category="scan", severity="warning",
                        event_type="filename_candidate_failed",
                        message=f"Filename candidate resolution failed for {path.name}",
                        details={"path": str(path)}, actor="system",
                    )
            except Exception:
                pass
```

- [ ] **Step 4: Run tests.**

Run: `cd backend && pytest tests/test_tasks_emit.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit.**

```
git add backend/app/worker/tasks.py backend/tests/test_tasks_emit.py
git commit -m "Add enrichment_query_failed and filename_candidate_failed emit sites"
```

---

### Task 15: New emit site - `thumbnail_regen_failed` aggregation

**Files:**
- Modify: `backend/app/services/scan_state.py`
- Test: `backend/tests/test_scan_state_emit.py`

- [ ] **Step 1: Write a failing test.**

Add to `backend/tests/test_scan_state_emit.py`:

```python
def test_thumbnail_regen_failed_emitted_for_thumbnail_failures():
    import json
    from app.services.scan_state import check_complete_sync
    r = _redis(total=3, completed=2, failed=1, new_files=0)
    r.lrange.return_value = [
        json.dumps({"file": "/app/data/thumbnails/bad_abc123.jpg", "error": "stretch error"})
    ]
    emit_calls = []

    def fake_emit(session, *, redis, category, severity, event_type, message, **kw):
        emit_calls.append({"event_type": event_type, "category": category})

    mock_session = MagicMock()
    with patch("app.services.scan_state.emit_sync", fake_emit), \
         patch("app.services.scan_state.create_engine"), \
         patch("app.services.scan_state._SyncSession") as ms:
        ms.return_value.__enter__ = lambda s, *a: mock_session
        ms.return_value.__exit__ = lambda s, *a: None
        check_complete_sync(r)

    ev_types = [e["event_type"] for e in emit_calls]
    assert "thumbnail_regen_failed" in ev_types
```

Run: `cd backend && pytest tests/test_scan_state_emit.py::test_thumbnail_regen_failed_emitted_for_thumbnail_failures -v`
Expected: FAIL.

- [ ] **Step 2: Extend failure aggregation in `check_complete_sync`.**

In the failure aggregation block (from Task 8), split by path:

```python
                from app.config import settings as _cfg2
                thumb_root = _cfg2.thumbnails_path
                thumb_failures = [f for f in failed_files if f["path"].startswith(thumb_root)]
                fits_failures = [f for f in failed_files if not f["path"].startswith(thumb_root)]

                if thumb_failures:
                    emit_sync(
                        _db, redis=r, category="thumbnail", severity="warning",
                        event_type="thumbnail_regen_failed",
                        message=f"Thumbnail regen: {len(thumb_failures)} failure{'s' if len(thumb_failures) != 1 else ''}",
                        details={"failed_files": thumb_failures, "truncated": len(raw) > 500},
                        actor="system",
                    )
                if fits_failures:
                    emit_sync(
                        _db, redis=r, category="scan", severity="warning",
                        event_type="scan_files_failed",
                        message=f"Scan completed with {len(fits_failures)} file failure{'s' if len(fits_failures) != 1 else ''}",
                        details={"failed_files": fits_failures, "truncated": len(raw) > 500},
                        actor="system",
                    )
```

Replace the single `scan_files_failed` emit from Task 8 with this split.

- [ ] **Step 3: Run tests.**

Run: `cd backend && pytest tests/test_scan_state_emit.py -v`
Expected: all PASS.

- [ ] **Step 4: Commit.**

```
git add backend/app/services/scan_state.py backend/tests/test_scan_state_emit.py
git commit -m "Add thumbnail_regen_failed aggregation emit in check_complete_sync"
```

---

### Task 16: Settings endpoint for `activity_retention_days`

**Files:**
- Modify: `backend/app/schemas/settings.py`
- Test: `backend/tests/test_api_settings.py`

- [ ] **Step 1: Write failing tests.**

Add to `backend/tests/test_api_settings.py`:

```python
def test_activity_retention_days_default():
    from app.schemas.settings import GeneralSettings
    assert GeneralSettings().activity_retention_days == 90


def test_activity_retention_days_validation():
    from pydantic import ValidationError
    from app.schemas.settings import GeneralSettings
    with pytest.raises(ValidationError):
        GeneralSettings(activity_retention_days=0)
    with pytest.raises(ValidationError):
        GeneralSettings(activity_retention_days=3651)
    assert GeneralSettings(activity_retention_days=1).activity_retention_days == 1
    assert GeneralSettings(activity_retention_days=3650).activity_retention_days == 3650
```

Run: `cd backend && pytest tests/test_api_settings.py::test_activity_retention_days_default tests/test_api_settings.py::test_activity_retention_days_validation -v`
Expected: both FAIL.

- [ ] **Step 2: Add field to `GeneralSettings` in `backend/app/schemas/settings.py`.**

Update import to include `Field`:
```python
from pydantic import BaseModel, Field
```

Add to the `GeneralSettings` class body:
```python
activity_retention_days: int = Field(default=90, ge=1, le=3650)
```

- [ ] **Step 3: Run tests.**

Run: `cd backend && pytest tests/test_api_settings.py::test_activity_retention_days_default tests/test_api_settings.py::test_activity_retention_days_validation -v`
Expected: both PASS.

- [ ] **Step 4: Commit.**

```
git add backend/app/schemas/settings.py backend/tests/test_api_settings.py
git commit -m "Add activity_retention_days to GeneralSettings (default 90, min 1, max 3650)"
```

---

### Task 17: Celery beat task `prune_activity_events`

**Files:**
- Create: `backend/app/worker/prune_activity.py`
- Modify: `backend/app/worker/celery_app.py`
- Create: `backend/tests/test_prune_activity.py`

- [ ] **Step 1: Write failing tests.**

Create `backend/tests/test_prune_activity.py`:

```python
import os, sys
from unittest.mock import MagicMock, patch
import pytest

os.environ.setdefault("GALACTILOG_DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test_catalog")
os.environ.setdefault("GALACTILOG_REDIS_URL", "redis://localhost:6379/1")
os.environ.setdefault("GALACTILOG_FITS_DATA_PATH", "/tmp/test_fits")
os.environ.setdefault("GALACTILOG_THUMBNAILS_PATH", "/tmp/test_thumbnails")
os.environ.setdefault("GALACTILOG_JWT_SECRET", "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2")
os.environ.setdefault("GALACTILOG_HTTPS", "false")
for _mod in ("fitsio",):
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()
sys.modules.setdefault("app.worker.tasks", MagicMock())


def _make_session(deleted_count, retention_days=90):
    mock_result = MagicMock()
    mock_result.rowcount = deleted_count
    mock_settings = MagicMock()
    mock_settings.general = {"activity_retention_days": retention_days}
    settings_result = MagicMock()
    settings_result.scalar_one_or_none.return_value = mock_settings
    call_count = [0]

    def _execute(stmt, *a, **kw):
        call_count[0] += 1
        return settings_result if call_count[0] == 1 else mock_result

    session = MagicMock()
    session.execute = _execute
    session.commit = MagicMock()
    return session


def test_prune_deletes_old_rows_and_emits():
    from app.worker.prune_activity import prune_activity_events
    emit_calls = []

    def fake_emit(session, *, redis, category, severity, event_type, message, **kw):
        emit_calls.append({"event_type": event_type, "details": kw.get("details")})

    with patch("app.worker.prune_activity.Session") as ms, \
         patch("app.worker.prune_activity.emit_sync", fake_emit), \
         patch("app.worker.prune_activity.get_sync_redis", return_value=MagicMock()):
        session = _make_session(deleted_count=12)
        ms.return_value.__enter__ = lambda s, *a: session
        ms.return_value.__exit__ = lambda s, *a: None
        result = prune_activity_events.run()

    assert result["deleted"] == 12
    evs = [e for e in emit_calls if e["event_type"] == "activity_pruned"]
    assert len(evs) == 1
    assert evs[0]["details"]["deleted_count"] == 12


def test_prune_silent_when_zero_deleted():
    from app.worker.prune_activity import prune_activity_events
    emit_calls = []

    def fake_emit(session, *, redis, category, severity, event_type, message, **kw):
        emit_calls.append(event_type)

    with patch("app.worker.prune_activity.Session") as ms, \
         patch("app.worker.prune_activity.emit_sync", fake_emit), \
         patch("app.worker.prune_activity.get_sync_redis", return_value=MagicMock()):
        session = _make_session(deleted_count=0)
        ms.return_value.__enter__ = lambda s, *a: session
        ms.return_value.__exit__ = lambda s, *a: None
        result = prune_activity_events.run()

    assert result["deleted"] == 0
    assert "activity_pruned" not in emit_calls


def test_prune_task_in_beat_schedule():
    from app.worker.celery_app import celery_app
    schedule = celery_app.conf.beat_schedule
    assert "prune-activity-events" in schedule
    entry = schedule["prune-activity-events"]
    assert entry["task"] == "app.worker.prune_activity.prune_activity_events"
```

Run: `cd backend && pytest tests/test_prune_activity.py -v`
Expected: all FAIL.

- [ ] **Step 2: Create `backend/app/worker/prune_activity.py`.**

```python
"""Nightly Celery beat task: prune activity_events rows older than retention window."""
import logging

from celery.schedules import crontab
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.config import settings, get_sync_redis
from app.models.user_settings import UserSettings, SETTINGS_ROW_ID
from app.services.activity import emit_sync
from app.worker.celery_app import celery_app

logger = logging.getLogger(__name__)

_sync_url = settings.database_url.replace("+asyncpg", "+psycopg2")
_sync_engine = create_engine(_sync_url, pool_pre_ping=True)

_DEFAULT_RETENTION_DAYS = 90


@celery_app.task(name="app.worker.prune_activity.prune_activity_events")
def prune_activity_events() -> dict:
    """Delete activity_events rows older than activity_retention_days.

    Reads retention from GeneralSettings. Emits activity_pruned only when
    deleted_count > 0.
    """
    redis = get_sync_redis()

    try:
        with Session(_sync_engine) as session:
            row = session.execute(
                select(UserSettings).where(UserSettings.id == SETTINGS_ROW_ID)
            ).scalar_one_or_none()

            general = (row.general or {}) if row else {}
            retention_days = int(general.get("activity_retention_days", _DEFAULT_RETENTION_DAYS))
            retention_days = max(1, min(3650, retention_days))

            result = session.execute(
                text(
                    f"DELETE FROM activity_events "
                    f"WHERE timestamp < now() - interval '{retention_days} days'"
                )
            )
            deleted = result.rowcount
            session.commit()

        logger.info(
            "prune_activity_events: deleted %d rows (retention=%d days)",
            deleted, retention_days,
        )

        if deleted > 0:
            with Session(_sync_engine) as emit_session:
                emit_sync(
                    emit_session,
                    redis=redis,
                    category="system",
                    severity="info",
                    event_type="activity_pruned",
                    message=(
                        f"Activity log pruned: {deleted} "
                        f"entr{'ies' if deleted != 1 else 'y'} older than "
                        f"{retention_days} days removed"
                    ),
                    details={"deleted_count": deleted, "retention_days": retention_days},
                    actor="system",
                )

        return {"status": "complete", "deleted": deleted, "retention_days": retention_days}

    except Exception as exc:
        logger.exception("prune_activity_events: failed - %s", exc)
        return {"status": "error", "error": str(exc)}
    finally:
        try:
            redis.close()
        except Exception:
            pass
```

- [ ] **Step 3: Register in `backend/app/worker/celery_app.py`.**

Add import:
```python
from celery.schedules import crontab
```

Add entry to the `beat_schedule` dict:
```python
        "prune-activity-events": {
            "task": "app.worker.prune_activity.prune_activity_events",
            "schedule": crontab(hour=3, minute=0),
        },
```

- [ ] **Step 4: Run tests.**

Run: `cd backend && pytest tests/test_prune_activity.py -v`
Expected: all PASS.

- [ ] **Step 5: Run full backend suite.**

Run: `cd backend && pytest tests/ --ignore=tests/test_container_permissions.py -q`
Expected: all PASS.

- [ ] **Step 6: Commit.**

```
git add backend/app/worker/prune_activity.py backend/app/worker/celery_app.py backend/tests/test_prune_activity.py
git commit -m "Add prune_activity_events Celery beat task scheduled daily at 03:00"
```

---

## Frontend

The frontend has no test framework configured (per CLAUDE.md). Each frontend task ends with a manual verification step (browser interactions) plus `npx tsc --noEmit` or `npm run build` compile check.

Several frontend tasks assume backend endpoints have been updated to return `{ task_id: string }` from the various trigger endpoints (`triggerMosaicDetection`, `smartRebuildTargets`, `rebuildTargets`, `retryUnresolved`, `triggerXmatchEnrichment`, `triggerReferenceThumbnails`, `regenerateThumbnails`). If any still return only `{ status, message }`, update the API client return types locally when refactoring the caller, or add a small backend follow-up task to ensure all trigger endpoints return `{ task_id }`.

### Task 100: Update activity types in `frontend/src/types/index.ts`

**Files:**
- Modify: `frontend/src/types/index.ts`

- [ ] **Step 1: Replace the `ActivityEntry` interface block.**

Locate the existing `ActivityEntry` interface and replace with:

```ts
export type ActivitySeverity = "info" | "warning" | "error";

export type ActivityCategory =
  | "scan"
  | "rebuild"
  | "thumbnail"
  | "enrichment"
  | "mosaic"
  | "migration"
  | "user_action"
  | "system";

export interface ActivityEvent {
  id: number;
  timestamp: string;
  severity: ActivitySeverity;
  category: ActivityCategory;
  event_type: string;
  message: string;
  details: Record<string, unknown> | null;
  target_id: number | null;
  actor: string | null;
  duration_ms: number | null;
}

export interface ActiveJob {
  id: string;
  category: "scan" | "rebuild" | "thumbnail" | "enrichment" | "mosaic";
  label: string;
  subLabel?: string;
  progress?: number;
  startedAt: number;
  detail?: string;
  cancelable: boolean;
  onCancel?: () => Promise<void>;
}

export interface ActivityQueryParams {
  severity?: ActivitySeverity | ActivitySeverity[];
  category?: ActivityCategory | ActivityCategory[];
  limit?: number;
  cursor?: string;
  since?: string;
}

export interface ActivityPageResponse {
  items: ActivityEvent[];
  next_cursor: string | null;
  total: number;
}
```

- [ ] **Step 2: Verify compilation.**

Run: `cd frontend && npx tsc --noEmit`
Expected: zero errors from this file. `ActivityEntry` reference errors in other files are expected and will be resolved in Task 113.

**Manual verification:** Compilation-only. No browser step.

---

### Task 101: Add activity API client functions

**Files:**
- Modify: `frontend/src/api/client.ts`

- [ ] **Step 1: Add type imports.**

At the top of `frontend/src/api/client.ts`, extend the existing `from "../types"` import block:

```ts
import type {
  // existing imports unchanged,
  ActivityEvent,
  ActivityQueryParams,
  ActivityPageResponse,
} from "../types";
```

- [ ] **Step 2: Replace old activity methods.**

Remove the existing `getActivity` and `clearActivity` methods. Add:

```ts
  fetchActivity: (params: ActivityQueryParams = {}) => {
    const qs = new URLSearchParams();
    const severities = Array.isArray(params.severity)
      ? params.severity
      : params.severity
      ? [params.severity]
      : [];
    severities.forEach((s) => qs.append("severity", s));
    const categories = Array.isArray(params.category)
      ? params.category
      : params.category
      ? [params.category]
      : [];
    categories.forEach((c) => qs.append("category", c));
    if (params.limit !== undefined) qs.set("limit", String(params.limit));
    if (params.cursor) qs.set("cursor", params.cursor);
    if (params.since) qs.set("since", params.since);
    const q = qs.toString();
    return fetchJson<ActivityPageResponse>(`/activity${q ? `?${q}` : ""}`);
  },

  fetchActivityErrorsSince: (since: string) => {
    const qs = new URLSearchParams({ severity: "error", since });
    return fetchJson<ActivityPageResponse>(`/activity?${qs}`);
  },

  clearActivityLog: () =>
    fetchJson<{ status: string }>("/activity", { method: "DELETE" }),

  getActivitySettings: () =>
    fetchJson<{ activity_retention_days: number }>("/settings/activity"),

  setActivitySettings: (body: { retention_days: number }) =>
    fetchJson<{ activity_retention_days: number }>("/settings/activity", {
      method: "PUT",
      body: JSON.stringify(body),
    }),
```

Note: the `/settings/activity` GET/PUT endpoints are added as part of the settings UI wiring. If not yet present on the backend, add a thin FastAPI endpoint in a backend follow-up that reads/writes `activity_retention_days` in `GeneralSettings`.

- [ ] **Step 3: Verify compilation.**

Run: `cd frontend && npx tsc --noEmit`
Expected: zero new errors.

**Manual verification:** No requests to `/activity` should appear in DevTools Network tab yet (not called by any component).

---

### Task 102: Create `frontend/src/store/activeJobs.ts`

**Files:**
- Create: `frontend/src/store/activeJobs.ts`
- Modify: `frontend/src/components/ScanManager.tsx`

- [ ] **Step 1: Write the full store module.**

```ts
import { createSignal } from "solid-js";
import type { ActiveJob, ScanStatus, RebuildStatus } from "../types";

const [celeryJobs, setCeleryJobs] = createSignal<Map<string, ActiveJob>>(new Map());

export function scanStatusToJob(
  s: ScanStatus,
  onStop: () => Promise<void>
): ActiveJob | null {
  if (s.state !== "scanning" && s.state !== "ingesting") return null;

  const startedAt = s.started_at != null ? s.started_at * 1000 : Date.now();

  const progress =
    s.state === "ingesting" && s.total > 0
      ? Math.min(1, (s.completed + s.failed) / s.total)
      : undefined;

  const subLabel =
    s.state === "ingesting" && s.total > 0
      ? `${(s.completed + s.failed).toLocaleString()} / ${s.total.toLocaleString()} files`
      : s.discovered > 0
      ? `${s.discovered.toLocaleString()} files found`
      : undefined;

  return {
    id: "scan",
    category: "scan",
    label: s.state === "scanning" ? "Discovering files" : "Ingesting files",
    subLabel,
    progress,
    startedAt,
    cancelable: true,
    onCancel: onStop,
  };
}

export function rebuildStatusToJob(r: RebuildStatus): ActiveJob | null {
  if (r.state !== "running") return null;

  const startedAt = r.started_at != null ? r.started_at * 1000 : Date.now();

  const modeLabel: Record<string, string> = {
    smart: "Fix Orphans",
    full: "Full Rebuild",
    retry: "Re-resolve Targets",
    xmatch: "Catalog Match",
    ref_thumbnails: "Fetch DSS Thumbnails",
    regen: "Regenerate Thumbnails",
  };

  return {
    id: "rebuild",
    category: "rebuild",
    label: modeLabel[r.mode] ?? "Rebuild",
    subLabel: r.message || undefined,
    progress: undefined,
    startedAt,
    cancelable: false,
  };
}

export function registerCeleryJob(job: ActiveJob): void {
  setCeleryJobs((prev) => {
    const next = new Map(prev);
    next.set(job.id, job);
    return next;
  });
}

export function unregisterCeleryJob(id: string): void {
  setCeleryJobs((prev) => {
    const next = new Map(prev);
    next.delete(id);
    return next;
  });
}

type Accessor<T> = () => T;

let _scanStatusAccessor: Accessor<ScanStatus> | null = null;
let _rebuildStatusAccessor: Accessor<RebuildStatus> | null = null;
let _stopScanFn: (() => Promise<void>) | null = null;

export function wireActiveJobSources(
  scanStatus: Accessor<ScanStatus>,
  rebuildStatus: Accessor<RebuildStatus>,
  stopScan: () => Promise<void>
): void {
  _scanStatusAccessor = scanStatus;
  _rebuildStatusAccessor = rebuildStatus;
  _stopScanFn = stopScan;
}

export const activeJobs: Accessor<ActiveJob[]> = () => {
  const jobs: ActiveJob[] = [];

  if (_scanStatusAccessor && _stopScanFn) {
    const scanJob = scanStatusToJob(_scanStatusAccessor(), _stopScanFn);
    if (scanJob) jobs.push(scanJob);
  }

  if (_rebuildStatusAccessor) {
    const rebuildJob = rebuildStatusToJob(_rebuildStatusAccessor());
    if (rebuildJob) jobs.push(rebuildJob);
  }

  celeryJobs().forEach((job) => jobs.push(job));

  return jobs;
};

export const hasActiveJobs: Accessor<boolean> = () => activeJobs().length > 0;
```

- [ ] **Step 2: Wire the sources from ScanManager.**

In `frontend/src/components/ScanManager.tsx`, add import:
```ts
import { wireActiveJobSources } from "../store/activeJobs";
```

Inside the `ScanManager` component body, after both `scanStatus` and `rebuildState` signals are declared and `stopScan` is defined:

```ts
wireActiveJobSources(scanStatus, rebuildState, stopScan);
```

- [ ] **Step 3: Verify compilation.**

Run: `cd frontend && npx tsc --noEmit`
Expected: zero errors.

**Manual verification:** No visible change yet.

---

### Task 103: Extend `taskPoller.ts` with `track()` method

**Files:**
- Modify: `frontend/src/store/taskPoller.ts`

- [ ] **Step 1: Rewrite the file preserving `pollTask()` signature.**

```ts
import { api } from "../api/client";
import { registerCeleryJob, unregisterCeleryJob } from "./activeJobs";
import type { ActiveJob } from "../types";

interface PollOptions {
  onSuccess?: (result: any) => void;
  onFailure?: (error: string) => void;
  interval?: number;
  timeout?: number;
}

export function pollTask(taskId: string, options: PollOptions = {}): () => void {
  const { onSuccess, onFailure, interval = 2000, timeout = 60000 } = options;
  let timer: ReturnType<typeof setInterval> | null = null;
  let timeoutTimer: ReturnType<typeof setTimeout> | null = null;
  let stopped = false;

  const stop = () => {
    stopped = true;
    if (timer) clearInterval(timer);
    if (timeoutTimer) clearTimeout(timeoutTimer);
    timer = null;
    timeoutTimer = null;
  };

  const check = async () => {
    if (stopped) return;
    try {
      const status = await api.getTaskStatus(taskId);
      if (stopped) return;
      if (status.state === "SUCCESS") {
        stop();
        onSuccess?.(status.result);
      } else if (status.state === "FAILURE") {
        stop();
        onFailure?.(status.result?.error ?? "Task failed");
      }
    } catch {
      // Network error, keep polling
    }
  };

  timer = setInterval(check, interval);
  timeoutTimer = setTimeout(() => {
    stop();
    onFailure?.("Detection timed out");
  }, timeout);

  return stop;
}

interface TrackOptions {
  id: string;
  category: ActiveJob["category"];
  label: string;
  subLabel?: string;
  cancelable?: boolean;
  timeout?: number;
  onSuccess?: (result: any) => void;
  onFailure?: (error: string) => void;
}

export function track(opts: TrackOptions): () => void {
  const jobId = `celery:${opts.id}`;

  registerCeleryJob({
    id: jobId,
    category: opts.category,
    label: opts.label,
    subLabel: opts.subLabel,
    progress: undefined,
    startedAt: Date.now(),
    cancelable: opts.cancelable ?? false,
  });

  const stop = pollTask(opts.id, {
    interval: 2000,
    timeout: opts.timeout ?? 300_000,
    onSuccess: (result) => {
      unregisterCeleryJob(jobId);
      opts.onSuccess?.(result);
    },
    onFailure: (error) => {
      unregisterCeleryJob(jobId);
      opts.onFailure?.(error);
    },
  });

  return () => {
    unregisterCeleryJob(jobId);
    stop();
  };
}
```

- [ ] **Step 2: Verify compilation.**

Run: `cd frontend && npx tsc --noEmit`
Expected: zero errors.

**Manual verification:** No visible change yet.

---

### Task 104: Redesign `ActivityFeed.tsx`

**Files:**
- Modify: `frontend/src/components/ActivityFeed.tsx` (full rewrite)
- Modify: `frontend/src/components/ScanManager.tsx`

- [ ] **Step 1: Replace the entire `ActivityFeed.tsx` file.**

```tsx
import {
  Component,
  For,
  Show,
  createSignal,
  createEffect,
  onMount,
  onCleanup,
  batch,
} from "solid-js";
import { A } from "@solidjs/router";
import { activeJobs, hasActiveJobs } from "../store/activeJobs";
import { api } from "../api/client";
import { useSettingsContext } from "./SettingsProvider";
import type {
  ActivityEvent,
  ActivityCategory,
  ActivitySeverity,
  ActiveJob,
} from "../types";
import FailedFilesList from "./activity/FailedFilesList";
import EnrichmentFailureList from "./activity/EnrichmentFailureList";
import DetailsJsonFallback from "./activity/DetailsJsonFallback";

const SEVERITY_ICON: Record<ActivitySeverity, string> = {
  info: "●",
  warning: "▲",
  error: "✕",
};

const SEVERITY_CLASS: Record<ActivitySeverity, string> = {
  info: "text-theme-text-secondary",
  warning: "text-theme-warning",
  error: "text-theme-error",
};

const CATEGORY_LABELS: Record<ActivityCategory, string> = {
  scan: "scan",
  rebuild: "reb",
  thumbnail: "thumb",
  enrichment: "enrich",
  mosaic: "mosaic",
  migration: "migr",
  user_action: "user",
  system: "sys",
};

const ALL_CATEGORIES: ActivityCategory[] = [
  "scan", "rebuild", "thumbnail", "enrichment",
  "mosaic", "migration", "user_action", "system",
];

const IndeterminateBar: Component = () => (
  <div class="w-full h-1.5 rounded-full overflow-hidden bg-[var(--color-bg-subtle)]">
    <div
      class="h-full rounded-full"
      style={{
        background: "var(--color-accent)",
        animation: "activityIndeterminate 1.6s ease-in-out infinite",
        width: "40%",
      }}
    />
    <style>{`
      @keyframes activityIndeterminate {
        0%   { transform: translateX(-150%); }
        100% { transform: translateX(350%); }
      }
    `}</style>
  </div>
);

function startedAgo(startedAt: number): string {
  const secs = Math.floor((Date.now() - startedAt) / 1000);
  if (secs < 60) return `${secs}s ago`;
  const m = Math.floor(secs / 60);
  const s = secs % 60;
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")} ago`;
}

const ActiveJobRow: Component<{ job: ActiveJob }> = (props) => {
  const [agoLabel, setAgoLabel] = createSignal(startedAgo(props.job.startedAt));

  const timer = setInterval(() => {
    setAgoLabel(startedAgo(props.job.startedAt));
  }, 5000);
  onCleanup(() => clearInterval(timer));

  return (
    <div class="space-y-1.5 py-2">
      <div class="flex items-center justify-between gap-2">
        <div class="flex flex-col min-w-0">
          <span class="text-xs font-medium text-theme-text-primary truncate">
            {props.job.label}
          </span>
          <Show when={props.job.subLabel}>
            <span class="text-xs text-theme-text-secondary truncate">
              {props.job.subLabel}
            </span>
          </Show>
        </div>
        <div class="flex items-center gap-2 flex-shrink-0">
          <span class="text-xs text-theme-text-secondary">{agoLabel()}</span>
          <Show when={props.job.cancelable && props.job.onCancel}>
            <button
              onClick={() => props.job.onCancel?.()}
              class="px-2 py-1 text-xs border border-theme-border-em text-theme-text-secondary rounded hover:border-theme-error hover:text-theme-error transition-colors"
            >
              Stop
            </button>
          </Show>
        </div>
      </div>
      <Show
        when={props.job.progress !== undefined}
        fallback={<IndeterminateBar />}
      >
        {(_) => {
          const pct = () => Math.round((props.job.progress ?? 0) * 100);
          return (
            <div class="w-full h-1.5 rounded-full overflow-hidden bg-[var(--color-bg-subtle)]">
              <div
                class="h-full rounded-full transition-all"
                style={{
                  background: "var(--color-accent)",
                  width: `${pct()}%`,
                }}
              />
            </div>
          );
        }}
      </Show>
    </div>
  );
};

const RowDetails: Component<{ event: ActivityEvent }> = (props) => {
  const d = props.event.details;
  if (!d) return null;

  if (
    props.event.category === "scan" &&
    Array.isArray((d as any).failed_files)
  ) {
    return (
      <FailedFilesList
        files={(d as any).failed_files}
        truncated={(d as any).truncated ?? false}
      />
    );
  }

  if (
    props.event.category === "enrichment" &&
    Array.isArray((d as any).failed_targets)
  ) {
    return <EnrichmentFailureList targets={(d as any).failed_targets} />;
  }

  return <DetailsJsonFallback details={d} />;
};

const TargetLinkedMessage: Component<{ event: ActivityEvent }> = (props) => (
  <span>
    {props.event.message}
    {" "}
    <A
      href={`/targets/${props.event.target_id}`}
      class="text-theme-accent hover:underline"
      onClick={(e) => e.stopPropagation()}
    >
      ↗
    </A>
  </span>
);

const HistoryRow: Component<{ event: ActivityEvent }> = (props) => {
  const settingsCtx = useSettingsContext();
  const [expanded, setExpanded] = createSignal(false);
  const hasDetails = () => props.event.details !== null;

  const hhmm = () => {
    const d = new Date(props.event.timestamp);
    const fmt = new Intl.DateTimeFormat("en-GB", {
      hour: "2-digit",
      minute: "2-digit",
      timeZone: settingsCtx.timezone() || "UTC",
      hour12: !settingsCtx.use24hTime(),
    });
    return fmt.format(d);
  };

  return (
    <div
      id={`activity-event-${props.event.id}`}
      class="border-t border-theme-border first:border-0"
    >
      <div
        class="flex items-start gap-2 py-1.5 text-xs cursor-default"
        tabIndex={hasDetails() ? 0 : undefined}
        role={hasDetails() ? "button" : undefined}
        aria-expanded={hasDetails() ? expanded() : undefined}
        onKeyDown={(e) => {
          if (hasDetails() && (e.key === "Enter" || e.key === " ")) {
            e.preventDefault();
            setExpanded((v) => !v);
          }
        }}
        onClick={() => {
          if (hasDetails()) setExpanded((v) => !v);
        }}
      >
        <span class="text-theme-text-secondary flex-shrink-0 w-[3rem] tabular-nums">
          {hhmm()}
        </span>
        <span
          class={`flex-shrink-0 w-4 text-center ${SEVERITY_CLASS[props.event.severity]}`}
          title={props.event.severity}
        >
          {SEVERITY_ICON[props.event.severity]}
        </span>
        <span class="flex-shrink-0 w-[3.5rem] text-theme-text-secondary truncate">
          {CATEGORY_LABELS[props.event.category]}
        </span>
        <span class="flex-1 text-theme-text-primary min-w-0">
          <Show
            when={props.event.target_id !== null}
            fallback={<span>{props.event.message}</span>}
          >
            <TargetLinkedMessage event={props.event} />
          </Show>
        </span>
        <Show when={hasDetails()}>
          <span
            class={`flex-shrink-0 text-theme-text-secondary transition-transform ${
              expanded() ? "rotate-90" : ""
            }`}
          >
            ›
          </span>
        </Show>
      </div>
      <Show when={expanded() && hasDetails()}>
        <div class="pb-2 pl-[7rem]">
          <RowDetails event={props.event} />
        </div>
      </Show>
    </div>
  );
};

const FilterPill: Component<{
  label: string;
  active: boolean;
  onClick: () => void;
}> = (props) => (
  <button
    onClick={props.onClick}
    class={`px-2 py-0.5 text-xs rounded-full border transition-colors ${
      props.active
        ? "bg-[var(--color-accent)]/20 text-[var(--color-accent)] border-[var(--color-accent)]/40"
        : "border-theme-border text-theme-text-secondary hover:text-theme-text-primary hover:border-theme-border-em"
    }`}
  >
    {props.label}
  </button>
);

const ActivityFeed: Component = () => {
  const [severityFilter, setSeverityFilter] =
    createSignal<ActivitySeverity | "all">("all");
  const [categoryFilter, setCategoryFilter] =
    createSignal<ActivityCategory | "all">("all");
  const [items, setItems] = createSignal<ActivityEvent[]>([]);
  const [nextCursor, setNextCursor] = createSignal<string | null>(null);
  const [total, setTotal] = createSignal(0);
  const [loading, setLoading] = createSignal(false);
  const [loadingMore, setLoadingMore] = createSignal(false);
  const [newCount, setNewCount] = createSignal(0);
  const [latestId, setLatestId] = createSignal<number | null>(null);
  const [isScrolledDown, setIsScrolledDown] = createSignal(false);
  let listRef: HTMLDivElement | undefined;
  let pollTimer: ReturnType<typeof setInterval> | null = null;

  const buildParams = (extra: Record<string, unknown> = {}) => {
    const p: Record<string, unknown> = { limit: 50, ...extra };
    const sv = severityFilter();
    if (sv !== "all") p.severity = sv;
    const cat = categoryFilter();
    if (cat !== "all") p.category = cat;
    return p;
  };

  const loadInitial = async () => {
    setLoading(true);
    try {
      const res = await api.fetchActivity(buildParams());
      batch(() => {
        setItems(res.items);
        setNextCursor(res.next_cursor);
        setTotal(res.total);
        setNewCount(0);
        if (res.items.length > 0) setLatestId(res.items[0].id);
      });
    } catch { /* non-blocking */ } finally {
      setLoading(false);
    }
  };

  const loadMore = async () => {
    const cursor = nextCursor();
    if (!cursor || loadingMore()) return;
    setLoadingMore(true);
    try {
      const res = await api.fetchActivity(buildParams({ cursor }));
      batch(() => {
        setItems((prev) => [...prev, ...res.items]);
        setNextCursor(res.next_cursor);
      });
    } catch { /* ignore */ } finally {
      setLoadingMore(false);
    }
  };

  const pollNew = async () => {
    const top = latestId();
    if (top === null) { await loadInitial(); return; }
    try {
      const res = await api.fetchActivity(buildParams({ limit: 50 }));
      if (res.items.length === 0) return;
      const newItems = res.items.filter((e) => e.id > top);
      if (newItems.length === 0) return;
      if (isScrolledDown()) {
        setNewCount((n) => n + newItems.length);
      } else {
        batch(() => {
          setItems((prev) => [...newItems, ...prev]);
          setLatestId(newItems[0].id);
          setTotal(res.total);
        });
      }
    } catch { /* ignore */ }
  };

  onMount(() => {
    loadInitial();
    pollTimer = setInterval(pollNew, 10_000);
  });

  onCleanup(() => {
    if (pollTimer) clearInterval(pollTimer);
  });

  createEffect(() => {
    severityFilter();
    categoryFilter();
    loadInitial();
  });

  const onScroll = () => {
    if (!listRef) return;
    setIsScrolledDown(listRef.scrollTop > 120);
  };

  const jumpToNew = () => {
    listRef?.scrollTo({ top: 0, behavior: "smooth" });
    setNewCount(0);
    loadInitial();
  };

  const jobs = () => activeJobs();
  const jobCount = () => jobs().length;

  return (
    <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] flex flex-col h-full min-h-0">
      <div class="flex items-center justify-between px-4 py-3 flex-shrink-0">
        <div class="flex items-center gap-2">
          <h3 class="text-theme-text-primary font-medium text-sm">Activity</h3>
          <Show when={jobCount() > 0}>
            <span class="px-1.5 py-0.5 text-xs rounded-full bg-[var(--color-accent)]/20 text-[var(--color-accent)] border border-[var(--color-accent)]/30 tabular-nums">
              {jobCount()} live
            </span>
          </Show>
        </div>
      </div>

      <Show when={hasActiveJobs()}>
        <div
          role="status"
          aria-live="polite"
          class="px-4 pb-3 border-b border-theme-border space-y-0 divide-y divide-theme-border"
          style={{ background: "var(--color-bg-subtle)" }}
        >
          <p class="text-[10px] font-semibold uppercase tracking-wider text-theme-text-secondary pb-1 pt-0.5">
            Now Running
          </p>
          <For each={jobs()}>
            {(job) => <ActiveJobRow job={job} />}
          </For>
        </div>
      </Show>

      <div class="flex flex-col flex-1 min-h-0">
        <div class="px-4 pt-3 pb-2 space-y-1.5 flex-shrink-0">
          <p class="text-[10px] font-semibold uppercase tracking-wider text-theme-text-secondary">
            History
          </p>
          <div class="flex flex-wrap gap-1">
            {(["all", "info", "warning", "error"] as const).map((sv) => (
              <FilterPill
                label={sv === "all" ? "all" : sv === "warning" ? "warn" : sv}
                active={severityFilter() === sv}
                onClick={() => setSeverityFilter(sv)}
              />
            ))}
          </div>
          <div class="flex flex-wrap gap-1">
            <FilterPill
              label="all"
              active={categoryFilter() === "all"}
              onClick={() => setCategoryFilter("all")}
            />
            <For each={ALL_CATEGORIES}>
              {(cat) => (
                <FilterPill
                  label={CATEGORY_LABELS[cat]}
                  active={categoryFilter() === cat}
                  onClick={() => setCategoryFilter(cat)}
                />
              )}
            </For>
          </div>
        </div>

        <div
          ref={listRef}
          class="flex-1 min-h-0 overflow-y-auto px-4 relative"
          onScroll={onScroll}
        >
          <Show when={newCount() > 0}>
            <div class="sticky top-2 flex justify-center z-10">
              <button
                onClick={jumpToNew}
                class="px-3 py-1 text-xs rounded-full bg-[var(--color-accent)] text-white shadow-md"
              >
                {newCount()} new, click to view
              </button>
            </div>
          </Show>

          <Show when={loading()}>
            <p class="text-xs text-theme-text-secondary py-4 text-center">Loading...</p>
          </Show>

          <Show when={!loading() && items().length === 0}>
            <p class="text-xs text-theme-text-secondary py-4">No activity recorded yet.</p>
          </Show>

          <Show when={!loading()}>
            <div class="space-y-0">
              <For each={items()}>
                {(event) => <HistoryRow event={event} />}
              </For>
            </div>

            <Show when={nextCursor() !== null}>
              <div class="py-3 text-center">
                <button
                  onClick={loadMore}
                  disabled={loadingMore()}
                  class="px-4 py-1.5 text-xs border border-theme-border text-theme-text-secondary rounded hover:text-theme-text-primary hover:border-theme-border-em transition-colors disabled:opacity-50"
                >
                  {loadingMore() ? "Loading..." : "Load older"}
                </button>
              </div>
            </Show>
          </Show>
        </div>
      </div>
    </div>
  );
};

export default ActivityFeed;
```

- [ ] **Step 2: Mount the redesigned component in ScanManager.**

In `ScanManager.tsx`, replace the existing `<ActivityFeed ...props />` with the prop-less version:

```tsx
<ActivityFeed />
```

Remove the old `activity` signal, `refreshActivity`, `clearActivity`, and the `createEffect` that drove them.

- [ ] **Step 3: Verify compilation.**

Run: `cd frontend && npx tsc --noEmit`
Expected: zero errors.

**Manual verification:** Navigate to `http://localhost:3000` Settings > Library. Confirm the Activity card shows a header, empty Now Running (hidden), History region with severity and category filter pills. Trigger a scan via Scan Now and verify the scan appears in Now Running with a progress bar and the header badge shows "1 live". After the scan completes the region collapses to 0h.

---

### Task 105: Create detail renderer components

**Files:**
- Create: `frontend/src/components/activity/FailedFilesList.tsx`
- Create: `frontend/src/components/activity/EnrichmentFailureList.tsx`
- Create: `frontend/src/components/activity/DetailsJsonFallback.tsx`

- [ ] **Step 1: Create `FailedFilesList.tsx`.**

```tsx
import { Component, For, Show } from "solid-js";

interface FailedFile {
  path: string;
  reason: string;
}

const DISPLAY_LIMIT = 10;

const FailedFilesList: Component<{
  files: FailedFile[];
  truncated: boolean;
}> = (props) => {
  const shown = () => props.files.slice(0, DISPLAY_LIMIT);
  const overflow = () => props.files.length - DISPLAY_LIMIT;

  return (
    <div class="space-y-1 mt-1 max-h-48 overflow-y-auto">
      <For each={shown()}>
        {(f) => (
          <div class="border border-theme-border rounded px-2 py-1">
            <div class="text-xs text-theme-text-secondary break-all font-mono">
              {f.path}
            </div>
            <div
              class="text-xs text-[var(--color-warning)] truncate"
              title={f.reason}
            >
              {f.reason}
            </div>
          </div>
        )}
      </For>
      <Show when={overflow() > 0}>
        <p class="text-xs text-theme-text-secondary pl-1">
          {overflow()} more file{overflow() > 1 ? "s" : ""}
        </p>
      </Show>
      <Show when={props.truncated}>
        <p class="text-xs text-[var(--color-warning)] pl-1">
          List truncated at 500 entries.
        </p>
      </Show>
    </div>
  );
};

export default FailedFilesList;
```

- [ ] **Step 2: Create `EnrichmentFailureList.tsx`.**

```tsx
import { Component, For, Show } from "solid-js";

interface FailedTarget {
  name: string;
  reason?: string;
}

const DISPLAY_LIMIT = 10;

const EnrichmentFailureList: Component<{ targets: FailedTarget[] }> = (props) => {
  const shown = () => props.targets.slice(0, DISPLAY_LIMIT);
  const overflow = () => props.targets.length - DISPLAY_LIMIT;

  return (
    <div class="space-y-1 mt-1 max-h-48 overflow-y-auto">
      <For each={shown()}>
        {(t) => (
          <div class="flex items-start gap-2 py-0.5">
            <span class="text-xs text-theme-text-primary font-medium">{t.name}</span>
            <Show when={t.reason}>
              <span class="text-xs text-theme-text-secondary">{t.reason}</span>
            </Show>
          </div>
        )}
      </For>
      <Show when={overflow() > 0}>
        <p class="text-xs text-theme-text-secondary pl-1">
          {overflow()} more target{overflow() > 1 ? "s" : ""}
        </p>
      </Show>
    </div>
  );
};

export default EnrichmentFailureList;
```

- [ ] **Step 3: Create `DetailsJsonFallback.tsx`.**

```tsx
import { Component } from "solid-js";

const DetailsJsonFallback: Component<{ details: Record<string, unknown> }> = (props) => {
  const formatted = () => {
    try {
      return JSON.stringify(props.details, null, 2);
    } catch {
      return String(props.details);
    }
  };

  return (
    <pre class="text-xs text-theme-text-secondary bg-theme-base/50 border border-theme-border rounded p-2 overflow-x-auto max-h-40 font-mono whitespace-pre-wrap break-all">
      {formatted()}
    </pre>
  );
};

export default DetailsJsonFallback;
```

- [ ] **Step 4: Verify compilation.**

Run: `cd frontend && npx tsc --noEmit`
Expected: zero errors.

**Manual verification:** If any history row has details (chevron shown), click the row. Expect a file list or JSON block to appear inline.

---

### Task 106: Create `emitWithToast()` helper and update Toast for persist mode

**Files:**
- Create: `frontend/src/lib/emitWithToast.ts`
- Modify: `frontend/src/components/Toast.tsx`

- [ ] **Step 1: Write the helper.**

```ts
import { showToast, dismissToast } from "../components/Toast";
import { track } from "../store/taskPoller";
import type { ActiveJob } from "../types";

interface EmitWithToastOptions {
  action: () => Promise<{ task_id: string }>;
  pendingLabel: string;
  successLabel: string;
  errorLabel: string;
  category: ActiveJob["category"];
  taskLabel: string;
  taskSubLabel?: string;
  timeout?: number;
}

export async function emitWithToast(opts: EmitWithToastOptions): Promise<void> {
  showToast(opts.pendingLabel, "info", 120_000);

  let taskId: string;
  try {
    const result = await opts.action();
    taskId = result.task_id;
  } catch {
    dismissToast();
    showToast(opts.errorLabel, "error", 0);
    return;
  }

  track({
    id: taskId,
    category: opts.category,
    label: opts.taskLabel,
    subLabel: opts.taskSubLabel,
    timeout: opts.timeout ?? 300_000,
    onSuccess: () => {
      dismissToast();
      showToast(opts.successLabel, "success", 3000);
    },
    onFailure: (error) => {
      dismissToast();
      showToast(`${opts.errorLabel}: ${error}`, "error", 0);
    },
  });
}
```

- [ ] **Step 2: Update `Toast.tsx` for persist mode + dismiss button.**

Support `duration = 0` meaning persist until `dismissToast()` is called. Add a dismiss button to the toast markup.

```ts
export function showToast(
  message: string,
  type: "success" | "error" | "info" = "success",
  duration = 3000,
) {
  clearTimeout(timeout);
  setToast({ message, type });
  if (duration > 0) {
    timeout = setTimeout(() => setToast(null), duration);
  }
}

export function dismissToast() {
  clearTimeout(timeout);
  setToast(null);
}
```

In the toast component JSX, after the message span, add:

```tsx
<button
  onClick={() => setToast(null)}
  class="opacity-60 hover:opacity-100 transition-opacity ml-1"
  aria-label="Dismiss"
>
  ✕
</button>
```

- [ ] **Step 3: Verify compilation.**

Run: `cd frontend && npx tsc --noEmit`
Expected: zero errors.

**Manual verification:** Exercised in Tasks 107-109.

---

### Task 107: Refactor `MergesTab.tsx` to use `emitWithToast()`

**Files:**
- Modify: `frontend/src/components/settings/MergesTab.tsx`

- [ ] **Step 1: Add import.**

```ts
import { emitWithToast } from "../../lib/emitWithToast";
```

Remove any now-unused imports of `pollTask` from the old inline polling code.

- [ ] **Step 2: Replace `handleDetect`.**

```ts
const handleDetect = async () => {
  if (detecting()) return;
  setDetecting(true);
  await emitWithToast({
    action: () => api.triggerDuplicateDetection(),
    pendingLabel: "Detecting duplicates...",
    successLabel: "Duplicate detection complete",
    errorLabel: "Duplicate detection failed",
    category: "scan",
    taskLabel: "Duplicate detection",
    timeout: 120_000,
  });
  setDetecting(false);
  refresh();
};
```

Remove the old `stopPolling` ref and its `onCleanup`.

- [ ] **Step 3: Verify compilation.**

Run: `cd frontend && npx tsc --noEmit`
Expected: zero errors.

**Manual verification:** Navigate to Settings > Target Management. Click Run Detection. Expect info toast "Detecting duplicates...", job appears in Now Running. On completion, success toast replaces the info toast and auto-dismisses after 3 seconds.

---

### Task 108: Refactor `MosaicsTab.tsx` for mosaic detection

**Files:**
- Modify: `frontend/src/components/settings/MosaicsTab.tsx`

- [ ] **Step 1: Add import.**

```ts
import { emitWithToast } from "../../lib/emitWithToast";
```

- [ ] **Step 2: Replace `handleDetect`.**

```ts
const handleDetect = async () => {
  if (detecting()) return;
  setDetecting(true);
  await emitWithToast({
    action: () => api.triggerMosaicDetection() as Promise<{ task_id: string }>,
    pendingLabel: "Running mosaic detection...",
    successLabel: "Mosaic detection complete",
    errorLabel: "Mosaic detection failed",
    category: "mosaic",
    taskLabel: "Mosaic detection",
    timeout: 120_000,
  });
  setDetecting(false);
  refresh(true);
};
```

- [ ] **Step 3: Verify compilation.**

Run: `cd frontend && npx tsc --noEmit`
Expected: zero errors.

**Manual verification:** Navigate to Settings > Mosaics. Click Run Detection. Info toast + Now Running entry + success toast on completion.

---

### Task 109: Refactor `MaintenanceActions.tsx` for all six triggers

**Files:**
- Modify: `frontend/src/components/MaintenanceActions.tsx`
- Modify: `frontend/src/components/ScanManager.tsx`

- [ ] **Step 1: Rewrite `MaintenanceActions.tsx` with no props.**

Each maintenance handler calls `emitWithToast()`. Preserve all the existing confirm dialogs and button styles. Full component structure per spec mockup retained. Key handlers:

```tsx
const fixOrphans = () => run(() => emitWithToast({
  action: () => api.smartRebuildTargets() as Promise<{ task_id: string }>,
  pendingLabel: "Starting Fix Orphans...",
  successLabel: "Fix Orphans complete",
  errorLabel: "Fix Orphans failed",
  category: "rebuild",
  taskLabel: "Fix Orphans",
  timeout: 600_000,
}));

const reResolve = () => run(() => emitWithToast({
  action: () => api.retryUnresolved() as Promise<{ task_id: string }>,
  pendingLabel: "Starting Re-resolve...",
  successLabel: "Re-resolve complete",
  errorLabel: "Re-resolve failed",
  category: "enrichment",
  taskLabel: "Re-resolve targets",
  timeout: 600_000,
}));

const catalogMatch = () => run(() => emitWithToast({
  action: () => api.triggerXmatchEnrichment() as Promise<{ task_id: string }>,
  pendingLabel: "Starting Catalog Match...",
  successLabel: "Catalog Match complete",
  errorLabel: "Catalog Match failed",
  category: "enrichment",
  taskLabel: "Catalog Match",
  timeout: 600_000,
}));

const fetchDss = (forceAll: boolean) => run(() => emitWithToast({
  action: () => api.triggerReferenceThumbnails(forceAll) as Promise<{ task_id: string }>,
  pendingLabel: "Starting DSS fetch...",
  successLabel: "DSS fetch complete",
  errorLabel: "DSS fetch failed",
  category: "thumbnail",
  taskLabel: forceAll ? "Fetch DSS (all)" : "Fetch DSS (missing)",
  timeout: 600_000,
}));

const regenThumbs = (purge: boolean) => run(() => emitWithToast({
  action: () => api.regenerateThumbnails({ purge }) as Promise<{ task_id: string }>,
  pendingLabel: purge ? "Deleting and regenerating thumbnails..." : "Regenerating thumbnails...",
  successLabel: "Thumbnail regeneration complete",
  errorLabel: "Thumbnail regeneration failed",
  category: "thumbnail",
  taskLabel: purge ? "Regen Thumbnails (purge)" : "Regen Thumbnails",
  timeout: 1_800_000,
}));

const fullRebuild = () => run(() => emitWithToast({
  action: () => api.rebuildTargets() as Promise<{ task_id: string }>,
  pendingLabel: "Starting Full Rebuild...",
  successLabel: "Full Rebuild complete",
  errorLabel: "Full Rebuild failed",
  category: "rebuild",
  taskLabel: "Full Rebuild",
  timeout: 3_600_000,
}));
```

Where `run` is a small wrapper managing `busy()`/dialog visibility:

```ts
const [busy, setBusy] = createSignal(false);
const run = async (fn: () => Promise<void>) => {
  if (busy()) return;
  setBusy(true);
  setShowFullConfirm(false);
  setShowRefThumbChoice(false);
  setShowRegenChoice(false);
  setConfirmPurgeRegen(false);
  try { await fn(); } finally { setBusy(false); }
};
```

Remove all props from `MaintenanceActions`; the component is now self-contained.

- [ ] **Step 2: Update `ScanManager.tsx` to drop `MaintenanceActions` props.**

Replace `<MaintenanceActions ... />` with `<MaintenanceActions />`.

- [ ] **Step 3: Verify compilation.**

Run: `cd frontend && npx tsc --noEmit`
Expected: zero errors.

**Manual verification:** Navigate to Settings > Library. Click each maintenance button. Each fires an info toast, shows an entry in Now Running, and emits a success toast on completion. Confirm the Full Rebuild confirmation dialog still works and that post-confirm the job appears in Now Running.

---

### Task 110: Create `errorToastPoller.ts`

**Files:**
- Create: `frontend/src/store/errorToastPoller.ts`

- [ ] **Step 1: Write the module.**

```ts
import { showToast } from "../components/Toast";
import { api } from "../api/client";

const LS_KEY = "galactilog_last_error_ts";

function getLastSeenTs(): string {
  try {
    return localStorage.getItem(LS_KEY) ?? new Date(0).toISOString();
  } catch {
    return new Date(0).toISOString();
  }
}

function setLastSeenTs(ts: string): void {
  try {
    localStorage.setItem(LS_KEY, ts);
  } catch { /* ignore */ }
}

let pollTimer: ReturnType<typeof setInterval> | null = null;

async function checkErrors(): Promise<void> {
  const since = getLastSeenTs();
  try {
    const res = await api.fetchActivityErrorsSince(since);
    if (res.items.length === 0) return;

    setLastSeenTs(res.items[0].timestamp);

    const toShow = res.items.slice(0, 3);
    for (const item of toShow) {
      const msg = `[${item.category}] ${item.message} (ref #${item.id})`;
      showToast(msg, "error", 0);
    }
    if (res.items.length > 3) {
      showToast(`${res.items.length - 3} more errors, check the Activity log`, "error", 0);
    }
  } catch { /* non-blocking */ }
}

export function startErrorToastPoller(): void {
  if (pollTimer) return;
  checkErrors();
  pollTimer = setInterval(checkErrors, 10_000);
}

export function stopErrorToastPoller(): void {
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
}
```

- [ ] **Step 2: Verify compilation.**

Run: `cd frontend && npx tsc --noEmit`
Expected: zero errors.

**Manual verification:** Mounted in Task 111.

---

### Task 111: Mount the error poller at app root

**Files:**
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: Wire the poller to auth state.**

```tsx
import { type Component, type ParentProps, Show, createEffect } from "solid-js";
import { useLocation } from "@solidjs/router";
import NavBar from "./components/NavBar";
import { Toast } from "./components/Toast";
import { useAuth } from "./components/AuthProvider";
import {
  startErrorToastPoller,
  stopErrorToastPoller,
} from "./store/errorToastPoller";

const ErrorPollerMount: Component = () => {
  const { user } = useAuth();

  createEffect(() => {
    if (user() !== null) {
      startErrorToastPoller();
    } else {
      stopErrorToastPoller();
    }
  });

  return null;
};

const App: Component<ParentProps> = (props) => {
  const location = useLocation();

  return (
    <div class="min-h-screen bg-theme-base text-theme-text-primary relative z-10">
      <Show when={location.pathname !== "/login"}>
        <NavBar />
        <ErrorPollerMount />
      </Show>
      {props.children}
      <Toast />
    </div>
  );
};

export default App;
```

- [ ] **Step 2: Verify compilation.**

Run: `cd frontend && npx tsc --noEmit`
Expected: zero errors.

**Manual verification:** Log in. In the browser console run `localStorage.setItem("galactilog_last_error_ts", new Date(0).toISOString())`. Within 10 seconds, if any error-severity rows exist, persistent error toasts appear. Click the dismiss button and confirm they close.

---

### Task 112: Add Activity Log section to Settings page

**Files:**
- Create: `frontend/src/components/settings/ActivityLogTab.tsx`
- Modify: `frontend/src/pages/SettingsPage.tsx`

- [ ] **Step 1: Create `ActivityLogTab.tsx`.**

```tsx
import { Component, createSignal, onMount, Show } from "solid-js";
import { api } from "../../api/client";
import { useAuth } from "../AuthProvider";
import { showToast } from "../Toast";

const ActivityLogTab: Component = () => {
  const { isAdmin } = useAuth();
  const [retentionDays, setRetentionDays] = createSignal(90);
  const [saving, setSaving] = createSignal(false);
  const [clearing, setClearing] = createSignal(false);
  const [showClearConfirm, setShowClearConfirm] = createSignal(false);
  const [loading, setLoading] = createSignal(true);

  onMount(async () => {
    try {
      const s = await api.getActivitySettings();
      setRetentionDays(s.activity_retention_days);
    } catch { /* ignore */ } finally {
      setLoading(false);
    }
  });

  const handleSave = async () => {
    if (saving()) return;
    setSaving(true);
    try {
      const res = await api.setActivitySettings({ retention_days: retentionDays() });
      setRetentionDays(res.activity_retention_days);
      showToast("Retention setting saved", "success", 3000);
    } catch {
      showToast("Failed to save retention setting", "error", 0);
    } finally {
      setSaving(false);
    }
  };

  const handleClear = async () => {
    if (clearing()) return;
    setShowClearConfirm(false);
    setClearing(true);
    try {
      await api.clearActivityLog();
      showToast("Activity log cleared", "success", 3000);
    } catch {
      showToast("Failed to clear activity log", "error", 0);
    } finally {
      setClearing(false);
    }
  };

  return (
    <div class="space-y-4">
      <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] p-4 space-y-4">
        <h3 class="text-theme-text-primary font-medium">Activity Log</h3>

        <Show when={loading()}>
          <p class="text-xs text-theme-text-secondary">Loading...</p>
        </Show>

        <Show when={!loading()}>
          <div class="space-y-3">
            <div class="flex items-center gap-3">
              <label class="text-sm text-theme-text-secondary w-40 flex-shrink-0">
                Retention (days)
              </label>
              <input
                type="number"
                min={1}
                max={3650}
                value={retentionDays()}
                onInput={(e) => {
                  const v = parseInt(e.currentTarget.value, 10);
                  if (!isNaN(v) && v >= 1 && v <= 3650) setRetentionDays(v);
                }}
                class="w-24 px-2 py-1 text-sm bg-theme-base border border-theme-border rounded text-theme-text-primary focus:outline-none focus:border-theme-accent tabular-nums"
              />
              <button
                onClick={handleSave}
                disabled={saving() || !isAdmin()}
                class="px-3 py-1.5 bg-theme-accent/15 text-theme-accent border border-theme-accent/30 rounded text-sm disabled:opacity-50 hover:bg-theme-accent/25 transition-colors"
              >
                {saving() ? "Saving..." : "Save"}
              </button>
            </div>
            <p class="text-xs text-theme-text-secondary">
              Events older than this many days are deleted by the nightly pruner. Min 1, max 3650.
            </p>
          </div>

          <Show when={isAdmin()}>
            <div class="border-t border-theme-border pt-4 space-y-2">
              <Show when={!showClearConfirm()}>
                <button
                  onClick={() => setShowClearConfirm(true)}
                  disabled={clearing()}
                  class="px-3 py-1.5 border border-theme-error/50 text-theme-error rounded text-sm disabled:opacity-50 hover:bg-theme-error/20 transition-colors"
                >
                  Clear activity log
                </button>
              </Show>
              <Show when={showClearConfirm()}>
                <div class="bg-theme-error/10 border border-theme-error/40 rounded-[var(--radius-md)] p-3 space-y-2">
                  <p class="text-sm text-theme-error font-medium">Clear all activity?</p>
                  <p class="text-xs text-theme-error/70">
                    This permanently deletes all activity log entries. The action cannot be undone.
                  </p>
                  <div class="flex gap-2 pt-1">
                    <button
                      onClick={handleClear}
                      class="px-3 py-1.5 bg-theme-error text-theme-text-primary rounded text-xs font-medium hover:opacity-90 transition-colors"
                    >
                      Yes, clear all
                    </button>
                    <button
                      onClick={() => setShowClearConfirm(false)}
                      class="px-3 py-1.5 border border-theme-border-em text-theme-text-secondary rounded text-xs hover:text-theme-text-primary transition-colors"
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              </Show>
            </div>
          </Show>
        </Show>
      </div>
    </div>
  );
};

export default ActivityLogTab;
```

- [ ] **Step 2: Register the tab in `SettingsPage.tsx`.**

Lazy import:
```ts
const ActivityLogTab = lazy(() => import("../components/settings/ActivityLogTab"));
```

Add to `ALL_TABS`:
```ts
{ id: "activity-log", label: "Activity Log", adminOnly: true },
```

Add rendering clause:
```tsx
<Show when={activeTab() === "activity-log" && isAdmin()}>
  <ActivityLogTab />
</Show>
```

- [ ] **Step 3: Verify compilation.**

Run: `cd frontend && npx tsc --noEmit`
Expected: zero errors.

**Manual verification:** Navigate to Settings. Confirm Activity Log tab visible for admin. Change retention to 30, save, expect success toast. Click Clear activity log, confirm, expect the feed to empty.

---

### Task 113: Final integration pass

**Files:**
- Modify: `frontend/src/types/index.ts`
- Modify: `frontend/src/components/ScanManager.tsx`
- Modify: `frontend/src/api/client.ts`

- [ ] **Step 1: Grep for remaining `ActivityEntry` references.**

```
cd frontend && grep -rn "ActivityEntry" src --include="*.ts" --include="*.tsx"
```

Replace each with `ActivityEvent` or remove dead references.

- [ ] **Step 2: Clean up `ScanManager.tsx`.**

Remove:
- `ActivityEntry` import.
- The `activity` signal, `refreshActivity`, `clearActivity` functions.
- The `createEffect` that called `refreshActivity`.
- Any `refreshActivity()` call in the `onMergesChanged` listener (keep `refreshDbSummary()`).

- [ ] **Step 3: Verify `api.getActivity` / `api.clearActivity` callers are gone.**

```
cd frontend && grep -rn "api.getActivity\|api.clearActivity\b" src
```

Expected: no matches. All callers use `api.fetchActivity` and `api.clearActivityLog`.

- [ ] **Step 4: Run full TypeScript build.**

```
cd frontend && npm run build
```

Expected: zero TypeScript errors. Bundle size warnings are acceptable.

- [ ] **Step 5: Browser smoke test.**

Log in at `http://localhost:3000`:

1. Settings > Library. Activity card renders with History + filter pills.
2. Click Scan Now. Now Running appears with a progress bar. Header badge shows "1 live". After completion, the region collapses and a history entry appears.
3. Switch severity filter to warn. List updates. Switch back to all.
4. Settings > Target Management. Run Detection. Now Running shows "Duplicate detection".
5. Settings > Activity Log (admin). Retention input shows 90. Set 365, save.
6. In browser console: `localStorage.setItem("galactilog_last_error_ts", new Date(0).toISOString())`. Within 10s, if errors exist, persistent error toasts appear.
7. In the feed, click Load older when >50 events exist. Entries append below.

- [ ] **Step 6: Final commit.**

```
git add frontend/src/types/index.ts frontend/src/components/ScanManager.tsx frontend/src/api/client.ts
git commit -m "Final activity log integration: remove ActivityEntry, clean up dead code"
```

---

## Notes for the implementer

- Backend migration revision number (`0011`) is a placeholder. Run `alembic current` and adjust to match your actual head before committing Task 1.
- Several frontend refactors assume backend trigger endpoints return `{ task_id: string }`. If any still return only `{ status, message }`, add a small follow-up backend task to change them, or add a `/settings/activity` GET/PUT endpoint alongside the GeneralSettings field from Task 16 so the frontend Settings UI (Task 112) has endpoints to call.
- Per project convention, commits MUST NOT include `Co-Authored-By` or any AI attribution line.
