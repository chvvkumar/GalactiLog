import pytest
from pydantic import ValidationError

from app.schemas.settings import (
    GeneralSettings, FilterConfig, EquipmentConfig,
    Phd2ProfileMapping,
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
    assert s.phd2_profile_map["140APO_AM5N_ASI174MM"].telescope == "140APO"
    assert s.phd2_profile_map["AM5n_OAG_ASI174M"].telescope == "140APO"
    assert len({e.telescope for e in s.phd2_profile_map.values()}) == 2


def test_phd2_settings_survive_a_general_round_trip():
    payload = GeneralSettings(
        observer_timezone="America/New_York",
        phd2_scan_enabled=False,
        phd2_profile_map={"AM5n_OAG_ASI174M": "140APO"},
    ).model_dump()
    restored = GeneralSettings(**payload)
    assert restored.observer_timezone == "America/New_York"
    assert restored.phd2_scan_enabled is False
    assert restored.phd2_profile_map["AM5n_OAG_ASI174M"].telescope == "140APO"


def test_phd2_profile_map_drops_a_value_that_is_no_kind_of_mapping():
    """A stored value that is neither a telescope name nor an entry is dropped,
    not raised on. GeneralSettings is rebuilt from the stored JSON on every
    settings read (api/settings.py `_row_to_response`, tasks_phd2), so a junk
    map value has to degrade rather than take the whole response down. The
    shape owner already makes that call for the raw readers; the schema must
    not contradict it."""
    s = GeneralSettings(phd2_profile_map={
        "AM5n_OAG_ASI174M": ["140APO"],
        "Rig B": "RedCat 51",
    })
    assert "AM5n_OAG_ASI174M" not in s.phd2_profile_map
    assert s.phd2_profile_map["Rig B"].telescope == "RedCat 51"


# --- Per-profile timezone and site -------------------------------------------

def test_phd2_profile_mapping_defaults_are_all_inherit_markers():
    entry = Phd2ProfileMapping()
    assert entry.telescope is None
    assert entry.timezone == ""
    assert entry.latitude is None
    assert entry.longitude is None


def test_a_legacy_string_map_loads_as_entries_and_dumps_as_objects():
    """Every install stored `{"Rig A": "Askar 120"}` before per-rig timezones
    existed. It has to load without a data migration having run, and the next
    save has to write the new shape (update_general stores model_dump())."""
    s = GeneralSettings(phd2_profile_map={"Rig A": "Askar 120"})
    dumped = s.model_dump()["phd2_profile_map"]
    assert dumped == {
        "Rig A": {
            "telescope": "Askar 120",
            "timezone": "",
            "latitude": None,
            "longitude": None,
        }
    }
    assert isinstance(dumped["Rig A"], dict)


def test_a_full_entry_round_trips_through_model_dump():
    s = GeneralSettings(phd2_profile_map={
        "Rig A": {
            "telescope": "Askar 120",
            "timezone": "America/Chicago",
            "latitude": 30.27,
            "longitude": -97.74,
        }
    })
    restored = GeneralSettings(**s.model_dump())
    entry = restored.phd2_profile_map["Rig A"]
    assert entry.telescope == "Askar 120"
    assert entry.timezone == "America/Chicago"
    assert entry.latitude == 30.27
    assert entry.longitude == -97.74


def test_an_entry_carrying_only_a_timezone_survives():
    """Unmapping a rig from a telescope must not discard the zone and site the
    user configured for it, so an entry with no telescope is a real entry."""
    s = GeneralSettings(phd2_profile_map={
        "Rig A": {"timezone": "Europe/Madrid"},
    })
    entry = s.phd2_profile_map["Rig A"]
    assert entry.telescope is None
    assert entry.timezone == "Europe/Madrid"


def test_a_per_profile_zone_typo_is_rejected_like_the_global_one():
    """Same damage, same refusal: a zone name ZoneInfo cannot load silently
    shifts every guide session the profile produced by hours."""
    with pytest.raises(ValidationError) as profile_err:
        GeneralSettings(phd2_profile_map={
            "Rig A": {"timezone": "America/Chicagoo"},
        })
    with pytest.raises(ValidationError) as global_err:
        GeneralSettings(observer_timezone="America/Chicagoo")
    message = "'America/Chicagoo' is not a known IANA time zone"
    assert message in str(profile_err.value)
    assert message in str(global_err.value)


def test_a_real_per_profile_zone_is_accepted():
    s = GeneralSettings(phd2_profile_map={"Rig A": {"timezone": "Asia/Kolkata"}})
    assert s.phd2_profile_map["Rig A"].timezone == "Asia/Kolkata"


def test_per_profile_coordinates_carry_range_bounds():
    """The bounds are the declared contract for a coordinate a client writes,
    and they reach the generated OpenAPI so the settings UI can bound its
    numeric inputs."""
    assert Phd2ProfileMapping(latitude=-90, longitude=-180).latitude == -90
    assert Phd2ProfileMapping(latitude=90, longitude=180).longitude == 180
    for bad in ({"latitude": 90.1}, {"latitude": -91}, {"longitude": 180.5},
                {"longitude": -181}):
        with pytest.raises(ValidationError):
            Phd2ProfileMapping(**bad)


def test_a_stored_out_of_range_coordinate_degrades_instead_of_failing_the_read():
    """The bounds refuse a bad coordinate on the model, but the map's
    normalizer runs first and degrades an unusable stored value to "inherit".
    That ordering is deliberate: GeneralSettings is rebuilt from stored JSON on
    every settings read and on every PHD2 pass, so no stored value may raise
    there."""
    s = GeneralSettings(phd2_profile_map={
        "Rig A": {"telescope": "Askar 120", "latitude": 950, "longitude": 4000},
    })
    entry = s.phd2_profile_map["Rig A"]
    assert entry.latitude is None
    assert entry.longitude is None
    assert entry.telescope == "Askar 120"


def test_zero_is_a_coordinate_and_not_an_inherit_marker():
    """Greenwich stores longitude 0.0 and the equator stores latitude 0.0. A
    falsy test anywhere on this path would move such a rig to the user's own
    site and file its nights under the wrong date."""
    s = GeneralSettings(phd2_profile_map={
        "Rig A": {"latitude": 0.0, "longitude": 0.0},
    })
    entry = s.phd2_profile_map["Rig A"]
    assert entry.latitude == 0.0
    assert entry.longitude == 0.0
    assert GeneralSettings(**s.model_dump()).phd2_profile_map["Rig A"].longitude == 0.0


def test_the_global_observer_coordinates_stay_unbounded():
    """Deliberately asymmetric with the per-profile fields. GeneralSettings is
    constructed from stored JSON in several places, so a bound added here would
    raise on every settings read for an install that already stored a junk
    value, taking the app down to enforce a range nobody can then correct."""
    s = GeneralSettings(observer_latitude=950, observer_longitude=-4000)
    assert s.observer_latitude == 950
    assert s.observer_longitude == -4000


def test_the_profile_map_dumps_plain_dicts_all_the_way_down():
    """update_general persists payload.model_dump() straight into a JSONB
    column, so an entry that dumped as a model would not be serializable."""
    dumped = GeneralSettings(phd2_profile_map={
        "Rig A": {"telescope": "Askar 120", "timezone": "America/Chicago"},
    }).model_dump()["phd2_profile_map"]
    assert all(isinstance(entry, dict) for entry in dumped.values())
    assert set(dumped["Rig A"]) == {"telescope", "timezone", "latitude", "longitude"}


def test_the_wbpp_quality_filter_can_target_guiding_rms():
    """The constraint names a FrameRecord field so the client can index a
    frame directly. Correlation fills that same field, so a PHD2-sourced
    frame is filterable without any change to the constraint model."""
    from app.schemas.settings import WbppRawConstraint

    constraint = WbppRawConstraint(metric="guiding_rms_arcsec", value=0.8)
    assert constraint.metric == "guiding_rms_arcsec"


def test_the_wbpp_metric_names_are_all_frame_record_fields():
    """The comment above WbppRawMetric promises this and nothing enforced it,
    which is how it came to name a frontend constant that no longer exists."""
    import typing

    from app.schemas.settings import WbppRawMetric
    from app.schemas.target import FrameRecord

    for name in typing.get_args(WbppRawMetric):
        assert name in FrameRecord.model_fields, name


def test_an_unknown_stored_metric_fails_the_settings_read_not_just_the_write():
    """test_wbpp_quality_rejects_an_unknown_metric above is a write-time guard.
    This pins the read path, which is the one with the blast radius:
    _row_to_response rebuilds GeneralSettings from the stored JSON on every
    settings fetch, so a constraint naming a metric this backend does not know
    takes the whole response down rather than degrading the WBPP filter.

    The asymmetry with an unknown top-level key is deliberate. Pydantic's
    default extra policy drops a stray key, so a setting a newer client
    invented is simply ignored on an older backend. A stray metric inside the
    typed list cannot be treated the same way: the client indexes a frame by
    that name, so an unrecognised one would evaluate to missing and silently
    skip the frame. A loud read failure was chosen over a wrong export."""
    stored = GeneralSettings(
        wbpp_quality_enabled=True,
        wbpp_quality_mode="raw",
        wbpp_quality_raw_constraints=[{"metric": "guiding_rms_arcsec", "value": 0.8}],
    ).model_dump()

    # A key a newer client invented is ignored, and the constraint a PHD2-derived
    # frame is filtered by survives the same read intact.
    tolerated = GeneralSettings(**{**stored, "wbpp_quality_future_knob": 7})
    assert tolerated.wbpp_quality_raw_constraints[0].metric == "guiding_rms_arcsec"
    assert not hasattr(tolerated, "wbpp_quality_future_knob")

    # An unrecognised metric inside the typed list is not tolerated, and it
    # fails when the row is read back, not only when a client writes it.
    stored["wbpp_quality_raw_constraints"].append({"metric": "snr", "value": 1.0})
    with pytest.raises(ValidationError):
        GeneralSettings(**stored)
