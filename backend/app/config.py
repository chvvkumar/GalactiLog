from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://astro:astro@localhost:5432/astro_catalog"
    redis_url: str = "redis://localhost:6379/0"
    fits_data_path: str = "/app/data/fits"
    thumbnails_path: str = "/app/data/thumbnails"
    thumbnail_max_width: int = 800
    jwt_secret: str = ""
    access_token_expiry: int = 1800
    refresh_token_expiry: int = 604800
    secure_cookies: bool = True

    model_config = {"env_prefix": "ASTRO_"}


settings = Settings()

import redis.asyncio as aioredis
import redis as sync_redis

def get_async_redis() -> aioredis.Redis:
    return aioredis.from_url(settings.redis_url, decode_responses=True)

def get_sync_redis() -> sync_redis.Redis:
    return sync_redis.from_url(settings.redis_url, decode_responses=True)

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=settings.redis_url,
)
