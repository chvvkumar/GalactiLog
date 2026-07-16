"""Ingest-side provenance and CSV-merge safety.

Covers three related ingest behaviours:

1. A present-but-blank CSV cell must never null a real header-derived value
   (the CSV parser emits None for every mapped column it cannot parse, and a
   blind ``metadata.update(csv_metrics)`` turned that None into data loss).
2. ``eccentricity_source`` records which of three non-comparable origins the
   stored eccentricity came from: a native ECCENTRICITY header, a value derived
   from ELLIPTICITY, or the N.I.N.A. CSV.
3. ``altitude_deg`` is captured from OBJCTALT/CENTALT so eccentricity can later
   be read against the atmospheric-dispersion term it is contaminated by.
"""
import math
import struct
from pathlib import Path
from unittest.mock import patch

import pytest

from app.services.csv_metadata import merge_csv_metrics
from app.services.scanner import extract_metadata
from app.services.xisf_parser import extract_xisf_metadata


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_fake_header(fields=None, drop=()):
    """Return a mock FITS header with sensible defaults."""
    defaults = {
        "DATE-OBS": "2025-06-15T23:30:00",
        "OBJECT": "M31",
        "EXPTIME": 300.0,
        "FILTER": "L",
        "IMAGETYP": "Light",
        "HFR": 2.5,
        "ECCENTRICITY": 0.45,
    }
    if fields:
        defaults.update(fields)
    for key in drop:
        defaults.pop(key, None)

    class FakeHeader:
        def __init__(self, data):
            self._data = data

        def get(self, key, default=None):
            return self._data.get(key, default)

        def records(self):
            return [{"name": k, "value": v} for k, v in self._data.items()]

    return FakeHeader(defaults)


def _blank_csv_metrics(**overrides):
    """CSV metrics as the parser really emits them: every mapped column present.

    Blank cells convert to None, which is exactly the shape that used to
    clobber header values.
    """
    metrics = {
        "median_hfr": None,
        "eccentricity": None,
        "hfr_stdev": None,
        "fwhm": None,
        "detected_stars": None,
        "guiding_rms_arcsec": None,
        "guiding_rms_ra_arcsec": None,
        "guiding_rms_dec_arcsec": None,
        "adu_stdev": None,
        "adu_mean": None,
        "adu_median": None,
        "adu_min": None,
        "adu_max": None,
        "focuser_position": None,
        "focuser_temp": None,
        "rotator_position": None,
        "pier_side": None,
        "airmass": None,
    }
    metrics.update(overrides)
    return metrics


def _make_xisf_bytes(xml_header: str) -> bytes:
    header_bytes = xml_header.encode("utf-8")
    return b"XISF0100" + struct.pack("<I", len(header_bytes)) + b"\x00\x00\x00\x00" + header_bytes


def _xisf_header(keywords: dict) -> str:
    kws = "\n".join(
        f'    <FITSKeyword name="{k}" value="{v}" comment=""/>'
        for k, v in keywords.items()
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<xisf version="1.0" xmlns="http://www.pixinsight.com/xisf">\n'
        '  <Image geometry="1024:768:1" sampleFormat="UInt16" imageType="Light"\n'
        '         location="attachment:4096:1572864">\n'
        f"{kws}\n"
        "  </Image>\n"
        "</xisf>"
    )


def _write_xisf(tmp_path: Path, keywords: dict, name: str = "frame.xisf") -> Path:
    path = tmp_path / name
    path.write_bytes(_make_xisf_bytes(_xisf_header(keywords)))
    return path


# ---------------------------------------------------------------------------
# merge_csv_metrics (Task 1 spine)
# ---------------------------------------------------------------------------


class TestMergeCsvMetrics:
    def test_blank_csv_value_does_not_clobber_existing_value(self):
        metadata = {"median_hfr": 2.5, "eccentricity": 0.45}
        merge_csv_metrics(metadata, {"median_hfr": None, "eccentricity": None})
        assert metadata["median_hfr"] == 2.5
        assert metadata["eccentricity"] == 0.45

    def test_real_csv_value_takes_priority_over_existing_value(self):
        metadata = {"median_hfr": 2.5, "eccentricity": 0.45}
        merge_csv_metrics(metadata, {"median_hfr": 1.8, "eccentricity": 0.32})
        assert metadata["median_hfr"] == 1.8
        assert metadata["eccentricity"] == 0.32

    def test_csv_only_columns_are_still_set_when_blank(self):
        # CSV-only fields (weather/guiding) have no header counterpart; a blank
        # cell must still land the key as None, exactly as before the fix.
        metadata = {}
        merge_csv_metrics(metadata, {"humidity": None, "sky_quality": 20.5})
        assert metadata["humidity"] is None
        assert metadata["sky_quality"] == 20.5

    def test_csv_eccentricity_stamps_csv_source(self):
        metadata = {"eccentricity": 0.45, "eccentricity_source": "header"}
        merge_csv_metrics(metadata, {"eccentricity": 0.32})
        assert metadata["eccentricity"] == 0.32
        assert metadata["eccentricity_source"] == "csv"

    def test_blank_csv_eccentricity_leaves_header_source(self):
        metadata = {"eccentricity": 0.45, "eccentricity_source": "header"}
        merge_csv_metrics(metadata, {"eccentricity": None})
        assert metadata["eccentricity"] == 0.45
        assert metadata["eccentricity_source"] == "header"


# ---------------------------------------------------------------------------
# FITS scanner
# ---------------------------------------------------------------------------


@patch("app.services.scanner.get_csv_metrics")
@patch("app.services.scanner.fitsio")
class TestScannerCsvBlankOverwrite:
    def test_blank_csv_cells_do_not_null_header_metrics(self, mock_fitsio, mock_get_csv):
        mock_fitsio.read_header.return_value = _make_fake_header()
        mock_get_csv.return_value = _blank_csv_metrics()

        meta = extract_metadata(Path("/data/M31_Light_300s_L.fits"))

        assert meta["median_hfr"] == 2.5
        assert meta["eccentricity"] == 0.45
        assert meta["eccentricity_source"] == "header"

    def test_real_csv_cells_still_win(self, mock_fitsio, mock_get_csv):
        mock_fitsio.read_header.return_value = _make_fake_header()
        mock_get_csv.return_value = _blank_csv_metrics(median_hfr=1.8, eccentricity=0.32)

        meta = extract_metadata(Path("/data/M31_Light_300s_L.fits"))

        assert meta["median_hfr"] == 1.8
        assert meta["eccentricity"] == 0.32
        assert meta["eccentricity_source"] == "csv"


@patch("app.services.scanner.get_csv_metrics", return_value={})
@patch("app.services.scanner.fitsio")
class TestScannerEccentricitySource:
    def test_native_header_source(self, mock_fitsio, _mock_csv):
        mock_fitsio.read_header.return_value = _make_fake_header()
        meta = extract_metadata(Path("/data/a.fits"))
        assert meta["eccentricity"] == 0.45
        assert meta["eccentricity_source"] == "header"

    def test_ellipticity_derived_source(self, mock_fitsio, _mock_csv):
        mock_fitsio.read_header.return_value = _make_fake_header(
            {"ELLIPTICITY": 0.3}, drop=("ECCENTRICITY",)
        )
        meta = extract_metadata(Path("/data/a.fits"))
        assert meta["eccentricity"] == pytest.approx(math.sqrt(1 - 0.7 ** 2))
        assert meta["eccentricity_source"] == "ellipticity"

    def test_no_eccentricity_means_no_source(self, mock_fitsio, _mock_csv):
        mock_fitsio.read_header.return_value = _make_fake_header(
            drop=("ECCENTRICITY",)
        )
        meta = extract_metadata(Path("/data/a.fits"))
        assert meta["eccentricity"] is None
        assert meta["eccentricity_source"] is None


@patch("app.services.scanner.get_csv_metrics", return_value={})
@patch("app.services.scanner.fitsio")
class TestScannerAltitude:
    def test_reads_objctalt(self, mock_fitsio, _mock_csv):
        mock_fitsio.read_header.return_value = _make_fake_header({"OBJCTALT": 61.2})
        meta = extract_metadata(Path("/data/a.fits"))
        assert meta["altitude_deg"] == pytest.approx(61.2)

    def test_falls_back_to_centalt(self, mock_fitsio, _mock_csv):
        mock_fitsio.read_header.return_value = _make_fake_header({"CENTALT": 33.7})
        meta = extract_metadata(Path("/data/a.fits"))
        assert meta["altitude_deg"] == pytest.approx(33.7)

    def test_objctalt_wins_over_centalt(self, mock_fitsio, _mock_csv):
        mock_fitsio.read_header.return_value = _make_fake_header(
            {"OBJCTALT": 61.2, "CENTALT": 33.7}
        )
        meta = extract_metadata(Path("/data/a.fits"))
        assert meta["altitude_deg"] == pytest.approx(61.2)

    def test_absent_altitude_is_none(self, mock_fitsio, _mock_csv):
        mock_fitsio.read_header.return_value = _make_fake_header()
        meta = extract_metadata(Path("/data/a.fits"))
        assert meta["altitude_deg"] is None


# ---------------------------------------------------------------------------
# XISF parser
# ---------------------------------------------------------------------------


class TestXisfProvenanceAndAltitude:
    @patch("app.services.xisf_parser.get_csv_metrics")
    def test_blank_csv_cells_do_not_null_header_metrics(self, mock_get_csv, tmp_path):
        mock_get_csv.return_value = _blank_csv_metrics()
        path = _write_xisf(tmp_path, {"HFR": 2.5, "ECCENTRICITY": 0.45})

        meta = extract_xisf_metadata(path)

        assert meta["median_hfr"] == 2.5
        assert meta["eccentricity"] == 0.45
        assert meta["eccentricity_source"] == "header"

    @patch("app.services.xisf_parser.get_csv_metrics")
    def test_csv_eccentricity_marked_as_csv(self, mock_get_csv, tmp_path):
        mock_get_csv.return_value = _blank_csv_metrics(eccentricity=0.32)
        path = _write_xisf(tmp_path, {"ECCENTRICITY": 0.45})

        meta = extract_xisf_metadata(path)

        assert meta["eccentricity"] == 0.32
        assert meta["eccentricity_source"] == "csv"

    @patch("app.services.xisf_parser.get_csv_metrics", return_value={})
    def test_ellipticity_derived_source(self, _mock_csv, tmp_path):
        path = _write_xisf(tmp_path, {"ELLIPTICITY": 0.3})

        meta = extract_xisf_metadata(path)

        assert meta["eccentricity"] == pytest.approx(math.sqrt(1 - 0.7 ** 2))
        assert meta["eccentricity_source"] == "ellipticity"

    @patch("app.services.xisf_parser.get_csv_metrics", return_value={})
    def test_altitude_from_objctalt_then_centalt(self, _mock_csv, tmp_path):
        p1 = _write_xisf(tmp_path, {"OBJCTALT": 61.2, "CENTALT": 33.7}, "a.xisf")
        p2 = _write_xisf(tmp_path, {"CENTALT": 33.7}, "b.xisf")
        p3 = _write_xisf(tmp_path, {"OBJECT": "M31"}, "c.xisf")

        assert extract_xisf_metadata(p1)["altitude_deg"] == pytest.approx(61.2)
        assert extract_xisf_metadata(p2)["altitude_deg"] == pytest.approx(33.7)
        assert extract_xisf_metadata(p3)["altitude_deg"] is None
