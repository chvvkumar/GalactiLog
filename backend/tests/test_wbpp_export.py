import pytest
from app.services.wbpp_export import detect_os, translate_path
from app.services.wbpp_export import (
    compute_ancestor_chain, longest_common_ancestor,
    compute_session_levels, pick_default_level, FolderLevel,
)


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


def test_compute_ancestor_chain_single_filter():
    assert compute_ancestor_chain(
        "/app/data/fits/M31/2024-01-01/Light/frame.fits", "/app/data/fits",
    ) == [
        "/app/data/fits/M31",
        "/app/data/fits/M31/2024-01-01",
        "/app/data/fits/M31/2024-01-01/Light",
    ]

def test_longest_common_ancestor_multi_filter():
    assert longest_common_ancestor([
        "/app/data/fits/M31/2024-01-01/Ha/f1.fits",
        "/app/data/fits/M31/2024-01-01/OIII/f2.fits",
    ]) == "/app/data/fits/M31/2024-01-01"

def test_compute_session_levels_flags_contamination():
    all_paths = {
        ("M31", "2024-01-01"): ["/app/data/fits/M31/2024-01-01/Light/a.fits"],
        ("M31", "2024-01-02"): ["/app/data/fits/M31/2024-01-02/Light/b.fits"],
    }
    levels = compute_session_levels(
        "2024-01-01", ["/app/data/fits/M31/2024-01-01/Light/a.fits"],
        all_paths, "/app/data/fits", "/mnt/a", "posix",
    )
    # shallowest-first: M31 (contaminated by 2024-01-02), date, Light
    assert levels[0].container_path == "/app/data/fits/M31"
    assert levels[0].is_contaminated is True
    assert "2024-01-02" in levels[0].other_dates
    assert levels[1].is_contaminated is False  # the date folder

def test_pick_default_prefers_non_contaminated():
    levels = [
        FolderLevel("/mnt/a/M31", "/fits/M31", 1, 10, other_dates=["2024-01-02"], is_contaminated=True),
        FolderLevel("/mnt/a/M31/2024-01-01", "/fits/M31/2024-01-01", 2, 10, is_contaminated=False),
        FolderLevel("/mnt/a/M31/2024-01-01/Light", "/fits/M31/2024-01-01/Light", 3, 8, is_contaminated=False),
    ]
    assert pick_default_level(levels) == 1

def test_pick_default_falls_back_when_all_contaminated():
    levels = [
        FolderLevel("/mnt/a/M31", "/fits/M31", 1, 10, other_dates=["x"], is_contaminated=True),
        FolderLevel("/mnt/a/M31/2024-01-01", "/fits/M31/2024-01-01", 2, 10, other_dates=["x"], is_contaminated=True),
    ]
    assert pick_default_level(levels) == 1
