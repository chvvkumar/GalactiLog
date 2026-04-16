import re
import uuid
from collections import defaultdict
from datetime import datetime

from sqlalchemy import select, func, cast, Date, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Target, UserSettings, SETTINGS_ROW_ID
from app.models.image import Image
from app.models.mosaic import Mosaic
from app.models.mosaic_panel import MosaicPanel
from app.models.mosaic_suggestion import MosaicSuggestion


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


async def detect_mosaic_panels(session: AsyncSession, gap_days: int = 0) -> int:
    """Scan targets for panel naming patterns and create suggestions."""
    # Load keywords from settings
    settings = await session.get(UserSettings, SETTINGS_ROW_ID)
    general = settings.general if settings else {}
    keywords = general.get("mosaic_keywords", ["Panel", "P"])

    if not keywords:
        return 0

    # Build regex: matches "{base_name} {sep}? {keyword} {sep}? {number}"
    # e.g., "Cygnus Wall Panel 1", "Veil_P3", "Heart Nebula Mosaic-2"
    kw_pattern = "|".join(re.escape(k) for k in keywords)
    pattern = re.compile(
        rf"^(.+?)\s*[-_\s]?\s*({kw_pattern})\s*[-_\s]?\s*(\d+)\s*$",
        re.IGNORECASE,
    )

    # Get all targets not already in a mosaic
    in_mosaic_q = select(MosaicPanel.target_id)
    in_mosaic = {r[0] for r in (await session.execute(in_mosaic_q)).all()}

    targets_q = select(Target).where(Target.merged_into_id.is_(None))
    targets = (await session.execute(targets_q)).scalars().all()

    # Group by base name
    # Tuple: (Target, label, panel_num, keyword) - panel_num used for OBJECT queries
    groups: dict[str, list[tuple[Target, str, str, str]]] = defaultdict(list)
    for t in targets:
        if t.id in in_mosaic:
            continue
        # Check primary name and aliases - don't break, one target may match
        # multiple panels via its aliases
        names_to_check = [t.primary_name] + (t.aliases or [])
        seen_panels: set[str] = set()
        for name in names_to_check:
            m = pattern.match(name)
            if m:
                base = m.group(1).strip()
                keyword = m.group(2)
                panel_num = m.group(3)
                panel_key = f"{base}|{panel_num}"
                if panel_key not in seen_panels:
                    seen_panels.add(panel_key)
                    groups[base].append((t, f"Panel {panel_num}", panel_num, keyword))

    # Collect base names we're about to create suggestions for
    new_base_names = {base for base, panels in groups.items() if len(panels) >= 2}

    # Delete stale pending suggestions for these base names so re-detection
    # with different gap settings replaces rather than accumulates.
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

    # Skip groups that already have an existing mosaic (check actual Mosaic table,
    # not suggestion status, so deleting a mosaic properly allows re-detection).
    existing_mosaic_q = select(Mosaic.name)
    existing_mosaic_names = {r[0].upper() for r in (await session.execute(existing_mosaic_q)).all()}
    # Build lookup: a base_name is "taken" if any existing mosaic name starts with it
    accepted_bases: set[str] = set()
    for base in new_base_names:
        base_upper = base.upper()
        for name in existing_mosaic_names:
            if name == base_upper or name.startswith(base_upper + " ("):
                accepted_bases.add(base)
                break

    count = 0

    if gap_days > 0:
        for base_name, panels in groups.items():
            if len(panels) < 2:
                continue

            # Collect distinct session dates per panel via OBJECT header pattern
            panel_dates: list[tuple[Target, str, str, str, list[str]]] = []
            for t, label, panel_num, keyword in panels:
                # Build a pattern that matches the original name used for this panel
                obj_pattern = f"%{base_name}%{panel_num}%"
                dates_q = select(
                    func.distinct(Image.session_date)
                ).where(
                    Image.image_type == "LIGHT",
                    Image.raw_headers["OBJECT"].astext.ilike(obj_pattern),
                )
                result = await session.execute(dates_q)
                raw_dates = result.scalars().all()
                date_strs = [
                    d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d)
                    for d in raw_dates
                    if d is not None
                ]
                panel_dates.append((t, label, panel_num, keyword, date_strs))

            # Gather all dates across all panels
            all_dates: list[str] = []
            for _, _, _, _, dates in panel_dates:
                all_dates.extend(dates)

            if not all_dates:
                # No date info found - fall through to non-clustered creation
                if base_name in accepted_bases:
                    continue
                panels_list = [(t, lbl, pn, kw) for t, lbl, pn, kw, _ in panel_dates]
                panel_patterns = [f"%{base_name}%{kw}%{pn}%" for _, _, pn, kw in panels_list]
                suggestion = MosaicSuggestion(
                    suggested_name=base_name,
                    base_name=base_name,
                    target_ids=[t.id for t, _, _, _ in panels_list],
                    panel_labels=[lbl for _, lbl, _, _ in panels_list],
                    panel_patterns=panel_patterns,
                    session_dates={},
                )
                session.add(suggestion)
                count += 1
                continue

            clusters = cluster_sessions_by_gap(all_dates, gap_days)

            if len(clusters) == 1:
                if base_name in accepted_bases:
                    continue
                panels_list = [(t, lbl, pn, kw) for t, lbl, pn, kw, _ in panel_dates]
                panel_patterns = [f"%{base_name}%{kw}%{pn}%" for _, _, pn, kw in panels_list]
                sess_dates = {}
                for t, lbl, pn, _kw, dates in panel_dates:
                    sess_dates[lbl] = sorted(dates)
                suggestion = MosaicSuggestion(
                    suggested_name=base_name,
                    base_name=base_name,
                    target_ids=[t.id for t, _, _, _, _ in panel_dates],
                    panel_labels=[lbl for _, lbl, _, _, _ in panel_dates],
                    panel_patterns=panel_patterns,
                    session_dates=sess_dates,
                )
                session.add(suggestion)
                count += 1
            else:
                for cluster_dates in clusters:
                    cluster_set = set(cluster_dates)
                    suffix = _date_range_suffix(cluster_dates)
                    campaign_name = f"{base_name} {suffix}"

                    if base_name in accepted_bases:
                        continue

                    campaign_panels = [
                        (t, lbl, pn, kw)
                        for t, lbl, pn, kw, dates in panel_dates
                        if any(d in cluster_set for d in dates)
                    ]

                    if len(campaign_panels) < 2:
                        continue

                    sess_dates = {}
                    for t, lbl, pn, _kw, dates in panel_dates:
                        if any(d in cluster_set for d in dates):
                            sess_dates[lbl] = sorted(d for d in dates if d in cluster_set)

                    panel_patterns = [f"%{base_name}%{kw}%{pn}%" for _, _, pn, kw in campaign_panels]
                    suggestion = MosaicSuggestion(
                        suggested_name=campaign_name,
                        base_name=base_name,
                        target_ids=[t.id for t, _, _, _ in campaign_panels],
                        panel_labels=[lbl for _, lbl, _, _ in campaign_panels],
                        panel_patterns=panel_patterns,
                        session_dates=sess_dates,
                    )
                    session.add(suggestion)
                    count += 1

    else:
        for base_name, panels in groups.items():
            if len(panels) < 2:
                continue
            if base_name in accepted_bases:
                continue

            sess_dates = {}
            for t, label, panel_num, keyword in panels:
                obj_pattern = f"%{base_name}%{panel_num}%"
                dates_q = select(
                    func.distinct(Image.session_date)
                ).where(
                    Image.image_type == "LIGHT",
                    Image.raw_headers["OBJECT"].astext.ilike(obj_pattern),
                )
                result = await session.execute(dates_q)
                raw_dates = result.scalars().all()
                date_strs = sorted(
                    d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d)
                    for d in raw_dates
                    if d is not None
                )
                sess_dates[label] = date_strs

            panel_patterns = [f"%{base_name}%{kw}%{pn}%" for _, _, pn, kw in panels]
            suggestion = MosaicSuggestion(
                suggested_name=base_name,
                base_name=base_name,
                target_ids=[t.id for t, _, _, _ in panels],
                panel_labels=[label for _, label, _, _ in panels],
                panel_patterns=panel_patterns,
                session_dates=sess_dates,
            )
            session.add(suggestion)
            count += 1

    await session.commit()
    return count
