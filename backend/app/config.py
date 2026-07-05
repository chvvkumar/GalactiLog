import logging
import os
import secrets

from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://galactilog:galactilog@localhost:5432/galactilog_catalog"
    redis_url: str = "redis://localhost:6379/0"
    fits_data_path: str = "/app/data/fits"
    thumbnails_path: str = "/app/data/thumbnails"
    previews_path: str = "/app/data/thumbnails/previews"
    thumbnail_max_width: int = 800
    jwt_secret: str = ""
    # Path to persist an auto-generated JWT secret when GALACTILOG_JWT_SECRET is
    # unset. Default lives under the FITS/thumbnail data volume so it survives
    # restarts and is shared by all workers.
    jwt_secret_file: str = "/app/data/.jwt_secret"
    access_token_expiry: int = 1800
    refresh_token_expiry: int = 604800
    https: bool = True
    admin_username: str = "admin"
    admin_password: str = ""
    viewer_username: str = ""
    viewer_password: str = ""

    model_config = {"env_prefix": "GALACTILOG_"}


settings = Settings()

# Upgrade gate: oldest install state this release can upgrade from.
# Installs older than this must first run the checkpoint image below.
# Bump these when migration history is squashed at a checkpoint release.
MIN_UPGRADE_FROM_ALEMBIC_REVISION = "0001"
MIN_UPGRADE_FROM_DATA_VERSION = 1
CHECKPOINT_IMAGE_TAG = "chvvkumar/galactilog:v2.0"


def load_or_create_jwt_secret(secret_file: str) -> str:
    """Load a persisted JWT secret from ``secret_file`` or create one.

    The generated secret is written to a stable file so it survives process
    restarts and is shared across multiple workers. The write tolerates
    concurrent workers racing to create the file: if another worker wins the
    race, the secret it persisted is read back and returned.
    """
    # Fast path: file already exists.
    try:
        with open(secret_file, "r", encoding="utf-8") as fh:
            existing = fh.read().strip()
        if existing:
            return existing
    except FileNotFoundError:
        pass
    except OSError as exc:
        logger.warning("Could not read JWT secret file %s: %s", secret_file, exc)

    secret = secrets.token_hex(32)
    parent = os.path.dirname(secret_file)
    if parent:
        try:
            os.makedirs(parent, exist_ok=True)
        except OSError as exc:
            logger.warning("Could not create directory for JWT secret file %s: %s", parent, exc)

    try:
        # O_EXCL ensures only the first worker writes; others race-lose here.
        fd = os.open(secret_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(fd, secret.encode("utf-8"))
        finally:
            os.close(fd)
        return secret
    except FileExistsError:
        # Another worker created it first; read back its secret.
        try:
            with open(secret_file, "r", encoding="utf-8") as fh:
                persisted = fh.read().strip()
            if persisted:
                return persisted
        except OSError as exc:
            logger.warning("Could not read JWT secret file %s after race: %s", secret_file, exc)
        return secret
    except OSError as exc:
        # Could not persist (read-only FS etc.); fall back to in-memory secret.
        logger.warning(
            "Could not persist JWT secret to %s: %s. Using an in-memory secret; "
            "sessions will not survive restarts.",
            secret_file,
            exc,
        )
        return secret


# Auto-generate JWT secret if not set. The secret is persisted to a stable file
# (settings.jwt_secret_file) so it survives restarts and is shared by all
# workers. Operators should still set GALACTILOG_JWT_SECRET explicitly for
# production/multi-host deployments (see the startup warning in main.py).
if not settings.jwt_secret:
    settings.jwt_secret = load_or_create_jwt_secret(settings.jwt_secret_file)

import redis.asyncio as aioredis
import redis as sync_redis
from contextlib import asynccontextmanager


import asyncio

# Single async Redis client shared across all requests. redis-py manages an
# internal connection pool, so building a fresh client (and TCP connection) per
# call is pure overhead on hot paths. The client is created lazily and reused.
#
# The client's connection pool is bound to the event loop it was created on, so
# it is keyed by that loop: in production there is one long-lived loop and thus
# one client for the process lifetime; under pytest each test runs on its own
# loop, so a new client is created per loop (the previous one is discarded),
# which preserves test isolation without a fixture reset.
_shared_async_redis: "aioredis.Redis | None" = None
_shared_async_redis_loop = None


def get_async_redis() -> aioredis.Redis:
    """Return the shared async Redis client for the current event loop."""
    global _shared_async_redis, _shared_async_redis_loop
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if _shared_async_redis is None or _shared_async_redis_loop is not loop:
        _shared_async_redis = aioredis.from_url(settings.redis_url, decode_responses=True)
        _shared_async_redis_loop = loop
    return _shared_async_redis


@asynccontextmanager
async def async_redis():
    """Yield the shared async Redis client.

    Kept as a context manager for call-site compatibility, but it no longer
    opens or closes a connection per use: it hands out the process-wide shared
    client and leaves it open (closing would tear down the pool other callers
    depend on). The pool self-manages connections.
    """
    yield get_async_redis()


def get_sync_redis() -> sync_redis.Redis:
    return sync_redis.from_url(settings.redis_url, decode_responses=True)

from slowapi import Limiter


def client_ip_from_request(request) -> str:
    """Derive the real client IP from the X-Forwarded-For header.

    Security assumption: nginx is the sole entry point and the backend is bound
    to localhost, so X-Forwarded-For can only have been set by our own trusted
    proxy (clients cannot reach the app directly to spoof it). nginx sets the
    header via ``$proxy_add_x_forwarded_for``, which appends the connecting peer
    to any pre-existing value, producing the order
    ``original-client, proxy1, proxy2, ...``; hence the left-most non-empty
    entry is the originating client. Falls back to the direct socket peer
    (request.client.host) when no header is present (e.g. local dev without
    nginx).
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        for part in forwarded.split(","):
            ip = part.strip()
            if ip:
                return ip
    return request.client.host if request.client else "unknown"


limiter = Limiter(
    key_func=client_ip_from_request,
    storage_uri=settings.redis_url,
)
