import json
import logging
import os
import re

import httpx
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

logger = logging.getLogger(__name__)

from .targets import router as targets_router
from .scan import router as scan_router
from .stats import router as stats_router
from .settings import router as settings_router
from .merges import router as merges_router
from .auth import router as auth_router
from .analysis import router as analysis_router
from .mosaics import router as mosaics_router
from .custom_columns import router as custom_columns_router
from .filename_resolution import router as filename_resolution_router
from .tasks import router as tasks_router
from .backup import router as backup_router
from .planning import router as planning_router
from .bootstrap import router as bootstrap_router
from .preview import router as preview_router
from .activity import router as activity_router
from .integrations import router as integrations_router
from app.database import async_session
from app.config import async_redis

api_router = APIRouter(prefix="/api")
api_router.include_router(targets_router)
api_router.include_router(scan_router)
api_router.include_router(stats_router)
api_router.include_router(settings_router)
api_router.include_router(merges_router)
api_router.include_router(auth_router)
api_router.include_router(analysis_router)
api_router.include_router(mosaics_router)
api_router.include_router(custom_columns_router)
api_router.include_router(filename_resolution_router)
api_router.include_router(tasks_router)
api_router.include_router(backup_router)
api_router.include_router(planning_router)
api_router.include_router(bootstrap_router)
api_router.include_router(preview_router)
api_router.include_router(activity_router)
api_router.include_router(integrations_router)


@api_router.get("/version")
async def version():
    return {
        "version": os.environ.get("GALACTILOG_VERSION", "dev"),
        "git_sha": os.environ.get("GALACTILOG_GIT_SHA", "unknown"),
    }


_SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:-rc\.(\d+))?$")
_LATEST_CACHE_KEY = "galactilog:version:latest"
_LATEST_CACHE_TTL = 3600  # 1 hour


def _semver_key(v: str) -> tuple | None:
    m = _SEMVER_RE.match(v)
    if not m:
        return None
    major, minor, patch, rc = m.groups()
    # Stable release sorts after any rc of the same (major, minor, patch).
    # Use a large sentinel for stable so it wins over any rc number.
    rc_rank = int(rc) if rc is not None else 10**9
    return (int(major), int(minor), int(patch), rc_rank)


@api_router.get("/version/latest")
async def latest_version():
    """Return the latest stable release from GitHub and whether the running
    build is older than it. Cached in Redis for 1 hour.
    """
    running = os.environ.get("GALACTILOG_VERSION", "dev")

    # Try cache first
    cached_payload = None
    try:
        async with async_redis() as r:
            raw = await r.get(_LATEST_CACHE_KEY)
        if raw:
            cached_payload = json.loads(raw)
    except Exception:
        logger.debug("Redis cache read failed for latest version")

    if cached_payload is None:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(
                    "https://api.github.com/repos/chvvkumar/GalactiLog/releases/latest",
                    headers={"Accept": "application/vnd.github+json"},
                )
            if resp.status_code != 200:
                return {
                    "available": False,
                    "error": f"GitHub API returned {resp.status_code}",
                    "running": running,
                }
            data = resp.json()
            cached_payload = {
                "tag": data.get("tag_name"),
                "name": data.get("name"),
                "url": data.get("html_url"),
                "published_at": data.get("published_at"),
                "body": data.get("body") or "",
            }
            try:
                async with async_redis() as r:
                    await r.setex(_LATEST_CACHE_KEY, _LATEST_CACHE_TTL, json.dumps(cached_payload))
            except Exception:
                logger.debug("Redis cache write failed for latest version")
        except Exception as e:
            return {"available": False, "error": str(e), "running": running}

    running_key = _semver_key(running)
    latest_key = _semver_key(cached_payload.get("tag") or "")
    is_newer = bool(running_key and latest_key and latest_key > running_key)

    return {
        "available": True,
        "running": running,
        "is_newer": is_newer,
        **cached_payload,
    }


@api_router.get("/health")
async def health():
    checks = {"postgres": "ok", "redis": "ok"}

    try:
        async with async_session() as session:
            await session.execute(text("SELECT 1"))
    except Exception:
        checks["postgres"] = "unavailable"

    try:
        async with async_redis() as r:
            await r.ping()
    except Exception:
        checks["redis"] = "unavailable"

    healthy = all(v == "ok" for v in checks.values())
    status_code = 200 if healthy else 503
    return JSONResponse(
        content={"status": "ok" if healthy else "degraded", **checks},
        status_code=status_code,
    )
