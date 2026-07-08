import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class MergeManifest(Base):
    """Records exactly what a target merge moved, so an unmerge/revert can be
    replayed precisely instead of re-deriving membership from OBJECT headers.

    Created when ``merge_targets`` merges a real loser target (by id) into a
    winner. ``payload`` captures the exact image id set that was reassigned,
    the session-note rows re-keyed or appended, and the custom-column-value
    rows re-keyed. ``unmerge_target`` and ``revert_merge_candidate`` consume
    (and delete) the manifest to reverse the merge losslessly. Merges made
    before this table existed have no manifest, so those paths fall back to the
    legacy OBJECT-header name-matching restore.
    """

    __tablename__ = "merge_manifests"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    winner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("targets.id", ondelete="CASCADE"), nullable=False
    )
    loser_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("targets.id", ondelete="CASCADE"), nullable=True
    )
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_merge_manifests_winner", "winner_id"),
        Index("ix_merge_manifests_loser", "loser_id"),
    )
