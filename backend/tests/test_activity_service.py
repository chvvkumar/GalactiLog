import os, sys
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch
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
sys.modules.setdefault("app.worker.tasks", MagicMock())


def _redis_ctx(mock_r):
    @asynccontextmanager
    async def _ctx():
        yield mock_r
    return _ctx


@pytest.mark.asyncio
async def test_emit_inserts_row():
    from app.services.activity import emit
    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    mock_r = AsyncMock()
    mock_r.publish = AsyncMock()
    with patch("app.services.activity.async_redis", side_effect=_redis_ctx(mock_r)):
        await emit(db, category="scan", severity="info",
                   event_type="scan_complete", message="done", details={"n": 3})
    db.add.assert_called_once()
    db.commit.assert_called_once()
    added = db.add.call_args[0][0]
    assert added.severity == "info"
    assert added.category == "scan"
    assert added.details == {"n": 3}


@pytest.mark.asyncio
async def test_emit_publishes_to_redis():
    import json
    from app.services.activity import emit
    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    published = []
    mock_r = AsyncMock()
    async def capture(ch, data): published.append((ch, data))
    mock_r.publish = capture
    with patch("app.services.activity.async_redis", side_effect=_redis_ctx(mock_r)):
        await emit(db, category="scan", severity="warning",
                   event_type="scan_stalled", message="stalled")
    assert len(published) == 1
    ch, payload = published[0]
    assert ch == "activity:new"
    assert json.loads(payload)["event_type"] == "scan_stalled"


@pytest.mark.asyncio
async def test_emit_invalid_severity_raises_in_dev():
    import app.services.activity as activity_mod
    from app.services.activity import emit
    db = AsyncMock()
    with patch.object(activity_mod, "_ENV", "development"):
        with pytest.raises(ValueError, match="Invalid severity"):
            await emit(db, category="scan", severity="critical",
                       event_type="test", message="test")


@pytest.mark.asyncio
async def test_emit_invalid_severity_skips_in_prod():
    import app.services.activity as activity_mod
    from app.services.activity import emit
    db = AsyncMock()
    db.add = MagicMock()
    with patch.object(activity_mod, "_ENV", "production"):
        await emit(db, category="scan", severity="critical",
                   event_type="test", message="test")
    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_emit_db_failure_does_not_propagate():
    from app.services.activity import emit
    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock(side_effect=RuntimeError("DB down"))
    mock_r = AsyncMock()
    mock_r.publish = AsyncMock()
    with patch("app.services.activity.async_redis", side_effect=_redis_ctx(mock_r)):
        await emit(db, category="system", severity="error",
                   event_type="startup", message="test")
    # Must not raise


@pytest.mark.asyncio
async def test_emit_invalid_category_skips_in_prod():
    import app.services.activity as activity_mod
    from app.services.activity import emit
    db = AsyncMock()
    db.add = MagicMock()
    with patch.object(activity_mod, "_ENV", "production"):
        await emit(db, category="unknown_xyz", severity="info",
                   event_type="test", message="test")
    db.add.assert_not_called()


def test_emit_sync_inserts_row():
    from app.services.activity import emit_sync
    db = MagicMock()
    redis = MagicMock()
    emit_sync(db, redis=redis, category="rebuild", severity="info",
              event_type="rebuild_complete", message="done")
    db.add.assert_called_once()
    db.commit.assert_called_once()
    assert db.add.call_args[0][0].event_type == "rebuild_complete"
