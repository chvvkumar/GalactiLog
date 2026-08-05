"""Tests for the PHD2 profile-mapping shape owner.

The headline invariant, asserted from several directions below: the inherit
marker for `latitude` and `longitude` is `None`, never `0`. Zero is a legal
longitude (Greenwich) and a legal latitude (the equator), so any falsy test
against a stored coordinate is a defect.
"""
import math

import pytest
from pydantic import BaseModel

from app.services.phd2_profiles import (
    longitude_resolver,
    normalize_profile_map,
    profile_has_own_latitude,
    profile_has_own_longitude,
    profile_site,
    profile_timezone,
    profile_zone_resolver,
    rewrite_telescopes,
    set_telescope,
    telescope_map,
)


CANONICAL_KEYS = {"telescope", "timezone", "latitude", "longitude"}


class _ProfileModel(BaseModel):
    """Stand-in for the pydantic per-profile model T3 adds to the schema."""

    telescope: str | None = None
    timezone: str = ""
    latitude: float | None = None
    longitude: float | None = None


# --------------------------------------------------------------------------
# normalize_profile_map: legacy coercion and shape
# --------------------------------------------------------------------------


def test_legacy_string_map_becomes_canonical_entries():
    out = normalize_profile_map({"AM5n_OAG": "140APO"})
    assert set(out) == {"AM5n_OAG"}
    assert set(out["AM5n_OAG"]) == CANONICAL_KEYS
    assert out["AM5n_OAG"]["telescope"] == "140APO"
    assert out["AM5n_OAG"]["timezone"] == ""
    assert out["AM5n_OAG"]["latitude"] is None
    assert out["AM5n_OAG"]["longitude"] is None


def test_canonical_map_survives_unchanged():
    raw = {
        "Rig A": {
            "telescope": "Askar 120",
            "timezone": "America/Chicago",
            "latitude": 30.27,
            "longitude": -97.74,
        }
    }
    assert normalize_profile_map(raw) == raw


def test_normalize_is_idempotent():
    once = normalize_profile_map({"Rig A": "Askar 120", "Rig B": {"timezone": "UTC"}})
    assert normalize_profile_map(once) == once


def test_normalize_does_not_mutate_its_input():
    raw = {"Rig A": {"telescope": "Askar 120"}}
    normalize_profile_map(raw)
    assert raw == {"Rig A": {"telescope": "Askar 120"}}


def test_partial_entry_gains_the_missing_keys():
    out = normalize_profile_map({"Rig A": {"timezone": "Europe/Madrid"}})
    assert out["Rig A"] == {
        "telescope": None,
        "timezone": "Europe/Madrid",
        "latitude": None,
        "longitude": None,
    }


def test_empty_telescope_string_means_not_mapped():
    # Today's UI deletes the key when the telescope select is cleared, so an
    # empty value has always meant "not mapped". Under the new shape the entry
    # must survive to carry the timezone, so the emptiness moves onto the field.
    out = normalize_profile_map({"Rig A": "", "Rig B": {"telescope": "   "}})
    assert out["Rig A"]["telescope"] is None
    assert out["Rig B"]["telescope"] is None


def test_surrounding_whitespace_is_stripped():
    out = normalize_profile_map({"Rig A": {"telescope": " 140APO ", "timezone": " UTC "}})
    assert out["Rig A"]["telescope"] == "140APO"
    assert out["Rig A"]["timezone"] == "UTC"


def test_junk_values_drop_the_entry():
    out = normalize_profile_map(
        {"good": "140APO", "listy": ["140APO"], "numeric": 7, "nothing": None}
    )
    assert set(out) == {"good"}


def test_junk_raw_yields_an_empty_map():
    for raw in (None, [], "140APO", 7, object()):
        assert normalize_profile_map(raw) == {}


def test_non_string_keys_are_dropped():
    out = normalize_profile_map({"Rig A": "140APO", 7: "RedCat 51", None: "RedCat 51"})
    assert set(out) == {"Rig A"}


def test_pydantic_model_values_are_accepted():
    out = normalize_profile_map(
        {"Rig A": _ProfileModel(telescope="Askar 120", timezone="America/Chicago", longitude=0.0)}
    )
    assert out["Rig A"]["telescope"] == "Askar 120"
    assert out["Rig A"]["timezone"] == "America/Chicago"
    assert out["Rig A"]["longitude"] == 0.0


def test_unicode_profile_names_are_preserved():
    out = normalize_profile_map({"Telescopio Ñandú – OAG": "140APO", "望遠鏡": "RedCat 51"})
    assert out["Telescopio Ñandú – OAG"]["telescope"] == "140APO"
    assert out["望遠鏡"]["telescope"] == "RedCat 51"


def test_non_string_timezone_becomes_empty():
    out = normalize_profile_map({"Rig A": {"telescope": "140APO", "timezone": 7}})
    assert out["Rig A"]["timezone"] == ""


# --------------------------------------------------------------------------
# normalize_profile_map: coordinates, where zero is data and None is inherit
# --------------------------------------------------------------------------


def test_zero_coordinates_survive_normalization():
    out = normalize_profile_map(
        {"Greenwich": {"telescope": "140APO", "latitude": 0, "longitude": 0}}
    )
    assert out["Greenwich"]["latitude"] == 0.0
    assert out["Greenwich"]["longitude"] == 0.0
    assert out["Greenwich"]["latitude"] is not None
    assert out["Greenwich"]["longitude"] is not None


def test_numeric_strings_are_coerced():
    out = normalize_profile_map({"Rig A": {"latitude": "30.27", "longitude": "-97.74"}})
    assert out["Rig A"]["latitude"] == pytest.approx(30.27)
    assert out["Rig A"]["longitude"] == pytest.approx(-97.74)


def test_zero_numeric_string_is_a_real_coordinate():
    out = normalize_profile_map({"Rig A": {"latitude": "0", "longitude": "0.0"}})
    assert out["Rig A"]["latitude"] == 0.0
    assert out["Rig A"]["longitude"] == 0.0


def test_empty_and_unparseable_coordinate_strings_mean_inherit():
    out = normalize_profile_map({"Rig A": {"latitude": "", "longitude": "  west  "}})
    assert out["Rig A"]["latitude"] is None
    assert out["Rig A"]["longitude"] is None


def test_booleans_are_not_coordinates():
    out = normalize_profile_map({"Rig A": {"latitude": True, "longitude": False}})
    assert out["Rig A"]["latitude"] is None
    assert out["Rig A"]["longitude"] is None


def test_out_of_range_coordinates_mean_inherit():
    out = normalize_profile_map({"Rig A": {"latitude": 500.0, "longitude": -1000.0}})
    assert out["Rig A"]["latitude"] is None
    assert out["Rig A"]["longitude"] is None


def test_range_bounds_are_inclusive():
    out = normalize_profile_map({"Rig A": {"latitude": -90, "longitude": 180}})
    assert out["Rig A"]["latitude"] == -90.0
    assert out["Rig A"]["longitude"] == 180.0


def test_nan_and_infinity_mean_inherit():
    out = normalize_profile_map(
        {"Rig A": {"latitude": math.nan, "longitude": math.inf}}
    )
    assert out["Rig A"]["latitude"] is None
    assert out["Rig A"]["longitude"] is None


# --------------------------------------------------------------------------
# telescope_map
# --------------------------------------------------------------------------


def test_telescope_map_reproduces_the_legacy_map():
    raw = {"AM5n_OAG": "140APO", "140APO_AM5N": "140APO"}
    assert telescope_map(raw) == raw


def test_telescope_map_omits_unmapped_entries():
    raw = {
        "Rig A": {"telescope": None, "timezone": "America/Chicago"},
        "Rig B": {"telescope": "140APO", "timezone": ""},
    }
    out = telescope_map(raw)
    assert out == {"Rig B": "140APO"}
    # Absence, not a None value: callers use .get() and expect None for unmapped.
    assert out.get("Rig A") is None


def test_telescope_map_of_junk_is_empty():
    assert telescope_map(None) == {}


# --------------------------------------------------------------------------
# profile_timezone and profile_zone_resolver
# --------------------------------------------------------------------------


def test_profile_timezone_prefers_the_profile_zone():
    raw = {"Rig A": {"telescope": "140APO", "timezone": "America/Chicago"}}
    assert profile_timezone(raw, "Rig A", "Europe/Madrid") == ("America/Chicago", "profile")


def test_empty_profile_timezone_inherits_the_global():
    raw = {"Rig A": {"telescope": "140APO", "timezone": ""}}
    assert profile_timezone(raw, "Rig A", "Europe/Madrid") == ("Europe/Madrid", "global")


def test_unloadable_profile_timezone_degrades_to_the_global():
    raw = {"Rig A": {"timezone": "Mars/Olympus_Mons"}}
    assert profile_timezone(raw, "Rig A", "Europe/Madrid") == ("Europe/Madrid", "global")


def test_unloadable_global_timezone_is_unset():
    raw = {"Rig A": {"timezone": "Mars/Olympus_Mons"}}
    assert profile_timezone(raw, "Rig A", "Mars/Elysium") == ("", "unset")


def test_unknown_profile_inherits_the_global():
    raw = {"Rig A": {"timezone": "America/Chicago"}}
    assert profile_timezone(raw, "Rig Z", "Europe/Madrid") == ("Europe/Madrid", "global")


def test_section_without_a_profile_inherits_the_global():
    raw = {"Rig A": {"timezone": "America/Chicago"}}
    assert profile_timezone(raw, None, "Europe/Madrid") == ("Europe/Madrid", "global")
    assert profile_timezone(raw, "", "Europe/Madrid") == ("Europe/Madrid", "global")


def test_nothing_configured_anywhere_is_unset():
    assert profile_timezone({}, "Rig A", "") == ("", "unset")
    assert profile_timezone(None, None, None) == ("", "unset")


def test_legacy_string_entry_has_no_timezone_of_its_own():
    assert profile_timezone({"Rig A": "140APO"}, "Rig A", "Europe/Madrid") == (
        "Europe/Madrid",
        "global",
    )


def test_zone_resolver_agrees_with_profile_timezone():
    raw = {
        "Rig A": {"timezone": "America/Chicago"},
        "Rig B": {"timezone": ""},
        "Rig C": {"timezone": "Mars/Olympus_Mons"},
    }
    resolve = profile_zone_resolver(raw, "Europe/Madrid")
    for profile in ("Rig A", "Rig B", "Rig C", "Rig Z", None, ""):
        assert resolve(profile) == profile_timezone(raw, profile, "Europe/Madrid")


def test_zone_resolver_is_reusable_across_calls():
    resolve = profile_zone_resolver({"Rig A": {"timezone": "America/Chicago"}}, "")
    assert resolve("Rig A") == ("America/Chicago", "profile")
    assert resolve("Rig A") == ("America/Chicago", "profile")
    assert resolve("Rig Z") == ("", "unset")


# --------------------------------------------------------------------------
# profile_site and longitude_resolver
# --------------------------------------------------------------------------


def test_profile_site_prefers_the_profile_coordinates():
    raw = {"Rig A": {"latitude": 30.27, "longitude": -97.74}}
    lat, lon, source = profile_site(raw, "Rig A", 51.48, -0.0015)
    assert (lat, lon) == (pytest.approx(30.27), pytest.approx(-97.74))
    assert source == "profile"


def test_zero_profile_longitude_beats_a_set_global():
    # Greenwich. A falsy test here would silently substitute the global value.
    raw = {"Rig A": {"latitude": 0.0, "longitude": 0.0}}
    lat, lon, source = profile_site(raw, "Rig A", 30.27, -97.74)
    assert lat == 0.0
    assert lon == 0.0
    assert source == "profile"


def test_null_profile_coordinates_inherit_the_global():
    raw = {"Rig A": {"latitude": None, "longitude": None}}
    assert profile_site(raw, "Rig A", 30.27, -97.74) == (
        pytest.approx(30.27),
        pytest.approx(-97.74),
        "global",
    )


def test_zero_global_longitude_is_a_real_coordinate():
    # The global value is Greenwich and the profile inherits it. The answer is
    # 0.0 from the global, never "unset".
    raw = {"Rig A": {"telescope": "140APO"}}
    lat, lon, source = profile_site(raw, "Rig A", 0.0, 0.0)
    assert lat == 0.0
    assert lon == 0.0
    assert source == "global"


def test_one_profile_coordinate_and_one_inherited():
    raw = {"Rig A": {"latitude": 30.27, "longitude": None}}
    lat, lon, source = profile_site(raw, "Rig A", 51.48, -0.0015)
    assert lat == pytest.approx(30.27)
    assert lon == pytest.approx(-0.0015)
    assert source == "profile"


def test_profile_site_is_unset_only_when_both_levels_are_null():
    assert profile_site({"Rig A": {}}, "Rig A", None, None) == (None, None, "unset")
    assert profile_site(None, None, None, None) == (None, None, "unset")


def test_profile_site_reports_global_when_only_one_global_is_set():
    lat, lon, source = profile_site({}, "Rig A", None, -97.74)
    assert lat is None
    assert lon == pytest.approx(-97.74)
    assert source == "global"


def test_junk_global_coordinates_are_rejected():
    assert profile_site({}, "Rig A", "north", 500.0) == (None, None, "unset")


def test_legacy_string_entry_has_no_site_of_its_own():
    assert profile_site({"Rig A": "140APO"}, "Rig A", 30.27, -97.74) == (
        pytest.approx(30.27),
        pytest.approx(-97.74),
        "global",
    )


def test_longitude_resolver_agrees_with_profile_site():
    raw = {
        "Rig A": {"longitude": -97.74},
        "Rig B": {"longitude": 0.0},
        "Rig C": {"longitude": None},
    }
    resolve = longitude_resolver(raw, 8.55)
    for profile in ("Rig A", "Rig B", "Rig C", "Rig Z", None, ""):
        assert resolve(profile) == profile_site(raw, profile, None, 8.55)[1]


def test_longitude_resolver_keeps_a_zero_profile_longitude():
    resolve = longitude_resolver({"Greenwich": {"longitude": 0.0}}, -97.74)
    assert resolve("Greenwich") == 0.0
    assert resolve("Rig Z") == pytest.approx(-97.74)


def test_longitude_resolver_returns_none_when_nothing_is_configured():
    resolve = longitude_resolver({"Rig A": {"timezone": "America/Chicago"}}, None)
    assert resolve("Rig A") is None
    assert resolve(None) is None


# --------------------------------------------------------------------------
# profile_has_own_longitude / profile_has_own_latitude
#
# The sidereal cross-check picks its tier on longitude alone: a profile with
# its own longitude gets the tight 0.5 h tolerance and a confident verdict, a
# profile without one gets the 3 h meridian tolerance and hedged wording.
# profile_site's pair-level `source` cannot answer that question, so these
# predicates exist to answer it.
# --------------------------------------------------------------------------


def test_latitude_only_profile_does_not_have_its_own_longitude():
    # The trap this predicate exists to close. `source` reads "profile"
    # because the latitude is per-rig, but the longitude is the home site's.
    # A tier decision taken on `source` here applies a 0.5 h tolerance and a
    # confident verdict to an inherited longitude.
    raw = {"Rig A": {"latitude": 40.7, "longitude": None}}
    assert profile_site(raw, "Rig A", 51.48, -0.0015)[2] == "profile"
    assert profile_has_own_longitude(raw, "Rig A") is False
    assert profile_has_own_latitude(raw, "Rig A") is True


def test_longitude_only_profile_does_not_have_its_own_latitude():
    raw = {"Rig A": {"longitude": -97.74}}
    assert profile_has_own_longitude(raw, "Rig A") is True
    assert profile_has_own_latitude(raw, "Rig A") is False


def test_a_zero_coordinate_counts_as_the_profile_having_its_own():
    raw = {"Greenwich": {"latitude": 0.0, "longitude": 0.0}}
    assert profile_has_own_longitude(raw, "Greenwich") is True
    assert profile_has_own_latitude(raw, "Greenwich") is True


def test_unknown_and_missing_profiles_have_no_coordinates_of_their_own():
    raw = {"Rig A": {"latitude": 40.7, "longitude": -97.74}}
    for profile in ("Rig Z", None, ""):
        assert profile_has_own_longitude(raw, profile) is False
        assert profile_has_own_latitude(raw, profile) is False


def test_legacy_string_entry_has_no_coordinates_of_its_own():
    assert profile_has_own_longitude({"Rig A": "140APO"}, "Rig A") is False
    assert profile_has_own_latitude({"Rig A": "140APO"}, "Rig A") is False


def test_an_out_of_range_longitude_does_not_count_as_the_profile_having_one():
    # It normalizes to None, meaning inherit, so the tier must follow it down.
    raw = {"Rig A": {"longitude": 500.0}}
    assert profile_has_own_longitude(raw, "Rig A") is False


# --------------------------------------------------------------------------
# Write side: set_telescope and rewrite_telescopes
#
# Both existing rewriters (api/settings.py and data_migrations.py) rebuild the
# map with bare string values, which flattens an entry and destroys its
# timezone and site. The rule "rewrite the telescope, preserve everything
# else" lives here so it is written once.
# --------------------------------------------------------------------------


def test_rewrite_telescopes_preserves_timezone_and_coordinates():
    raw = {
        "Rig A": {
            "telescope": "SVBony SV503 80mm",
            "timezone": "America/Chicago",
            "latitude": 30.27,
            "longitude": -97.74,
        }
    }
    out = rewrite_telescopes(raw, {"SVBony SV503 80mm": "SVBony 80ED"})
    assert out["Rig A"] == {
        "telescope": "SVBony 80ED",
        "timezone": "America/Chicago",
        "latitude": pytest.approx(30.27),
        "longitude": pytest.approx(-97.74),
    }


def test_rewrite_telescopes_preserves_a_zero_longitude():
    raw = {"Greenwich": {"telescope": "140APO", "latitude": 0.0, "longitude": 0.0}}
    out = rewrite_telescopes(raw, {"140APO": "140 APO"})
    assert out["Greenwich"]["latitude"] == 0.0
    assert out["Greenwich"]["longitude"] == 0.0


def test_rewrite_telescopes_accepts_a_callable():
    raw = {"Rig A": "svbony sv503 80mm"}
    out = rewrite_telescopes(raw, lambda name: name.upper())
    assert out["Rig A"]["telescope"] == "SVBONY SV503 80MM"


def test_rewrite_telescopes_leaves_unlisted_names_alone():
    # Mirrors the `normalize_equipment(name, tel_map) or name` fallback both
    # existing call sites write by hand.
    raw = {"Rig A": "140APO", "Rig B": "RedCat 51"}
    out = rewrite_telescopes(raw, {"140APO": "140 APO"})
    assert telescope_map(out) == {"Rig A": "140 APO", "Rig B": "RedCat 51"}


def test_rewrite_telescopes_treats_an_empty_result_as_no_change():
    raw = {"Rig A": "140APO"}
    assert telescope_map(rewrite_telescopes(raw, lambda name: None)) == {"Rig A": "140APO"}
    assert telescope_map(rewrite_telescopes(raw, lambda name: "  ")) == {"Rig A": "140APO"}


def test_rewrite_telescopes_skips_unmapped_entries():
    raw = {"Rig A": {"telescope": None, "timezone": "America/Chicago"}}
    calls = []

    def rename(name):
        calls.append(name)
        return name

    out = rewrite_telescopes(raw, rename)
    assert calls == []
    assert out["Rig A"]["telescope"] is None
    assert out["Rig A"]["timezone"] == "America/Chicago"


def test_rewrite_telescopes_does_not_mutate_its_input():
    raw = {"Rig A": {"telescope": "140APO", "timezone": "America/Chicago"}}
    rewrite_telescopes(raw, {"140APO": "140 APO"})
    assert raw["Rig A"]["telescope"] == "140APO"


def test_rewrite_telescopes_change_detection_ignores_the_shape_upgrade():
    # The documented gate is `out != normalize_profile_map(raw)`, not
    # `out != raw`. Comparing against the raw legacy map would report a change
    # on every save and queue a pointless re-scan.
    raw = {"Rig A": "140APO"}
    out = rewrite_telescopes(raw, {"RedCat 51": "RedCat 51 II"})
    assert out != raw
    assert out == normalize_profile_map(raw)


def test_rewrite_telescopes_of_junk_is_empty():
    assert rewrite_telescopes(None, {"a": "b"}) == {}


def test_set_telescope_preserves_the_rest_of_the_entry():
    raw = {
        "Rig A": {
            "telescope": "140APO",
            "timezone": "America/Chicago",
            "latitude": 30.27,
            "longitude": -97.74,
        }
    }
    out = set_telescope(raw, "Rig A", "RedCat 51")
    assert out["Rig A"]["telescope"] == "RedCat 51"
    assert out["Rig A"]["timezone"] == "America/Chicago"
    assert out["Rig A"]["latitude"] == pytest.approx(30.27)
    assert out["Rig A"]["longitude"] == pytest.approx(-97.74)


def test_set_telescope_creates_a_missing_entry():
    out = set_telescope({}, "Rig A", "140APO")
    assert out["Rig A"] == {
        "telescope": "140APO",
        "timezone": "",
        "latitude": None,
        "longitude": None,
    }


def test_set_telescope_leaves_other_profiles_untouched():
    raw = {"Rig A": "140APO", "Rig B": {"telescope": "RedCat 51", "timezone": "UTC"}}
    out = set_telescope(raw, "Rig A", "Askar 120")
    assert out["Rig B"] == {
        "telescope": "RedCat 51",
        "timezone": "UTC",
        "latitude": None,
        "longitude": None,
    }


def test_clearing_the_telescope_drops_an_entry_that_carries_nothing_else():
    # Today's UI deletes the key when the select is cleared. An entry with no
    # other configuration must keep vanishing, or the map fills with husks.
    out = set_telescope({"Rig A": "140APO", "Rig B": "RedCat 51"}, "Rig A", "")
    assert set(out) == {"Rig B"}


def test_clearing_the_telescope_keeps_an_entry_that_carries_a_timezone():
    raw = {"Rig A": {"telescope": "140APO", "timezone": "America/Chicago"}}
    out = set_telescope(raw, "Rig A", "")
    assert out["Rig A"]["telescope"] is None
    assert out["Rig A"]["timezone"] == "America/Chicago"


def test_clearing_the_telescope_keeps_an_entry_sited_on_the_prime_meridian():
    # A falsy emptiness test would read longitude 0.0 as "carries nothing"
    # and delete the site the user configured.
    raw = {"Greenwich": {"telescope": "140APO", "latitude": 0.0, "longitude": 0.0}}
    out = set_telescope(raw, "Greenwich", "")
    assert "Greenwich" in out
    assert out["Greenwich"]["latitude"] == 0.0
    assert out["Greenwich"]["longitude"] == 0.0


def test_clearing_a_profile_that_is_absent_is_a_no_op():
    raw = {"Rig A": "140APO"}
    assert set_telescope(raw, "Rig Z", "") == normalize_profile_map(raw)


def test_set_telescope_does_not_mutate_its_input():
    raw = {"Rig A": {"telescope": "140APO", "timezone": "America/Chicago"}}
    set_telescope(raw, "Rig A", "RedCat 51")
    assert raw["Rig A"]["telescope"] == "140APO"
