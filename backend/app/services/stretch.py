import numpy as np
from PIL import Image as PILImage


def mtf(x: np.ndarray, m: float) -> np.ndarray:
    """Midtones Transfer Function rational curve.

    f(x) = (m - 1) * x / ((2m - 1) * x - m)
    Equivalent to N.I.N.A. / PixInsight Auto STF.
    """
    return (m - 1.0) * x / ((2.0 * m - 1.0) * x - m)


def normalize_to_unit(data: np.ndarray) -> np.ndarray:
    """Normalize a 2D array to [0, 1] based on its min/max."""
    dmin = float(np.min(data))
    dmax = float(np.max(data))
    if dmax > dmin:
        return (data - dmin) / (dmax - dmin)
    return np.zeros_like(data)


def stretch_channel(data: np.ndarray) -> np.ndarray:
    """Apply N.I.N.A.-equivalent MTF stretch to a single 2D channel.

    Expects `data` already normalized to [0, 1].
    Returns uint8 [0, 255].
    """
    median = float(np.median(data))
    mad = float(np.median(np.abs(data - median)))

    midtone = 0.5
    shadows = 0.0

    if mad > 0:
        shadows = median - 2.8 * mad
        if shadows < 0:
            shadows = 0.0
        if shadows >= 1.0:
            shadows = 0.0

        scale = 1.0 - shadows
        if scale <= 0:
            scale = 1.0
        median_norm = (median - shadows) / scale
        median_norm = float(np.clip(median_norm, 1e-6, 1.0 - 1e-6))

        target = 0.25
        denom = 2.0 * target * median_norm - target - median_norm
        if abs(denom) > 1e-10:
            midtone = median_norm * (target - 1.0) / denom
            midtone = float(np.clip(midtone, 0.001, 0.999))
        else:
            midtone = 0.5

    scale = 1.0 - shadows
    if scale <= 0:
        scale = 1.0
    normed = (data - shadows) / scale
    normed = np.clip(normed, 0.0, 1.0)

    if mad == 0:
        return np.full(data.shape, 128, dtype=np.uint8)

    stretched = mtf(normed, midtone)
    return (stretched * 255).astype(np.uint8)


def resize_array(data: np.ndarray, max_width: int) -> np.ndarray:
    """Resize a 2D float array maintaining aspect ratio using LANCZOS.

    Uses PIL mode "F" for high-quality resampling on linear float data.
    """
    h, w = data.shape
    if w <= max_width:
        return data

    ratio = max_width / w
    new_h = int(h * ratio)

    img = PILImage.fromarray(data, mode="F")
    img = img.resize((max_width, new_h), PILImage.LANCZOS)
    return np.array(img)
