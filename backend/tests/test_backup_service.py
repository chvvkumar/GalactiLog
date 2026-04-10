import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from app.services.backup import export_backup, CURRENT_BACKUP_SCHEMA_VERSION, APP_VERSION


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
