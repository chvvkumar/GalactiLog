import pytest
from app.services.wbpp_export import detect_os, translate_path
from app.services.wbpp_export import (
    compute_ancestor_chain, longest_common_ancestor,
    compute_session_levels, pick_default_level, FolderLevel,
)
from app.services.wbpp_export import (
    disambiguate_staging_names, generate_powershell_script,
    generate_shell_script, DEFAULT_EXCLUSIONS, sanitize_script_name,
)
from app.services.wbpp_export import fits_relative_path, map_excluded_to_ops
from app.services.wbpp_export import subtree_bytes


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
    assert levels[0].relative_path == "M31"
    assert levels[1].relative_path == "M31/2024-01-01"
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


FITS = "/app/data/fits"
_HA_A = f"{FITS}/M31/2024-01-01/Ha/a.fits"
_HA_B = f"{FITS}/M31/2024-01-01/Ha/b.fits"
_O3_C = f"{FITS}/M31/2024-01-01/OIII/c.fits"
_SESSION_FILES = [_HA_A, _HA_B, _O3_C]


def _levels_by_rel(sizes_by_path):
    """Compute one session's levels, keyed by relative_path.

    Sibling levels at equal depth have no guaranteed order, so tests address
    levels by path rather than by index.
    """
    all_paths = {("M31", "2024-01-01"): list(_SESSION_FILES)}
    levels = compute_session_levels(
        "2024-01-01", list(_SESSION_FILES), all_paths, FITS, "/mnt/a", "posix",
        sizes_by_path=sizes_by_path,
    )
    return {lv.relative_path: lv for lv in levels}


def test_frame_bytes_sums_root_and_nested_levels():
    lv = _levels_by_rel({_HA_A: 100, _HA_B: 200, _O3_C: 400})
    # root level holds every frame in the session
    assert lv["M31"].frame_count == 3
    assert lv["M31"].frame_bytes == 700
    assert lv["M31/2024-01-01"].frame_bytes == 700
    # nested levels hold only their own subtree
    assert lv["M31/2024-01-01/Ha"].frame_count == 2
    assert lv["M31/2024-01-01/Ha"].frame_bytes == 300
    assert lv["M31/2024-01-01/OIII"].frame_count == 1
    assert lv["M31/2024-01-01/OIII"].frame_bytes == 400

def test_frame_bytes_tracks_frame_count():
    # A frame outside a level's subtree contributes to neither its count nor its sum.
    lv = _levels_by_rel({_HA_A: 100, _HA_B: 200, _O3_C: 400})
    o3 = lv["M31/2024-01-01/OIII"]
    assert o3.frame_count == 1 and o3.frame_bytes == 400  # not 700: Ha frames excluded
    assert sum(l.frame_bytes for l in (lv["M31/2024-01-01/Ha"], o3)) == lv["M31"].frame_bytes

def test_frame_bytes_none_when_any_contributing_size_is_null():
    # b.fits has an unknown size: every level containing it goes None, all-or-nothing.
    lv = _levels_by_rel({_HA_A: 100, _HA_B: None, _O3_C: 400})
    assert lv["M31"].frame_bytes is None            # not 500 (partial), not 0
    assert lv["M31/2024-01-01"].frame_bytes is None
    assert lv["M31/2024-01-01/Ha"].frame_bytes is None
    # a sibling level that does not contain the NULL frame is still reported
    assert lv["M31/2024-01-01/OIII"].frame_bytes == 400
    # counts are unaffected by unknown sizes
    assert lv["M31"].frame_count == 3

def test_frame_bytes_none_when_size_missing_from_map():
    # An absent entry is as unknown as an explicit NULL.
    lv = _levels_by_rel({_HA_A: 100, _O3_C: 400})
    assert lv["M31/2024-01-01/Ha"].frame_bytes is None
    assert lv["M31/2024-01-01/OIII"].frame_bytes == 400

def test_frame_bytes_none_when_no_sizes_supplied():
    lv = _levels_by_rel(None)
    assert all(l.frame_bytes is None for l in lv.values())
    assert lv["M31"].frame_count == 3  # counts still work without sizes

def test_subtree_bytes_zero_frames_is_zero_not_none():
    # Zero frames is a known quantity, unlike an unknown size.
    assert subtree_bytes([], {_HA_A: 100}) == 0

def test_subtree_bytes_without_size_map_is_none():
    assert subtree_bytes([_HA_A], None) is None

def test_compute_session_levels_no_frames_yields_no_levels():
    assert compute_session_levels(
        "2024-01-01", [], {}, FITS, "/mnt/a", "posix", sizes_by_path={},
    ) == []


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
    # The custom inline bar replaced Write-Progress: it draws a block-glyph bar
    # via the Show-CopyProgress helper and tracks an accurate byte total.
    assert "Show-CopyProgress" in s
    assert "$TotalBytes" in s
    assert "Write-Progress" not in s


def test_shell_script_shows_progress():
    s = generate_shell_script(
        [("/mnt/astro/M31/2024-01-01", "2024-01-01")], "/tmp/staging",
        "M31", ["WBPP"], ["2024-01-01"],
    )
    assert "--info=progress2" in s


def test_shell_script_color_guard_and_helper():
    """Tidied output: terminal-guarded colors, a copy_folder helper, and a
    consistent header/footer."""
    s = generate_shell_script(
        [("/mnt/astro/M31/2024-01-01", "2024-01-01"),
         ("/mnt/astro/M31/2024-01-02", "2024-01-02")],
        "/tmp/staging", "M31", ["WBPP"], ["2024-01-01", "2024-01-02"],
    )
    # colors only on a tty
    assert "if [ -t 1 ]; then" in s
    assert "C_RESET" in s
    # shared helper, invoked once per session folder
    assert "copy_folder() {" in s
    assert "copy_folder 1 " in s
    assert "copy_folder 2 " in s
    # header + footer wording
    assert "WBPP staging copy" in s
    assert "Done. Copied 2 folder(s)." in s


def test_shell_script_target_name_not_command_substituted():
    """A target name containing $(...) is passed as a quoted printf argument,
    never interpolated into a double-quoted string where it could execute."""
    s = generate_shell_script(
        [("/mnt/astro/M31/2024-01-01", "2024-01-01")], "/tmp/staging",
        "$(rm -rf ~)", ["WBPP"], ["2024-01-01"],
    )
    # the dangerous name is single-quoted (literal) for printf
    assert "'$(rm -rf ~)'" in s
    # and never sits inside a double-quoted printf operand
    assert '"$(rm -rf ~)"' not in s


def test_sanitize_script_name_strips_illegal_chars():
    # Windows-illegal characters and apostrophes are replaced; runs collapse.
    assert sanitize_script_name("NGC 7000: North America Nebula") == "NGC_7000_North_America_Nebula"
    assert sanitize_script_name("M 81 - Bode's Galaxy") == "M_81_-_Bode_s_Galaxy"
    assert sanitize_script_name('M27 / "Dumbbell" *test*?') == "M27_Dumbbell_test"
    # Dashes, underscores, and dots survive; leading/trailing junk is trimmed.
    assert sanitize_script_name("  ...Sh2-155...  ") == "Sh2-155"
    # Nothing usable falls back to the placeholder.
    assert sanitize_script_name("::: ???") == "target"


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

# ---------------------------------------------------------------------------
# Per-file quality-filter exclusion (excluded_by_op)
# ---------------------------------------------------------------------------

def test_fits_relative_path_strips_root():
    assert fits_relative_path(
        "/app/data/fits/M31/2024-01-01/Light/x.fits", "/app/data/fits",
    ) == "M31/2024-01-01/Light/x.fits"
    # trailing slash on root and paths outside root both degrade gracefully
    assert fits_relative_path("/app/data/fits/a.fits", "/app/data/fits/") == "a.fits"
    assert fits_relative_path("/other/a.fits", "/app/data/fits") == "other/a.fits"


def test_map_excluded_to_ops_prefix_and_drop():
    chosen = [
        ("2024-01-01", FolderLevel("/mnt/a/M31/2024-01-01", "/fits/M31/2024-01-01", 2, 5,
                                   relative_path="M31/2024-01-01")),
        ("2024-01-02", FolderLevel("/mnt/a/M31/2024-01-02", "/fits/M31/2024-01-02", 2, 5,
                                   relative_path="M31/2024-01-02")),
    ]
    excluded = [
        "M31/2024-01-01/Ha/bad1.fits",
        "M31/2024-01-02/OIII/bad2.fits",
        "M31/2099-12-31/Ha/orphan.fits",  # matches no chosen folder -> dropped
    ]
    result = map_excluded_to_ops(excluded, chosen)
    # mapped by folder-level prefix, stored relative to each op's transfer root
    assert result[0] == ["Ha/bad1.fits"]
    assert result[1] == ["OIII/bad2.fits"]
    # the orphan produced no entry for any op
    assert len(result) == 2


def test_map_excluded_to_ops_longest_prefix_wins():
    # Nested chosen folders: the deeper (longer) prefix claims the file.
    chosen = [
        ("outer", FolderLevel("/mnt/a/M31", "/fits/M31", 1, 5, relative_path="M31")),
        ("inner", FolderLevel("/mnt/a/M31/2024-01-01", "/fits/M31/2024-01-01", 2, 5,
                              relative_path="M31/2024-01-01")),
    ]
    result = map_excluded_to_ops(["M31/2024-01-01/Ha/bad.fits"], chosen)
    assert result == {1: ["Ha/bad.fits"]}


def test_powershell_no_exclusions_byte_identical():
    args = (
        [("Z:\\Astro\\M31\\2024-01-01", "2024-01-01")], "Z:\\Staging",
        "M31", DEFAULT_EXCLUSIONS, ["2024-01-01"], "wbpp_M31.ps1",
    )
    base = generate_powershell_script(*args)
    assert generate_powershell_script(*args, excluded_by_op=None) == base
    assert generate_powershell_script(*args, excluded_by_op={}) == base
    assert "ExcludeFiles" not in base


def test_shell_no_exclusions_byte_identical():
    args = (
        [("/mnt/astro/M31/2024-01-01", "2024-01-01")], "/tmp/staging",
        "M31", DEFAULT_EXCLUSIONS, ["2024-01-01"], "wbpp_M31.sh",
    )
    base = generate_shell_script(*args)
    assert generate_shell_script(*args, excluded_by_op=None) == base
    assert generate_shell_script(*args, excluded_by_op={}) == base
    assert "${@:4}" not in base


def test_powershell_per_file_exclusion():
    s = generate_powershell_script(
        [("Z:\\Astro\\M31\\2024-01-01", "2024-01-01")], "Z:\\Staging",
        "M31", ["WBPP"], ["2024-01-01"], "wbpp_M31.ps1",
        excluded_by_op={0: ["Ha/light_bad.fits"]},
    )
    # the named light appears as a backslash-normalized ExcludeFiles entry, checked
    # against each file's job-relative path
    assert "ExcludeFiles = @(" in s
    assert "'Ha\\light_bad.fits'" in s
    assert "$Job.ExcludeFiles -contains $RelPath" in s
    # a non-excluded sibling and any calibration file are never named
    assert "light_good.fits" not in s
    assert "Calib_dark_001.fits" not in s


def test_shell_per_file_exclusion():
    s = generate_shell_script(
        [("/mnt/astro/M31/2024-01-01", "2024-01-01")], "/tmp/staging",
        "M31", ["WBPP"], ["2024-01-01"], "wbpp_M31.sh",
        excluded_by_op={0: ["Ha/light_bad.fits"]},
    )
    # one --exclude anchored to the job's transfer root, passed through $4+
    assert "--exclude='/Ha/light_bad.fits'" in s
    assert "${@:4}" in s
    # a non-excluded sibling and any calibration file are never named
    assert "light_good.fits" not in s
    assert "Calib_dark_001.fits" not in s


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
