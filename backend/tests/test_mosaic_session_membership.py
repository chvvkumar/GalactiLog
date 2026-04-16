import uuid
from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.database import get_session
from app.api.auth import get_current_user
from app.models import User, UserRole
from app.services.mosaic_detection import cluster_sessions_by_gap


def _make_admin():
    user = MagicMock(spec=User)
    user.id = uuid.uuid4()
    user.username = "admin"
    user.role = UserRole.admin
    return user


def test_cluster_no_span_check():
    """Dates spread over months but consecutive gaps under gap_days form one cluster."""
    dates = [
        "2023-10-01", "2023-10-15", "2023-10-29",
        "2023-11-12", "2023-11-26", "2023-12-10",
    ]
    clusters = cluster_sessions_by_gap(dates, 30)
    assert len(clusters) == 1
    assert len(clusters[0]) == 6


def test_cluster_splits_on_gap():
    """Split when consecutive gap exceeds threshold."""
    dates = [
        "2023-10-01", "2023-10-15",
        "2024-03-01", "2024-03-15",
    ]
    clusters = cluster_sessions_by_gap(dates, 60)
    assert len(clusters) == 2
    assert clusters[0] == ["2023-10-01", "2023-10-15"]
    assert clusters[1] == ["2024-03-01", "2024-03-15"]


def test_cluster_deduplicates_dates():
    """Duplicate dates are handled."""
    dates = ["2023-10-01", "2023-10-01", "2023-10-15"]
    clusters = cluster_sessions_by_gap(dates, 30)
    assert len(clusters) == 1
    assert len(clusters[0]) == 2


def test_cluster_empty():
    clusters = cluster_sessions_by_gap([], 30)
    assert clusters == []


def test_cluster_single_date():
    clusters = cluster_sessions_by_gap(["2023-10-01"], 30)
    assert len(clusters) == 1
    assert clusters[0] == ["2023-10-01"]


def test_cluster_multi_year_no_split():
    """Multi-year campaign with small gaps should not split."""
    dates = [
        "2023-10-01", "2023-10-20",
        "2023-11-08", "2023-11-27",
        "2023-12-16", "2024-01-04",
    ]
    clusters = cluster_sessions_by_gap(dates, 30)
    assert len(clusters) == 1


@pytest.mark.asyncio
async def test_get_panel_sessions_404():
    admin = _make_admin()
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute = AsyncMock(return_value=mock_result)

    app.dependency_overrides[get_session] = lambda: mock_session
    app.dependency_overrides[get_current_user] = lambda: admin
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(
                f"/api/mosaics/{uuid.uuid4()}/panels/{uuid.uuid4()}/sessions"
            )
        assert resp.status_code == 404
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_update_panel_sessions_404():
    admin = _make_admin()
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute = AsyncMock(return_value=mock_result)

    app.dependency_overrides[get_session] = lambda: mock_session
    app.dependency_overrides[get_current_user] = lambda: admin
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.put(
                f"/api/mosaics/{uuid.uuid4()}/panels/{uuid.uuid4()}/sessions",
                json={"include": ["2023-10-01"], "exclude": []},
            )
        assert resp.status_code == 404
    finally:
        app.dependency_overrides.clear()
