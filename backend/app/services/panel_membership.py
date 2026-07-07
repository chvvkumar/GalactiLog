"""Panel membership persistence: DB reads/writes on Image / MosaicPanel /
MosaicPanelSession.

Split out of ``mosaic_detection.py`` (Task 5 of the phase-6 file-size
retrofit); re-exported there so every existing import site keeps working.
"""

from sqlalchemy import select, delete, exists, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.models import UserSettings, SETTINGS_ROW_ID
from app.models.image import Image
from app.models.mosaic_panel import MosaicPanel
from app.models.mosaic_panel_session import MosaicPanelSession
from app.services.panel_tokens import match_panel_token_full, _panel_label


async def load_mosaic_keywords(session: AsyncSession) -> list[str]:
    """Load the configured panel keywords (e.g. ["Panel", "P"]) used by both
    detection and every accepted-mosaic panel-matching call site so they all
    re-parse OBJECT strings with the same tokenizer."""
    settings = await session.get(UserSettings, SETTINGS_ROW_ID)
    general = settings.general if settings else {}
    return general.get("mosaic_keywords", ["Panel", "P"]) or []


def load_mosaic_keywords_sync(session: Session) -> list[str]:
    """Synchronous twin of :func:`load_mosaic_keywords` for the Celery sync
    worker (plain ``Session``, not ``AsyncSession``)."""
    settings = session.get(UserSettings, SETTINGS_ROW_ID)
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


async def retro_link_panel_images(
    session: AsyncSession,
    panel_id,
    target_id,
    panel_label: str,
) -> None:
    """Claim already-ingested frames for a newly created (or restored)
    MosaicPanel.

    Ingest (and the 0018 backfill) stamp ``Image.panel_label`` on token-bearing
    frames but leave ``Image.panel_id`` NULL when no ``MosaicPanel`` exists yet.
    Without this retro-link, a panel created (or, e.g., re-created by a backup
    restore) after those frames were ingested would start with zero stats
    until every file was re-ingested. Only frames whose parsed label matches
    exactly are claimed; token-bearing frames with other labels and unlabeled
    frames are never touched, matching the established ingest/backfill
    semantics. Runs in the caller's transaction.

    Lives in the service layer (not ``app.api.mosaics``) so non-API callers
    such as backup restore can use it without importing from the API layer.
    """
    await session.execute(
        update(Image)
        .where(
            Image.resolved_target_id == target_id,
            Image.panel_label == panel_label,
            Image.panel_id.is_(None),
        )
        .values(panel_id=panel_id)
    )


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


def _prepare_recompute_groups(
    rows, keywords: list[str]
) -> tuple[dict[tuple, list], dict]:
    """Shared, pure core of the recompute step (no I/O), used by both the
    async and sync variants of ``recompute_panel_membership_for_images``.

    ``rows`` is an iterable of ``(image_id, resolved_target_id, panel_label,
    object_name)``. Images that already carry a ``panel_label`` use it as-is
    (it was parsed once at ingest/backfill time and does not change). Images
    with a NULL ``panel_label`` -- e.g. orphan frames ingested before their
    target was resolved, since the ingest hook only stamps ``panel_label``
    when ``target_id`` is already known -- are re-tokenized here against their
    raw ``OBJECT`` header with the same ``match_panel_token_full`` tokenizer
    ``resolve_panel_membership`` uses, so a late-resolved frame with a real
    token (e.g. "NGC 1234 Panel 3") can still gain a label instead of being
    stuck at NULL forever.

    Returns ``(groups, label_updates)``:
      - ``groups``: ``(target_id, effective_panel_label) -> [image_id, ...]``,
        the input to the panel_id lookup step.
      - ``label_updates``: ``image_id -> newly derived panel_label``, only for
        images whose NULL label was just resolved to a real token and needs
        persisting back onto the row.
    """
    groups: dict[tuple, list] = {}
    label_updates: dict = {}
    for img_id, target_id, panel_label, object_name in rows:
        effective_label = panel_label
        if effective_label is None:
            token = match_panel_token_full(object_name, keywords)
            if token is not None:
                _base, num, _keyword = token
                effective_label = _panel_label(num)
                label_updates[img_id] = effective_label
        groups.setdefault((target_id, effective_label), []).append(img_id)
    return groups, label_updates


def _panel_id_lookup_stmt(target_id, panel_label: str | None):
    """Build the (shared) SELECT that resolves a panel_id for one
    (target_id, panel_label) group, mirroring ``resolve_panel_membership``'s
    two branches. Returns ``(statement, is_simple_fallback)``; the caller
    executes it (sync or async) and applies the "exactly one" fallback rule
    when ``is_simple_fallback`` is True.
    """
    if panel_label is not None:
        return (
            select(MosaicPanel.id).where(
                MosaicPanel.target_id == target_id,
                MosaicPanel.panel_label == panel_label,
            ),
            False,
        )
    return (
        select(MosaicPanel.id).where(
            MosaicPanel.target_id == target_id,
            MosaicPanel.object_pattern.is_(None),
        ),
        True,
    )


def _pick_panel_id(ids: list, is_simple_fallback: bool):
    if is_simple_fallback:
        return ids[0] if len(ids) == 1 else None
    return ids[0] if ids else None


async def recompute_panel_membership_for_images(session: AsyncSession, image_ids) -> None:
    """Recompute ``Image.panel_id`` (and, when missing, re-derive and persist
    ``Image.panel_label``) for images whose ``resolved_target_id`` just
    changed outside ingest (target unmerge, merge-candidate revert,
    orphan-to-target attach, custom-target retro-link), keeping panel
    membership in agreement with ``resolve_panel_membership``'s lookup
    semantics.

    ``Image.panel_label`` is normally parsed once at ingest time and is
    independent of target assignment, so for most images only the
    ``panel_id`` lookup (keyed on the image's *current* ``resolved_target_id``
    and its stored ``panel_label``) needs to be redone. But orphan frames
    ingested before their target was known never got a ``panel_label`` (the
    ingest hook requires ``target_id``), so images with a NULL label are
    re-tokenized against their raw ``OBJECT`` header here (see
    ``_prepare_recompute_groups``) instead of being stuck at NULL forever.

    Call this after any bulk update that changes ``Image.resolved_target_id``
    for a set of images -- including setting it to ``NULL``, in which case
    ``panel_id`` is cleared to match (no target means no valid panel
    membership). When the image's current target has no matching panel for
    its (stored or freshly re-tokenized) label, ``panel_id`` is cleared rather
    than left stale.
    """
    ids = [i for i in image_ids if i is not None]
    if not ids:
        return

    keywords = await load_mosaic_keywords(session)

    rows = (await session.execute(
        select(
            Image.id, Image.resolved_target_id, Image.panel_label,
            Image.raw_headers["OBJECT"].astext.label("object_name"),
        ).where(Image.id.in_(ids))
    )).all()

    groups, label_updates = _prepare_recompute_groups(rows, keywords)

    label_groups: dict[str, list] = {}
    for img_id, label in label_updates.items():
        label_groups.setdefault(label, []).append(img_id)
    for label, label_ids in label_groups.items():
        await session.execute(
            update(Image).where(Image.id.in_(label_ids)).values(panel_label=label)
        )

    for (target_id, panel_label), group_ids in groups.items():
        new_panel_id = None
        if target_id is not None:
            stmt, is_simple_fallback = _panel_id_lookup_stmt(target_id, panel_label)
            ids_found = (await session.execute(stmt)).scalars().all()
            new_panel_id = _pick_panel_id(ids_found, is_simple_fallback)

        await session.execute(
            update(Image).where(Image.id.in_(group_ids)).values(panel_id=new_panel_id)
        )


def recompute_panel_membership_for_images_sync(session: Session, image_ids) -> None:
    """Synchronous twin of :func:`recompute_panel_membership_for_images` for
    the Celery sync worker's bulk target-resolution tasks (``rebuild_targets``,
    ``retry_unresolved``, ``backfill_catalog_identity``,
    ``detect_duplicate_targets``, ``smart_rebuild_targets``), which all run in
    a plain ``Session`` and set ``Image.resolved_target_id`` in bulk UPDATEs
    without ever touching panel membership on their own. Shares the exact same
    core grouping/re-tokenizing logic (``_prepare_recompute_groups``) as the
    async variant -- only the I/O (no ``await``) differs.
    """
    ids = [i for i in image_ids if i is not None]
    if not ids:
        return

    keywords = load_mosaic_keywords_sync(session)

    rows = session.execute(
        select(
            Image.id, Image.resolved_target_id, Image.panel_label,
            Image.raw_headers["OBJECT"].astext.label("object_name"),
        ).where(Image.id.in_(ids))
    ).all()

    groups, label_updates = _prepare_recompute_groups(rows, keywords)

    label_groups: dict[str, list] = {}
    for img_id, label in label_updates.items():
        label_groups.setdefault(label, []).append(img_id)
    for label, label_ids in label_groups.items():
        session.execute(
            update(Image).where(Image.id.in_(label_ids)).values(panel_label=label)
        )

    for (target_id, panel_label), group_ids in groups.items():
        new_panel_id = None
        if target_id is not None:
            stmt, is_simple_fallback = _panel_id_lookup_stmt(target_id, panel_label)
            ids_found = session.execute(stmt).scalars().all()
            new_panel_id = _pick_panel_id(ids_found, is_simple_fallback)

        session.execute(
            update(Image).where(Image.id.in_(group_ids)).values(panel_id=new_panel_id)
        )
