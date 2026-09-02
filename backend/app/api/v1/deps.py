"""Bearer-key auth and per-key rate limiting for /api/v1.

``require_read_key`` is attached to the v1 APIRouter itself
(``dependencies=[Depends(require_read_key)]``), so every route under /api/v1
is key-authed by construction. A route added later cannot ship
unauthenticated by forgetting a decorator; there are no per-route read
checks. Write routes add ``Depends(require_write_key)`` on top, which resolves
through the same dependency (FastAPI caches it per request, so the key is
verified and the rate limit counted exactly once).
"""

import logging

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import async_redis, client_ip_from_request
from app.database import get_session
from app.models.api_key import ApiKey
from app.services.api_keys import verify_api_key

logger = logging.getLogger(__name__)

_BEARER_CHALLENGE = {"WWW-Authenticate": "Bearer"}

RATE_LIMIT = 120  # requests per key per window
BAD_KEY_LIMIT = 30  # rejected keys per client address per window
RATE_WINDOW = 60  # seconds


def _bucket(name: str) -> str:
    return f"galactilog:v1:ratelimit:{name}"


async def _count_hit(name: str, limit: int) -> bool:
    """Count one hit against a fixed window; True once the budget is spent.

    ponytail: fixed window counted in Redis rather than the app's slowapi
    limiter. slowapi only exposes a per-route decorator keyed on the client
    IP, and pasting one onto every v1 route is exactly the per-handler
    pattern this dependency exists to avoid. Swap in a sliding window if
    burst-at-the-window-boundary ever matters.

    SET NX EX seeds the counter together with its TTL, so a crash between
    creating the key and expiring it cannot leave a TTL-less counter that
    locks the bucket out forever. Redis being unavailable does not fail the
    request: the API stays up unthrottled rather than going dark.
    """
    try:
        async with async_redis() as r:
            key = _bucket(name)
            await r.set(key, 0, ex=RATE_WINDOW, nx=True)
            return await r.incr(key) > limit
    except Exception:
        logger.debug("v1 rate-limit check skipped: Redis unavailable")
        return False


async def _is_spent(name: str, limit: int) -> bool:
    """Read a window without counting against it."""
    try:
        async with async_redis() as r:
            current = await r.get(_bucket(name))
    except Exception:
        logger.debug("v1 rate-limit peek skipped: Redis unavailable")
        return False
    return current is not None and int(current) > limit


async def require_read_key(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> ApiKey:
    """Resolve the Authorization: Bearer key, or 401."""
    scheme, _, raw = (request.headers.get("authorization") or "").partition(" ")
    raw = raw.strip()
    if scheme.lower() != "bearer" or not raw:
        raise HTTPException(
            status_code=401,
            detail="Missing bearer token",
            headers=_BEARER_CHALLENGE,
        )

    # A bogus token costs an api_keys SELECT, and until a key is resolved
    # there is nothing to charge that lookup to but the caller's address.
    # The budget is peeked BEFORE the lookup so that once an address has
    # burned it, further guesses are refused without touching the database,
    # and charged only on a miss so legitimate traffic never pays into it.
    ip = client_ip_from_request(request)
    if await _is_spent(f"badkey:{ip}", BAD_KEY_LIMIT):
        raise HTTPException(
            status_code=429,
            detail="Too many invalid API keys",
            headers=_BEARER_CHALLENGE,
        )

    key = await verify_api_key(session, raw)
    if key is None:
        await _count_hit(f"badkey:{ip}", BAD_KEY_LIMIT)
        raise HTTPException(
            status_code=401,
            detail="Invalid API key",
            headers=_BEARER_CHALLENGE,
        )

    if await _count_hit(str(key.id), RATE_LIMIT):
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

    request.state.api_key = key
    return key


async def require_write_key(key: ApiKey = Depends(require_read_key)) -> ApiKey:
    if not key.can_write:
        raise HTTPException(status_code=403, detail="Write access required")
    return key
