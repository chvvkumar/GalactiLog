import numpy as np
import pytest
import fitsio
from pathlib import Path
from PIL import Image as PILImage

from app.services.thumbnail import generate_thumbnail


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
    # Background sky (median) should be dark — below 64 on 0-255 scale
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
