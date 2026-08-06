// Clipboard formats for the Copy Frame List export.
//
// Given the quality verdicts from wbppQualityFilter, selects the good or bad
// frame set (with per-row overrides) and renders it as one of three clipboard
// payloads: a Windows Explorer search string, a plain newline name list, or a
// move/delete script (PowerShell or bash).
//
// Identity is the bare `file_name`, not the full path: the formats exist to
// find files in whatever staging folder the user copied them to, where the
// catalog's paths mean nothing. The caveat is that the same name can exist in
// several folders, so the scripts search recursively, list every match before
// acting, and require confirmation; the modal shows `file_path` per row so the
// user can see which physical file a name refers to.

import type { FrameVerdict } from "./wbppQualityFilter";
import type { PathOs } from "../components/wbpp/paths";

export type FrameListMode = "good" | "bad";

export interface FrameSelectionOptions {
  mode: FrameListMode;
  /** Good mode only: whether unmeasured frames join the list. Ignored in bad mode. */
  includeUnmeasured: boolean;
  /** Sparse per-row override keyed by overrideKey(verdict); value = final inclusion. */
  overrides: Record<string, boolean>;
}

/**
 * Identity of a verdict row for override purposes. Bare source_relative is not
 * unique across sessions (the same relative path can appear under two selected
 * dates), so the key pairs it with the verdict's session date: a hand edit on
 * one row must never flip its twin in another session.
 */
export function overrideKey(v: FrameVerdict): string {
  return `${v.sessionDate}|${v.frame.source_relative}`;
}

/**
 * Whether a verdict lands in the copy list. Bad mode is strict failures only:
 * unmeasured frames were never rejected by a gate, so they are never "bad".
 * Good mode is passes, plus unmeasured while the toggle is on. A per-row
 * override, when present, replaces the computed answer entirely.
 */
export function isIncluded(v: FrameVerdict, opts: FrameSelectionOptions): boolean {
  const computed =
    opts.mode === "bad"
      ? v.reason === "fail"
      : v.reason === "pass" || (v.reason === "unmeasured" && opts.includeUnmeasured);
  return opts.overrides[overrideKey(v)] ?? computed;
}

export function selectedFrames(
  verdicts: FrameVerdict[],
  opts: FrameSelectionOptions,
): FrameVerdict[] {
  return verdicts.filter((v) => isIncluded(v, opts));
}

// Windows Explorer search-box syntax: each name double-quoted, OR-joined.
export function explorerSearchString(names: string[]): string {
  return names.map((n) => `"${n}"`).join(" OR ");
}

export function plainNameList(names: string[]): string {
  return names.join("\n");
}

// PowerShell single-quoted literal: embedded quotes are doubled.
function psQuote(s: string): string {
  return `'${s.replace(/'/g, "''")}'`;
}

// POSIX shell single-quoted literal: close, escaped quote, reopen.
function bashQuote(s: string): string {
  return `'${s.replace(/'/g, "'\\''")}'`;
}

// The bash script feeds each name to `find -name`, which treats * ? [ ] \ as
// glob metacharacters. Backslash-escape them (backslash first) so a literal
// file name like "weird[1].fits" matches itself and nothing else.
function escapeFindGlob(s: string): string {
  return s.replace(/\\/g, "\\\\").replace(/[*?[\]]/g, (c) => `\\${c}`);
}

/**
 * A self-contained script that finds each listed name under the base folder
 * and moves every match into a `_rejected` subfolder (or deletes it with the
 * delete switch), after printing the full match/missing report and asking for
 * confirmation. Re-runs are safe: files already under `_rejected` are skipped.
 */
export function moveScript(names: string[], baseFolder: string, os: PathOs): string {
  return os === "windows"
    ? powershellScript(names, baseFolder)
    : bashScript(names, baseFolder);
}

function powershellScript(names: string[], baseFolder: string): string {
  const nameBlock =
    names.length === 0 ? "" : names.map((n) => `  ${psQuote(n)}`).join(",\n") + "\n";
  return `# GalactiLog frame list script. Moves the listed frames into a _rejected
# subfolder under the base folder. Run with -Delete to delete instead.
param([switch]$Delete)

$base = ${psQuote(baseFolder)}
$names = @(
${nameBlock})

if (-not (Test-Path -LiteralPath $base)) {
  Write-Host "Base folder not found: $base"
  exit 1
}

$all = Get-ChildItem -LiteralPath $base -Recurse -File
$dest = Join-Path $base '_rejected'
$plan = @()
$notFound = @()
foreach ($n in $names) {
  $hits = @($all | Where-Object { $_.Name -eq $n -and $_.DirectoryName -ne $dest })
  if ($hits.Count -eq 0) { $notFound += $n; continue }
  if ($hits.Count -gt 1) {
    Write-Host "WARNING: $n matches $($hits.Count) files; all will be processed:"
    foreach ($h in $hits) { Write-Host "  $($h.FullName)" }
  }
  $plan += $hits
}

Write-Host ""
Write-Host "$($plan.Count) files matched, $($notFound.Count) not found."
foreach ($m in $notFound) { Write-Host "  missing: $m" }
if ($plan.Count -eq 0) { exit 0 }

$action = if ($Delete) { 'DELETE' } else { "move to $dest" }
$answer = Read-Host "Proceed to $action $($plan.Count) files? (y/N)"
if ($answer -ne 'y') { Write-Host 'Aborted.'; exit 0 }

if (-not $Delete) { New-Item -ItemType Directory -Force -Path $dest | Out-Null }
foreach ($f in $plan) {
  if ($Delete) {
    Remove-Item -LiteralPath $f.FullName -Force
  } else {
    $target = Join-Path $dest $f.Name
    $i = 1
    while (Test-Path -LiteralPath $target) {
      $target = Join-Path $dest ("{0}_{1}{2}" -f [IO.Path]::GetFileNameWithoutExtension($f.Name), $i, [IO.Path]::GetExtension($f.Name))
      $i++
    }
    Move-Item -LiteralPath $f.FullName -Destination $target
  }
}
Write-Host 'Done.'
`;
}

function bashScript(names: string[], baseFolder: string): string {
  const nameBlock =
    names.length === 0 ? "" : names.map((n) => bashQuote(escapeFindGlob(n))).join("\n") + "\n";
  return `#!/usr/bin/env bash
# GalactiLog frame list script. Moves the listed frames into a _rejected
# subfolder under the base folder. Run with --delete to delete instead.
set -u
base=${bashQuote(baseFolder)}
delete=0
[ "\${1:-}" = "--delete" ] && delete=1
names=(
${nameBlock})
[ -d "$base" ] || { echo "Base folder not found: $base"; exit 1; }
dest="$base/_rejected"
plan=()
missing=0
for n in "\${names[@]}"; do
  mapfile -t hits < <(find "$base" -path "$dest" -prune -o -type f -name "$n" -print)
  if [ "\${#hits[@]}" -eq 0 ]; then echo "missing: $n"; missing=$((missing+1)); continue; fi
  if [ "\${#hits[@]}" -gt 1 ]; then
    echo "WARNING: $n matches \${#hits[@]} files; all will be processed:"
    printf '  %s\\n' "\${hits[@]}"
  fi
  plan+=("\${hits[@]}")
done
echo "\${#plan[@]} files matched, $missing not found."
[ "\${#plan[@]}" -eq 0 ] && exit 0
if [ "$delete" -eq 1 ]; then action="DELETE"; else action="move to $dest"; fi
read -r -p "Proceed to $action \${#plan[@]} files? (y/N) " answer
[ "$answer" = "y" ] || { echo "Aborted."; exit 0; }
[ "$delete" -eq 1 ] || mkdir -p "$dest"
for f in "\${plan[@]}"; do
  if [ "$delete" -eq 1 ]; then rm -f -- "$f"
  else
    t="$dest/$(basename "$f")"
    i=1
    while [ -e "$t" ]; do t="$dest/$(basename "\${f%.*}")_$i.\${f##*.}"; i=$((i+1)); done
    mv -- "$f" "$t"
  fi
done
echo "Done."
`;
}
