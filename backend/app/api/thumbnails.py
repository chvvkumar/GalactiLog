"""Thumbnail serving endpoint with nginx X-Accel-Redirect support.

When running behind nginx the X-Accel-Redirect header lets nginx stream
the file directly from disk, bypassing Python/uvicorn for the actual
bytes.  The ``/_thumbnails_internal/`` location must be configured as
``internal`` in the nginx server block::

    location /_thumbnails_internal/ {
        internal;
        alias /app/data/thumbnails/;
    }

When running locally without nginx the response falls back to a normal
FileResponse (the header is simply ignored by non-nginx clients).
"""

import logging
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.config import settings
from app.services.path_safety import resolve_relative_under

logger = logging.getLogger(__name__)

router = APIRouter(tags=["thumbnails"])


@router.get("/thumbnails/{file_path:path}")
async def serve_thumbnail(file_path: str) -> FileResponse:
    """Serve a generated thumbnail image.

    Returns an ``X-Accel-Redirect`` header so nginx can stream the file
    directly.  The response body (FileResponse) acts as a fallback when
    nginx is not in front.
    """
    # --- Path traversal guard -------------------------------------------
    # The whole URL path segment is attacker-controlled, so it is confined
    # to the thumbnails root before any filesystem call touches it.
    thumbnails_dir = Path(settings.thumbnails_path).resolve()
    try:
        full_path = resolve_relative_under(thumbnails_dir, file_path)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid path")

    if not full_path.is_file():
        raise HTTPException(status_code=404, detail="Thumbnail not found")

    # Build the internal redirect path preserving sub-directories
    # (e.g. "reference/abc.jpg" -> "/_thumbnails_internal/reference/abc.jpg").
    # Derived from the validated path, never from the raw request, so nginx
    # is handed the same location this handler just authorised.
    rel_posix = full_path.relative_to(thumbnails_dir).as_posix()
    internal_path = f"/_thumbnails_internal/{quote(rel_posix)}"

    return FileResponse(
        path=full_path,
        media_type="image/jpeg",
        headers={
            "X-Accel-Redirect": internal_path,
            "Cache-Control": "public, max-age=86400",
        },
    )
