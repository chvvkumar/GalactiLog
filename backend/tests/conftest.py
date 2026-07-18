import os
import sys
from unittest.mock import MagicMock

os.environ.setdefault("GALACTILOG_DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test_catalog")
os.environ.setdefault("GALACTILOG_REDIS_URL", "redis://localhost:6379/1")
os.environ.setdefault("GALACTILOG_FITS_DATA_PATH", "/tmp/test_fits")
os.environ.setdefault("GALACTILOG_THUMBNAILS_PATH", "/tmp/test_thumbnails")
# Previews path must be writable: create_app() calls previews_dir.mkdir() at
# import time, and its default (/app/data/thumbnails/previews) is not writable
# on a non-root runner. Place it under the test thumbnails path above.
os.environ.setdefault("GALACTILOG_PREVIEWS_PATH", "/tmp/test_thumbnails/previews")
os.environ.setdefault("GALACTILOG_JWT_SECRET", "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2")
os.environ.setdefault("GALACTILOG_HTTPS", "false")

# Stub out native modules that may not be available in the test environment.
# Use the real library when it is importable (CI with compiled extensions);
# fall back to MagicMock only when it is absent (Windows dev without fitsio).
try:
    import fitsio as _fitsio_real  # noqa: F401
except ImportError:
    sys.modules.setdefault("fitsio", MagicMock())

# Stub out worker.tasks to avoid sync DB connection at import time
_tasks_mock = MagicMock()
sys.modules.setdefault("app.worker.tasks", _tasks_mock)

import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock as _MagicMock
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.database import get_session
from app.api.deps import get_current_user, require_admin
from app.models.user import User


@pytest.fixture
def mock_session():
    return AsyncMock()


@pytest.fixture
def admin_user():
    from app.models.user import UserRole
    user = _MagicMock(spec=User)
    user.id = uuid.uuid4()
    user.username = "admin"
    user.role = UserRole.admin
    user.is_active = True
    user.password_hash = "hashed"
    user.activity_seen_at = None
    return user


@pytest.fixture
def viewer_user():
    from app.models.user import UserRole
    user = _MagicMock(spec=User)
    user.id = uuid.uuid4()
    user.username = "viewer"
    user.role = UserRole.viewer
    user.is_active = True
    user.password_hash = "hashed"
    user.activity_seen_at = None
    return user
