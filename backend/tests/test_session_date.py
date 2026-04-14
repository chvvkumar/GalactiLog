from datetime import datetime, date, timezone
from app.services.session_date import compute_session_date


class TestComputeSessionDate:
    """Test session date computation with longitude-based noon boundary."""

    def test_disabled_returns_utc_date(self):
        dt = datetime(2024, 11, 16, 2, 0, tzinfo=timezone.utc)
        result = compute_session_date(dt, use_imaging_night=False)
        assert result == date(2024, 11, 16)

    def test_no_longitude_returns_utc_date(self):
        dt = datetime(2024, 11, 16, 2, 0, tzinfo=timezone.utc)
        result = compute_session_date(dt, use_imaging_night=True, longitude=None)
        assert result == date(2024, 11, 16)

    def test_us_central_before_midnight(self):
        """US Central observer (lon=-97), imaging at 9PM local = 03:00 UTC next day.
        Solar noon UTC ~ 12 - (-97/15) = 12 + 6.47 = 18:28 UTC.
        03:00 UTC < 18:28 UTC => session_date = previous day."""
        dt = datetime(2024, 11, 16, 3, 0, tzinfo=timezone.utc)
        result = compute_session_date(dt, use_imaging_night=True, longitude=-97.0)
        assert result == date(2024, 11, 15)

    def test_us_central_after_midnight_same_session(self):
        dt = datetime(2024, 11, 16, 10, 0, tzinfo=timezone.utc)
        result = compute_session_date(dt, use_imaging_night=True, longitude=-97.0)
        assert result == date(2024, 11, 15)

    def test_us_central_afternoon_next_session(self):
        dt = datetime(2024, 11, 16, 21, 0, tzinfo=timezone.utc)
        result = compute_session_date(dt, use_imaging_night=True, longitude=-97.0)
        assert result == date(2024, 11, 16)

    def test_australia_sydney_before_midnight(self):
        """Sydney (lon=151), 9PM local = 11:00 UTC. Solar noon UTC ~ 01:53.
        11:00 > 01:53 => current day."""
        dt = datetime(2024, 11, 15, 11, 0, tzinfo=timezone.utc)
        result = compute_session_date(dt, use_imaging_night=True, longitude=151.0)
        assert result == date(2024, 11, 15)

    def test_australia_sydney_after_midnight(self):
        dt = datetime(2024, 11, 15, 17, 0, tzinfo=timezone.utc)
        result = compute_session_date(dt, use_imaging_night=True, longitude=151.0)
        assert result == date(2024, 11, 15)

    def test_australia_sydney_after_local_midnight_crosses_utc_day(self):
        dt = datetime(2024, 11, 15, 15, 0, tzinfo=timezone.utc)
        result = compute_session_date(dt, use_imaging_night=True, longitude=151.0)
        assert result == date(2024, 11, 15)

    def test_greenwich_matches_utc_noon(self):
        dt = datetime(2024, 6, 15, 1, 0, tzinfo=timezone.utc)
        result = compute_session_date(dt, use_imaging_night=True, longitude=0.0)
        assert result == date(2024, 6, 14)

    def test_greenwich_afternoon(self):
        dt = datetime(2024, 6, 15, 13, 0, tzinfo=timezone.utc)
        result = compute_session_date(dt, use_imaging_night=True, longitude=0.0)
        assert result == date(2024, 6, 15)

    def test_naive_datetime_treated_as_utc(self):
        dt = datetime(2024, 11, 16, 3, 0)
        result = compute_session_date(dt, use_imaging_night=True, longitude=-97.0)
        assert result == date(2024, 11, 15)

    def test_none_capture_date_returns_none(self):
        result = compute_session_date(None, use_imaging_night=True, longitude=-97.0)
        assert result is None


class TestExtractLongitude:
    def test_sitelong_header(self):
        from app.services.session_date import extract_longitude
        headers = {"SITELONG": "-97.5"}
        assert extract_longitude(headers) == -97.5

    def test_obslong_header(self):
        from app.services.session_date import extract_longitude
        headers = {"OBSLONG": "151.2"}
        assert extract_longitude(headers) == 151.2

    def test_long_obs_header(self):
        from app.services.session_date import extract_longitude
        headers = {"LONG-OBS": "2.3"}
        assert extract_longitude(headers) == 2.3

    def test_priority_order(self):
        from app.services.session_date import extract_longitude
        headers = {"SITELONG": "-97.5", "OBSLONG": "151.2"}
        assert extract_longitude(headers) == -97.5

    def test_no_longitude_returns_none(self):
        from app.services.session_date import extract_longitude
        headers = {"OBJECT": "M31"}
        assert extract_longitude(headers) is None

    def test_non_numeric_returns_none(self):
        from app.services.session_date import extract_longitude
        headers = {"SITELONG": "bad"}
        assert extract_longitude(headers) is None

    def test_none_headers_returns_none(self):
        from app.services.session_date import extract_longitude
        assert extract_longitude(None) is None
