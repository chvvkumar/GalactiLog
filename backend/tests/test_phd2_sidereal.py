"""Sidereal cross-check tests: GMST, implied longitude, coherence gate, verdict.

Reference values in this file are external. The GMST figures were produced by
astropy 7.2.0 via `Time(<iso>, scale='ut1').sidereal_time('mean', 'greenwich')`
and independently agree with Meeus, `Astronomical Algorithms`, Example 12.a
(1987 April 10 at 0h UT, 13h10m46.3668s) and Example 12.b (1987 April 10 at
19h21m00s UT, 8h34m57.0896s) to 3.3 milliseconds. They are pasted here as
literals so the test suite never imports astropy: `sidereal_time` reaches for
IERS earth-rotation tables and attempts a network download, and this code runs
on a guide-log ingest worker that may be offline.

The east-positive longitude convention is likewise pinned against astropy
(`sidereal_time('mean', longitude=+75 deg)` returns GMST + 5 h) and matches
`session_date.py`, whose solar-noon formula is `12 - longitude / 15`.

The pointing-geometry cases are pinned against facts that need no formula at
all: a target on the meridian whose declination equals the observer's latitude
passes through the zenith, the celestial equator crosses the meridian at
altitude 90 - latitude, a declination-zero target sits on the horizon at hour
angle 6 h from every latitude, and the altitude of the celestial pole equals
the observer's latitude.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.services.phd2_sidereal import (
    MIN_SIDEREAL_SECTIONS,
    POINTING_MAX_ALT_RESIDUAL_DEG,
    SIDEREAL_MAX_SPREAD_HOURS,
    SIDEREAL_NO_SITE_TOLERANCE_HOURS,
    SIDEREAL_TOLERANCE_HOURS,
    TIER_SITE_KNOWN,
    TIER_ZONE_MERIDIAN,
    SidVerdict,
    gmst_hours,
    implied_longitude_deg,
    implied_longitude_hours,
    latitude_from_pointing,
    offset_error_hours,
    pointing_is_coherent,
    verdict,
    wrap12,
    zone_meridian_longitude_deg,
)

UTC = timezone.utc

# One second of time expressed in hours. Two uses: the polynomial must land
# well inside it against the astropy reference, and the reference values below
# are quoted to ten decimals, so anything constructed from them carries the
# same residual. Every relation under test is exact; only the reference is not.
ONE_SECOND_HOURS = 1.0 / 3600.0

# (instant, GMST hours) from astropy 7.2.0, scale='ut1'.
GMST_REFERENCES = [
    (datetime(1987, 4, 10, 0, 0, 0, tzinfo=UTC), 13.1795472597),
    (datetime(1987, 4, 10, 19, 21, 0, tzinfo=UTC), 8.5825258054),
    (datetime(2000, 1, 1, 12, 0, 0, tzinfo=UTC), 18.6973748287),
    (datetime(2024, 6, 15, 3, 27, 41, tzinfo=UTC), 21.0555377778),
    (datetime(2026, 1, 31, 21, 5, 0, tzinfo=UTC), 5.8230751672),
    (datetime(2020, 11, 2, 9, 12, 33, 500000, tzinfo=UTC), 12.0165134243),
]


# --------------------------------------------------------------------------
# GMST
# --------------------------------------------------------------------------

@pytest.mark.parametrize("instant,expected", GMST_REFERENCES)
def test_gmst_matches_external_reference(instant, expected):
    assert gmst_hours(instant) == pytest.approx(expected, abs=ONE_SECOND_HOURS)


def test_gmst_meeus_example_12a_to_the_published_digits():
    # Meeus, Astronomical Algorithms, Example 12.a: 13h 10m 46.3668s.
    published = 13 + 10 / 60.0 + 46.3668 / 3600.0
    got = gmst_hours(datetime(1987, 4, 10, 0, 0, 0, tzinfo=UTC))
    assert got == pytest.approx(published, abs=0.05 * ONE_SECOND_HOURS)


def test_gmst_meeus_example_12b_to_the_published_digits():
    # Meeus Example 12.b: 8h 34m 57.0896s.
    published = 8 + 34 / 60.0 + 57.0896 / 3600.0
    got = gmst_hours(datetime(1987, 4, 10, 19, 21, 0, tzinfo=UTC))
    assert got == pytest.approx(published, abs=0.05 * ONE_SECOND_HOURS)


def test_gmst_is_wrapped_into_zero_to_twentyfour():
    start = datetime(2025, 3, 1, tzinfo=UTC)
    for minutes in range(0, 60 * 26, 37):
        value = gmst_hours(start + timedelta(minutes=minutes))
        assert 0.0 <= value < 24.0


def test_gmst_depends_on_the_instant_not_the_written_offset():
    utc_form = datetime(2024, 6, 15, 3, 27, 41, tzinfo=UTC)
    india_form = datetime(
        2024, 6, 15, 8, 57, 41, tzinfo=timezone(timedelta(hours=5, minutes=30))
    )
    assert gmst_hours(india_form) == pytest.approx(gmst_hours(utc_form), abs=1e-12)


def test_gmst_treats_a_naive_instant_as_utc():
    naive = datetime(2024, 6, 15, 3, 27, 41)
    aware = datetime(2024, 6, 15, 3, 27, 41, tzinfo=UTC)
    assert gmst_hours(naive) == pytest.approx(gmst_hours(aware), abs=1e-12)


def test_gmst_advances_faster_than_solar_time():
    # A sidereal day is 23h56m04s, so 24 h of clock time advances GMST by
    # 3m56.6s. This surplus is what makes the offset solve possible.
    base = datetime(2025, 9, 9, 1, 0, 0, tzinfo=UTC)
    advance = wrap12(gmst_hours(base + timedelta(days=1)) - gmst_hours(base))
    assert advance * 3600.0 == pytest.approx(236.5554, abs=0.01)


# --------------------------------------------------------------------------
# wrap12
# --------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    (0.0, 0.0),
    (5.0, 5.0),
    (-5.0, -5.0),
    (13.0, -11.0),
    (-13.0, 11.0),
    (24.0, 0.0),
    (23.5, -0.5),
    (-23.5, 0.5),
    (11.999, 11.999),
])
def test_wrap12_maps_into_minus_twelve_to_twelve(raw, expected):
    assert wrap12(raw) == pytest.approx(expected, abs=1e-9)


# --------------------------------------------------------------------------
# implied longitude
# --------------------------------------------------------------------------

def test_implied_longitude_is_zero_at_greenwich():
    # Local sidereal time at Greenwich equals GMST, so a target whose RA plus
    # hour angle sums to the reference GMST implies longitude zero.
    instant, gmst = GMST_REFERENCES[3]
    ra = 10.0
    ha = gmst - ra
    assert implied_longitude_hours(ra, ha, instant) == pytest.approx(
        0.0, abs=ONE_SECOND_HOURS
    )


def test_implied_longitude_is_positive_east():
    # astropy: sidereal_time('mean', longitude=+75 deg) == GMST + 5 h.
    instant, gmst = GMST_REFERENCES[3]
    lst_at_plus_75 = (gmst + 5.0) % 24.0
    ra = 10.0
    ha = lst_at_plus_75 - ra
    assert implied_longitude_hours(ra, ha, instant) == pytest.approx(
        5.0, abs=ONE_SECOND_HOURS
    )


def test_implied_longitude_is_negative_west():
    # astropy: sidereal_time('mean', longitude=-74 deg) == GMST - 4.93333 h.
    instant, gmst = GMST_REFERENCES[3]
    lst_at_minus_74 = (gmst - 74.0 / 15.0) % 24.0
    ra = 10.0
    ha = lst_at_minus_74 - ra
    assert implied_longitude_hours(ra, ha, instant) == pytest.approx(
        -74.0 / 15.0, abs=ONE_SECOND_HOURS
    )


def test_implied_longitude_survives_hour_angle_wrapping_past_twentyfour():
    instant, gmst = GMST_REFERENCES[4]
    ra = 23.5
    positive = (gmst - ra) % 24.0
    plain = implied_longitude_hours(ra, positive, instant)
    wrapped = implied_longitude_hours(ra, positive - 24.0, instant)
    assert plain == pytest.approx(wrapped, abs=1e-9)


def test_implied_longitude_accepts_a_negative_hour_angle():
    # PHD2 writes hour angle signed; east of the meridian is negative.
    instant, gmst = GMST_REFERENCES[5]
    ra = 4.0
    ha = -3.25
    expected = wrap12((ra + ha) % 24.0 - gmst)
    assert implied_longitude_hours(ra, ha, instant) == pytest.approx(
        expected, abs=ONE_SECOND_HOURS
    )


@pytest.mark.parametrize("ra,ha", [(None, 1.0), (5.0, None), (None, None)])
def test_implied_longitude_is_none_when_pointing_is_incomplete(ra, ha):
    # The ASIAIR degrade path: those logs carry no RA.
    assert implied_longitude_hours(ra, ha, GMST_REFERENCES[3][0]) is None


def test_implied_longitude_deg_is_hours_times_fifteen():
    instant, gmst = GMST_REFERENCES[3]
    ra = 10.0
    ha = (gmst + 5.0) % 24.0 - ra
    assert implied_longitude_deg(ra, ha, instant) == pytest.approx(
        75.0, abs=15.0 * ONE_SECOND_HOURS
    )


def test_implied_longitude_deg_is_none_when_pointing_is_incomplete():
    assert implied_longitude_deg(None, 1.0, GMST_REFERENCES[3][0]) is None


# --------------------------------------------------------------------------
# offset error, and the sign convention
# --------------------------------------------------------------------------

def test_offset_error_is_zero_when_the_site_matches():
    assert offset_error_hours(-74.0 / 15.0, -74.0) == pytest.approx(0.0, abs=1e-12)


def test_offset_error_takes_the_short_way_round_the_meridian():
    # Implied 11.9 h east against a site at 179 deg west is 0.17 h, not 23.8 h.
    assert offset_error_hours(11.9, -179.0) == pytest.approx(-0.1666667, abs=1e-6)


# The sign pin. This case is synthetic and its truth is known by construction,
# not read off the formula. A rig at 74 deg west runs on America/New_York,
# which on 2026 April 10 is UTC-4. The pointing is generated from that truth
# and then handed back with a deliberately wrong assumed instant.
_SIGN_SITE_LON_DEG = -74.0
_SIGN_TRUE_UTC = datetime(2026, 4, 11, 2, 0, 0, tzinfo=UTC)     # 22:00 at UTC-4
_SIGN_WRONG_UTC = datetime(2026, 4, 10, 21, 0, 0, tzinfo=UTC)   # 22:00 read as UTC+1
_SIGN_RA_HR = 12.34
_SIGN_HA_HR = -1.9861522110  # LST at the true instant and true site, minus RA


def test_sign_correct_timezone_produces_no_offset_error():
    implied = implied_longitude_hours(_SIGN_RA_HR, _SIGN_HA_HR, _SIGN_TRUE_UTC)
    assert offset_error_hours(implied, _SIGN_SITE_LON_DEG) == pytest.approx(
        0.0, abs=ONE_SECOND_HOURS
    )


def test_sign_a_configured_zone_ahead_of_the_truth_gives_a_positive_error():
    # The profile says Europe/London, UTC+1 in April; the rig really runs at
    # UTC-4. The configured zone is 5 hours ahead of the truth.
    implied = implied_longitude_hours(_SIGN_RA_HR, _SIGN_HA_HR, _SIGN_WRONG_UTC)
    error = offset_error_hours(implied, _SIGN_SITE_LON_DEG)
    assert error > 0
    # 5 hours of clock time is 5 x 1.00274 hours of sidereal time.
    assert error == pytest.approx(5.0137, abs=0.005)


def test_sign_a_configured_zone_behind_the_truth_gives_a_negative_error():
    # Same rig and same pointing, but the wall clock is now read as UTC-9,
    # which puts the assumed instant 5 hours later than the truth.
    assumed = _SIGN_TRUE_UTC + timedelta(hours=5)
    implied = implied_longitude_hours(_SIGN_RA_HR, _SIGN_HA_HR, assumed)
    error = offset_error_hours(implied, _SIGN_SITE_LON_DEG)
    assert error < 0
    assert error == pytest.approx(-5.0137, abs=0.005)


# --------------------------------------------------------------------------
# pointing coherence gate
# --------------------------------------------------------------------------

def test_pointing_is_coherent_for_the_equator_on_the_meridian():
    # The celestial equator crosses the meridian at altitude 90 - latitude.
    assert pointing_is_coherent(50.0, 0.0, 0.0, 40.0) is True


def test_pointing_is_incoherent_when_the_latitude_is_wrong():
    assert pointing_is_coherent(50.0, 0.0, 0.0, 10.0) is False


def test_pointing_is_coherent_at_the_zenith_when_declination_equals_latitude():
    assert pointing_is_coherent(90.0, 40.7, 0.0, 40.7) is True


def test_pointing_is_coherent_for_the_celestial_pole():
    # The altitude of the pole equals the observer's latitude at any hour angle.
    assert pointing_is_coherent(52.0, 90.0, 3.5, 52.0) is True
    assert pointing_is_coherent(52.0, 90.0, -7.25, 52.0) is True


def test_pointing_is_incoherent_for_a_pole_altitude_that_is_not_the_latitude():
    assert pointing_is_coherent(20.0, 90.0, 3.5, 52.0) is False


def test_pointing_is_coherent_on_the_horizon_at_six_hours_of_hour_angle():
    # A declination-zero target is on the horizon at hour angle +/- 6 h from
    # every latitude, so this case constrains nothing and must not reject.
    for latitude in (-45.0, 0.0, 40.0, 60.0):
        assert pointing_is_coherent(0.0, 0.0, 6.0, latitude) is True
        assert pointing_is_coherent(0.0, 0.0, -6.0, latitude) is True


def test_pointing_coherence_tolerance_is_the_documented_constant():
    inside = 50.0 + POINTING_MAX_ALT_RESIDUAL_DEG - 0.2
    outside = 50.0 + POINTING_MAX_ALT_RESIDUAL_DEG + 0.2
    assert pointing_is_coherent(inside, 0.0, 0.0, 40.0) is True
    assert pointing_is_coherent(outside, 0.0, 0.0, 40.0) is False


@pytest.mark.parametrize("alt,dec,ha,lat", [
    (None, 0.0, 0.0, 40.0),
    (50.0, None, 0.0, 40.0),
    (50.0, 0.0, None, 40.0),
    (50.0, 0.0, 0.0, None),
])
def test_pointing_coherence_is_none_when_an_input_is_missing(alt, dec, ha, lat):
    assert pointing_is_coherent(alt, dec, ha, lat) is None


def test_latitude_from_pointing_recovers_the_two_geometric_solutions():
    # Altitude 50 on the meridian at declination zero fits latitude +40 and
    # latitude -40 equally. Both are returned; the caller decides.
    got = latitude_from_pointing(50.0, 0.0, 0.0)
    assert got == pytest.approx([-40.0, 40.0], abs=1e-6)


def test_latitude_from_pointing_is_unique_at_the_celestial_pole():
    got = latitude_from_pointing(52.0, 90.0, 3.5)
    assert len(got) == 1
    assert got[0] == pytest.approx(52.0, abs=1e-6)


def test_latitude_from_pointing_is_empty_for_unreachable_geometry():
    # At hour angle 6 h a declination-30 target cannot exceed altitude 30 from
    # any latitude, so altitude 80 pins no latitude at all.
    assert latitude_from_pointing(80.0, 30.0, 6.0) == []


def test_latitude_from_pointing_is_none_when_an_input_is_missing():
    assert latitude_from_pointing(None, 0.0, 0.0) is None


# --------------------------------------------------------------------------
# verdict
# --------------------------------------------------------------------------

def _tight(centre, n=6, jitter=0.01):
    return [centre + jitter * ((i % 3) - 1) for i in range(n)]


def test_verdict_is_none_below_the_minimum_section_count():
    assert verdict(_tight(6.0, n=MIN_SIDEREAL_SECTIONS - 1)) is None


def test_verdict_is_emitted_at_exactly_the_minimum_section_count():
    got = verdict(_tight(6.0, n=MIN_SIDEREAL_SECTIONS))
    assert got is not None
    assert got.sample_count == MIN_SIDEREAL_SECTIONS


def test_verdict_is_none_for_an_empty_sample_list():
    assert verdict([]) is None


def test_verdict_is_none_when_the_error_is_inside_tolerance():
    assert verdict(_tight(SIDEREAL_TOLERANCE_HOURS - 0.1)) is None


def test_verdict_is_emitted_for_a_tight_six_hour_cluster():
    got = verdict(_tight(6.0))
    assert isinstance(got, SidVerdict)
    assert got.median_error_hours == pytest.approx(6.0, abs=0.02)
    assert got.nearest_whole_hours == 6
    assert got.sample_count == 6
    assert got.tier == TIER_SITE_KNOWN
    assert got.tolerance_hours == SIDEREAL_TOLERANCE_HOURS
    assert got.confident is True


def test_verdict_keeps_the_sign_of_the_median_error():
    got = verdict(_tight(-6.0))
    assert got is not None
    assert got.median_error_hours == pytest.approx(-6.0, abs=0.02)
    assert got.nearest_whole_hours == -6


def test_verdict_is_none_when_the_samples_are_scattered():
    # A drifting mount clock, or a profile carried between two sites. The
    # median is a clean 6 h but the spread says the evidence is not there.
    scattered = [1.0, 3.5, 6.0, 6.1, 9.0, 11.5]
    assert verdict(scattered) is None


def test_verdict_spread_guard_uses_the_documented_constant():
    inside = [6.0 + SIDEREAL_MAX_SPREAD_HOURS * k
              for k in (-0.2, -0.1, 0.0, 0.0, 0.1, 0.2)]
    outside = [6.0 + SIDEREAL_MAX_SPREAD_HOURS * k
               for k in (-1.5, -1.0, 0.0, 0.0, 1.0, 1.5)]
    assert verdict(inside) is not None
    assert verdict(outside) is None


def test_verdict_handles_a_cluster_straddling_the_twelve_hour_wrap():
    # +11.98 and -11.98 are 0.04 h apart, not 23.96 h apart.
    straddling = [11.98, -11.98, 11.99, -11.99, 12.0, -11.97]
    got = verdict(straddling)
    assert got is not None
    assert abs(got.median_error_hours) == pytest.approx(12.0, abs=0.05)
    assert abs(got.nearest_whole_hours) == 12


def test_verdict_rounds_to_the_nearest_whole_hour():
    got = verdict(_tight(5.51))
    assert got is not None
    assert got.nearest_whole_hours == 6


def test_verdict_meridian_tier_ignores_errors_a_wide_zone_can_explain():
    # Xinjiang sits about 3 h from the +8 meridian, so a 2 h disagreement
    # against a standard meridian is not evidence of anything.
    assert verdict(_tight(2.0), tier=TIER_ZONE_MERIDIAN) is None
    assert verdict(_tight(2.0), tier=TIER_SITE_KNOWN) is not None


def test_verdict_meridian_tier_fires_on_a_gross_error():
    got = verdict(_tight(6.0), tier=TIER_ZONE_MERIDIAN)
    assert got is not None
    assert got.tier == TIER_ZONE_MERIDIAN
    assert got.tolerance_hours == SIDEREAL_NO_SITE_TOLERANCE_HOURS
    assert got.confident is False


def test_verdict_meridian_tier_suggests_a_longitude_to_enter():
    got = verdict(_tight(6.0), tier=TIER_ZONE_MERIDIAN,
                  implied_longitudes_hours=_tight(-1.5))
    assert got is not None
    assert got.implied_longitude_deg == pytest.approx(-22.5, abs=0.3)


def test_verdict_suggested_longitude_is_none_without_implied_samples():
    got = verdict(_tight(6.0), tier=TIER_ZONE_MERIDIAN)
    assert got is not None
    assert got.implied_longitude_deg is None


def test_verdict_rejects_an_unknown_tier():
    with pytest.raises(ValueError):
        verdict(_tight(6.0), tier="guesswork")


# --------------------------------------------------------------------------
# zone standard meridian
# --------------------------------------------------------------------------

def test_zone_meridian_follows_daylight_saving():
    summer = datetime(2026, 7, 15, 4, 0, 0, tzinfo=UTC)
    winter = datetime(2026, 1, 15, 4, 0, 0, tzinfo=UTC)
    assert zone_meridian_longitude_deg("America/New_York", summer) == pytest.approx(-60.0)
    assert zone_meridian_longitude_deg("America/New_York", winter) == pytest.approx(-75.0)


def test_zone_meridian_handles_a_half_hour_zone():
    instant = datetime(2026, 7, 15, 4, 0, 0, tzinfo=UTC)
    assert zone_meridian_longitude_deg("Asia/Kolkata", instant) == pytest.approx(82.5)


@pytest.mark.parametrize("name", ["", None, "Not/AZone"])
def test_zone_meridian_is_none_for_an_unusable_zone(name):
    assert zone_meridian_longitude_deg(name, datetime(2026, 7, 15, tzinfo=UTC)) is None


def test_module_never_imports_astropy():
    # The reason the polynomial exists: astropy's sidereal_time reaches for
    # IERS tables and would try to download them on an offline worker.
    import inspect

    from app.services import phd2_sidereal

    for line in inspect.getsource(phd2_sidereal).splitlines():
        stripped = line.strip()
        assert not stripped.startswith("import astropy")
        assert not stripped.startswith("from astropy")
