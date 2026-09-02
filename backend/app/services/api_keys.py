"""Issue, verify and revoke public-API bearer keys.

The raw key is "glg_" + 40 hex characters from secrets.token_hex(20). Only its
sha256 hexdigest is stored, so a leaked database yields no usable credential
and a lost key cannot be recovered, only replaced.
"""
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.api_key import ApiKey
from app.services.auth import hash_token

KEY_PREFIX = "glg_"
PREFIX_LEN = 12

# How stale last_used_at is allowed to get. Writing it on every request would
# turn a read-only API call into a write plus a commit; a minute of resolution
# is all the "when was this key last used" column is read for.
LAST_USED_RESOLUTION = timedelta(seconds=60)


async def verify_api_key(session: AsyncSession, raw: str) -> ApiKey | None:
    """Return the live ApiKey for a raw key, or None if unknown or revoked."""
    result = await session.execute(
        select(ApiKey).where(ApiKey.key_hash == hash_token(raw))
    )
    key = result.scalar_one_or_none()
    if key is None or key.revoked_at is not None:
        return None

    now = datetime.now(timezone.utc)
    if key.last_used_at is None or now - key.last_used_at >= LAST_USED_RESOLUTION:
        key.last_used_at = now
        await session.commit()
        await session.refresh(key)

    return key


async def create_api_key(session: AsyncSession, name: str, can_write: bool) -> tuple[ApiKey, str]:
    """Create a key and return (record, raw key). The raw key is the only copy."""
    raw = KEY_PREFIX + secrets.token_hex(20)
    key = ApiKey(
        name=name,
        key_hash=hash_token(raw),
        prefix=raw[:PREFIX_LEN],
        can_write=can_write,
    )
    session.add(key)
    await session.commit()
    await session.refresh(key)
    return key, raw


async def revoke_api_key(session: AsyncSession, key_id: uuid.UUID) -> bool:
    """Mark a key revoked. False if no such key. Already-revoked keys keep
    their original revoked_at so the audit trail stays honest."""
    key = await session.get(ApiKey, key_id)
    if key is None:
        return False
    if key.revoked_at is None:
        key.revoked_at = datetime.now(timezone.utc)
        await session.commit()
    return True


async def delete_api_key(session: AsyncSession, key_id: uuid.UUID) -> bool:
    """Hard-delete a revoked key's row. False if no such key. Raises
    ValueError if the key is not revoked: revoke-then-delete is the only
    path to permanent removal."""
    key = await session.get(ApiKey, key_id)
    if key is None:
        return False
    if key.revoked_at is None:
        raise ValueError("Revoke the key first")
    await session.delete(key)
    await session.commit()
    return True
