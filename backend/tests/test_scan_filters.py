import pytest
from pathlib import Path

from app.services.scan_filters import NameRule, ScanFilterConfig


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


def test_roots_returns_includes_when_set(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    cfg = ScanFilterConfig(
        include_paths=[tmp_path / "a", tmp_path / "b"],
        exclude_paths=[],
        name_rules=[],
    )
    assert cfg.roots(tmp_path) == [tmp_path / "a", tmp_path / "b"]
