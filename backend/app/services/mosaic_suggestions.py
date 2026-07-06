"""Mosaic suggestion listing and acceptance.

Pure extraction of the panel-pattern derivation and suggestion-processing
logic that used to live inline in app/api/mosaics.py, in `get_suggestions`
and `accept_suggestion`. Behavior is preserved exactly, including one
pre-existing, intentional asymmetry: the two "object_pattern for a mosaic
name" call sites (create_mosaic, add_panel, delete_mosaic in the router)
strip a trailing "(YYYY)"/"(YYYY-YYYY)" year suffix from the mosaic's display
name before deriving `base`, via `strip_year_suffix`. The suggestion call
sites (`list_pending_suggestions`, `accept_suggestion_panels`) do NOT strip
anything -- they pass `suggestion.base_name or suggestion.suggested_name`
straight through to `object_pattern_for_label`, because a suggestion's
`base_name` is already the un-suffixed base, stored separately from its
display name at detection time. This is not a bug and must not be merged
into one behavior.
"""

import re
from collections import defaultdict

from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Image, Target
from app.models.mosaic import Mosaic
from app.models.mosaic_panel import MosaicPanel
from app.models.mosaic_panel_session import MosaicPanelSession
from app.models.mosaic_suggestion import MosaicSuggestion
from app.schemas.mosaic import MosaicSuggestionResponse, SuggestionPreviewPanel
from app.services.mosaic_detection import (
    load_mosaic_keywords,
    object_matches_panel,
    panel_number_from_label,
    retro_link_panel_images as _retro_link_panel_images,
)


def strip_year_suffix(name: str) -> str:
    """Strip a trailing "(YYYY)" or "(YYYY-YYYY)" suffix from a mosaic name.

    Used by mosaic-name call sites (create_mosaic, delete_mosaic, add_panel)
    before deriving an object_pattern `base` from `mosaic.name`. NOT used by
    suggestion call sites, which already have an un-suffixed `base_name`.
    """
    return re.sub(r'\s*\(\d{4}(?:-\d{4})?\)\s*$', '', name)


def object_pattern_for_label(
    label: str,
    base_name: str,
    panel_labels: list[str] | None = None,
    panel_patterns: list[str] | None = None,
) -> str:
    """Derive the OBJECT ILIKE pattern for a single panel label.

    Prefers a pre-computed pattern from `panel_patterns`/`panel_labels` (set
    at detection time) when the label is present there; otherwise falls back
    to `f"%{base_name}%Panel%{num}%"` where `num` is the trailing token of a
    "Panel N" label (or the whole label if it doesn't start with "Panel ").

    Callers are responsible for resolving `base_name` first: mosaic-name call
    sites (create_mosaic, add_panel) pass `strip_year_suffix(mosaic.name)`;
    suggestion call sites pass `suggestion.base_name or suggestion.suggested_name`
    as-is. See module docstring.
    """
    if panel_patterns and panel_labels and label in panel_labels:
        idx = panel_labels.index(label)
        if idx < len(panel_patterns):
            return panel_patterns[idx]
    num = label.split()[-1] if label.startswith("Panel ") else label
    return f"%{base_name}%Panel%{num}%"


def _ilike_pattern_matches(pattern: str, value: str) -> bool:
    """Match an SQL ILIKE pattern against a value with the SAME semantics SQL
    uses: '%' is an ordered, possibly-empty gap and '_' a single char. Literal
    segments must appear in order and contiguously (no reordering).

    A naive "split on % and check each segment is a substring" test is wrong:
    for "%Sh2 119%1%" the segments are ["sh2 119", "1"], and "Sh2 119 Panel 2"
    contains both ("1" lives inside "119"), so it would falsely match Panel 1.
    Translating to an anchored regex preserves order and avoids that.
    """
    if value is None:
        return False
    regex_parts = []
    for ch in pattern:
        if ch == "%":
            regex_parts.append(".*")
        elif ch == "_":
            regex_parts.append(".")
        else:
            regex_parts.append(re.escape(ch))
    regex = "^" + "".join(regex_parts) + "$"
    return re.match(regex, value, re.IGNORECASE | re.DOTALL) is not None


async def list_pending_suggestions(session: AsyncSession) -> list[MosaicSuggestionResponse]:
    """Build the full suggestion list response: pending suggestions not
    already matching an existing mosaic name, with resolved target names,
    per-panel thumbnails, and per-panel session summaries.

    Moved verbatim from the router's `get_suggestions`, except the local
    `_pattern_for_label` closure is replaced by `object_pattern_for_label`.
    """
    from app.schemas.mosaic import SuggestionPanelSession

    keywords = await load_mosaic_keywords(session)

    q = select(MosaicSuggestion).where(MosaicSuggestion.status == "pending")
    all_pending = (await session.execute(q)).scalars().all()

    # Filter out suggestions whose name already matches an existing mosaic
    existing_mosaic_names_q = select(Mosaic.name)
    existing_mosaic_names = {
        r[0].upper() for r in (await session.execute(existing_mosaic_names_q)).all()
    }
    rows = [r for r in all_pending if r.suggested_name.upper() not in existing_mosaic_names]

    # Resolve target names in batch
    all_ids = {t for r in rows for t in r.target_ids}
    name_map: dict[str, str] = {}
    if all_ids:
        tq = select(Target.id, Target.primary_name).where(Target.id.in_(all_ids))
        for tid, tname in (await session.execute(tq)).all():
            name_map[str(tid)] = tname

    def _thumb_url(thumbnail_path: str | None) -> str | None:
        if not thumbnail_path:
            return None
        filename = thumbnail_path.split("/")[-1].split("\\")[-1]
        return f"/thumbnails/{filename}"

    # Per-target fallback thumbnail in one query (avoid N+1). Reuses the panel
    # stats scheme: the most recent LIGHT frame with a thumbnail_path becomes
    # /thumbnails/{filename}. DISTINCT ON keeps one row per target. Used when a
    # panel has no object_pattern or no pattern-matching frame.
    thumb_map: dict[str, str] = {}
    if all_ids:
        thumb_q = (
            select(
                Image.resolved_target_id,
                Image.thumbnail_path,
            )
            .where(
                Image.resolved_target_id.in_(all_ids),
                Image.image_type == "LIGHT",
                Image.thumbnail_path.is_not(None),
            )
            .distinct(Image.resolved_target_id)
            .order_by(Image.resolved_target_id, Image.capture_date.desc())
        )
        for tid, thumb_path in (await session.execute(thumb_q)).all():
            url = _thumb_url(thumb_path)
            if url:
                thumb_map[str(tid)] = url

    # Per-(target, object_pattern) thumbnail resolution. Two panels can share one
    # target_id (SIMBAD merges "Veil Nebula Panel 1"/"Panel 2" into NGC 6960);
    # the per-target fallback would give both the same image. Resolve each panel
    # by the same (resolved_target_id + OBJECT ILIKE pattern) frame selection
    # that mosaic_stats/mosaic_composite use for accepted panels. Collect the
    # distinct pairs first so each is queried once (LIMIT 1, bounded by panel
    # count across pending suggestions).
    def _pattern_for_label(r, label: str) -> str | None:
        base = r.base_name or r.suggested_name
        return object_pattern_for_label(label, base, r.panel_labels, r.panel_patterns)

    pattern_thumb_pairs: set[tuple[str, str, str]] = set()
    for r in rows:
        geometry = r.geometry or {}
        for gp in geometry.get("panels", []):
            tid = gp.get("target_id")
            if tid is None:
                continue
            label = gp.get("label") or ""
            pattern = _pattern_for_label(r, label)
            if pattern:
                pattern_thumb_pairs.add((str(tid), pattern, panel_number_from_label(label)))

    pattern_thumb_map: dict[tuple[str, str], str] = {}
    obj_col_thumb = Image.raw_headers["OBJECT"].astext
    for tid_str, pattern, expected_num in pattern_thumb_pairs:
        # ILIKE is a cheap pre-filter only (also matches sibling panels for
        # which expected_num is a prefix, e.g. "1" matching "Panel 12"), so
        # fetch a bounded candidate set ordered the same way and re-parse each
        # OBJECT string to keep only the exact panel (AUD-008).
        pq = (
            select(Image.thumbnail_path, obj_col_thumb.label("obj"))
            .where(
                Image.resolved_target_id == tid_str,
                Image.image_type == "LIGHT",
                Image.thumbnail_path.is_not(None),
                obj_col_thumb.ilike(pattern),
            )
            .order_by(Image.capture_date.desc())
            .limit(25)
        )
        candidates = (await session.execute(pq)).all()
        thumb_path = next(
            (c.thumbnail_path for c in candidates if object_matches_panel(c.obj, keywords, expected_num)),
            None,
        )
        url = _thumb_url(thumb_path)
        if url:
            pattern_thumb_map[(tid_str, pattern)] = url

    # Build all OBJECT ILIKE patterns across every suggestion+panel,
    # then fetch session summaries in a single query instead of N queries.
    # Each pattern maps back to (suggestion index, panel label).
    pattern_map: dict[str, list[tuple[int, str]]] = {}  # pattern -> [(row_idx, label)]
    for idx, r in enumerate(rows):
        if r.panel_patterns:
            # Use pre-computed patterns stored at detection time
            for label, pattern in zip(r.panel_labels, r.panel_patterns):
                pattern_map.setdefault(pattern, []).append((idx, label))
        else:
            # Fallback for legacy suggestions without panel_patterns
            base = r.base_name or r.suggested_name
            for label in r.panel_labels:
                obj_pattern = object_pattern_for_label(label, base, r.panel_labels, r.panel_patterns)
                pattern_map.setdefault(obj_pattern, []).append((idx, label))

    # Run one query with all patterns OR'd together
    all_patterns = list(pattern_map.keys())
    obj_col = Image.raw_headers["OBJECT"].astext
    session_rows_by_idx: dict[int, list[SuggestionPanelSession]] = defaultdict(list)

    if all_patterns:
        sq = (
            select(
                obj_col.label("obj"),
                Image.session_date.label("night"),
                Image.filter_used,
                func.count(Image.id).label("frames"),
                func.sum(Image.exposure_time).label("integration"),
            )
            .where(
                Image.image_type == "LIGHT",
                or_(*(obj_col.ilike(p) for p in all_patterns)),
            )
            .group_by("obj", "night", Image.filter_used)
            .order_by("obj", "night")
        )
        all_session_rows = (await session.execute(sq)).all()

        # Distribute each result row back to the suggestions whose pattern matches
        for row in all_session_rows:
            obj_val = row.obj or ""
            for pattern, mappings in pattern_map.items():
                # _ilike_pattern_matches mirrors ILIKE's own semantics (a cheap
                # pre-filter), which still matches sibling panels for which a
                # panel's number is a prefix (e.g. "1" matching "Panel 12").
                # Re-parse and check each mapping's own expected number too
                # (AUD-008) before accepting the row.
                if _ilike_pattern_matches(pattern, obj_val):
                    for row_idx, label in mappings:
                        expected_num = panel_number_from_label(label)
                        if not object_matches_panel(obj_val, keywords, expected_num):
                            continue
                        session_rows_by_idx[row_idx].append(SuggestionPanelSession(
                            panel_label=label,
                            object_name=obj_val,
                            date=str(row.night) if row.night else "",
                            frames=row.frames,
                            integration_seconds=row.integration or 0,
                            filter_used=row.filter_used,
                        ))

    results = []
    for idx, r in enumerate(rows):
        all_sessions = session_rows_by_idx.get(idx, [])
        filtered_sessions = all_sessions
        other_count = 0

        if r.session_dates:
            campaign_dates = set()
            for dates in r.session_dates.values():
                campaign_dates.update(dates)
            filtered_sessions = [s for s in all_sessions if s.date in campaign_dates]
            other_count = len(all_sessions) - len(filtered_sessions)

        # Build preview panels from stored geometry. The frontend arranger
        # auto-arranges tiles, so grid_row/grid_col are left null here; only
        # thumbnail_url is resolved (batched above, no per-panel compute).
        preview_panels: list[SuggestionPreviewPanel] = []
        geometry = r.geometry or {}
        for gp in geometry.get("panels", []):
            tid = gp.get("target_id")
            if tid is None:
                continue
            tid_str = str(tid)
            label = gp.get("label") or ""
            pattern = _pattern_for_label(r, label)
            # Prefer the per-(target, pattern) frame so merged-target panels get
            # distinct thumbnails; fall back to the per-target latest thumbnail.
            thumb = None
            if pattern is not None:
                thumb = pattern_thumb_map.get((tid_str, pattern))
            if thumb is None:
                thumb = thumb_map.get(tid_str)
            preview_panels.append(SuggestionPreviewPanel(
                target_id=tid_str,
                panel_label=label,
                ra=gp.get("ra"),
                dec=gp.get("dec"),
                thumbnail_url=thumb,
                grid_row=None,
                grid_col=None,
            ))

        results.append(MosaicSuggestionResponse(
            id=str(r.id),
            suggested_name=r.suggested_name,
            base_name=r.base_name,
            target_ids=[str(t) for t in r.target_ids],
            panel_labels=r.panel_labels,
            panel_patterns=r.panel_patterns,
            target_names={str(t): name_map.get(str(t), "Unknown") for t in set(r.target_ids)},
            sessions=filtered_sessions,
            session_dates=r.session_dates,
            other_session_count=other_count,
            status=r.status,
            confidence=r.confidence,
            discovery_source=r.discovery_source,
            flags=list(r.flags) if r.flags else [],
            preview_panels=preview_panels,
        ))

    return results


async def accept_suggestion_panels(
    session: AsyncSession,
    suggestion: MosaicSuggestion,
    selected_panels: set[str] | None,
    keywords,
) -> tuple[Mosaic, int]:
    """Create the mosaic and its accepted panels for a pending suggestion.

    Moved verbatim from the router's `accept_suggestion` panel-creation loop,
    using `object_pattern_for_label` instead of the inline pattern
    derivation. The caller (router) still owns the pre-existing-mosaic 409
    check, the `suggestion.status = "accepted"` mutation, the commit, and the
    `MosaicSummary` response construction.
    """
    from datetime import date as date_type

    # Create the mosaic
    mosaic = Mosaic(name=suggestion.suggested_name)
    session.add(mosaic)
    await session.flush()

    # Create panels - multiple panels may share the same target_id
    # (SIMBAD often merges panel variants into one target)
    panel_num = 0
    created = 0
    base = suggestion.base_name or suggestion.suggested_name
    for target_id, label in zip(suggestion.target_ids, suggestion.panel_labels):
        if selected_panels is not None and label not in selected_panels:
            continue
        obj_pattern = object_pattern_for_label(
            label, base, suggestion.panel_labels, suggestion.panel_patterns
        )
        panel = MosaicPanel(
            mosaic_id=mosaic.id,
            target_id=target_id,
            panel_label=label,
            sort_order=panel_num,
            object_pattern=obj_pattern,
        )
        session.add(panel)
        await session.flush()  # get panel.id

        # Claim already-ingested frames whose parsed label matches this
        # panel -- panel stats read Image.panel_id, so without this the
        # freshly-accepted mosaic would show zero frames until re-ingest.
        await _retro_link_panel_images(session, panel.id, target_id, label)

        # Seed session membership from suggestion's session_dates
        campaign_dates = set()
        if suggestion.session_dates and label in suggestion.session_dates:
            for ds in suggestion.session_dates[label]:
                d = date_type.fromisoformat(ds)
                campaign_dates.add(d)
                session.add(MosaicPanelSession(
                    panel_id=panel.id,
                    session_date=d,
                    status="included",
                ))

        # Find additional sessions outside the campaign
        base_filter = [
            Image.resolved_target_id == target_id,
            Image.image_type == "LIGHT",
            Image.session_date.isnot(None),
        ]
        if obj_pattern:
            base_filter.append(Image.raw_headers["OBJECT"].astext.ilike(obj_pattern))
        # ILIKE is a cheap pre-filter only; re-parse each matched OBJECT and
        # keep only frames that exactly belong to this panel number, so a
        # sibling panel (e.g. panel "12" vs this panel "1") doesn't seed
        # spurious "available" sessions (AUD-008).
        expected_num = panel_number_from_label(label)
        all_dates_q = select(
            Image.session_date, Image.raw_headers["OBJECT"].astext.label("obj")
        ).where(*base_filter).distinct()
        all_dates = {
            r.session_date
            for r in (await session.execute(all_dates_q)).all()
            if not obj_pattern or object_matches_panel(r.obj, keywords, expected_num)
        }

        for d in all_dates:
            if d not in campaign_dates:
                session.add(MosaicPanelSession(
                    panel_id=panel.id,
                    session_date=d,
                    status="available",
                ))

        panel_num += 1
        created += 1

    return mosaic, created
