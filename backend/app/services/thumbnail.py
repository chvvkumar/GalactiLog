from pathlib import Path

import numpy as np
import fitsio
from PIL import Image as PILImage

from app.services.stretch import (
    normalize_to_unit,
    stretch_channel,
    resize_array,
)


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
    Handles both mono (2D) and color (3D with shape [3, H, W]) data.

    Block-binning before resize integrates noise across bins (sqrt(N) reduction
    per axis) and prevents the aliasing that strided reads cause.
    """
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
