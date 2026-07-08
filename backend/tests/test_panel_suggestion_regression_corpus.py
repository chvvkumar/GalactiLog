"""Regression-fixture parity suite: suggestion/detection-side panel matching.

Roadmap Phase 5 verification bar: "suggestion results identical on regression
fixture set." Phase 5 rewrote *accepted-mosaic* panel stats
(``mosaic_stats.py``/``get_panel_sessions``) to exact ``Image.panel_id``
joins, but explicitly did NOT touch the suggestion-detection side
(``get_suggestions`` in ``app.api.mosaics``, ``detect_mosaic_panels``/
``group_panels`` in ``app.services.mosaic_detection``) or the shared
tokenizer/pattern-building functions both sides call
(``match_panel_token_full``, ``build_panel_pattern``, ``object_matches_panel``,
``exact_panel_regex``).

This suite runs a hand-built corpus (``tests/fixtures/panel_suggestion_corpus``)
through those still-unmodified functions and asserts the output matches
hand-verified literal expectations recorded in the fixture module. Since nothing
in Tasks 1-5 was supposed to touch this code, this should currently pass
trivially -- its value is as a tripwire: if a future change (in this phase or
a later one) accidentally touches the shared tokenizer/grouping code, this
suite is what catches the drift. A legitimate future change to tokenizer or
grouping behavior requires an explicit, reviewed edit to the fixture file's
literals -- not a silent pass because the test recomputed its own expectation.
"""
import re

from app.services.mosaic_detection import (
    build_panel_pattern,
    exact_panel_regex,
    group_panels,
    match_panel_token_full,
    object_matches_panel,
)
from tests.fixtures.panel_suggestion_corpus import (
    GROUPING_CASES,
    PATTERN_CASES,
    TOKEN_CASES,
)


def test_token_corpus_matches_recorded_golden_output():
    failures = []
    for case_id, keywords, object_name, expected in TOKEN_CASES:
        actual = match_panel_token_full(object_name, keywords)
        if actual != expected:
            failures.append(f"{case_id}: expected {expected!r}, got {actual!r}")
    assert not failures, "\n".join(failures)


def test_pattern_and_exact_recheck_corpus_matches_recorded_golden_output():
    failures = []
    for case in PATTERN_CASES:
        pattern = build_panel_pattern(case["base"], case["keyword"], case["num"])
        if pattern != case["expected_pattern"]:
            failures.append(
                f"{case['case_id']}: pattern expected {case['expected_pattern']!r}, "
                f"got {pattern!r}"
            )

        # The ILIKE prefilter itself is exercised in Python here as a plain
        # substring check on the pattern's literal tokens (no DB round trip
        # needed to prove the *prefilter's* known over-matching behavior --
        # the DB-backed ILIKE semantics are unchanged Postgres behavior, not
        # something this phase touched).
        ilike_matches = all(
            token in case["candidate_object"]
            for token in case["expected_pattern"].strip("%").split("%")
        )
        if ilike_matches != case["ilike_prefilter_matches"]:
            failures.append(
                f"{case['case_id']}: ilike_prefilter_matches expected "
                f"{case['ilike_prefilter_matches']!r}, got {ilike_matches!r}"
            )

        exact = object_matches_panel(case["candidate_object"], case["keywords"], case["num"])
        if exact != case["exact_match_expected"]:
            failures.append(
                f"{case['case_id']}: object_matches_panel expected "
                f"{case['exact_match_expected']!r}, got {exact!r}"
            )

        regex = exact_panel_regex(case["keywords"], case["num"])
        if regex != case["exact_panel_regex"]:
            failures.append(
                f"{case['case_id']}: exact_panel_regex expected "
                f"{case['exact_panel_regex']!r}, got {regex!r}"
            )
        regex_matches = bool(re.search(regex, case["candidate_object"], re.IGNORECASE))
        if regex_matches != case["exact_match_expected"]:
            failures.append(
                f"{case['case_id']}: exact_panel_regex search against "
                f"{case['candidate_object']!r} expected "
                f"{case['exact_match_expected']!r}, got {regex_matches!r}"
            )
    assert not failures, "\n".join(failures)


def test_grouping_corpus_matches_recorded_golden_output():
    failures = []
    for scenario in GROUPING_CASES:
        groups = group_panels(scenario["targets"], keywords=scenario["keywords"])
        actual = sorted(
            (
                {
                    "base_name": g.base_name,
                    "panel_numbers": sorted(g.panel_numbers),
                    "confidence": g.confidence,
                    "discovery_source": g.discovery_source,
                    "panel_labels": sorted(g.panel_labels),
                }
                for g in groups
            ),
            key=lambda g: g["base_name"],
        )
        expected = sorted(scenario["expected_groups"], key=lambda g: g["base_name"])
        if actual != expected:
            failures.append(
                f"{scenario['name']}: expected {expected!r}, got {actual!r}"
            )
    assert not failures, "\n".join(failures)
