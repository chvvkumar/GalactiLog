import numpy as np
import pytest
import fitsio
from pathlib import Path
from PIL import Image as PILImage

from app.services.thumbnail import (
    generate_thumbnail,
    get_bayer_pattern,
    debayer_superpixel,
    _read_bayer_debayered,
)


@pytest.fixture
def sample_fits_mono(tmp_path: Path) -> Path:
    """Create a minimal mono FITS file with synthetic star field."""
    rng = np.random.default_rng(42)
    data = rng.normal(loc=1000, scale=50, size=(256, 256)).astype(np.float32)
    data[128, 128] = 50000
    data[64, 192] = 30000

    file_path = tmp_path / "test_mono.fits"
    fitsio.write(str(file_path), data, clobber=True)
    return file_path


@pytest.fixture
def sample_fits_bayer(tmp_path: Path) -> Path:
    """Create a 2D Bayer-patterned (RGGB) FITS file.

    Large enough (over 2x max_width used in tests) that the thumbnail path
    exercises binning/decimation rather than a 1:1 read.
    """
    rng = np.random.default_rng(7)
    # 2000x3000 (rows x cols): a realistic OSC sensor, well above 400px.
    data = rng.normal(loc=1000, scale=50, size=(2000, 3000)).astype(np.float32)
    # Bright "star" spanning a full 2x2 Bayer cell so it survives debayering.
    data[1000:1002, 1500:1502] = 50000

    file_path = tmp_path / "test_bayer.fits"
    fitsio.write(str(file_path), data, header={"BAYERPAT": "RGGB"}, clobber=True)
    return file_path


@pytest.fixture
def sample_fits_bayer_odd(tmp_path: Path) -> Path:
    """Create a Bayer FITS with odd, non-square dimensions.

    Odd dims force the (//2)*2 crop in both the strip reader and
    debayer_superpixel; non-square dims (height != width) would expose any
    accidental h/w axis swap in the strip reader.
    """
    rng = np.random.default_rng(11)
    # 2001 rows x 3001 cols: non-square, both axes odd.
    data = rng.normal(loc=1000, scale=50, size=(2001, 3001)).astype(np.float32)
    data[1000:1002, 1500:1502] = 50000

    file_path = tmp_path / "test_bayer_odd.fits"
    fitsio.write(str(file_path), data, header={"BAYERPAT": "GRBG"}, clobber=True)
    return file_path


@pytest.fixture
def sample_fits_color(tmp_path: Path) -> Path:
    """Create a minimal 3-channel color FITS file."""
    rng = np.random.default_rng(42)
    data = rng.normal(loc=1000, scale=50, size=(3, 128, 128)).astype(np.float32)
    data[0, 64, 64] = 40000
    data[1, 64, 64] = 45000
    data[2, 64, 64] = 35000

    file_path = tmp_path / "test_color.fits"
    fitsio.write(str(file_path), data, clobber=True)
    return file_path


def test_generate_thumbnail_mono(sample_fits_mono: Path, tmp_path: Path):
    output = tmp_path / "thumb.jpg"
    result = generate_thumbnail(sample_fits_mono, output, max_width=400)

    assert result == output
    assert output.exists()
    img = PILImage.open(output)
    assert img.width <= 400
    assert img.mode == "L" or img.mode == "RGB"


def test_generate_thumbnail_color(sample_fits_color: Path, tmp_path: Path):
    output = tmp_path / "thumb_color.jpg"
    result = generate_thumbnail(sample_fits_color, output, max_width=400)

    assert result == output
    assert output.exists()
    img = PILImage.open(output)
    assert img.width <= 400
    assert img.mode == "RGB"


def test_generate_thumbnail_respects_max_width(sample_fits_mono: Path, tmp_path: Path):
    output = tmp_path / "thumb_small.jpg"
    generate_thumbnail(sample_fits_mono, output, max_width=100)

    img = PILImage.open(output)
    assert img.width <= 100


def test_mtf_stretch_dark_sky_background(sample_fits_mono: Path, tmp_path: Path):
    """MTF stretch should produce dark sky, not washed-out white."""
    output = tmp_path / "thumb_mtf.jpg"
    generate_thumbnail(sample_fits_mono, output, max_width=256)

    img = PILImage.open(output)
    pixels = np.array(img)
    # Background sky (median) should be dark - below 64 on 0-255 scale
    # The MTF lifts faint signal but keeps background subdued
    assert np.median(pixels) < 64, (
        f"Sky background too bright: median={np.median(pixels):.0f}, "
        f"expected < 64 for proper MTF stretch"
    )


def test_mtf_stretch_star_contrast(sample_fits_mono: Path, tmp_path: Path):
    """MTF stretch should preserve bright stars against dark background."""
    output = tmp_path / "thumb_contrast.jpg"
    generate_thumbnail(sample_fits_mono, output, max_width=256)

    img = PILImage.open(output)
    pixels = np.array(img)
    # Stars (max pixel) should be significantly brighter than background (median)
    contrast = float(np.max(pixels)) - float(np.median(pixels))
    assert contrast > 100, (
        f"Insufficient star/sky contrast: {contrast:.0f}, expected > 100"
    )


def test_mtf_stretch_uniform_image(tmp_path: Path):
    """Uniform image (MAD=0) should produce valid thumbnail without crashing."""
    data = np.full((128, 128), 1000.0, dtype=np.float32)
    fits_path = tmp_path / "uniform.fits"
    fitsio.write(str(fits_path), data, clobber=True)

    output = tmp_path / "thumb_uniform.jpg"
    result = generate_thumbnail(fits_path, output, max_width=128)
    assert result == output
    assert output.exists()
    img = PILImage.open(output)
    assert img.width <= 128
    # With m=0.5 fallback, uniform input should map to mid-grey (not all-black or all-white)
    pixels = np.array(img)
    assert 0 < np.median(pixels) < 255, "Uniform image should not be all-black or all-white"


def test_generate_thumbnail_bayer(sample_fits_bayer: Path, tmp_path: Path):
    """A 2D Bayer frame produces a valid RGB thumbnail within max_width."""
    output = tmp_path / "thumb_bayer.jpg"
    result = generate_thumbnail(sample_fits_bayer, output, max_width=400)

    assert result == output
    assert output.exists()
    img = PILImage.open(output)
    assert img.mode == "RGB"
    # debayer halves each axis; thumbnail still bounded by max_width.
    assert img.width <= 400
    # The injected bright cell should leave a clearly bright region.
    pixels = np.array(img)
    assert int(pixels.max()) - int(np.median(pixels)) > 80


def test_bayer_strip_read_matches_full_debayer(sample_fits_bayer: Path):
    """Strip-based debayer is byte-identical to full read + debayer_superpixel.

    This is the behavior-preserving guarantee behind reading the Bayer frame
    in strips instead of loading the whole sensor at once. The fixture is
    non-square (2000x3000), so an h/w axis swap in the strip reader would
    produce a wrong shape or mismatched values and fail this assertion.
    """
    raw = fitsio.read(str(sample_fits_bayer))
    expected = debayer_superpixel(raw.astype(np.float32), "RGGB")
    actual = _read_bayer_debayered(sample_fits_bayer)
    assert actual.shape == expected.shape
    assert np.array_equal(actual, expected)


def test_bayer_strip_read_matches_full_debayer_odd_dims(sample_fits_bayer_odd: Path):
    """Strip-debayer == full debayer for odd, non-square dimensions.

    Locks the (//2)*2 crop edge case and the row/column axis order.
    """
    raw = fitsio.read(str(sample_fits_bayer_odd))
    expected = debayer_superpixel(raw.astype(np.float32), "GRBG")
    actual = _read_bayer_debayered(sample_fits_bayer_odd)
    assert actual.shape == expected.shape
    assert np.array_equal(actual, expected)


def test_bayer_strip_read_with_supplied_header(sample_fits_bayer: Path):
    """Passing a pre-read header yields the same debayered result as reading it."""
    header = fitsio.read_header(str(sample_fits_bayer), ext=0)
    with_header = _read_bayer_debayered(sample_fits_bayer, header=header)
    without_header = _read_bayer_debayered(sample_fits_bayer)
    assert np.array_equal(with_header, without_header)


def test_get_bayer_pattern_from_disk(sample_fits_bayer: Path):
    """get_bayer_pattern reads BAYERPAT from disk when no header is passed."""
    assert get_bayer_pattern(sample_fits_bayer) == "RGGB"


def test_get_bayer_pattern_from_header(sample_fits_bayer: Path):
    """get_bayer_pattern uses a supplied header without reopening the file."""
    header = fitsio.read_header(str(sample_fits_bayer), ext=0)
    # Passing the header must yield the same result as the disk read.
    assert get_bayer_pattern(sample_fits_bayer, header=header) == "RGGB"


def test_get_bayer_pattern_none_for_mono(sample_fits_mono: Path):
    """A frame without BAYERPAT returns None whether reading disk or header."""
    assert get_bayer_pattern(sample_fits_mono) is None
    header = fitsio.read_header(str(sample_fits_mono), ext=0)
    assert get_bayer_pattern(sample_fits_mono, header=header) is None
