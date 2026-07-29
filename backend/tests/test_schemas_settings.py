import pytest
from pydantic import ValidationError

from app.schemas.settings import (
    GeneralSettings, FilterConfig, EquipmentConfig,
    SettingsResponse, SuggestionGroup, SuggestionsResponse,
    WbppRawConstraint,
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


# --- WBPP quality filter persistence -----------------------------------------

def test_wbpp_quality_defaults_match_the_modals_own_starting_state():
    # A user who has never touched the filter must read back exactly the state
    # the modal used to reset to on every open, or persistence changes behaviour
    # rather than just remembering it.
    s = GeneralSettings()
    assert s.wbpp_quality_enabled is False
    assert s.wbpp_quality_mode == "score"
    assert s.wbpp_quality_score_threshold == 60
    assert s.wbpp_quality_baseline == "session"
    assert s.wbpp_quality_raw_constraints == []


def test_wbpp_quality_round_trips_a_full_config():
    s = GeneralSettings(
        wbpp_quality_enabled=True,
        wbpp_quality_mode="raw",
        wbpp_quality_score_threshold=75,
        wbpp_quality_baseline="rig",
        wbpp_quality_raw_constraints=[{"metric": "eccentricity", "value": 0.6}],
    )
    data = s.model_dump()
    assert data["wbpp_quality_mode"] == "raw"
    assert data["wbpp_quality_baseline"] == "rig"
    assert data["wbpp_quality_raw_constraints"] == [{"metric": "eccentricity", "value": 0.6}]
    # Re-parsing a dumped dict is what _row_to_response does with the stored JSON.
    assert GeneralSettings(**data).wbpp_quality_raw_constraints[0].value == 0.6


def test_wbpp_quality_rejects_an_unknown_metric():
    # The metric names are FrameRecord fields the client indexes directly; a
    # typo stored here would silently evaluate to "missing" and skip the frame.
    with pytest.raises(ValidationError):
        GeneralSettings(wbpp_quality_raw_constraints=[{"metric": "snr", "value": 1.0}])


@pytest.mark.parametrize("field,value", [
    ("wbpp_quality_mode", "composite"),
    ("wbpp_quality_baseline", "catalog"),
    ("wbpp_quality_score_threshold", 101),
    ("wbpp_quality_score_threshold", -1),
])
def test_wbpp_quality_rejects_out_of_domain_values(field, value):
    with pytest.raises(ValidationError):
        GeneralSettings(**{field: value})


def test_wbpp_raw_constraint_stores_no_direction():
    # Direction belongs to the metric (only detected_stars is higher-is-better)
    # and is derived on the client. Storing it would let it contradict.
    assert set(WbppRawConstraint(metric="eccentricity", value=0.6).model_dump()) == {
        "metric", "value",
    }


# --- PHD2 guide-log settings --------------------------------------------------

def test_phd2_settings_defaults():
    s = GeneralSettings()
    assert s.observer_timezone == ""
    assert s.phd2_scan_enabled is True
    assert s.phd2_profile_map == {}


def test_phd2_profile_map_accepts_many_names_for_one_telescope():
    s = GeneralSettings(phd2_profile_map={
        "140APO_AM5N_ASI174MM": "140APO",
        "AM5n_OAG_ASI174M": "140APO",
        "ASI220mm_30F5_AM5": "RedCat 51",
    })
    assert s.phd2_profile_map["140APO_AM5N_ASI174MM"] == "140APO"
    assert s.phd2_profile_map["AM5n_OAG_ASI174M"] == "140APO"
    assert len(set(s.phd2_profile_map.values())) == 2


def test_phd2_settings_survive_a_general_round_trip():
    payload = GeneralSettings(
        observer_timezone="America/New_York",
        phd2_scan_enabled=False,
        phd2_profile_map={"AM5n_OAG_ASI174M": "140APO"},
    ).model_dump()
    restored = GeneralSettings(**payload)
    assert restored.observer_timezone == "America/New_York"
    assert restored.phd2_scan_enabled is False
    assert restored.phd2_profile_map == {"AM5n_OAG_ASI174M": "140APO"}


def test_phd2_profile_map_rejects_non_string_values():
    with pytest.raises(ValidationError):
        GeneralSettings(phd2_profile_map={"AM5n_OAG_ASI174M": ["140APO"]})
