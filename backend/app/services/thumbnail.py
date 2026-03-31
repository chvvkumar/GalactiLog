from pathlib import Path

import numpy as np
import fitsio
from PIL import Image as PILImage


def _mtf(x: np.ndarray, m: float) -> np.ndarray:
    """Apply Midtones Transfer Function (MTF) rational curve.

    f(x) = (m - 1) * x / ((2m - 1) * x - m)

    Equivalent to N.I.N.A. / PixInsight Auto STF.
    """
    return (m - 1.0) * x / ((2.0 * m - 1.0) * x - m)


def _stretch_channel(data: np.ndarray) -> np.ndarray:
    """Apply N.I.N.A.-equivalent MTF stretch to a single 2D channel.

    Expects data already normalized to [0, 1] via _normalize_to_unit.

    Algorithm:
    1. Compute median and MAD (Median Absolute Deviation)
    2. Calculate shadows clipping point and midtone balance
    3. Apply MTF rational curve
    """
    median = float(np.median(data))
    mad = float(np.median(np.abs(data - median)))

    # Default midtone for uniform images (MAD=0): map 0.5 input to mid-grey
    midtone = 0.5
    shadows = 0.0

    if mad > 0:
        # Shadows clipping: 2.8 is N.I.N.A. default autostretch factor
        shadows = median - 2.8 * mad
        if shadows < 0:
            shadows = 0.0
        if shadows >= 1.0:
            shadows = 0.0

        # Compute normalized median position within [shadows, 1]
        scale = 1.0 - shadows
        if scale <= 0:
            scale = 1.0
        median_norm = (median - shadows) / scale
        median_norm = float(np.clip(median_norm, 1e-6, 1.0 - 1e-6))

        # Solve MTF inverse: find m so that f(median_norm) = target_background (0.25)
        # From f(x) = (m-1)*x / ((2m-1)*x - m) = t, solving for m:
        # m = x*(t - 1) / (2*t*x - t - x)
        target = 0.25
        denom = 2.0 * target * median_norm - target - median_norm
        if abs(denom) > 1e-10:
            midtone = median_norm * (target - 1.0) / denom
            midtone = float(np.clip(midtone, 0.001, 0.999))
        else:
            midtone = 0.5

    # Normalize to [0, 1] relative to shadows..1.0 range
    scale = 1.0 - shadows
    if scale <= 0:
        scale = 1.0
    normed = (data - shadows) / scale
    normed = np.clip(normed, 0.0, 1.0)

    # Uniform images: after _normalize_to_unit, all pixels become 0.
    # MTF(0, m) = 0 for any m, so return mid-grey directly instead.
    if mad == 0:
        return np.full(data.shape, 128, dtype=np.uint8)

    # Apply MTF rational curve
    stretched = _mtf(normed, midtone)
    return (stretched * 255).astype(np.uint8)


def _normalize_to_unit(data: np.ndarray) -> np.ndarray:
    """Normalize a 2D array to [0, 1] range based on its min/max.

    Required because raw FITS ADU values can be in the thousands;
    the MTF shadows/midtone math expects [0, 1] input.
    """
    dmin = float(np.min(data))
    dmax = float(np.max(data))
    if dmax > dmin:
        return (data - dmin) / (dmax - dmin)
    return np.zeros_like(data)


def _resize_array(data: np.ndarray, max_width: int) -> np.ndarray:
    """Resize a 2D float array maintaining aspect ratio using LANCZOS.

    Uses PIL mode "F" (32-bit float) for high-quality resampling
    on raw linear float data without precision loss.
    """
    h, w = data.shape
    if w <= max_width:
        return data

    ratio = max_width / w
    new_h = int(h * ratio)

    img = PILImage.fromarray(data, mode="F")
    img = img.resize((max_width, new_h), PILImage.LANCZOS)
    return np.array(img)


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

        # Use the larger dimension for step calculation — fitsio dims order
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

    Uses decimated reads for large images to reduce I/O — for a 6000px wide
    sensor targeting 800px thumbnails, this reads ~16x fewer pixels from disk.
    """
    data = _read_decimated(fits_path, max_width)

    if data.ndim == 2:
        # Mono: normalize, flip, resize, stretch
        data = _normalize_to_unit(data)
        flipped = np.flipud(data)
        resized = _resize_array(flipped, max_width)
        stretched = _stretch_channel(resized)
        img = PILImage.fromarray(stretched, mode="L")
    elif data.ndim == 3 and data.shape[0] == 3:
        # Color: normalize, flip, resize, stretch each channel independently (unlinked)
        channels = []
        for i in range(3):
            ch = _normalize_to_unit(data[i])
            flipped = np.flipud(ch)
            resized = _resize_array(flipped, max_width)
            stretched = _stretch_channel(resized)
            channels.append(stretched)
        rgb = np.stack(channels, axis=-1)
        img = PILImage.fromarray(rgb, mode="RGB")
    else:
        raise ValueError(f"Unsupported FITS data shape: {data.shape}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path, "JPEG", quality=85)
    return output_path
