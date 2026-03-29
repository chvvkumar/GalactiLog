import uuid
from datetime import datetime, timezone

from app.models import Target, Image


def test_target_creation():
    t = Target(
        primary_name="M31",
        aliases=["Andromeda", "NGC 224"],
        ra=10.6847,
        dec=41.2687,
        object_type="Galaxy",
    )
    assert t.primary_name == "M31"
    assert "Andromeda" in t.aliases
    assert t.ra == 10.6847


def test_image_creation():
    img = Image(
        file_path="/data/fits/2024-01-15/Light_M31_300s_001.fits",
        file_name="Light_M31_300s_001.fits",
        capture_date=datetime(2024, 1, 15, 22, 30, 0, tzinfo=timezone.utc),
        exposure_time=300.0,
        filter_used="Ha",
        sensor_temp=-10.0,
        camera_gain=120,
        raw_headers={"OBJECT": "M31", "TELESCOP": "RedCat 51"},
    )
    assert img.file_name == "Light_M31_300s_001.fits"
    assert img.raw_headers["TELESCOP"] == "RedCat 51"
    assert img.exposure_time == 300.0


def test_image_defaults():
    img = Image(file_path="/data/test.fits", file_name="test.fits")
    assert img.resolved_target_id is None
    assert img.thumbnail_path is None


import pytest
from app.models.user_settings import UserSettings, SETTINGS_ROW_ID

def test_user_settings_has_expected_columns():
    """UserSettings model has all expected columns."""
    columns = {c.name for c in UserSettings.__table__.columns}
    assert columns == {"id", "general", "filters", "equipment", "dismissed_suggestions", "updated_at"}

def test_user_settings_fixed_row_id():
    """The fixed single-row ID is a valid UUID."""
    import uuid
    assert isinstance(SETTINGS_ROW_ID, uuid.UUID)

def test_user_settings_defaults():
    """Default JSONB values are populated."""
    s = UserSettings()
    assert s.general == {}
    assert s.filters == {}
    assert s.equipment == {}

def test_user_settings_has_dismissed_suggestions_default():
    from app.models.user_settings import UserSettings, SETTINGS_ROW_ID
    row = UserSettings(id=SETTINGS_ROW_ID)
    assert row.dismissed_suggestions == []
