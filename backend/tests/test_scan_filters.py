import pytest
from pathlib import Path

from app.services.scan_filters import NameRule, ScanFilterConfig, TestResult


def _rule(**kwargs):
    defaults = {
        "id": "r1", "action": "exclude", "type": "glob",
        "pattern": "*.tmp", "target": "file", "enabled": True,
    }
    defaults.update(kwargs)
    return NameRule(**defaults)


def test_glob_matches_filename():
    r = _rule(type="glob", pattern="*_bad.fits")
    assert r.matches("frame_bad.fits")
    assert not r.matches("frame_good.fits")


def test_glob_double_star_segment():
    r = _rule(type="glob", pattern="**/rejected/**", target="folder")
    # folder rule sees individual segments; ** is not meaningful against a single
    # segment, so this rule instead must be written as substring or regex.
    # Glob for folders matches a single segment name.
    r2 = _rule(type="glob", pattern="rejected", target="folder")
    assert r2.matches("rejected")
    assert not r2.matches("accepted")


def test_substring_case_insensitive():
    r = _rule(type="substring", pattern="Rejected", target="folder")
    assert r.matches("2025_rejected_frames")
    assert r.matches("REJECTED")
    assert not r.matches("accepted")


def test_regex_anchored():
    r = _rule(type="regex", pattern=r"^M\d+$", target="folder")
    assert r.matches("M31")
    assert r.matches("M101")
    assert not r.matches("NGC7000")
    assert not r.matches("M31_v2")


def test_disabled_rule_never_matches():
    r = _rule(type="substring", pattern="bad", enabled=False)
    assert not r.matches("bad")


def test_invalid_regex_raises_at_construction():
    with pytest.raises(ValueError, match="invalid regex"):
        _rule(type="regex", pattern="[unclosed")


def test_from_settings_empty(tmp_path):
    cfg = ScanFilterConfig.from_settings({}, tmp_path)
    assert cfg.include_paths == []
    assert cfg.exclude_paths == []
    assert cfg.name_rules == []


def test_from_settings_parses_paths_and_rules(tmp_path):
    (tmp_path / "2025").mkdir()
    (tmp_path / "2025" / "rejected").mkdir()
    general = {
        "scan_filters": {
            "include_paths": [str(tmp_path / "2025")],
            "exclude_paths": [str(tmp_path / "2025" / "rejected")],
            "name_rules": [
                {"id": "r1", "action": "exclude", "type": "glob",
                 "pattern": "*_bad.fits", "target": "file", "enabled": True},
            ],
        }
    }
    cfg = ScanFilterConfig.from_settings(general, tmp_path)
    assert len(cfg.include_paths) == 1
    assert len(cfg.exclude_paths) == 1
    assert len(cfg.name_rules) == 1


def test_from_settings_rejects_path_outside_root(tmp_path):
    outside = tmp_path.parent / "escape"
    outside.mkdir(exist_ok=True)
    general = {
        "scan_filters": {
            "include_paths": [str(outside)],
            "exclude_paths": [],
            "name_rules": [],
        }
    }
    with pytest.raises(ValueError, match="outside configured data path"):
        ScanFilterConfig.from_settings(general, tmp_path)


def test_roots_returns_fits_root_when_includes_empty(tmp_path):
    cfg = ScanFilterConfig(include_paths=[], exclude_paths=[], name_rules=[])
    assert cfg.roots(tmp_path) == [tmp_path]


def _cfg(include_paths=None, exclude_paths=None, rules=None):
    return ScanFilterConfig(
        include_paths=include_paths or [],
        exclude_paths=exclude_paths or [],
        name_rules=rules or [],
    )


def test_should_walk_dir_prunes_exclude_paths(tmp_path):
    (tmp_path / "rejected").mkdir()
    cfg = _cfg(exclude_paths=[tmp_path / "rejected"])
    assert not cfg.should_walk_dir(tmp_path / "rejected", tmp_path)
    assert not cfg.should_walk_dir(tmp_path / "rejected" / "sub", tmp_path)
    assert cfg.should_walk_dir(tmp_path / "kept", tmp_path)


def test_should_walk_dir_exclude_folder_name_rule(tmp_path):
    cfg = _cfg(rules=[_rule(
        type="substring", pattern="rejected", target="folder", action="exclude",
    )])
    (tmp_path / "2025_rejected").mkdir()
    assert not cfg.should_walk_dir(tmp_path / "2025_rejected", tmp_path)
    assert cfg.should_walk_dir(tmp_path / "2025_kept", tmp_path)


def test_should_include_file_exclude_wins(tmp_path):
    cfg = _cfg(rules=[
        _rule(id="i1", action="include", type="glob",
              pattern="*.fits", target="file"),
        _rule(id="e1", action="exclude", type="glob",
              pattern="*_bad.fits", target="file"),
    ])
    assert cfg.should_include_file(tmp_path / "frame.fits", tmp_path)
    assert not cfg.should_include_file(tmp_path / "frame_bad.fits", tmp_path)


def test_should_include_file_include_narrowing(tmp_path):
    # An include rule exists for 'file' target, so files must match at least one
    cfg = _cfg(rules=[
        _rule(id="i1", action="include", type="regex",
              pattern=r"^M\d+_.*\.fits$", target="file"),
    ])
    assert cfg.should_include_file(tmp_path / "M31_L.fits", tmp_path)
    assert not cfg.should_include_file(tmp_path / "NGC7000_L.fits", tmp_path)


def test_should_include_file_no_includes_passes_all(tmp_path):
    cfg = _cfg(rules=[
        _rule(id="e1", action="exclude", type="substring",
              pattern="tmp", target="file"),
    ])
    assert cfg.should_include_file(tmp_path / "frame.fits", tmp_path)
    assert not cfg.should_include_file(tmp_path / "frame.tmp", tmp_path)


def test_should_include_file_folder_rule_applies_to_ancestors(tmp_path):
    (tmp_path / "rejected" / "sub").mkdir(parents=True)
    cfg = _cfg(rules=[_rule(
        id="e1", action="exclude", type="substring", pattern="rejected",
        target="folder",
    )])
    f = tmp_path / "rejected" / "sub" / "frame.fits"
    assert not cfg.should_include_file(f, tmp_path)


def test_roots_returns_includes_when_set(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    cfg = ScanFilterConfig(
        include_paths=[tmp_path / "a", tmp_path / "b"],
        exclude_paths=[],
        name_rules=[],
    )
    assert cfg.roots(tmp_path) == [tmp_path / "a", tmp_path / "b"]


def test_test_path_included(tmp_path):
    cfg = _cfg()
    result = cfg.test_path(tmp_path / "M31" / "frame.fits", tmp_path)
    assert result.verdict == "included"
    assert result.matched_rule_ids == []


def test_test_path_excluded_by_path(tmp_path):
    (tmp_path / "rejected").mkdir()
    cfg = _cfg(exclude_paths=[tmp_path / "rejected"])
    result = cfg.test_path(tmp_path / "rejected" / "x.fits", tmp_path)
    assert result.verdict == "excluded_by_path"


def test_test_path_excluded_by_rule(tmp_path):
    cfg = _cfg(rules=[_rule(
        id="e1", action="exclude", type="glob",
        pattern="*_bad.fits", target="file",
    )])
    result = cfg.test_path(tmp_path / "frame_bad.fits", tmp_path)
    assert result.verdict == "excluded_by_rule"
    assert "e1" in result.matched_rule_ids


def test_test_path_excluded_by_missing_include(tmp_path):
    cfg = _cfg(rules=[_rule(
        id="i1", action="include", type="glob",
        pattern="M*.fits", target="file",
    )])
    result = cfg.test_path(tmp_path / "NGC7000.fits", tmp_path)
    assert result.verdict == "excluded_by_missing_include"


def test_test_path_excluded_when_outside_include_paths(tmp_path):
    (tmp_path / "kept").mkdir()
    (tmp_path / "other").mkdir()
    cfg = _cfg(include_paths=[tmp_path / "kept"])
    assert cfg.test_path(tmp_path / "kept" / "x.fits", tmp_path).verdict == "included"
    assert cfg.test_path(tmp_path / "other" / "x.fits", tmp_path).verdict == "excluded_by_path"
    # The fits_root itself, when include_paths is set, is not under any include
    assert cfg.test_path(tmp_path, tmp_path).verdict == "excluded_by_path"


def test_should_include_file_respects_include_paths(tmp_path):
    (tmp_path / "kept").mkdir()
    (tmp_path / "other").mkdir()
    cfg = _cfg(include_paths=[tmp_path / "kept"])
    assert cfg.should_include_file(tmp_path / "kept" / "x.fits", tmp_path)
    assert not cfg.should_include_file(tmp_path / "other" / "x.fits", tmp_path)
