"""Mosaic panel detection: name + position hybrid grouping.

Replaces the original single name-regex pass with a four-stage pipeline that
groups by *target* (not frame) and corroborates name grouping with robust
sky-position clustering. See
docs/superpowers/specs/2026-06-19-mosaic-panel-grouping-design.md.

Stage 0  robust per-target median sky-center + FOV
Stage 1  name path  (panel keyword OR tile pattern against per-frame OBJECT)
Stage 2  position path (cluster median centers among panel candidates)
Stage 3  reconcile + score (union, confidence tier, human-readable flags)

The pure stage helpers operate on plain in-memory structures so they can be
unit-tested with synthetic fixtures; ``detect_mosaic_panels`` is the DB-backed
orchestrator that gathers per-target frame data and persists suggestions.
"""

import math
import re
import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select, delete, exists, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.models import Target, UserSettings, SETTINGS_ROW_ID
from app.models.image import Image
from app.models.mosaic import Mosaic
from app.models.mosaic_panel import MosaicPanel
from app.models.mosaic_panel_session import MosaicPanelSession
from app.models.mosaic_suggestion import MosaicSuggestion
from app.services.mosaic_composite import _parse_ra, _parse_coord


# Fallback position tolerance when no FOV-derived value is available
# (production data: usable adjacent-panel gap is ~12-15 arcmin).
DEFAULT_TOLERANCE_ARCMIN = 12.0


# ---------------------------------------------------------------------------
# Stage 0: robust per-target median sky-center + FOV
# ---------------------------------------------------------------------------

@dataclass
class TargetCenter:
    ra: float   # degrees, 0-360
    dec: float  # degrees


def _frame_coords(header: dict) -> tuple[float, float] | None:
    """Extract (ra_deg, dec_deg) from one frame's headers.

    Prefer decimal RA/DEC; fall back to sexagesimal OBJCTRA/OBJCTDEC.
    Returns None if neither pair yields a valid coordinate.
    """
    if not header:
        return None
    ra = _parse_ra(header.get("RA"))
    dec = _parse_coord(header.get("DEC"))
    if ra is None:
        ra = _parse_ra(header.get("OBJCTRA"))
    if dec is None:
        dec = _parse_coord(header.get("OBJCTDEC"))
    if ra is None or dec is None:
        return None
    # Guard against obviously invalid values.
    if not (-90.0 <= dec <= 90.0):
        return None
    ra = ra % 360.0
    return ra, dec


def robust_median_center(frames: list[dict]) -> TargetCenter | None:
    """Median sky-center over a target's frames, robust to corrupt outliers.

    RA is medianed in the cos(dec)-corrected tangent space and unwrapped so
    values straddling the 0/360 boundary do not collapse to ~180. DEC is a
    plain median. Median (not mean) survives single corrupt-header frames.
    """
    coords = [c for c in (_frame_coords(h) for h in frames) if c is not None]
    if not coords:
        return None

    decs = [c[1] for c in coords]
    med_dec = statistics.median(decs)
    cos_dec = math.cos(math.radians(med_dec)) or 1e-9

    # Unwrap RA relative to a robust reference so the 0/360 seam is handled
    # AND the unwrap is not anchored to a (possibly corrupt) first frame.
    # A first-pass median of the raw RA values gives an outlier-resilient
    # reference; deltas are then taken relative to it and re-medianed in the
    # cos-dec-corrected linear coordinate.
    ref_ra = statistics.median([c[0] for c in coords])
    x_vals = []
    for ra, _dec in coords:
        delta = ra - ref_ra
        # bring delta into (-180, 180]
        delta = (delta + 180.0) % 360.0 - 180.0
        x_vals.append(delta * cos_dec)
    med_x = statistics.median(x_vals)
    med_ra = (ref_ra + med_x / cos_dec) % 360.0

    return TargetCenter(ra=med_ra, dec=med_dec)


def compute_fov_arcmin(
    focallen: float | None, xpixsz: float | None, naxis: int | None
) -> float | None:
    """Field of view (long axis) in arcmin from focal length, pixel size, NAXIS.

    pixel scale (arcsec/px) = 206.265 * XPIXSZ(um) / FOCALLEN(mm)
    FOV (arcmin) = NAXIS * scale / 60
    """
    try:
        if not focallen or not xpixsz or not naxis:
            return None
        focallen = float(focallen)
        xpixsz = float(xpixsz)
        naxis = float(naxis)
        if focallen <= 0 or xpixsz <= 0 or naxis <= 0:
            return None
    except (TypeError, ValueError):
        return None
    scale_arcsec = 206.265 * xpixsz / focallen
    return naxis * scale_arcsec / 60.0


def angular_separation_deg(ra1: float, dec1: float, ra2: float, dec2: float) -> float:
    """Great-circle angular separation in degrees (haversine)."""
    phi1 = math.radians(dec1)
    phi2 = math.radians(dec2)
    dphi = math.radians(dec2 - dec1)
    dlam = math.radians(ra2 - ra1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    )
    a = min(1.0, max(0.0, a))
    return math.degrees(2 * math.asin(math.sqrt(a)))


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


async def load_mosaic_keywords(session: AsyncSession) -> list[str]:
    """Load the configured panel keywords (e.g. ["Panel", "P"]) used by both
    detection and every accepted-mosaic panel-matching call site so they all
    re-parse OBJECT strings with the same tokenizer."""
    settings = await session.get(UserSettings, SETTINGS_ROW_ID)
    general = settings.general if settings else {}
    return general.get("mosaic_keywords", ["Panel", "P"]) or []


def resolve_panel_membership(
    session: Session,
    target_id,
    object_name: str | None,
    keywords: list[str],
) -> tuple[str | None, "object | None"]:
    """Resolve ``(panel_label, panel_id)`` for one Image at ingest time.

    Synchronous (plain ``Session``, not ``AsyncSession``) since it runs from
    the Celery sync worker's ``_do_ingest``. Mirrors the backfill semantics
    in ``alembic/versions/0018_image_panel_membership.py`` exactly (both must
    agree so ingest-time and backfill-time assignment never drift):

    - ``object_name`` parses to a panel token (``match_panel_token_full``) ->
      ``panel_label`` is the derived label (``_panel_label(num)``);
      ``panel_id`` is the id of the ``MosaicPanel`` row already matching
      ``(target_id, panel_label)``, or ``None`` if no such row exists yet.
    - ``object_name`` carries no panel token -> ``panel_label`` stays
      ``None``; ``panel_id`` falls back to the target's "simple" panel (a
      ``MosaicPanel`` with no ``object_pattern``) only when there is EXACTLY
      ONE such panel for this target (ambiguous otherwise, so no fallback is
      applied). This is the mechanism that lets non-token, one-target-one-
      panel mosaics still get ``panel_id`` populated on their Images.
    """
    token = match_panel_token_full(object_name, keywords)
    if token is not None:
        _base, num, _keyword = token
        label = _panel_label(num)
        panel_id = session.execute(
            select(MosaicPanel.id).where(
                MosaicPanel.target_id == target_id,
                MosaicPanel.panel_label == label,
            )
        ).scalars().first()
        return label, panel_id

    simple_ids = session.execute(
        select(MosaicPanel.id).where(
            MosaicPanel.target_id == target_id,
            MosaicPanel.object_pattern.is_(None),
        )
    ).scalars().all()
    panel_id = simple_ids[0] if len(simple_ids) == 1 else None
    return None, panel_id


def prune_stale_panel_sessions(session: Session, panel_ids) -> int:
    """Remove ``MosaicPanelSession`` rows whose (panel_id, session_date) no
    longer has any backing ``Image`` row, for the given set of panels touched
    by orphan-cleanup Image deletion.

    Synchronous (plain ``Session``), called once after a whole orphan-cleanup
    pass (not per 500-row delete batch) from ``run_scan``. Deliberately a
    per-(panel_id, session_date) check, not a per-panel-total-emptiness check:
    a panel can lose every Image for one session_date while retaining Images
    for other dates, and only that one date's session row should be pruned.
    The ``MosaicPanel`` row itself is never deleted here -- an admin may have
    manually configured grid position/rotation for it, or it may simply be
    between imaging sessions with no data locally yet (see Task 5 brief).
    """
    panel_ids = {p for p in panel_ids if p is not None}
    if not panel_ids:
        return 0

    stale = ~exists().where(
        Image.panel_id == MosaicPanelSession.panel_id,
        Image.session_date == MosaicPanelSession.session_date,
    )
    result = session.execute(
        delete(MosaicPanelSession)
        .where(MosaicPanelSession.panel_id.in_(panel_ids))
        .where(stale)
    )
    session.commit()
    return result.rowcount or 0


async def recompute_panel_membership_for_images(session: AsyncSession, image_ids) -> None:
    """Recompute ``Image.panel_id`` for images whose ``resolved_target_id``
    just changed outside ingest (target unmerge, merge-candidate revert,
    orphan-to-target attach, custom-target retro-link), keeping ``panel_id``
    in agreement with ``resolve_panel_membership``'s ``(target_id,
    panel_label)`` lookup semantics.

    Does not re-tokenize OBJECT headers: ``Image.panel_label`` is already
    parsed and stored at ingest time and is independent of target assignment,
    so only the ``panel_id`` lookup (keyed on the image's *current*
    ``resolved_target_id`` and its unchanged ``panel_label``) needs to be
    redone. Mirrors ``resolve_panel_membership``'s two branches (token-bearing
    label vs. the unambiguous simple-panel fallback) exactly, driven by the
    already-stored label instead of re-parsing ``object_name``.

    Call this after any bulk update that changes ``Image.resolved_target_id``
    for a set of images -- including setting it to ``NULL``, in which case
    ``panel_id`` is cleared to match (no target means no valid panel
    membership). When the image's current target has no matching panel for
    its stored label, ``panel_id`` is cleared rather than left stale.
    """
    ids = [i for i in image_ids if i is not None]
    if not ids:
        return

    rows = (await session.execute(
        select(Image.id, Image.resolved_target_id, Image.panel_label)
        .where(Image.id.in_(ids))
    )).all()

    groups: dict[tuple, list] = {}
    for img_id, target_id, panel_label in rows:
        groups.setdefault((target_id, panel_label), []).append(img_id)

    for (target_id, panel_label), group_ids in groups.items():
        new_panel_id = None
        if target_id is not None:
            if panel_label is not None:
                new_panel_id = (await session.execute(
                    select(MosaicPanel.id).where(
                        MosaicPanel.target_id == target_id,
                        MosaicPanel.panel_label == panel_label,
                    )
                )).scalars().first()
            else:
                simple_ids = (await session.execute(
                    select(MosaicPanel.id).where(
                        MosaicPanel.target_id == target_id,
                        MosaicPanel.object_pattern.is_(None),
                    )
                )).scalars().all()
                new_panel_id = simple_ids[0] if len(simple_ids) == 1 else None

        await session.execute(
            update(Image).where(Image.id.in_(group_ids)).values(panel_id=new_panel_id)
        )


# ---------------------------------------------------------------------------
# Stage 2 + 3: grouping, reconciliation, scoring
# ---------------------------------------------------------------------------

@dataclass
class PanelCandidate:
    target_id: str
    base_name: str
    panel_number: str
    label: str
    center: TargetCenter | None
    fov_arcmin: float | None
    keyword: str | None = None  # matched keyword token (None for tile pattern)


@dataclass
class PanelGroup:
    base_name: str
    target_ids: list[str]
    panel_labels: list[str]
    panel_numbers: list[str]
    confidence: str            # 'high' | 'low'
    discovery_source: str      # 'name' | 'position' | 'both'
    flags: list[str] = field(default_factory=list)
    geometry: dict | None = None
    panel_keywords: list[str | None] = field(default_factory=list)


def _build_candidates(targets: list[dict], keywords: list[str]) -> list[PanelCandidate]:
    """Stage 1: emit one PanelCandidate per DISTINCT panel-token OBJECT.

    A single resolved target can carry several distinct panel-token OBJECT
    strings across its frames (e.g. "Veil Nebula Panel 1" and "...Panel 2" both
    resolve to NGC 6960). Each such OBJECT becomes its own candidate, with the
    same target_id but its own panel number and its own per-OBJECT sky center.

    Never-absorb / reframing is preserved: a target with no panel-token OBJECT
    yields no candidate, and a target with exactly one token OBJECT yields
    exactly one candidate.

    Per-OBJECT centers come from ``object_centers`` (OBJECT -> {center, fov})
    when present; otherwise the candidate falls back to the target-level
    ``center`` / ``fov_arcmin``.
    """
    candidates: list[PanelCandidate] = []
    for t in targets:
        object_centers = t.get("object_centers") or {}
        default_center = t.get("center")
        default_fov = t.get("fov_arcmin")
        # Dedupe by (base, number) so the same panel seen under two spellings
        # within one target does not produce duplicate labels.
        seen: set[tuple[str, str]] = set()
        for name in t.get("object_names", []):
            match = match_panel_token_full(name, keywords)
            if not match:
                continue  # never-absorb: no token => not a panel candidate
            base, num, keyword = match
            key = (base.upper(), num)
            if key in seen:
                continue
            seen.add(key)
            per_obj = object_centers.get(name) or {}
            center = per_obj.get("center", default_center)
            fov = per_obj.get("fov_arcmin", default_fov)
            candidates.append(
                PanelCandidate(
                    target_id=t["target_id"],
                    base_name=base,
                    panel_number=num,
                    label=_panel_label(num),
                    center=center,
                    fov_arcmin=fov,
                    keyword=keyword,
                )
            )
    return candidates


def _panel_label(num: str) -> str:
    return f"Panel {num}"


def _effective_tolerance(
    candidates: list[PanelCandidate], tolerance_arcmin: float
) -> float:
    """Resolve the position tolerance.

    tolerance_arcmin > 0 is used directly. Otherwise derive adaptively from the
    smallest candidate FOV (a fraction of a frame), falling back to the default.
    """
    if tolerance_arcmin and tolerance_arcmin > 0:
        return tolerance_arcmin
    fovs = [c.fov_arcmin for c in candidates if c.fov_arcmin]
    if fovs:
        # A fraction of the smallest frame: panels closer than this share a
        # field and are treated as the same position.
        derived = 0.25 * min(fovs)
        return max(derived, 1.0)
    return DEFAULT_TOLERANCE_ARCMIN


def _geometry(candidates: list[PanelCandidate]) -> dict:
    panels = [
        {
            "target_id": c.target_id,
            "label": c.label,
            "ra": round(c.center.ra, 6) if c.center else None,
            "dec": round(c.center.dec, 6) if c.center else None,
        }
        for c in candidates
    ]
    pitches: list[float] = []
    with_center = [c for c in candidates if c.center]
    for i in range(len(with_center)):
        for j in range(i + 1, len(with_center)):
            sep = angular_separation_deg(
                with_center[i].center.ra, with_center[i].center.dec,
                with_center[j].center.ra, with_center[j].center.dec,
            ) * 60.0  # arcmin
            pitches.append(round(sep, 3))
    fovs = [c.fov_arcmin for c in candidates if c.fov_arcmin]
    fov = round(statistics.median(fovs), 2) if fovs else None
    return {"panels": panels, "pitches": pitches, "fov_arcmin": fov}


def _geometry_from_panels(panels: list[dict], fov_arcmin: float | None) -> dict:
    """Rebuild a geometry dict from serialized panel records.

    Recomputes pairwise pitches over exactly the supplied panels (used when a
    campaign split narrows a group to a subset, so pitches reflect only the
    in-campaign pairs and never the full group). ``fov_arcmin`` is a rig
    property and is carried through unchanged.
    """
    pitches: list[float] = []
    with_center = [
        p for p in panels if p.get("ra") is not None and p.get("dec") is not None
    ]
    for i in range(len(with_center)):
        for j in range(i + 1, len(with_center)):
            sep = angular_separation_deg(
                with_center[i]["ra"], with_center[i]["dec"],
                with_center[j]["ra"], with_center[j]["dec"],
            ) * 60.0  # arcmin
            pitches.append(round(sep, 3))
    return {"panels": panels, "pitches": pitches, "fov_arcmin": fov_arcmin}


def _score_group(
    candidates: list[PanelCandidate],
    tolerance_arcmin: float,
    discovery_source: str,
    cross_name: bool = False,
) -> tuple[str, list[str]]:
    """Return (confidence, flags) for a candidate group.

    HIGH requires distinct centers, a consistent base name, regular-ish pitch,
    and name+position agreement. Anything else is LOW with human-readable flags.
    """
    flags: list[str] = []
    with_center = [c for c in candidates if c.center]

    # Conflict: two panels share a center within tolerance (dup / mislabel).
    shared_center = False
    for i in range(len(with_center)):
        for j in range(i + 1, len(with_center)):
            sep = angular_separation_deg(
                with_center[i].center.ra, with_center[i].center.dec,
                with_center[j].center.ra, with_center[j].center.dec,
            ) * 60.0
            if sep < tolerance_arcmin:
                shared_center = True
    if shared_center:
        flags.append(
            "Two panels share a sky center within tolerance "
            "(possible duplicate or mislabel)."
        )

    if cross_name:
        flags.append(
            "Position-grouped targets have unrelated base names."
        )

    # Missing centers reduce confidence (cannot corroborate by position).
    if len(with_center) < len(candidates):
        flags.append("Some panels have no usable sky coordinates.")

    # Irregular geometry: largest pairwise pitch far beyond a plausible mosaic
    # extent (heuristic: many FOVs across). Only meaningful with >=3 panels.
    fovs = [c.fov_arcmin for c in candidates if c.fov_arcmin]
    if len(with_center) >= 3 and fovs:
        med_fov = statistics.median(fovs)
        max_pitch = 0.0
        for i in range(len(with_center)):
            for j in range(i + 1, len(with_center)):
                sep = angular_separation_deg(
                    with_center[i].center.ra, with_center[i].center.dec,
                    with_center[j].center.ra, with_center[j].center.dec,
                ) * 60.0
                max_pitch = max(max_pitch, sep)
        if med_fov and max_pitch > 8.0 * med_fov:
            flags.append(
                "Panel spread is far larger than the field of view "
                "(irregular geometry)."
            )

    # Mixed plate scales across candidates.
    if len(fovs) >= 2:
        lo, hi = min(fovs), max(fovs)
        if lo > 0 and hi / lo > 1.5:
            flags.append("Mixed plate scales across panels.")

    single_signal = discovery_source != "both"
    if flags or single_signal:
        return "low", flags
    return "high", flags


def _finalize_group(
    candidates: list[PanelCandidate],
    tolerance_arcmin: float,
    name_grouped: bool,
    position_grouped: bool,
    cross_name: bool = False,
) -> PanelGroup:
    # Order panels deterministically by panel number for stable labels.
    candidates = sorted(candidates, key=lambda c: _panel_sort_key(c.panel_number))
    base = candidates[0].base_name

    if name_grouped and position_grouped:
        source = "both"
    elif position_grouped:
        source = "position"
    else:
        source = "name"

    confidence, flags = _score_group(
        candidates, tolerance_arcmin, source, cross_name=cross_name
    )
    return PanelGroup(
        base_name=base,
        target_ids=[c.target_id for c in candidates],
        panel_labels=[c.label for c in candidates],
        panel_numbers=[c.panel_number for c in candidates],
        confidence=confidence,
        discovery_source=source,
        flags=flags,
        geometry=_geometry(candidates),
        panel_keywords=[c.keyword for c in candidates],
    )


def _panel_sort_key(num: str):
    # "1-2" -> (1, 2); "3" -> (3,)
    parts = num.split("-")
    try:
        return tuple(int(p) for p in parts)
    except ValueError:
        return (10**9, num)


def _positions_distinct(candidates: list[PanelCandidate], tolerance_arcmin: float) -> bool:
    """True if at least one pair of centers is separated beyond tolerance."""
    with_center = [c for c in candidates if c.center]
    for i in range(len(with_center)):
        for j in range(i + 1, len(with_center)):
            sep = angular_separation_deg(
                with_center[i].center.ra, with_center[i].center.dec,
                with_center[j].center.ra, with_center[j].center.dec,
            ) * 60.0
            if sep >= tolerance_arcmin:
                return True
    return False


def group_panels(
    targets: list[dict],
    keywords: list[str],
    tolerance_arcmin: float = DEFAULT_TOLERANCE_ARCMIN,
) -> list[PanelGroup]:
    """Run Stages 1-3 over per-target records.

    Each ``targets`` item is a dict:
        {"target_id", "object_names": [str], "center": TargetCenter|None,
         "fov_arcmin": float|None}

    Returns a list of PanelGroup (each with >= 2 distinct panel numbers).
    """
    candidates = _build_candidates(targets, keywords)
    if not candidates:
        return []

    tol = _effective_tolerance(candidates, tolerance_arcmin)

    # Stage 1: group by stripped base name (case-insensitive).
    by_base: dict[str, list[PanelCandidate]] = defaultdict(list)
    for c in candidates:
        by_base[c.base_name.upper()].append(c)

    groups: list[PanelGroup] = []
    consumed: set[str] = set()  # target_ids placed into a name group

    for _key, members in by_base.items():
        distinct_numbers = {m.panel_number for m in members}
        if len(distinct_numbers) < 2:
            continue
        # Collapse duplicate panel numbers (keep first per number).
        seen: set[str] = set()
        unique: list[PanelCandidate] = []
        for m in members:
            if m.panel_number in seen:
                continue
            seen.add(m.panel_number)
            unique.append(m)

        # Stage 2: position confirms (or fails to confirm) spatial distinctness.
        position_grouped = _positions_distinct(unique, tol)
        groups.append(
            _finalize_group(
                unique, tol,
                name_grouped=True,
                position_grouped=position_grouped,
            )
        )
        for m in unique:
            consumed.add(m.target_id)

    # Stage 2 (cross-name discovery): among remaining panel candidates that were
    # not name-grouped, link any that cluster spatially. These get unrelated
    # base names => surfaced as low-confidence, flagged.
    remaining = [
        c for c in candidates
        if c.target_id not in consumed and c.center is not None
    ]
    for cluster in _cluster_by_position(remaining, tol):
        if len({c.target_id for c in cluster}) < 2:
            continue
        # Mirror the name path's ">=2 distinct panel numbers" guard: a cluster
        # whose members all parsed to the same panel number (e.g. two "Panel 1"
        # from different bases) would yield duplicate panel labels, which breaks
        # the accept path / panel-session matching. Reject it.
        if len({c.panel_number for c in cluster}) < 2:
            continue
        bases = {c.base_name.upper() for c in cluster}
        cross_name = len(bases) > 1
        groups.append(
            _finalize_group(
                cluster, tol,
                name_grouped=False,
                position_grouped=True,
                cross_name=cross_name,
            )
        )

    return groups


def _cluster_by_position(
    candidates: list[PanelCandidate], tolerance_arcmin: float
) -> list[list[PanelCandidate]]:
    """Single-link clustering: join candidates whose centers fall within a
    mosaic-plausible reach of one another (a few FOVs). Used only for the
    cross-name position discovery path.
    """
    if not candidates:
        return []
    # Reach: how far apart two panels of the same mosaic may sit. Use the
    # median FOV (panels are adjacent within a few fields), fallback generous.
    fovs = [c.fov_arcmin for c in candidates if c.fov_arcmin]
    reach = (statistics.median(fovs) * 3.0) if fovs else (tolerance_arcmin * 10.0)

    n = len(candidates)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i, j):
        parent[find(i)] = find(j)

    for i in range(n):
        for j in range(i + 1, n):
            sep = angular_separation_deg(
                candidates[i].center.ra, candidates[i].center.dec,
                candidates[j].center.ra, candidates[j].center.dec,
            ) * 60.0
            if sep <= reach:
                union(i, j)

    clusters: dict[int, list[PanelCandidate]] = defaultdict(list)
    for i in range(n):
        clusters[find(i)].append(candidates[i])
    return list(clusters.values())


# ---------------------------------------------------------------------------
# Campaign (gap_days) helpers - unchanged behavior
# ---------------------------------------------------------------------------

def cluster_sessions_by_gap(dates: list[str], gap_days: int) -> list[list[str]]:
    """Split sorted date strings into clusters.

    A new cluster starts when the gap between consecutive dates exceeds gap_days.
    """
    if not dates:
        return []
    sorted_dates = sorted(set(dates))
    parsed = [datetime.strptime(d, "%Y-%m-%d").date() for d in sorted_dates]
    clusters: list[list[str]] = [[sorted_dates[0]]]
    for i in range(1, len(parsed)):
        if (parsed[i] - parsed[i - 1]).days > gap_days:
            clusters.append([])
        clusters[-1].append(sorted_dates[i])
    return clusters


def _date_range_suffix(dates: list[str]) -> str:
    """Return '(Mon YYYY)' or '(Mon YYYY - Mon YYYY)' from a list of date strings."""
    parsed = sorted(datetime.strptime(d, "%Y-%m-%d").date() for d in dates)
    first = parsed[0]
    last = parsed[-1]
    fmt_first = first.strftime("%b %Y")
    fmt_last = last.strftime("%b %Y")
    if fmt_first == fmt_last:
        return f"({fmt_first})"
    return f"({fmt_first} - {fmt_last})"


def _unique_name(name: str, used: set[str]) -> str:
    """Return ``name`` (or a deterministic ' (#n)' variant) not already in
    ``used``, and record the chosen name. Prevents two suggestions in one run
    from sharing a suggested_name, which would collide on the unique mosaic name
    when both are accepted.
    """
    if name not in used:
        used.add(name)
        return name
    n = 2
    while f"{name} (#{n})" in used:
        n += 1
    chosen = f"{name} (#{n})"
    used.add(chosen)
    return chosen


def compute_dedup_signature(
    base_name: str, target_ids, panel_labels: list[str]
) -> str:
    """Stable signature identifying a suggestion's panel set.

    Composed of ``base_name | sorted(target_ids) | sorted(panel_labels)``.
    Order-independent and independent of frame counts, geometry, session dates,
    and the date-suffixed suggested_name. Duplicate target_ids are retained
    (a multi-panel-per-target group has the same target id more than once), so
    sorting preserves multiplicity. Used to suppress re-creating a suggestion a
    user previously dismissed: a rejected row stores this signature, and a new
    run skips any group whose signature matches.
    """
    tids = sorted(str(t) for t in target_ids)
    labels = sorted(panel_labels)
    return "|".join([base_name, ",".join(tids), ",".join(labels)])


# ---------------------------------------------------------------------------
# DB orchestrator
# ---------------------------------------------------------------------------

async def _gather_target_records(session: AsyncSession) -> list[dict]:
    """Build per-target records (object names, median center, FOV) for all
    unmerged targets not already assigned to a mosaic panel.
    """
    in_mosaic_q = select(MosaicPanel.target_id)
    in_mosaic = {r[0] for r in (await session.execute(in_mosaic_q)).all()}

    targets_q = select(Target.id).where(Target.merged_into_id.is_(None))
    target_ids = [r[0] for r in (await session.execute(targets_q)).all()]
    target_ids = [tid for tid in target_ids if tid not in in_mosaic]
    if not target_ids:
        return []

    # Pull only the header keys detection actually reads, extracted as scalar
    # columns, instead of shipping the full raw_headers JSONB of every LIGHT
    # frame (hundreds of MB on a large catalog). Keys used downstream:
    # OBJECT (panel token), RA/DEC/OBJCTRA/OBJCTDEC (center), FOCALLEN/XPIXSZ/
    # NAXIS1/NAXIS2 (FOV).
    _HEADER_KEYS = (
        "OBJECT", "RA", "DEC", "OBJCTRA", "OBJCTDEC",
        "FOCALLEN", "XPIXSZ", "NAXIS1", "NAXIS2",
    )
    rows_q = (
        select(
            Image.resolved_target_id,
            *(Image.raw_headers[k].astext.label(k) for k in _HEADER_KEYS),
        )
        .where(
            Image.resolved_target_id.in_(target_ids),
            Image.image_type == "LIGHT",
        )
    )
    by_target_headers: dict = defaultdict(list)
    for row in (await session.execute(rows_q)).all():
        headers = {k: getattr(row, k) for k in _HEADER_KEYS if getattr(row, k) is not None}
        if headers:
            by_target_headers[row.resolved_target_id].append(headers)

    def _first_fov(frame_list: list[dict]) -> float | None:
        for h in frame_list:
            fov = compute_fov_arcmin(
                h.get("FOCALLEN"), h.get("XPIXSZ"),
                h.get("NAXIS1") or h.get("NAXIS2"),
            )
            if fov is not None:
                return fov
        return None

    records: list[dict] = []
    for tid in target_ids:
        headers = by_target_headers.get(tid, [])
        # Partition this target's frames by OBJECT so each distinct OBJECT gets
        # its own robust center/FOV. A target can host several panel-token
        # OBJECTs (the Veil case), which must NOT collapse to one median center.
        by_object: dict[str, list[dict]] = defaultdict(list)
        object_names: list[str] = []
        seen_names: set[str] = set()
        for h in headers:
            obj = h.get("OBJECT")
            if not obj:
                continue
            by_object[obj].append(h)
            if obj not in seen_names:
                seen_names.add(obj)
                object_names.append(obj)

        object_centers = {
            obj: {
                "center": robust_median_center(frames),
                "fov_arcmin": _first_fov(frames),
            }
            for obj, frames in by_object.items()
        }

        records.append({
            "target_id": str(tid),
            "raw_target_id": tid,
            "object_names": object_names,
            "object_centers": object_centers,
            # Target-level fallback center/fov (used when an OBJECT has no
            # per-object center, and by any single-OBJECT path).
            "center": robust_median_center(headers),
            "fov_arcmin": _first_fov(headers),
        })
    return records


async def detect_mosaic_panels(session: AsyncSession, gap_days: int = 0) -> int:
    """Scan targets for mosaic panels (name + position) and create suggestions.

    Entry point used by the API (with gap_days from settings) and the Celery
    task (gap_days defaults to 0). Reads mosaic_keywords and
    mosaic_position_tolerance_arcmin from user settings.
    """
    settings = await session.get(UserSettings, SETTINGS_ROW_ID)
    general = settings.general if settings else {}
    keywords = general.get("mosaic_keywords", ["Panel", "P"])
    tolerance_arcmin = general.get("mosaic_position_tolerance_arcmin", 0) or 0

    if not keywords:
        keywords = []

    records = await _gather_target_records(session)
    if not records:
        return 0

    groups = group_panels(records, keywords=keywords, tolerance_arcmin=tolerance_arcmin)
    if not groups:
        return 0

    # Map target_id (str) -> raw uuid for persistence.
    raw_id = {r["target_id"]: r["raw_target_id"] for r in records}

    new_base_names = {g.base_name for g in groups}

    # Durable dismissals: load the dedup signatures of rejected (dismissed)
    # suggestions BEFORE clearing pending, along with the session dates each
    # dismissal covered at the time. A regenerated group is skipped only when
    # its signature matches AND its own session dates are fully covered by
    # (a subset of) the dismissed suggestion's dates -- a later campaign over
    # the same panel set that includes genuinely new dates (e.g. a re-shoot
    # years later, AUD-033) is NOT a subset and resurfaces normally. If the
    # panel set materially changes (different target set or panel_labels) the
    # signature differs and the suggestion may resurface regardless.
    rejected_q = select(
        MosaicSuggestion.dedup_signature, MosaicSuggestion.session_dates
    ).where(
        MosaicSuggestion.status == "rejected",
        MosaicSuggestion.dedup_signature.is_not(None),
    )
    rejected_signatures: dict[str, set[str]] = {}
    for sig, dates_by_label in (await session.execute(rejected_q)).all():
        if not sig:
            continue
        flat_dates: set[str] = set()
        for dates in (dates_by_label or {}).values():
            flat_dates.update(dates or [])
        # Multiple dismissed rows can share a signature (re-dismissed after a
        # resurfacing); union their covered dates so any of them can suppress.
        rejected_signatures.setdefault(sig, set()).update(flat_dates)

    # Detection is idempotent: clear ALL pending suggestions before regenerating.
    # This drops stale rows from prior runs AND legacy rows from the old code
    # (which have NULL base_name/geometry and would otherwise coexist as
    # no-preview duplicates). Rejected/dismissed and accepted rows are untouched.
    await session.execute(
        delete(MosaicSuggestion).where(MosaicSuggestion.status == "pending")
    )

    # Skip base names already represented by an existing mosaic.
    existing_mosaic_q = select(Mosaic.name)
    existing_mosaic_names = {
        r[0].upper() for r in (await session.execute(existing_mosaic_q)).all()
    }
    accepted_bases: set[str] = set()
    for base in new_base_names:
        base_upper = base.upper()
        for name in existing_mosaic_names:
            if name == base_upper or name.startswith(base_upper + " ("):
                accepted_bases.add(base)
                break

    count = 0
    used_names: set[str] = set()
    for g in groups:
        if g.base_name in accepted_bases:
            continue

        # Collect session dates per panel via the OBJECT header pattern, so the
        # campaign (gap_days) split and the suggestion card session view work.
        # Include the matched keyword token so a panel's pattern does not match a
        # sibling panel's OBJECT (ambiguous for bases containing digits).
        keywords_per_panel = g.panel_keywords or [None] * len(g.panel_numbers)
        panel_patterns = [
            build_panel_pattern(g.base_name, kw, num)
            for kw, num in zip(keywords_per_panel, g.panel_numbers)
        ]
        sess_dates: dict[str, list[str]] = {}
        all_dates: list[str] = []
        per_panel_dates: list[list[str]] = []
        for label, pattern, num in zip(g.panel_labels, panel_patterns, g.panel_numbers):
            # ILIKE is a cheap pre-filter only (it also matches sibling panels
            # for which `num` is a prefix, e.g. "1" matching "Panel 12"), so
            # fetch (session_date, OBJECT) pairs and re-parse each OBJECT to
            # keep only frames that exactly belong to this panel (AUD-008).
            dates_q = (
                select(
                    Image.session_date,
                    Image.raw_headers["OBJECT"].astext.label("obj"),
                )
                .where(
                    Image.image_type == "LIGHT",
                    Image.raw_headers["OBJECT"].astext.ilike(pattern),
                )
                .distinct()
            )
            raw_rows = (await session.execute(dates_q)).all()
            date_strs = sorted(
                {
                    d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d)
                    for d, obj in raw_rows
                    if d is not None and object_matches_panel(obj, keywords, num)
                }
            )
            sess_dates[label] = date_strs
            per_panel_dates.append(date_strs)
            all_dates.extend(date_strs)

        if gap_days > 0 and all_dates:
            clusters = cluster_sessions_by_gap(all_dates, gap_days)
        else:
            clusters = [sorted(set(all_dates))] if all_dates else [[]]

        if len(clusters) <= 1:
            count += _add_suggestion(
                session, g, raw_id, panel_patterns, sess_dates,
                suggested_name=g.base_name,
                used_names=used_names,
                rejected_signatures=rejected_signatures,
            )
        else:
            for cluster_dates in clusters:
                cluster_set = set(cluster_dates)
                idxs = [
                    i for i, dates in enumerate(per_panel_dates)
                    if any(d in cluster_set for d in dates)
                ]
                if len({g.panel_numbers[i] for i in idxs}) < 2:
                    continue
                suffix = _date_range_suffix(cluster_dates)
                campaign_sess = {
                    g.panel_labels[i]: sorted(
                        d for d in per_panel_dates[i] if d in cluster_set
                    )
                    for i in idxs
                }
                count += _add_suggestion(
                    session, g, raw_id,
                    [panel_patterns[i] for i in idxs],
                    campaign_sess,
                    suggested_name=f"{g.base_name} {suffix}",
                    subset_idxs=idxs,
                    used_names=used_names,
                    rejected_signatures=rejected_signatures,
                )

    await session.commit()
    return count


def _add_suggestion(
    session: AsyncSession,
    group: PanelGroup,
    raw_id: dict,
    panel_patterns: list[str],
    sess_dates: dict[str, list[str]],
    suggested_name: str,
    subset_idxs: list[int] | None = None,
    used_names: set[str] | None = None,
    rejected_signatures: dict[str, set[str]] | None = None,
) -> int:
    """Create and add one MosaicSuggestion.

    Returns 1 if created, 0 if skipped because its dedup signature matches a
    dismissed (rejected) suggestion AND its session dates are fully covered
    by that dismissal's dates (AUD-033: a later campaign with genuinely new
    dates is not suppressed). ``suggested_name`` is uniquified against
    ``used_names`` only when the suggestion is actually created.
    """
    if subset_idxs is None:
        target_ids = [raw_id[tid] for tid in group.target_ids]
        panel_labels = list(group.panel_labels)
        geometry = group.geometry
    else:
        target_ids = [raw_id[group.target_ids[i]] for i in subset_idxs]
        panel_labels = [group.panel_labels[i] for i in subset_idxs]
        # Narrow geometry panels to the campaign subset AND recompute pitches so
        # they only reflect pairs within this campaign (carrying the full-group
        # pitches/fov here would be stale).
        if group.geometry:
            sub_labels = set(panel_labels)
            panels = [
                p for p in group.geometry["panels"] if p["label"] in sub_labels
            ]
            geometry = _geometry_from_panels(panels, group.geometry.get("fov_arcmin"))
        else:
            geometry = None

    signature = compute_dedup_signature(group.base_name, target_ids, panel_labels)
    if rejected_signatures and signature in rejected_signatures:
        campaign_dates: set[str] = set()
        for dates in sess_dates.values():
            campaign_dates.update(dates or [])
        if campaign_dates <= rejected_signatures[signature]:
            # Every date in this campaign was already covered by the
            # dismissal; do not resurface it.
            return 0

    if used_names is not None:
        suggested_name = _unique_name(suggested_name, used_names)

    suggestion = MosaicSuggestion(
        suggested_name=suggested_name,
        base_name=group.base_name,
        target_ids=target_ids,
        panel_labels=panel_labels,
        panel_patterns=panel_patterns,
        session_dates=sess_dates,
        confidence=group.confidence,
        discovery_source=group.discovery_source,
        geometry=geometry,
        flags=list(group.flags),
        dedup_signature=signature,
    )
    session.add(suggestion)
    return 1
