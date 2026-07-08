"""Authorization tests for mosaics write endpoints (SEC-2).

Viewer role must be read-only: state-changing mosaic endpoints require admin.
"""

import uuid

import pytest
from unittest.mock import AsyncMock, MagicMock
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.database import get_session
from app.api.deps import get_current_user


def _override_user(user):
    app.dependency_overrides[get_current_user] = lambda: user


def _override_session(mock_session):
    async def _gen():
        yield mock_session
    app.dependency_overrides[get_session] = _gen


@pytest.mark.asyncio
async def test_create_mosaic_viewer_forbidden(viewer_user):
    _override_user(viewer_user)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/api/mosaics", json={"name": "M31 Mosaic"})
        assert resp.status_code == 403
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_create_mosaic_admin_allowed(admin_user):
    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.flush = AsyncMock()
    mock_session.commit = AsyncMock()

    _override_session(mock_session)
    _override_user(admin_user)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/api/mosaics", json={"name": "M31 Mosaic"})
        assert resp.status_code == 200, resp.text
        assert resp.json()["name"] == "M31 Mosaic"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_delete_mosaic_viewer_forbidden(viewer_user):
    _override_user(viewer_user)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.delete(f"/api/mosaics/{uuid.uuid4()}")
        assert resp.status_code == 403
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_trigger_detection_viewer_forbidden(viewer_user):
    _override_user(viewer_user)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/api/mosaics/detect")
        assert resp.status_code == 403
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_trigger_detection_admin_dispatches_and_returns_202(admin_user, monkeypatch):
    """Detection is dispatched to Celery and the endpoint returns 202 with a
    pollable task id instead of running inline."""
    from app.worker import tasks as tasks_mod

    fake_task = MagicMock()
    fake_task.id = "task-123"
    delay_mock = MagicMock(return_value=fake_task)
    monkeypatch.setattr(tasks_mod.detect_mosaic_panels_task, "delay", delay_mock)

    _override_user(admin_user)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/api/mosaics/detect")
        assert resp.status_code == 202, resp.text
        body = resp.json()
        assert body["status"] == "started"
        assert body["task_id"] == "task-123"
        delay_mock.assert_called_once()
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_detection_status_reports_success_count(admin_user, monkeypatch):
    from app.worker import celery_app as celery_mod

    fake_result = MagicMock()
    fake_result.state = "SUCCESS"
    fake_result.result = {"status": "complete", "new_suggestions": 4}
    monkeypatch.setattr(
        celery_mod.celery_app, "AsyncResult", MagicMock(return_value=fake_result)
    )

    _override_user(admin_user)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/mosaics/detect/status", params={"task_id": "task-123"})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["state"] == "SUCCESS"
        assert body["new_suggestions"] == 4
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_clear_reviews_viewer_forbidden(viewer_user):
    _override_user(viewer_user)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/api/mosaics/clear-reviews")
        assert resp.status_code == 403
    finally:
        app.dependency_overrides.clear()
