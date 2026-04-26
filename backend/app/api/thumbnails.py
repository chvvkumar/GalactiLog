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
from pathlib import Path, PurePosixPath

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.config import settings

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
    # Normalise the requested path and ensure it stays inside the
    # thumbnails directory.  Reject anything that resolves outside.
    thumbnails_dir = Path(settings.thumbnails_path).resolve()

    # Use PurePosixPath to normalise forward-slash segments coming from
    # the URL, then resolve against the thumbnails root.
    rel = PurePosixPath(file_path)
    if rel.is_absolute():
        raise HTTPException(status_code=400, detail="Invalid path")

    full_path = (thumbnails_dir / rel).resolve()

    # Verify the resolved path is still under the thumbnails directory
    if not full_path.is_relative_to(thumbnails_dir):
        raise HTTPException(status_code=400, detail="Invalid path")

    if not full_path.is_file():
        raise HTTPException(status_code=404, detail="Thumbnail not found")

    # Build the internal redirect path preserving sub-directories
    # (e.g. "reference/abc.jpg" -> "/_thumbnails_internal/reference/abc.jpg")
    internal_path = f"/_thumbnails_internal/{file_path}"

    return FileResponse(
        path=full_path,
        media_type="image/jpeg",
        headers={
            "X-Accel-Redirect": internal_path,
            "Cache-Control": "public, max-age=86400",
        },
    )
