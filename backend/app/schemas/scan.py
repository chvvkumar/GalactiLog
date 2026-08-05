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
    task: str | None = None
    step: int | None = None
    total_steps: int | None = None
    percent: float | None = None
    message: str | None = None


class RegenerateThumbnailsResponse(BaseModel):
    status: str
    message: str | None = None
    task_id: str | None = None
    queued: int | None = None


class ScanFailedFile(BaseModel):
    """One entry of the per-scan failed-file list.

    Key names must match what ``increment_failed_sync`` pushes onto
    ``SCAN_FAILED_KEY`` (app/services/scan_state.py):
    ``json.dumps({"file": file_path, "error": error})``.
    """
    file: str
    error: str


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
    phd2_found: int = 0
    phd2_ingested: int = 0
    phd2_failed: int = 0
    # "" | pending | running. The guide-log pass outlives the image scan, so
    # ``state == "complete"`` alone does not mean the scan is finished. A
    # caller that needs everything done waits for this to be "" as well; the
    # phd2_* counters above only describe the current pass once it is.
    phd2_state: str = ""
    # Unix time phd2_state was last written, or null. A "pending" claim has no
    # expiry of its own - a task queued and then lost never clears it - so a
    # consumer that would otherwise wait on the flag forever ages it out on
    # this instead.
    phd2_state_at: float | None = None
    failed_files: list[ScanFailedFile] | None = None
    task: str = ""
    step: int = 0
    total_steps: int = 0
    percent: float = 0.0
    message: str = ""


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


class ProgressEnvelope(BaseModel):
    """Structured progress shape from docs/retrofit-roadmap.md Phase 3:
    {task, step, total_steps, percent, message}.

    ``percent`` is always derived from ``step``/``total_steps`` via
    ``for_progress`` -- it is never stored as its own Redis field or DB
    column (see app.services.progress_envelope and the DataJob model
    docstring, which independently arrived at the same "derived, not
    stored" intent for Phase 2's data-migration jobs). Scale is 0-100,
    float, rounded to one decimal place.
    """
    task: str
    step: int
    total_steps: int
    percent: float
    message: str

    @classmethod
    def for_progress(cls, task: str, step: int, total_steps: int, message: str) -> "ProgressEnvelope":
        percent = round(100 * step / total_steps, 1) if total_steps > 0 else 0.0
        return cls(task=task, step=step, total_steps=total_steps, percent=percent, message=message)


class RebuildStatusResponse(BaseModel):
    state: str
    mode: str
    message: str
    started_at: float | None = None
    completed_at: float | None = None
    details: dict[str, Any]
    step: int | None = None
    total_steps: int | None = None
    percent: float | None = None


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
