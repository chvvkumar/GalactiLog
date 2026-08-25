"""Tests for analysis API endpoints (ARCH-4)."""
import statistics
import uuid
from datetime import date, datetime, timedelta, timezone

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
    # Contract fields present even with no data.
    assert body["total_count"] == 0
    assert body["sampled_count"] == 0


@pytest.mark.asyncio
async def test_get_correlation_downsamples_over_cap():
    """Frame granularity over the 5,000-point cap returns a downsampled point
    set, but total_count reflects the full match and trend/stats span all rows."""
    user = _admin_user()

    n = 12000
    frame_rows = [
        MagicMock(x_val=float(i % 100), y_val=float((i * 7) % 100),
                  night="2024-01-01", resolved_target_id=None)
        for i in range(n)
    ]
    tgt_result = MagicMock()
    tgt_result.all.return_value = []
    data_result = MagicMock()
    data_result.all.return_value = frame_rows
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[data_result, tgt_result])

    app.dependency_overrides[get_current_user] = _override_user(user)
    app.dependency_overrides[get_session] = _override_session(session)

    with _make_cache_miss_patch():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/api/analysis/correlation?x_metric=humidity&y_metric=hfr&granularity=frame"
            )

    app.dependency_overrides.clear()
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_count"] == n
    assert body["sampled_count"] == 5000
    assert len(body["points"]) == 5000
    # Trend is computed over the full set (needs >= 3 points).
    assert body["trend"] is not None


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


def _row(val, scale):
    r = MagicMock()
    r.val = val
    r.scale = scale
    return r


def _compare_session(rows_a, rows_b):
    """Session whose two executes return group A rows then group B rows."""
    res_a = MagicMock()
    res_a.all.return_value = rows_a
    res_b = MagicMock()
    res_b.all.return_value = rows_b
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[res_a, res_b])
    return session


@pytest.mark.asyncio
async def test_get_compare_pixel_metric_uses_arcsec_when_scaled():
    """With plate scale on both sides, the verdict runs on arcsec medians and
    the arcsec median fields are populated."""
    user = _admin_user()
    # Group A: 2.0..2.6 px at 1.5 arcsec/px -> arcsec median 3.3
    rows_a = [_row(v, 1.5) for v in [2.0, 2.0, 2.2, 2.4, 2.6]]
    # Group B: 4.0 px (worse in px!) at 0.5 arcsec/px -> arcsec median 2.0
    rows_b = [_row(4.0, 0.5) for _ in range(5)]
    session = _compare_session(rows_a, rows_b)

    app.dependency_overrides[get_current_user] = _override_user(user)
    app.dependency_overrides[get_session] = _override_session(session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/api/analysis/compare?metric=hfr&mode=filter&group_a=Ha&group_b=OIII"
        )

    app.dependency_overrides.clear()
    assert resp.status_code == 200
    data = resp.json()
    assert data["comparable"] is True
    assert data["median_hfr_arcsec_a"] == pytest.approx(3.3)
    assert data["median_hfr_arcsec_b"] == pytest.approx(2.0)
    # Group B wins in arcsec even though its px median (4.0) is larger than
    # group A's (2.2): that is the whole point of the conversion.
    assert data["verdict"].startswith("OIII has ")
    assert "(arcsec)" in data["verdict"]


@pytest.mark.asyncio
async def test_get_compare_pixel_metric_not_comparable_without_scale():
    """When one side lacks plate-scale coverage the response says so instead
    of returning a bogus % figure."""
    user = _admin_user()
    rows_a = [_row(v, 1.5) for v in [2.0, 2.0, 2.2, 2.4, 2.6]]
    rows_b = [_row(4.0, None) for _ in range(5)]  # arcsec_per_pixel NULL
    session = _compare_session(rows_a, rows_b)

    app.dependency_overrides[get_current_user] = _override_user(user)
    app.dependency_overrides[get_session] = _override_session(session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/api/analysis/compare?metric=hfr&mode=filter&group_a=Ha&group_b=OIII"
        )

    app.dependency_overrides.clear()
    assert resp.status_code == 200
    data = resp.json()
    assert data["comparable"] is False
    assert data["median_hfr_arcsec_a"] is None
    assert data["median_hfr_arcsec_b"] is None
    assert "%" not in data["verdict"]
    assert "cannot be compared" in data["verdict"]
    # px box plots stay populated for backward compatibility
    assert data["group_a"]["stats"]["count"] == 5
    assert data["group_b"]["stats"]["count"] == 5


@pytest.mark.asyncio
async def test_get_compare_non_pixel_metric_unaffected():
    """Non-pixel metrics keep the original px-domain verdict and stay comparable."""
    user = _admin_user()
    rows_a = [_row(v, None) for v in [0.30, 0.32, 0.34, 0.36, 0.38]]
    rows_b = [_row(v, None) for v in [0.50, 0.52, 0.54, 0.56, 0.58]]
    session = _compare_session(rows_a, rows_b)

    app.dependency_overrides[get_current_user] = _override_user(user)
    app.dependency_overrides[get_session] = _override_session(session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/api/analysis/compare?metric=eccentricity&mode=filter&group_a=Ha&group_b=OIII"
        )

    app.dependency_overrides.clear()
    assert resp.status_code == 200
    data = resp.json()
    assert data["comparable"] is True
    assert data["median_hfr_arcsec_a"] is None
    assert data["median_hfr_arcsec_b"] is None
    assert "lower median than" in data["verdict"]
    assert "(arcsec)" not in data["verdict"]


def test_the_guiding_metrics_are_column_backed_and_source_agnostic():
    """Analysis reads the three guiding columns, not a source. A phd2-sourced
    row and a csv-sourced row are the same row to every consumer here, which
    is the whole point of filling the existing columns rather than adding
    parallel ones."""
    from app.api.analysis import METRIC_MAP, Y_METRICS
    from app.models import Image

    assert METRIC_MAP["guiding_rms"] is Image.guiding_rms_arcsec
    assert METRIC_MAP["guiding_rms_ra"] is Image.guiding_rms_ra_arcsec
    assert METRIC_MAP["guiding_rms_dec"] is Image.guiding_rms_dec_arcsec
    for name in ("guiding_rms", "guiding_rms_ra", "guiding_rms_dec"):
        assert name in Y_METRICS


def test_the_guiding_metrics_are_not_plate_scale_converted():
    """They are already in arcsec, and so is the CSV-sourced `fwhm` column.
    HFR is the only pixel metric."""
    from app.api.analysis import METRIC_MAP, _PIXEL_METRICS

    assert _PIXEL_METRICS == {"hfr"}
    assert not _PIXEL_METRICS & {
        "fwhm", "guiding_rms", "guiding_rms_ra", "guiding_rms_dec"
    }
    assert set(_PIXEL_METRICS) <= set(METRIC_MAP)


@pytest.mark.asyncio
async def test_distribution_counts_a_phd2_row_and_a_csv_row_alike():
    """The metric-map identity above survives a provenance filter added to the
    query, so it cannot guard the regression this phase actually fears. This
    drives the endpoint instead: four guiding rows, two stamped phd2 and two
    stamped csv, and every one of them has to reach the response.

    The mocked session returns its rows whatever it is asked, so the count
    assertions alone would not notice a WHERE clause. The statement the
    endpoint executed is therefore captured and compiled, and the compiled SQL
    must select the arcsec column and must never mention the provenance
    column. That fails for any expression that filters on the source, not only
    for the one spelling of it."""
    from sqlalchemy.dialects import postgresql

    user = _admin_user()

    rows = []
    for value, source in [(0.40, "phd2"), (0.45, "phd2"), (0.85, "csv"), (0.90, "csv")]:
        row = MagicMock()
        row.val = value
        row.night = "2026-07-14"
        row.resolved_target_id = None
        row.guiding_rms_source = source
        rows.append(row)

    executed = []
    result = MagicMock()
    result.all.return_value = rows

    async def _execute(stmt, *args, **kwargs):
        executed.append(stmt)
        return result

    session = AsyncMock()
    session.execute = _execute

    app.dependency_overrides[get_current_user] = _override_user(user)
    app.dependency_overrides[get_session] = _override_session(session)

    with _make_cache_miss_patch():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/analysis/distribution?metric=guiding_rms")

    app.dependency_overrides.clear()
    assert resp.status_code == 200
    data = resp.json()
    assert data["metric"] == "guiding_rms"
    # Both stamps counted: dropping either pair changes the count and collapses
    # the range onto one of the two clusters.
    assert data["stats"]["count"] == 4
    assert data["stats"]["min"] == 0.40
    assert data["stats"]["max"] == 0.90
    assert sum(b["count"] for b in data["bins"]) == 4

    assert len(executed) == 1
    sql = str(executed[0].compile(dialect=postgresql.dialect()))
    assert "images.guiding_rms_arcsec" in sql
    assert "guiding_rms_source" not in sql


# ---------------------------------------------------------------------------
# PHD2 night metrics as correlation X (DB-backed)
# ---------------------------------------------------------------------------
#
# Requires a real Postgres (test:test@localhost:5432/test_catalog) with the
# Alembic schema applied. Pattern from test_stats_fwhm_timeline.py.

import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings as _settings
from app.models import Image
from app.models.phd2 import Phd2Log, Phd2Session
from app.models.user_settings import UserSettings, SETTINGS_ROW_ID
from app.services.normalization import invalidate_alias_cache
from app.services.phd2_metrics import _weighted_rms, MIN_FRAMES

PHD2_NIGHT = date(2024, 3, 1)
NO_PHD2_NIGHT = date(2024, 3, 2)
PHD2_NIGHT_FWHM = [2.0, 3.0, 4.0]

# (raw telescope spelling, frame_count, drop_count, rms_total, rms_ra, rms_dec, snr)
# The alias spelling and the canonical one must merge into one night; the
# 50-frame session is under MIN_FRAMES and only counts toward star-lost and SNR.
PHD2_SESSIONS = [
    ("Askar_SQA55", 300, 3, 0.5, 0.3, 0.4, 30.0),
    ("SQA55", 200, 7, 1.0, 0.6, 0.8, 50.0),
    ("SQA55", 50, 5, 9.0, 9.0, 9.0, 10.0),
]
assert PHD2_SESSIONS[2][1] < MIN_FRAMES


class _SessionRow:
    def __init__(self, frame_count, rms_total_arcsec, rms_ra_arcsec, rms_dec_arcsec):
        self.frame_count = frame_count
        self.rms_total_arcsec = rms_total_arcsec
        self.rms_ra_arcsec = rms_ra_arcsec
        self.rms_dec_arcsec = rms_dec_arcsec


_EXPECTED_ROWS = [_SessionRow(fc, t, r, d) for _, fc, _, t, r, d, _ in PHD2_SESSIONS]
EXPECTED_RMS_TOTAL = _weighted_rms(_EXPECTED_ROWS, "rms_total_arcsec")
EXPECTED_RMS_RA = _weighted_rms(_EXPECTED_ROWS, "rms_ra_arcsec")
EXPECTED_RMS_DEC = _weighted_rms(_EXPECTED_ROWS, "rms_dec_arcsec")
_TOTAL_FRAMES = sum(s[1] for s in PHD2_SESSIONS)
EXPECTED_STAR_LOST_PCT = 100.0 * sum(s[2] for s in PHD2_SESSIONS) / _TOTAL_FRAMES
EXPECTED_SNR_MEAN = sum(s[6] * s[1] for s in PHD2_SESSIONS) / _TOTAL_FRAMES


def _light(**kw):
    defaults = dict(
        id=uuid.uuid4(),
        file_path=f"/data/{uuid.uuid4()}.fits",
        file_name="x.fits",
        image_type="LIGHT",
        exposure_time=300.0,
        camera="ASI2600MM Pro",
        filter_used="Ha",
    )
    defaults.update(kw)
    return Image(**defaults)


async def _truncate_phd2(engine):
    async with engine.begin() as conn:
        await conn.execute(text(
            "TRUNCATE images, user_settings, phd2_logs RESTART IDENTITY CASCADE"
        ))


@pytest_asyncio.fixture
async def seeded_phd2_db():
    from app.database import engine as app_engine
    await app_engine.dispose()

    engine = create_async_engine(_settings.database_url, poolclass=None)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    await _truncate_phd2(engine)

    async with Session() as s:
        s.add(UserSettings(
            id=SETTINGS_ROW_ID,
            equipment={"telescopes": {"SQA55": {"aliases": ["Askar_SQA55"]}}},
        ))

        # Night with a mapped PHD2 night: three frames, canonical spelling.
        for i, fwhm in enumerate(PHD2_NIGHT_FWHM):
            s.add(_light(
                session_date=PHD2_NIGHT,
                capture_date=datetime(2024, 3, 1, 20, i, tzinfo=timezone.utc),
                telescope="SQA55", fwhm=fwhm,
            ))
        # Same night, a rig with no PHD2 sessions: must be dropped.
        s.add(_light(
            session_date=PHD2_NIGHT,
            capture_date=datetime(2024, 3, 1, 21, 0, tzinfo=timezone.utc),
            telescope="Other Scope", fwhm=9.0,
        ))
        # Same rig (alias spelling), a night with no PHD2 sessions: dropped.
        for i, fwhm in enumerate([5.0, 6.0]):
            s.add(_light(
                session_date=NO_PHD2_NIGHT,
                capture_date=datetime(2024, 3, 2, 20, i, tzinfo=timezone.utc),
                telescope="Askar_SQA55", fwhm=fwhm,
            ))

        log_id = uuid.uuid4()
        s.add(Phd2Log(id=log_id, file_path=f"/phd2/{log_id}.txt", parse_status="ok"))
        await s.flush()
        start = datetime(2024, 3, 2, 2, 0, tzinfo=timezone.utc)
        for i, (tel, fc, drops, rms_t, rms_ra, rms_dec, snr) in enumerate(PHD2_SESSIONS):
            s.add(Phd2Session(
                id=uuid.uuid4(), log_id=log_id, run_index=0, section_index=i,
                started_at_local=start.replace(tzinfo=None),
                started_at_utc=start,
                ended_at_utc=start + timedelta(seconds=fc),
                duration_s=float(fc),
                session_date=PHD2_NIGHT,
                telescope=tel,
                pixel_scale_arcsec=1.0,
                frame_count=fc, drop_count=drops,
                rms_total_arcsec=rms_t, rms_ra_arcsec=rms_ra, rms_dec_arcsec=rms_dec,
                snr_mean=snr,
                events=[],
            ))
        await s.commit()

    invalidate_alias_cache()

    async def _override_db():
        async with Session() as s:
            yield s

    app.dependency_overrides[get_session] = _override_db
    app.dependency_overrides[get_current_user] = _override_user(_admin_user())

    yield Session

    app.dependency_overrides.clear()
    invalidate_alias_cache()
    await _truncate_phd2(engine)
    await engine.dispose()
    await app_engine.dispose()


async def _correlation(x_metric, granularity="frame"):
    with _make_cache_miss_patch():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get(
                f"/api/analysis/correlation?x_metric={x_metric}&y_metric=fwhm"
                f"&granularity={granularity}"
            )


@pytest.mark.asyncio
async def test_correlation_phd2_rms_total_joins_only_mapped_nights(seeded_phd2_db):
    resp = await _correlation("phd2_rms_total")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["x_metric"] == "phd2_rms_total"
    assert body["total_count"] == len(PHD2_NIGHT_FWHM)
    assert sorted(p["y"] for p in body["points"]) == PHD2_NIGHT_FWHM
    assert {p["date"] for p in body["points"]} == {PHD2_NIGHT.isoformat()}
    for p in body["points"]:
        assert p["x"] == pytest.approx(EXPECTED_RMS_TOTAL, abs=1e-5)


@pytest.mark.asyncio
async def test_correlation_phd2_rms_axes(seeded_phd2_db):
    for metric, expected in [
        ("phd2_rms_ra", EXPECTED_RMS_RA),
        ("phd2_rms_dec", EXPECTED_RMS_DEC),
    ]:
        resp = await _correlation(metric)
        assert resp.status_code == 200, resp.text
        xs = {round(p["x"], 5) for p in resp.json()["points"]}
        assert xs == {round(expected, 5)}, metric


@pytest.mark.asyncio
async def test_correlation_phd2_star_lost_pct_uses_all_sessions(seeded_phd2_db):
    resp = await _correlation("phd2_star_lost_pct")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total_count"] == len(PHD2_NIGHT_FWHM)
    for p in body["points"]:
        assert p["x"] == pytest.approx(EXPECTED_STAR_LOST_PCT, abs=1e-6)


@pytest.mark.asyncio
async def test_correlation_phd2_snr_mean_is_frame_weighted(seeded_phd2_db):
    resp = await _correlation("phd2_snr_mean")
    assert resp.status_code == 200, resp.text
    for p in resp.json()["points"]:
        assert p["x"] == pytest.approx(EXPECTED_SNR_MEAN, abs=1e-6)


@pytest.mark.asyncio
async def test_correlation_phd2_session_granularity_keeps_night_value(seeded_phd2_db):
    resp = await _correlation("phd2_rms_total", granularity="session")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total_count"] == 1
    point = body["points"][0]
    assert point["x"] == pytest.approx(EXPECTED_RMS_TOTAL, abs=1e-5)
    assert point["y"] == pytest.approx(statistics.median(PHD2_NIGHT_FWHM))
    assert point["date"] == PHD2_NIGHT.isoformat()


@pytest.mark.asyncio
async def test_phd2_metrics_rejected_outside_correlation():
    """The phd2_* names are correlation-only X metrics: every other metric
    endpoint rejects them through its unknown-metric path, and they are not
    part of the matrix X list."""
    from app.api.analysis import METRIC_MAP, X_METRICS, PHD2_X_METRICS

    for name in PHD2_X_METRICS:
        assert name not in METRIC_MAP
        assert name not in X_METRICS

    app.dependency_overrides[get_current_user] = _override_user(_admin_user())
    app.dependency_overrides[get_session] = _override_session(AsyncMock())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        dist = await client.get("/api/analysis/distribution?metric=phd2_rms_total")
        ts = await client.get("/api/analysis/timeseries?metric=phd2_star_lost_pct")
        as_y = await client.get(
            "/api/analysis/correlation?x_metric=humidity&y_metric=phd2_rms_total"
        )
    app.dependency_overrides.clear()
    assert dist.status_code == 400
    assert ts.status_code == 400
    assert as_y.status_code == 400
