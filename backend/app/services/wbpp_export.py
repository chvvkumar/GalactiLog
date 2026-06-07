"""WBPP session export service.

Translates container-internal FITS paths to user-machine paths, computes
per-session folder level candidates, detects contamination, disambiguates
colliding staging names, and generates copy scripts.
"""
import posixpath
import re
from collections import Counter
from dataclasses import dataclass, field


def detect_os(library_root: str) -> str:
    """Return 'windows' if root has a drive letter or backslash, else 'posix'."""
    if re.match(r"^[A-Za-z]:\\", library_root) or "\\" in library_root:
        return "windows"
    return "posix"


def translate_path(container_path: str, fits_root: str, library_root: str, target_os: str) -> str:
    """Strip fits_root from container_path, prepend library_root, adjust separators.

    Raises ValueError if container_path is not under fits_root.
    """
    fits_root = fits_root.rstrip("/")
    if not container_path.startswith(fits_root + "/") and container_path != fits_root:
        raise ValueError(f"Path {container_path!r} does not start with fits_root {fits_root!r}")
    relative = container_path[len(fits_root):].lstrip("/")
    if target_os == "windows":
        return library_root.rstrip("\\").rstrip("/") + "\\" + relative.replace("/", "\\")
    return library_root.rstrip("/") + "/" + relative


@dataclass
class FolderLevel:
    """One candidate folder level for a session's copy source."""
    path: str               # user-machine path (translated)
    container_path: str
    depth_from_root: int    # 1 = first level under fits_root
    frame_count: int        # session frames under this subtree
    other_targets: list[str] = field(default_factory=list)
    other_dates: list[str] = field(default_factory=list)
    is_contaminated: bool = False


def compute_ancestor_chain(container_path: str, fits_root: str) -> list[str]:
    """Return container-path ancestors from fits_root+1 down to the file's parent."""
    fits_root = fits_root.rstrip("/")
    rel = container_path[len(fits_root):].lstrip("/")
    folder_parts = rel.split("/")[:-1]  # drop file name
    return [fits_root + "/" + "/".join(folder_parts[:i]) for i in range(1, len(folder_parts) + 1)]


def longest_common_ancestor(paths: list[str]) -> str:
    """Return the longest common directory prefix across file paths."""
    if not paths:
        return ""
    common = []
    for components in zip(*[p.split("/") for p in paths]):
        if len(set(components)) == 1:
            common.append(components[0])
        else:
            break
    return "/".join(common)


def compute_session_levels(
    session_date: str,
    file_paths: list[str],
    all_paths_by_target_date: dict,   # {(target_name, date_str): [container paths]}
    fits_root: str,
    library_root: str,
    target_os: str,
) -> list[FolderLevel]:
    """Compute ancestor-chain levels for one session, annotated with contamination.

    Returned shallowest-first (closest to library root first).
    """
    if not file_paths:
        return []
    fits_root = fits_root.rstrip("/")

    all_ancestors: set[str] = set()
    for fp in file_paths:
        all_ancestors.update(compute_ancestor_chain(fp, fits_root))
    sorted_ancestors = sorted(all_ancestors, key=lambda p: p.count("/"))

    # folder -> set of (target, date) that have frames anywhere under it
    folder_occupants: dict[str, set] = {}
    for (tname, dstr), tpaths in all_paths_by_target_date.items():
        for tp in tpaths:
            for anc in compute_ancestor_chain(tp, fits_root):
                folder_occupants.setdefault(anc, set()).add((tname, dstr))

    # the current session's target = the target occupying any of this session's folders on session_date
    occ_for_session = folder_occupants.get(sorted_ancestors[-1], set())
    current_target = next((t for t, d in occ_for_session if d == session_date), "")

    levels = []
    for anc in sorted_ancestors:
        count = sum(1 for fp in file_paths if fp.startswith(anc + "/") or fp == anc)
        occupants = folder_occupants.get(anc, set())
        other_t = sorted({t for t, d in occupants if t != current_target})
        other_d = sorted({d for t, d in occupants if d != session_date})
        levels.append(FolderLevel(
            path=translate_path(anc, fits_root, library_root, target_os),
            container_path=anc,
            depth_from_root=anc.count("/") - fits_root.count("/"),
            frame_count=count,
            other_targets=other_t,
            other_dates=other_d,
            is_contaminated=bool(other_t or other_d),
        ))
    return levels


def pick_default_level(levels: list[FolderLevel]) -> int:
    """Return index of the deepest non-contaminated level holding all session frames.

    Falls back to the deepest level holding all frames if every level is contaminated.
    """
    if not levels:
        return 0
    max_frames = max(lv.frame_count for lv in levels)
    for i in reversed(range(len(levels))):
        if levels[i].frame_count == max_frames and not levels[i].is_contaminated:
            return i
    for i in reversed(range(len(levels))):
        if levels[i].frame_count == max_frames:
            return i
    return len(levels) - 1


DEFAULT_EXCLUSIONS = [
    "WBPP", "PixInsight", "finals", "WORK_AREA",
    "masters", "Masters", "MASTERS", "*CALIBRATED", "CALIBRATED",
]


def disambiguate_staging_names(selected_paths: list[str], session_dates: list[str]) -> list[str]:
    """Return staging entry names; prefix with the session date when basenames collide."""
    basenames = [p.rstrip("/\\").rsplit("/", 1)[-1].rsplit("\\", 1)[-1] for p in selected_paths]
    counts = Counter(basenames)
    return [
        f"{date}_{base}" if counts[base] > 1 else base
        for base, date in zip(basenames, session_dates)
    ]


def generate_powershell_script(copy_ops, staging_root, target_name, exclusions, session_dates):
    """Generate a PowerShell .ps1 copy script (copy only, recursive, with exclusions)."""
    excl_patterns = "|".join(re.escape(e).replace(r"\*", ".*") for e in exclusions)
    win = "\\" in staging_root
    lines = [
        "# WBPP Session Export",
        f"# Target: {target_name}",
        f"# Sessions: {', '.join(session_dates)}",
        "# Run on the machine where PixInsight is installed, then open WBPP and",
        f"# use 'Add Directory' on the staging root: {staging_root}",
        "",
        f'$StagingRoot = "{staging_root}"',
        "$ErrorActionPreference = 'Stop'",
        "if (-not (Test-Path $StagingRoot)) { New-Item -ItemType Directory -Force -Path $StagingRoot | Out-Null }",
        "",
    ]
    for src, entry_name in copy_ops:
        dest = f'"{staging_root}\\{entry_name}"' if win else f'"{staging_root}/{entry_name}"'
        lines += [
            f"# Session folder: {src}",
            f'$Src = "{src}"',
            f"$Dst = {dest}",
            "Get-ChildItem -Path $Src -Recurse -File | Where-Object {",
        ]
        if exclusions:
            lines.append(f'    $_.FullName -notmatch "({excl_patterns})"')
        else:
            lines.append("    $true")
        lines += [
            "} | ForEach-Object {",
            "    $RelPath = $_.FullName.Substring($Src.Length).TrimStart('\\', '/')",
            "    $Target = Join-Path $Dst $RelPath",
            "    $TargetDir = Split-Path $Target -Parent",
            "    if (-not (Test-Path $TargetDir)) { New-Item -ItemType Directory -Force -Path $TargetDir | Out-Null }",
            "    Copy-Item -Path $_.FullName -Destination $Target -Force",
            "}",
            "",
        ]
    lines.append("Write-Host 'Copy complete. Open WBPP and use Add Directory on:' $StagingRoot")
    return "\n".join(lines)


def generate_shell_script(copy_ops, staging_root, target_name, exclusions, session_dates):
    """Generate a POSIX shell .sh copy script using rsync (copy only)."""
    excl_args = " ".join(f'--exclude="{e}"' for e in exclusions)
    lines = [
        "#!/usr/bin/env bash",
        "# WBPP Session Export",
        f"# Target: {target_name}",
        f"# Sessions: {', '.join(session_dates)}",
        "# Run on the machine where PixInsight is installed, then open WBPP and",
        f"# use 'Add Directory' on the staging root: {staging_root}",
        "",
        "set -euo pipefail",
        f'STAGING_ROOT="{staging_root}"',
        'mkdir -p "$STAGING_ROOT"',
        "",
    ]
    for src, entry_name in copy_ops:
        dest = f'"$STAGING_ROOT/{entry_name}"'
        lines += [
            f"# Session folder: {src}",
            f"mkdir -p {dest}",
            f'rsync -av --copy-links {excl_args} \\'.rstrip(),
            f'    "{src}/" \\',
            f"    {dest}/",
            "",
        ]
    lines.append('echo "Copy complete. Open WBPP and use Add Directory on: $STAGING_ROOT"')
    return "\n".join(lines)
