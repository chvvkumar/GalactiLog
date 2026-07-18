import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.database import get_session
from app.api.deps import get_current_user
from app.models.user import User, UserRole


def _user(role=UserRole.viewer):
    u = MagicMock(spec=User)
    u.id = uuid.uuid4()
    u.username = "viewer"
    u.role = role
    u.is_active = True
    u.activity_seen_at = None
    return u


def _session_gen(mock_session):
    async def _gen():
        yield mock_session
    return _gen


def test_user_model_has_nullable_activity_seen_at():
    assert "activity_seen_at" in User.__table__.columns
    col = User.__table__.columns["activity_seen_at"]
    assert col.nullable is True
