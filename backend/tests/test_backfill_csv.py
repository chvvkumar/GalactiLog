"""Tests for the backfill_csv_metrics Celery task and /scan/backfill-csv endpoint.

NOTE: app.worker.tasks runs Base.metadata.create_all() at module-level import, which
requires a live DB. We intercept this via sys.modules stubbing before first import.
"""
import sys
import types
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import pytest


def _mock_async_redis(mock_redis):
    """Create an async context manager mock that yields the given mock_redis."""
    @asynccontextmanager
    async def _ctx():
        yield mock_redis
    return _ctx


# ── Pre-import stubs ──────────────────────────────────────────────────────────
# fitsio is not available on the dev machine (native C extension, build env only).
if "fitsio" not in sys.modules:
    _fitsio_stub = types.ModuleType("fitsio")
    _fitsio_stub.FITSHDR = MagicMock  # type: ignore[attr-defined]
    _fitsio_stub.write = MagicMock()   # type: ignore[attr-defined]
    _fitsio_stub.read = MagicMock()    # type: ignore[attr-defined]
    sys.modules["fitsio"] = _fitsio_stub


def _bootstrap_tasks_module():
    """Import app.worker.tasks with DB create_all mocked out."""
    # If already imported (e.g. by another test file), just return it
    if "app.worker.tasks" in sys.modules:
        return sys.modules["app.worker.tasks"]

    # Patch sqlalchemy create_engine to return a mock, preventing DB connection
    mock_engine = MagicMock()
    mock_engine.connect.return_value.__enter__ = MagicMock(return_value=mock_engine)
    mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)

    with patch("sqlalchemy.create_engine", return_value=mock_engine):
        import app.worker.tasks as tasks_mod
    return tasks_mod


# Bootstrap once at module level (runs during collection)
_tasks = _bootstrap_tasks_module()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_row(id_="img-001", file_name="Light_001.fits"):
    """Create a mock DB row with id and file_name attributes."""
    row = MagicMock()
    row.id = id_
    row.file_name = file_name
    return row


# ── Task tests ────────────────────────────────────────────────────────────────

def test_backfill_csv_metrics_no_csv_dirs(tmp_path):
    """Task returns early when no ImageMetaData.csv files are found."""
    import redis as _redis_module

    with patch.object(_redis_module, "from_url") as mock_from_url, \
         patch.object(_tasks, "settings") as mock_settings, \
         patch.object(_tasks, "set_idle_sync") as mock_idle, \
         patch.object(_tasks, "start_scanning_sync") as mock_start, \
         patch.object(_tasks, "parse_image_metadata_csv") as mock_image_csv:

        mock_settings.fits_data_path = str(tmp_path)
        mock_settings.redis_url = "redis://localhost:6379/1"
        mock_redis_conn = MagicMock()
        mock_from_url.return_value = mock_redis_conn

        result = _tasks.backfill_csv_metrics()

    assert result == {"updated": 0, "dirs": 0}
    mock_idle.assert_called_once_with(mock_redis_conn)
    mock_start.assert_not_called()
    mock_image_csv.assert_not_called()


def test_backfill_csv_metrics_updates_rows(tmp_path):
    """Task parses CSVs, queries images, and commits updates for matched rows."""
    csv_dir = tmp_path / "session1"
    csv_dir.mkdir()
    (csv_dir / "ImageMetaData.csv").write_text("FilePath,HFR\n")

    import redis as _redis_module

    image_entry = {
        "median_hfr": 1.5,
        "eccentricity": 0.4,
        "_exposure_start_utc": "2024-01-01T00:00:00",
    }

    mock_conn = MagicMock()
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)
    mock_conn.execute.return_value.fetchall.return_value = [
        _make_row("img-001", "Light_001.fits")
    ]

    with patch.object(_redis_module, "from_url") as mock_from_url, \
         patch.object(_tasks, "settings") as mock_settings, \
         patch.object(_tasks, "_sync_engine") as mock_engine, \
         patch.object(_tasks, "set_idle_sync") as mock_idle, \
         patch.object(_tasks, "start_scanning_sync") as mock_start, \
         patch.object(_tasks, "increment_completed_sync") as mock_increment, \
         patch.object(_tasks, "parse_image_metadata_csv") as mock_image_csv, \
         patch.object(_tasks, "parse_weather_csv") as mock_weather_csv:

        mock_settings.fits_data_path = str(tmp_path)
        mock_settings.redis_url = "redis://localhost:6379/1"
        mock_redis_conn = MagicMock()
        mock_from_url.return_value = mock_redis_conn
        mock_image_csv.return_value = {"Light_001.fits": image_entry}
        mock_weather_csv.return_value = {
            "2024-01-01T00:00:00": {"ambient_temp": -5.0}
        }
        mock_engine.connect.return_value = mock_conn

        result = _tasks.backfill_csv_metrics()

    assert result["dirs"] == 1
    assert result["updated"] == 1
    mock_start.assert_called_once_with(mock_redis_conn, total=1)
    mock_increment.assert_called_once_with(mock_redis_conn)
    mock_idle.assert_called_once_with(mock_redis_conn)
    mock_conn.commit.assert_called_once()


def test_backfill_csv_metrics_handles_exception(tmp_path):
    """Task calls increment_failed_sync and rolls back on exception."""
    csv_dir = tmp_path / "session1"
    csv_dir.mkdir()
    (csv_dir / "ImageMetaData.csv").write_text("FilePath,HFR\n")

    import redis as _redis_module

    mock_conn = MagicMock()
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)

    with patch.object(_redis_module, "from_url") as mock_from_url, \
         patch.object(_tasks, "settings") as mock_settings, \
         patch.object(_tasks, "_sync_engine") as mock_engine, \
         patch.object(_tasks, "set_idle_sync") as mock_idle, \
         patch.object(_tasks, "start_scanning_sync") as mock_start, \
         patch.object(_tasks, "increment_failed_sync") as mock_failed, \
         patch.object(_tasks, "parse_image_metadata_csv") as mock_image_csv, \
         patch.object(_tasks, "parse_weather_csv") as mock_weather_csv:

        mock_settings.fits_data_path = str(tmp_path)
        mock_settings.redis_url = "redis://localhost:6379/1"
        mock_redis_conn = MagicMock()
        mock_from_url.return_value = mock_redis_conn
        mock_image_csv.side_effect = RuntimeError("CSV parse error")
        mock_engine.connect.return_value = mock_conn

        result = _tasks.backfill_csv_metrics()

    assert result["updated"] == 0
    mock_failed.assert_called_once_with(mock_redis_conn)
    mock_conn.rollback.assert_called_once()
    mock_idle.assert_called_once_with(mock_redis_conn)


def test_backfill_csv_metrics_skips_empty_image_data(tmp_path):
    """Task skips a directory when parse_image_metadata_csv returns empty dict."""
    csv_dir = tmp_path / "session1"
    csv_dir.mkdir()
    (csv_dir / "ImageMetaData.csv").write_text("FilePath,HFR\n")

    import redis as _redis_module

    mock_conn = MagicMock()
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)

    with patch.object(_redis_module, "from_url") as mock_from_url, \
         patch.object(_tasks, "settings") as mock_settings, \
         patch.object(_tasks, "_sync_engine") as mock_engine, \
         patch.object(_tasks, "set_idle_sync") as mock_idle, \
         patch.object(_tasks, "start_scanning_sync") as mock_start, \
         patch.object(_tasks, "increment_completed_sync") as mock_increment, \
         patch.object(_tasks, "parse_image_metadata_csv") as mock_image_csv, \
         patch.object(_tasks, "parse_weather_csv") as mock_weather_csv:

        mock_settings.fits_data_path = str(tmp_path)
        mock_settings.redis_url = "redis://localhost:6379/1"
        mock_redis_conn = MagicMock()
        mock_from_url.return_value = mock_redis_conn
        mock_image_csv.return_value = {}
        mock_engine.connect.return_value = mock_conn

        result = _tasks.backfill_csv_metrics()

    assert result == {"updated": 0, "dirs": 1}
    mock_increment.assert_called_once_with(mock_redis_conn)
    mock_conn.execute.assert_not_called()


def test_backfill_csv_metrics_no_file_name_match(tmp_path):
    """Task skips rows where filename does not appear in CSV image data."""
    csv_dir = tmp_path / "session1"
    csv_dir.mkdir()
    (csv_dir / "ImageMetaData.csv").write_text("FilePath,HFR\n")

    import redis as _redis_module

    mock_conn = MagicMock()
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)
    # DB has a row for a file not in the CSV
    mock_conn.execute.return_value.fetchall.return_value = [
        _make_row("img-001", "Light_001.fits")
    ]

    with patch.object(_redis_module, "from_url") as mock_from_url, \
         patch.object(_tasks, "settings") as mock_settings, \
         patch.object(_tasks, "_sync_engine") as mock_engine, \
         patch.object(_tasks, "set_idle_sync") as mock_idle, \
         patch.object(_tasks, "start_scanning_sync") as mock_start, \
         patch.object(_tasks, "increment_completed_sync") as mock_increment, \
         patch.object(_tasks, "parse_image_metadata_csv") as mock_image_csv, \
         patch.object(_tasks, "parse_weather_csv") as mock_weather_csv:

        mock_settings.fits_data_path = str(tmp_path)
        mock_settings.redis_url = "redis://localhost:6379/1"
        mock_redis_conn = MagicMock()
        mock_from_url.return_value = mock_redis_conn
        # CSV has data for a *different* filename
        mock_image_csv.return_value = {"Other_999.fits": {"median_hfr": 1.0}}
        mock_weather_csv.return_value = {}
        mock_engine.connect.return_value = mock_conn

        result = _tasks.backfill_csv_metrics()

    assert result["updated"] == 0
    assert result["dirs"] == 1


# ── API endpoint tests ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_backfill_csv_endpoint_accepted():
    """POST /scan/backfill-csv returns accepted when state is idle."""
    from httpx import AsyncClient, ASGITransport
    from app.main import app

    with patch("app.api.scan.async_redis") as mock_redis_cm, \
         patch("app.api.scan.backfill_csv_metrics") as mock_task:
        mock_task.delay = MagicMock()
        mock_redis = AsyncMock()
        mock_redis.hgetall = AsyncMock(return_value={})
        mock_redis_cm.side_effect = _mock_async_redis(mock_redis)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/scan/backfill-csv")

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "accepted"
    mock_task.delay.assert_called_once()


@pytest.mark.asyncio
async def test_backfill_csv_endpoint_already_running_scanning():
    """POST /scan/backfill-csv returns already_running when scanning."""
    from httpx import AsyncClient, ASGITransport
    from app.main import app

    with patch("app.api.scan.async_redis") as mock_redis_cm, \
         patch("app.api.scan.backfill_csv_metrics") as mock_task:
        mock_task.delay = MagicMock()
        import time as _time
        mock_redis = AsyncMock()
        mock_redis.hgetall = AsyncMock(return_value={
            "state": "scanning",
            "total": "10",
            "completed": "2",
            "failed": "0",
            "started_at": "1711000000.0",
            "completed_at": "",
        })
        # Return a recent timestamp so the stale-scan detection does not trigger
        mock_redis.get = AsyncMock(return_value=str(_time.time()))
        mock_redis_cm.side_effect = _mock_async_redis(mock_redis)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/scan/backfill-csv")

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "already_running"
    assert data["state"] == "scanning"
    mock_task.delay.assert_not_called()


@pytest.mark.asyncio
async def test_backfill_csv_endpoint_already_running_ingesting():
    """POST /scan/backfill-csv returns already_running when ingesting."""
    from httpx import AsyncClient, ASGITransport
    from app.main import app

    with patch("app.api.scan.async_redis") as mock_redis_cm, \
         patch("app.api.scan.backfill_csv_metrics") as mock_task:
        mock_task.delay = MagicMock()
        mock_redis = AsyncMock()
        mock_redis.hgetall = AsyncMock(return_value={
            "state": "ingesting",
            "total": "50",
            "completed": "10",
            "failed": "0",
            "started_at": "1711000000.0",
            "completed_at": "",
        })
        mock_redis_cm.side_effect = _mock_async_redis(mock_redis)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/scan/backfill-csv")

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "already_running"
    mock_task.delay.assert_not_called()
