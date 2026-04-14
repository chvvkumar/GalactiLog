from pathlib import Path

import numpy as np
import fitsio
from PIL import Image as PILImage

from app.services.stretch import (
    normalize_to_unit,
    stretch_channel,
    resize_array,
)


def _read_decimated(fits_path: Path, max_width: int) -> np.ndarray:
    """Read FITS pixel data with decimation for thumbnail generation.

    For large sensors (e.g., 6000x4000), reading every Nth row/column
    cuts I/O by N^2 while producing more data than the final thumbnail needs.
    The subsequent LANCZOS resize handles the remaining downscale cleanly.

    Falls back to full read for small images or color (3D) data.
    """
    with fitsio.FITS(str(fits_path), "r") as fits:
        hdu = fits[0]
        info = hdu.get_info()
        dims = info.get("dims", [])

        # Color FITS [3, H, W] or unusual layouts: fall back to full read
        if len(dims) != 2:
            return hdu.read().astype(np.float32)

        # Use the larger dimension for step calculation - fitsio dims order
        # may vary (NAXIS1/NAXIS2), and we just need a proportional decimation.
        max_dim = max(dims)
        step = max(1, max_dim // (max_width * 2))

        if step <= 1:
            return hdu.read().astype(np.float32)

        # Read every step-th row and column via numpy slicing on FITS data
        data = hdu[::step, ::step].astype(np.float32)
        return data


def generate_thumbnail(
    fits_path: Path,
    output_path: Path,
    max_width: int = 800,
) -> Path:
    """Read a FITS file, resize raw data, apply MTF stretch, save JPEG.

    Pipeline: read (decimated) → flip → resize (raw linear) → MTF stretch → save.
    Handles both mono (2D) and color (3D with shape [3, H, W]) data.

    Uses decimated reads for large images to reduce I/O - for a 6000px wide
    sensor targeting 800px thumbnails, this reads ~16x fewer pixels from disk.
    """
    data = _read_decimated(fits_path, max_width)

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
