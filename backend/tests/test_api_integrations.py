import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.api.deps import get_current_user
from app.models.user import User, UserRole


def _admin_user():
    u = MagicMock(spec=User)
    u.id = uuid.uuid4()
    u.role = UserRole.admin
    u.is_active = True
    return u


def _auth_override():
    async def override():
        return _admin_user()
    return override


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_nina_requires_auth():
    """Unauthenticated request to NINA endpoint is rejected with 401."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/integrations/nina/send-coordinates",
            json={"url": "http://192.168.1.50:1888", "ra": 10.0, "dec": 20.0},
        )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_stellarium_requires_auth():
    """Unauthenticated request to Stellarium endpoint is rejected with 401."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/integrations/stellarium/send-coordinates",
            json={"url": "http://192.168.1.50:8090", "ra": 10.0, "dec": 20.0},
        )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# SSRF hardening
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_nina_rejects_metadata_ip():
    """Authenticated request to the cloud metadata IP is rejected with 400."""
    app.dependency_overrides[get_current_user] = _auth_override()
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/integrations/nina/send-coordinates",
                json={"url": "http://169.254.169.254/latest/meta-data", "ra": 1.0, "dec": 2.0},
            )
        assert resp.status_code == 400
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_stellarium_rejects_bad_scheme():
    """A non-http(s) scheme is rejected with 400."""
    app.dependency_overrides[get_current_user] = _auth_override()
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/integrations/stellarium/send-coordinates",
                json={"url": "file:///etc/passwd", "ra": 1.0, "dec": 2.0},
            )
        assert resp.status_code == 400
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_nina_accepts_lan_url_when_authenticated():
    """A normal LAN URL is accepted for an authenticated user (httpx mocked)."""
    app.dependency_overrides[get_current_user] = _auth_override()

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    try:
        with patch("app.api.integrations.httpx.AsyncClient", return_value=mock_client):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    "/api/integrations/nina/send-coordinates",
                    json={"url": "http://192.168.1.50:1888", "ra": 10.0, "dec": 20.0},
                )
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}
        mock_client.get.assert_awaited()
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Link-local boundary IPs
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("ip", ["169.254.0.1", "169.254.255.255", "169.254.169.254"])
@pytest.mark.asyncio
async def test_nina_rejects_link_local_boundaries(ip):
    """Both ends of the link-local range (and the metadata IP) are rejected."""
    app.dependency_overrides[get_current_user] = _auth_override()
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/integrations/nina/send-coordinates",
                json={"url": f"http://{ip}:1888", "ra": 1.0, "dec": 2.0},
            )
        assert resp.status_code == 400
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_rejects_ipv6_loopback_literal():
    """An IPv6 loopback literal host is rejected."""
    app.dependency_overrides[get_current_user] = _auth_override()
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/integrations/stellarium/send-coordinates",
                json={"url": "http://[::1]:8090", "ra": 1.0, "dec": 2.0},
            )
        assert resp.status_code == 400
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Allowlist enforcement
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_allowlist_rejects_host_not_in_list(monkeypatch):
    """When GALACTILOG_INTEGRATION_ALLOWED_HOSTS is set, a host outside it is rejected."""
    monkeypatch.setenv("GALACTILOG_INTEGRATION_ALLOWED_HOSTS", "nina.lan,stellarium.lan")
    app.dependency_overrides[get_current_user] = _auth_override()
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/integrations/nina/send-coordinates",
                json={"url": "http://192.168.1.50:1888", "ra": 1.0, "dec": 2.0},
            )
        assert resp.status_code == 400
        assert "allowlist" in resp.json()["detail"].lower()
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_allowlist_accepts_host_in_list(monkeypatch):
    """A host present in the allowlist is accepted (httpx mocked)."""
    monkeypatch.setenv("GALACTILOG_INTEGRATION_ALLOWED_HOSTS", "nina.lan,stellarium.lan")
    app.dependency_overrides[get_current_user] = _auth_override()

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    try:
        with patch("app.api.integrations.httpx.AsyncClient", return_value=mock_client):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    "/api/integrations/nina/send-coordinates",
                    json={"url": "http://nina.lan:1888", "ra": 1.0, "dec": 2.0},
                )
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Hostname resolving to a blocked IP
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rejects_hostname_resolving_to_metadata_ip():
    """A hostname that resolves to the metadata IP is rejected (getaddrinfo mocked)."""
    app.dependency_overrides[get_current_user] = _auth_override()

    def fake_getaddrinfo(host, port, *args, **kwargs):
        return [(2, 1, 6, "", ("169.254.169.254", port or 80))]

    try:
        with patch("app.api.integrations.socket.getaddrinfo", side_effect=fake_getaddrinfo):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    "/api/integrations/nina/send-coordinates",
                    json={"url": "http://evil.example.com:1888", "ra": 1.0, "dec": 2.0},
                )
        assert resp.status_code == 400
        assert "blocked" in resp.json()["detail"].lower()
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_allows_hostname_resolving_to_lan_ip():
    """A hostname resolving to a normal LAN IP is allowed (getaddrinfo + httpx mocked)."""
    app.dependency_overrides[get_current_user] = _auth_override()

    def fake_getaddrinfo(host, port, *args, **kwargs):
        return [(2, 1, 6, "", ("192.168.1.50", port or 80))]

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    try:
        with patch("app.api.integrations.socket.getaddrinfo", side_effect=fake_getaddrinfo), \
                patch("app.api.integrations.httpx.AsyncClient", return_value=mock_client):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    "/api/integrations/nina/send-coordinates",
                    json={"url": "http://nina.lan:1888", "ra": 1.0, "dec": 2.0},
                )
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}
    finally:
        app.dependency_overrides.clear()
