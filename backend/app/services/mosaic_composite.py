from __future__ import annotations

import hashlib
import io
import logging
import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image as PILImage
from sqlalchemy import select, cast, Float
from sqlalchemy.ext.asyncio import AsyncSession
from astropy.wcs import WCS

from app.models.image import Image
from app.services.thumbnail import (
    _read_decimated,
    _normalize_to_unit,
    _resize_array,
    _stretch_channel,
)

logger = logging.getLogger(__name__)


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


def generate_panel_thumbnail(fits_path: Path, max_width: int = 800) -> PILImage.Image:
    """Generate an in-memory PIL Image from a FITS file using MTF stretch.
    Reuses the existing thumbnail pipeline but returns a PIL Image
    instead of saving to disk.
    """
    data = _read_decimated(fits_path, max_width)

    if data.ndim == 2:
        data = _normalize_to_unit(data)
        flipped = np.flipud(data)
        resized = _resize_array(flipped, max_width)
        stretched = _stretch_channel(resized)
        return PILImage.fromarray(stretched, mode="L").convert("RGB")
    elif data.ndim == 3 and data.shape[0] == 3:
        channels = []
        for i in range(3):
            ch = _normalize_to_unit(data[i])
            flipped = np.flipud(ch)
            resized = _resize_array(flipped, max_width)
            stretched = _stretch_channel(resized)
            channels.append(stretched)
        rgb = np.stack(channels, axis=-1)
        return PILImage.fromarray(rgb, mode="RGB")
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
) -> list[LayoutPosition]:
    """Project panel RA/DEC onto a common tangent plane using gnomonic (TAN) projection."""
    if not panels:
        return []

    center_ra = sum(p.ra for p in panels) / len(panels)
    center_dec = sum(p.dec for p in panels) / len(panels)

    ref = panels[0]
    plate_scale_arcsec = (ref.xpixsz / ref.focallen) * 206.265
    plate_scale_deg = plate_scale_arcsec / 3600.0

    w = WCS(naxis=2)
    w.wcs.crpix = [0.0, 0.0]
    w.wcs.crval = [center_ra, center_dec]
    w.wcs.cdelt = [-plate_scale_deg, plate_scale_deg]
    w.wcs.ctype = ["RA---TAN", "DEC--TAN"]

    ref_pierside = ref.pierside

    positions = []
    for p in panels:
        px, py = w.world_to_pixel_values(p.ra, p.dec)
        rotation = p.objctrot - ref.objctrot
        if p.pierside != ref_pierside:
            rotation += 180.0
        rotation = ((rotation + 180.0) % 360.0) - 180.0

        positions.append(LayoutPosition(
            panel_id=p.panel_id,
            x=float(px),
            y=float(py),
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
        max_x = max(max_x, pos.x + rot_w)
        max_y = max(max_y, pos.y + rot_h)

    canvas_w = int(math.ceil(max_x))
    canvas_h = int(math.ceil(max_y))
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

        paste_x = int(pos.x) - (rotated.width - tile.width) // 2
        paste_y = int(pos.y) - (rotated.height - tile.height) // 2

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
    tile_max_width: int = 800,
) -> bytes:
    """Full orchestrator: select frames, check cache, generate composite."""
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
        ra = headers.get("RA") or headers.get("OBJCTRA")
        dec = headers.get("DEC") or headers.get("OBJCTDEC")
        if ra is None or dec is None:
            continue

        info = PanelInfo(
            panel_id=str(panel.id),
            ra=float(ra),
            dec=float(dec),
            objctrot=float(headers.get("OBJCTROT", 0)),
            pierside=str(headers.get("PIERSIDE", "West")),
            fits_path=frame.file_path,
            focallen=float(headers.get("FOCALLEN", 448)),
            xpixsz=float(headers.get("XPIXSZ", 3.76)),
        )
        panel_infos.append(info)

        fits_path = Path(frame.file_path)
        if fits_path.exists():
            try:
                tile_img = generate_panel_thumbnail(fits_path, max_width=tile_max_width)
                tiles[str(panel.id)] = tile_img
            except Exception:
                logger.warning("Failed to generate thumbnail for panel %s", panel.id)

    if not tiles:
        raise ValueError("No panels could be rendered from FITS files")

    sample_tile = next(iter(tiles.values()))
    layout = compute_panel_layout(
        panel_infos,
        tile_width=sample_tile.width,
        tile_height=sample_tile.height,
    )

    composite = composite_panels(tiles, layout)

    buf = io.BytesIO()
    composite.save(buf, "JPEG", quality=90)
    jpeg_bytes = buf.getvalue()

    _set_cached(cache_key, jpeg_bytes)
    return jpeg_bytes
