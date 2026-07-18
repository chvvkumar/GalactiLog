"""Tests for the plate-scale spine (app.services.units)."""

import pytest

from app.services.units import (
    arcsec_per_pixel,
    to_arcsec,
    plate_scale_from_headers,
    sql_arcsec_per_pixel,
)


class TestArcsecPerPixel:
    def test_known_value(self):
        # 3.76 um pixels at 530 mm: 206.265 * 3.76 / 530
        assert arcsec_per_pixel(3.76, 530) == pytest.approx(1.4633, abs=1e-3)

    def test_accepts_numeric_strings(self):
        # FITS headers arrive as text
        assert arcsec_per_pixel("3.76", "530") == pytest.approx(1.4633, abs=1e-3)

    def test_none_inputs(self):
        assert arcsec_per_pixel(None, 530) is None
        assert arcsec_per_pixel(3.76, None) is None
        assert arcsec_per_pixel(None, None) is None

    def test_zero_and_negative_inputs(self):
        assert arcsec_per_pixel(0, 530) is None
        assert arcsec_per_pixel(3.76, 0) is None
        assert arcsec_per_pixel(-3.76, 530) is None
        assert arcsec_per_pixel(3.76, -530) is None

    def test_non_numeric_strings(self):
        assert arcsec_per_pixel("abc", 530) is None
        assert arcsec_per_pixel(3.76, "") is None


class TestToArcsec:
    def test_converts(self):
        # 2.0 px HFR at ~1.4633 arcsec/px
        assert to_arcsec(2.0, 3.76, 530) == pytest.approx(2.9265, abs=1e-3)

    def test_none_value(self):
        assert to_arcsec(None, 3.76, 530) is None

    def test_no_scale(self):
        assert to_arcsec(2.0, None, 530) is None
        assert to_arcsec(2.0, 3.76, 0) is None


class TestPlateScaleFromHeaders:
    def test_from_headers(self):
        hdrs = {"XPIXSZ": "3.76", "FOCALLEN": "530"}
        assert plate_scale_from_headers(hdrs) == pytest.approx(1.4633, abs=1e-3)

    def test_missing_keys(self):
        assert plate_scale_from_headers({"OBJECT": "M 42"}) is None
        assert plate_scale_from_headers({}) is None
        assert plate_scale_from_headers(None) is None


class TestMosaicParity:
    """The refactored mosaic call sites must match the old inline formula."""

    def test_compute_fov_arcmin_unchanged(self):
        from app.services.mosaic_detection import compute_fov_arcmin

        # Old formula: naxis * (206.265 * xpixsz / focallen) / 60
        assert compute_fov_arcmin(530, 3.76, 6248) == pytest.approx(
            6248 * (206.265 * 3.76 / 530) / 60.0
        )
        assert compute_fov_arcmin(None, 3.76, 6248) is None
        assert compute_fov_arcmin(530, None, 6248) is None
        assert compute_fov_arcmin(530, 3.76, None) is None
        assert compute_fov_arcmin(0, 3.76, 6248) is None
        assert compute_fov_arcmin(530, 3.76, 0) is None
        assert compute_fov_arcmin("bad", 3.76, 6248) is None


class TestSqlExpression:
    def test_builds_and_compiles(self):
        from app.models.image import Image
        from sqlalchemy.dialects import postgresql

        expr = sql_arcsec_per_pixel(Image.raw_headers)
        sql = str(expr.compile(dialect=postgresql.dialect()))
        # Regex-guarded cast wrapped in a positivity CASE
        assert "CASE" in sql
        assert "XPIXSZ" in str(expr.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        ))
