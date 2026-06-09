"""Tests for timeline granularity in /stats endpoint."""
from contextlib import asynccontextmanager

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.database import get_session
from app.api.deps import get_current_user
from app.models.user import User


def _make_admin_user():
    from app.models.user import UserRole
    user = MagicMock(spec=User)
    user.id = __import__("uuid").uuid4()
    user.username = "admin"
    user.role = UserRole.admin
    user.is_active = True
    return user


def _make_overview_result():
    r = MagicMock()
    # (total_seconds, target_count, total_frames, session_count, first_date, last_date)
    r.one.return_value = (0, 0, 0, 0, None, None)
    r.all.return_value = []
    r.first.return_value = None
    r.scalar_one.return_value = 0
    r.scalar_one_or_none.return_value = None
    return r


def _make_bucket_result():
    r = MagicMock()
    # One count per HFR bucket range (8 buckets defined in stats.py)
    r.one.return_value = (0, 0, 0, 0, 0, 0, 0, 0)
    r.all.return_value = []
    r.first.return_value = None
    r.scalar_one.return_value = 0
    r.scalar_one_or_none.return_value = None
    return r


def _make_quality_result():
    r = MagicMock()
    # (avg_hfr, avg_eccentricity, best_hfr)
    r.one.return_value = (None, None, None)
    r.all.return_value = []
    r.first.return_value = None
    r.scalar_one.return_value = 0
    r.scalar_one_or_none.return_value = None
    return r


def _make_default_result():
    r = MagicMock()
    r.one.return_value = (0,)
    r.all.return_value = []
    r.first.return_value = None
    r.scalar_one.return_value = 0
    r.scalar_one_or_none.return_value = None
    return r


def _make_mock_session_for_stats():
    """Build a mock session that returns plausible empty results for all get_stats queries.

    The internal stats queries open their own async_session() contexts (patched separately).
    This session is used only for the injected get_session dep (load_alias_maps).
    """
    session = AsyncMock()
    # load_alias_maps uses scalar_one_or_none -> None, returning empty maps
    session.execute = AsyncMock(side_effect=lambda *a, **kw: _make_default_result())
    return session


def _make_async_session_cm():
    """Return an async context manager factory that yields an appropriate mock session.

    The stats endpoint calls async_session() once per internal query coroutine.
    Each session's execute() must return a result whose .one() tuple has the right
    length for that query.  The calls arrive in the order defined by asyncio.gather
    in stats.py:
        0: overview (6-tuple), 1: cameras (all), 2: telescopes (all),
        3: equipment_perf (all), 4: filter_usage (all), 5: timeline_monthly (all),
        6: site_coords/first (first), 7: timeline_weekly (all), 8: timeline_daily (all),
        9: top_targets (all), 10: data_quality (3-tuple), 11: hfr_buckets (8-tuple),
        12: db_size (scalar_one), 13: ingest_history (all).
    """
    # _extract_site_coords is patched separately to return None, so _query_site_coords
    # still opens one async_session() internally before calling the patched function.
    # Order matches the asyncio.gather() call sequence in stats.py.
    _results = [
        _make_overview_result(),   # 0 _query_overview
        _make_default_result(),    # 1 _query_cameras
        _make_default_result(),    # 2 _query_telescopes
        _make_default_result(),    # 3 _query_equipment_perf
        _make_default_result(),    # 4 _query_filter_usage
        _make_default_result(),    # 5 _query_timeline_monthly
        _make_default_result(),    # 6 _query_site_coords (session opened even if fn is patched)
        _make_default_result(),    # 7 _query_timeline_weekly
        _make_default_result(),    # 8 _query_timeline_daily
        _make_default_result(),    # 9 _query_top_targets
        _make_quality_result(),    # 10 _query_data_quality
        _make_bucket_result(),     # 11 _query_hfr_buckets
        _make_default_result(),    # 12 _query_db_size
        _make_default_result(),    # 13 _query_ingest_history
    ]
    _call_count = [0]

    @asynccontextmanager
    async def _cm():
        idx = _call_count[0]
        _call_count[0] += 1
        result = _results[idx] if idx < len(_results) else _make_default_result()
        session = AsyncMock()
        session.execute = AsyncMock(return_value=result)
        yield session
    return _cm


def _make_async_redis_cm():
    """Return an async context manager factory that yields a mock Redis client."""
    @asynccontextmanager
    async def _cm():
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=None)  # no cached stats
        redis.setex = AsyncMock()
        yield redis
    return _cm


@pytest.mark.asyncio
async def test_stats_has_timeline_fields():
    """Verify /stats returns all three timeline granularities and site_coords."""
    session = _make_mock_session_for_stats()
    user = _make_admin_user()

    async def override_session():
        yield session

    async def override_user():
        return user

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_current_user] = override_user

    try:
        with patch("app.api.stats.async_session", side_effect=_make_async_session_cm()), \
             patch("app.api.stats.async_redis", side_effect=_make_async_redis_cm()), \
             patch("app.api.stats._extract_site_coords", new=AsyncMock(return_value=None)):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/api/stats")

        assert resp.status_code == 200
        data = resp.json()

        assert "timeline" in data
        assert isinstance(data["timeline"], list)

        assert "timeline_monthly" in data
        assert "timeline_weekly" in data
        assert "timeline_daily" in data
        assert "site_coords" in data

        assert isinstance(data["timeline_monthly"], list)
        assert isinstance(data["timeline_weekly"], list)
        assert isinstance(data["timeline_daily"], list)
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_timeline_detail_entry_shape():
    """Verify TimelineDetailEntry has period, integration_seconds, efficiency_pct."""
    session = _make_mock_session_for_stats()
    user = _make_admin_user()

    async def override_session():
        yield session

    async def override_user():
        return user

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_current_user] = override_user

    try:
        with patch("app.api.stats.async_session", side_effect=_make_async_session_cm()), \
             patch("app.api.stats.async_redis", side_effect=_make_async_redis_cm()), \
             patch("app.api.stats._extract_site_coords", new=AsyncMock(return_value=None)):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/api/stats")

        data = resp.json()

        for key in ("timeline_monthly", "timeline_weekly", "timeline_daily"):
            for entry in data[key]:
                assert "period" in entry
                assert "integration_seconds" in entry
                assert "efficiency_pct" in entry
    finally:
        app.dependency_overrides.clear()
