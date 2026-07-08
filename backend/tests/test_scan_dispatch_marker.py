"""Tests for the scan:dispatched marker (AUD-016).

Covers get_scan_state() honoring the marker and mark_scan_dispatched()
setting it, closing the race where a second POST /scan lands after the
dispatch lock is released but before run_scan's worker has picked up the
task and written the real "scanning" state.
"""
import os
import sys
from unittest.mock import AsyncMock, MagicMock
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

from app.services.scan_state import get_scan_state, mark_scan_dispatched, SCAN_DISPATCHED_KEY, SCAN_DISPATCHED_TTL


@pytest.mark.asyncio
async def test_get_scan_state_reports_scanning_when_dispatch_marker_set():
    """Even though scan:state hash is still idle (worker hasn't run
    start_scanning_sync yet), a live dispatch marker must make get_scan_state
    report an active scan so a racing second request doesn't dispatch a
    duplicate."""
    r = AsyncMock()
    r.hgetall = AsyncMock(return_value={})  # idle: worker hasn't started yet
    r.exists = AsyncMock(return_value=1)  # dispatch marker present

    state = await get_scan_state(r)

    assert state.state == "scanning"


@pytest.mark.asyncio
async def test_get_scan_state_stays_idle_without_dispatch_marker():
    r = AsyncMock()
    r.hgetall = AsyncMock(return_value={})
    r.exists = AsyncMock(return_value=0)

    state = await get_scan_state(r)

    assert state.state == "idle"


@pytest.mark.asyncio
async def test_get_scan_state_ignores_dispatch_marker_once_ingesting():
    """Once the hash itself says scanning/ingesting, the dispatch marker is
    irrelevant (and not even consulted) - the real state takes precedence."""
    r = AsyncMock()
    r.hgetall = AsyncMock(return_value={
        "state": "ingesting", "total": "10", "completed": "2", "failed": "0",
        "started_at": "1711000000.0", "completed_at": "",
    })
    r.get = AsyncMock(return_value=None)
    r.exists = AsyncMock(return_value=0)

    state = await get_scan_state(r)

    assert state.state == "ingesting"
    r.exists.assert_not_called()


@pytest.mark.asyncio
async def test_mark_scan_dispatched_sets_key_with_ttl():
    r = AsyncMock()
    r.set = AsyncMock()

    await mark_scan_dispatched(r)

    r.set.assert_called_once_with(SCAN_DISPATCHED_KEY, "1", ex=SCAN_DISPATCHED_TTL)
