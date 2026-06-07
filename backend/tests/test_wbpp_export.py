import pytest
from app.services.wbpp_export import detect_os, translate_path


def test_detect_os_windows_drive():
    assert detect_os("Z:\\Astro") == "windows"

def test_detect_os_windows_backslash():
    assert detect_os("\\\\server\\share\\Astro") == "windows"

def test_detect_os_posix():
    assert detect_os("/mnt/astro") == "posix"

def test_translate_posix():
    assert translate_path(
        "/app/data/fits/M31/2024-01-01/Light/x.fits",
        "/app/data/fits", "/mnt/astro", "posix",
    ) == "/mnt/astro/M31/2024-01-01/Light/x.fits"

def test_translate_windows():
    assert translate_path(
        "/app/data/fits/M31/2024-01-01/Light/x.fits",
        "/app/data/fits", "Z:\\Astro", "windows",
    ) == "Z:\\Astro\\M31\\2024-01-01\\Light\\x.fits"

def test_translate_raises_for_wrong_root():
    with pytest.raises(ValueError, match="does not start with fits_root"):
        translate_path("/other/path/x.fits", "/app/data/fits", "/mnt/astro", "posix")

def test_translate_strips_trailing_slash_from_root():
    assert translate_path(
        "/app/data/fits/M31/x.fits", "/app/data/fits/", "/mnt/astro/", "posix",
    ) == "/mnt/astro/M31/x.fits"
