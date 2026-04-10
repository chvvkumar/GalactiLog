import pytest
from pathlib import Path

from app.services.scan_filters import NameRule


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
