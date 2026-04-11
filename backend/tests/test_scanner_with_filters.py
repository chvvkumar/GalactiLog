from pathlib import Path

from app.services.scanner import scan_directory
from app.services.scan_filters import ScanFilterConfig, NameRule


def _touch(p: Path) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"")


def _make_tree(root: Path) -> None:
    _touch(root / "2025" / "M31" / "frame_01.fits")
    _touch(root / "2025" / "M31" / "frame_bad.fits")
    _touch(root / "2025" / "rejected" / "frame_02.fits")
    _touch(root / "2024" / "M42" / "frame_03.fits")
    _touch(root / "calibration" / "darks" / "dark_01.fits")


def test_scan_without_filters_finds_all(tmp_path):
    _make_tree(tmp_path)
    new_files, _, _ = scan_directory(tmp_path)
    assert len(new_files) == 5


def test_scan_with_exclude_path_prunes_subtree(tmp_path):
    _make_tree(tmp_path)
    cfg = ScanFilterConfig(
        include_paths=[],
        exclude_paths=[(tmp_path / "calibration").resolve()],
        name_rules=[],
    )
    new_files, _, _ = scan_directory(tmp_path, filter_config=cfg)
    names = {f.name for f in new_files}
    assert "dark_01.fits" not in names
    assert len(new_files) == 4


def test_scan_with_file_exclude_rule(tmp_path):
    _make_tree(tmp_path)
    cfg = ScanFilterConfig(
        include_paths=[],
        exclude_paths=[],
        name_rules=[NameRule(
            id="e1", action="exclude", type="glob",
            pattern="*_bad.fits", target="file", enabled=True,
        )],
    )
    new_files, _, _ = scan_directory(tmp_path, filter_config=cfg)
    names = {f.name for f in new_files}
    assert "frame_bad.fits" not in names
    assert "frame_01.fits" in names


def test_scan_with_folder_exclude_rule_prunes(tmp_path):
    _make_tree(tmp_path)
    cfg = ScanFilterConfig(
        include_paths=[],
        exclude_paths=[],
        name_rules=[NameRule(
            id="e1", action="exclude", type="substring",
            pattern="rejected", target="folder", enabled=True,
        )],
    )
    new_files, _, _ = scan_directory(tmp_path, filter_config=cfg)
    assert not any("rejected" in str(f) for f in new_files)
