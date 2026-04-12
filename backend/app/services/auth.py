import hashlib
import json
import logging
import secrets
import uuid
from datetime import datetime, timezone, timedelta

import jwt
from pwdlib import PasswordHash
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.user import User
from app.models.refresh_token import RefreshToken

logger = logging.getLogger("auth.audit")

password_hasher = PasswordHash.recommended()


# ---------------------------------------------------------------------------
# Password helpers
# ---------------------------------------------------------------------------

def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return password_hasher.verify(password, password_hash)


def verify_password_timing_safe(password: str, password_hash: str | None) -> bool:
    """Verify password with constant-time behaviour even for unknown users."""
    if password_hash is None:
        dummy = hash_password("timing-safe-dummy-password")
        password_hasher.verify(password, dummy)
        return False
    return password_hasher.verify(password, password_hash)


# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------

def create_access_token(user_id: uuid.UUID, role: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "role": role,
        "exp": now + timedelta(seconds=settings.access_token_expiry),
        "iat": now,
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_access_token(token: str) -> dict:
    return jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=["HS256"],
        options={"require": ["sub", "role", "exp", "iat", "jti"]},
    )


# ---------------------------------------------------------------------------
# Refresh token helpers
# ---------------------------------------------------------------------------

def generate_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def store_refresh_token(
    session: AsyncSession,
    user_id: uuid.UUID,
    token: str,
    family_id: uuid.UUID | None = None,
    persistent: bool = False,
) -> RefreshToken:
    token_hash = hash_token(token)
    if family_id is None:
        family_id = uuid.uuid4()
    rt = RefreshToken(
        user_id=user_id,
        token_hash=token_hash,
        family_id=family_id,
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=settings.refresh_token_expiry),
        persistent=persistent,
    )
    session.add(rt)
    await session.flush()
    return rt


async def rotate_refresh_token(
    session: AsyncSession,
    old_token: str,
) -> tuple[RefreshToken | None, bool]:
    """Rotate a refresh token. Returns (old_token_row, was_reuse).

    If the old token was already revoked (reuse detected), the entire family
    is revoked and (None, True) is returned.
    """
    old_hash = hash_token(old_token)
    result = await session.execute(
        select(RefreshToken).where(RefreshToken.token_hash == old_hash)
    )
    old_rt = result.scalar_one_or_none()

    if old_rt is None:
        return None, False

    if old_rt.revoked:
        # Theft detected - revoke entire family
        await revoke_family(session, old_rt.family_id)
        return None, True

    if old_rt.expires_at < datetime.now(timezone.utc):
        return None, False

    # Revoke the old token
    old_rt.revoked = True
    await session.flush()

    return old_rt, False


async def revoke_family(session: AsyncSession, family_id: uuid.UUID) -> None:
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == family_id)
        .values(revoked=True)
    )
    await session.flush()


# ---------------------------------------------------------------------------
# User lookups
# ---------------------------------------------------------------------------

async def get_user_by_username(session: AsyncSession, username: str) -> User | None:
    result = await session.execute(
        select(User).where(User.username == username)
    )
    return result.scalar_one_or_none()


async def get_user_by_id(session: AsyncSession, user_id: uuid.UUID) -> User | None:
    result = await session.execute(
        select(User).where(User.id == user_id)
    )
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# Audit logging
# ---------------------------------------------------------------------------

def audit_log(
    event: str,
    *,
    user_id: uuid.UUID | str | None = None,
    username: str | None = None,
    source_ip: str | None = None,
    success: bool = True,
    detail: str | None = None,
) -> None:
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": event,
        "user_id": str(user_id) if user_id else None,
        "username": username,
        "source_ip": source_ip,
        "success": success,
        "detail": detail,
    }
    logger.info(json.dumps(entry))
