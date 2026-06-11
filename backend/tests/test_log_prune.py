import os
import sys
from unittest.mock import MagicMock

os.environ.setdefault("GALACTILOG_DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test_catalog")
os.environ.setdefault("GALACTILOG_REDIS_URL", "redis://localhost:6379/1")
os.environ.setdefault("GALACTILOG_JWT_SECRET", "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2")
os.environ.setdefault("GALACTILOG_HTTPS", "false")
for _mod in ("fitsio",):
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()
sys.modules.setdefault("app.worker.tasks", MagicMock())

from app.worker.prune_activity import _compute_app_log_deletes  # noqa: E402


def test_keeps_within_limits():
    # 100 rows, max_rows above count -> nothing deleted
    plan = _compute_app_log_deletes(total_rows=100, max_rows=50000)
    assert plan["excess_rows"] == 0


def test_max_rows_excess():
    plan = _compute_app_log_deletes(total_rows=60000, max_rows=50000)
    assert plan["excess_rows"] == 10000
