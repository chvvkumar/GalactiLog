from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from PIL import Image as PILImage

from app.services.preview import generate_preview


def _make_fits_mock(data: np.ndarray) -> MagicMock:
    """Build a fitsio.FITS context manager mock that returns `data` on read."""
    hdu = MagicMock()
    hdu.read.return_value = data
    fits_obj = MagicMock()
    fits_obj.__enter__ = MagicMock(return_value=fits_obj)
    fits_obj.__exit__ = MagicMock(return_value=False)
    fits_obj.__getitem__ = MagicMock(return_value=hdu)
    return fits_obj


@pytest.fixture
def mono_data() -> np.ndarray:
    """Deterministic 2D mono FITS data (600 H x 800 W)."""
    rng = np.random.default_rng(42)
    return (rng.random((600, 800)) * 65535).astype(np.uint16)


@pytest.fixture
def color_data() -> np.ndarray:
    """Deterministic 3D color FITS data [3, 400, 600]."""
    rng = np.random.default_rng(7)
    return (rng.random((3, 400, 600)) * 65535).astype(np.uint16)


def test_generate_preview_writes_jpeg_at_requested_width(mono_data, tmp_path):
    out = tmp_path / "preview.jpg"
    fits_mock = _make_fits_mock(mono_data)
    with patch("app.services.preview.fitsio.FITS", return_value=fits_mock):
        generate_preview(tmp_path / "synth.fits", out, max_width=400)
    assert out.exists()
    with PILImage.open(out) as img:
        assert img.format == "JPEG"
        assert img.width == 400


def test_generate_preview_native_when_zero(mono_data, tmp_path):
    out = tmp_path / "preview_native.jpg"
    fits_mock = _make_fits_mock(mono_data)
    with patch("app.services.preview.fitsio.FITS", return_value=fits_mock):
        generate_preview(tmp_path / "synth.fits", out, max_width=0)
    assert out.exists()
    with PILImage.open(out) as img:
        assert img.width == 800  # native sensor width
        assert img.height == 600


def test_generate_preview_color_produces_rgb_jpeg(color_data, tmp_path):
    out = tmp_path / "color_preview.jpg"
    fits_mock = _make_fits_mock(color_data)
    with patch("app.services.preview.fitsio.FITS", return_value=fits_mock):
        generate_preview(tmp_path / "synth_color.fits", out, max_width=300)
    assert out.exists()
    with PILImage.open(out) as img:
        assert img.format == "JPEG"
        assert img.mode == "RGB"
        assert img.width == 300


def test_generate_preview_raises_on_unsupported_shape(tmp_path):
    data = np.zeros((2, 10, 10, 10), dtype=np.uint16)  # 4D not supported
    out = tmp_path / "out.jpg"
    fits_mock = _make_fits_mock(data)
    with patch("app.services.preview.fitsio.FITS", return_value=fits_mock):
        with pytest.raises(ValueError, match="Unsupported FITS data shape"):
            generate_preview(tmp_path / "bad.fits", out, max_width=100)
