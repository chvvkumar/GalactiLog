import numpy as np

from app.services.stretch import (
    mtf,
    normalize_to_unit,
    stretch_channel,
    resize_array,
)


def test_mtf_identity_at_midtone_half():
    # f(x) with m=0.5 → (m-1)x / ((2m-1)x - m) = (-0.5 x) / (0 - 0.5) = x
    x = np.array([0.0, 0.25, 0.5, 0.75, 1.0])
    out = mtf(x, 0.5)
    np.testing.assert_allclose(out, x, atol=1e-9)


def test_normalize_to_unit_range():
    data = np.array([[100.0, 200.0], [300.0, 400.0]])
    out = normalize_to_unit(data)
    assert out.min() == 0.0
    assert out.max() == 1.0


def test_normalize_uniform_returns_zeros():
    data = np.full((3, 3), 500.0)
    out = normalize_to_unit(data)
    assert np.all(out == 0.0)


def test_stretch_channel_mono_produces_uint8():
    data = np.random.default_rng(0).random((64, 64)).astype(np.float32)
    data = normalize_to_unit(data)
    out = stretch_channel(data)
    assert out.dtype == np.uint8
    assert out.shape == (64, 64)


def test_resize_array_downscales_preserves_aspect():
    data = np.zeros((400, 800), dtype=np.float32)
    out = resize_array(data, max_width=200)
    assert out.shape == (100, 200)


def test_resize_array_noop_when_smaller():
    data = np.zeros((50, 100), dtype=np.float32)
    out = resize_array(data, max_width=200)
    assert out.shape == (50, 100)


def test_stretch_channel_uniform_returns_midgrey():
    data = np.full((32, 32), 0.5, dtype=np.float32)
    out = stretch_channel(data)
    assert out.dtype == np.uint8
    assert np.all(out == 128)
