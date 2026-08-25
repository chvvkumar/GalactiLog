"""Tests for the first-run setup block on GET /api/bootstrap."""
import os
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.bootstrap import _fetch_setup_state, _fits_root_state


def _session_patch(general, has_images):
    """Patch app.api.bootstrap.async_session with a two-query fake session.

    _fetch_setup_state issues exactly two queries: the raw general JSONB, then
    the images EXISTS probe.
    """
    general_result = MagicMock()
    general_result.scalar_one_or_none.return_value = general
    images_result = MagicMock()
    images_result.scalar.return_value = has_images

    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[general_result, images_result])

    @asynccontextmanager
    async def fake_session():
        yield session

    return patch("app.api.bootstrap.async_session", fake_session)


@pytest.mark.asyncio
async def test_fresh_install_is_not_complete(tmp_path):
    with _session_patch({}, False), \
            patch("app.api.bootstrap.app_settings.fits_data_path", str(tmp_path)):
        state = await _fetch_setup_state()

    assert state["complete"] is False
    assert state["fits_root"] == str(tmp_path)
    assert state["fits_root_exists"] is True
    assert state["fits_root_has_entries"] is False
    assert state["version"] == os.environ.get("GALACTILOG_VERSION", "dev")


@pytest.mark.asyncio
async def test_setup_completed_at_marks_complete(tmp_path):
    with _session_patch({"setup_completed_at": "2026-08-24T00:00:00+00:00"}, False), \
            patch("app.api.bootstrap.app_settings.fits_data_path", str(tmp_path)):
        state = await _fetch_setup_state()

    assert state["complete"] is True


@pytest.mark.asyncio
async def test_scan_filters_configured_marks_complete(tmp_path):
    with _session_patch({"scan_filters_configured": True}, False), \
            patch("app.api.bootstrap.app_settings.fits_data_path", str(tmp_path)):
        state = await _fetch_setup_state()

    assert state["complete"] is True


@pytest.mark.asyncio
async def test_existing_images_mark_complete(tmp_path):
    with _session_patch({}, True), \
            patch("app.api.bootstrap.app_settings.fits_data_path", str(tmp_path)):
        state = await _fetch_setup_state()

    assert state["complete"] is True


@pytest.mark.asyncio
async def test_missing_settings_row_is_not_complete(tmp_path):
    """A NULL general column must not blow up the whole bootstrap request."""
    with _session_patch(None, False), \
            patch("app.api.bootstrap.app_settings.fits_data_path", str(tmp_path)):
        state = await _fetch_setup_state()

    assert state["complete"] is False


@pytest.mark.asyncio
async def test_missing_fits_root_reports_false_without_raising(tmp_path):
    missing = str(tmp_path / "does-not-exist")
    with _session_patch({}, False), \
            patch("app.api.bootstrap.app_settings.fits_data_path", missing):
        state = await _fetch_setup_state()

    assert state["fits_root"] == missing
    assert state["fits_root_exists"] is False
    assert state["fits_root_has_entries"] is False


@pytest.mark.asyncio
async def test_https_flag_passes_through(tmp_path):
    with _session_patch({}, False), \
            patch("app.api.bootstrap.app_settings.fits_data_path", str(tmp_path)), \
            patch("app.api.bootstrap.app_settings.https", True):
        state = await _fetch_setup_state()

    assert state["https_enabled"] is True


def test_fits_root_state_detects_entries(tmp_path):
    assert _fits_root_state(str(tmp_path)) == (True, False)
    (tmp_path / "sub").mkdir()
    assert _fits_root_state(str(tmp_path)) == (True, True)


def test_fits_root_state_swallows_oserror(tmp_path):
    """A permission error on scandir must degrade to False, not 500."""
    with patch("app.api.bootstrap.os.scandir", side_effect=PermissionError):
        assert _fits_root_state(str(tmp_path)) == (False, False)


def test_fits_root_state_on_a_file(tmp_path):
    f = tmp_path / "not-a-dir"
    f.write_text("x")
    assert _fits_root_state(str(f)) == (False, False)
