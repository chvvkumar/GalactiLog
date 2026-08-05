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


def bootstrap_worker_module(modname):
    """Import a worker module with its sync DB engine mocked out.

    Several test files need the real code of one app.worker.tasks_* module
    without a live Postgres behind it: they patch the module's own Session or
    _sync_engine per test. Importing under a patched sqlalchemy.create_engine
    is how they get that.

    The engine itself lives in app.worker.tasks_common, which builds it once
    at module import and which every domain module binds by name. That makes
    the patched import leak: whichever caller imports first pulls
    tasks_common in under the patch, and the MagicMock-engine copy then STAYS
    in sys.modules for every module imported afterwards, including ones whose
    tests do need a real engine. The failure is silent, because a MagicMock
    result set iterates empty rather than raising, so a DB-reading test on the
    far side of the leak passes vacuously. Which tests land on the far side
    depended only on the alphabetical order of the file names.

    So tasks_common is popped on both sides of the import: before, so the
    patch actually applies to the copy this module will bind; after, so the
    next importer that wants a real engine builds one. Callers that already
    hold the mocked copy keep it, which is what they asked for.

    Returns the imported module. A module already present and not a MagicMock
    is returned as-is, which is what makes repeated calls cheap.
    """
    import importlib
    from unittest.mock import patch

    cached = sys.modules.get(modname)
    if cached is not None and not isinstance(cached, MagicMock):
        return cached

    common = "app.worker.tasks_common"
    sys.modules.pop(modname, None)
    sys.modules.pop(common, None)

    mock_engine = MagicMock()
    mock_engine.connect.return_value.__enter__ = MagicMock(return_value=mock_engine)
    mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)
    try:
        with patch("sqlalchemy.create_engine", return_value=mock_engine):
            return importlib.import_module(modname)
    finally:
        sys.modules.pop(common, None)

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
