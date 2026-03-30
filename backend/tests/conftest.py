import os
import sys
from unittest.mock import MagicMock

os.environ.setdefault("GALACTILOG_DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test_catalog")
os.environ.setdefault("GALACTILOG_REDIS_URL", "redis://localhost:6379/1")
os.environ.setdefault("GALACTILOG_FITS_DATA_PATH", "/tmp/test_fits")
os.environ.setdefault("GALACTILOG_THUMBNAILS_PATH", "/tmp/test_thumbnails")
os.environ.setdefault("GALACTILOG_JWT_SECRET", "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2")
os.environ.setdefault("GALACTILOG_HTTPS", "false")

# Stub out native modules that may not be available in the test environment
for _mod in ("fitsio",):
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()

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
    return user
