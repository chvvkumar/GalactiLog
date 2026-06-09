"""Tests for analysis API endpoints (ARCH-4)."""
import uuid
import pytest
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.database import get_session
from app.api.deps import get_current_user
from app.models.user import User, UserRole


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _admin_user():
    u = MagicMock(spec=User)
    u.id = uuid.uuid4()
    u.role = UserRole.admin
    u.is_active = True
    return u


def _mock_session_with_rows(rows):
    """Return an AsyncMock session whose execute() returns rows."""
    result = MagicMock()
    result.all.return_value = rows
    result.scalars.return_value.all.return_value = rows
    result.one.return_value = rows[0] if rows else MagicMock()
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result)
    return session


def _override_user(user):
    async def _dep():
        return user
    return _dep


def _override_session(session):
    async def _dep():
        yield session
    return _dep


def _make_cache_miss_patch():
    """Return a context manager that patches async_redis to always miss."""
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=None)
    mock_redis.setex = AsyncMock()

    @asynccontextmanager
    async def _ctx():
        yield mock_redis

    return patch("app.services.cache.async_redis", _ctx)


# ---------------------------------------------------------------------------
# /api/analysis/filters
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_filters_returns_list():
    user = _admin_user()
    result = MagicMock()
    result.scalars.return_value.all.return_value = ["Ha", "OIII", "SII"]
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result)

    app.dependency_overrides[get_current_user] = _override_user(user)
    app.dependency_overrides[get_session] = _override_session(session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/analysis/filters")

    app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json() == ["Ha", "OIII", "SII"]


# ---------------------------------------------------------------------------
# /api/analysis/correlation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_correlation_bad_metric_returns_400():
    user = _admin_user()
    session = AsyncMock()

    app.dependency_overrides[get_current_user] = _override_user(user)
    app.dependency_overrides[get_session] = _override_session(session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/analysis/correlation?x_metric=bad&y_metric=hfr")

    app.dependency_overrides.clear()
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_get_correlation_empty_data():
    user = _admin_user()
    result = MagicMock()
    result.all.return_value = []
    # Second call is for target name resolution.
    tgt_result = MagicMock()
    tgt_result.all.return_value = []
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[result, tgt_result])

    app.dependency_overrides[get_current_user] = _override_user(user)
    app.dependency_overrides[get_session] = _override_session(session)

    with _make_cache_miss_patch():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/analysis/correlation?x_metric=humidity&y_metric=hfr")

    app.dependency_overrides.clear()
    assert resp.status_code == 200
    body = resp.json()
    assert body["x_metric"] == "humidity"
    assert body["y_metric"] == "hfr"
    assert body["points"] == []
    assert body["trend"] is None


# ---------------------------------------------------------------------------
# /api/analysis/distribution
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_distribution_bad_metric_returns_400():
    user = _admin_user()
    session = AsyncMock()

    app.dependency_overrides[get_current_user] = _override_user(user)
    app.dependency_overrides[get_session] = _override_session(session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/analysis/distribution?metric=bad")

    app.dependency_overrides.clear()
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_get_distribution_insufficient_data():
    user = _admin_user()
    row = MagicMock()
    row.val = 1.5
    row.night = "2024-01-01"
    row.resolved_target_id = None
    result = MagicMock()
    result.all.return_value = [row]  # only one point
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result)

    app.dependency_overrides[get_current_user] = _override_user(user)
    app.dependency_overrides[get_session] = _override_session(session)

    with _make_cache_miss_patch():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/analysis/distribution?metric=hfr")

    app.dependency_overrides.clear()
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_get_distribution_returns_bins():
    user = _admin_user()

    rows = []
    for v in [1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5]:
        row = MagicMock()
        row.val = v
        row.night = "2024-01-01"
        row.resolved_target_id = None
        rows.append(row)

    result = MagicMock()
    result.all.return_value = rows
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result)

    app.dependency_overrides[get_current_user] = _override_user(user)
    app.dependency_overrides[get_session] = _override_session(session)

    with _make_cache_miss_patch():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/analysis/distribution?metric=hfr")

    app.dependency_overrides.clear()
    assert resp.status_code == 200
    body = resp.json()
    assert body["metric"] == "hfr"
    assert len(body["bins"]) > 0
    assert "stats" in body
    assert body["stats"]["count"] == 8


# ---------------------------------------------------------------------------
# /api/analysis/boxplot
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_boxplot_bad_metric_returns_400():
    user = _admin_user()
    session = AsyncMock()

    app.dependency_overrides[get_current_user] = _override_user(user)
    app.dependency_overrides[get_session] = _override_session(session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/analysis/boxplot?metric=bad&group_by=filter")

    app.dependency_overrides.clear()
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_get_boxplot_empty_groups():
    user = _admin_user()

    # alias maps result: filter_map={}, cam_map={}, tel_map={}
    alias_result = MagicMock()
    alias_result.all.return_value = []

    data_result = MagicMock()
    data_result.all.return_value = []

    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[data_result, alias_result, alias_result, alias_result])

    app.dependency_overrides[get_current_user] = _override_user(user)
    app.dependency_overrides[get_session] = _override_session(session)

    with _make_cache_miss_patch():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/analysis/boxplot?metric=hfr&group_by=filter")

    app.dependency_overrides.clear()
    assert resp.status_code == 200
    body = resp.json()
    assert body["groups"] == []
    assert body["metric"] == "hfr"


# ---------------------------------------------------------------------------
# /api/analysis/timeseries
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_timeseries_bad_metric_returns_400():
    user = _admin_user()
    session = AsyncMock()

    app.dependency_overrides[get_current_user] = _override_user(user)
    app.dependency_overrides[get_session] = _override_session(session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/analysis/timeseries?metric=bad")

    app.dependency_overrides.clear()
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_get_timeseries_empty_data():
    user = _admin_user()
    data_result = MagicMock()
    data_result.all.return_value = []
    tgt_result = MagicMock()
    tgt_result.all.return_value = []
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[data_result, tgt_result])

    app.dependency_overrides[get_current_user] = _override_user(user)
    app.dependency_overrides[get_session] = _override_session(session)

    with _make_cache_miss_patch():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/analysis/timeseries?metric=hfr")

    app.dependency_overrides.clear()
    assert resp.status_code == 200
    body = resp.json()
    assert body["metric"] == "hfr"
    assert body["points"] == []
    assert body["ma_7"] == []
    assert body["ma_30"] == []


# ---------------------------------------------------------------------------
# /api/analysis/matrix
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_matrix_returns_cells():
    """Matrix endpoint must return x_metrics, y_metrics, and cells."""
    user = _admin_user()

    # cached_json will call async_redis first; mock it to miss so _compute runs.
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=None)
    mock_redis.setex = AsyncMock()

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _mock_async_redis():
        yield mock_redis

    # Build a row mock that returns None for all corr() columns and 0 for count().
    # getattr on an unconfigured MagicMock attribute returns a new MagicMock by
    # default; explicit None assignment covers the exact attribute names used.
    from app.api.analysis import X_METRICS, Y_METRICS

    row = MagicMock()
    for xm in X_METRICS:
        for ym in Y_METRICS:
            setattr(row, f"r_{xm}__{ym}", None)
            setattr(row, f"n_{xm}__{ym}", 0)

    # alias maps + data query
    alias_result = MagicMock()
    alias_result.all.return_value = []
    data_result = MagicMock()
    data_result.one.return_value = row
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[data_result, alias_result, alias_result, alias_result])

    app.dependency_overrides[get_current_user] = _override_user(user)
    app.dependency_overrides[get_session] = _override_session(session)

    with patch("app.services.cache.async_redis", _mock_async_redis):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/analysis/matrix")

    app.dependency_overrides.clear()
    assert resp.status_code == 200
    body = resp.json()
    assert "cells" in body
    assert "x_metrics" in body
    assert "y_metrics" in body


# ---------------------------------------------------------------------------
# Cache behaviour for /api/analysis/distribution
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_distribution_cache_miss_computes_and_stores():
    """On a Redis miss the endpoint must compute the result and write it to Redis."""
    user = _admin_user()

    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=None)  # cache miss
    mock_redis.setex = AsyncMock()

    @asynccontextmanager
    async def _mock_async_redis():
        yield mock_redis

    rows = []
    for v in [1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5]:
        row = MagicMock()
        row.val = v
        row.night = "2024-01-01"
        row.resolved_target_id = None
        rows.append(row)

    result = MagicMock()
    result.all.return_value = rows
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result)

    app.dependency_overrides[get_current_user] = _override_user(user)
    app.dependency_overrides[get_session] = _override_session(session)

    with patch("app.services.cache.async_redis", _mock_async_redis):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/analysis/distribution?metric=hfr")

    app.dependency_overrides.clear()
    assert resp.status_code == 200
    body = resp.json()
    assert body["metric"] == "hfr"
    assert len(body["bins"]) > 0
    # Redis get was called (miss) and setex was called to store the result.
    mock_redis.get.assert_called_once()
    mock_redis.setex.assert_called_once()
    stored_key = mock_redis.setex.call_args[0][0]
    assert "distribution" in stored_key
    assert "hfr" in stored_key


@pytest.mark.asyncio
async def test_distribution_cache_hit_skips_compute():
    """On a Redis hit the endpoint must return the cached value without hitting the DB."""
    import json as _json
    user = _admin_user()

    # Pre-build a valid cached payload.
    cached_payload = {
        "bins": [{"bin_start": 1.0, "bin_end": 2.0, "count": 4}],
        "stats": {
            "count": 8,
            "min": 1.0,
            "max": 4.5,
            "mean": 2.75,
            "median": 2.75,
            "std_dev": 1.224745,
        },
        "metric": "hfr",
        "skewness": 0.0,
    }

    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=_json.dumps(cached_payload).encode())
    mock_redis.setex = AsyncMock()

    @asynccontextmanager
    async def _mock_async_redis():
        yield mock_redis

    session = AsyncMock()

    app.dependency_overrides[get_current_user] = _override_user(user)
    app.dependency_overrides[get_session] = _override_session(session)

    with patch("app.services.cache.async_redis", _mock_async_redis):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/analysis/distribution?metric=hfr")

    app.dependency_overrides.clear()
    assert resp.status_code == 200
    body = resp.json()
    assert body["metric"] == "hfr"
    # DB was never queried because the cache provided the result.
    session.execute.assert_not_called()
    # Redis setex must NOT have been called (no re-store on a hit).
    mock_redis.setex.assert_not_called()


# ---------------------------------------------------------------------------
# /api/analysis/compare
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_compare_bad_metric_returns_400():
    user = _admin_user()
    session = AsyncMock()

    app.dependency_overrides[get_current_user] = _override_user(user)
    app.dependency_overrides[get_session] = _override_session(session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/api/analysis/compare?metric=bad&mode=filter&group_a=Ha&group_b=OIII"
        )

    app.dependency_overrides.clear()
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_get_compare_insufficient_data():
    user = _admin_user()

    # Both groups return empty rows.
    empty_result = MagicMock()
    empty_result.all.return_value = []
    session = AsyncMock()
    session.execute = AsyncMock(return_value=empty_result)

    app.dependency_overrides[get_current_user] = _override_user(user)
    app.dependency_overrides[get_session] = _override_session(session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/api/analysis/compare?metric=hfr&mode=filter&group_a=Ha&group_b=OIII"
        )

    app.dependency_overrides.clear()
    assert resp.status_code == 400
