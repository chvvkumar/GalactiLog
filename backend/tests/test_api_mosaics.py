"""API tests for mosaic endpoints after the service extraction (ARCH-1/ARCH-7).

These exercise representative endpoints via dependency overrides for the DB
session and auth, asserting response shapes are unchanged by the refactor.
"""

import uuid

import pytest
from unittest.mock import AsyncMock, MagicMock
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.database import get_session
from app.api.deps import get_current_user, require_admin


def _override_session(mock_session):
    async def _gen():
        yield mock_session
    app.dependency_overrides[get_session] = _gen


@pytest.mark.asyncio
async def test_list_mosaics_empty_returns_200(viewer_user):
    """list_mosaics delegates to the service; empty DB yields an empty list."""
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)

    _override_session(mock_session)
    app.dependency_overrides[get_current_user] = lambda: viewer_user
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/mosaics")
        assert resp.status_code == 200, resp.text
        assert resp.json() == []
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_create_mosaic_returns_summary_shape(admin_user):
    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.flush = AsyncMock()
    mock_session.commit = AsyncMock()

    _override_session(mock_session)
    app.dependency_overrides[require_admin] = lambda: admin_user
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/api/mosaics", json={"name": "Veil Mosaic"})
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["name"] == "Veil Mosaic"
        assert data["panel_count"] == 0
        assert data["total_integration_seconds"] == 0
        assert data["total_frames"] == 0
        assert data["completion_pct"] == 0
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_mosaic_detail_not_found_returns_404(viewer_user):
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)

    _override_session(mock_session)
    app.dependency_overrides[get_current_user] = lambda: viewer_user
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(f"/api/mosaics/{uuid.uuid4()}")
        assert resp.status_code == 404
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_update_mosaic_not_found_returns_404(admin_user):
    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=None)

    _override_session(mock_session)
    app.dependency_overrides[require_admin] = lambda: admin_user
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.put(
                f"/api/mosaics/{uuid.uuid4()}", json={"name": "Renamed"}
            )
        assert resp.status_code == 404
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_update_mosaic_returns_status_ok(admin_user):
    mosaic = MagicMock()
    mosaic.name = "Old"
    mosaic.notes = None
    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=mosaic)
    mock_session.commit = AsyncMock()

    _override_session(mock_session)
    app.dependency_overrides[require_admin] = lambda: admin_user
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.put(
                f"/api/mosaics/{uuid.uuid4()}", json={"name": "New name"}
            )
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"status": "ok"}
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_suggestions_includes_new_fields_and_preview_panels(viewer_user):
    """The /suggestions endpoint surfaces confidence, discovery_source, flags,
    and preview_panels (built from geometry) with batched thumbnail URLs."""
    suggestion_id = uuid.uuid4()
    target_id = uuid.uuid4()

    suggestion = MagicMock()
    suggestion.id = suggestion_id
    suggestion.suggested_name = "Heart Nebula"
    suggestion.base_name = "Heart Nebula"
    suggestion.target_ids = [target_id]
    suggestion.panel_labels = ["Panel 1"]
    suggestion.panel_patterns = None
    suggestion.session_dates = None
    suggestion.status = "pending"
    suggestion.confidence = "high"
    suggestion.discovery_source = "both"
    suggestion.flags = ["irregular geometry"]
    suggestion.geometry = {
        "panels": [
            {"target_id": str(target_id), "label": "Panel 1", "ra": 38.2, "dec": 61.5},
        ],
        "pitches": [68.0],
        "fov_arcmin": 90.0,
    }

    # Result objects for each session.execute() call, in order:
    # 1) pending suggestions, 2) existing mosaic names, 3) target names,
    # 4) per-target thumbnail batch, 5) per-(target, pattern) thumbnail (one
    # distinct pair here), 6) per-panel session summary query.
    pending_result = MagicMock()
    pending_result.scalars.return_value.all.return_value = [suggestion]

    mosaic_names_result = MagicMock()
    mosaic_names_result.all.return_value = []

    target_names_result = MagicMock()
    target_names_result.all.return_value = [(target_id, "Heart Nebula")]

    thumb_result = MagicMock()
    thumb_result.all.return_value = [(target_id, "/data/thumbs/heart_target.jpg")]

    pattern_thumb_result = MagicMock()
    pattern_thumb_result.scalars.return_value.first.return_value = "/data/thumbs/heart_panel1.jpg"

    sessions_result = MagicMock()
    sessions_result.all.return_value = []

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(side_effect=[
        pending_result,
        mosaic_names_result,
        target_names_result,
        thumb_result,
        pattern_thumb_result,
        sessions_result,
    ])

    _override_session(mock_session)
    app.dependency_overrides[get_current_user] = lambda: viewer_user
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/mosaics/suggestions")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert len(data) == 1
        s = data[0]
        assert s["confidence"] == "high"
        assert s["discovery_source"] == "both"
        assert s["flags"] == ["irregular geometry"]
        assert len(s["preview_panels"]) == 1
        p = s["preview_panels"][0]
        assert p["target_id"] == str(target_id)
        assert p["panel_label"] == "Panel 1"
        assert p["ra"] == 38.2
        assert p["dec"] == 61.5
        # Pattern-matched frame wins over the per-target fallback.
        assert p["thumbnail_url"] == "/thumbnails/heart_panel1.jpg"
        assert p["grid_row"] is None
        assert p["grid_col"] is None
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_suggestions_shared_target_panels_get_distinct_thumbnails(viewer_user):
    """Two panels sharing one target_id (SIMBAD-merged) but with different
    object_patterns resolve to DIFFERENT preview thumbnails via per-panel
    pattern-aware frame selection."""
    suggestion_id = uuid.uuid4()
    target_id = uuid.uuid4()  # both panels merged into one target

    suggestion = MagicMock()
    suggestion.id = suggestion_id
    suggestion.suggested_name = "Veil Nebula"
    suggestion.base_name = "Veil Nebula"
    suggestion.target_ids = [target_id, target_id]
    suggestion.panel_labels = ["Panel 1", "Panel 2"]
    suggestion.panel_patterns = ["%Veil Nebula%1%", "%Veil Nebula%2%"]
    suggestion.session_dates = None
    suggestion.status = "pending"
    suggestion.confidence = "high"
    suggestion.discovery_source = "name"
    suggestion.flags = []
    suggestion.geometry = {
        "panels": [
            {"target_id": str(target_id), "label": "Panel 1", "ra": 311.6, "dec": 30.7},
            {"target_id": str(target_id), "label": "Panel 2", "ra": 312.1, "dec": 31.2},
        ],
        "pitches": [45.0],
        "fov_arcmin": 90.0,
    }

    pending_result = MagicMock()
    pending_result.scalars.return_value.all.return_value = [suggestion]

    mosaic_names_result = MagicMock()
    mosaic_names_result.all.return_value = []

    target_names_result = MagicMock()
    target_names_result.all.return_value = [(target_id, "NGC 6960")]

    # Per-target fallback batch: a single thumbnail for the shared target.
    thumb_result = MagicMock()
    thumb_result.all.return_value = [(target_id, "/data/thumbs/veil_target.jpg")]

    sessions_result = MagicMock()
    sessions_result.all.return_value = []

    call_log = {"n": 0}

    async def _execute(stmt, *args, **kwargs):
        call_log["n"] += 1
        n = call_log["n"]
        if n == 1:
            return pending_result
        if n == 2:
            return mosaic_names_result
        if n == 3:
            return target_names_result
        if n == 4:
            return thumb_result
        # Calls 5 and 6 are the two per-(target, pattern) thumbnail queries
        # (order depends on set iteration); call 7 is the session summary.
        params = stmt.compile().params
        pattern_vals = [v for v in params.values() if isinstance(v, str) and "Veil" in v]
        if pattern_vals and any(p.endswith("1%") for p in pattern_vals):
            result = MagicMock()
            result.scalars.return_value.first.return_value = "/data/thumbs/veil_panel1.jpg"
            return result
        if pattern_vals and any(p.endswith("2%") for p in pattern_vals):
            result = MagicMock()
            result.scalars.return_value.first.return_value = "/data/thumbs/veil_panel2.jpg"
            return result
        return sessions_result

    mock_session = AsyncMock()
    mock_session.execute = _execute

    _override_session(mock_session)
    app.dependency_overrides[get_current_user] = lambda: viewer_user
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/mosaics/suggestions")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert len(data) == 1
        panels = data[0]["preview_panels"]
        assert len(panels) == 2
        by_label = {p["panel_label"]: p["thumbnail_url"] for p in panels}
        assert by_label["Panel 1"] == "/thumbnails/veil_panel1.jpg"
        assert by_label["Panel 2"] == "/thumbnails/veil_panel2.jpg"
        # Both panels share a target but must not share a thumbnail.
        assert by_label["Panel 1"] != by_label["Panel 2"]
    finally:
        app.dependency_overrides.clear()


def test_ilike_pattern_matcher_is_ordered_and_contiguous():
    """The ILIKE->regex matcher respects segment ORDER, unlike a naive
    unordered substring check. Regression for the Sh2 119 cross-mapping bug."""
    from app.api.mosaics import _ilike_pattern_matches

    # Token-less legacy pattern: "%Sh2 119%1%" must NOT match "Sh2 119 Panel 2"
    # even though "1" appears inside "119".
    assert _ilike_pattern_matches("%Sh2 119%1%", "Sh2 119 Panel 1")
    assert not _ilike_pattern_matches("%Sh2 119%1%", "Sh2 119 Panel 2")
    assert _ilike_pattern_matches("%Sh2 119%2%", "Sh2 119 Panel 2")
    assert not _ilike_pattern_matches("%Sh2 119%2%", "Sh2 119 Panel 1")

    # Token pattern (detection now stores %base%Panel%num%).
    assert _ilike_pattern_matches("%Sh2 119%Panel%1%", "Sh2 119 Panel 1")
    assert not _ilike_pattern_matches("%Sh2 119%Panel%1%", "Sh2 119 Panel 2")

    # Case-insensitive, and order matters.
    assert _ilike_pattern_matches("%veil%1%", "Veil Nebula Panel 1")
    assert not _ilike_pattern_matches("%1%veil%", "Veil Nebula Panel 1")


@pytest.mark.asyncio
async def test_get_suggestions_distributes_sessions_to_correct_panel(viewer_user):
    """Each OBJECT's sessions go to exactly ONE panel, not every panel.
    Reproduces the Sh2 119 cross-mapping where 'Panel 2' leaked into Panel 1."""
    suggestion_id = uuid.uuid4()
    target_id = uuid.uuid4()

    suggestion = MagicMock()
    suggestion.id = suggestion_id
    suggestion.suggested_name = "Sh2 119"
    suggestion.base_name = "Sh2 119"
    suggestion.target_ids = [target_id, target_id]
    suggestion.panel_labels = ["Panel 1", "Panel 2"]
    # Legacy token-less patterns (the bug case).
    suggestion.panel_patterns = ["%Sh2 119%1%", "%Sh2 119%2%"]
    suggestion.session_dates = None
    suggestion.status = "pending"
    suggestion.confidence = "high"
    suggestion.discovery_source = "name"
    suggestion.flags = []
    suggestion.geometry = {"panels": []}  # no preview panels -> no pattern thumb queries

    pending_result = MagicMock()
    pending_result.scalars.return_value.all.return_value = [suggestion]

    mosaic_names_result = MagicMock()
    mosaic_names_result.all.return_value = []

    target_names_result = MagicMock()
    target_names_result.all.return_value = [(target_id, "Sh2 119")]

    thumb_result = MagicMock()
    thumb_result.all.return_value = []

    # Session summary rows: one OBJECT per panel.
    def _mk_row(obj, night, frames, integration, filt):
        r = MagicMock()
        r.obj = obj
        r.night = night
        r.frames = frames
        r.integration = integration
        r.filter_used = filt
        return r

    sessions_result = MagicMock()
    sessions_result.all.return_value = [
        _mk_row("Sh2 119 Panel 1", "2025-01-01", 10, 600.0, "Ha"),
        _mk_row("Sh2 119 Panel 2", "2025-01-02", 12, 720.0, "Ha"),
    ]

    # geometry has no panels, so no per-(target,pattern) thumb queries run.
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(side_effect=[
        pending_result,
        mosaic_names_result,
        target_names_result,
        thumb_result,
        sessions_result,
    ])

    _override_session(mock_session)
    app.dependency_overrides[get_current_user] = lambda: viewer_user
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/mosaics/suggestions")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert len(data) == 1
        sessions = data[0]["sessions"]
        # Each OBJECT maps to its single correct panel, not both.
        by_object = {(s["object_name"], s["panel_label"]) for s in sessions}
        assert ("Sh2 119 Panel 1", "Panel 1") in by_object
        assert ("Sh2 119 Panel 2", "Panel 2") in by_object
        assert ("Sh2 119 Panel 1", "Panel 2") not in by_object
        assert ("Sh2 119 Panel 2", "Panel 1") not in by_object
        # Exactly two session entries total (no duplication across panels).
        assert len(sessions) == 2
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_accept_suggestion_duplicate_name_returns_409(admin_user):
    """Accepting a suggestion whose name already exists returns 409, not a 500
    IntegrityError, and never inserts a partial/duplicate mosaic."""
    suggestion_id = uuid.uuid4()

    suggestion = MagicMock()
    suggestion.id = suggestion_id
    suggestion.suggested_name = "Veil Nebula"
    suggestion.status = "pending"

    existing_mosaic = MagicMock()
    existing_mosaic.name = "Veil Nebula"

    dup_result = MagicMock()
    dup_result.scalar_one_or_none.return_value = existing_mosaic

    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=suggestion)
    mock_session.execute = AsyncMock(return_value=dup_result)
    mock_session.add = MagicMock()
    mock_session.flush = AsyncMock()
    mock_session.commit = AsyncMock()

    _override_session(mock_session)
    app.dependency_overrides[require_admin] = lambda: admin_user
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(f"/api/mosaics/suggestions/{suggestion_id}/accept")
        assert resp.status_code == 409, resp.text
        assert "already exists" in resp.json()["detail"]
        # No mosaic insert/flush/commit should have happened.
        mock_session.add.assert_not_called()
        mock_session.flush.assert_not_called()
        mock_session.commit.assert_not_called()
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_add_panel_mosaic_not_found_returns_404(admin_user):
    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=None)

    _override_session(mock_session)
    app.dependency_overrides[require_admin] = lambda: admin_user
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                f"/api/mosaics/{uuid.uuid4()}/panels",
                json={"target_id": str(uuid.uuid4()), "panel_label": "Panel 1"},
            )
        assert resp.status_code == 404
    finally:
        app.dependency_overrides.clear()
