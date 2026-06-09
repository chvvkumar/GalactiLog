"""Unit tests for app.services.usno - time parsing, response parsing, and HTTP mocking."""
import pytest
from unittest.mock import MagicMock, patch

from app.services.usno import (
    _empty_result,
    _parse_time_to_iso,
    get_night_ephemeris,
)


# ---------------------------------------------------------------------------
# _empty_result
# ---------------------------------------------------------------------------

class TestEmptyResult:
    def test_has_required_keys(self):
        r = _empty_result("2024-06-15")
        assert r["date"] == "2024-06-15"
        assert r["astro_dusk"] is None
        assert r["astro_dawn"] is None
        assert r["moon_phase"] is None
        assert r["moon_illumination"] is None
        assert r["moon_rise"] is None
        assert r["moon_set"] is None
        assert r["source_available"] is False


# ---------------------------------------------------------------------------
# _parse_time_to_iso
# ---------------------------------------------------------------------------

class TestParseTimeToIso:
    def test_valid_time_returns_iso(self):
        result = _parse_time_to_iso("2024-06-15", "21:15")
        assert result == "2024-06-15T21:15:00+00:00"

    def test_includes_utc_offset(self):
        result = _parse_time_to_iso("2024-01-01", "00:00")
        assert "+00:00" in result

    def test_invalid_time_returns_original_string(self):
        result = _parse_time_to_iso("2024-06-15", "NOTAZEIT")
        assert result == "NOTAZEIT"

    def test_invalid_date_returns_original_string(self):
        result = _parse_time_to_iso("BAD-DATE", "21:15")
        assert result == "21:15"


# ---------------------------------------------------------------------------
# get_night_ephemeris (HTTP mocked)
# ---------------------------------------------------------------------------

_RSTT_RESPONSE = {
    "properties": {
        "data": {
            "sundata": [
                {"phen": "EA", "time": "21:30"},
                {"phen": "BA", "time": "03:45"},
            ],
            "moondata": [
                {"phen": "Rise", "time": "22:00"},
                {"phen": "Set", "time": "06:15"},
            ],
            "closestphase": {"phase": "Waxing Gibbous"},
            "curphase": "45.6%",
        }
    }
}


def _make_client_with_responses(*json_responses):
    resps = []
    for data in json_responses:
        resp = MagicMock()
        resp.json = MagicMock(return_value=data)
        resp.raise_for_status = MagicMock()
        resps.append(resp)

    client = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    client.get = MagicMock(side_effect=resps)
    return client


class TestGetNightEphemeris:
    def test_parses_valid_response(self):
        client = _make_client_with_responses(_RSTT_RESPONSE)
        with patch("app.services.usno.httpx.Client", return_value=client):
            result = get_night_ephemeris("2024-06-15", 35.0, -106.0)

        assert result["source_available"] is True
        assert "21:30" in result["astro_dusk"]
        assert "03:45" in result["astro_dawn"]
        assert "22:00" in result["moon_rise"]
        assert "06:15" in result["moon_set"]
        assert result["moon_phase"] == "Waxing Gibbous"
        assert result["moon_illumination"] == pytest.approx(0.456, rel=0.01)

    def test_returns_empty_on_http_error(self):
        import httpx
        client = MagicMock()
        client.__enter__ = MagicMock(return_value=client)
        client.__exit__ = MagicMock(return_value=False)
        client.get = MagicMock(side_effect=httpx.HTTPError("timeout"))

        with patch("app.services.usno.httpx.Client", return_value=client):
            result = get_night_ephemeris("2024-06-15", 35.0, -106.0)

        assert result["source_available"] is False
        assert result["astro_dusk"] is None

    def test_date_preserved_in_result(self):
        client = _make_client_with_responses(_RSTT_RESPONSE)
        with patch("app.services.usno.httpx.Client", return_value=client):
            result = get_night_ephemeris("2024-06-15", 35.0, -106.0)

        assert result["date"] == "2024-06-15"

    def test_moon_illumination_parsing(self):
        # curphase as percent string
        data = {
            "properties": {
                "data": {
                    "sundata": [],
                    "moondata": [],
                    "closestphase": {"phase": "Full Moon"},
                    "curphase": "99.8%",
                }
            }
        }
        client = _make_client_with_responses(data)
        with patch("app.services.usno.httpx.Client", return_value=client):
            result = get_night_ephemeris("2024-06-15", 35.0, -106.0)

        assert result["moon_illumination"] == pytest.approx(0.998, rel=0.001)

    def test_handles_empty_properties(self):
        data = {"properties": {"data": {}}}
        client = _make_client_with_responses(data)
        with patch("app.services.usno.httpx.Client", return_value=client):
            result = get_night_ephemeris("2024-06-15", 35.0, -106.0)

        assert result["source_available"] is True
        assert result["astro_dusk"] is None
        assert result["astro_dawn"] is None

    def test_ba_phenomen_maps_to_astro_dawn(self):
        data = {
            "properties": {
                "data": {
                    "sundata": [
                        {"phen": "BA", "time": "04:10"},
                    ],
                    "moondata": [],
                }
            }
        }
        client = _make_client_with_responses(data)
        with patch("app.services.usno.httpx.Client", return_value=client):
            result = get_night_ephemeris("2024-06-15", 35.0, -106.0)

        assert "04:10" in result["astro_dawn"]

    def test_full_name_astronomical_twilight_end(self):
        data = {
            "properties": {
                "data": {
                    "sundata": [
                        {"phen": "End Astronomical Twilight", "time": "21:45"},
                    ],
                    "moondata": [],
                }
            }
        }
        client = _make_client_with_responses(data)
        with patch("app.services.usno.httpx.Client", return_value=client):
            result = get_night_ephemeris("2024-06-15", 35.0, -106.0)

        assert "21:45" in result["astro_dusk"]
