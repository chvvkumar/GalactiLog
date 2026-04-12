import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from slowapi.errors import RateLimitExceeded
from starlette.responses import JSONResponse

from app.config import settings, limiter
from app.api.router import api_router
from app.api.metrics_endpoint import router as metrics_router
from app.metrics import PrometheusMiddleware

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Warn if JWT secret was auto-generated (won't survive restarts)
    if not os.environ.get("GALACTILOG_JWT_SECRET"):
        logger.warning("GALACTILOG_JWT_SECRET is not set - using auto-generated secret. Sessions will not survive restarts. Set GALACTILOG_JWT_SECRET in .env for persistence.")

    # Ensure required PostgreSQL extensions exist (idempotent)
    from app.database import async_session
    from sqlalchemy import text
    async with async_session() as session:
        await session.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        await session.commit()

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

    yield


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

    # CORS for dev mode
    cors_origins = os.environ.get("GALACTILOG_CORS_ORIGINS")
    if cors_origins:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=[o.strip() for o in cors_origins.split(",")],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    # API routes
    application.include_router(api_router)
    application.include_router(metrics_router)

    application.add_middleware(PrometheusMiddleware)

    # Serve generated thumbnails as static files
    thumbnails_dir = Path(settings.thumbnails_path)
    thumbnails_dir.mkdir(parents=True, exist_ok=True)
    application.mount(
        "/thumbnails",
        StaticFiles(directory=str(thumbnails_dir)),
        name="thumbnails",
    )

    return application


app = create_app()
