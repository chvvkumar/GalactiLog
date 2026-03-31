import secrets

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://galactilog:galactilog@localhost:5432/galactilog_catalog"
    redis_url: str = "redis://localhost:6379/0"
    fits_data_path: str = "/app/data/fits"
    thumbnails_path: str = "/app/data/thumbnails"
    thumbnail_max_width: int = 800
    jwt_secret: str = ""
    access_token_expiry: int = 1800
    refresh_token_expiry: int = 604800
    https: bool = True
    admin_username: str = "admin"
    admin_password: str = ""
    viewer_username: str = ""
    viewer_password: str = ""

    model_config = {"env_prefix": "GALACTILOG_"}


settings = Settings()

# Auto-generate JWT secret if not set -- stable for the lifetime of the process,
# but tokens won't survive a restart. Fine for getting started; set GALACTILOG_JWT_SECRET
# in .env for persistence across restarts.
if not settings.jwt_secret:
    settings.jwt_secret = secrets.token_hex(32)

import redis.asyncio as aioredis
import redis as sync_redis
from contextlib import asynccontextmanager


def get_async_redis() -> aioredis.Redis:
    return aioredis.from_url(settings.redis_url, decode_responses=True)


@asynccontextmanager
async def async_redis():
    """Async context manager that auto-closes the Redis connection."""
    r = get_async_redis()
    try:
        yield r
    finally:
        await r.aclose()


def get_sync_redis() -> sync_redis.Redis:
    return sync_redis.from_url(settings.redis_url, decode_responses=True)

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=settings.redis_url,
)
