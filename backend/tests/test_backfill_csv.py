"""Tests for the backfill_csv_metrics Celery task and /scan/backfill-csv endpoint.

NOTE: app.worker.tasks creates a sync DB engine at module-level import.
We intercept this via sys.modules stubbing before first import.
"""
import sys
import types
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
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
    """Import app.worker.tasks_csv (owns backfill_csv_metrics since the
    Phase 6 Task 3 module split) with the DB engine mocked out.

    This runs at COLLECTION time, so it is usually the first mocked import of
    the run. See conftest.bootstrap_worker_module for why the mocked engine
    must not be left behind in sys.modules."""
    from tests.conftest import bootstrap_worker_module

    return bootstrap_worker_module("app.worker.tasks_csv")


# Bootstrap once at module level (runs during collection)
_tasks = _bootstrap_tasks_module()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_row(id_="img-001", file_name="Light_001.fits", **existing):
    """Create a fake DB row carrying the current value of every mergeable column.

    A SimpleNamespace, not a MagicMock, on purpose: the task reads the row's
    pre-existing column values to decide what a CSV blank may overwrite, and a
    MagicMock would hand back a truthy auto-attribute for every column, which
    would make a "None must not erase a real value" test pass for the wrong
    reason. Unspecified columns default to None (the DB's own default).
    """
    values = {
        col: None
        for col in _tasks.CSV_MERGE_COLUMNS + _tasks._PROVENANCE_COLUMNS
    }
    values.update(existing)
    return SimpleNamespace(id=id_, file_name=file_name, **values)


def _blank_csv_entry(**real_values):
    """A parsed CSV row where every mapped column is blank (None).

    _parse_image_csv emits a key for EVERY mapped column, so this is the shape
    the task actually receives for a CSV whose cells are empty -- the shape
    that used to null out real header-derived values on backfill.
    """
    entry = {col: None for col in _tasks.CSV_MERGE_COLUMNS}
    entry.update(real_values)
    return entry


def _captured_updates(mock_conn):
    """Extract the .values() payload of every UPDATE passed to conn.execute."""
    from sqlalchemy.sql.dml import Update
    from sqlalchemy.sql.elements import BindParameter

    payloads = []
    for call in mock_conn.execute.call_args_list:
        stmt = call.args[0]
        if isinstance(stmt, Update):
            payloads.append({
                col.name: (val.value if isinstance(val, BindParameter) else val)
                for col, val in stmt._values.items()
            })
    return payloads


# ── Task tests ────────────────────────────────────────────────────────────────

def test_backfill_csv_metrics_no_csv_dirs(tmp_path):
    """Task returns early when no ImageMetaData.csv files are found."""
    import redis as _redis_module

    with patch.object(_redis_module, "from_url") as mock_from_url, \
         patch.object(_tasks, "settings") as mock_settings, \
         patch.object(_tasks, "set_idle_sync") as mock_idle, \
         patch.object(_tasks, "parse_image_metadata_csv") as mock_image_csv:

        mock_settings.fits_data_path = str(tmp_path)
        mock_settings.redis_url = "redis://localhost:6379/1"
        mock_redis_conn = MagicMock()
        mock_from_url.return_value = mock_redis_conn

        result = _tasks.backfill_csv_metrics()

    assert result == {"updated": 0, "dirs": 0}
    mock_idle.assert_called_once_with(mock_redis_conn)
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
         patch.object(_tasks, "set_ingesting_sync") as mock_ingesting, \
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
    mock_ingesting.assert_called_once_with(mock_redis_conn, total=1, kind="csv_backfill")
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


# ── Merge semantics on the UPDATE path ────────────────────────────────────────
# The backfill writes over rows that already hold header-derived values, so the
# merge rules differ from ingest: there, a key the header never set is
# legitimately written as None onto a fresh row; here, writing None over a
# stored value destroys it. These pin that distinction.

def _run_backfill(tmp_path, image_data, weather_data, rows):
    """Drive backfill_csv_metrics over one CSV dir, returning (result, conn)."""
    csv_dir = tmp_path / "session1"
    csv_dir.mkdir()
    (csv_dir / "ImageMetaData.csv").write_text("FilePath,HFR\n")

    import redis as _redis_module

    mock_conn = MagicMock()
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)
    mock_conn.execute.return_value.fetchall.return_value = rows

    with patch.object(_redis_module, "from_url") as mock_from_url, \
         patch.object(_tasks, "settings") as mock_settings, \
         patch.object(_tasks, "_sync_engine") as mock_engine, \
         patch.object(_tasks, "set_idle_sync"), \
         patch.object(_tasks, "set_ingesting_sync"), \
         patch.object(_tasks, "increment_completed_sync"), \
         patch.object(_tasks, "parse_image_metadata_csv") as mock_image_csv, \
         patch.object(_tasks, "parse_weather_csv") as mock_weather_csv:

        mock_settings.fits_data_path = str(tmp_path)
        mock_settings.redis_url = "redis://localhost:6379/1"
        mock_from_url.return_value = MagicMock()
        mock_image_csv.return_value = image_data
        mock_weather_csv.return_value = weather_data
        mock_engine.connect.return_value = mock_conn

        result = _tasks.backfill_csv_metrics()

    return result, mock_conn


def test_backfill_blank_csv_cell_does_not_erase_header_value(tmp_path):
    """A blank CSV cell must not null a real header-derived value on UPDATE.

    The row already carries a header eccentricity and HFR; the CSV has those
    cells empty but does supply a star count. The UPDATE must write the star
    count without touching the two values the CSV is silent about.
    """
    row = _make_row(eccentricity=0.42, median_hfr=2.1, eccentricity_source="header")
    entry = _blank_csv_entry(detected_stars=1234)
    entry["_exposure_start_utc"] = "2024-01-01T00:00:00"

    result, conn = _run_backfill(
        tmp_path, {"Light_001.fits": entry}, {}, [row]
    )

    updates = _captured_updates(conn)
    assert len(updates) == 1
    values = updates[0]
    assert values["detected_stars"] == 1234
    # The destructive writes: either absent from the UPDATE, or unchanged.
    assert values.get("eccentricity", 0.42) == 0.42
    assert values.get("median_hfr", 2.1) == 2.1
    assert values.get("eccentricity_source", "header") == "header"
    assert result["updated"] == 1


def test_backfill_real_csv_value_still_wins_over_stored_value(tmp_path):
    """A real CSV value must still overwrite the stored header value.

    The N.I.N.A. plugin measures the frame itself, so where both exist the CSV
    is the better number. Not erasing must not become never updating.
    """
    row = _make_row(eccentricity=0.42, median_hfr=2.1, eccentricity_source="header")
    entry = _blank_csv_entry(median_hfr=1.5)

    _, conn = _run_backfill(tmp_path, {"Light_001.fits": entry}, {}, [row])

    values = _captured_updates(conn)[0]
    assert values["median_hfr"] == 1.5


def test_backfill_stamps_eccentricity_source_when_csv_supplies_it(tmp_path):
    """Writing a CSV eccentricity must re-stamp provenance to "csv".

    Leaving the stored "header" source in place would label a CSV-measured
    number as header-derived, and the two are not comparable.
    """
    row = _make_row(eccentricity=0.42, eccentricity_source="header")
    entry = _blank_csv_entry(eccentricity=0.31)

    _, conn = _run_backfill(tmp_path, {"Light_001.fits": entry}, {}, [row])

    values = _captured_updates(conn)[0]
    assert values["eccentricity"] == 0.31
    assert values["eccentricity_source"] == "csv"


def test_backfill_leaves_source_alone_when_csv_has_no_eccentricity(tmp_path):
    """A CSV that says nothing about eccentricity must not touch provenance."""
    row = _make_row(eccentricity=0.42, eccentricity_source="header")
    entry = _blank_csv_entry(detected_stars=900)

    _, conn = _run_backfill(tmp_path, {"Light_001.fits": entry}, {}, [row])

    values = _captured_updates(conn)[0]
    assert values.get("eccentricity_source", "header") == "header"


def test_backfill_stamps_guiding_rms_source_when_csv_supplies_guiding(tmp_path):
    """Replayed CSV guiding values must carry their provenance to the row.

    The guide log is the other writer of these columns, so a backfilled value
    that arrives unlabelled is indistinguishable from a PHD2-derived one.
    """
    row = _make_row()
    entry = _blank_csv_entry(guiding_rms_arcsec=0.78, guiding_rms_ra_arcsec=0.52)

    _, conn = _run_backfill(tmp_path, {"Light_001.fits": entry}, {}, [row])

    values = _captured_updates(conn)[0]
    assert values["guiding_rms_arcsec"] == 0.78
    assert values["guiding_rms_source"] == "csv"


def test_backfill_leaves_guiding_source_alone_when_csv_has_no_guiding(tmp_path):
    """A CSV silent about guiding must not relabel a guide-log value."""
    row = _make_row(guiding_rms_arcsec=0.61, guiding_rms_source="phd2")
    entry = _blank_csv_entry(detected_stars=900)

    _, conn = _run_backfill(tmp_path, {"Light_001.fits": entry}, {}, [row])

    values = _captured_updates(conn)[0]
    assert values.get("guiding_rms_arcsec", 0.61) == 0.61
    assert values.get("guiding_rms_source", "phd2") == "phd2"


def test_backfill_issues_no_update_when_csv_changes_nothing(tmp_path):
    """An all-blank CSV row must produce no UPDATE at all.

    Every column the CSV could write is already either equal or unmentioned,
    so there is nothing to write and nothing to count as updated.
    """
    row = _make_row(median_hfr=2.1, detected_stars=1234)
    entry = _blank_csv_entry(median_hfr=2.1)

    result, conn = _run_backfill(tmp_path, {"Light_001.fits": entry}, {}, [row])

    assert _captured_updates(conn) == []
    assert result["updated"] == 0


def test_backfill_merges_weather_without_erasing_stored_weather(tmp_path):
    """Weather joins in, and a blank weather cell does not erase a stored one."""
    row = _make_row(ambient_temp=-3.0, humidity=55.0)
    entry = _blank_csv_entry(detected_stars=10)
    entry["_exposure_start_utc"] = "2024-01-01T00:00:00"
    weather = {"2024-01-01T00:00:00": {"ambient_temp": -5.0, "humidity": None}}

    _, conn = _run_backfill(tmp_path, {"Light_001.fits": entry}, weather, [row])

    values = _captured_updates(conn)[0]
    assert values["ambient_temp"] == -5.0          # real CSV value wins
    assert values.get("humidity", 55.0) == 55.0    # blank must not erase


# ── API endpoint tests ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_backfill_csv_endpoint_accepted():
    """POST /scan/backfill-csv returns accepted when state is idle."""
    import uuid
    from httpx import AsyncClient, ASGITransport
    from app.main import app
    from app.api.deps import require_admin
    from app.models.user import User, UserRole

    def _admin_override():
        user = MagicMock(spec=User)
        user.id = uuid.uuid4()
        user.role = UserRole.admin
        user.is_active = True
        return user

    with patch("app.api.scan.async_redis") as mock_redis_cm, \
         patch("app.api.scan.backfill_csv_metrics") as mock_task:
        mock_task.delay = MagicMock()
        mock_redis = AsyncMock()
        mock_redis.hgetall = AsyncMock(return_value={})
        mock_redis.exists = AsyncMock(return_value=0)  # no scan already dispatched
        mock_redis_cm.side_effect = _mock_async_redis(mock_redis)

        app.dependency_overrides[require_admin] = _admin_override
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post("/api/scan/backfill-csv")
        finally:
            app.dependency_overrides.pop(require_admin, None)

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "accepted"
    mock_task.delay.assert_called_once()


@pytest.mark.asyncio
async def test_backfill_csv_endpoint_accepted_after_scan_complete():
    """POST /scan/backfill-csv dispatches the task when state is "complete".

    AUD-002: a completed scan (or a completed prior backfill) leaves
    scan:state at "complete" with a 24h TTL. The endpoint used to gate on
    `state.state != "idle"`, which treated "complete" as "already running"
    and silently refused to dispatch for up to 24h after any scan.
    """
    import uuid
    from httpx import AsyncClient, ASGITransport
    from app.main import app
    from app.api.deps import require_admin
    from app.models.user import User, UserRole

    def _admin_override():
        user = MagicMock(spec=User)
        user.id = uuid.uuid4()
        user.role = UserRole.admin
        user.is_active = True
        return user

    with patch("app.api.scan.async_redis") as mock_redis_cm, \
         patch("app.api.scan.backfill_csv_metrics") as mock_task:
        mock_task.delay = MagicMock()
        mock_redis = AsyncMock()
        mock_redis.hgetall = AsyncMock(return_value={
            "state": "complete",
            "total": "0",
            "completed": "0",
            "failed": "0",
            "started_at": "1711000000.0",
            "completed_at": "1711000100.0",
        })
        mock_redis.exists = AsyncMock(return_value=0)  # no scan already dispatched
        mock_redis_cm.side_effect = _mock_async_redis(mock_redis)

        app.dependency_overrides[require_admin] = _admin_override
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post("/api/scan/backfill-csv")
        finally:
            app.dependency_overrides.pop(require_admin, None)

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "accepted"
    mock_task.delay.assert_called_once()


@pytest.mark.asyncio
async def test_backfill_csv_endpoint_already_running_scanning():
    """POST /scan/backfill-csv returns already_running when scanning."""
    import uuid
    from httpx import AsyncClient, ASGITransport
    from app.main import app
    from app.api.deps import require_admin
    from app.models.user import User, UserRole

    def _admin_override():
        user = MagicMock(spec=User)
        user.id = uuid.uuid4()
        user.role = UserRole.admin
        user.is_active = True
        return user

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

        app.dependency_overrides[require_admin] = _admin_override
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post("/api/scan/backfill-csv")
        finally:
            app.dependency_overrides.pop(require_admin, None)

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "already_running"
    assert data["state"] == "scanning"
    mock_task.delay.assert_not_called()


@pytest.mark.asyncio
async def test_backfill_csv_endpoint_already_running_ingesting():
    """POST /scan/backfill-csv returns already_running when ingesting."""
    import uuid
    from httpx import AsyncClient, ASGITransport
    from app.main import app
    from app.api.deps import require_admin
    from app.models.user import User, UserRole

    def _admin_override():
        user = MagicMock(spec=User)
        user.id = uuid.uuid4()
        user.role = UserRole.admin
        user.is_active = True
        return user

    with patch("app.api.scan.async_redis") as mock_redis_cm, \
         patch("app.api.scan.backfill_csv_metrics") as mock_task:
        mock_task.delay = MagicMock()
        import time as _time
        mock_redis = AsyncMock()
        mock_redis.hgetall = AsyncMock(return_value={
            "state": "ingesting",
            "total": "50",
            "completed": "10",
            "failed": "0",
            "started_at": "1711000000.0",
            "completed_at": "",
        })
        # Return a recent timestamp so the stale-scan detection does not trigger
        mock_redis.get = AsyncMock(return_value=str(_time.time()))
        mock_redis_cm.side_effect = _mock_async_redis(mock_redis)

        app.dependency_overrides[require_admin] = _admin_override
        try:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post("/api/scan/backfill-csv")
        finally:
            app.dependency_overrides.pop(require_admin, None)

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "already_running"
    mock_task.delay.assert_not_called()
