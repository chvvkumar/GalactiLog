from app.schemas.settings import (
    GeneralSettings, FilterConfig, EquipmentConfig,
    SettingsResponse, SuggestionGroup, SuggestionsResponse,
)

def test_general_settings_defaults():
    s = GeneralSettings()
    assert s.auto_scan_enabled is True
    assert s.auto_scan_interval == 240
    assert s.thumbnail_width == 800
    assert s.default_page_size == 50

def test_filter_config_structure():
    fc = FilterConfig(color="#e74c3c", aliases=["ha", "H-alpha"])
    assert fc.color == "#e74c3c"
    assert fc.aliases == ["ha", "H-alpha"]

def test_settings_response_round_trip():
    resp = SettingsResponse(
        general=GeneralSettings(),
        filters={"Ha": FilterConfig(color="#e74c3c", aliases=[])},
        equipment=EquipmentConfig(cameras={}, telescopes={}),
    )
    data = resp.model_dump()
    assert data["general"]["auto_scan_enabled"] is True
    assert data["filters"]["Ha"]["color"] == "#e74c3c"

def test_suggestion_group():
    sg = SuggestionGroup(group=["OIII", "Oiii"], counts={"OIII": 100, "Oiii": 20})
    assert len(sg.group) == 2


def test_settings_response_includes_dismissed_suggestions():
    resp = SettingsResponse(
        general=GeneralSettings(),
        filters={},
        equipment=EquipmentConfig(),
        dismissed_suggestions=[["Ha", "ha"]],
    )
    assert resp.dismissed_suggestions == [["Ha", "ha"]]


def test_settings_response_dismissed_suggestions_defaults_empty():
    resp = SettingsResponse(
        general=GeneralSettings(),
        filters={},
        equipment=EquipmentConfig(),
    )
    assert resp.dismissed_suggestions == []
