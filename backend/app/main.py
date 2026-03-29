import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.api.router import api_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ensure database tables exist on startup
    from app.database import engine
    from app.models import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables verified/created")

    yield


def create_app() -> FastAPI:
    application = FastAPI(
        title="GalactiLog",
        version="0.1.0",
        description="Astrophotography FITS file catalog and browser",
        lifespan=lifespan,
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
