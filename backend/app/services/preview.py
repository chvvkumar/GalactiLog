from pathlib import Path

import numpy as np
import fitsio
from PIL import Image as PILImage

from app.services.stretch import normalize_to_unit, stretch_channel, resize_array


def generate_preview(
    fits_path: Path,
    output_path: Path,
    max_width: int,
) -> Path:
    """Render a full-resolution MTF-stretched JPEG preview from a FITS file.

    Unlike thumbnail generation, does not decimate on read. Reads the full
    frame and resizes to `max_width`. If `max_width <= 0`, writes at native
    sensor resolution.

    Pipeline: read -> normalize -> flip -> resize (raw linear) -> MTF stretch -> save.
    Handles mono (2D) and color (3D [3, H, W]) data.
    """
    with fitsio.FITS(str(fits_path), "r") as fits:
        data = fits[0].read().astype(np.float32)

    effective_width: int | None = None
    if max_width and max_width > 0:
        effective_width = max_width

    if data.ndim == 2:
        data = normalize_to_unit(data)
        flipped = np.flipud(data)
        resized = flipped if effective_width is None else resize_array(flipped, effective_width)
        stretched = stretch_channel(resized)
        img = PILImage.fromarray(stretched, mode="L")
    elif data.ndim == 3 and data.shape[0] == 3:
        channels = []
        for i in range(3):
            ch = normalize_to_unit(data[i])
            flipped = np.flipud(ch)
            resized = flipped if effective_width is None else resize_array(flipped, effective_width)
            stretched = stretch_channel(resized)
            channels.append(stretched)
        rgb = np.stack(channels, axis=-1)
        img = PILImage.fromarray(rgb, mode="RGB")
    else:
        raise ValueError(f"Unsupported FITS data shape: {data.shape}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path, "JPEG", quality=85)
    return output_path
