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

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Warn if JWT secret was auto-generated (won't survive restarts)
    if not os.environ.get("GALACTILOG_JWT_SECRET"):
        logger.warning("GALACTILOG_JWT_SECRET is not set — using auto-generated secret. Sessions will not survive restarts. Set GALACTILOG_JWT_SECRET in .env for persistence.")

    # Ensure database tables exist on startup
    from app.database import engine
    from app.models import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables verified/created")

    # Auto-create accounts from env vars if they don't already exist
    if settings.admin_password or settings.viewer_password:
        from app.database import async_session
        from app.models.user import User
        from app.services.auth import hash_password
        from sqlalchemy import select

        async with async_session() as session:
            for username, password, role in [
                (settings.admin_username, settings.admin_password, "admin"),
                (settings.viewer_username, settings.viewer_password, "viewer"),
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
                logger.info("%s user '%s' created from environment variables", role.capitalize(), username)
            await session.commit()

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
