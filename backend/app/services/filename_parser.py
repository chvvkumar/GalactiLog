"""Extract target names from astrophotography filenames.

Strips noise tokens (frame types, filters, exposure, gain, temperature,
binning, cameras, dates, sequence numbers, etc.) to isolate the target name.
"""

from __future__ import annotations

import re
from pathlib import Path

# ---------------------------------------------------------------------------
# Compiled regex patterns (module-level for performance)
# ---------------------------------------------------------------------------

EXTENSIONS_RE = re.compile(
    r"\.(fits|fit|fts|xisf|ser)$", re.IGNORECASE
)

UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)

# Date/time combo: 20230212-195555 or 2023-03-20T21-04-17
DATETIME_COMBO_RE = re.compile(
    r"\d{4}-?\d{2}-?\d{2}[T-]\d{2}-?\d{2}-?\d{2}"
)

# Standalone 8-digit date: YYYYMMDD
DATE8_RE = re.compile(r"(?<![0-9A-Za-z])\d{8}(?![0-9A-Za-z])")

# Frame types (as token match)
FRAME_TYPES_RE = re.compile(
    r"^(?:Light|Dark|Flat|Bias|DarkFlat|FlatDark|Snapshot|Master\w+)$",
    re.IGNORECASE,
)

# LP / dual-band filter tokens (lowercased for lookup)
LP_FILTER_TOKENS = {
    "l-pro", "l-enhance", "l-extreme", "l-ultimate",
    "dualband", "hoo", "sho",
}

# Multi-char filter tokens (lowercased)
FILTER_TOKENS = {
    "lum", "luminance", "red", "green", "blue", "rgb", "nofilter", "clear",
    "ha", "h-alpha", "halpha", "oiii", "o3", "sii", "s2", "nii", "hb", "hbeta",
    "cls", "uhc",
}

# Single-letter filters
SINGLE_LETTER_FILTERS = {"l", "r", "g", "b"}

# Exposure: number + time unit.  "s" alone counts too (e.g., 300s).
EXPOSURE_RE = re.compile(
    r"^\d+\.?\d*(?:s|secs?|ms|min)$", re.IGNORECASE
)

# Gain/offset/ISO
GAIN_OFFSET_RE = re.compile(
    r"^(?:Gain\d+|Offset\d+|ISO\d+)$", re.IGNORECASE
)

# Short gain: G139 (capital G + 2+ digits, standalone token)
SHORT_GAIN_RE = re.compile(r"^G\d{2,}$")

# Compact gain/offset: 110G (digits + G), 50Of (digits + Of)
COMPACT_GAIN_RE = re.compile(r"^\d+G$")
COMPACT_OFFSET_RE = re.compile(r"^\d+Of$", re.IGNORECASE)

# Temperature: -10C, -10.0C, -10degC, -20C
TEMP_NEG_RE = re.compile(
    r"^-\d+\.?\d*(?:deg)?C$", re.IGNORECASE
)

# Temperature: T-25, T20
TEMP_T_RE = re.compile(r"^T-?\d+\.?\d*$")

# Binning
BINNING_RE = re.compile(r"^(?:Bin[1-4]|[1-4]x[1-4])$", re.IGNORECASE)

# Camera models (includes manufacturer prefixes that appear as separate tokens)
CAMERA_RE = re.compile(
    r"^(?:ASI\d{3,4}\w*|QHY\d{3,4}\w*|\d{4}M[CP]?"
    r"|Canon\w*|Nikon\w*|Sony\w*|EOS\w*|DSLR"
    r"|Atik\w*|FLI\w*|SBIG\w*|Moravian\w*|PlayerOne\w*"
    r"|ZWO|Pro)$",
    re.IGNORECASE,
)

# HFR / FWHM (e.g. 1.56HFR)
HFR_FWHM_RE = re.compile(r"^\d+\.?\d*(?:HFR|FWHM)$", re.IGNORECASE)

# Panel / pier
PANEL_PIER_RE = re.compile(
    r"^(?:Panel\d+|Pane\d+|Tile\d+|Mosaic\d+|PierEast|PierWest|sop-east|sop-west)$",
    re.IGNORECASE,
)

# Angle/degree values: 93.74deg
DEGREE_RE = re.compile(r"^\d+\.?\d*deg$", re.IGNORECASE)

# Sky Quality: SQA55, SQM20.5
SKY_QUALITY_RE = re.compile(r"^SQ[AM]\d+\.?\d*$", re.IGNORECASE)

# Misc tokens
MISC_RE = re.compile(
    r"^(?:Stack\d*|USB\d+|Dithered|NoDither|HighGain|LowNoise|Normal|Unity"
    r"|frame\d*|image|RMS\w*|SQM\w*)$",
    re.IGNORECASE,
)

# SGPro sequence: f202
FSEQ_RE = re.compile(r"^f\d+$", re.IGNORECASE)

# Purely numeric
NUMERIC_RE = re.compile(r"^\d+$")


def _is_noise_token(token: str) -> bool:
    """Return True if this token is noise that should be stripped."""
    if FRAME_TYPES_RE.match(token):
        return True
    low = token.lower()
    if low in FILTER_TOKENS or low in LP_FILTER_TOKENS:
        return True
    if EXPOSURE_RE.match(token):
        return True
    if GAIN_OFFSET_RE.match(token):
        return True
    if SHORT_GAIN_RE.match(token):
        return True
    if COMPACT_GAIN_RE.match(token):
        return True
    if COMPACT_OFFSET_RE.match(token):
        return True
    if DEGREE_RE.match(token):
        return True
    if SKY_QUALITY_RE.match(token):
        return True
    if TEMP_NEG_RE.match(token):
        return True
    if TEMP_T_RE.match(token):
        return True
    if BINNING_RE.match(token):
        return True
    if CAMERA_RE.match(token):
        return True
    if HFR_FWHM_RE.match(token):
        return True
    if PANEL_PIER_RE.match(token):
        return True
    if MISC_RE.match(token):
        return True
    if FSEQ_RE.match(token):
        return True
    return False


# Catalog ID pattern: prefix + digits + hyphen + digits (Sh2-132, IC2-14, etc.)
CATALOG_HYPHEN_RE = re.compile(r"^[A-Za-z]+\d+-\d+$")


def _tokenize(name: str) -> list[str]:
    """Split a cleaned filename into tokens.

    - Splits on underscores
    - Merges adjacent tokens that form "number + unit" patterns (e.g., "30" + "secs")
    - Handles hyphens: preserves catalog IDs (Sh2-132) and LP filters (L-eXtreme),
      splits other standalone hyphens
    """
    # Split on underscores first, then split each part on spaces
    # (handles filenames with spaces like "ZWO ASI2600MM Pro")
    underscore_parts = [p.strip() for p in name.split("_") if p.strip()]
    raw_parts = []
    for part in underscore_parts:
        if " " in part:
            raw_parts.extend(s for s in part.split() if s)
        else:
            raw_parts.append(part)

    # Merge tokens where a bare number is followed by a time-unit token
    # e.g., ["30", "secs"] -> ["30secs"]
    merged = []
    i = 0
    while i < len(raw_parts):
        part = raw_parts[i]
        # Check if current is a number and next is a time unit
        if (
            i + 1 < len(raw_parts)
            and re.match(r"^\d+\.?\d*$", part)
            and re.match(r"^(?:s|secs?|ms|min)$", raw_parts[i + 1], re.IGNORECASE)
        ):
            merged.append(part + raw_parts[i + 1])
            i += 2
            continue
        merged.append(part)
        i += 1

    # Now handle hyphens within each token
    tokens = []
    for part in merged:
        if "-" not in part:
            tokens.append(part)
            continue

        low = part.lower()

        # LP filter (L-eXtreme, L-Pro, etc.)
        if low in LP_FILTER_TOKENS:
            tokens.append(part)
            continue

        # Catalog ID with hyphen (Sh2-132)
        if CATALOG_HYPHEN_RE.match(part):
            tokens.append(part)
            continue

        # Temperature pattern (-10C, -10.0C, -10degC)
        if TEMP_NEG_RE.match(part):
            tokens.append(part)
            continue

        # Temperature T-25
        if TEMP_T_RE.match(part):
            tokens.append(part)
            continue

        # Panel/pier with hyphen (sop-east)
        if PANEL_PIER_RE.match(part):
            tokens.append(part)
            continue

        # MaxIm DL pattern: M27-001R (target-seqFilter)
        # Two parts separated by hyphen where second starts with digits
        sub = part.split("-")
        if len(sub) == 2 and re.match(r"^\d+[A-Za-z]?$", sub[1]):
            # Keep only the first part (target name)
            tokens.append(sub[0])
            continue

        # Generic: split on hyphens
        for sp in sub:
            sp = sp.strip()
            if sp:
                tokens.append(sp)

    return tokens


# Prefixed directory patterns: Target_NGC 2264, Object_M31
_PREFIXED_DIR_RE = re.compile(
    r"^(?:Target|Object)[_\s]+(.+)$", re.IGNORECASE
)

# Directory components that are definitely NOT target names
_NOISE_DIR_RE = re.compile(
    r"^(?:"
    r"LIGHT|DARK|FLAT|BIAS|DARKFLAT|FLATDARK"  # frame types
    r"|Date[_\s].*"  # Date_ prefixed dirs
    r"|Angle[_\s].*"  # Angle_ prefixed dirs
    r"|Filter[_\s].*"  # Filter_ prefixed dirs
    r"|\d{4}"  # bare year (2024, 2025, 2026)
    r"|\d{4}-\d{2}-\d{2}"  # ISO date
    r"|\d{8}"  # YYYYMMDD
    r"|fits|data|images?|captures?|subs?|masters?"  # generic folder names
    r"|app|home|mnt|media|volumes?"  # system mount points
    r")$",
    re.IGNORECASE,
)


def _is_noise_dir(dirname: str) -> bool:
    """Return True if this directory name is noise (not a target)."""
    if _NOISE_DIR_RE.match(dirname):
        return True
    # Camera model as directory name
    if CAMERA_RE.match(dirname):
        return True
    # Multi-word camera names with spaces (e.g., "ZWO ASI2600MM Pro")
    space_tokens = dirname.split()
    if len(space_tokens) > 1 and any(CAMERA_RE.match(t) for t in space_tokens):
        return True
    return False


def _extract_target_from_path(filepath: Path) -> str | None:
    """Check directory components for target name patterns.

    Scans all directory components looking for target names. Uses two
    strategies:

    1. **Prefixed directories** -- ``Target_NGC 2264``, ``Object_M31``
       are extracted directly (highest confidence).
    2. **Plain directory names** -- any directory component that isn't
       a known noise pattern (date, frame type, camera, etc.) is
       treated as a potential target. The deepest (most specific) match
       wins.

    Returns the best target name found, or None.
    """
    # Exclude the filename itself and the root/drive
    dirs = filepath.parent.parts

    # First pass: look for prefixed directories (most reliable)
    for part in dirs:
        m = _PREFIXED_DIR_RE.match(part)
        if m:
            return m.group(1).strip()

    # Second pass: find the deepest non-noise directory component
    # Iterate in reverse (deepest first) to find the most specific match
    for part in reversed(dirs):
        if not part or len(part) < 2:
            continue
        if _is_noise_dir(part):
            continue
        # Skip purely numeric dirs and common path roots
        if part.replace("-", "").replace(".", "").isdigit():
            continue
        # This looks like it could be a target name
        return part

    return None


def extract_target_from_filename(filepath: Path) -> str | None:
    """Extract the target name from an astrophotography file path.

    First checks directory components for explicit target patterns
    (e.g., N.I.N.A.'s ``Target_<name>`` folders), then falls back to
    parsing the filename itself.

    Returns the cleaned target string, or None if no meaningful target
    name can be extracted.
    """
    # Try path-based extraction first (most reliable)
    path_target = _extract_target_from_path(filepath)
    if path_target:
        return path_target

    name = filepath.name

    # 1. Strip known extensions
    name = EXTENSIONS_RE.sub("", name)

    # 3. Remove UUID patterns
    name = UUID_RE.sub("", name)

    # 4. Remove date/time patterns on the raw string (before tokenizing)
    name = DATETIME_COMBO_RE.sub("", name)
    name = DATE8_RE.sub("", name)

    # Tokenize (splits on _, merges number+unit, handles hyphens)
    tokens = _tokenize(name)

    # First pass: merge single-letter catalog prefixes with following numbers.
    # "M" + "106" -> "M 106" (Messier designation from Ekos-style filenames).
    merged_tokens: list[str] = []
    i = 0
    while i < len(tokens):
        token = tokens[i]
        # Single letter that could be a catalog prefix (M for Messier)
        # followed by a numeric token
        if (
            len(token) == 1
            and token.upper() == "M"
            and i + 1 < len(tokens)
            and NUMERIC_RE.match(tokens[i + 1])
        ):
            merged_tokens.append(f"{token} {tokens[i + 1]}")
            i += 2
            continue
        merged_tokens.append(token)
        i += 1

    # Filter out noise tokens
    kept: list[str] = []
    for token in merged_tokens:
        if _is_noise_token(token):
            continue
        if NUMERIC_RE.match(token):
            continue
        # Single-letter filter check
        if len(token) == 1 and token.lower() in SINGLE_LETTER_FILTERS:
            continue
        kept.append(token)

    # Remove trailing numeric tokens
    while kept and NUMERIC_RE.match(kept[-1]):
        kept.pop()
    while kept and NUMERIC_RE.match(kept[0]):
        kept.pop(0)

    # Join with spaces
    result = " ".join(kept).strip()

    # Return cleaned string if >= 2 chars and not purely numeric
    if len(result) < 2 or result.replace(" ", "").isdigit():
        return None

    return result
