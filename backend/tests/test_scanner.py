import pytest
from pathlib import Path
import fitsio
import numpy as np

from app.services.scanner import scan_directory, extract_metadata


def _write_fits(path: Path, data: np.ndarray, header: dict) -> None:
    """Write a FITS file with data and header keys."""
    fits_header = fitsio.FITSHDR()
    for k, v in header.items():
        fits_header.add_record({"name": k, "value": v})
    fitsio.write(str(path), data, header=fits_header, clobber=True)


@pytest.fixture
def fits_tree(tmp_path: Path) -> Path:
    """Create a directory tree with FITS files and non-FITS files."""
    for subdir in ["2024-01-15", "2024-01-16"]:
        d = tmp_path / subdir
        d.mkdir()
        for i in range(3):
            data = np.zeros((64, 64), dtype=np.float32)
            _write_fits(d / f"Light_{i:03d}.fits", data, {
                "OBJECT": "M31",
                "EXPTIME": 300.0,
                "FILTER": "Ha",
                "CCD-TEMP": -10.0,
                "GAIN": 120,
                "DATE-OBS": f"2024-01-{15 + int(subdir[-2:])-15}T22:{i:02d}:00",
            })

    # Non-FITS file (should be ignored)
    (tmp_path / "notes.txt").write_text("session notes")
    return tmp_path


def test_scan_directory_finds_all_fits(fits_tree: Path):
    new_files, all_disk_paths = scan_directory(fits_tree)
    assert len(new_files) == 6
    assert all(f.suffix == ".fits" for f in new_files)
    assert len(all_disk_paths) == 6


def test_scan_directory_excludes_known_paths(fits_tree: Path):
    known = {str(fits_tree / "2024-01-15" / "Light_000.fits")}
    new_files, all_disk_paths = scan_directory(fits_tree, known_paths=known)
    assert len(new_files) == 5
    assert len(all_disk_paths) == 6  # all files still reported on disk


def test_extract_metadata(fits_tree: Path):
    fits_file = fits_tree / "2024-01-15" / "Light_000.fits"
    meta = extract_metadata(fits_file)

    assert meta["file_name"] == "Light_000.fits"
    assert meta["object_name"] == "M31"
    assert meta["exposure_time"] == 300.0
    assert meta["filter_used"] == "Ha"
    assert meta["sensor_temp"] == -10.0
    assert meta["camera_gain"] == 120
    assert "OBJECT" in meta["raw_headers"]
    assert meta["capture_date"] is not None


from unittest.mock import patch, MagicMock
from app.services.scanner import extract_metadata


CSV_COLUMNS = [
    "hfr_stdev", "fwhm", "detected_stars", "guiding_rms_arcsec",
    "guiding_rms_ra_arcsec", "guiding_rms_dec_arcsec", "adu_stdev",
    "adu_mean", "adu_median", "adu_min", "adu_max", "focuser_position",
    "focuser_temp", "rotator_position", "pier_side", "airmass",
    "ambient_temp", "dew_point", "humidity", "pressure", "wind_speed",
    "wind_direction", "wind_gust", "cloud_cover", "sky_quality",
]


def _make_fake_header(fields=None):
    """Return a mock FITS header with sensible defaults."""
    defaults = {
        "DATE-OBS": "2025-06-15T23:30:00",
        "OBJECT": "M31",
        "EXPTIME": 300.0,
        "FILTER": "L",
        "CCD-TEMP": -10.0,
        "GAIN": 100,
        "IMAGETYP": "Light",
        "TELESCOP": "RC8",
        "INSTRUME": "ASI2600MM",
        "HFR": 2.5,
        "ECCENTRICITY": 0.45,
    }
    if fields:
        defaults.update(fields)

    class FakeHeader:
        def __init__(self, data):
            self._data = data

        def get(self, key, default=None):
            return self._data.get(key, default)

        def records(self):
            return [{"name": k, "value": v} for k, v in self._data.items()]

    return FakeHeader(defaults)


def _csv_metrics_full():
    """Return a complete CSV metrics dict with known values."""
    return {
        "median_hfr": 1.8,
        "eccentricity": 0.32,
        "hfr_stdev": 0.12,
        "fwhm": 3.1,
        "detected_stars": 245,
        "guiding_rms_arcsec": 0.65,
        "guiding_rms_ra_arcsec": 0.42,
        "guiding_rms_dec_arcsec": 0.50,
        "adu_stdev": 120.5,
        "adu_mean": 1500.0,
        "adu_median": 1480.0,
        "adu_min": 200.0,
        "adu_max": 55000.0,
        "focuser_position": 12500,
        "focuser_temp": 18.3,
        "rotator_position": 90.0,
        "pier_side": "West",
        "airmass": 1.23,
        "ambient_temp": 15.0,
        "dew_point": 8.0,
        "humidity": 60.0,
        "pressure": 1013.0,
        "wind_speed": 5.0,
        "wind_direction": 180.0,
        "wind_gust": 8.0,
        "cloud_cover": 10.0,
        "sky_quality": 20.5,
    }


@patch("app.services.scanner.get_csv_metrics")
@patch("app.services.scanner.fitsio")
def test_csv_metrics_merged_into_metadata(mock_fitsio, mock_get_csv):
    """CSV metrics are merged into the metadata dict."""
    mock_fitsio.read_header.return_value = _make_fake_header()
    csv_data = _csv_metrics_full()
    mock_get_csv.return_value = csv_data

    result = extract_metadata(Path("/data/M31_Light_300s_L.fits"))

    for col in CSV_COLUMNS:
        assert col in result, f"Missing CSV column: {col}"
        assert result[col] == csv_data[col]


@patch("app.services.scanner.get_csv_metrics")
@patch("app.services.scanner.fitsio")
def test_csv_median_hfr_overrides_fits(mock_fitsio, mock_get_csv):
    """CSV median_hfr takes priority over FITS header HFR."""
    mock_fitsio.read_header.return_value = _make_fake_header({"HFR": 2.5})
    mock_get_csv.return_value = _csv_metrics_full()  # median_hfr = 1.8

    result = extract_metadata(Path("/data/M31_Light_300s_L.fits"))

    assert result["median_hfr"] == 1.8


@patch("app.services.scanner.get_csv_metrics")
@patch("app.services.scanner.fitsio")
def test_csv_eccentricity_overrides_fits(mock_fitsio, mock_get_csv):
    """CSV eccentricity takes priority over FITS header eccentricity."""
    mock_fitsio.read_header.return_value = _make_fake_header({"ECCENTRICITY": 0.45})
    mock_get_csv.return_value = _csv_metrics_full()  # eccentricity = 0.32

    result = extract_metadata(Path("/data/M31_Light_300s_L.fits"))

    assert result["eccentricity"] == 0.32


@patch("app.services.scanner.get_csv_metrics")
@patch("app.services.scanner.fitsio")
def test_fits_values_preserved_when_no_csv(mock_fitsio, mock_get_csv):
    """When no CSV match is found, FITS header values are preserved."""
    mock_fitsio.read_header.return_value = _make_fake_header({"HFR": 2.5, "ECCENTRICITY": 0.45})
    mock_get_csv.return_value = {}

    result = extract_metadata(Path("/data/M31_Light_300s_L.fits"))

    assert result["median_hfr"] == 2.5
    assert result["eccentricity"] == 0.45


@patch("app.services.scanner.get_csv_metrics")
@patch("app.services.scanner.fitsio")
def test_csv_only_fields_present_in_output(mock_fitsio, mock_get_csv):
    """All 25 CSV-only columns appear in the returned dict."""
    mock_fitsio.read_header.return_value = _make_fake_header()
    csv_data = _csv_metrics_full()
    mock_get_csv.return_value = csv_data

    result = extract_metadata(Path("/data/M31_Light_300s_L.fits"))

    for col in CSV_COLUMNS:
        assert col in result, f"CSV-only column missing from output: {col}"
