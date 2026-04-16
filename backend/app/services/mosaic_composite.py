from __future__ import annotations

import hashlib
import io
import logging
import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import fitsio
import numpy as np
from PIL import Image as PILImage
from sqlalchemy import select, cast, Float
from sqlalchemy.ext.asyncio import AsyncSession
from astropy.wcs import WCS

from app.models.image import Image
from app.services.activity import emit as _emit_activity
from app.services.thumbnail import _read_binned
from app.services.stretch import (
    normalize_to_unit,
    resize_array,
    stretch_channel,
)

logger = logging.getLogger(__name__)


def _parse_coord(value) -> float | None:
    """Parse a coordinate value that may be numeric or sexagesimal.

    Handles:
    - Numeric (float/int): returned directly
    - RA sexagesimal 'HH MM SS.s': converted to degrees (* 15)
    - DEC sexagesimal '[+-]DD MM SS.s': converted to degrees
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    try:
        return float(s)
    except ValueError:
        pass
    # Sexagesimal parsing
    parts = s.lstrip("+-").split()
    if len(parts) != 3:
        return None
    try:
        d, m, sec = float(parts[0]), float(parts[1]), float(parts[2])
        deg = d + m / 60 + sec / 3600
        if s.startswith("-"):
            deg = -deg
        return deg
    except (ValueError, IndexError):
        return None


def _parse_ra(value) -> float | None:
    """Parse RA - if sexagesimal (HH MM SS), multiply by 15 for degrees."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    try:
        return float(s)
    except ValueError:
        pass
    parts = s.split()
    if len(parts) != 3:
        return None
    try:
        h, m, sec = float(parts[0]), float(parts[1]), float(parts[2])
        return (h + m / 60 + sec / 3600) * 15
    except (ValueError, IndexError):
        return None


def score_frames(frames: list) -> list[tuple[Any, float]]:
    """Score frames by quality metrics, returning (frame, score) pairs sorted best-first.

    Metrics and weights:
      detected_stars  0.35  (higher is better)
      median_hfr      0.30  (lower is better)
      eccentricity    0.15  (lower is better)
      guiding_rms     0.12  (lower is better)
      fwhm            0.08  (lower is better)

    Each metric is min-max normalised within the provided frame pool.
    Missing values receive a neutral 0.5.
    """
    if not frames:
        return []
    if len(frames) == 1:
        return [(frames[0], 1.0)]

    METRICS = [
        # (attr, weight, higher_is_better)
        ("detected_stars",      0.35, True),
        ("median_hfr",          0.30, False),
        ("eccentricity",        0.15, False),
        ("guiding_rms_arcsec",  0.12, False),
        ("fwhm",                0.08, False),
    ]

    # Collect raw values per metric
    raw: dict[str, list[float | None]] = {}
    for attr, _, _ in METRICS:
        raw[attr] = [getattr(f, attr, None) for f in frames]

    # Normalise each metric to 0-1
    normalised: dict[str, list[float]] = {}
    for attr, _, higher_is_better in METRICS:
        vals = raw[attr]
        nums = [v for v in vals if v is not None and v > 0]
        if len(nums) < 2:
            normalised[attr] = [0.5] * len(frames)
            continue
        lo, hi = min(nums), max(nums)
        span = hi - lo if hi != lo else 1.0
        result = []
        for v in vals:
            if v is None or v <= 0:
                result.append(0.5)
            else:
                n = (v - lo) / span
                result.append(n if higher_is_better else 1.0 - n)
        normalised[attr] = result

    # Weighted sum
    scored = []
    for i, frame in enumerate(frames):
        total = sum(
            normalised[attr][i] * weight
            for attr, weight, _ in METRICS
        )
        scored.append((frame, total))

    scored.sort(key=lambda x: x[1], reverse=True)
    return scored


async def select_best_frame(
    target_id,
    object_pattern: str | None,
    session: AsyncSession,
):
    """Select the best LIGHT frame for a mosaic panel.
    Primary: lowest median_hfr > 0.
    Fallback: highest CENTALT (closest to zenith).
    """
    base_filter = [
        Image.resolved_target_id == target_id,
        Image.image_type == "LIGHT",
        Image.file_path.isnot(None),
    ]
    if object_pattern:
        base_filter.append(Image.raw_headers["OBJECT"].astext.ilike(object_pattern))

    # Try best HFR first
    hfr_q = (
        select(Image)
        .where(*base_filter, Image.median_hfr > 0)
        .order_by(Image.median_hfr.asc())
        .limit(1)
    )
    row = (await session.execute(hfr_q)).scalars().first()
    if row:
        return row

    # Fallback: highest altitude
    alt_q = (
        select(Image)
        .where(*base_filter)
        .where(Image.raw_headers["CENTALT"].astext.cast(Float).isnot(None))
        .order_by(Image.raw_headers["CENTALT"].astext.cast(Float).desc())
        .limit(1)
    )
    row = (await session.execute(alt_q)).scalars().first()
    return row


def generate_panel_thumbnail(
    fits_path: Path, max_width: int = 800,
) -> tuple[PILImage.Image, int]:
    """Generate an in-memory PIL Image from a FITS file using MTF stretch.

    Returns (image, native_width) where native_width is the original sensor
    width in pixels before any downscaling.
    """
    # Read native dimensions before decimation
    with fitsio.FITS(str(fits_path), "r") as fits:
        info = fits[0].get_info()
        dims = info.get("dims", [])
        # dims is [NAXIS1, NAXIS2] for 2D (NAXIS1=width), [3, H, W] for color
        if len(dims) == 2:
            native_width = dims[0]  # NAXIS1 = width
        elif len(dims) == 3:
            native_width = dims[2]
        else:
            native_width = max(dims) if dims else max_width

    data = _read_binned(fits_path, max_width)

    if data.ndim == 2:
        data = normalize_to_unit(data)
        flipped = np.flipud(data)
        resized = resize_array(flipped, max_width)
        stretched = stretch_channel(resized)
        img = PILImage.fromarray(stretched, mode="L").convert("RGB")
        return img, native_width
    elif data.ndim == 3 and data.shape[0] == 3:
        channels = []
        for i in range(3):
            ch = normalize_to_unit(data[i])
            flipped = np.flipud(ch)
            resized = resize_array(flipped, max_width)
            stretched = stretch_channel(resized)
            channels.append(stretched)
        rgb = np.stack(channels, axis=-1)
        img = PILImage.fromarray(rgb, mode="RGB")
        return img, native_width
    else:
        raise ValueError(f"Unsupported FITS data shape: {data.shape}")


@dataclass
class PanelInfo:
    panel_id: str
    ra: float
    dec: float
    objctrot: float
    pierside: str
    fits_path: str
    focallen: float
    xpixsz: float


@dataclass
class LayoutPosition:
    panel_id: str
    x: float
    y: float
    rotation: float
    fits_path: str


def compute_panel_layout(
    panels: list[PanelInfo],
    tile_width: int,
    tile_height: int,
    scale: float = 1.0,
) -> list[LayoutPosition]:
    """Project panel RA/DEC onto a common tangent plane using gnomonic (TAN) projection.

    The WCS projects at native sensor plate scale. The `scale` parameter
    converts from native pixels to thumbnail pixels (tile_width / native_width).
    """
    if not panels:
        return []

    center_ra = sum(p.ra for p in panels) / len(panels)
    center_dec = sum(p.dec for p in panels) / len(panels)

    ref = panels[0]
    plate_scale_arcsec = (ref.xpixsz / ref.focallen) * 206.265
    plate_scale_deg = plate_scale_arcsec / 3600.0

    # Include camera rotation (OBJCTROT) in WCS via CD matrix so that
    # panel positions match the camera's field of view, not North-up sky.
    theta = math.radians(ref.objctrot)
    cos_t = math.cos(theta)
    sin_t = math.sin(theta)

    w = WCS(naxis=2)
    w.wcs.crpix = [0.0, 0.0]
    w.wcs.crval = [center_ra, center_dec]
    w.wcs.cd = [
        [-plate_scale_deg * cos_t, -plate_scale_deg * sin_t],
        [-plate_scale_deg * sin_t,  plate_scale_deg * cos_t],
    ]
    w.wcs.ctype = ["RA---TAN", "DEC--TAN"]

    ref_pierside = ref.pierside

    positions = []
    for p in panels:
        px, py = w.world_to_pixel_values(p.ra, p.dec)
        # Scale from native sensor pixels to thumbnail pixels
        # Negate X: the synthetic WCS cdelt1 is negative (standard sky
        # parity), which puts East to the left in pixel coords; negating
        # flips to match the camera's actual view where East pier side
        # images are mirrored.  Y stays as-is because the CD matrix
        # rotation already maps +DEC → correct screen direction.
        px = float(-px) * scale
        py = float(py) * scale

        rotation = p.objctrot - ref.objctrot
        if p.pierside != ref_pierside:
            rotation += 180.0
        rotation = ((rotation + 180.0) % 360.0) - 180.0

        positions.append(LayoutPosition(
            panel_id=p.panel_id,
            x=px,
            y=py,
            rotation=rotation,
            fits_path=p.fits_path,
        ))

    if positions:
        diag = math.sqrt(tile_width**2 + tile_height**2) / 2
        min_x = min(pos.x for pos in positions) - diag
        min_y = min(pos.y for pos in positions) - diag
        for pos in positions:
            pos.x -= min_x
            pos.y -= min_y

    return positions


def composite_panels(
    tiles: dict[str, PILImage.Image],
    layout: list[LayoutPosition],
) -> PILImage.Image:
    """Composite panel tiles onto a single canvas at their layout positions."""
    if not layout or not tiles:
        raise ValueError("No panels to composite")

    # Compute bounding box of all placed tiles
    min_x = float("inf")
    min_y = float("inf")
    max_x = 0.0
    max_y = 0.0
    for pos in layout:
        tile = tiles.get(pos.panel_id)
        if not tile:
            continue
        w, h = tile.size
        angle_rad = math.radians(abs(pos.rotation))
        rot_w = w * abs(math.cos(angle_rad)) + h * abs(math.sin(angle_rad))
        rot_h = w * abs(math.sin(angle_rad)) + h * abs(math.cos(angle_rad))
        tx = pos.x - (rot_w - w) / 2
        ty = pos.y - (rot_h - h) / 2
        min_x = min(min_x, tx)
        min_y = min(min_y, ty)
        max_x = max(max_x, tx + rot_w)
        max_y = max(max_y, ty + rot_h)

    content_w = max_x - min_x
    content_h = max_y - min_y
    canvas_w = int(math.ceil(content_w))
    canvas_h = int(math.ceil(content_h))
    # Offset to center content: shift all positions so content starts at (0, 0)
    offset_x = -min_x
    offset_y = -min_y
    canvas = PILImage.new("RGB", (canvas_w, canvas_h), color=(0, 0, 0))

    for pos in layout:
        tile = tiles.get(pos.panel_id)
        if not tile:
            continue

        if abs(pos.rotation) > 0.1:
            rotated = tile.rotate(
                -pos.rotation,
                resample=PILImage.BICUBIC,
                expand=True,
            )
        else:
            rotated = tile

        paste_x = int(pos.x + offset_x) - (rotated.width - tile.width) // 2
        paste_y = int(pos.y + offset_y) - (rotated.height - tile.height) // 2

        mask = rotated.convert("L").point(lambda p: 255 if p > 0 else 0)
        canvas.paste(rotated, (paste_x, paste_y), mask=mask)

    return canvas


# Module-level cache
_composite_cache: dict[str, tuple[float, bytes]] = {}
_CACHE_TTL = 3600


def _compute_cache_key(mosaic_id: str, frame_ids: list) -> str:
    raw = f"{mosaic_id}:" + ",".join(str(fid) for fid in sorted(str(f) for f in frame_ids))
    return hashlib.sha256(raw.encode()).hexdigest()


def _get_cached(cache_key: str) -> bytes | None:
    entry = _composite_cache.get(cache_key)
    if entry is None:
        return None
    ts, data = entry
    if time.time() - ts > _CACHE_TTL:
        del _composite_cache[cache_key]
        return None
    return data


def _set_cached(cache_key: str, data: bytes) -> None:
    _composite_cache[cache_key] = (time.time(), data)


async def build_mosaic_composite(
    mosaic_id: str,
    panels: list,
    session: AsyncSession,
    tile_max_width: int = 400,
) -> bytes:
    """Full orchestrator: select frames, check cache, generate composite."""
    try:
        panel_frames = []
        for panel in panels:
            frame = await select_best_frame(panel.target_id, panel.object_pattern, session)
            if frame and frame.file_path:
                panel_frames.append((panel, frame))

        if not panel_frames:
            raise ValueError("No panels have accessible FITS frames")

        frame_ids = [f.id for _, f in panel_frames]
        cache_key = _compute_cache_key(mosaic_id, frame_ids)
        cached = _get_cached(cache_key)
        if cached:
            return cached

        panel_infos = []
        tiles = {}
        for panel, frame in panel_frames:
            headers = frame.raw_headers or {}
            ra_raw = headers.get("RA") or headers.get("OBJCTRA")
            dec_raw = headers.get("DEC") or headers.get("OBJCTDEC")
            ra = _parse_ra(ra_raw)
            dec = _parse_coord(dec_raw)
            if ra is None or dec is None:
                continue

            pid = str(panel.id)
            fits_path = Path(frame.file_path)
            if not fits_path.exists():
                continue
            try:
                tile_img, native_width = generate_panel_thumbnail(fits_path, max_width=tile_max_width)
                tiles[pid] = tile_img
            except Exception:
                logger.warning("Failed to generate thumbnail for panel %s", panel.id)
                continue

            panel_infos.append(PanelInfo(
                panel_id=pid,
                ra=ra,
                dec=dec,
                objctrot=float(headers.get("OBJCTROT", 0)),
                pierside=str(headers.get("PIERSIDE", "West")),
                fits_path=frame.file_path,
                focallen=float(headers.get("FOCALLEN", 448)),
                xpixsz=float(headers.get("XPIXSZ", 3.76)),
            ))

        if not tiles:
            raise ValueError("No panels could be rendered from FITS files")

        sample_tile = next(iter(tiles.values()))
        # Scale factor: thumbnail pixels / native sensor pixels
        thumb_scale = sample_tile.width / native_width if native_width > 0 else 1.0
        layout = compute_panel_layout(
            panel_infos,
            tile_width=sample_tile.width,
            tile_height=sample_tile.height,
            scale=thumb_scale,
        )

        composite = composite_panels(tiles, layout)

        buf = io.BytesIO()
        composite.save(buf, "JPEG", quality=90)
        jpeg_bytes = buf.getvalue()

        _set_cached(cache_key, jpeg_bytes)
        return jpeg_bytes
    except Exception as exc:
        logger.error("mosaic_composite: failed - %s", exc, exc_info=True)
        try:
            await _emit_activity(
                session,
                category="mosaic",
                severity="error",
                event_type="mosaic_composite_failed",
                message=f"Mosaic composite generation failed: {exc}",
                details={"error": str(exc), "mosaic_id": str(mosaic_id)},
                actor="system",
            )
        except Exception:
            pass
        raise
