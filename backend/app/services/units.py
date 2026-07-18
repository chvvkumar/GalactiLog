"""Pixel-to-angular unit conversions (the plate-scale spine).

Plate scale in arcseconds per pixel is:

    arcsec/px = 206.265 * XPIXSZ(um) / FOCALLEN(mm)

This formula previously lived twice in the mosaic code
(mosaic_detection.compute_fov_arcmin, mosaic_composite.compute_panel_layout)
and is now extracted here so every surface that needs to compare pixel-domain
star metrics (HFR, FWHM) across optical trains converts through the same
helper.

Binning caveat: XPIXSZ is assumed to be the binned-effective pixel size.
N.I.N.A. writes XPIXSZ that way (physical pixel size multiplied by the binning
factor), so no XBINNING correction is applied. If a file from another capture
application exposes XBINNING alongside a clearly unbinned XPIXSZ, no
correction is attempted here; that is out of scope and the value converts
as-is.
"""

from sqlalchemy import Float, and_, case, cast

# 206265 arcsec per radian, divided by 1000 to reconcile um vs mm.
ARCSEC_FACTOR = 206.265

# Anchored float literal (optionally signed, decimal, scientific notation).
# Guards the SQL cast: FITS header values live in JSONB as text, and a bare
# ::float cast aborts the whole query on any non-numeric string.
_SQL_FLOAT_RE = r"^\s*[+-]?([0-9]+(\.[0-9]*)?|\.[0-9]+)([eE][+-]?[0-9]+)?\s*$"


def arcsec_per_pixel(xpixsz_um, focallen_mm) -> float | None:
    """Plate scale in arcsec/px, or None if either input is missing/invalid.

    Inputs may be numbers or numeric strings (FITS headers store text).
    Returns None for None, non-numeric, or non-positive values.
    """
    try:
        x = float(xpixsz_um)
        f = float(focallen_mm)
    except (TypeError, ValueError):
        return None
    if x <= 0 or f <= 0:
        return None
    return ARCSEC_FACTOR * x / f


def to_arcsec(value_px, xpixsz_um, focallen_mm) -> float | None:
    """Convert a pixel-domain value (HFR, FWHM) to arcseconds.

    Returns None when the value or the plate scale is unavailable.
    """
    scale = arcsec_per_pixel(xpixsz_um, focallen_mm)
    if value_px is None or scale is None:
        return None
    try:
        return float(value_px) * scale
    except (TypeError, ValueError):
        return None


def plate_scale_from_headers(raw_headers: dict | None) -> float | None:
    """Plate scale from a raw FITS header dict (XPIXSZ + FOCALLEN keys)."""
    if not raw_headers:
        return None
    return arcsec_per_pixel(raw_headers.get("XPIXSZ"), raw_headers.get("FOCALLEN"))


# ---------------------------------------------------------------------------
# SQL expression builders (for aggregations that must stay in the database).
# ---------------------------------------------------------------------------

def sql_header_float(raw_headers_col, key: str):
    """SQL expression: raw_headers->>key as float, NULL when non-numeric."""
    txt = raw_headers_col[key].astext
    return case((txt.op("~")(_SQL_FLOAT_RE), cast(txt, Float)), else_=None)


def sql_arcsec_per_pixel(raw_headers_col):
    """SQL expression for the plate scale of a row, NULL when underivable."""
    x = sql_header_float(raw_headers_col, "XPIXSZ")
    f = sql_header_float(raw_headers_col, "FOCALLEN")
    return case((and_(x > 0, f > 0), ARCSEC_FACTOR * x / f), else_=None)
