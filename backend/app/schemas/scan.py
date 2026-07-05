from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class ScanAcceptResponse(BaseModel):
    status: str
    message: str | None = None
    task_id: str | None = None


class ScanQueueResponse(BaseModel):
    """Response for /scan (POST) - covers accepted and already_running shapes."""
    status: str
    message: str | None = None
    # Fields present when already_running
    state: str | None = None
    total: int | None = None
    completed: int | None = None
    failed: int | None = None
    started_at: float | None = None
    completed_at: float | None = None
    csv_enriched: int | None = None
    discovered: int | None = None
    removed: int | None = None
    skipped_calibration: int | None = None
    new_files: int | None = None
    changed_files: int | None = None


class RegenerateThumbnailsResponse(BaseModel):
    status: str
    message: str | None = None
    task_id: str | None = None
    queued: int | None = None


class ScanStateResponse(BaseModel):
    """Response for /scan/status - scan state snapshot with optional failed_files."""
    state: str
    total: int
    completed: int
    failed: int
    started_at: float | None = None
    completed_at: float | None = None
    csv_enriched: int = 0
    discovered: int = 0
    removed: int = 0
    skipped_calibration: int = 0
    new_files: int = 0
    changed_files: int = 0
    failed_files: list[str] | None = None


class ScanStopResponse(BaseModel):
    status: str
    state: str | None = None
    message: str | None = None


class ScanResetResponse(BaseModel):
    status: str
    previous_state: str
    completed: int
    failed: int
    total: int


class RebuildStatusResponse(BaseModel):
    state: str
    mode: str
    message: str
    started_at: float | None = None
    completed_at: float | None = None
    details: dict[str, Any]


class DbSummaryResponse(BaseModel):
    total_images: int
    light_frames: int
    resolved_targets: int
    unresolved_images: int
    cached_simbad: int
    cached_negative: int
    pending_merges: int
    csv_enriched: int
    cached_vizier: int
    cached_vizier_negative: int
    cached_sesame: int
    cached_sesame_negative: int


class BackfillCsvResponse(BaseModel):
    status: str
    state: str | None = None
