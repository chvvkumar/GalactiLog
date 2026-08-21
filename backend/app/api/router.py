import json
import logging
import os

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
from .jobs import router as jobs_router
from .backup import router as backup_router
from .bootstrap import router as bootstrap_router
from .preview import router as preview_router
from .activity import router as activity_router
from .logs import router as logs_router
from .integrations import router as integrations_router
from .wbpp import router as wbpp_router
from .phd2 import router as phd2_router
from app.database import async_session
from app.config import async_redis
from app.services.version_check import (
    GITHUB_REPO,
    IMAGE_REPO,
    fetch_latest_release,
    fetch_remote_build,
    tag_for_version,
)

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
api_router.include_router(jobs_router)
api_router.include_router(backup_router)
api_router.include_router(bootstrap_router)
api_router.include_router(preview_router)
api_router.include_router(activity_router)
api_router.include_router(logs_router)
api_router.include_router(integrations_router)
api_router.include_router(wbpp_router)
api_router.include_router(phd2_router)


@api_router.get("/version")
async def version():
    return {
        "version": os.environ.get("GALACTILOG_VERSION", "dev"),
        "git_sha": os.environ.get("GALACTILOG_GIT_SHA", "unknown"),
    }


_REMOTE_CACHE_TTL = 3600  # 1 hour
_RELEASE_CACHE_KEY = "galactilog:version:release:latest"


async def _latest_release():
    """Return the latest GitHub release notes dict (or None), cached in Redis
    for 1 hour. Redis and GitHub failures are swallowed; the worst case is
    None, so the version endpoint never fails because of release notes."""
    try:
        async with async_redis() as r:
            raw = await r.get(_RELEASE_CACHE_KEY)
        if raw:
            return json.loads(raw)
    except Exception:
        logger.debug("Redis cache read failed for latest release")

    release = await fetch_latest_release(GITHUB_REPO)
    if release is not None:
        try:
            async with async_redis() as r:
                await r.setex(_RELEASE_CACHE_KEY, _REMOTE_CACHE_TTL, json.dumps(release))
        except Exception:
            logger.debug("Redis cache write failed for latest release")
    return release


@api_router.get("/version/latest")
async def latest_version():
    """Report whether a newer build of the running channel is available.

    Reads the git_sha baked into the published Docker image for the running
    build's moving tag (snd / dev / latest) and compares it to the running
    container's git_sha. The remote lookup is cached in Redis for 1 hour.
    """
    running = os.environ.get("GALACTILOG_VERSION", "dev")
    running_sha = os.environ.get("GALACTILOG_GIT_SHA", "unknown")

    # Latest GitHub release notes, fetched and cached independently of the
    # Docker-tag detection below. Never fails the endpoint: on any error the
    # release is simply None.
    release = await _latest_release()

    tag = tag_for_version(running)
    if tag is None:
        return {
            "available": False,
            "running": running,
            "running_sha": running_sha,
            "is_newer": False,
            "source": "dockerhub",
            "release": release,
        }

    try:
        cache_key = f"galactilog:version:remote:{tag}"
        result = None

        # Try cache first.
        try:
            async with async_redis() as r:
                raw = await r.get(cache_key)
            if raw:
                result = json.loads(raw)
        except Exception:
            logger.debug("Redis cache read failed for remote version")

        if result is None:
            result = await fetch_remote_build(IMAGE_REPO, tag)
            if result is not None:
                try:
                    async with async_redis() as r:
                        await r.setex(cache_key, _REMOTE_CACHE_TTL, json.dumps(result))
                except Exception:
                    logger.debug("Redis cache write failed for remote version")

        remote_sha = result["git_sha"] if result else None
        is_newer = bool(
            remote_sha
            and running_sha
            and running_sha != "unknown"
            and remote_sha != running_sha
        )
        compare_url = (
            f"https://github.com/chvvkumar/GalactiLog/compare/{running_sha}...{remote_sha}"
            if remote_sha and running_sha and running_sha != "unknown"
            else None
        )

        return {
            "available": bool(result),
            "running": running,
            "running_sha": running_sha,
            "is_newer": is_newer,
            "tag": tag,
            "remote_sha": remote_sha,
            "published_at": (result or {}).get("published_at"),
            "compare_url": compare_url,
            "source": "dockerhub",
            "release": release,
        }
    except Exception:
        # Redis/Docker Hub/JSON failures carry internal hosts and library
        # detail, so the client gets a fixed string (py/stack-trace-exposure).
        logger.exception("version/latest lookup failed for tag %s", tag)
        return {
            "available": False,
            "running": running,
            "running_sha": running_sha,
            "is_newer": False,
            "source": "dockerhub",
            "error": "Version check failed - see server logs for details.",
            "release": release,
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
