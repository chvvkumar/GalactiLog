import re
import uuid
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Target, UserSettings, SETTINGS_ROW_ID
from app.models.mosaic import Mosaic
from app.models.mosaic_panel import MosaicPanel
from app.models.mosaic_suggestion import MosaicSuggestion


async def detect_mosaic_panels(session: AsyncSession) -> int:
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
        rf"^(.+?)\s*[-_\s]?\s*(?:{kw_pattern})\s*[-_\s]?\s*(\d+)\s*$",
        re.IGNORECASE,
    )

    # Get all targets not already in a mosaic
    in_mosaic_q = select(MosaicPanel.target_id)
    in_mosaic = {r[0] for r in (await session.execute(in_mosaic_q)).all()}

    targets_q = select(Target).where(Target.merged_into_id.is_(None))
    targets = (await session.execute(targets_q)).scalars().all()

    # Group by base name
    groups: dict[str, list[tuple[Target, str]]] = defaultdict(list)
    for t in targets:
        if t.id in in_mosaic:
            continue
        # Check primary name and aliases
        names_to_check = [t.primary_name] + (t.aliases or [])
        for name in names_to_check:
            m = pattern.match(name)
            if m:
                base = m.group(1).strip()
                panel_num = m.group(2)
                groups[base].append((t, f"Panel {panel_num}"))
                break

    # Create suggestions for groups with 2+ panels
    # Skip if a suggestion for this base name already exists
    existing_q = select(MosaicSuggestion.suggested_name).where(MosaicSuggestion.status == "pending")
    existing_names = {r[0] for r in (await session.execute(existing_q)).all()}

    count = 0
    for base_name, panels in groups.items():
        if len(panels) < 2:
            continue
        if base_name in existing_names:
            continue

        suggestion = MosaicSuggestion(
            suggested_name=base_name,
            target_ids=[t.id for t, _ in panels],
            panel_labels=[label for _, label in panels],
        )
        session.add(suggestion)
        count += 1

    await session.commit()
    return count
