"""WBPP session export service.

Translates container-internal FITS paths to user-machine paths, computes
per-session folder level candidates, detects contamination, disambiguates
colliding staging names, and generates copy scripts.
"""
import re
from collections import Counter
from dataclasses import dataclass, field


def _sh_quote(value: str) -> str:
    """Quote a value as a single bash literal.

    Wraps in single quotes and escapes embedded single quotes via the '\\'' idiom,
    so command substitution ($(...), backticks) and other metacharacters in
    user-derived paths cannot execute when the script is run.
    """
    return "'" + value.replace("'", "'\\''") + "'"


def _ps_quote(value: str) -> str:
    """Quote a value as a single PowerShell literal.

    PowerShell single-quoted strings are literal; embedded single quotes are
    escaped by doubling them. This prevents subexpression evaluation and parse
    errors from user-derived paths.
    """
    return "'" + value.replace("'", "''") + "'"


def sanitize_script_name(target_name: str, fallback: str = "target") -> str:
    """Make a target name safe to use as a download filename component.

    Replaces any character that is not alphanumeric, dash, underscore, or dot
    (this covers spaces and the Windows-illegal set < > : " / \\ | ? * as well
    as apostrophes that complicate shell quoting), collapses runs of separators
    into a single underscore, and trims leading/trailing junk. Falls back to a
    placeholder if nothing usable remains.
    """
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", target_name).strip("._")
    return cleaned or fallback


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
    relative_path: str = ""  # path relative to the FITS/library root (POSIX, for browser copy)


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
            relative_path=anc[len(fits_root):].lstrip("/"),
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


def generate_powershell_script(copy_ops, staging_root, target_name, exclusions, session_dates, filename=None):
    """Generate a PowerShell .ps1 copy script with a progress bar.

    Copies recursively (copy only), applies component-level exclusions, gathers
    the full file list first so it can show Write-Progress with an accurate
    overall percentage as files are copied.
    """
    excl_patterns = "|".join(re.escape(e).replace(r"\*", ".*") for e in exclusions)
    script_name = filename or "this script"
    # Single-quoted PowerShell literal: double any embedded apostrophes (e.g. "Bode's").
    quoted_name = script_name.replace("'", "''")
    lines = [
        "# WBPP Session Export",
        f"# Target: {target_name}",
        f"# Sessions: {', '.join(session_dates)}",
        "#",
        "# To run this script:",
        "#   Open PowerShell in this folder. Files downloaded via a browser are blocked",
        "#   by Windows (Mark of the Web); this unblocks and runs the script in one step:",
        f"#     powershell -ExecutionPolicy Bypass -Command "
        f"\"Unblock-File -LiteralPath '.\\{quoted_name}'; & '.\\{quoted_name}'\"",
        "#",
        "# When it finishes, open PixInsight WBPP and use 'Add Directory' on the",
        f"# staging root: {staging_root}",
        "",
        f"$StagingRoot = {_ps_quote(staging_root)}",
        "$ErrorActionPreference = 'Stop'",
        "if (-not (Test-Path $StagingRoot)) { New-Item -ItemType Directory -Force -Path $StagingRoot | Out-Null }",
        "",
        "$Jobs = @(",
    ]
    for src, entry_name in copy_ops:
        lines.append(
            f"    @{{ Src = {_ps_quote(src)}; "
            f"Dst = (Join-Path $StagingRoot {_ps_quote(entry_name)}) }}"
        )
    lines += [
        ")",
        "",
        "# ---------------------------------------------------------------------------",
        "# Display helpers",
        "# ---------------------------------------------------------------------------",
        "# Render block glyphs from code points so this script stays ASCII on disk;",
        "# the console renders them as Unicode once OutputEncoding is UTF-8.",
        "$Glyph = @{",
        "    Full  = [char]0x2588   # full block",
        "    Light = [char]0x2591   # light shade",
        "    CapL  = [char]0x2595   # right one-eighth block (left edge cap)",
        "    CapR  = [char]0x258F   # left one-eighth block (right edge cap)",
        "}",
        "try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }",
        "",
        "function Format-Bytes {",
        "    param([double]$Bytes)",
        "    if ($Bytes -ge 1GB) { return ('{0:N1} GB' -f ($Bytes / 1GB)) }",
        "    elseif ($Bytes -ge 1MB) { return ('{0:N1} MB' -f ($Bytes / 1MB)) }",
        "    elseif ($Bytes -ge 1KB) { return ('{0:N0} KB' -f ($Bytes / 1KB)) }",
        "    else { return ('{0:N0} B' -f $Bytes) }",
        "}",
        "",
        "function Format-Duration {",
        "    param([double]$Seconds)",
        "    if ($Seconds -lt 0 -or [double]::IsNaN($Seconds) -or [double]::IsInfinity($Seconds)) { return '--:--' }",
        "    $ts = [TimeSpan]::FromSeconds([Math]::Round($Seconds))",
        "    if ($ts.TotalHours -ge 1) {",
        "        return ('{0:d2}:{1:d2}:{2:d2}' -f [int]$ts.TotalHours, $ts.Minutes, $ts.Seconds)",
        "    }",
        "    return ('{0:d2}:{1:d2}' -f $ts.Minutes, $ts.Seconds)",
        "}",
        "",
        "# Pass 1: gather the full file list (so progress can show an accurate total).",
        "Write-Host ''",
        "Write-Host '  Scanning source folders...' -ForegroundColor Cyan",
        "$Files = @()",
        "$TotalBytes = [long]0",
        "foreach ($Job in $Jobs) {",
        "    Get-ChildItem -Path $Job.Src -Recurse -File | Where-Object {",
    ]
    if exclusions:
        # Match a full path COMPONENT (anchored ^...$) rather than an arbitrary
        # substring, so "finals" does not exclude "semifinals".
        lines.append(
            f"        -not ($_.FullName.Split([char[]]@('\\', '/')) "
            f'| Where-Object {{ $_ -match "^({excl_patterns})$" }})'
        )
    else:
        lines.append("        $true")
    lines += [
        "    } | ForEach-Object {",
        "        $RelPath = $_.FullName.Substring($Job.Src.Length).TrimStart('\\', '/')",
        "        $TotalBytes += $_.Length",
        "        $Files += [pscustomobject]@{ Source = $_.FullName; "
        "Target = (Join-Path $Job.Dst $RelPath); Size = $_.Length }",
        "    }",
        "}",
        "",
        "# Pass 2: copy with an inline progress bar.",
        "$Total = $Files.Count",
        "Write-Host ('  Found {0} file(s), {1}' -f $Total, (Format-Bytes $TotalBytes)) -ForegroundColor Gray",
        "Write-Host ('  Destination: {0}' -f $StagingRoot) -ForegroundColor DarkGray",
        "Write-Host ''",
        "",
        "# Decide whether we can drive the cursor for in-place redraws.",
        "$CanDraw = $false",
        "$OriginRow = 0",
        "try {",
        "    if (-not [Console]::IsOutputRedirected) {",
        "        [Console]::CursorVisible = $false",
        "        Write-Host ''   # reserve line 1 (stats)",
        "        Write-Host ''   # reserve line 2 (bar)",
        "        $OriginRow = [Console]::CursorTop - 2",
        "        $CanDraw = $true",
        "    }",
        "} catch { $CanDraw = $false }",
        "",
        "# Bar width adapts to the window, clamped to a sane range.",
        "$BarWidth = 40",
        "try { $BarWidth = [Math]::Max(20, [Math]::Min(50, [Console]::WindowWidth - 38)) } catch { }",
        "",
        "function Show-CopyProgress {",
        "    param(",
        "        [int]$Index, [int]$Total, [long]$Copied, [long]$TotalBytes, [double]$ElapsedSec, [switch]$Done",
        "    )",
        "    if ($TotalBytes -gt 0) { $frac = $Copied / $TotalBytes } else { $frac = $Index / [Math]::Max($Total, 1) }",
        "    if ($frac -gt 1) { $frac = 1 }",
        "    if ($frac -lt 0) { $frac = 0 }",
        "    $pct = [int][Math]::Floor($frac * 100)",
        "",
        "    if ($ElapsedSec -gt 0) { $rate = $Copied / $ElapsedSec } else { $rate = 0 }",
        "    if ($rate -gt 0 -and -not $Done) { $eta = ($TotalBytes - $Copied) / $rate } else { $eta = -1 }",
        "    if ($Done) { $eta = 0 }",
        "",
        "    $cells = [int][Math]::Round($frac * $BarWidth)",
        "    if ($cells -gt $BarWidth) { $cells = $BarWidth }",
        "    $filled = ([string]$Glyph.Full) * $cells",
        "    $empty = ([string]$Glyph.Light) * ($BarWidth - $cells)",
        "    if ($Done) { $barColor = 'Green' } else { $barColor = 'Cyan' }",
        "",
        "    $rest = ('   {0}/{1}   {2,3}%   {3} / {4}   {5}/s   ETA {6}' -f `",
        "        $Index, $Total, $pct, (Format-Bytes $Copied), (Format-Bytes $TotalBytes), `",
        "        (Format-Bytes $rate), (Format-Duration $eta))",
        "",
        "    if ($CanDraw) {",
        "        try {",
        "            $w = [Console]::WindowWidth",
        "            [Console]::SetCursorPosition(0, $OriginRow)",
        "",
        "            # Line 1: title accent + stats, padded to clear any previous frame.",
        "            Write-Host -NoNewline '  '",
        "            Write-Host -NoNewline 'WBPP staging copy' -ForegroundColor Cyan",
        "            $line1Len = 2 + 17 + $rest.Length",
        "            $pad1 = [Math]::Max(0, $w - 1 - $line1Len)",
        "            Write-Host ($rest + (' ' * $pad1)) -ForegroundColor Gray",
        "",
        "            # Line 2: the bar.",
        "            Write-Host -NoNewline '  '",
        "            Write-Host -NoNewline ([string]$Glyph.CapL) -ForegroundColor DarkGray",
        "            Write-Host -NoNewline $filled -ForegroundColor $barColor",
        "            Write-Host -NoNewline $empty -ForegroundColor DarkGray",
        "            Write-Host -NoNewline ([string]$Glyph.CapR) -ForegroundColor DarkGray",
        "            $line2Len = 2 + 1 + $BarWidth + 1",
        "            $pad2 = [Math]::Max(0, $w - 1 - $line2Len)",
        "            Write-Host (' ' * $pad2)",
        "        } catch {",
        "            $script:CanDraw = $false",
        "        }",
        "    }",
        "    if (-not $CanDraw) {",
        "        Write-Host ('  WBPP staging copy   {0}' -f $rest.Trim())",
        "    }",
        "}",
        "",
        "Write-Host '  Copying frames to WBPP staging' -ForegroundColor Cyan",
        "$sw = [System.Diagnostics.Stopwatch]::StartNew()",
        "$i = 0",
        "$CopiedBytes = [long]0",
        "$lastPct = -1",
        "$lastDrawMs = [long](-1000)",
        "foreach ($f in $Files) {",
        "    $i++",
        "    $TargetDir = Split-Path $f.Target -Parent",
        "    if (-not (Test-Path $TargetDir)) { New-Item -ItemType Directory -Force -Path $TargetDir | Out-Null }",
        "    Copy-Item -Path $f.Source -Destination $f.Target -Force",
        "    $CopiedBytes += $f.Size",
        "",
        "    $nowMs = $sw.ElapsedMilliseconds",
        "    $pctNow = [int][Math]::Floor((($CopiedBytes / [Math]::Max($TotalBytes, 1)) * 100))",
        "    if ($i -eq $Total -or $pctNow -ne $lastPct -or ($nowMs - $lastDrawMs) -ge 100) {",
        "        Show-CopyProgress -Index $i -Total $Total -Copied $CopiedBytes "
        "-TotalBytes $TotalBytes -ElapsedSec $sw.Elapsed.TotalSeconds",
        "        $lastPct = $pctNow",
        "        $lastDrawMs = $nowMs",
        "    }",
        "}",
        "$sw.Stop()",
        "Show-CopyProgress -Index $Total -Total $Total -Copied $TotalBytes "
        "-TotalBytes $TotalBytes -ElapsedSec $sw.Elapsed.TotalSeconds -Done",
        "if ($CanDraw) { try { [Console]::CursorVisible = $true } catch { } }",
        "",
        "Write-Host ''",
        "Write-Host ('  Done. Copied {0} file(s), {1} in {2}.' -f $Total, "
        "(Format-Bytes $TotalBytes), (Format-Duration $sw.Elapsed.TotalSeconds)) -ForegroundColor Green",
        "Write-Host ('  Open WBPP and use Add Directory on: {0}' -f $StagingRoot) -ForegroundColor Gray",
    ]
    return "\n".join(lines)


def generate_shell_script(copy_ops, staging_root, target_name, exclusions, session_dates, filename=None):
    """Generate a POSIX shell .sh copy script using rsync with a progress meter.

    Emits a colorized header/footer (colors auto-disabled when output is not a
    terminal) and copies each session folder through a shared copy_folder
    helper. rsync's --info=progress2 provides the per-folder transfer meter.

    User-derived values (staging root, source paths) are single-quoted via
    _sh_quote; the target name is passed to printf as a quoted %s argument so
    command substitution in any of them cannot execute.
    """
    excl_args = [f'--exclude="{e}"' for e in exclusions]
    total = len(copy_ops)
    script_name = filename or "wbpp_export.sh"
    # rsync source ($3) carries a trailing slash from the call site; dest is
    # derived inside the helper from the staging root and the entry name ($2).
    rsync_cmd = " ".join(
        ["rsync", "-a", "--copy-links", "--info=progress2", *excl_args, '"$3"', '"$dest/"']
    )
    lines = [
        "#!/usr/bin/env bash",
        "# WBPP Session Export",
        f"# Target: {target_name}",
        f"# Sessions: {', '.join(session_dates)}",
        "#",
        "# To run this script:",
        f"#   chmod +x {script_name} && ./{script_name}",
        "#",
        "# When it finishes, open PixInsight WBPP and use 'Add Directory' on the",
        f"# staging root: {staging_root}",
        "",
        "set -euo pipefail",
        "",
        "# Colors only when writing to a terminal (skipped when piped/redirected).",
        "if [ -t 1 ]; then",
        "    C_TITLE=$'\\033[36m'; C_DIM=$'\\033[90m'; C_OK=$'\\033[32m'; C_RESET=$'\\033[0m'",
        "else",
        "    C_TITLE=''; C_DIM=''; C_OK=''; C_RESET=''",
        "fi",
        "",
        f"STAGING_ROOT={_sh_quote(staging_root)}",
        'mkdir -p "$STAGING_ROOT"',
        "",
        f"TOTAL={total}",
        "printf '%s%s%s\\n' \"$C_TITLE\" 'WBPP staging copy' \"$C_RESET\"",
        f"printf '%s  Target: %s%s\\n' \"$C_DIM\" {_sh_quote(target_name)} \"$C_RESET\"",
        "printf '%s  %s session folder(s) -> %s%s\\n' \"$C_DIM\" \"$TOTAL\" \"$STAGING_ROOT\" \"$C_RESET\"",
        "printf '\\n'",
        "",
        "copy_folder() {",
        "    # $1 = index, $2 = entry name, $3 = source dir (with trailing slash)",
        "    printf '%s[%s/%s] %s%s\\n' \"$C_TITLE\" \"$1\" \"$TOTAL\" \"$2\" \"$C_RESET\"",
        '    local dest="$STAGING_ROOT/$2"',
        '    mkdir -p "$dest"',
        f"    {rsync_cmd}",
        "    printf '\\n'",
        "}",
        "",
    ]
    for idx, (src, entry_name) in enumerate(copy_ops, start=1):
        lines.append(
            f"copy_folder {idx} {_sh_quote(entry_name)} {_sh_quote(src + '/')}"
        )
    lines += [
        "",
        f"printf '%s%s%s\\n' \"$C_OK\" 'Done. Copied {total} folder(s).' \"$C_RESET\"",
        "printf '  Open WBPP and use Add Directory on: %s\\n' \"$STAGING_ROOT\"",
    ]
    return "\n".join(lines)
