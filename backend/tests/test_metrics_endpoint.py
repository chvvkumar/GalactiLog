"""Tests for the GET /api/metrics endpoint token guard.

External access is blocked at the nginx layer (allowlist), which is not
unit-testable here. The optional bearer-token guard is enforced in-app when
GALACTILOG_METRICS_TOKEN is set; these tests cover that behavior.
"""
import pytest

from httpx import AsyncClient, ASGITransport

from app.main import app


@pytest.mark.asyncio
async def test_metrics_no_token_when_env_unset(monkeypatch):
    """When GALACTILOG_METRICS_TOKEN is unset, no Authorization header is required."""
    monkeypatch.delenv("GALACTILOG_METRICS_TOKEN", raising=False)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/metrics")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_metrics_rejects_missing_token_when_env_set(monkeypatch):
    """When the env var is set, a request without the bearer token is rejected."""
    monkeypatch.setenv("GALACTILOG_METRICS_TOKEN", "s3cr3t")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/metrics")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_metrics_rejects_wrong_token_when_env_set(monkeypatch):
    """A mismatched bearer token is rejected."""
    monkeypatch.setenv("GALACTILOG_METRICS_TOKEN", "s3cr3t")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/api/metrics", headers={"Authorization": "Bearer wrong"}
        )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_metrics_rejects_wrong_scheme_when_env_set(monkeypatch):
    """A non-Bearer scheme (e.g. Basic) is rejected even if it carries the token."""
    monkeypatch.setenv("GALACTILOG_METRICS_TOKEN", "s3cr3t")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/api/metrics", headers={"Authorization": "Basic s3cr3t"}
        )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_metrics_rejects_empty_bearer_token_when_env_set(monkeypatch):
    """A bare/empty bearer token is rejected."""
    monkeypatch.setenv("GALACTILOG_METRICS_TOKEN", "s3cr3t")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/api/metrics", headers={"Authorization": "Bearer "}
        )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_metrics_accepts_correct_token_when_env_set(monkeypatch):
    """The correct bearer token is accepted and metrics are served."""
    monkeypatch.setenv("GALACTILOG_METRICS_TOKEN", "s3cr3t")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/api/metrics", headers={"Authorization": "Bearer s3cr3t"}
        )
    assert resp.status_code == 200
