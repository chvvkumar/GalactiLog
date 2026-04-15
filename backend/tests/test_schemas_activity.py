import pytest
from datetime import datetime, timezone


def test_activity_item_fields():
    from app.schemas.activity import ActivityItem
    fields = set(ActivityItem.model_fields.keys())
    assert fields == {"id", "timestamp", "severity", "category", "event_type",
                      "message", "details", "target_id", "actor", "duration_ms"}


def test_activity_item_serializes():
    from app.schemas.activity import ActivityItem
    item = ActivityItem(
        id=1,
        timestamp=datetime(2026, 4, 15, 12, 0, 0, tzinfo=timezone.utc),
        severity="info", category="scan", event_type="scan_complete",
        message="done", details=None, target_id=None, actor="system", duration_ms=None,
    )
    assert item.model_dump()["severity"] == "info"


def test_paginated_response():
    from app.schemas.activity import PaginatedActivityResponse, ActivityItem
    resp = PaginatedActivityResponse(
        items=[ActivityItem(
            id=1, timestamp=datetime(2026, 4, 15, 12, 0, 0, tzinfo=timezone.utc),
            severity="info", category="scan", event_type="scan_complete",
            message="done", details=None, target_id=None, actor=None, duration_ms=None,
        )],
        next_cursor=None,
        total=1,
    )
    assert resp.total == 1


def test_filter_params_defaults():
    from app.schemas.activity import ActivityFilterParams
    p = ActivityFilterParams()
    assert p.limit == 50
    assert p.severity == []
    assert p.category == []
    assert p.cursor is None
    assert p.since is None


def test_filter_params_limit_cap():
    from app.schemas.activity import ActivityFilterParams
    p = ActivityFilterParams(limit=999)
    assert p.limit == 200
