import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from app.services.backup import export_backup, validate_backup, restore_backup, CURRENT_BACKUP_SCHEMA_VERSION, APP_VERSION


@pytest.mark.asyncio
async def test_export_backup_meta():
    """Export produces correct meta with schema_version and app_version."""
    session = AsyncMock()

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_result.scalars.return_value.all.return_value = []
    session.execute = AsyncMock(return_value=mock_result)

    result = await export_backup(session)

    assert result["meta"]["schema_version"] == CURRENT_BACKUP_SCHEMA_VERSION
    assert result["meta"]["app_version"] == APP_VERSION
    assert "exported_at" in result["meta"]


@pytest.mark.asyncio
async def test_export_backup_settings():
    """Export includes settings JSONB fields."""
    session = AsyncMock()

    settings_row = MagicMock()
    settings_row.general = {"auto_scan_enabled": True, "timezone": "UTC"}
    settings_row.filters = {"Ha": {"color": "#ff0000", "aliases": []}}
    settings_row.equipment = {"cameras": {}, "telescopes": {}}
    settings_row.display = {"quality": {"enabled": True}}
    settings_row.graph = {}
    settings_row.dismissed_suggestions = []

    result_settings = MagicMock()
    result_settings.scalar_one_or_none.return_value = settings_row

    result_empty = MagicMock()
    result_empty.scalars.return_value.all.return_value = []

    call_count = 0
    async def mock_execute(stmt, *args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return result_settings
        return result_empty

    session.execute = mock_execute

    result = await export_backup(session)

    assert result["settings"]["general"]["auto_scan_enabled"] is True
    assert "Ha" in result["settings"]["filters"]


@pytest.mark.asyncio
async def test_export_backup_has_all_sections():
    """Export includes all expected top-level sections."""
    session = AsyncMock()

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_result.scalars.return_value.all.return_value = []
    session.execute = AsyncMock(return_value=mock_result)

    result = await export_backup(session)

    expected_sections = [
        "meta", "settings", "session_notes", "custom_columns",
        "target_overrides", "mosaics", "users", "column_visibility",
    ]
    for section in expected_sections:
        assert section in result, f"Missing section: {section}"


def _make_backup(overrides=None):
    """Build a minimal valid backup dict."""
    data = {
        "meta": {
            "schema_version": CURRENT_BACKUP_SCHEMA_VERSION,
            "app_version": APP_VERSION,
            "exported_at": "2026-04-09T00:00:00+00:00",
        },
        "settings": {
            "general": {"auto_scan_enabled": True},
            "filters": {},
            "equipment": {"cameras": {}, "telescopes": {}},
            "display": {},
            "graph": {},
            "dismissed_suggestions": [],
        },
        "session_notes": [],
        "custom_columns": [],
        "target_overrides": [],
        "mosaics": [],
        "users": [],
        "column_visibility": [],
    }
    if overrides:
        data.update(overrides)
    return data


def test_validate_rejects_future_schema():
    """Validation rejects backups from a newer schema version."""
    data = _make_backup()
    data["meta"]["schema_version"] = CURRENT_BACKUP_SCHEMA_VERSION + 1

    result = validate_backup(data, sections=None, mode="merge")
    assert result["valid"] is False
    assert "newer" in result["error"].lower()


def test_validate_rejects_missing_meta():
    """Validation rejects backups without meta."""
    result = validate_backup({}, sections=None, mode="merge")
    assert result["valid"] is False


def test_validate_accepts_valid_backup():
    """Validation accepts a well-formed backup."""
    data = _make_backup()
    result = validate_backup(data, sections=None, mode="merge")
    assert result["valid"] is True
    assert result["error"] is None


def test_validate_preview_counts_notes():
    """Preview counts session notes correctly."""
    data = _make_backup({
        "session_notes": [
            {"target_name": "M31", "session_date": "2026-01-01", "notes": "Good seeing"},
            {"target_name": "M42", "session_date": "2026-01-02", "notes": "Cloudy"},
        ],
    })
    result = validate_backup(data, sections=["session_notes"], mode="merge")
    assert result["valid"] is True
    assert result["preview"]["session_notes"]["add"] == 2


def test_validate_filters_sections():
    """Only selected sections appear in preview."""
    data = _make_backup({
        "session_notes": [
            {"target_name": "M31", "session_date": "2026-01-01", "notes": "test"},
        ],
        "users": [{"username": "viewer1", "role": "viewer"}],
    })
    result = validate_backup(data, sections=["users"], mode="merge")
    assert "session_notes" not in result["preview"]
    assert "users" in result["preview"]


@pytest.mark.asyncio
async def test_restore_session_notes_merge():
    """Restore adds a new session note when merging and no existing match."""
    from datetime import date

    session = AsyncMock()

    target = MagicMock()
    target.id = "tid-1"
    target.primary_name = "M31"

    target_result = MagicMock()
    target_result.scalars.return_value.all.return_value = [target]

    empty_result = MagicMock()
    empty_result.scalar_one_or_none.return_value = None
    empty_result.scalars.return_value.all.return_value = []

    call_idx = 0
    async def mock_execute(stmt, *args, **kwargs):
        nonlocal call_idx
        call_idx += 1
        if call_idx == 1:
            return target_result  # select Target (all targets for lookup)
        return empty_result

    session.execute = mock_execute
    session.add = MagicMock()
    session.flush = AsyncMock()

    data = _make_backup({
        "session_notes": [
            {"target_name": "M31", "session_date": "2026-01-01", "notes": "Great session"},
        ],
    })

    result = await restore_backup(session, data, sections=["session_notes"], mode="merge")
    assert result["success"] is True
    assert result["applied"]["session_notes"]["add"] == 1


def test_migration_chain_rejects_future():
    """apply_migrations raises ValueError for schema > current."""
    from app.services.backup import apply_migrations
    data = {"meta": {"schema_version": 999}}
    with pytest.raises(ValueError, match="newer"):
        apply_migrations(data)


def test_migration_chain_noop_current():
    """apply_migrations is a no-op when data is already at current schema version."""
    from app.services.backup import apply_migrations
    data = _make_backup()
    result = apply_migrations(data)
    assert result["meta"]["schema_version"] == CURRENT_BACKUP_SCHEMA_VERSION
