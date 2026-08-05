"""PHD2 guide-log discovery piggybacked on the image scan walk.

The image contract must not move: scan_directory still returns image paths
only, and SUPPORTED_EXTENSIONS is untouched. PHD2 hits arrive via a callback.
"""
from pathlib import Path

import pytest

from app.services.scanner import SUPPORTED_EXTENSIONS, is_phd2_guide_log, scan_directory
from app.services.scan_filters import NameRule, ScanFilterConfig


@pytest.fixture
def tree(tmp_path):
    root = tmp_path / "library"
    (root / "M42").mkdir(parents=True)
    (root / "logs").mkdir(parents=True)
    (root / "M42" / "Light_Ha_001.fits").write_text("x")
    (root / "M42" / "notes.txt").write_text("x")
    (root / "logs" / "PHD2_GuideLog_2026-07-14_201333.txt").write_text("x")
    (root / "logs" / "PHD2_GuideLog_2026-01-19_172118.txt").write_text("x")
    (root / "logs" / "PHD2_DebugLog_2026-07-14_201333.txt").write_text("x")
    return root


def test_is_phd2_guide_log_accepts_guide_rejects_debug():
    assert is_phd2_guide_log("PHD2_GuideLog_2026-07-14_201333.txt") is True
    assert is_phd2_guide_log("phd2_guidelog_2026-07-14_201333.TXT") is True
    assert is_phd2_guide_log("PHD2_DebugLog_2026-07-14_201333.txt") is False
    assert is_phd2_guide_log("PHD2_GuideLog_2026-07-14_201333.log") is False
    assert is_phd2_guide_log("notes.txt") is False


def test_supported_extensions_still_excludes_txt():
    assert ".txt" not in SUPPORTED_EXTENSIONS


def test_walk_emits_guide_logs_through_the_callback_only(tree):
    hits = []
    new_files, changed, all_paths = scan_directory(tree, on_phd2_file=hits.append)
    assert sorted(p.name for p in hits) == [
        "PHD2_GuideLog_2026-01-19_172118.txt",
        "PHD2_GuideLog_2026-07-14_201333.txt",
    ]
    # The image contract is unchanged: no .txt anywhere in the returns.
    assert [p.name for p in new_files] == ["Light_Ha_001.fits"]
    assert changed == []
    assert all(not p.endswith(".txt") for p in all_paths)


def test_walk_without_the_callback_behaves_exactly_as_before(tree):
    new_files, changed, all_paths = scan_directory(tree)
    assert [p.name for p in new_files] == ["Light_Ha_001.fits"]
    assert len(all_paths) == 1


def test_guide_logs_respect_scan_exclude_rules(tree):
    config = ScanFilterConfig(
        include_paths=[],
        exclude_paths=[Path(tree / "logs").resolve()],
        name_rules=[],
    )
    hits = []
    scan_directory(tree, filter_config=config, fits_root=tree, on_phd2_file=hits.append)
    assert hits == []


def test_guide_logs_respect_file_name_exclude_rules(tree):
    config = ScanFilterConfig(
        include_paths=[],
        exclude_paths=[],
        name_rules=[NameRule(
            id="r1", action="exclude", type="glob",
            pattern="PHD2_GuideLog_2026-01*", target="file",
        )],
    )
    hits = []
    scan_directory(tree, filter_config=config, fits_root=tree, on_phd2_file=hits.append)
    assert [p.name for p in hits] == ["PHD2_GuideLog_2026-07-14_201333.txt"]


def test_scan_state_snapshot_carries_phd2_counters():
    from app.services.scan_state import ScanStateSnapshot, parse_snapshot

    snap = parse_snapshot({
        "state": "complete", "total": "3", "completed": "3", "failed": "0",
        "phd2_found": "25", "phd2_ingested": "18", "phd2_failed": "1",
    })
    assert snap.phd2_found == 25
    assert snap.phd2_ingested == 18
    assert snap.phd2_failed == 1
    assert snap.to_dict()["phd2_ingested"] == 18

    blank = ScanStateSnapshot(
        state="idle", total=0, completed=0, failed=0,
        started_at=None, completed_at=None,
    )
    assert blank.phd2_found == 0
    assert blank.to_dict()["phd2_found"] == 0


def test_scan_state_response_schema_accepts_phd2_counters():
    from app.schemas.scan import ScanStateResponse

    resp = ScanStateResponse(state="complete", total=0, completed=0, failed=0)
    assert resp.phd2_found == 0
    assert resp.phd2_ingested == 0
    assert resp.phd2_failed == 0
