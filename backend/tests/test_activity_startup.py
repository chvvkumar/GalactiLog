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


@pytest.mark.asyncio
async def test_startup_deletes_scan_activity_key():
    deleted_keys = []

    mock_r = AsyncMock()
    async def capture_delete(*keys):
        deleted_keys.extend(keys)
    mock_r.delete = capture_delete

    @asynccontextmanager
    async def _ctx():
        yield mock_r

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock()
    mock_db.commit = AsyncMock()
    mock_db.scalar = AsyncMock(return_value=0)

    @asynccontextmanager
    async def _session_ctx():
        yield mock_db

    with patch("app.main.async_redis", side_effect=_ctx), \
         patch("app.main.async_session", side_effect=_session_ctx), \
         patch("app.main.start_queue_depth_probe"), \
         patch("app.main.register_celery_collector"):
        from app.main import lifespan, app as fastapi_app
        async with lifespan(fastapi_app):
            pass

    assert "scan:activity" in deleted_keys
