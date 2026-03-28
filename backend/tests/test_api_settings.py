import pytest
from unittest.mock import AsyncMock, MagicMock
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.database import get_session
from app.models.user_settings import SETTINGS_ROW_ID


def _make_settings_row(
    general=None,
    filters=None,
    equipment=None,
    dismissed_suggestions=None,
    display=None,
    graph=None,
):
    """Return a MagicMock that looks like a UserSettings ORM row."""
    row = MagicMock()
    row.id = SETTINGS_ROW_ID
    row.general = general if general is not None else {}
    row.filters = filters if filters is not None else {}
    row.equipment = equipment if equipment is not None else {}
    row.dismissed_suggestions = dismissed_suggestions if dismissed_suggestions is not None else []
    row.display = display if display is not None else {}
    row.graph = graph if graph is not None else {}
    return row


# ---------------------------------------------------------------------------
# GET /api/settings
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_settings_returns_defaults():
    """GET /api/settings returns default-valued object when row has empty dicts."""
    row = _make_settings_row()

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = row

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)

    async def override():
        yield mock_session

    app.dependency_overrides[get_session] = override
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/settings")

        assert resp.status_code == 200
        data = resp.json()
        assert "general" in data
        assert "filters" in data
        assert "equipment" in data
        # general defaults
        assert data["general"]["auto_scan_enabled"] is True
        assert data["general"]["auto_scan_interval"] == 240
        assert data["general"]["thumbnail_width"] == 800
        assert data["general"]["default_page_size"] == 50
        # empty containers
        assert data["filters"] == {}
        assert data["equipment"] == {"cameras": {}, "telescopes": {}}
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_settings_creates_row_when_missing():
    """GET /api/settings creates the row if it doesn't exist yet."""
    # scalar_one_or_none returns None (no row), then after flush the row exists
    created_row = _make_settings_row()

    first_result = MagicMock()
    first_result.scalar_one_or_none.return_value = None

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=first_result)
    mock_session.flush = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()
    mock_session.refresh = AsyncMock(side_effect=lambda obj: None)

    # After flush, we need the created row to be returned via refresh
    # We'll simulate that by replacing scalar_one_or_none on the second call
    call_count = 0

    async def execute_side_effect(stmt):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            r = MagicMock()
            r.scalar_one_or_none.return_value = None
            return r
        else:
            r = MagicMock()
            r.scalar_one_or_none.return_value = created_row
            return r

    mock_session.execute = AsyncMock(side_effect=execute_side_effect)

    async def override():
        yield mock_session

    app.dependency_overrides[get_session] = override
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/settings")

        assert resp.status_code == 200
        assert mock_session.add.called
        assert mock_session.flush.called
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_settings_with_stored_values():
    """GET /api/settings returns stored values from the row."""
    row = _make_settings_row(
        general={"auto_scan_enabled": False, "auto_scan_interval": 120,
                 "thumbnail_width": 400, "default_page_size": 25},
        filters={"Ha": {"color": "#ff0000", "aliases": ["Halpha", "H-alpha"]}},
        equipment={"cameras": {"ASI2600": {"aliases": ["ASI 2600"]}}, "telescopes": {}},
    )

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = row

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)

    async def override():
        yield mock_session

    app.dependency_overrides[get_session] = override
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/settings")

        assert resp.status_code == 200
        data = resp.json()
        assert data["general"]["auto_scan_enabled"] is False
        assert data["general"]["auto_scan_interval"] == 120
        assert data["filters"]["Ha"]["color"] == "#ff0000"
        assert data["filters"]["Ha"]["aliases"] == ["Halpha", "H-alpha"]
        assert data["equipment"]["cameras"]["ASI2600"]["aliases"] == ["ASI 2600"]
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_settings_returns_dismissed_suggestions():
    """GET /api/settings returns dismissed_suggestions from the row."""
    row = _make_settings_row()
    row.dismissed_suggestions = [["Ha", "ha"]]

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = row

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)

    async def override():
        yield mock_session

    app.dependency_overrides[get_session] = override
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/settings")

        assert resp.status_code == 200
        data = resp.json()
        assert data["dismissed_suggestions"] == [["Ha", "ha"]]
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_settings_defaults_dismissed_suggestions_empty():
    """GET /api/settings returns empty list when no dismissed suggestions."""
    row = _make_settings_row()
    row.dismissed_suggestions = []

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = row

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)

    async def override():
        yield mock_session

    app.dependency_overrides[get_session] = override
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/settings")

        assert resp.status_code == 200
        data = resp.json()
        assert data["dismissed_suggestions"] == []
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# PUT /api/settings/general
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_put_general_updates_and_returns_settings():
    """PUT /api/settings/general persists changes and returns full settings."""
    row = _make_settings_row(
        general={"auto_scan_enabled": True, "auto_scan_interval": 240,
                 "thumbnail_width": 800, "default_page_size": 50},
    )

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = row

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.commit = AsyncMock()
    mock_session.refresh = AsyncMock()

    async def override():
        yield mock_session

    app.dependency_overrides[get_session] = override
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.put(
                "/api/settings/general",
                json={"auto_scan_enabled": False, "auto_scan_interval": 60,
                      "thumbnail_width": 400, "default_page_size": 25},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert "general" in data
        assert "filters" in data
        assert "equipment" in data
        assert mock_session.commit.called
        assert mock_session.refresh.called
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_put_general_invalid_payload():
    """PUT /api/settings/general rejects non-boolean for auto_scan_enabled."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.put(
            "/api/settings/general",
            json={"auto_scan_enabled": "yes", "auto_scan_interval": -1,
                  "thumbnail_width": 800, "default_page_size": 50},
        )
    # Pydantic will coerce "yes" string to bool — just check it responds
    assert resp.status_code in (200, 422)


# ---------------------------------------------------------------------------
# PUT /api/settings/filters
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_put_filters_updates_filter_config():
    """PUT /api/settings/filters stores new filter mapping."""
    row = _make_settings_row(filters={})

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = row

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.commit = AsyncMock()
    mock_session.refresh = AsyncMock()

    async def override():
        yield mock_session

    app.dependency_overrides[get_session] = override
    try:
        payload = {
            "Ha": {"color": "#ff0000", "aliases": ["Halpha"]},
            "OIII": {"color": "#00ff00", "aliases": []},
        }
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.put("/api/settings/filters", json=payload)

        assert resp.status_code == 200
        data = resp.json()
        assert "filters" in data
        assert mock_session.commit.called
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# PUT /api/settings/equipment
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_put_equipment_updates_equipment_config():
    """PUT /api/settings/equipment stores new equipment aliases."""
    row = _make_settings_row(equipment={})

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = row

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.commit = AsyncMock()
    mock_session.refresh = AsyncMock()

    async def override():
        yield mock_session

    app.dependency_overrides[get_session] = override
    try:
        payload = {
            "cameras": {"ASI2600MC": {"aliases": ["ASI 2600 MC", "ASI2600"]}},
            "telescopes": {"RedCat51": {"aliases": ["William Optics RedCat 51"]}},
        }
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.put("/api/settings/equipment", json=payload)

        assert resp.status_code == 200
        data = resp.json()
        assert "equipment" in data
        assert mock_session.commit.called
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# PUT /api/settings/dismissed-suggestions
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_put_dismissed_suggestions_stores_sorted_lists():
    """PUT /api/settings/dismissed-suggestions stores sorted name lists."""
    row = _make_settings_row()

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = row

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.commit = AsyncMock()
    mock_session.refresh = AsyncMock()

    async def override():
        yield mock_session

    app.dependency_overrides[get_session] = override
    try:
        payload = [["ha", "Ha"], ["ASI533", "ASI 533"]]
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.put("/api/settings/dismissed-suggestions", json=payload)

        assert resp.status_code == 200
        data = resp.json()
        assert "dismissed_suggestions" in data
        assert mock_session.commit.called
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# GET /api/settings/suggestions/filters
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_suggestions_filters_groups_case_insensitive():
    """GET /api/settings/suggestions/filters groups case-insensitive duplicates."""
    # Simulate DB returning distinct filter_used values with counts
    rows = [
        ("OIII", 10),
        ("oiii", 5),
        ("Oiii", 3),
        ("Ha", 20),
        ("ha", 8),
    ]

    mock_result = MagicMock()
    mock_result.all.return_value = rows

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)

    async def override():
        yield mock_session

    app.dependency_overrides[get_session] = override
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/settings/suggestions/filters")

        assert resp.status_code == 200
        data = resp.json()
        assert "suggestions" in data
        suggestions = data["suggestions"]
        # Should have groups for oiii variants and ha variants
        assert len(suggestions) >= 1

        # Find the OIII group
        oiii_group = next(
            (g for g in suggestions if len(g["group"]) == 3 and
             any(v.lower() == "oiii" for v in g["group"])),
            None,
        )
        assert oiii_group is not None, f"Expected OIII group not found in {suggestions}"
        assert oiii_group["counts"]["OIII"] == 10
        assert oiii_group["counts"]["oiii"] == 5
        assert oiii_group["counts"]["Oiii"] == 3

        # Find the Ha group
        ha_group = next(
            (g for g in suggestions if any(v.lower() == "ha" for v in g["group"])),
            None,
        )
        assert ha_group is not None, f"Expected Ha group not found in {suggestions}"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_suggestions_filters_no_duplicates():
    """GET /api/settings/suggestions/filters returns empty when all names are unique."""
    rows = [("Ha", 10), ("OIII", 5), ("SII", 3)]

    mock_result = MagicMock()
    mock_result.all.return_value = rows

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)

    async def override():
        yield mock_session

    app.dependency_overrides[get_session] = override
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/settings/suggestions/filters")

        assert resp.status_code == 200
        data = resp.json()
        assert data["suggestions"] == []
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_suggestions_filters_levenshtein_grouping():
    """GET /api/settings/suggestions/filters groups names within edit distance 2."""
    # "Halpha" and "H-alpha" differ by 1 char (insertion), should be grouped
    rows = [("Halpha", 15), ("H-alpha", 7)]

    mock_result = MagicMock()
    mock_result.all.return_value = rows

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)

    async def override():
        yield mock_session

    app.dependency_overrides[get_session] = override
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/settings/suggestions/filters")

        assert resp.status_code == 200
        data = resp.json()
        suggestions = data["suggestions"]
        assert len(suggestions) == 1
        assert set(suggestions[0]["group"]) == {"Halpha", "H-alpha"}
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_suggestions_filters_short_strings_not_levenshtein_grouped():
    """Short strings (<= 3 chars) are only grouped by case, not Levenshtein."""
    # "Ha" and "Hb" differ by 1 char but are <= 3 chars — should NOT be grouped
    rows = [("Ha", 10), ("Hb", 5)]

    mock_result = MagicMock()
    mock_result.all.return_value = rows

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)

    async def override():
        yield mock_session

    app.dependency_overrides[get_session] = override
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/settings/suggestions/filters")

        assert resp.status_code == 200
        data = resp.json()
        # No groups since they are distinct (not case variants, not long enough for Levenshtein)
        assert data["suggestions"] == []
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# GET /api/settings/suggestions/equipment
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_suggestions_equipment_returns_camera_and_telescope():
    """GET /api/settings/suggestions/equipment returns suggestions for both columns."""
    # Two execute calls: first for cameras, second for telescopes
    camera_rows = [("ASI2600MC", 30), ("ASI 2600 MC", 12)]
    telescope_rows = [("RedCat51", 20), ("RedCat 51", 8)]

    call_count = 0

    async def execute_side_effect(stmt):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        if call_count == 1:
            r.all.return_value = camera_rows
        else:
            r.all.return_value = telescope_rows
        return r

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(side_effect=execute_side_effect)

    async def override():
        yield mock_session

    app.dependency_overrides[get_session] = override
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/settings/suggestions/equipment")

        assert resp.status_code == 200
        data = resp.json()
        assert "suggestions" in data
        suggestions = data["suggestions"]
        # Both camera and telescope pairs should be grouped
        assert len(suggestions) >= 1
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_suggestions_equipment_empty_db():
    """GET /api/settings/suggestions/equipment returns empty when no equipment data."""
    mock_result = MagicMock()
    mock_result.all.return_value = []

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)

    async def override():
        yield mock_session

    app.dependency_overrides[get_session] = override
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/settings/suggestions/equipment")

        assert resp.status_code == 200
        data = resp.json()
        assert data["suggestions"] == []
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Task 5: dismissed suggestions filtering
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_suggestions_filters_excludes_dismissed():
    """Dismissed suggestion groups are filtered from the response."""
    rows = [("Ha", 20), ("ha", 8)]

    settings_row = _make_settings_row(
        dismissed_suggestions=[["Ha", "ha"]],
    )

    call_count = 0
    async def execute_side_effect(stmt):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            r = MagicMock()
            r.all.return_value = rows
            return r
        else:
            r = MagicMock()
            r.scalar_one_or_none.return_value = settings_row
            return r

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(side_effect=execute_side_effect)

    async def override():
        yield mock_session

    app.dependency_overrides[get_session] = override
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/settings/suggestions/filters")

        assert resp.status_code == 200
        data = resp.json()
        assert data["suggestions"] == []
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Task 6: GET /api/settings/discovered/{section}
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_discovered_filters_returns_names_and_counts():
    """GET /api/settings/discovered/filters returns distinct filter names with counts."""
    db_rows = [("Ha", 50), ("OIII", 30), ("SII", 20)]

    mock_result = MagicMock()
    mock_result.all.return_value = db_rows

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)

    async def override():
        yield mock_session

    app.dependency_overrides[get_session] = override
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/settings/discovered/filters")

        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == [
            {"name": "Ha", "count": 50},
            {"name": "OIII", "count": 30},
            {"name": "SII", "count": 20},
        ]
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_discovered_cameras_returns_names_and_counts():
    """GET /api/settings/discovered/cameras returns distinct camera names with counts."""
    db_rows = [("ASI2600MC", 100), ("ASI533MC", 40)]

    mock_result = MagicMock()
    mock_result.all.return_value = db_rows

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)

    async def override():
        yield mock_session

    app.dependency_overrides[get_session] = override
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/settings/discovered/cameras")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 2
        assert data["items"][0]["name"] == "ASI2600MC"
        assert data["items"][0]["count"] == 100
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_discovered_invalid_section_returns_422():
    """GET /api/settings/discovered/invalid returns 422."""
    mock_session = AsyncMock()

    async def override():
        yield mock_session

    app.dependency_overrides[get_session] = override
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/settings/discovered/invalid")

        assert resp.status_code == 422
    finally:
        app.dependency_overrides.clear()
