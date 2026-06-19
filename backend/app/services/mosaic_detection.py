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

from sqlalchemy import select, func, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Target, UserSettings, SETTINGS_ROW_ID
from app.models.image import Image
from app.models.mosaic import Mosaic
from app.models.mosaic_panel import MosaicPanel
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
    return re.compile(
        rf"^(.+?)\s*[-_\s]?\s*(?:{kw_pattern})\s*[-_\s]?\s*(\d+)\s*$",
        re.IGNORECASE,
    )


def match_panel_token(name: str, keywords: list[str]) -> tuple[str, str] | None:
    """Return (base_name, panel_number) if name carries a panel/tile token.

    Tries the keyword pattern (Panel N / P N) first, then the _R-C tile
    pattern. Returns None when the name has no panel token (never-absorb).
    """
    if not name:
        return None
    if keywords:
        m = _keyword_regex(keywords).match(name)
        if m:
            return m.group(1).strip(), m.group(2)
    m = _TILE_RE.match(name)
    if m:
        return m.group(1).strip(), m.group(2)
    return None


def strip_panel_token(name: str, keywords: list[str]) -> str | None:
    """Return the stripped base name, or None if no panel token present."""
    result = match_panel_token(name, keywords)
    return result[0] if result else None


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
            match = match_panel_token(name, keywords)
            if not match:
                continue  # never-absorb: no token => not a panel candidate
            base, num = match
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

    # Pull LIGHT-frame headers per target. Project only the JSONB header so we
    # don't load full ORM rows. Headers carry OBJECT / RA / DEC / FOCALLEN etc.
    rows_q = (
        select(Image.resolved_target_id, Image.raw_headers)
        .where(
            Image.resolved_target_id.in_(target_ids),
            Image.image_type == "LIGHT",
        )
    )
    by_target_headers: dict = defaultdict(list)
    for tid, headers in (await session.execute(rows_q)).all():
        if headers:
            by_target_headers[tid].append(headers)

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

    # Replace stale pending suggestions for these base names.
    if new_base_names:
        stale_q = select(MosaicSuggestion.id).where(
            MosaicSuggestion.status == "pending",
            MosaicSuggestion.base_name.in_(new_base_names),
        )
        stale_ids = [r[0] for r in (await session.execute(stale_q)).all()]
        if stale_ids:
            await session.execute(
                delete(MosaicSuggestion).where(MosaicSuggestion.id.in_(stale_ids))
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
    for g in groups:
        if g.base_name in accepted_bases:
            continue

        # Collect session dates per panel via the OBJECT header pattern, so the
        # campaign (gap_days) split and the suggestion card session view work.
        panel_patterns = [
            f"%{g.base_name}%{num}%" for num in g.panel_numbers
        ]
        sess_dates: dict[str, list[str]] = {}
        all_dates: list[str] = []
        per_panel_dates: list[list[str]] = []
        for label, pattern in zip(g.panel_labels, panel_patterns):
            dates_q = select(func.distinct(Image.session_date)).where(
                Image.image_type == "LIGHT",
                Image.raw_headers["OBJECT"].astext.ilike(pattern),
            )
            raw_dates = (await session.execute(dates_q)).scalars().all()
            date_strs = sorted(
                d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d)
                for d in raw_dates
                if d is not None
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
) -> int:
    """Create and add one MosaicSuggestion. Returns 1."""
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
    )
    session.add(suggestion)
    return 1
