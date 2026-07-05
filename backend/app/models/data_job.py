import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class DataJobStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    interrupted = "interrupted"


class DataJob(Base):
    """Durable per-job record for backfills that must survive worker restarts.

    A job is identified by (job_type, job_key) - job_type names the kind of
    work (e.g. "data_migration"; future: "scan", "rebuild"), job_key
    identifies a specific run of that kind (e.g. the target DATA_VERSION for
    a data-migration run). A restarted worker looks up the existing row by
    that pair to resume or restart idempotently instead of blindly redoing
    completed work.

    step/total_steps/message are named to align with the {task, step,
    total_steps, percent, message} progress envelope a future API endpoint
    will expose; job_type doubles as that envelope's "task" and "percent" is
    derived from step/total_steps rather than stored.
    """

    __tablename__ = "data_jobs"
    __table_args__ = (
        UniqueConstraint("job_type", "job_key", name="uq_data_jobs_type_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_type: Mapped[str] = mapped_column(String(64), nullable=False)
    job_key: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[DataJobStatus] = mapped_column(
        Enum(DataJobStatus, name="data_job_status_enum"),
        nullable=False,
        default=DataJobStatus.pending,
        index=True,
    )
    step: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_steps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    enqueued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
