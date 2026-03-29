import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base

SETTINGS_ROW_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")


class UserSettings(Base):
    __tablename__ = "user_settings"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=SETTINGS_ROW_ID)
    general: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    filters: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    equipment: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    dismissed_suggestions: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    display: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    graph: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )

    def __init__(self, **kwargs):
        kwargs.setdefault("general", {})
        kwargs.setdefault("filters", {})
        kwargs.setdefault("equipment", {})
        kwargs.setdefault("dismissed_suggestions", [])
        kwargs.setdefault("display", {})
        kwargs.setdefault("graph", {})
        super().__init__(**kwargs)
