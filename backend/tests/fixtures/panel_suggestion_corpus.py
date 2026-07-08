"""Regression-fixture corpus for suggestion/detection-side panel matching.

Phase 5 (docs/retrofit-roadmap.md) rewrote *accepted-mosaic* panel stats to
exact ``Image.panel_id`` joins, but deliberately left the *suggestion-side*
matching untouched: ``match_panel_token_full``/``build_panel_pattern``/
``object_matches_panel``/``exact_panel_regex`` (``app.services.mosaic_detection``)
and the grouping logic those feed (``group_panels``/``detect_mosaic_panels``,
and ``get_suggestions`` in ``app.api.mosaics``) all still parse OBJECT headers
and ILIKE-prefilter the same way they did before the phase.

This corpus exists to prove that claim, not to assume it. Every expected
value below is a literal, hand-verified constant -- NOT computed by calling
the real functions at collection time -- so a future change to the tokenizer
or grouping logic (in this phase or a later one) shows up as a failing
assertion against a value a human wrote down, rather than the test silently
tracking whatever the code happens to do today. If a change here is ever
needed, it must be a deliberate, reviewed edit to this file's literals, with
the reason spelled out in the commit message -- not a mechanical
"regenerate the golden output" step.

Categories covered, per the Task 6 brief:
  - simple non-mosaic objects (no panel token)
  - keyword-style panel tokens, including the AUD-008 sibling-number
    collision ("Panel 1" vs "Panel 12")
  - tile-style tokens ("<base>_<row>-<col>")
  - multiple configured keywords (default ["Panel", "P"], plus a custom
    keyword to prove the corpus isn't hardcoded to the defaults)
  - edge cases: leading/trailing whitespace, mixed case, and
    hyphen/underscore/space separators
"""

# ---------------------------------------------------------------------------
# TOKEN_CASES: match_panel_token_full(object_name, keywords) -> expected
#
# expected is either None (no panel token) or (base_name, panel_number,
# keyword_or_None), exactly as match_panel_token_full returns it.
# ---------------------------------------------------------------------------

TOKEN_CASES = [
    # -- simple non-mosaic objects: no panel token at all --
    ("simple_object_no_token", ["Panel", "P"], "NGC 7000", None),
    ("simple_object_no_token_letters_only", ["Panel", "P"], "M31", None),

    # -- keyword-style tokens, default keywords --
    ("keyword_panel_1", ["Panel", "P"], "IC1805 Panel 1", ("IC1805", "1", "Panel")),
    # AUD-008: "Panel 1" and "Panel 12" must parse to DIFFERENT panel
    # numbers, not have "12" swallowed as a prefix match of "1".
    ("keyword_panel_12_sibling", ["Panel", "P"], "IC1805 Panel 12", ("IC1805", "12", "Panel")),
    ("keyword_short_form_p", ["Panel", "P"], "IC1805 P 12", ("IC1805", "12", "P")),

    # -- tile-style tokens --
    ("tile_1_1", ["Panel", "P"], "IC1805_1-1", ("IC1805", "1-1", None)),
    ("tile_1_2", ["Panel", "P"], "IC1805_1-2", ("IC1805", "1-2", None)),

    # -- multiple configured keywords, including a custom (non-default) one --
    ("custom_keyword_tile", ["Tile"], "Sh2-119 Tile 3", ("Sh2-119", "3", "Tile")),
    ("custom_keyword_alongside_defaults", ["Panel", "P", "Tile"], "CustomTile Tile 1", ("CustomTile", "1", "Tile")),

    # -- edge cases: whitespace, case, separators --
    ("leading_trailing_whitespace", ["Panel", "P"], "  M31 Panel 2 ", ("M31", "2", "Panel")),
    ("mixed_case_keyword_and_object", ["Panel", "P"], "m31 panel 3", ("m31", "3", "panel")),
    ("hyphen_separator", ["Panel", "P"], "IC1805-Panel-4", ("IC1805", "4", "Panel")),
    ("underscore_separator", ["Panel", "P"], "IC1805_Panel_5", ("IC1805", "5", "Panel")),
    ("space_separator", ["Panel", "P"], "IC1805 Panel 6", ("IC1805", "6", "Panel")),

    # -- empty keyword list: only the tile pattern still matches --
    ("empty_keywords_tile_still_matches", [], "IC1805_2-3", ("IC1805", "2-3", None)),
    ("empty_keywords_keyword_form_no_longer_matches", [], "IC1805 Panel 7", None),

    # -- falsy/missing OBJECT strings --
    ("empty_string_object", ["Panel", "P"], "", None),
    ("none_object", ["Panel", "P"], None, None),
]


# ---------------------------------------------------------------------------
# PATTERN_CASES: build_panel_pattern / object_matches_panel / exact_panel_regex
#
# Each case names a panel (base, keyword, num) and a candidate OBJECT string
# to re-check it against. ``ilike_prefilter_matches`` records whether the
# ILIKE pattern (a cheap substring prefilter) matches the candidate -- true
# for both the exact panel and any sibling panel whose number the target
# number is a prefix of. ``exact_match_expected`` is the ground truth after
# the exact recheck (object_matches_panel / exact_panel_regex boundary
# check), which is what callers must actually rely on.
# ---------------------------------------------------------------------------

PATTERN_CASES = [
    {
        "case_id": "sibling_1_vs_12_ilike_prefilter_over_matches",
        "keywords": ["Panel", "P"],
        "base": "IC1805",
        "keyword": "Panel",
        "num": "1",
        "expected_pattern": "%IC1805%Panel%1%",
        "candidate_object": "IC1805 Panel 12",
        "ilike_prefilter_matches": True,
        "exact_match_expected": False,
        "exact_panel_regex": r"(Panel|P)\s*[-_]?\s*1\s*$",
    },
    {
        "case_id": "sibling_1_exact_match",
        "keywords": ["Panel", "P"],
        "base": "IC1805",
        "keyword": "Panel",
        "num": "1",
        "expected_pattern": "%IC1805%Panel%1%",
        "candidate_object": "IC1805 Panel 1",
        "ilike_prefilter_matches": True,
        "exact_match_expected": True,
        "exact_panel_regex": r"(Panel|P)\s*[-_]?\s*1\s*$",
    },
    {
        "case_id": "tile_pattern_no_keyword",
        "keywords": [],
        "base": "IC1805",
        "keyword": None,
        "num": "1-1",
        "expected_pattern": "%IC1805%1-1%",
        "candidate_object": "IC1805_1-1",
        "ilike_prefilter_matches": True,
        "exact_match_expected": True,
        "exact_panel_regex": r"1\-1\s*$",
    },
    {
        "case_id": "unrelated_object_no_match_at_all",
        "keywords": ["Panel", "P"],
        "base": "IC1805",
        "keyword": "Panel",
        "num": "1",
        "expected_pattern": "%IC1805%Panel%1%",
        "candidate_object": "NGC 7000",
        "ilike_prefilter_matches": False,
        "exact_match_expected": False,
        "exact_panel_regex": r"(Panel|P)\s*[-_]?\s*1\s*$",
    },
]


# ---------------------------------------------------------------------------
# GROUPING_CASES: group_panels(targets, keywords) -> expected PanelGroup list
#
# Each scenario is a self-contained call to group_panels with no position
# data (center=None everywhere), so grouping is driven purely by Stage 1
# (name-path token matching) -- deterministic and independent of any RA/DEC
# fixture data. ``expected_groups`` lists, per group, the base name, the
# sorted set of panel numbers, confidence, discovery_source, and sorted
# panel labels group_panels actually returns today.
# ---------------------------------------------------------------------------

GROUPING_CASES = [
    {
        "name": "keyword_style_two_panel_target",
        "keywords": ["Panel", "P"],
        "targets": [
            {
                "target_id": "t-veil",
                "object_names": ["Veil Nebula Panel 1", "Veil Nebula Panel 2"],
                "center": None,
                "fov_arcmin": None,
            },
        ],
        "expected_groups": [
            {
                "base_name": "Veil Nebula",
                "panel_numbers": ["1", "2"],
                "confidence": "low",
                "discovery_source": "name",
                "panel_labels": ["Panel 1", "Panel 2"],
            },
        ],
    },
    {
        "name": "tile_style_two_panel_target",
        "keywords": ["Panel", "P"],
        "targets": [
            {
                "target_id": "t-tile",
                "object_names": ["TilePair_1-1", "TilePair_1-2"],
                "center": None,
                "fov_arcmin": None,
            },
        ],
        "expected_groups": [
            {
                "base_name": "TilePair",
                "panel_numbers": ["1-1", "1-2"],
                "confidence": "low",
                "discovery_source": "name",
                "panel_labels": ["Panel 1-1", "Panel 1-2"],
            },
        ],
    },
    {
        # AUD-008 sibling numbers: still grouped together as two panels of
        # the SAME target (that's correct -- they really are two distinct
        # panels of one mosaic); the bug this corpus guards against is the
        # ACCEPTED-MOSAIC *query* side assigning a frame to the wrong panel,
        # not the suggestion-side grouping shown here.
        "name": "sibling_panel_numbers_grouped_as_one_target",
        "keywords": ["Panel", "P"],
        "targets": [
            {
                "target_id": "t-sibling",
                "object_names": ["Sh2119 Panel 1", "Sh2119 Panel 12"],
                "center": None,
                "fov_arcmin": None,
            },
        ],
        "expected_groups": [
            {
                "base_name": "Sh2119",
                "panel_numbers": ["1", "12"],
                "confidence": "low",
                "discovery_source": "name",
                "panel_labels": ["Panel 1", "Panel 12"],
            },
        ],
    },
    {
        "name": "custom_keyword_two_panel_target",
        "keywords": ["Panel", "P", "Tile"],
        "targets": [
            {
                "target_id": "t-custom-kw",
                "object_names": ["CustomTile Tile 1", "CustomTile Tile 2"],
                "center": None,
                "fov_arcmin": None,
            },
        ],
        "expected_groups": [
            {
                "base_name": "CustomTile",
                "panel_numbers": ["1", "2"],
                "confidence": "low",
                "discovery_source": "name",
                "panel_labels": ["Panel 1", "Panel 2"],
            },
        ],
    },
    {
        # A target with a single panel-token OBJECT never-absorbs into a
        # suggestion (need >= 2 distinct panel numbers) -- must produce NO
        # group at all.
        "name": "single_token_target_produces_no_group",
        "keywords": ["Panel", "P"],
        "targets": [
            {
                "target_id": "t-single-token",
                "object_names": ["LonePanel Panel 1"],
                "center": None,
                "fov_arcmin": None,
            },
        ],
        "expected_groups": [],
    },
    {
        # A target with no panel token at all (a plain single-shot object)
        # must also produce no group.
        "name": "no_token_target_produces_no_group",
        "keywords": ["Panel", "P"],
        "targets": [
            {
                "target_id": "t-simple",
                "object_names": ["NGC 7000"],
                "center": None,
                "fov_arcmin": None,
            },
        ],
        "expected_groups": [],
    },
]
