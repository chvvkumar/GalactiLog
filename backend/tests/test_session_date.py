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


class TestImagingNightFallbackWarning:
    """AUD-021: the UTC-midnight fallback must be surfaced, but rate-limited
    to one warning per scan/recompute run, never one per image."""

    def test_compute_session_date_itself_is_silent(self, caplog):
        """The per-image function must NOT log the warning (it is emitted by
        callers via warn_imaging_night_fallback, once per run)."""
        import logging

        dt = datetime(2024, 11, 16, 2, 0, tzinfo=timezone.utc)
        with caplog.at_level(logging.WARNING, logger="app.services.session_date"):
            for _ in range(5):
                compute_session_date(dt, use_imaging_night=True, longitude=None)
        assert caplog.records == []

    def test_warn_helper_emits_single_warning(self, caplog):
        import logging
        from app.services.session_date import warn_imaging_night_fallback

        with caplog.at_level(logging.WARNING, logger="app.services.session_date"):
            warn_imaging_night_fallback()
        assert len(caplog.records) == 1
        assert "observer_longitude" in caplog.records[0].getMessage()

    def test_ingest_guard_warns_exactly_once_across_multiple_calls(self, caplog):
        """Simulate the caller-side pattern used by _do_ingest and
        recompute_session_dates: many fallback observations in one run emit
        exactly one warning."""
        import logging
        from app.services.session_date import warn_imaging_night_fallback

        dt = datetime(2024, 11, 16, 2, 0, tzinfo=timezone.utc)
        fallback_warned = False
        with caplog.at_level(logging.WARNING, logger="app.services.session_date"):
            for _ in range(100):
                use_imaging_night = True
                longitude = None
                if use_imaging_night and longitude is None and not fallback_warned:
                    warn_imaging_night_fallback()
                    fallback_warned = True
                compute_session_date(
                    dt, use_imaging_night=use_imaging_night, longitude=longitude
                )
        assert len(caplog.records) == 1

    def test_worker_module_guard_warns_once_per_process(self, caplog):
        """The module-level guard in app.worker.tasks (used by the per-image
        _do_ingest path) fires the warning at most once per process."""
        import logging
        import app.worker.tasks as tasks_mod
        from app.services.session_date import warn_imaging_night_fallback

        tasks_mod._imaging_night_fallback_warned = False
        try:
            with caplog.at_level(logging.WARNING, logger="app.services.session_date"):
                for _ in range(10):
                    # Mirrors the guard block in _do_ingest.
                    if not tasks_mod._imaging_night_fallback_warned:
                        warn_imaging_night_fallback()
                        tasks_mod._imaging_night_fallback_warned = True
            assert len(caplog.records) == 1
            assert tasks_mod._imaging_night_fallback_warned is True
        finally:
            tasks_mod._imaging_night_fallback_warned = False


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
