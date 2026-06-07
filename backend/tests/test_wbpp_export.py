import pytest
from app.services.wbpp_export import detect_os, translate_path
from app.services.wbpp_export import (
    compute_ancestor_chain, longest_common_ancestor,
    compute_session_levels, pick_default_level, FolderLevel,
)
from app.services.wbpp_export import (
    disambiguate_staging_names, generate_powershell_script,
    generate_shell_script, DEFAULT_EXCLUSIONS,
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


def test_disambiguate_no_collision():
    assert disambiguate_staging_names(
        ["/mnt/a/2024-01-01", "/mnt/a/2024-01-02"], ["2024-01-01", "2024-01-02"],
    ) == ["2024-01-01", "2024-01-02"]

def test_disambiguate_collision():
    assert disambiguate_staging_names(
        ["/mnt/a/2024-01-01/M31", "/mnt/a/2024-01-02/M31"], ["2024-01-01", "2024-01-02"],
    ) == ["2024-01-01_M31", "2024-01-02_M31"]

def test_powershell_script_contains_copy_operations():
    s = generate_powershell_script(
        [("Z:\\Astro\\M31\\2024-01-01", "2024-01-01")], "Z:\\WBPP_Staging\\M31",
        "M31", ["WBPP", "PixInsight"], ["2024-01-01"],
    )
    assert "Z:\\Astro\\M31\\2024-01-01" in s
    assert "Z:\\WBPP_Staging\\M31" in s
    assert "Copy-Item" in s

def test_powershell_script_excludes_known_folders():
    s = generate_powershell_script(
        [("Z:\\Astro\\M31\\2024-01-01", "2024-01-01")], "Z:\\Staging",
        "M31", DEFAULT_EXCLUSIONS, ["2024-01-01"],
    )
    assert "WBPP" in s and "PixInsight" in s and "CALIBRATED" in s

def test_shell_script_uses_rsync():
    s = generate_shell_script(
        [("/mnt/astro/M31/2024-01-01", "2024-01-01")], "/tmp/wbpp_staging/M31",
        "M31", ["WBPP", "PixInsight"], ["2024-01-01"],
    )
    assert "rsync" in s and "/mnt/astro/M31/2024-01-01" in s and "--exclude" in s

def test_shell_script_valid_shebang():
    assert generate_shell_script([], "/tmp/s", "T", [], []).startswith("#!/usr/bin/env bash")


def test_shell_script_quotes_paths_safely():
    """User-derived paths containing $(...) must be single-quoted, not double-quoted."""
    s = generate_shell_script(
        [("/mnt/astro/$(id)/M31", "2024-01-01")], "/tmp/$(id)/staging",
        "M31", ["WBPP"], ["2024-01-01"],
    )
    # staging root is single-quoted (literal, no command substitution)
    assert "'/tmp/$(id)/staging'" in s
    # the dangerous value must NOT sit inside a double-quoted assignment
    assert 'STAGING_ROOT="/tmp/$(id)/staging"' not in s
    assert 'STAGING_ROOT="' not in s
    # rsync source is single-quoted as well
    assert "'/mnt/astro/$(id)/M31/'" in s
    assert '"/mnt/astro/$(id)/M31/"' not in s

def test_shell_script_escapes_single_quote():
    """A path containing a single quote round-trips with the '\\'' idiom."""
    s = generate_shell_script(
        [("/mnt/astro/o'brien/M31", "2024-01-01")], "/tmp/o'brien/staging",
        "M31", [], ["2024-01-01"],
    )
    assert "STAGING_ROOT='/tmp/o'\\''brien/staging'" in s
    assert "'/mnt/astro/o'\\''brien/M31/'" in s

def test_powershell_script_quotes_paths_safely():
    """A staging_root containing a single quote is doubled inside the literal."""
    s = generate_powershell_script(
        [("Z:\\Astro\\o'brien\\M31", "2024-01-01")], "Z:\\o'brien\\Staging",
        "M31", ["WBPP"], ["2024-01-01"],
    )
    assert "$StagingRoot = 'Z:\\o''brien\\Staging'" in s
    assert "Src = 'Z:\\Astro\\o''brien\\M31'" in s
    # no double-quoted user path literal remains
    assert '$StagingRoot = "' not in s
    assert 'Src = "' not in s


def test_powershell_script_shows_progress():
    s = generate_powershell_script(
        [("Z:\\Astro\\M31\\2024-01-01", "2024-01-01")], "Z:\\Staging",
        "M31", ["WBPP"], ["2024-01-01"],
    )
    assert "Write-Progress" in s


def test_shell_script_shows_progress():
    s = generate_shell_script(
        [("/mnt/astro/M31/2024-01-01", "2024-01-01")], "/tmp/staging",
        "M31", ["WBPP"], ["2024-01-01"],
    )
    assert "--info=progress2" in s


def test_powershell_script_includes_run_instruction():
    s = generate_powershell_script(
        [("Z:\\Astro\\M31\\2024-01-01", "2024-01-01")], "Z:\\Staging",
        "M31", ["WBPP"], ["2024-01-01"], "wbpp_M31.ps1",
    )
    assert "ExecutionPolicy Bypass" in s
    assert "wbpp_M31.ps1" in s


def test_shell_script_includes_run_instruction():
    s = generate_shell_script(
        [("/mnt/astro/M31/2024-01-01", "2024-01-01")], "/tmp/staging",
        "M31", ["WBPP"], ["2024-01-01"], "wbpp_M31.sh",
    )
    assert "chmod +x wbpp_M31.sh" in s

def test_powershell_exclusion_matches_component_not_substring():
    """'finals' excludes a 'finals' folder but NOT a 'semifinals' folder."""
    s = generate_powershell_script(
        [("Z:\\Astro\\M31\\2024-01-01", "2024-01-01")], "Z:\\Staging",
        "M31", ["finals"], ["2024-01-01"],
    )
    # the filter must split FullName into path components and test each, not a bare
    # substring -notmatch against the whole FullName
    assert ".Split(" in s
    # the exclusion regex must be anchored to a full component (^...$), so that a
    # component named 'semifinals' is not matched by 'finals'
    assert "^(" in s and ")$" in s
    assert '$_.FullName -notmatch' not in s
