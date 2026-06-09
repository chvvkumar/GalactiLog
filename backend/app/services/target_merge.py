"""Target merge/unmerge/preview business logic.

Pure extraction of the logic that used to live inline in app/api/merges.py.
HTTP concerns (status codes via HTTPException) are preserved so handler
behavior is unchanged.
"""

from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.target import Target
from app.models.image import Image
from app.models.merge_candidate import MergeCandidate
from app.models.mosaic_panel import MosaicPanel
from app.models.mosaic_suggestion import MosaicSuggestion
from app.schemas.target import (
    MergeRequest, MergePreviewRequest, MergePreviewResponse, MergePreviewSide,
)


async def merge_targets(body: MergeRequest, session: AsyncSession) -> dict:
    """Merge a loser target (by id or unresolved name) into a winner target."""
    # Load winner
    winner = await session.get(Target, body.winner_id)
    if not winner:
        raise HTTPException(status_code=404, detail="Winner target not found")

    now = datetime.now(timezone.utc)

    if body.loser_id is not None:
        # Merge by target ID: move images, merge aliases, soft-delete loser
        loser = await session.get(Target, body.loser_id)
        if not loser:
            raise HTTPException(status_code=404, detail="Loser target not found")
        if loser.id == winner.id:
            raise HTTPException(status_code=400, detail="Winner and loser must be different targets")

        # Move all images from loser to winner
        await session.execute(
            update(Image)
            .where(Image.resolved_target_id == loser.id)
            .values(resolved_target_id=winner.id)
        )

        # Merge aliases: add loser's primary_name and all its aliases to winner
        new_aliases = list(winner.aliases or [])
        if loser.primary_name not in new_aliases and loser.primary_name != winner.primary_name:
            new_aliases.append(loser.primary_name)
        for alias in (loser.aliases or []):
            if alias not in new_aliases and alias != winner.primary_name:
                new_aliases.append(alias)
        winner.aliases = new_aliases

        # Update mosaic panels: reassign panels from loser to winner
        loser_panels_q = select(MosaicPanel).where(MosaicPanel.target_id == loser.id)
        loser_panels = (await session.execute(loser_panels_q)).scalars().all()
        for panel in loser_panels:
            panel.target_id = winner.id

        # Update mosaic suggestions: replace loser id with winner id in target_ids arrays
        suggestions_q = select(MosaicSuggestion).where(
            MosaicSuggestion.status == "pending"
        )
        all_suggestions = (await session.execute(suggestions_q)).scalars().all()
        for sug in all_suggestions:
            if loser.id in sug.target_ids:
                sug.target_ids = [winner.id if t == loser.id else t for t in sug.target_ids]

        # Soft-delete loser
        loser.merged_into_id = winner.id
        loser.merged_at = now

        # Mark related merge_candidates as accepted (candidates pointing to winner where source_name matches loser names)
        loser_names = set([loser.primary_name] + list(loser.aliases or []))
        await session.execute(
            update(MergeCandidate)
            .where(
                MergeCandidate.suggested_target_id == winner.id,
                MergeCandidate.source_name.in_(loser_names),
                MergeCandidate.status == "pending",
            )
            .values(status="accepted", resolved_at=now)
        )
        # Also accept candidates where suggested_target is the loser
        await session.execute(
            update(MergeCandidate)
            .where(
                MergeCandidate.suggested_target_id == loser.id,
                MergeCandidate.status == "pending",
            )
            .values(status="accepted", resolved_at=now)
        )

    elif body.loser_name is not None:
        # Merge unresolved name: add as alias to winner, resolve images with that OBJECT header
        loser_name = body.loser_name
        new_aliases = list(winner.aliases or [])
        if loser_name not in new_aliases and loser_name != winner.primary_name:
            new_aliases.append(loser_name)
        winner.aliases = new_aliases

        # Resolve all images whose OBJECT header matches loser_name and have no target (or wrong target)
        await session.execute(
            update(Image)
            .where(
                Image.raw_headers["OBJECT"].astext == loser_name,
                Image.resolved_target_id.is_(None),
            )
            .values(resolved_target_id=winner.id)
        )

        # Mark related merge_candidates as accepted
        await session.execute(
            update(MergeCandidate)
            .where(
                MergeCandidate.suggested_target_id == winner.id,
                MergeCandidate.source_name == loser_name,
                MergeCandidate.status == "pending",
            )
            .values(status="accepted", resolved_at=now)
        )

        # Also accept orphan candidates for this source_name
        await session.execute(
            update(MergeCandidate)
            .where(
                MergeCandidate.source_name == loser_name,
                MergeCandidate.suggested_target_id.is_(None),
                MergeCandidate.status == "pending",
            )
            .values(status="accepted", resolved_at=now, suggested_target_id=winner.id)
        )

    else:
        raise HTTPException(status_code=400, detail="Either loser_id or loser_name must be provided")

    await session.commit()
    return {"status": "ok"}


async def merge_preview(body: MergePreviewRequest, session: AsyncSession) -> MergePreviewResponse:
    """Preview the effect of a merge without making any changes."""
    if body.loser_id is None and body.loser_name is None:
        raise HTTPException(status_code=400, detail="Either loser_id or loser_name must be provided")

    # Load winner
    winner = await session.get(Target, body.winner_id)
    if not winner or winner.merged_into_id is not None:
        raise HTTPException(status_code=404, detail="Winner target not found")

    # Compute winner stats
    winner_image_result = await session.execute(
        select(
            func.count(Image.id).label("image_count"),
            func.count(func.distinct(Image.session_date)).label("session_count"),
            func.coalesce(func.sum(Image.exposure_time), 0.0).label("integration_seconds"),
        ).where(Image.resolved_target_id == winner.id)
    )
    winner_stats = winner_image_result.one()

    winner_side = MergePreviewSide(
        id=winner.id,
        primary_name=winner.primary_name,
        object_type=winner.object_type,
        constellation=winner.constellation,
        image_count=winner_stats.image_count or 0,
        session_count=winner_stats.session_count or 0,
        integration_seconds=float(winner_stats.integration_seconds or 0.0),
        aliases=list(winner.aliases or []),
    )

    if body.loser_id is not None:
        loser = await session.get(Target, body.loser_id)
        if not loser or loser.merged_into_id is not None:
            raise HTTPException(status_code=404, detail="Loser target not found")

        # Compute loser stats
        loser_image_result = await session.execute(
            select(
                func.count(Image.id).label("image_count"),
                func.count(func.distinct(Image.session_date)).label("session_count"),
                func.coalesce(func.sum(Image.exposure_time), 0.0).label("integration_seconds"),
            ).where(Image.resolved_target_id == loser.id)
        )
        loser_stats = loser_image_result.one()

        # Count mosaic panels to move
        panel_count_result = await session.execute(
            select(func.count(MosaicPanel.id)).where(MosaicPanel.target_id == loser.id)
        )
        panels_to_move = panel_count_result.scalar_one() or 0

        # Compute aliases that would be added to winner
        existing = set(list(winner.aliases or []) + [winner.primary_name])
        aliases_to_add = []
        if loser.primary_name not in existing:
            aliases_to_add.append(loser.primary_name)
        for alias in (loser.aliases or []):
            if alias not in existing and alias not in aliases_to_add:
                aliases_to_add.append(alias)

        loser_side = MergePreviewSide(
            id=loser.id,
            primary_name=loser.primary_name,
            object_type=loser.object_type,
            constellation=loser.constellation,
            image_count=loser_stats.image_count or 0,
            session_count=loser_stats.session_count or 0,
            integration_seconds=float(loser_stats.integration_seconds or 0.0),
            aliases=list(loser.aliases or []),
        )

        return MergePreviewResponse(
            winner=winner_side,
            loser=loser_side,
            images_to_move=loser_stats.image_count or 0,
            mosaic_panels_to_move=panels_to_move,
            aliases_to_add=aliases_to_add,
        )

    else:
        # loser_name path: count unresolved images with that OBJECT header
        loser_name = body.loser_name
        unresolved_result = await session.execute(
            select(func.count(Image.id)).where(
                Image.raw_headers["OBJECT"].astext == loser_name,
                Image.resolved_target_id.is_(None),
            )
        )
        unresolved_count = unresolved_result.scalar_one() or 0

        loser_side = MergePreviewSide(
            primary_name=loser_name,
            image_count=unresolved_count,
        )

        existing = set(list(winner.aliases or []) + [winner.primary_name])
        aliases_to_add = [loser_name] if loser_name not in existing else []

        return MergePreviewResponse(
            winner=winner_side,
            loser=loser_side,
            images_to_move=unresolved_count,
            mosaic_panels_to_move=0,
            aliases_to_add=aliases_to_add,
        )


async def unmerge_target(target_id, session: AsyncSession) -> dict:
    """Restore a soft-deleted (merged) target."""
    loser = await session.get(Target, target_id)
    if not loser:
        raise HTTPException(status_code=404, detail="Target not found")
    if not loser.merged_into_id:
        raise HTTPException(status_code=400, detail="Target has not been merged")

    winner = await session.get(Target, loser.merged_into_id)
    if not winner:
        raise HTTPException(status_code=404, detail="Winner target not found")

    # Determine the names that belong to the loser (primary + aliases recorded at merge time)
    loser_names = set([loser.primary_name] + list(loser.aliases or []))

    # Reassign images back to loser based on OBJECT header matching loser's names
    for name in loser_names:
        await session.execute(
            update(Image)
            .where(
                Image.resolved_target_id == winner.id,
                Image.raw_headers["OBJECT"].astext == name,
            )
            .values(resolved_target_id=loser.id)
        )

    # Remove loser's names from winner's aliases
    winner_aliases = [a for a in (winner.aliases or []) if a not in loser_names]
    winner.aliases = winner_aliases

    # Revert mosaic panel reassignment: move panels back to loser
    # Only reassign panels whose object_pattern matches the loser's names
    winner_panels_q = select(MosaicPanel).where(MosaicPanel.target_id == winner.id)
    winner_panels = (await session.execute(winner_panels_q)).scalars().all()
    for panel in winner_panels:
        if panel.object_pattern:
            pattern_lower = panel.object_pattern.lower()
            for name in loser_names:
                if name.lower() in pattern_lower:
                    panel.target_id = loser.id
                    break

    # Clear merge fields on loser
    loser.merged_into_id = None
    loser.merged_at = None

    # Reset merge_candidates back to pending
    loser_names_list = list(loser_names)
    await session.execute(
        update(MergeCandidate)
        .where(
            MergeCandidate.suggested_target_id == winner.id,
            MergeCandidate.source_name.in_(loser_names_list),
            MergeCandidate.status == "accepted",
        )
        .values(status="pending", resolved_at=None)
    )
    await session.execute(
        update(MergeCandidate)
        .where(
            MergeCandidate.suggested_target_id == loser.id,
            MergeCandidate.status == "accepted",
        )
        .values(status="pending", resolved_at=None)
    )

    await session.commit()
    return {"status": "ok"}
