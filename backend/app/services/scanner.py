import logging
import os
import re
from pathlib import Path
from datetime import datetime
from typing import Any, Iterator

import fitsio

from app.services.csv_metadata import get_csv_metrics
from app.services.scan_filters import ScanFilterConfig

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".fits", ".fit", ".fts", ".FITS", ".FIT", ".FTS", ".xisf", ".XISF"}

# Backwards-compatible alias
FITS_EXTENSIONS = SUPPORTED_EXTENSIONS


CALIBRATION_FRAME_TYPES = {"BIAS", "DARK", "FLAT", "DARKFLAT", "BIASFLAT"}


def _walk_supported_files(
    root: Path,
    filter_config: "ScanFilterConfig | None" = None,
    fits_root: "Path | None" = None,
) -> Iterator[Path]:
    """Yield supported image files using os.scandir for better NFS performance.

    os.scandir batches readdir calls per directory and caches DirEntry.name,
    avoiding the per-entry stat() overhead of Path.rglob on network filesystems.

    When filter_config is provided, subtrees that fail should_walk_dir are
    pruned before descent, and files that fail should_include_file are
    dropped. fits_root is the effective data root used for relative-path
    segment extraction; defaults to root when not provided.
    """
    effective_root = fits_root or root
    try:
        with os.scandir(root) as entries:
            for entry in entries:
                try:
                    if entry.is_dir(follow_symlinks=True):
                        sub = Path(entry.path)
                        if filter_config and not filter_config.should_walk_dir(
                            sub, effective_root
                        ):
                            continue
                        yield from _walk_supported_files(
                            sub, filter_config, effective_root
                        )
                    elif entry.is_file(follow_symlinks=True):
                        # entry.name is already cached - no extra stat
                        _, ext = os.path.splitext(entry.name)
                        if ext not in SUPPORTED_EXTENSIONS:
                            continue
                        path = Path(entry.path)
                        if filter_config and not filter_config.should_include_file(
                            path, effective_root
                        ):
                            continue
                        yield path
                except OSError as exc:
                    # Handle stale NFS handles, permission errors, etc.
                    logger.warning("Skipping inaccessible entry %s: %s", entry.path, exc)
    except OSError as exc:
        logger.warning("Cannot read directory %s: %s", root, exc)


def scan_directory(
    root: Path,
    known_paths: set[str] | None = None,
    known_file_stats: dict[str, tuple[int | None, float | None]] | None = None,
    on_progress: "callable | None" = None,
    is_cancelled: "callable | None" = None,
    on_new_file: "callable | None" = None,
    on_changed_file: "callable | None" = None,
    filter_config: "ScanFilterConfig | None" = None,
    fits_root: "Path | None" = None,
) -> tuple[list[Path], list[Path], set[str]]:
    """Walk a directory tree finding new and changed image files.

    Returns (new_files, changed_files, all_disk_paths) where:
    - new_files: image files not in known_paths
    - changed_files: known files whose size or mtime changed (delta rescan)
    - all_disk_paths: every supported path found during the walk

    Calibration filtering is NOT done here - it's deferred to the ingest phase
    where the file header is already being read for metadata extraction, avoiding
    a redundant file open per candidate (especially costly on NFS).

    known_file_stats maps file_path -> (file_size, file_mtime) for delta detection.
    on_changed_file(path) is called for each changed file, enabling parallel re-ingest.
    """
    known = known_paths or set()
    file_stats = known_file_stats or {}
    new_files: list[Path] = []
    changed_files: list[Path] = []
    all_disk_paths: set[str] = set()
    discovered = 0
    for path in _walk_supported_files(root, filter_config, fits_root or root):
        if is_cancelled and is_cancelled():
            break
        path_str = str(path)
        all_disk_paths.add(path_str)
        if path_str not in known:
            new_files.append(path)
            if on_new_file:
                on_new_file(path)
        elif file_stats:
            # Delta detection: check if known file was modified on disk
            stored = file_stats.get(path_str)
            if stored:
                stored_size, stored_mtime = stored
                try:
                    stat = path.stat()
                    if (stored_size is not None and stat.st_size != stored_size) or \
                       (stored_mtime is not None and abs(stat.st_mtime - stored_mtime) > 1.0):
                        changed_files.append(path)
                        if on_changed_file:
                            on_changed_file(path)
                except OSError:
                    pass
        discovered += 1
        if on_progress and discovered % 50 == 0:
            on_progress(discovered)
    if on_progress:
        on_progress(discovered)
    return new_files, changed_files, all_disk_paths


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


def extract_metadata(fits_path: Path, header=None) -> dict[str, Any]:
    """Extract structured metadata and raw headers from a FITS file.

    If header is provided, skip the file read (avoids redundant I/O when
    the caller already read the header).
    """
    if header is None:
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

    # Merge CSV metrics - CSV values take priority for median_hfr and eccentricity
    csv_metrics = get_csv_metrics(fits_path)
    if csv_metrics:
        metadata.update(csv_metrics)

    return metadata


def _serialize_header_value(value: Any) -> Any:
    """Ensure header values are JSON-serializable."""
    if isinstance(value, (str, int, float, bool, type(None))):
        return value
    return str(value)
