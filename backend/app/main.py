import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from slowapi.errors import RateLimitExceeded
from starlette.responses import JSONResponse

from app.config import settings, limiter, async_redis, get_jwt_secret, jwt_secret_persisted
from app.database import async_session
from app.api.router import api_router
from app.api.metrics_endpoint import router as metrics_router
from app.metrics import PrometheusMiddleware, start_queue_depth_probe, register_celery_collector
from app.schemas.error import ErrorEnvelope

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Warn if JWT secret was auto-generated. It's meant to be persisted to the
    # secret file (settings.jwt_secret_file) so it survives single-host
    # restarts; set GALACTILOG_JWT_SECRET explicitly for multi-host/multi-
    # instance setups. Generating it here (under this process's identity,
    # not a root-context entrypoint snippet) also confirms whether it was
    # actually persisted, so the log doesn't claim durability it can't back up.
    if not os.environ.get("GALACTILOG_JWT_SECRET"):
        secret = get_jwt_secret()
        if jwt_secret_persisted(settings.jwt_secret_file, secret):
            logger.warning(
                "GALACTILOG_JWT_SECRET is not set - using an auto-generated secret "
                "persisted to %s. Sessions survive restarts on this host. Set "
                "GALACTILOG_JWT_SECRET explicitly for multi-host/multi-instance deployments.",
                settings.jwt_secret_file,
            )
        else:
            logger.warning(
                "GALACTILOG_JWT_SECRET is not set and the auto-generated secret "
                "could not be persisted to %s (see the preceding warning for why). "
                "A new secret will be generated on every restart, invalidating all "
                "sessions. Set GALACTILOG_JWT_SECRET explicitly to avoid this.",
                settings.jwt_secret_file,
            )

    # Install the backend log capture handler (pushes to Redis, drained by Celery)
    from app.services.log_capture import (
        RedisLogHandler,
        CAPTURE_LEVEL_KEY,
        DEFAULT_LEVEL,
    )
    root_logger = logging.getLogger()
    if not any(isinstance(h, RedisLogHandler) for h in root_logger.handlers):
        root_logger.addHandler(RedisLogHandler(source="api"))
    # Lower the app logger so debug/info records reach the handler; the handler's
    # runtime capture floor decides what is actually recorded. The default root
    # level (WARNING) would otherwise drop debug/info at the call site, making the
    # capture-level setting below WARNING ineffective.
    logging.getLogger("app").setLevel(logging.DEBUG)
    # Seed the capture-level Redis key from stored settings so the configured
    # level survives Redis restarts and is visible to the worker/beat handlers
    # (which only read it from Redis).
    try:
        from sqlalchemy import select
        from app.models.user_settings import UserSettings, SETTINGS_ROW_ID
        async with async_session() as session:
            general = await session.scalar(
                select(UserSettings.general).where(UserSettings.id == SETTINGS_ROW_ID)
            )
        level = (general or {}).get("app_log_capture_level", DEFAULT_LEVEL)
        async with async_redis() as r:
            await r.set(CAPTURE_LEVEL_KEY, level)
    except Exception:
        logger.warning("Failed to seed app_logs capture level from settings", exc_info=True)

    # Ensure required PostgreSQL extensions exist (idempotent)
    from sqlalchemy import text
    async with async_session() as session:
        await session.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        await session.commit()

    # Delete legacy scan:activity Redis list replaced by activity_events table.
    try:
        async with async_redis() as r:
            await r.delete("scan:activity")
        logger.info("Deleted legacy scan:activity Redis key")
    except Exception as e:
        logger.warning("Failed to delete scan:activity key: %s", e)

    # Auto-create accounts from env vars if they don't already exist
    if settings.admin_password or settings.viewer_password:
        from app.models.user import User, UserRole
        from app.services.auth import hash_password
        from sqlalchemy import select

        async with async_session() as session:
            for username, password, role in [
                (settings.admin_username, settings.admin_password, UserRole.admin),
                (settings.viewer_username, settings.viewer_password, UserRole.viewer),
            ]:
                if not username or not password:
                    continue
                exists = await session.scalar(
                    select(User.id).where(User.username == username)
                )
                if exists:
                    continue
                session.add(User(
                    username=username,
                    password_hash=hash_password(password),
                    role=role,
                ))
                logger.info("%s user '%s' created from environment variables", role.value.capitalize(), username)
            await session.commit()

    # Dispatch dark hours backfill to Celery worker (runs in background,
    # doesn't block startup or the event loop)
    try:
        from app.worker.tasks import backfill_dark_hours
        backfill_dark_hours.apply_async(countdown=5)
        logger.info("Dark hours backfill task dispatched")
    except Exception as e:
        logger.warning("Failed to dispatch dark hours backfill: %s", e)

    # Backfill session_date for any images that don't have one yet
    try:
        from sqlalchemy import select, func as sa_func
        from app.models import Image
        async with async_session() as db:
            null_count = (await db.execute(
                select(sa_func.count(Image.id)).where(
                    Image.capture_date.isnot(None),
                    Image.session_date.is_(None),
                )
            )).scalar_one()
            if null_count > 0:
                from app.worker.tasks import recompute_session_dates
                recompute_session_dates.apply_async(countdown=10)
                logger.info("Queued session_date backfill for %d images", null_count)
    except Exception as e:
        logger.warning("Failed to check/dispatch session_date backfill: %s", e)

    # Start queue depth probe in the uvicorn process so gauges are visible
    # at the /metrics endpoint (worker and uvicorn have separate registries)
    from app.worker.celery_app import celery_app
    start_queue_depth_probe(celery_app, settings.redis_url)
    register_celery_collector(settings.redis_url)

    # Reconcile preview cache: drop orphaned metadata and on-disk strays
    try:
        from app.config import get_sync_redis
        from app.services.preview_cache import PreviewCache
        from pathlib import Path as _P
        redis = get_sync_redis()
        try:
            cache = PreviewCache(redis, _P(settings.previews_path), cap_bytes=1)
            summary = cache.reconcile()
            logger.info("Preview cache reconciled: %s", summary)
        finally:
            redis.close()
    except Exception as exc:
        logger.warning("Preview cache reconcile skipped: %s", exc)

    yield


def _resolve_cors_config(raw_origins: str | None, allow_credentials: bool = True):
    """Validate operator-supplied CORS origins.

    Returns ``(origins, allow_credentials)``.

    - Each origin must be well-formed (scheme http/https + host); malformed
      entries are dropped with a warning.
    - A wildcard ("*") combined with credentials is unsafe (and rejected by
      browsers anyway). If "*" is present we disable credentials so the
      server-side intent is explicit and safe.
    """
    if not raw_origins:
        return [], allow_credentials

    valid: list[str] = []
    has_wildcard = False
    for entry in raw_origins.split(","):
        origin = entry.strip()
        if not origin:
            continue
        if origin == "*":
            has_wildcard = True
            valid.append(origin)
            continue
        parsed = urlparse(origin)
        if parsed.scheme in ("http", "https") and parsed.netloc:
            valid.append(origin)
        else:
            logger.warning("Ignoring malformed CORS origin: %r", origin)

    if has_wildcard and allow_credentials:
        logger.warning(
            "CORS wildcard '*' is configured with credentials enabled; "
            "disabling allow_credentials (browsers reject '*' with credentials)."
        )
        allow_credentials = False

    return valid, allow_credentials


def create_app() -> FastAPI:
    application = FastAPI(
        title="GalactiLog",
        version="0.1.0",
        description="Astrophotography FITS file catalog and browser",
        lifespan=lifespan,
    )

    # Rate limiter
    application.state.limiter = limiter

    @application.exception_handler(RateLimitExceeded)
    async def rate_limit_handler(request, exc):
        return JSONResponse(status_code=429, content={"detail": "Rate limit exceeded"})

    @application.exception_handler(Exception)
    async def unhandled_exception_handler(request, exc):
        logger.exception(
            "Unhandled exception on %s %s",
            request.method,
            request.url.path,
        )
        # Emit a curated api_error event on a fresh session so it commits
        # independently of the request that failed. The full traceback is
        # captured separately into app_logs by the root-logger handler above.
        try:
            from app.services.activity import emit
            actor = None
            user = getattr(request.state, "user", None)
            if user is not None:
                actor = getattr(user, "username", None)
            async with async_session() as s:
                await emit(
                    s, category="system", severity="error", event_type="api_error",
                    message=f"{request.method} {request.url.path} failed: {type(exc).__name__}",
                    details={
                        "method": request.method,
                        "path": str(request.url.path),
                        "exception": str(exc)[:500],
                    },
                    actor=actor,
                )
        except Exception:
            logger.warning("Failed to emit api_error activity event", exc_info=True)
        return JSONResponse(
            status_code=500,
            content=ErrorEnvelope(detail="Internal server error").model_dump(),
        )

    # CORS for dev mode
    cors_origins, cors_allow_credentials = _resolve_cors_config(
        os.environ.get("GALACTILOG_CORS_ORIGINS"), allow_credentials=True
    )
    if cors_origins:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_credentials=cors_allow_credentials,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    # API routes
    application.include_router(api_router)
    application.include_router(metrics_router)

    application.add_middleware(PrometheusMiddleware)

    # Thumbnail endpoint with X-Accel-Redirect for nginx (must be
    # registered before the StaticFiles mount so it takes priority).
    from app.api.thumbnails import router as thumbnails_router
    application.include_router(thumbnails_router)

    # Serve generated thumbnails as static files (fallback for local dev
    # without nginx; the router above handles prod requests).
    thumbnails_dir = Path(settings.thumbnails_path)
    thumbnails_dir.mkdir(parents=True, exist_ok=True)
    application.mount(
        "/thumbnails",
        StaticFiles(directory=str(thumbnails_dir)),
        name="thumbnails",
    )

    # Serve preview cache files (nginx intercepts via X-Accel-Redirect in prod)
    previews_dir = Path(settings.previews_path)
    previews_dir.mkdir(parents=True, exist_ok=True)
    application.mount(
        "/_previews_internal",
        StaticFiles(directory=str(previews_dir)),
        name="previews_internal",
    )

    return application


app = create_app()
