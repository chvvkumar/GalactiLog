"""DB-backed test for GET /api/activity?attention=true.

The filter is `severity = 'error' OR details ? 'action'`, a JSONB key test that
only a real Postgres evaluates: the mocked sessions the rest of the activity
API tests use never run the SQL. Requires test:test@localhost:5432/test_catalog
with the Alembic schema applied.
"""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.main import app
from app.database import get_session
from app.api.deps import get_current_user
from app.models.activity_event import ActivityEvent
from app.models.user import User, UserRole


TEST_DB_URL = settings.database_url

ACTION = {"label": "Map PHD2 profiles", "href": "/settings?tab=equipment#phd2-profiles"}
BASE_TS = datetime(2026, 8, 24, 20, 0, tzinfo=timezone.utc)


def _event(n, severity, details):
    return ActivityEvent(
        timestamp=BASE_TS + timedelta(minutes=n),
        severity=severity, category="scan", event_type=f"ev_{n}",
        message=f"event {n}", details=details, actor="system",
    )


@pytest_asyncio.fixture
async def seeded_activity():
    from app.database import engine as app_engine
    await app_engine.dispose()

    engine = create_async_engine(TEST_DB_URL, poolclass=None)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async def _truncate():
        async with engine.begin() as conn:
            await conn.execute(text("TRUNCATE TABLE activity_events CASCADE"))

    await _truncate()

    async with Session() as s:
        s.add(_event(1, "error", {"failed_files": []}))          # error, no action
        s.add(_event(2, "warning", {"profiles": ["a"], "action": ACTION}))
        s.add(_event(3, "warning", {"profiles": ["b"]}))          # plain warning
        s.add(_event(4, "info", None))                           # details IS NULL
        s.add(_event(5, "error", {"action": ACTION}))            # both halves
        await s.commit()

    async def _override_session():
        async with Session() as s:
            yield s

    def _override_user():
        u = MagicMock(spec=User)
        u.id = uuid.uuid4()
        u.username = "tester"
        u.role = UserRole.admin
        u.is_active = True
        return u

    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_current_user] = _override_user

    yield Session

    app.dependency_overrides.clear()
    await _truncate()
    await engine.dispose()
    await app_engine.dispose()


async def _get(url):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get(url)
    assert resp.status_code == 200
    return resp.json()


@pytest.mark.asyncio
async def test_attention_returns_errors_and_actionable_warnings(seeded_activity):
    data = await _get("/api/activity?attention=true")
    types = {i["event_type"] for i in data["items"]}
    assert types == {"ev_1", "ev_2", "ev_5"}
    assert data["total"] == 3


@pytest.mark.asyncio
async def test_attention_excludes_plain_warnings_and_null_details(seeded_activity):
    data = await _get("/api/activity?attention=true")
    types = {i["event_type"] for i in data["items"]}
    assert "ev_3" not in types
    assert "ev_4" not in types


@pytest.mark.asyncio
async def test_attention_overrides_severity_param(seeded_activity):
    data = await _get("/api/activity?attention=true&severity=info")
    types = {i["event_type"] for i in data["items"]}
    assert types == {"ev_1", "ev_2", "ev_5"}


@pytest.mark.asyncio
async def test_attention_false_leaves_severity_filter_alone(seeded_activity):
    data = await _get("/api/activity?severity=warning")
    types = {i["event_type"] for i in data["items"]}
    assert types == {"ev_2", "ev_3"}

    data = await _get("/api/activity")
    assert data["total"] == 5


@pytest.mark.asyncio
async def test_attention_still_honours_category_filter(seeded_activity):
    data = await _get("/api/activity?attention=true&category=mosaic")
    assert data["items"] == [] and data["total"] == 0
