"""Mosaic panel statistics and list aggregation.

Pure extraction of the per-panel and per-mosaic stat computations that used to
live inline in app/api/mosaics.py. Behavior (query shapes, aggregation rules,
and returned PanelStats/MosaicSummary fields) is preserved exactly.
"""

import re
from collections import defaultdict

from sqlalchemy import select, func, or_, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Image
from app.models.custom_column import CustomColumn, CustomColumnValue, AppliesTo
from app.models.mosaic import Mosaic
from app.models.mosaic_panel import MosaicPanel
from app.models.mosaic_panel_session import MosaicPanelSession
from app.schemas.mosaic import MosaicSummary, PanelStats
from app.services.mosaic_detection import (
    exact_panel_regex,
    load_mosaic_keywords,
    object_matches_panel,
    panel_number_from_label,
)


def _ilike_to_regex(pattern: str):
    """Convert a SQL ILIKE pattern (%, _) to a compiled Python regex."""
    # Process char-by-char: % and _ are ILIKE wildcards, everything else is literal.
    # Can't rely on re.escape treating % specially (Python 3.7+ doesn't).
    parts = []
    for ch in pattern:
        if ch == "%":
            parts.append(".*")
        elif ch == "_":
            parts.append(".")
        else:
            parts.append(re.escape(ch))
    return re.compile(f"^{''.join(parts)}$", re.IGNORECASE)


def _parse_sexa_ra(s: str) -> float | None:
    """Parse sexagesimal RA 'HH MM SS' to degrees."""
    try:
        parts = s.strip().split()
        h, m, sec = float(parts[0]), float(parts[1]), float(parts[2])
        return (h + m / 60 + sec / 3600) * 15
    except (ValueError, IndexError):
        return None


def _parse_sexa_dec(s: str) -> float | None:
    """Parse sexagesimal Dec '+DD MM SS' to degrees."""
    try:
        s = s.strip()
        sign = -1 if s.startswith("-") else 1
        parts = s.lstrip("+-").split()
        d, m, sec = float(parts[0]), float(parts[1]), float(parts[2])
        return sign * (d + m / 60 + sec / 3600)
    except (ValueError, IndexError):
        return None


async def get_panel_included_dates(
    panels: list[MosaicPanel], session: AsyncSession,
) -> dict[str, list]:
    """Build a mapping of panel_id -> included session dates.

    Only panels that have membership records are included in the dict.
    Panels without any membership records are omitted (meaning "use all sessions").
    """
    panel_ids = [p.id for p in panels]
    if not panel_ids:
        return {}

    q = (
        select(MosaicPanelSession.panel_id, MosaicPanelSession.session_date, MosaicPanelSession.status)
        .where(MosaicPanelSession.panel_id.in_(panel_ids))
    )
    rows = (await session.execute(q)).all()

    has_membership: set[str] = set()
    included: dict[str, list] = {}
    for panel_id, session_date, status in rows:
        pid = str(panel_id)
        has_membership.add(pid)
        if status == "included":
            included.setdefault(pid, []).append(session_date)

    for pid in has_membership:
        if pid not in included:
            included[pid] = []

    return included


async def panel_stats(panel: MosaicPanel, session: AsyncSession) -> PanelStats:
    """Compute stats for a single panel."""
    target = panel.target

    # When an object_pattern is set, filter frames by OBJECT header
    # (needed when multiple panels share the same target after SIMBAD merge).
    # The ILIKE pattern is a cheap pre-filter only -- it also matches sibling
    # panels for which this panel's number is a prefix (e.g. "1" matching
    # "Panel 12"), so pair it with an exact-number regex (AUD-008).
    object_regex = None
    if panel.object_pattern:
        keywords = await load_mosaic_keywords(session)
        expected_num = panel_number_from_label(panel.panel_label)
        object_regex = exact_panel_regex(keywords, expected_num)

    base_filter = [
        Image.resolved_target_id == panel.target_id,
        Image.image_type == "LIGHT",
    ]
    if panel.object_pattern:
        base_filter.append(Image.raw_headers["OBJECT"].astext.ilike(panel.object_pattern))
        base_filter.append(Image.raw_headers["OBJECT"].astext.op("~*")(object_regex))

    # Fetch all membership rows in one query, then derive both the total count
    # (any status) and the included-date list in Python. This replaces the two
    # separate count + included-dates queries with a single round-trip.
    membership_q = (
        select(MosaicPanelSession.session_date, MosaicPanelSession.status)
        .where(MosaicPanelSession.panel_id == panel.id)
    )
    membership_rows = (await session.execute(membership_q)).all()
    any_membership_count = len(membership_rows)
    included_dates = [r[0] for r in membership_rows if r[1] == "included"]

    if any_membership_count > 0:
        # Panel has membership records - scope to included sessions only
        if included_dates:
            base_filter.append(Image.session_date.in_(included_dates))
        else:
            # All sessions excluded - force empty result
            base_filter.append(text("false"))

    # Count available sessions
    if any_membership_count > 0:
        all_dates_filter = [
            Image.resolved_target_id == panel.target_id,
            Image.image_type == "LIGHT",
        ]
        if panel.object_pattern:
            all_dates_filter.append(Image.raw_headers["OBJECT"].astext.ilike(panel.object_pattern))
            all_dates_filter.append(Image.raw_headers["OBJECT"].astext.op("~*")(object_regex))
        all_dates_q = (
            select(func.count(func.distinct(Image.session_date)))
            .where(*all_dates_filter)
            .where(Image.session_date.isnot(None))
        )
        total_session_count = (await session.execute(all_dates_q)).scalar() or 0
        available_count = total_session_count - len(included_dates)
    else:
        available_count = 0

    q = (
        select(
            func.sum(Image.exposure_time).label("integration"),
            func.count(Image.id).label("frames"),
            func.max(Image.session_date).label("last_date"),
        )
        .where(*base_filter)
    )
    row = (await session.execute(q)).one()

    # Filter distribution
    fq = (
        select(Image.filter_used, func.sum(Image.exposure_time))
        .where(*base_filter)
        .where(Image.filter_used.is_not(None))
        .group_by(Image.filter_used)
    )
    filter_dist = {r[0]: r[1] or 0 for r in (await session.execute(fq)).all()}

    # Most recent thumbnail for this panel (also grab pier side for orientation)
    thumb_q = (
        select(
            Image.thumbnail_path,
            Image.raw_headers["PIERSIDE"].astext.label("pier_side"),
            Image.id,
            Image.file_path,
        )
        .where(*base_filter)
        .where(Image.thumbnail_path.is_not(None))
        .order_by(Image.capture_date.desc())
        .limit(1)
    )
    thumb_row = (await session.execute(thumb_q)).first()
    thumb_url = None
    thumb_pier_side = None
    thumb_image_id = None
    thumb_file_path = None
    if thumb_row and thumb_row.thumbnail_path:
        filename = thumb_row.thumbnail_path.split("/")[-1].split("\\")[-1]
        thumb_url = f"/thumbnails/{filename}"
        thumb_pier_side = thumb_row.pier_side
        thumb_image_id = str(thumb_row.id)
        thumb_file_path = thumb_row.file_path

    # Compute per-panel center from frame FITS headers (median of OBJCTRA/OBJCTDEC).
    # This gives the actual pointing position for each panel, even when multiple
    # panels are merged into the same target by SIMBAD resolution.
    panel_ra = target.ra
    panel_dec = target.dec
    if panel.object_pattern:
        coord_q = (
            select(
                Image.raw_headers["OBJCTRA"].astext.label("ra_str"),
                Image.raw_headers["OBJCTDEC"].astext.label("dec_str"),
            )
            .where(*base_filter)
            .where(Image.raw_headers["OBJCTRA"].isnot(None))
            .where(Image.raw_headers["OBJCTDEC"].isnot(None))
            .limit(50)
        )
        coord_rows = (await session.execute(coord_q)).all()
        if coord_rows:
            ras = sorted(r for row in coord_rows if (r := _parse_sexa_ra(row.ra_str)) is not None)
            decs = sorted(r for row in coord_rows if (r := _parse_sexa_dec(row.dec_str)) is not None)
            if ras:
                panel_ra = ras[len(ras) // 2]
            if decs:
                panel_dec = decs[len(decs) // 2]

    return PanelStats(
        panel_id=str(panel.id),
        target_id=str(panel.target_id),
        target_name=target.primary_name,
        panel_label=panel.panel_label,
        sort_order=panel.sort_order,
        ra=panel_ra,
        dec=panel_dec,
        total_integration_seconds=row.integration or 0,
        total_frames=row.frames or 0,
        filter_distribution=filter_dist,
        last_session_date=str(row.last_date) if row.last_date else None,
        thumbnail_url=thumb_url,
        thumbnail_pier_side=thumb_pier_side,
        thumbnail_image_id=thumb_image_id,
        thumbnail_file_path=thumb_file_path,
        object_pattern=panel.object_pattern,
        grid_row=panel.grid_row,
        grid_col=panel.grid_col,
        rotation=panel.rotation,
        flip_h=panel.flip_h,
        available_session_count=max(available_count, 0),
    )


async def batch_panel_stats(
    panels: list[MosaicPanel], session: AsyncSession
) -> dict[str, PanelStats]:
    """Compute stats for multiple simple panels (no object_pattern) in bulk queries.

    Panels with session membership records are handled in batch by fetching
    all membership data at once, then applying per-panel date filters in Python.
    Panels without membership use the original 3-query bulk approach.

    Returns a dict keyed by str(panel.id).
    """
    # Check which panels have any membership records
    all_panel_ids = [p.id for p in panels]
    has_membership_q = (
        select(func.distinct(MosaicPanelSession.panel_id))
        .where(MosaicPanelSession.panel_id.in_(all_panel_ids))
    )
    panel_has_membership: set[str] = {
        str(r[0]) for r in (await session.execute(has_membership_q)).all()
    }

    # Split panels into two groups
    unscoped_panels = [p for p in panels if str(p.id) not in panel_has_membership]
    scoped_panels = [p for p in panels if str(p.id) in panel_has_membership]

    result: dict[str, PanelStats] = {}

    # --- Handle scoped panels in batch ---
    if scoped_panels:
        # 1. Batch-fetch all included dates for scoped panels
        scoped_ids = [p.id for p in scoped_panels]
        membership_q = (
            select(
                MosaicPanelSession.panel_id,
                MosaicPanelSession.session_date,
                MosaicPanelSession.status,
            )
            .where(MosaicPanelSession.panel_id.in_(scoped_ids))
        )
        membership_rows = (await session.execute(membership_q)).all()

        # Build per-panel membership info
        panel_any_membership: set[str] = set()
        panel_included_dates: dict[str, list] = defaultdict(list)
        for pid, sdate, status in membership_rows:
            pid_str = str(pid)
            panel_any_membership.add(pid_str)
            if status == "included":
                panel_included_dates[pid_str].append(sdate)

        # 2. Batch-fetch all image rows for scoped panels' targets (one query)
        scoped_target_ids = list({p.target_id for p in scoped_panels})
        scoped_img_q = (
            select(
                Image.resolved_target_id,
                Image.exposure_time,
                Image.filter_used,
                Image.session_date,
                Image.id,
            )
            .where(
                Image.resolved_target_id.in_(scoped_target_ids),
                Image.image_type == "LIGHT",
            )
        )
        scoped_img_rows = (await session.execute(scoped_img_q)).all()

        # Build per-panel aggregates in Python, filtering by included dates
        # Map: target_id -> list of scoped panels (multiple panels may share a target)
        panels_by_target: dict[str, list[MosaicPanel]] = defaultdict(list)
        for p in scoped_panels:
            panels_by_target[str(p.target_id)].append(p)

        # Accumulators per panel
        scoped_agg: dict[str, dict] = {
            str(p.id): {"integration": 0, "frames": 0, "last_date": None, "filters": {}, "all_dates": set()}
            for p in scoped_panels
        }

        for row in scoped_img_rows:
            tid_str = str(row.resolved_target_id)
            for p in panels_by_target.get(tid_str, []):
                pid_str = str(p.id)
                included = panel_included_dates.get(pid_str, [])
                # If panel has membership but no included dates, skip all frames
                if pid_str in panel_any_membership and not included:
                    # Still count all_dates for available_session_count
                    if row.session_date is not None:
                        scoped_agg[pid_str]["all_dates"].add(row.session_date)
                    continue
                # If panel has membership, only count included sessions
                if pid_str in panel_any_membership and row.session_date not in included:
                    if row.session_date is not None:
                        scoped_agg[pid_str]["all_dates"].add(row.session_date)
                    continue
                # Count this frame
                exp = row.exposure_time or 0.0
                acc = scoped_agg[pid_str]
                acc["integration"] += exp
                acc["frames"] += 1
                if row.session_date is not None:
                    acc["all_dates"].add(row.session_date)
                    if acc["last_date"] is None or row.session_date > acc["last_date"]:
                        acc["last_date"] = row.session_date
                if row.filter_used:
                    acc["filters"][row.filter_used] = acc["filters"].get(row.filter_used, 0) + exp

        # 3. Batch-fetch thumbnails for scoped panels' targets
        scoped_thumb_q = text(
            "SELECT DISTINCT ON (resolved_target_id) "
            "resolved_target_id, thumbnail_path, raw_headers->>'PIERSIDE' AS pier_side, id, file_path "
            "FROM images "
            "WHERE resolved_target_id = ANY(:target_ids) "
            "AND image_type = 'LIGHT' "
            "AND thumbnail_path IS NOT NULL "
            "ORDER BY resolved_target_id, capture_date DESC"
        )
        scoped_thumb_rows = (await session.execute(scoped_thumb_q, {"target_ids": scoped_target_ids})).all()
        scoped_thumb_map: dict[str, tuple[str | None, str | None, str | None, str | None]] = {}
        for r in scoped_thumb_rows:
            tid = str(r[0])
            thumb_path = r[1]
            thumb_url = None
            if thumb_path:
                filename = thumb_path.split("/")[-1].split("\\")[-1]
                thumb_url = f"/thumbnails/{filename}"
            scoped_thumb_map[tid] = (thumb_url, r[2], str(r[3]) if r[3] else None, r[4])

        # Build PanelStats for each scoped panel
        for p in scoped_panels:
            target = p.target
            tid = str(p.target_id)
            pid_str = str(p.id)
            acc = scoped_agg[pid_str]
            included = panel_included_dates.get(pid_str, [])
            total_sessions = len(acc["all_dates"])
            available_count = max(total_sessions - len(included), 0)

            thumb_url, thumb_pier_side, thumb_image_id, thumb_file_path = scoped_thumb_map.get(tid, (None, None, None, None))

            result[pid_str] = PanelStats(
                panel_id=pid_str,
                target_id=tid,
                target_name=target.primary_name,
                panel_label=p.panel_label,
                sort_order=p.sort_order,
                ra=target.ra,
                dec=target.dec,
                total_integration_seconds=acc["integration"],
                total_frames=acc["frames"],
                filter_distribution=acc["filters"],
                last_session_date=str(acc["last_date"]) if acc["last_date"] else None,
                thumbnail_url=thumb_url,
                thumbnail_pier_side=thumb_pier_side,
                thumbnail_image_id=thumb_image_id,
                thumbnail_file_path=thumb_file_path,
                object_pattern=p.object_pattern,
                grid_row=p.grid_row,
                grid_col=p.grid_col,
                rotation=p.rotation,
                flip_h=p.flip_h,
                available_session_count=available_count,
            )

    # --- Handle unscoped panels in bulk ---
    if not unscoped_panels:
        return result

    target_ids = list({p.target_id for p in unscoped_panels})

    # 1. Aggregation: integration, frames, last session date
    agg_q = (
        select(
            Image.resolved_target_id,
            func.sum(Image.exposure_time).label("integration"),
            func.count(Image.id).label("frames"),
            func.max(Image.session_date).label("last_date"),
        )
        .where(Image.resolved_target_id.in_(target_ids), Image.image_type == "LIGHT")
        .group_by(Image.resolved_target_id)
    )
    agg_map: dict[str, tuple] = {
        str(r[0]): (r[1] or 0, r[2] or 0, r[3])
        for r in (await session.execute(agg_q)).all()
    }

    # 2. Filter distribution per target
    filt_q = (
        select(
            Image.resolved_target_id,
            Image.filter_used,
            func.sum(Image.exposure_time),
        )
        .where(
            Image.resolved_target_id.in_(target_ids),
            Image.image_type == "LIGHT",
            Image.filter_used.is_not(None),
        )
        .group_by(Image.resolved_target_id, Image.filter_used)
    )
    filt_map: dict[str, dict[str, float]] = defaultdict(dict)
    for r in (await session.execute(filt_q)).all():
        filt_map[str(r[0])][r[1]] = r[2] or 0

    # 3. Most recent thumbnail per target (with pier side for orientation)
    thumb_q = text(
        "SELECT DISTINCT ON (resolved_target_id) "
        "resolved_target_id, thumbnail_path, raw_headers->>'PIERSIDE' AS pier_side, id, file_path "
        "FROM images "
        "WHERE resolved_target_id = ANY(:target_ids) "
        "AND image_type = 'LIGHT' "
        "AND thumbnail_path IS NOT NULL "
        "ORDER BY resolved_target_id, capture_date DESC"
    )
    thumb_rows = (await session.execute(thumb_q, {"target_ids": target_ids})).all()
    thumb_map: dict[str, tuple[str | None, str | None, str | None, str | None]] = {}
    for r in thumb_rows:
        tid = str(r[0])
        thumb_path = r[1]
        thumb_url = None
        if thumb_path:
            filename = thumb_path.split("/")[-1].split("\\")[-1]
            thumb_url = f"/thumbnails/{filename}"
        thumb_map[tid] = (thumb_url, r[2], str(r[3]) if r[3] else None, r[4])

    # Build PanelStats for each unscoped panel
    for p in unscoped_panels:
        target = p.target
        tid = str(p.target_id)
        agg = agg_map.get(tid, (0, 0, None))
        filters = filt_map.get(tid, {})
        thumb_url, thumb_pier_side, thumb_image_id, thumb_file_path = thumb_map.get(tid, (None, None, None, None))

        result[str(p.id)] = PanelStats(
            panel_id=str(p.id),
            target_id=tid,
            target_name=target.primary_name,
            panel_label=p.panel_label,
            sort_order=p.sort_order,
            ra=target.ra,
            dec=target.dec,
            total_integration_seconds=agg[0],
            total_frames=agg[1],
            filter_distribution=filters,
            last_session_date=str(agg[2]) if agg[2] else None,
            thumbnail_url=thumb_url,
            thumbnail_pier_side=thumb_pier_side,
            thumbnail_image_id=thumb_image_id,
            thumbnail_file_path=thumb_file_path,
            object_pattern=p.object_pattern,
            grid_row=p.grid_row,
            grid_col=p.grid_col,
            rotation=p.rotation,
            flip_h=p.flip_h,
        )

    return result


async def list_mosaic_summaries(session: AsyncSession) -> list[MosaicSummary]:
    """Return per-mosaic summary stats (integration, frames, completion, dates)."""
    q = select(Mosaic).options(selectinload(Mosaic.panels)).order_by(Mosaic.name)
    mosaics = (await session.execute(q)).scalars().all()

    # Batch-fetch integration stats for all simple panels (no object_pattern)
    # to avoid N+1 per-panel queries.
    simple_panels = [p for m in mosaics for p in m.panels if not p.object_pattern]
    bulk_rows: dict[str, tuple[float, int]] = {}
    bulk_dates: dict[str, tuple[str | None, str | None]] = {}
    if simple_panels:
        target_ids = list({p.target_id for p in simple_panels})
        bulk_q = (
            select(
                Image.resolved_target_id,
                func.sum(Image.exposure_time).label("integration"),
                func.count(Image.id).label("frames"),
                func.min(Image.session_date).label("first_session"),
                func.max(Image.session_date).label("last_session"),
            )
            .where(Image.resolved_target_id.in_(target_ids), Image.image_type == "LIGHT")
            .group_by(Image.resolved_target_id)
        )
        for r in (await session.execute(bulk_q)).all():
            tid = str(r[0])
            bulk_rows[tid] = (r[1] or 0, r[2] or 0)
            bulk_dates[tid] = (
                str(r.first_session) if r.first_session else None,
                str(r.last_session) if r.last_session else None,
            )

    # Batch-fetch integration stats for all pattern panels using a single query
    # with per-(target_id, object_pattern) case expressions to avoid N+1.
    pattern_panels = [p for m in mosaics for p in m.panels if p.object_pattern]
    panel_stats_map: dict[str, tuple[float, int]] = {}
    panel_dates_map: dict[str, tuple[str | None, str | None]] = {}
    if pattern_panels:
        # Build one OR condition per unique (target_id, pattern) pair
        unique_pairs = list({(p.target_id, p.object_pattern) for p in pattern_panels})
        conditions = or_(*(
            (Image.resolved_target_id == tid) &
            (Image.raw_headers["OBJECT"].astext.ilike(pat))
            for tid, pat in unique_pairs
        ))

        # Collect ALL membership records to distinguish "no records" from "records but none included"
        all_panel_ids = [p.id for p in pattern_panels]
        has_membership_q = (
            select(func.distinct(MosaicPanelSession.panel_id))
            .where(MosaicPanelSession.panel_id.in_(all_panel_ids))
        )
        panel_has_membership: set[str] = {
            str(r[0]) for r in (await session.execute(has_membership_q)).all()
        }

        membership_q = (
            select(MosaicPanelSession.panel_id, MosaicPanelSession.session_date)
            .where(
                MosaicPanelSession.panel_id.in_(all_panel_ids),
                MosaicPanelSession.status == "included",
            )
        )
        membership_rows = (await session.execute(membership_q)).all()
        panel_included_dates: dict[str, set] = defaultdict(set)
        for r in membership_rows:
            panel_included_dates[str(r.panel_id)].add(r.session_date)

        # Aggregate matching frames in SQL by (target_id, object_name, session_date).
        # ILIKE patterns can't appear in GROUP BY, so we group on the raw OBJECT
        # string and per-session date instead: this collapses the per-frame result
        # set into one row per (target, object, session) while letting Python still
        # apply per-panel pattern matching and included-date scoping. SUM/COUNT move
        # into SQL; the Python-side regex/scoping work scales with distinct
        # (object, session) tuples rather than total frame count.
        object_name_col = Image.raw_headers["OBJECT"].astext.label("object_name")
        grouped_q = (
            select(
                Image.resolved_target_id,
                object_name_col,
                Image.session_date,
                # coalesce so a group where every frame has NULL exposure_time
                # yields 0.0 (SQL SUM over all-NULL returns NULL), matching the
                # prior per-frame `exposure_time or 0.0` aggregation.
                func.sum(func.coalesce(Image.exposure_time, 0.0)).label("integration"),
                func.count(Image.id).label("frames"),
            )
            .where(Image.image_type == "LIGHT", conditions)
            .group_by(Image.resolved_target_id, object_name_col, Image.session_date)
        )
        grouped_rows = (await session.execute(grouped_q)).all()

        # Build a lookup: target_id -> list of (compiled regex, pattern string) per target_id.
        pair_regexes = {(str(tid), pat): _ilike_to_regex(pat) for tid, pat in unique_pairs}
        # Group patterns by target_id for efficient lookup
        patterns_by_target: dict[str, list[tuple[str, object]]] = defaultdict(list)
        for (tid_str, pat), rx in pair_regexes.items():
            patterns_by_target[tid_str].append((pat, rx))

        pair_to_panels: dict[tuple[str, str], list[str]] = defaultdict(list)
        for p in pattern_panels:
            pair_to_panels[(str(p.target_id), p.object_pattern)].append(str(p.id))

        # rx.match() mirrors ILIKE semantics only (a cheap pre-filter): it
        # still matches sibling panels for which this panel's number is a
        # prefix (e.g. "1" matching "Panel 12"). Re-parse and compare each
        # panel's own exact expected number before accumulating (AUD-008).
        keywords = await load_mosaic_keywords(session)
        panel_expected_num = {str(p.id): panel_number_from_label(p.panel_label) for p in pattern_panels}

        # Accumulate per panel: total integration, total frames, and the set of
        # contributing session dates (for min/max). Sum/count come pre-aggregated
        # from SQL; we add a session's totals to a panel when its pattern matches
        # and (for scoped panels) the session is included.
        panel_integration: dict[str, float] = {str(p.id): 0.0 for p in pattern_panels}
        panel_frames: dict[str, int] = {str(p.id): 0 for p in pattern_panels}
        panel_accum_dates: dict[str, list[str]] = {str(p.id): [] for p in pattern_panels}

        for row in grouped_rows:
            tid_str = str(row.resolved_target_id)
            obj_name = row.object_name or ""
            integration = row.integration or 0.0
            frames = row.frames or 0
            for pat, rx in patterns_by_target.get(tid_str, []):
                if rx.match(obj_name):
                    for pid in pair_to_panels.get((tid_str, pat), []):
                        if not object_matches_panel(obj_name, keywords, panel_expected_num[pid]):
                            continue
                        if pid not in panel_has_membership:
                            # No membership records - legacy unscoped
                            panel_integration[pid] += integration
                            panel_frames[pid] += frames
                            if row.session_date:
                                panel_accum_dates[pid].append(str(row.session_date))
                        elif pid in panel_included_dates and row.session_date in panel_included_dates[pid]:
                            # Has membership with included dates - scoped
                            panel_integration[pid] += integration
                            panel_frames[pid] += frames
                            if row.session_date:
                                panel_accum_dates[pid].append(str(row.session_date))
                        # else: has membership but session not included - skip

        for pid in panel_integration:
            panel_stats_map[pid] = (panel_integration[pid], panel_frames[pid])
        for pid, dates in panel_accum_dates.items():
            if dates:
                sorted_d = sorted(dates)
                panel_dates_map[pid] = (sorted_d[0], sorted_d[-1])
            else:
                panel_dates_map[pid] = (None, None)

    # Batch-load custom column values for all mosaics
    mosaic_ids = [m.id for m in mosaics]
    custom_values_map: dict[str, dict[str, str]] = {}
    if mosaic_ids:
        cv_q = (
            select(CustomColumnValue.mosaic_id, CustomColumn.slug, CustomColumnValue.value)
            .join(CustomColumn)
            .where(
                CustomColumnValue.mosaic_id.in_(mosaic_ids),
                CustomColumn.applies_to == AppliesTo.mosaic,
            )
        )
        cv_rows = (await session.execute(cv_q)).all()
        for mid, slug, val in cv_rows:
            mid_str = str(mid)
            if mid_str not in custom_values_map:
                custom_values_map[mid_str] = {}
            custom_values_map[mid_str][slug] = val

    results = []
    for m in mosaics:
        total_int = 0
        total_frames = 0
        panel_integrations = []
        mosaic_first: str | None = None
        mosaic_last: str | None = None
        for p in m.panels:
            if not p.object_pattern:
                pi, pf = bulk_rows.get(str(p.target_id), (0, 0))
                pf_date, pl_date = bulk_dates.get(str(p.target_id), (None, None))
            else:
                pi, pf = panel_stats_map.get(str(p.id), (0, 0))
                pf_date, pl_date = panel_dates_map.get(str(p.id), (None, None))
            total_int += pi
            total_frames += pf
            panel_integrations.append(pi)
            if pf_date and (mosaic_first is None or pf_date < mosaic_first):
                mosaic_first = pf_date
            if pl_date and (mosaic_last is None or pl_date > mosaic_last):
                mosaic_last = pl_date

        max_panel = max(panel_integrations) if panel_integrations else 0
        if max_panel > 0 and len(panel_integrations) > 0:
            completion = sum(min(p / max_panel, 1.0) for p in panel_integrations) / len(panel_integrations) * 100
        else:
            completion = 0

        results.append(MosaicSummary(
            id=str(m.id),
            name=m.name,
            notes=m.notes,
            panel_count=len(m.panels),
            total_integration_seconds=total_int,
            total_frames=total_frames,
            completion_pct=round(completion, 1),
            first_session=mosaic_first,
            last_session=mosaic_last,
            needs_review=m.needs_review,
            custom_values=custom_values_map.get(str(m.id)),
        ))
    return results
