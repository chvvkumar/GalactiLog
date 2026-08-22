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
    # (avg_hfr, avg_eccentricity, best_hfr,
    #  avg_hfr_arcsec, best_hfr_arcsec, unscaled_frame_count)
    r.one.return_value = (None, None, None, None, None, 0)
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
        _make_default_result(),    # 4 _query_equipment_mad
        _make_default_result(),    # 5 _query_filter_usage
        _make_default_result(),    # 6 _query_timeline_monthly
        _make_default_result(),    # 7 _query_site_coords (session opened even if fn is patched)
        _make_default_result(),    # 8 _query_timeline_weekly
        _make_default_result(),    # 9 _query_timeline_daily
        _make_default_result(),    # 10 _query_top_targets
        _make_quality_result(),    # 11 _query_data_quality
        _make_bucket_result(),     # 12 _query_hfr_buckets
        _make_default_result(),    # 13 _query_db_size
        _make_default_result(),    # 14 _query_ingest_history
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


def _make_perf_row(tel, cam, filt, hfr_vals, ecc_vals, fwhm_vals):
    """Mimic a row from _query_equipment_perf (per-group medians only)."""
    import statistics
    row = MagicMock()
    row.telescope = tel
    row.camera = cam
    row.filter_used = filt
    row.frame_count = len(hfr_vals)
    row.total_seconds = 300.0 * len(hfr_vals)
    row.med_hfr = statistics.median(hfr_vals) if hfr_vals else None
    row.best_hfr = min(hfr_vals) if hfr_vals else None
    row.med_ecc = statistics.median(ecc_vals) if ecc_vals else None
    row.med_fwhm = statistics.median(fwhm_vals) if fwhm_vals else None
    # Set explicitly: MagicMock implements __int__, so an unset attribute would
    # be coerced to 1 by pydantic instead of surfacing as a missing field.
    row.fwhm_n = len(fwhm_vals)
    return row


def _make_mad_row(norm_tel, norm_cam, mad_hfr, mad_ecc, mad_fwhm,
                  med_hfr=None, med_ecc=None, med_fwhm=None):
    """Mimic a row from _query_equipment_mad.

    This query returns both the MADs and the per-combo medians: all three of
    median_hfr, median_eccentricity and median_fwhm on an equipment_performance
    row now come from here rather than from a weighted blend of the per-filter
    medians, so all three must be set.
    """
    row = MagicMock()
    row.norm_tel = norm_tel
    row.norm_cam = norm_cam
    row.mad_hfr = mad_hfr
    row.mad_ecc = mad_ecc
    row.mad_fwhm = mad_fwhm
    # Set explicitly: MagicMock implements __float__, so an unset attribute
    # would be coerced to 1.0 rather than surfacing as a missing field.
    row.med_hfr = med_hfr
    row.med_ecc = med_ecc
    row.med_fwhm = med_fwhm
    return row


def _make_perf_result(rows):
    r = MagicMock()
    r.all.return_value = rows
    r.one.return_value = (0,)
    r.first.return_value = None
    r.scalar_one.return_value = 0
    r.scalar_one_or_none.return_value = None
    return r


def _make_async_session_cm_with_perf(perf_rows, mad_rows=None):
    _results = [
        _make_overview_result(),
        _make_default_result(),
        _make_default_result(),
        _make_perf_result(perf_rows),          # 3 _query_equipment_perf
        _make_perf_result(mad_rows or []),     # 4 _query_equipment_mad
        _make_default_result(),
        _make_default_result(),
        _make_default_result(),
        _make_default_result(),
        _make_default_result(),
        _make_default_result(),
        _make_quality_result(),
        _make_bucket_result(),
        _make_default_result(),
        _make_default_result(),
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


@pytest.mark.asyncio
async def test_equipment_combo_has_mad_fields():
    """equipment_performance combos expose mad_hfr/mad_eccentricity/mad_fwhm."""
    session = _make_mock_session_for_stats()
    user = _make_admin_user()

    perf_rows = [
        _make_perf_row(
            "Esprit 150", "ASI2600MM", "Ha",
            hfr_vals=[2.0, 2.4, 2.2, 2.1],
            ecc_vals=[0.30, 0.40, 0.35, 0.32],
            fwhm_vals=[3.0, 3.4, 3.2, 3.1],
        ),
    ]
    # MAD is now computed in SQL and returned by _query_equipment_mad, keyed by
    # normalized (telescope, camera). For [2.0,2.4,2.2,2.1] the median is 2.15
    # and median(|x-2.15|) = 0.10.
    mad_rows = [
        _make_mad_row("Esprit 150", "ASI2600MM", mad_hfr=0.10, mad_ecc=0.025,
                      mad_fwhm=0.15, med_hfr=2.15, med_ecc=0.335, med_fwhm=3.15),
    ]

    async def override_session():
        yield session

    async def override_user():
        return user

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_current_user] = override_user

    try:
        with patch("app.api.stats.async_session", side_effect=_make_async_session_cm_with_perf(perf_rows, mad_rows)), \
             patch("app.api.stats.async_redis", side_effect=_make_async_redis_cm()), \
             patch("app.api.stats._extract_site_coords", new=AsyncMock(return_value=None)):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/api/stats")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["equipment_performance"]) >= 1
        combo = data["equipment_performance"][0]
        assert "mad_hfr" in combo
        assert "mad_eccentricity" in combo
        assert "mad_fwhm" in combo
        # median of |x-2.15| for [2.0,2.4,2.2,2.1] -> |.15,.25,.05,.05| -> median 0.10
        assert combo["mad_hfr"] is not None
        assert abs(combo["mad_hfr"] - 0.10) < 1e-6
        # All three combo medians come from the mad query, not from a weighted
        # blend of the per-filter medians. FWHM carries the same number in both
        # of its fields because the stored value is already arcseconds.
        assert combo["median_hfr"] == 2.15
        assert combo["median_eccentricity"] == 0.34  # safe_round to 2 dp
        assert combo["median_fwhm"] == 3.15
        assert combo["median_fwhm_arcsec"] == 3.15
        assert combo["fwhm_frame_count"] == 4
    finally:
        app.dependency_overrides.clear()


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


def _make_populated_quality_result():
    r = MagicMock()
    # (avg_hfr, avg_eccentricity, best_hfr,
    #  avg_hfr_arcsec, best_hfr_arcsec, unscaled_frame_count)
    r.one.return_value = (2.0, 0.35, 1.5, 3.2, 2.4, 7)
    r.all.return_value = []
    r.first.return_value = None
    r.scalar_one.return_value = 0
    r.scalar_one_or_none.return_value = None
    return r


def _make_arcsec_bucket_result():
    r = MagicMock()
    # 16 half-arcsec buckets 0-8 plus one overflow bucket (17 counts)
    counts = [0] * 17
    counts[4] = 3   # 2.0-2.5
    counts[16] = 1  # 8.0+
    r.one.return_value = tuple(counts)
    r.all.return_value = []
    r.first.return_value = None
    r.scalar_one.return_value = 0
    r.scalar_one_or_none.return_value = None
    return r


def _make_ecc_source_result():
    r = MagicMock()
    # (eccentricity_source, count, avg) per source group
    r.all.return_value = [("csv", 10, 0.31), ("header", 4, 0.55)]
    r.one.return_value = (0,)
    r.first.return_value = None
    r.scalar_one.return_value = 0
    r.scalar_one_or_none.return_value = None
    return r


def _make_async_session_cm_arcsec():
    """cm factory with populated data-quality / arcsec-histogram / ecc-source results."""
    _results = [
        _make_overview_result(),          # 0 _query_overview
        _make_default_result(),           # 1 _query_cameras
        _make_default_result(),           # 2 _query_telescopes
        _make_default_result(),           # 3 _query_equipment_perf
        _make_default_result(),           # 4 _query_equipment_mad
        _make_default_result(),           # 5 _query_filter_usage
        _make_default_result(),           # 6 _query_timeline_monthly
        _make_default_result(),           # 7 _query_site_coords
        _make_default_result(),           # 8 _query_timeline_weekly
        _make_default_result(),           # 9 _query_timeline_daily
        _make_default_result(),           # 10 _query_top_targets
        _make_populated_quality_result(), # 11 _query_data_quality
        _make_bucket_result(),            # 12 _query_hfr_buckets
        _make_default_result(),           # 13 _query_db_size
        _make_default_result(),           # 14 _query_ingest_history
        _make_default_result(),           # 15 _query_fits_bytes
        _make_default_result(),           # 16 _query_all_frames
        _make_arcsec_bucket_result(),     # 17 _query_hfr_arcsec_buckets
        _make_ecc_source_result(),        # 18 _query_ecc_sources
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


@pytest.mark.asyncio
async def test_data_quality_arcsec_fields():
    """data_quality exposes arcsec aggregates, unscaled count, arcsec histogram,
    and a modal-source-restricted eccentricity average with exclusion count."""
    session = _make_mock_session_for_stats()
    user = _make_admin_user()

    async def override_session():
        yield session

    async def override_user():
        return user

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_current_user] = override_user

    try:
        with patch("app.api.stats.async_session", side_effect=_make_async_session_cm_arcsec()), \
             patch("app.api.stats.async_redis", side_effect=_make_async_redis_cm()), \
             patch("app.api.stats._extract_site_coords", new=AsyncMock(return_value=None)):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/api/stats")

        assert resp.status_code == 200
        dq = resp.json()["data_quality"]

        assert dq["avg_hfr"] == 2.0
        assert dq["best_hfr"] == 1.5
        assert dq["avg_hfr_arcsec"] == 3.2
        assert dq["best_hfr_arcsec"] == 2.4
        assert dq["unscaled_frame_count"] == 7

        # Arcsec histogram: only non-empty buckets are emitted
        hist = {b["bucket"]: b["count"] for b in dq["hfr_arcsec_hist"]}
        assert hist == {"2.0-2.5": 3, "8.0+": 1}

        # Eccentricity restricted to the modal source ("csv", 10 frames,
        # avg 0.31); the 4 "header" frames are excluded, not pooled.
        assert dq["avg_eccentricity"] == 0.31
        assert dq["ecc_excluded_count"] == 4
    finally:
        app.dependency_overrides.clear()
