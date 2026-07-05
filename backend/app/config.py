import logging
import os
import secrets
import tempfile
import threading

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
MIN_UPGRADE_FROM_ALEMBIC_REVISION = "0015"
MIN_UPGRADE_FROM_DATA_VERSION = 13
CHECKPOINT_IMAGE_TAG = "chvvkumar/galactilog:v2.0"


def load_or_create_jwt_secret(secret_file: str) -> str:
    """Load a persisted JWT secret from ``secret_file`` or create one.

    The generated secret is written to a stable file so it survives process
    restarts and is shared across multiple workers. The write is atomic:
    the secret is first written completely to a temporary file (mode 0600)
    in the same directory, which is then published under the final name via
    os.link, an atomic create-if-absent. A process that loses the creation
    race therefore can only ever observe the winner's fully written file,
    never a partial one, and reads the winner's secret back so all
    processes end up sharing the same secret. On filesystems without hard
    link support the publish falls back to os.replace, which is equally
    atomic but last-writer-wins rather than first-writer-wins.
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

    tmp_path = None
    try:
        # Write the full secret to a temp file in the target directory first
        # (mkstemp creates it 0600), then publish it under the final name.
        fd, tmp_path = tempfile.mkstemp(dir=parent or ".", prefix=".jwt_secret.tmp.")
        try:
            os.write(fd, secret.encode("utf-8"))
        finally:
            os.close(fd)
        try:
            # os.link is an atomic create-if-absent: it fails if the target
            # already exists and, because the temp file is complete before
            # the link, a racing loser can never see a partially written
            # secret under the final name.
            os.link(tmp_path, secret_file)
            return secret
        except FileExistsError:
            # Another worker published first; its file is complete by
            # construction, so a single read-back suffices.
            try:
                with open(secret_file, "r", encoding="utf-8") as fh:
                    persisted = fh.read().strip()
                if persisted:
                    return persisted
            except OSError as exc:
                logger.warning("Could not read JWT secret file %s after race: %s", secret_file, exc)
            return secret
        except OSError:
            # Filesystem without hard link support: fall back to os.replace,
            # which is still atomic (readers never see a partial file) but
            # last-writer-wins instead of first-writer-wins.
            os.replace(tmp_path, secret_file)
            tmp_path = None
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
    finally:
        if tmp_path is not None:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def jwt_secret_persisted(secret_file: str, secret: str) -> bool:
    """Best-effort check that ``secret`` actually made it to ``secret_file``.

    load_or_create_jwt_secret() falls back to an in-memory-only secret when it
    can't read or write the file (e.g. wrong ownership, read-only filesystem).
    Callers use this to avoid logging that sessions survive restarts when
    they in fact won't.
    """
    try:
        with open(secret_file, "r", encoding="utf-8") as fh:
            return fh.read().strip() == secret
    except OSError:
        return False


_jwt_secret_lock = threading.Lock()


def get_jwt_secret() -> str:
    """Return the configured JWT secret, generating/loading it on first use.

    This is deliberately lazy rather than run as a side effect of importing
    this module. The entrypoint script imports app.config from several
    root-context helper snippets (to read settings.database_url, version
    constants, etc.) before privileges drop to the unprivileged app user. If
    secret generation ran at import time, whichever of those root snippets
    happened to import this module first would create the persisted secret
    file as root, and the app user would never be able to read it back -
    causing a fresh secret (and fresh sessions) on every restart. Deferring
    generation until a token is actually created/decoded ensures the file is
    created by the process that needs it, running as the app user.
    """
    if settings.jwt_secret:
        return settings.jwt_secret
    with _jwt_secret_lock:
        if not settings.jwt_secret:
            settings.jwt_secret = load_or_create_jwt_secret(settings.jwt_secret_file)
    return settings.jwt_secret

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
