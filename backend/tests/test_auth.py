import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.database import get_session
from app.api.deps import get_current_user, require_admin
from app.models.user import User
from app.services.auth import (
    hash_password, verify_password, create_access_token,
    decode_access_token, hash_token, generate_refresh_token,
)


class TestPasswordHashing:
    def test_hash_and_verify(self):
        hashed = hash_password("secure-password-123")
        assert verify_password("secure-password-123", hashed) is True

    def test_wrong_password(self):
        hashed = hash_password("correct-password")
        assert verify_password("wrong-password", hashed) is False

    def test_hash_not_plaintext(self):
        hashed = hash_password("my-secret")
        assert hashed != "my-secret"


class TestJWT:
    def test_create_and_decode(self):
        uid = uuid.uuid4()
        token = create_access_token(uid, "admin")
        payload = decode_access_token(token)
        assert payload["sub"] == str(uid)
        assert payload["role"] == "admin"
        assert all(k in payload for k in ["exp", "iat", "jti"])

    def test_tampered_token(self):
        token = create_access_token(uuid.uuid4(), "admin")
        with pytest.raises(Exception):
            decode_access_token(token[:-5] + "XXXXX")

    def test_expired_token(self):
        import jwt as pyjwt
        from datetime import datetime, timedelta, timezone
        from app.config import settings
        payload = {
            "sub": str(uuid.uuid4()), "role": "admin",
            "iat": datetime.now(timezone.utc) - timedelta(hours=2),
            "exp": datetime.now(timezone.utc) - timedelta(hours=1),
            "jti": str(uuid.uuid4()),
        }
        token = pyjwt.encode(payload, settings.jwt_secret, algorithm="HS256")
        with pytest.raises(pyjwt.ExpiredSignatureError):
            decode_access_token(token)


class TestTokenUtils:
    def test_hash_deterministic(self):
        assert hash_token("token") == hash_token("token")

    def test_different_tokens_different_hashes(self):
        assert hash_token("a") != hash_token("b")

    def test_generate_random(self):
        assert generate_refresh_token() != generate_refresh_token()


@pytest.mark.asyncio
async def test_health_no_auth():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_me_unauthenticated():
    app.dependency_overrides.clear()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/auth/me")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_me_authenticated(admin_user):
    async def override_user():
        return admin_user
    app.dependency_overrides[get_current_user] = override_user
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/auth/me")
    assert resp.status_code == 200
    assert resp.json()["username"] == "admin"
    assert resp.json()["role"] == "admin"
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_viewer_blocked_on_scan(viewer_user):
    async def override_user():
        return viewer_user
    app.dependency_overrides[get_current_user] = override_user
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/scan")
    assert resp.status_code == 403
    app.dependency_overrides.clear()


class TestLockoutIdentity:
    def test_identity_includes_username_and_ip(self):
        from app.api.auth import _lockout_id
        assert _lockout_id("alice", "203.0.113.7") == "alice|203.0.113.7"

    def test_different_ip_yields_different_identity(self):
        from app.api.auth import _lockout_id
        a = _lockout_id("alice", "203.0.113.7")
        b = _lockout_id("alice", "198.51.100.4")
        assert a != b

    @pytest.mark.asyncio
    async def test_increment_locks_out_after_threshold(self):
        from app.api.auth import _increment_login_failures, MAX_LOGIN_FAILURES, _lockout_id
        redis = MagicMock()
        pipe = MagicMock()
        pipe.incr = MagicMock()
        pipe.expire = MagicMock()
        pipe.execute = AsyncMock(return_value=[MAX_LOGIN_FAILURES])
        redis.pipeline = MagicMock(return_value=pipe)
        redis.setex = AsyncMock()

        await _increment_login_failures(redis, "alice", "203.0.113.7")

        identity = _lockout_id("alice", "203.0.113.7")
        redis.setex.assert_awaited_once()
        args = redis.setex.await_args.args
        assert args[0] == f"auth:lockout:{identity}"

    @pytest.mark.asyncio
    async def test_increment_no_lockout_below_threshold(self):
        from app.api.auth import _increment_login_failures
        redis = MagicMock()
        pipe = MagicMock()
        pipe.incr = MagicMock()
        pipe.expire = MagicMock()
        pipe.execute = AsyncMock(return_value=[1])
        redis.pipeline = MagicMock(return_value=pipe)
        redis.setex = AsyncMock()

        await _increment_login_failures(redis, "alice", "203.0.113.7")

        redis.setex.assert_not_awaited()


class TestPasswordPolicy:
    def test_short_password_rejected(self):
        from app.schemas.auth import PasswordChangeRequest
        with pytest.raises(Exception):
            PasswordChangeRequest(current_password="old", new_password="short")

    def test_valid_password(self):
        from app.schemas.auth import PasswordChangeRequest
        req = PasswordChangeRequest(current_password="old", new_password="valid-password-123")
        assert req.new_password == "valid-password-123"
