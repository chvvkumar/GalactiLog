import re
from pathlib import Path
from datetime import datetime
from typing import Any, Iterator

import fitsio

from app.services.csv_metadata import get_csv_metrics

FITS_EXTENSIONS = {".fits", ".fit", ".fts", ".FITS", ".FIT", ".FTS"}


CALIBRATION_FRAME_TYPES = {"BIAS", "DARK", "FLAT", "DARKFLAT", "BIASFLAT"}


def _is_calibration_frame(path: Path) -> bool | None:
    """Quick-check the IMAGETYP header to decide if this is a calibration frame.

    Returns True for calibration, False for light/science, None if unreadable.
    """
    try:
        header = fitsio.read_header(str(path), ext=0)
        image_type = (header.get("IMAGETYP") or "").strip().upper()
        return image_type in CALIBRATION_FRAME_TYPES
    except Exception:
        return None


def scan_directory(
    root: Path,
    known_paths: set[str] | None = None,
    include_calibration: bool = True,
    on_progress: "callable | None" = None,
    is_cancelled: "callable | None" = None,
) -> tuple[list[Path], set[str]]:
    """Walk a directory tree finding new FITS files and all FITS paths on disk.

    Returns (new_files, all_disk_paths) where new_files are FITS files not in
    known_paths and all_disk_paths is every FITS path found during the walk.
    If include_calibration is False, only LIGHT / science frames are in new_files.

    on_progress(discovered_count) is called periodically during discovery.
    is_cancelled() should return True to abort the scan early.
    """
    known = known_paths or set()
    new_files: list[Path] = []
    all_disk_paths: set[str] = set()
    discovered = 0
    for path in root.rglob("*"):
        if is_cancelled and is_cancelled():
            break
        if path.suffix in FITS_EXTENSIONS:
            all_disk_paths.add(str(path))
            if str(path) not in known:
                if not include_calibration:
                    is_cal = _is_calibration_frame(path)
                    if is_cal is True:
                        continue
                new_files.append(path)
            discovered += 1
            if on_progress and discovered % 50 == 0:
                on_progress(discovered)
    if on_progress:
        on_progress(discovered)
    return new_files, all_disk_paths


def _first_float(header, *keys) -> float | None:
    """Return the first non-None float value found among the given header keys."""
    for key in keys:
        val = header.get(key)
        if val is not None:
            try:
                return float(val)
            except (ValueError, TypeError):
                continue
    return None


_HFR_PATTERN = re.compile(r"(\d+\.\d+)HFR", re.IGNORECASE)


def _parse_hfr_from_filename(filename: str) -> float | None:
    """Extract HFR from N.I.N.A. filename pattern like '1.56HFR'."""
    m = _HFR_PATTERN.search(filename)
    if m:
        return float(m.group(1))
    return None


def extract_metadata(fits_path: Path) -> dict[str, Any]:
    """Extract structured metadata and raw headers from a FITS file."""
    header = fitsio.read_header(str(fits_path), ext=0)

    raw_headers = {
        rec["name"]: _serialize_header_value(rec["value"])
        for rec in header.records()
        if rec["name"].strip()
    }

    capture_date = None
    date_obs = header.get("DATE-OBS")
    if date_obs:
        try:
            capture_date = datetime.fromisoformat(date_obs)
        except ValueError:
            pass

    metadata = {
        "file_path": str(fits_path),
        "file_name": fits_path.name,
        "object_name": header.get("OBJECT"),
        "exposure_time": header.get("EXPTIME"),
        "filter_used": header.get("FILTER"),
        "sensor_temp": header.get("CCD-TEMP"),
        "camera_gain": int(header.get("GAIN")) if header.get("GAIN") is not None else None,
        "image_type": header.get("IMAGETYP"),
        "telescope": header.get("TELESCOP"),
        "camera": header.get("INSTRUME"),
        "median_hfr": _first_float(header, "HFR", "MEANFWHM", "FWHM") or _parse_hfr_from_filename(fits_path.name),
        "eccentricity": _first_float(header, "ECCENTRICITY", "ELLIPTICITY"),
        "capture_date": capture_date,
        "raw_headers": raw_headers,
    }

    # Merge CSV metrics — CSV values take priority for median_hfr and eccentricity
    csv_metrics = get_csv_metrics(fits_path)
    if csv_metrics:
        metadata.update(csv_metrics)

    return metadata


def _serialize_header_value(value: Any) -> Any:
    """Ensure header values are JSON-serializable."""
    if isinstance(value, (str, int, float, bool, type(None))):
        return value
    return str(value)
