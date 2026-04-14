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


def test_resize_array_prefilter_reduces_noise():
    # Large downscale (7.5x) with uniform random noise: the box-average
    # prefilter should reduce output variance relative to the input.
    rng = np.random.default_rng(42)
    data = rng.standard_normal((4000, 6000)).astype(np.float32)
    out = resize_array(data, max_width=800)
    assert out.shape[1] == 800
    # Block averaging by factor 7 cuts stddev by ~sqrt(49)=7. Allow slack
    # for the fractional LANCZOS step, but it must be far below 1.0.
    assert out.std() < 0.25


def test_resize_array_integer_downscale_uses_prefilter_only():
    # For exact integer downscales, the prefilter alone reaches target width
    # and the function returns without invoking LANCZOS.
    data = np.ones((400, 800), dtype=np.float32)
    out = resize_array(data, max_width=200)
    assert out.shape == (100, 200)
    np.testing.assert_allclose(out, 1.0, atol=1e-6)


def test_stretch_channel_uniform_returns_midgrey():
    data = np.full((32, 32), 0.5, dtype=np.float32)
    out = stretch_channel(data)
    assert out.dtype == np.uint8
    assert np.all(out == 128)
