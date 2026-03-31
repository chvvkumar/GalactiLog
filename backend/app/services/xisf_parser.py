"""XISF file metadata extraction.

Parses the XML header of monolithic XISF files to extract metadata
compatible with the existing FITS ingest pipeline. Uses stdlib XML
parsing for metadata (no GPL dependency); the `xisf` PyPI library
is used only for pixel data reading in thumbnail generation.

XISF Spec: https://pixinsight.com/doc/docs/XISF-1.0-spec/XISF-1.0-spec.html
"""
import re
import struct
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image as PILImage

from app.services.csv_metadata import get_csv_metrics
from app.services.thumbnail import _normalize_to_unit, _resize_array, _stretch_channel

XISF_SIGNATURE = b"XISF0100"
XISF_NS = "http://www.pixinsight.com/xisf"

_HFR_PATTERN = re.compile(r"(\d+\.\d+)HFR", re.IGNORECASE)

# Mapping from XISF native properties to FITS keyword equivalents
_XISF_PROPERTY_MAP = {
    "Observation:Object:Name": "OBJECT",
    "Instrument:ExposureTime": "EXPTIME",
    "Instrument:Filter:Name": "FILTER",
    "Instrument:Sensor:Temperature": "CCD-TEMP",
    "Instrument:Camera:Gain": "GAIN",
    "Instrument:Telescope:Name": "TELESCOP",
    "Instrument:Camera:Name": "INSTRUME",
    "Observation:Time:Start": "DATE-OBS",
}


def _parse_xisf_header(path: Path) -> ET.Element:
    """Read and parse the XML header from a monolithic XISF file."""
    with open(path, "rb") as f:
        sig = f.read(8)
        if sig != XISF_SIGNATURE:
            raise ValueError(f"Not a valid XISF file: {path}")
        header_len = struct.unpack("<I", f.read(4))[0]
        f.read(4)  # reserved
        xml_bytes = f.read(header_len)
    return ET.fromstring(xml_bytes)


def _strip_fits_string(value: str) -> str:
    """Strip surrounding quotes from FITS keyword string values."""
    value = value.strip()
    if len(value) >= 2 and value[0] == "'" and value[-1] == "'":
        return value[1:-1].strip()
    return value


def _parse_fits_keywords(image_elem: ET.Element) -> dict[str, str]:
    """Extract FITSKeyword elements into a {name: value} dict."""
    keywords = {}
    for kw in image_elem.findall(f"{{{XISF_NS}}}FITSKeyword"):
        name = kw.get("name", "").strip()
        value = kw.get("value", "").strip()
        if name:
            keywords[name] = _strip_fits_string(value)
    return keywords


def _parse_xisf_properties(image_elem: ET.Element) -> dict[str, str]:
    """Extract Property elements into a {id: value} dict."""
    properties = {}
    for prop in image_elem.findall(f"{{{XISF_NS}}}Property"):
        prop_id = prop.get("id", "").strip()
        value = prop.get("value")
        if value is None:
            value = prop.text or ""
        if prop_id:
            properties[prop_id] = value.strip()
    return properties


def _first_float(*values) -> float | None:
    """Return the first value that can be parsed as a float."""
    for v in values:
        if v is not None:
            try:
                return float(v)
            except (ValueError, TypeError):
                continue
    return None


def _parse_capture_date(date_str: str | None) -> datetime | None:
    """Parse a date string from FITS keyword or XISF TimePoint."""
    if not date_str:
        return None
    try:
        return datetime.fromisoformat(date_str)
    except ValueError:
        return None


def extract_xisf_metadata(xisf_path: Path) -> dict[str, Any]:
    """Extract structured metadata and raw headers from an XISF file.

    Returns a dict with the same keys as scanner.extract_metadata()
    so downstream code is format-agnostic.

    Strategy:
    1. Parse FITSKeyword elements (present in N.I.N.A./SGPro files)
    2. Parse native XISF Property elements
    3. FITSKeywords take priority; Properties fill gaps
    """
    root = _parse_xisf_header(xisf_path)
    image_elem = root.find(f"{{{XISF_NS}}}Image")
    if image_elem is None:
        raise ValueError(f"No Image element in XISF header: {xisf_path}")

    fits_kw = _parse_fits_keywords(image_elem)
    xisf_props = _parse_xisf_properties(image_elem)

    # Build a merged keyword dict: FITS keywords first, then XISF properties
    # mapped to their FITS equivalents (only filling gaps)
    merged = dict(fits_kw)
    for prop_id, fits_name in _XISF_PROPERTY_MAP.items():
        if fits_name not in merged and prop_id in xisf_props:
            merged[fits_name] = xisf_props[prop_id]

    # imageType attribute on <Image> element as fallback for IMAGETYP
    if "IMAGETYP" not in merged:
        image_type_attr = image_elem.get("imageType")
        if image_type_attr:
            merged["IMAGETYP"] = image_type_attr

    # Build raw_headers: all FITS keywords + all XISF properties
    raw_headers: dict[str, Any] = {}
    for k, v in fits_kw.items():
        raw_headers[k] = v
    for k, v in xisf_props.items():
        raw_headers[k] = v

    # Parse gain as int
    gain_val = merged.get("GAIN")
    camera_gain = None
    if gain_val is not None:
        try:
            camera_gain = int(float(gain_val))
        except (ValueError, TypeError):
            pass

    # HFR from headers or filename
    hfr = _first_float(merged.get("HFR"), merged.get("MEANFWHM"), merged.get("FWHM"))
    if hfr is None:
        m = _HFR_PATTERN.search(xisf_path.name)
        if m:
            hfr = float(m.group(1))

    metadata = {
        "file_path": str(xisf_path),
        "file_name": xisf_path.name,
        "object_name": merged.get("OBJECT"),
        "exposure_time": _first_float(merged.get("EXPTIME")),
        "filter_used": merged.get("FILTER"),
        "sensor_temp": _first_float(merged.get("CCD-TEMP")),
        "camera_gain": camera_gain,
        "image_type": merged.get("IMAGETYP"),
        "telescope": merged.get("TELESCOP"),
        "camera": merged.get("INSTRUME"),
        "median_hfr": hfr,
        "eccentricity": _first_float(
            merged.get("ECCENTRICITY"), merged.get("ELLIPTICITY")
        ),
        "capture_date": _parse_capture_date(merged.get("DATE-OBS")),
        "raw_headers": raw_headers,
    }

    # Merge CSV metrics (same as FITS path)
    csv_metrics = get_csv_metrics(xisf_path)
    if csv_metrics:
        metadata.update(csv_metrics)

    return metadata


def generate_xisf_thumbnail(
    xisf_path: Path,
    output_path: Path,
    max_width: int = 800,
) -> Path:
    """Read an XISF file, resize raw data, apply MTF stretch, save JPEG.

    Uses the `xisf` PyPI library for pixel data reading.
    Reuses the MTF stretch pipeline from thumbnail.py.
    """
    from xisf import XISF

    xobj = XISF(str(xisf_path))
    data = xobj.read_image(0).astype(np.float32)

    # xisf library returns channels-last [H, W, C] for color, [H, W] for mono
    if data.ndim == 2:
        data = _normalize_to_unit(data)
        resized = _resize_array(data, max_width)
        stretched = _stretch_channel(resized)
        img = PILImage.fromarray(stretched, mode="L")
    elif data.ndim == 3 and data.shape[2] == 3:
        # Channels-last [H, W, 3] — process each channel independently
        channels = []
        for i in range(3):
            ch = _normalize_to_unit(data[:, :, i])
            resized = _resize_array(ch, max_width)
            stretched = _stretch_channel(resized)
            channels.append(stretched)
        rgb = np.stack(channels, axis=-1)
        img = PILImage.fromarray(rgb, mode="RGB")
    elif data.ndim == 3 and data.shape[0] == 3:
        # Channels-first [3, H, W] fallback
        channels = []
        for i in range(3):
            ch = _normalize_to_unit(data[i])
            resized = _resize_array(ch, max_width)
            stretched = _stretch_channel(resized)
            channels.append(stretched)
        rgb = np.stack(channels, axis=-1)
        img = PILImage.fromarray(rgb, mode="RGB")
    else:
        raise ValueError(f"Unsupported XISF data shape: {data.shape}")

    # No vertical flip — XISF uses top-left origin (unlike FITS)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path, "JPEG", quality=85)
    return output_path
