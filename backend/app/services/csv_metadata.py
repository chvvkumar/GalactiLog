"""Parse N.I.N.A. Session Metadata plugin CSV files (ImageMetaData.csv, WeatherData.csv)."""

import csv
import math
import ntpath
import os
from pathlib import Path
from typing import Optional


# mtime-aware cache: re-parses when the CSV file is modified
_cache: dict[str, tuple[float, dict]] = {}  # path -> (mtime, parsed_data)


def _cached_parse(csv_path: Path, parser):
    """Return cached result if file hasn't changed, otherwise re-parse."""
    key = str(csv_path)
    try:
        mtime = os.path.getmtime(csv_path)
    except OSError:
        _cache.pop(key, None)
        return {}

    cached = _cache.get(key)
    if cached and cached[0] == mtime:
        return cached[1]

    result = parser(csv_path)
    _cache[key] = (mtime, result)
    return result


def _float_or_none(value: str) -> Optional[float]:
    """Convert string to float, returning None for NaN or empty strings."""
    if not value or value.strip() == "":
        return None
    try:
        f = float(value)
        if math.isnan(f):
            return None
        return f
    except (ValueError, TypeError):
        return None


def _int_or_none(value: str) -> Optional[int]:
    """Convert string to int, returning None for NaN or empty strings."""
    f = _float_or_none(value)
    if f is None:
        return None
    return int(f)


def _str_or_none(value: str) -> Optional[str]:
    """Return string value, or None for empty/NaN."""
    if not value or value.strip() == "" or value.strip() == "NaN":
        return None
    return value.strip()


IMAGE_COLUMN_MAP: dict[str, tuple[str, callable]] = {
    "HFR":                 ("median_hfr",              _float_or_none),
    "HFRStDev":            ("hfr_stdev",               _float_or_none),
    "FWHM":                ("fwhm",                    _float_or_none),
    "Eccentricity":        ("eccentricity",            _float_or_none),
    "DetectedStars":       ("detected_stars",          _int_or_none),
    "GuidingRMSArcSec":    ("guiding_rms_arcsec",      _float_or_none),
    "GuidingRMSRAArcSec":  ("guiding_rms_ra_arcsec",   _float_or_none),
    "GuidingRMSDECArcSec": ("guiding_rms_dec_arcsec",  _float_or_none),
    "ADUStDev":            ("adu_stdev",               _float_or_none),
    "ADUMean":             ("adu_mean",                _float_or_none),
    "ADUMedian":           ("adu_median",              _float_or_none),
    "ADUMin":              ("adu_min",                 _int_or_none),
    "ADUMax":              ("adu_max",                 _int_or_none),
    "FocuserPosition":     ("focuser_position",        _int_or_none),
    "FocuserTemp":         ("focuser_temp",            _float_or_none),
    "RotatorPosition":     ("rotator_position",        _float_or_none),
    "PierSide":            ("pier_side",               _str_or_none),
    "Airmass":             ("airmass",                 _float_or_none),
}

WEATHER_COLUMN_MAP: dict[str, tuple[str, callable]] = {
    "Temperature":    ("ambient_temp",    _float_or_none),
    "DewPoint":       ("dew_point",       _float_or_none),
    "Humidity":       ("humidity",        _float_or_none),
    "Pressure":       ("pressure",        _float_or_none),
    "WindSpeed":      ("wind_speed",      _float_or_none),
    "WindDirection":  ("wind_direction",  _float_or_none),
    "WindGust":       ("wind_gust",       _float_or_none),
    "CloudCover":     ("cloud_cover",     _float_or_none),
    "SkyQuality":     ("sky_quality",     _float_or_none),
}


def _extract_filename(filepath: str) -> str:
    """Extract the filename from a path string, handling both Windows and Unix separators."""
    return ntpath.basename(filepath)


def _parse_image_csv(csv_path: Path) -> dict[str, dict]:
    """Parse a single ImageMetaData.csv file."""
    result: dict[str, dict] = {}

    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            filepath = row.get("FilePath", "")
            if not filepath:
                continue

            filename = _extract_filename(filepath)
            entry: dict = {}

            for csv_col, (db_col, converter) in IMAGE_COLUMN_MAP.items():
                raw_value = row.get(csv_col, "")
                entry[db_col] = converter(raw_value)

            # HFR == 0.0 means star detection failed in N.I.N.A. — treat as None
            if entry.get("median_hfr") == 0.0:
                entry["median_hfr"] = None

            # Preserve ExposureStartUTC for weather data joining
            exposure_start = row.get("ExposureStartUTC", "")
            if exposure_start:
                entry["_exposure_start_utc"] = exposure_start.strip()

            result[filename] = entry

    return result


def _parse_weather_csv(csv_path: Path) -> dict[str, dict]:
    """Parse a single WeatherData.csv file."""
    result: dict[str, dict] = {}

    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            exposure_start = row.get("ExposureStartUTC", "")
            if not exposure_start:
                continue

            key = exposure_start.strip()
            entry: dict = {}

            for csv_col, (db_col, converter) in WEATHER_COLUMN_MAP.items():
                raw_value = row.get(csv_col, "")
                entry[db_col] = converter(raw_value)

            result[key] = entry

    return result


def parse_image_metadata_csv(directory: Path) -> dict[str, dict]:
    """Parse ImageMetaData.csv from the given directory.

    Returns a dict keyed by filename (last segment of the FilePath column).
    NaN values and HFR == 0.0 are converted to None.
    Results are cached and automatically invalidated when the file is modified.
    """
    csv_path = Path(directory) / "ImageMetaData.csv"
    return _cached_parse(csv_path, _parse_image_csv)


def parse_weather_csv(directory: Path) -> dict[str, dict]:
    """Parse WeatherData.csv from the given directory.

    Returns a dict keyed by ExposureStartUTC (string).
    NaN values are converted to None.
    Results are cached and automatically invalidated when the file is modified.
    """
    csv_path = Path(directory) / "WeatherData.csv"
    return _cached_parse(csv_path, _parse_weather_csv)


def get_csv_metrics(fits_path: Path) -> dict:
    """Look up CSV metrics for a single FITS file.

    Calls parse_image_metadata_csv for the parent directory, matches by filename,
    then joins weather data by matching ExposureStartUTC from the image CSV row.
    Returns a flat dict of all metric fields, or empty dict if no CSV data found.
    """
    fits_path = Path(fits_path)
    directory = fits_path.parent
    filename = fits_path.name

    image_data = parse_image_metadata_csv(directory)
    if filename not in image_data:
        return {}

    entry = dict(image_data[filename])  # shallow copy so we don't mutate cache

    # Join weather data by ExposureStartUTC
    exposure_start = entry.pop("_exposure_start_utc", None)
    if exposure_start:
        weather_data = parse_weather_csv(directory)
        weather_entry = weather_data.get(exposure_start)
        if weather_entry:
            entry.update(weather_entry)

    return entry
