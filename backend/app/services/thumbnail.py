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


def get_bayer_pattern(fits_path: Path, header=None) -> str | None:
    """Read BAYERPAT from a FITS header, return None if absent.

    If ``header`` is provided (an already-read FITS header), it is used
    directly so the file is not opened a second time. Otherwise the header
    is read from disk.
    """
    if header is None:
        header = fitsio.read_header(str(fits_path), ext=0)
    pat = header.get("BAYERPAT")
    if pat and str(pat).strip().upper() in _BAYER_OFFSETS:
        return str(pat).strip().upper()
    return None


def _read_bayer_debayered(fits_path: Path, header=None) -> np.ndarray:
    """Read a 2D Bayer frame in row strips and superpixel-debayer it.

    Reading the sensor one horizontal strip at a time, debayering each strip,
    and concatenating the half-resolution channels avoids ever holding the
    full raw frame and the full debayered result in memory at the same time.
    The output is byte-identical to ``debayer_superpixel(fits[0].read(), ...)``
    because every strip starts on an even row, preserving the 2x2 Bayer phase.

    ``header`` may be a header the caller already read; it is used to resolve
    the Bayer pattern so the file is not opened an extra time.

    Returns a [3, H//2, W//2] float32 array (channels-first RGB).
    """
    with fitsio.FITS(str(fits_path), "r") as fits:
        hdu = fits[0]
        # Resolve the pattern from the caller-supplied header when available,
        # else from the HDU header read in this same open.
        if header is None:
            header = hdu.read_header()
        pattern = get_bayer_pattern(fits_path, header=header)
        if pattern is None:
            # Callers only invoke this for Bayer data, so a missing/invalid
            # BAYERPAT here is a genuine error, not something to silently
            # mis-debayer with a raw header value.
            raise ValueError(
                f"No valid BAYERPAT in FITS header for {fits_path}"
            )

        info = hdu.get_info()
        dims = info.get("dims", [])
        if len(dims) != 2:
            # Not a plain 2D sensor frame: fall back to full read + debayer.
            return debayer_superpixel(hdu.read().astype(np.float32), pattern)

        # Per-pattern Bayer offsets, matching debayer_superpixel: R sits at
        # (r_row, r_col) within each 2x2 cell, B at the diagonal opposite, and
        # the two G samples at the off-diagonal corners.
        r_row, r_col = _BAYER_OFFSETS[pattern]
        b_row = 1 - r_row
        b_col = 1 - r_col

        # fitsio reads images as C-order NumPy arrays of shape (NAXIS2, NAXIS1)
        # = (height, width), and get_info()["dims"] mirrors that array shape.
        # So dims[0] is the row count (height) and dims[1] the column count
        # (width); hdu[rows, cols] slices in the same (height, width) order.
        h = (dims[0] // 2) * 2  # height (rows)
        w = (dims[1] // 2) * 2  # width (columns)

        # Strip height must be even so each strip begins on a Bayer phase
        # boundary (an even absolute row), making concatenation equivalent
        # to debayering the whole frame at once.
        strip_rows = 512
        r_parts: list[np.ndarray] = []
        g_parts: list[np.ndarray] = []
        b_parts: list[np.ndarray] = []
        r0 = 0
        while r0 < h:
            r1 = min(r0 + strip_rows, h)
            d = hdu[r0:r1, 0:w].astype(np.float32)
            r_parts.append(d[r_row::2, r_col::2])
            b_parts.append(d[b_row::2, b_col::2])
            g_parts.append(
                (d[r_row::2, b_col::2] + d[b_row::2, r_col::2]) / 2.0
            )
            r0 = r1

    r = np.concatenate(r_parts, axis=0)
    g = np.concatenate(g_parts, axis=0)
    b = np.concatenate(b_parts, axis=0)
    return np.stack([r, g, b], axis=0)


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
    header = fitsio.read_header(str(fits_path), ext=0)
    bayer = get_bayer_pattern(fits_path, header=header)
    if bayer:
        # Strip-read + debayer to avoid loading the full sensor frame and the
        # full debayered result simultaneously. resize_array (below) still
        # receives the identical debayered channels, so output is unchanged.
        # Reuse the header already read above so the file isn't reopened.
        data = _read_bayer_debayered(fits_path, header=header)
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
