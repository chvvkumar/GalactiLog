"""Panel token/pattern parsing: pure regex helpers, no DB or I/O.

Split out of ``mosaic_detection.py`` (Task 5 of the phase-6 file-size
retrofit); re-exported there so every existing import site keeps working.
"""

import re


# ---------------------------------------------------------------------------
# Stage 1: name-path token matching
# ---------------------------------------------------------------------------

# Tile convention: "<base>_<row>-<col>" e.g. IC1805_1-1. The row-col pair is
# the panel number. Anchored to end-of-string so trailing tokens aren't lost.
_TILE_RE = re.compile(r"^(.+?)[\s_-]+(\d+-\d+)\s*$")


def _keyword_regex(keywords: list[str]) -> re.Pattern:
    kw_pattern = "|".join(re.escape(k) for k in keywords)
    # Capture the keyword token itself (group 2) so the stored panel_pattern can
    # include it for unambiguous matching.
    return re.compile(
        rf"^(.+?)\s*[-_\s]?\s*({kw_pattern})\s*[-_\s]?\s*(\d+)\s*$",
        re.IGNORECASE,
    )


def match_panel_token_full(
    name: str, keywords: list[str]
) -> tuple[str, str, str | None] | None:
    """Return (base_name, panel_number, keyword) if name carries a token.

    ``keyword`` is the matched keyword (e.g. "Panel"/"P") for keyword matches,
    or None for tile-pattern (_R-C) matches. Tries the keyword pattern first,
    then the tile pattern. Returns None when there is no panel token.
    """
    if not name:
        return None
    if keywords:
        m = _keyword_regex(keywords).match(name)
        if m:
            return m.group(1).strip(), m.group(3), m.group(2)
    m = _TILE_RE.match(name)
    if m:
        return m.group(1).strip(), m.group(2), None
    return None


def match_panel_token(name: str, keywords: list[str]) -> tuple[str, str] | None:
    """Return (base_name, panel_number) if name carries a panel/tile token.

    Tries the keyword pattern (Panel N / P N) first, then the _R-C tile
    pattern. Returns None when the name has no panel token (never-absorb).
    """
    result = match_panel_token_full(name, keywords)
    if result is None:
        return None
    base, num, _kw = result
    return base, num


def strip_panel_token(name: str, keywords: list[str]) -> str | None:
    """Return the stripped base name, or None if no panel token present."""
    result = match_panel_token(name, keywords)
    return result[0] if result else None


def build_panel_pattern(base_name: str, keyword: str | None, num: str) -> str:
    """Build an ILIKE pattern that uniquely identifies a panel's OBJECT.

    Keyword candidates include the matched keyword token so the pattern does not
    match a sibling panel of the same base (important when the base itself
    contains digits, e.g. "Sh2 119"). Tile candidates carry the R-C token, which
    is already unique within the base.

    NOTE: this pattern is a cheap SQL pre-filter only. Because the trailing
    "%" imposes no boundary after ``num``, it also matches sibling panels for
    which ``num`` is a prefix (panel "1" also matches "Panel 12"). Callers
    MUST re-parse every ILIKE-matched OBJECT string with
    ``object_matches_panel`` (or ``match_panel_token_full`` directly) and keep
    only exact matches; see AUD-008.
    """
    if keyword:
        return f"%{base_name}%{keyword}%{num}%"
    return f"%{base_name}%{num}%"


def panel_number_from_label(label: str) -> str:
    """Extract the panel-number token from a stored panel label.

    Labels are generated as "Panel {num}" (see ``_panel_label``); a manually
    relabeled panel that no longer follows this convention falls back to
    using the whole label, which simply never matches a real OBJECT token
    (same as pre-fix behavior for that edge case).
    """
    return label.split()[-1] if label and label.startswith("Panel ") else label


def object_matches_panel(
    object_name: str | None, keywords: list[str], expected_num: str
) -> bool:
    """True iff ``object_name`` genuinely belongs to the panel numbered
    ``expected_num``, re-parsed with the same tokenizer used to build panel
    candidates (``match_panel_token_full``).

    This is the re-parse step every ``build_panel_pattern``/ILIKE call site
    must apply to its SQL-matched rows: the ILIKE pattern is only a cheap
    pre-filter and can match sibling panels whose number the target number is
    a prefix of (e.g. pattern for panel "1" also matches OBJECT "...Panel
    12"). Comparing the exact parsed number closes that gap.
    """
    if not object_name:
        return False
    match = match_panel_token_full(object_name, keywords)
    if match is None:
        return False
    return match[1] == expected_num


def exact_panel_regex(keywords: list[str], expected_num: str) -> str:
    """POSIX regex (for use with PostgreSQL's ``~*`` operator against the
    OBJECT header) that only matches when the trailing panel-number token is
    exactly ``expected_num``, not merely a prefix of a longer number.

    Used as an additional SQL-level filter alongside the existing ILIKE
    pre-filter in aggregate queries where fetching every row into Python to
    re-parse with ``match_panel_token_full`` would be a larger rewrite (see
    AUD-008). Mirrors the same end-of-string, optional-trailing-whitespace
    boundary ``match_panel_token_full`` uses, so "1" no longer matches
    "...Panel 12" while "...Panel 1 " (trailing whitespace) still matches.
    """
    num_re = re.escape(expected_num)
    if keywords:
        kw_alt = "|".join(re.escape(k) for k in keywords)
        return rf"({kw_alt})\s*[-_]?\s*{num_re}\s*$"
    return rf"{num_re}\s*$"


def _panel_label(num: str) -> str:
    return f"Panel {num}"
