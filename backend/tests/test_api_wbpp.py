"""Tests for the WBPP export router."""
import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock
from httpx import ASGITransport, AsyncClient
from datetime import date

from app.main import app
from app.database import get_session
from app.api.deps import get_current_user
from app.models.user import User, UserRole


def _admin():
    u = MagicMock(spec=User)
    u.id = uuid.uuid4(); u.role = UserRole.admin; u.is_active = True
    return u


def _db(*row_sets):
    """Mock a session whose successive execute() calls return the given row sets.

    Both handlers issue two queries in a fixed order: the session query
    (file_path, session_date, file_size) then the contamination query
    (file_path, session_date, primary_name). The column shapes differ, so each
    query gets its own rows rather than sharing one result.
    """
    session = AsyncMock()
    results = []
    for rows in row_sets:
        r = MagicMock(); r.all.return_value = rows
        results.append(r)
    session.execute = AsyncMock(side_effect=results)
    return session


@pytest.mark.asyncio
async def test_wbpp_preview_empty_sessions():
    mock_session = _db([], [])

    async def override():
        yield mock_session

    app.dependency_overrides[get_session] = override
    app.dependency_overrides[get_current_user] = lambda: _admin()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/wbpp/preview", json={
                "target_id": str(uuid.uuid4()),
                "session_dates": ["2024-01-01"],
                "library_root": "/mnt/astro",
            })
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["sessions"]) == 1
        assert data["sessions"][0]["total_frame_count"] == 0
        assert data["target_os"] == "posix"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_wbpp_generate_returns_script_and_operations_for_windows_root():
    from unittest.mock import patch as _patch
    from app.api import wbpp as wbpp_module

    fits_root = "/app/data/fits"
    path = f"{fits_root}/M31/2024-01-01/Light/frame.fits"

    mock_session = _db(
        [(path, date(2024, 1, 1), 1000)],
        [(path, date(2024, 1, 1), "M 31")],
    )

    async def override():
        yield mock_session

    app.dependency_overrides[get_session] = override
    app.dependency_overrides[get_current_user] = lambda: _admin()
    try:
        # Patch fits_data_path so the service sees paths matching the mock data
        with _patch.object(wbpp_module.settings, "fits_data_path", fits_root):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post("/api/wbpp/generate", json={
                    "target_id": str(uuid.uuid4()),
                    "target_name": "M 31",
                    "session_dates": ["2024-01-01"],
                    "library_root": "Z:\\Astro",
                })
        assert resp.status_code == 200
        data = resp.json()
        assert data["filename"].endswith(".ps1")
        assert data["target_os"] == "windows"
        assert "Copy-Item" in data["script"]
        assert "Write-Host" in data["script"]
        assert len(data["operations"]) == 1
        op = data["operations"][0]
        assert op["session_date"] == "2024-01-01"
        assert op["source"].startswith("Z:\\Astro")
        assert op["destination"].startswith("Z:\\Astro")
        # Relative path (for browser File System Access API) is root-relative, no drive/sep prefix.
        # Single light frame -> deepest level (the Light folder) is the default.
        assert op["source_relative"] == "M31/2024-01-01/Light"
        assert "\\" not in op["source_relative"]
        assert op["dest_entry"] == "Light"
        assert isinstance(data["exclusions"], list)
        # No exclude list supplied -> counts reflect a single copied light.
        assert data["light_total"] == 1
        assert data["light_excluded"] == 0
        assert data["light_copied"] == 1
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_wbpp_preview_counts_excluded_frames():
    from unittest.mock import patch as _patch
    from app.api import wbpp as wbpp_module

    fits_root = "/app/data/fits"
    rel = "M31/2024-01-01/Light/frame.fits"

    mock_session = _db(
        [(f"{fits_root}/{rel}", date(2024, 1, 1), 1000)],
        [(f"{fits_root}/{rel}", date(2024, 1, 1), "M 31")],
    )

    async def override():
        yield mock_session

    app.dependency_overrides[get_session] = override
    app.dependency_overrides[get_current_user] = lambda: _admin()
    try:
        with _patch.object(wbpp_module.settings, "fits_data_path", fits_root):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post("/api/wbpp/preview", json={
                    "target_id": str(uuid.uuid4()),
                    "session_dates": ["2024-01-01"],
                    "library_root": "/mnt/astro",
                    "excluded_source_relatives": [rel],
                })
        assert resp.status_code == 200
        data = resp.json()
        assert data["sessions"][0]["total_frame_count"] == 1
        assert data["sessions"][0]["excluded_frame_count"] == 1
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_wbpp_preview_reports_frame_bytes_per_level():
    from unittest.mock import patch as _patch
    from app.api import wbpp as wbpp_module

    fits_root = "/app/data/fits"
    a = f"{fits_root}/M31/2024-01-01/Light/a.fits"
    b = f"{fits_root}/M31/2024-01-01/Light/b.fits"

    mock_session = _db(
        [(a, date(2024, 1, 1), 1000), (b, date(2024, 1, 1), 2500)],
        [(a, date(2024, 1, 1), "M 31"), (b, date(2024, 1, 1), "M 31")],
    )

    async def override():
        yield mock_session

    app.dependency_overrides[get_session] = override
    app.dependency_overrides[get_current_user] = lambda: _admin()
    try:
        with _patch.object(wbpp_module.settings, "fits_data_path", fits_root):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post("/api/wbpp/preview", json={
                    "target_id": str(uuid.uuid4()),
                    "session_dates": ["2024-01-01"],
                    "library_root": "/mnt/astro",
                })
        assert resp.status_code == 200
        levels = resp.json()["sessions"][0]["levels"]
        # every level holds both frames, so each reports their combined size
        assert all(lv["frame_count"] == 2 for lv in levels)
        assert all(lv["frame_bytes"] == 3500 for lv in levels)
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_wbpp_preview_frame_bytes_null_when_a_size_is_unknown():
    from unittest.mock import patch as _patch
    from app.api import wbpp as wbpp_module

    fits_root = "/app/data/fits"
    a = f"{fits_root}/M31/2024-01-01/Light/a.fits"
    b = f"{fits_root}/M31/2024-01-01/Light/b.fits"

    # b.fits predates the file_size column: its size is NULL in the DB.
    mock_session = _db(
        [(a, date(2024, 1, 1), 1000), (b, date(2024, 1, 1), None)],
        [(a, date(2024, 1, 1), "M 31"), (b, date(2024, 1, 1), "M 31")],
    )

    async def override():
        yield mock_session

    app.dependency_overrides[get_session] = override
    app.dependency_overrides[get_current_user] = lambda: _admin()
    try:
        with _patch.object(wbpp_module.settings, "fits_data_path", fits_root):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post("/api/wbpp/preview", json={
                    "target_id": str(uuid.uuid4()),
                    "session_dates": ["2024-01-01"],
                    "library_root": "/mnt/astro",
                })
        assert resp.status_code == 200
        levels = resp.json()["sessions"][0]["levels"]
        # null, not the partial 1000 sum -- a partial would understate the copy size
        assert all(lv["frame_bytes"] is None for lv in levels)
        assert all(lv["frame_count"] == 2 for lv in levels)
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_wbpp_generate_excludes_named_light_and_counts():
    from unittest.mock import patch as _patch
    from app.api import wbpp as wbpp_module

    fits_root = "/app/data/fits"
    good = "M31/2024-01-01/Light/good.fits"
    bad = "M31/2024-01-01/Light/bad.fits"

    mock_session = _db(
        [(f"{fits_root}/{good}", date(2024, 1, 1), 1000),
         (f"{fits_root}/{bad}", date(2024, 1, 1), 2000)],
        [(f"{fits_root}/{good}", date(2024, 1, 1), "M 31"),
         (f"{fits_root}/{bad}", date(2024, 1, 1), "M 31")],
    )

    async def override():
        yield mock_session

    app.dependency_overrides[get_session] = override
    app.dependency_overrides[get_current_user] = lambda: _admin()
    try:
        with _patch.object(wbpp_module.settings, "fits_data_path", fits_root):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post("/api/wbpp/generate", json={
                    "target_id": str(uuid.uuid4()),
                    "target_name": "M 31",
                    "session_dates": ["2024-01-01"],
                    "library_root": "Z:\\Astro",
                    "excluded_source_relatives": [bad],
                })
        assert resp.status_code == 200
        data = resp.json()
        assert data["light_total"] == 2
        assert data["light_excluded"] == 1
        assert data["light_copied"] == 1
        # the named light is emitted as a per-file skip; the good sibling is not.
        assert "ExcludeFiles = @(" in data["script"]
        assert "bad.fits" in data["script"]
        assert "good.fits" not in data["script"]
    finally:
        app.dependency_overrides.clear()
