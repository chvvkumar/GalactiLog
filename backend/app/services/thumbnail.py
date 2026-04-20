from pathlib import Path

import numpy as np
import fitsio
from PIL import Image as PILImage

from app.services.stretch import (
    normalize_to_unit,
    stretch_channel,
    resize_array,
)

_BAYER_OFFSETS = {
    "RGGB": (0, 0),
    "GRBG": (0, 1),
    "GBRG": (1, 0),
    "BGGR": (1, 1),
}


def debayer_superpixel(data: np.ndarray, pattern: str) -> np.ndarray:
    """Debayer a 2D Bayer-patterned array using 2x2 superpixel binning.

    Returns a [3, H//2, W//2] float32 array (channels-first RGB).
    Each 2x2 cell yields one R, one B, and the mean of two G samples.
    """
    pattern = pattern.upper().strip()
    if pattern not in _BAYER_OFFSETS:
        raise ValueError(f"Unknown Bayer pattern: {pattern}")

    r_row, r_col = _BAYER_OFFSETS[pattern]
    b_row = 1 - r_row
    b_col = 1 - r_col

    h = (data.shape[0] // 2) * 2
    w = (data.shape[1] // 2) * 2
    d = data[:h, :w]

    r = d[r_row::2, r_col::2].astype(np.float32)
    b = d[b_row::2, b_col::2].astype(np.float32)
    g = (d[r_row::2, b_col::2].astype(np.float32) +
         d[b_row::2, r_col::2].astype(np.float32)) / 2.0

    return np.stack([r, g, b], axis=0)


def get_bayer_pattern(fits_path: Path) -> str | None:
    """Read BAYERPAT from a FITS header, return None if absent."""
    header = fitsio.read_header(str(fits_path), ext=0)
    pat = header.get("BAYERPAT")
    if pat and str(pat).strip().upper() in _BAYER_OFFSETS:
        return str(pat).strip().upper()
    return None


def _read_binned(fits_path: Path, max_width: int) -> np.ndarray:
    """Read FITS pixel data and block-average-bin for thumbnail generation.

    For large sensors (e.g. 6000x4000), the full frame is read and then
    mean-pooled by an integer factor that leaves ~2x the target width for
    the subsequent LANCZOS step. Block averaging (vs. strided sub-sampling)
    integrates noise across bins, giving sqrt(N) noise reduction per axis
    and eliminating the aliasing/moire that strided reads produce.

    Falls back to full read for small images or non-2D data.
    """
    with fitsio.FITS(str(fits_path), "r") as fits:
        hdu = fits[0]
        info = hdu.get_info()
        dims = info.get("dims", [])

        # Color FITS [3, H, W] or unusual layouts: fall back to full read
        if len(dims) != 2:
            return hdu.read().astype(np.float32)

        data = hdu.read().astype(np.float32)

    h, w = data.shape
    max_dim = max(h, w)
    step = max(1, max_dim // (max_width * 2))
    if step <= 1:
        return data

    h2 = (h // step) * step
    w2 = (w // step) * step
    cropped = data[:h2, :w2]
    binned = cropped.reshape(
        h2 // step, step, w2 // step, step
    ).mean(axis=(1, 3)).astype(np.float32)
    return binned


def generate_thumbnail(
    fits_path: Path,
    output_path: Path,
    max_width: int = 800,
) -> Path:
    """Read a FITS file, resize raw data, apply MTF stretch, save JPEG.

    Pipeline: read → block-bin → flip → resize (raw linear) → MTF stretch → save.
    Handles mono (2D), color (3D [3, H, W]), and Bayer-patterned (2D + BAYERPAT) data.
    """
    bayer = get_bayer_pattern(fits_path)
    if bayer:
        with fitsio.FITS(str(fits_path), "r") as fits:
            raw = fits[0].read().astype(np.float32)
        data = debayer_superpixel(raw, bayer)
    else:
        data = _read_binned(fits_path, max_width)

    if data.ndim == 2:
        # Mono: normalize, flip, resize, stretch
        data = normalize_to_unit(data)
        flipped = np.flipud(data)
        resized = resize_array(flipped, max_width)
        stretched = stretch_channel(resized)
        img = PILImage.fromarray(stretched, mode="L")
    elif data.ndim == 3 and data.shape[0] == 3:
        # Color: normalize, flip, resize, stretch each channel independently (unlinked)
        channels = []
        for i in range(3):
            ch = normalize_to_unit(data[i])
            flipped = np.flipud(ch)
            resized = resize_array(flipped, max_width)
            stretched = stretch_channel(resized)
            channels.append(stretched)
        rgb = np.stack(channels, axis=-1)
        img = PILImage.fromarray(rgb, mode="RGB")
    else:
        raise ValueError(f"Unsupported FITS data shape: {data.shape}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path, "JPEG", quality=85)
    return output_path
