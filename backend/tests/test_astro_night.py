"""Tests for astronomical night duration calculation."""
import pytest
from datetime import date
from app.services.astro_night import dark_hours_for_night, dark_hours_for_month


class TestDarkHoursForNight:
    """Test single-night astronomical darkness calculation."""

    def test_winter_solstice_mid_latitude(self):
        """Winter solstice at ~33N should have long dark hours (~10-12h)."""
        hours = dark_hours_for_night(date(2025, 12, 21), 33.0, -117.0)
        assert 10.0 < hours < 13.0

    def test_summer_solstice_mid_latitude(self):
        """Summer solstice at ~33N should have short dark hours (~5-7h)."""
        hours = dark_hours_for_night(date(2025, 6, 21), 33.0, -117.0)
        assert 5.0 < hours < 8.0

    def test_arctic_summer_very_short(self):
        """Arctic summer should have near-zero dark hours."""
        hours = dark_hours_for_night(date(2025, 6, 21), 65.0, 25.0)
        assert hours < 2.0

    def test_returns_float(self):
        hours = dark_hours_for_night(date(2025, 3, 20), 33.0, -117.0)
        assert isinstance(hours, float)
        assert hours >= 0.0


class TestDarkHoursForMonth:
    """Test monthly aggregation of dark hours."""

    def test_december_more_than_june(self):
        """At mid-northern latitude, December should have more dark hours than June."""
        dec = dark_hours_for_month(2025, 12, 33.0, -117.0)
        jun = dark_hours_for_month(2025, 6, 33.0, -117.0)
        assert dec > jun

    def test_returns_positive_float(self):
        hours = dark_hours_for_month(2025, 1, 33.0, -117.0)
        assert isinstance(hours, float)
        assert hours > 0.0

    def test_february_fewer_days(self):
        """February total should be less than March (fewer days, similar night length)."""
        feb = dark_hours_for_month(2025, 2, 33.0, -117.0)
        mar = dark_hours_for_month(2025, 3, 33.0, -117.0)
        assert feb < mar
