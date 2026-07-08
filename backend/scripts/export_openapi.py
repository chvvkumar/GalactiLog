"""Export the FastAPI app's OpenAPI schema to frontend/openapi.json.

Imports the app object directly and calls `.openapi()` -- this builds the
schema from route metadata without running the app's lifespan (no DB
connections, no Redis, no startup side effects). No running server needed.

Run from the backend/ directory:
    python -m scripts.export_openapi
"""

import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

# Same defaults/stubs as tests/conftest.py: satisfy settings validation and
# avoid importing native/sync-DB modules that aren't needed to build the
# OpenAPI schema (route metadata only -- no lifespan, no real DB/Redis calls).
os.environ.setdefault("GALACTILOG_DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test_catalog")
os.environ.setdefault("GALACTILOG_REDIS_URL", "redis://localhost:6379/1")
os.environ.setdefault("GALACTILOG_FITS_DATA_PATH", "/tmp/export_openapi_fits")
os.environ.setdefault("GALACTILOG_THUMBNAILS_PATH", "/tmp/export_openapi_thumbnails")
os.environ.setdefault("GALACTILOG_PREVIEWS_PATH", "/tmp/export_openapi_thumbnails/previews")
os.environ.setdefault("GALACTILOG_JWT_SECRET", "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2")
os.environ.setdefault("GALACTILOG_HTTPS", "false")

try:
    import fitsio  # noqa: F401
except ImportError:
    sys.modules.setdefault("fitsio", MagicMock())

sys.modules.setdefault("app.worker.tasks", MagicMock())

from app.main import create_app


def main() -> None:
    app = create_app()
    schema = app.openapi()
    # backend/scripts/export_openapi.py -> parents[0]=scripts, [1]=backend, [2]=repo root
    out = Path(__file__).resolve().parents[2] / "frontend" / "openapi.json"
    out.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n")
    print(f"Wrote OpenAPI schema to {out}")


if __name__ == "__main__":
    main()
