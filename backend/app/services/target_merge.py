"""Target merge/unmerge/preview business logic.

Pure extraction of the logic that used to live inline in app/api/merges.py.
HTTP concerns (status codes via HTTPException) are preserved so handler
behavior is unchanged.
"""

import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.target import Target
from app.models.image import Image
from app.models.merge_candidate import MergeCandidate
from app.models.merge_manifest import MergeManifest
from app.models.mosaic_panel import MosaicPanel
from app.models.mosaic_suggestion import MosaicSuggestion
from app.models.session_note import SessionNote
from app.models.custom_column import CustomColumnValue
from app.schemas.target import (
    MergeRequest, MergePreviewRequest, MergePreviewResponse, MergePreviewSide,
)
from app.services.cache import invalidate_stats_and_analysis_cache
from app.services.mosaic_detection import recompute_panel_membership_for_images


async def _record_merge_manifest(loser, winner, session: AsyncSession) -> None:
    """Persist exactly what a loser->winner merge moved, for lossless reversal.

    Captures the exact image id set reassigned to the winner, plus the loser's
    session notes (re-keyed to the winner when the date is free, appended to the
    winner's existing note otherwise) and non-conflicting custom column values
    (re-keyed to the winner). The recorded manifest lets unmerge/revert restore
    the precise pre-merge state instead of re-deriving it from OBJECT headers.

    Must be called BEFORE the images are reassigned so the captured id set
    reflects loser membership.
    """
    # Exact set of images currently on the loser (before reassignment). This is
    # the only reliable record of filename-resolved images (blank OBJECT header)
    # that a later OBJECT-text restore would miss (AUD-005).
    moved_rows = (await session.execute(
        select(Image.id).where(Image.resolved_target_id == loser.id)
    )).scalars().all()
    moved_image_ids = [str(i) for i in moved_rows]

    # Session notes: keep the loser's notes visible on the winner post-merge
    # (AUD-018) while recording enough to restore them on unmerge.
    notes_rekeyed: list[str] = []
    notes_appended: list[dict] = []
    loser_notes = (await session.execute(
        select(SessionNote).where(SessionNote.target_id == loser.id)
    )).scalars().all()
    if loser_notes:
        winner_notes = (await session.execute(
            select(SessionNote).where(SessionNote.target_id == winner.id)
        )).scalars().all()
        winner_by_date = {n.session_date: n for n in winner_notes}
        for ln in loser_notes:
            wn = winner_by_date.get(ln.session_date)
            if wn is None:
                # Winner has no note for this date: move the loser's note over.
                ln.target_id = winner.id
                notes_rekeyed.append(str(ln.id))
            else:
                # Winner already has a note for this date: append the loser's
                # text (remembering the prior text) and leave the loser's own
                # row in place so it reappears on the loser after unmerge.
                notes_appended.append({"note_id": str(wn.id), "prev_text": wn.notes})
                wn.notes = (
                    f"{wn.notes}\n\n--- merged from {loser.primary_name} ---\n{ln.notes}"
                )

    # Custom column values: copy non-conflicting loser values onto the winner so
    # they are visible post-merge (AUD-018). Conflicts (winner already has a
    # value for the same column/session/rig slot) keep the winner's value and
    # leave the loser's row untouched (it reappears on unmerge).
    ccv_rekeyed: list[str] = []
    loser_ccvs = (await session.execute(
        select(CustomColumnValue).where(CustomColumnValue.target_id == loser.id)
    )).scalars().all()
    if loser_ccvs:
        winner_ccvs = (await session.execute(
            select(CustomColumnValue).where(CustomColumnValue.target_id == winner.id)
        )).scalars().all()
        # Mirror the unique index (column_id, target, mosaic, session_date,
        # rig_label); target is the winner on both sides after a copy, so the
        # slot is identified by (column_id, session_date, rig_label).
        winner_keys = {(c.column_id, c.session_date, c.rig_label) for c in winner_ccvs}
        for lc in loser_ccvs:
            key = (lc.column_id, lc.session_date, lc.rig_label)
            if key in winner_keys:
                continue
            lc.target_id = winner.id
            winner_keys.add(key)
            ccv_rekeyed.append(str(lc.id))

    session.add(MergeManifest(
        winner_id=winner.id,
        loser_id=loser.id,
        payload={
            "image_ids": moved_image_ids,
            "notes_rekeyed": notes_rekeyed,
            "notes_appended": notes_appended,
            "ccv_rekeyed": ccv_rekeyed,
        },
    ))


async def apply_merge_manifest_restore(manifest, loser, winner, session: AsyncSession) -> list:
    """Reverse a merge exactly, using the recorded manifest.

    Reassigns the recorded image id set back to the loser, moves re-keyed
    session notes and custom values back, and restores appended winner notes to
    their pre-merge text. Shared by unmerge_target and revert_merge_candidate.

    Returns the list of moved image ids (as ``uuid.UUID``) so the caller can
    recompute their panel membership at the right point in its own flow.
    Deliberately does NOT recompute panel membership itself: unmerge_target
    also moves MosaicPanel rows back to the loser (panel-target reversion,
    based on object_pattern substring match) in a step that runs AFTER this
    function returns, and panel membership must be recomputed only once that
    reversion has happened -- recomputing here first would look up a panel
    under the loser before it exists there, incorrectly clearing panel_id for
    images whose panel is legitimately about to move back.
    """
    payload = manifest.payload or {}

    image_ids = payload.get("image_ids") or []
    image_uuids: list = []
    if image_ids:
        image_uuids = [uuid.UUID(i) for i in image_ids]
        await session.execute(
            update(Image)
            .where(
                Image.id.in_(image_uuids),
                Image.resolved_target_id == winner.id,
            )
            .values(resolved_target_id=loser.id)
        )

    note_ids = payload.get("notes_rekeyed") or []
    if note_ids:
        await session.execute(
            update(SessionNote)
            .where(SessionNote.id.in_([uuid.UUID(i) for i in note_ids]))
            .values(target_id=loser.id)
        )

    for entry in payload.get("notes_appended") or []:
        await session.execute(
            update(SessionNote)
            .where(SessionNote.id == uuid.UUID(entry["note_id"]))
            .values(notes=entry["prev_text"])
        )

    ccv_ids = payload.get("ccv_rekeyed") or []
    if ccv_ids:
        await session.execute(
            update(CustomColumnValue)
            .where(CustomColumnValue.id.in_([uuid.UUID(i) for i in ccv_ids]))
            .values(target_id=loser.id)
        )

    return image_uuids


async def _find_merge_manifest(loser_id, winner_id, session: AsyncSession):
    """Return the most recent merge manifest for a (loser, winner) pair, or None."""
    return (await session.execute(
        select(MergeManifest)
        .where(
            MergeManifest.loser_id == loser_id,
            MergeManifest.winner_id == winner_id,
        )
        .order_by(MergeManifest.created_at.desc())
        .limit(1)
    )).scalars().first()


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

        # Record exactly what this merge moves BEFORE reassigning images, so an
        # unmerge/revert can be replayed precisely instead of re-deriving image
        # membership from OBJECT headers (which strands filename-resolved images
        # with blank OBJECT headers -- AUD-005). This also re-keys/appends the
        # loser's session notes and non-conflicting custom values onto the
        # winner so they stay visible after the merge (AUD-018).
        await _record_merge_manifest(loser, winner, session)

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
        resolved_rows = (await session.execute(
            update(Image)
            .where(
                Image.raw_headers["OBJECT"].astext == loser_name,
                Image.resolved_target_id.is_(None),
            )
            .values(resolved_target_id=winner.id)
            .returning(Image.id)
        )).scalars().all()
        # These images were unresolved at ingest, so panel membership was
        # never attempted; recompute now that they have a target.
        await recompute_panel_membership_for_images(session, resolved_rows)

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
    # Statistics/Analysis caches are stale after a merge (new membership,
    # renamed-via-alias target); invalidate so both pages reflect it
    # immediately instead of waiting out the TTL (AUD-034).
    await invalidate_stats_and_analysis_cache()
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

    # Prefer the persisted merge manifest for an exact reversal (restores ALL
    # moved images, including filename-resolved ones, plus notes/custom values).
    # Merges made before manifests existed have none, so fall back to the legacy
    # OBJECT-header name match (lossy for filename-resolved images, but the only
    # information available for those older merges).
    manifest = await _find_merge_manifest(loser.id, winner.id, session)
    moved_image_ids: list = []
    if manifest is not None:
        moved_image_ids = await apply_merge_manifest_restore(manifest, loser, winner, session)
        await session.delete(manifest)
    else:
        # Legacy fallback: reassign images back to loser based on OBJECT header
        # matching loser's names.
        for name in loser_names:
            rows = (await session.execute(
                update(Image)
                .where(
                    Image.resolved_target_id == winner.id,
                    Image.raw_headers["OBJECT"].astext == name,
                )
                .values(resolved_target_id=loser.id)
                .returning(Image.id)
            )).scalars().all()
            moved_image_ids.extend(rows)

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

    # Recompute panel membership for the moved images now that both their
    # resolved_target_id AND any panels moving back to the loser (just above)
    # have settled -- doing this before the panel reversion would look up a
    # panel under the loser before it exists there and incorrectly clear
    # panel_id for images whose panel is legitimately moving back too.
    if moved_image_ids:
        await recompute_panel_membership_for_images(session, moved_image_ids)

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
    # See the matching comment in merge_targets (AUD-034).
    await invalidate_stats_and_analysis_cache()
    return {"status": "ok"}
