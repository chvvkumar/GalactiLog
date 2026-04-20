# Target Health Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the fragmented target management UI with a unified Target Health view, add merge preview, inline rename, post-scan summary, and reorganize maintenance buttons.

**Architecture:** Backend-first approach. Add the `name_locked` and `reason_text` columns, then build the three new API endpoints (merge-preview, identity, scan-summary), modify smart rebuild and duplicate detection, remove dead endpoints, and finally rebuild the frontend components.

**Tech Stack:** FastAPI + SQLAlchemy 2.0 async (backend), SolidJS + TypeScript + Tailwind CSS v4 (frontend), Alembic (migrations), pytest + httpx (tests)

**Spec:** `guides/superpowers/specs/2026-04-20-target-health-redesign-design.md`

---

## File Structure

### New files
- `backend/alembic/versions/0015_target_health_columns.py` - Migration adding `name_locked` and `reason_text`
- `backend/tests/test_api_merge_preview.py` - Tests for merge-preview endpoint
- `backend/tests/test_api_target_identity.py` - Tests for identity endpoint
- `backend/tests/test_api_scan_summary.py` - Tests for scan summary endpoint
- `frontend/src/components/settings/TargetHealthTab.tsx` - Replaces MergesTab
- `frontend/src/components/settings/IssueCard.tsx` - Individual issue card component
- `frontend/src/components/MergePreviewModal.tsx` - Replaces MergeTargetModal

### Modified files
- `backend/app/models/target.py` - Add `name_locked` column
- `backend/app/models/merge_candidate.py` - Add `reason_text` column
- `backend/app/schemas/target.py` - Add new request/response schemas
- `backend/app/api/merges.py` - Add merge-preview and identity endpoints
- `backend/app/api/scan.py` - Add scan-summary endpoint, remove backfill-targets and xmatch-enrichment
- `backend/app/worker/tasks.py` - Guard smart rebuild Phases 4-5 with `name_locked`, populate `reason_text` in detect_duplicate_targets, write scan_summary to Redis
- `backend/app/services/scan_state.py` - Write scan summary after post-scan chain completes
- `frontend/src/api/client.ts` - Add new API methods, remove dead ones
- `frontend/src/pages/SettingsPage.tsx` - Rename tab, swap component
- `frontend/src/pages/TargetDetailPage.tsx` - Add inline rename, re-resolve, swap merge modal
- `frontend/src/components/MaintenanceActions.tsx` - Reduce to Fetch Reference Images + Regen Thumbnails
- `frontend/src/store/activeJobs.ts` - Update mode labels

---

### Task 1: Database Migration

**Files:**
- Create: `backend/alembic/versions/0015_target_health_columns.py`
- Modify: `backend/app/models/target.py:14-38`
- Modify: `backend/app/models/merge_candidate.py:14-24`

- [ ] **Step 1: Create the migration file**

```python
"""add target health columns

Revision ID: 0015
Revises: 0014
Create Date: 2026-04-20
"""
from alembic import op
import sqlalchemy as sa

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def _add_column_if_not_exists(table, column_name, column):
    from sqlalchemy import inspect as sa_inspect
    bind = op.get_bind()
    inspector = sa_inspect(bind)
    columns = [c["name"] for c in inspector.get_columns(table)]
    if column_name not in columns:
        op.add_column(table, column)


def upgrade() -> None:
    _add_column_if_not_exists(
        "targets", "name_locked",
        sa.Column("name_locked", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    _add_column_if_not_exists(
        "merge_candidates", "reason_text",
        sa.Column("reason_text", sa.String(500), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("merge_candidates", "reason_text")
    op.drop_column("targets", "name_locked")
```

- [ ] **Step 2: Add `name_locked` to the Target model**

In `backend/app/models/target.py`, add after the `distance_pc` column (line 38):

```python
    name_locked = Column(Boolean, nullable=False, server_default=text("false"), default=False)
```

Add `Boolean` and `text` to the existing sqlalchemy imports at the top of the file.

- [ ] **Step 3: Add `reason_text` to the MergeCandidate model**

In `backend/app/models/merge_candidate.py`, add after the `resolved_at` column (line 24):

```python
    reason_text = Column(String(500), nullable=True)
```

- [ ] **Step 4: Run the migration**

Run: `cd backend && alembic upgrade head`
Expected: Migration 0015 applies successfully.

- [ ] **Step 5: Commit**

```bash
git add backend/alembic/versions/0015_target_health_columns.py backend/app/models/target.py backend/app/models/merge_candidate.py
git commit -m "feat: add name_locked and reason_text columns for target health"
```

---

### Task 2: Backend - Merge Preview Endpoint

**Files:**
- Modify: `backend/app/schemas/target.py:295-347`
- Modify: `backend/app/api/merges.py:20-145`
- Create: `backend/tests/test_api_merge_preview.py`

- [ ] **Step 1: Add Pydantic schemas**

In `backend/app/schemas/target.py`, add after the `MergeRequest` schema (after line 347):

```python
class MergePreviewRequest(BaseModel):
    winner_id: UUID
    loser_id: UUID | None = None
    loser_name: str | None = None

class MergePreviewSide(BaseModel):
    id: UUID | None = None
    primary_name: str
    object_type: str | None = None
    constellation: str | None = None
    image_count: int = 0
    session_count: int = 0
    integration_seconds: float = 0.0
    aliases: list[str] = []

class MergePreviewResponse(BaseModel):
    winner: MergePreviewSide
    loser: MergePreviewSide
    images_to_move: int = 0
    mosaic_panels_to_move: int = 0
    aliases_to_add: list[str] = []
```

- [ ] **Step 2: Write the failing test**

Create `backend/tests/test_api_merge_preview.py`:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.database import get_session
from app.api.deps import require_admin


@pytest.mark.asyncio
async def test_merge_preview_with_loser_id():
    winner_id = uuid4()
    loser_id = uuid4()

    winner = MagicMock()
    winner.id = winner_id
    winner.primary_name = "NGC 7000 - North America Nebula"
    winner.object_type = "HII"
    winner.constellation = "Cyg"
    winner.aliases = ["NGC 7000", "NGC7000"]
    winner.merged_into_id = None

    loser = MagicMock()
    loser.id = loser_id
    loser.primary_name = "North America Nebula"
    loser.object_type = "HII"
    loser.constellation = "Cyg"
    loser.aliases = ["NORTH AMERICA NEBULA"]
    loser.merged_into_id = None

    mock_session = AsyncMock()

    target_result = AsyncMock()
    target_result.scalar_one_or_none = MagicMock(side_effect=[winner, loser])
    mock_session.execute = AsyncMock(return_value=target_result)

    async def override():
        yield mock_session

    app.dependency_overrides[get_session] = override
    app.dependency_overrides[require_admin] = lambda: MagicMock()

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/targets/merge-preview", json={
                "winner_id": str(winner_id),
                "loser_id": str(loser_id),
            })
        assert resp.status_code == 200
        data = resp.json()
        assert data["winner"]["primary_name"] == "NGC 7000 - North America Nebula"
        assert data["loser"]["primary_name"] == "North America Nebula"
        assert isinstance(data["images_to_move"], int)
        assert isinstance(data["aliases_to_add"], list)
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_merge_preview_missing_target_returns_404():
    mock_session = AsyncMock()
    target_result = AsyncMock()
    target_result.scalar_one_or_none = MagicMock(return_value=None)
    mock_session.execute = AsyncMock(return_value=target_result)

    async def override():
        yield mock_session

    app.dependency_overrides[get_session] = override
    app.dependency_overrides[require_admin] = lambda: MagicMock()

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/targets/merge-preview", json={
                "winner_id": str(uuid4()),
                "loser_id": str(uuid4()),
            })
        assert resp.status_code == 404
    finally:
        app.dependency_overrides.clear()
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_api_merge_preview.py -v`
Expected: FAIL (endpoint does not exist yet)

- [ ] **Step 4: Implement the merge-preview endpoint**

In `backend/app/api/merges.py`, add the new endpoint. Place it after the existing `merge_targets` endpoint (after line 145). Import the new schemas at the top of the file.

```python
@router.post("/merge-preview", response_model=MergePreviewResponse)
async def merge_preview(
    body: MergePreviewRequest,
    session: AsyncSession = Depends(get_session),
    _admin=Depends(require_admin),
):
    from app.models.image import Image
    from app.models.mosaic import MosaicPanel

    winner = await session.execute(
        select(Target).where(Target.id == body.winner_id, Target.merged_into_id.is_(None))
    )
    winner = winner.scalar_one_or_none()
    if not winner:
        raise HTTPException(404, "Winner target not found")

    async def _build_side(target):
        img_result = await session.execute(
            select(
                func.count(Image.id),
                func.count(func.distinct(Image.session_date)),
                func.coalesce(func.sum(Image.exposure_time), 0.0),
            ).where(Image.resolved_target_id == target.id)
        )
        row = img_result.one()
        return MergePreviewSide(
            id=target.id,
            primary_name=target.primary_name,
            object_type=target.object_type,
            constellation=target.constellation,
            image_count=row[0],
            session_count=row[1],
            integration_seconds=float(row[2]),
            aliases=target.aliases or [],
        )

    winner_side = await _build_side(winner)

    if body.loser_id:
        loser = await session.execute(
            select(Target).where(Target.id == body.loser_id, Target.merged_into_id.is_(None))
        )
        loser = loser.scalar_one_or_none()
        if not loser:
            raise HTTPException(404, "Loser target not found")

        loser_side = await _build_side(loser)

        images_to_move_result = await session.execute(
            select(func.count(Image.id)).where(Image.resolved_target_id == loser.id)
        )
        images_to_move = images_to_move_result.scalar() or 0

        panels_result = await session.execute(
            select(func.count(MosaicPanel.id)).where(MosaicPanel.target_id == loser.id)
        )
        mosaic_panels_to_move = panels_result.scalar() or 0

        winner_aliases_norm = {a.upper() for a in (winner.aliases or [])}
        winner_aliases_norm.add(winner.primary_name.upper())
        aliases_to_add = [
            a for a in ([loser.primary_name] + (loser.aliases or []))
            if a.upper() not in winner_aliases_norm
        ]

    elif body.loser_name:
        img_result = await session.execute(
            select(
                func.count(Image.id),
            ).where(
                Image.resolved_target_id.is_(None),
                func.upper(Image.raw_headers["OBJECT"].astext) == body.loser_name.upper(),
            )
        )
        images_to_move = img_result.scalar() or 0

        loser_side = MergePreviewSide(
            primary_name=body.loser_name,
            image_count=images_to_move,
        )
        mosaic_panels_to_move = 0
        norm_name = body.loser_name.upper()
        winner_aliases_norm = {a.upper() for a in (winner.aliases or [])}
        aliases_to_add = [body.loser_name] if norm_name not in winner_aliases_norm else []

    else:
        raise HTTPException(400, "Provide either loser_id or loser_name")

    return MergePreviewResponse(
        winner=winner_side,
        loser=loser_side,
        images_to_move=images_to_move,
        mosaic_panels_to_move=mosaic_panels_to_move,
        aliases_to_add=aliases_to_add,
    )
```

Add the necessary imports at the top of `merges.py`: `from sqlalchemy import func` and the new schema classes from `app.schemas.target`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_api_merge_preview.py -v`
Expected: Tests pass (the mock setup may need adjustment depending on how the endpoint queries are structured; the mock should handle multiple `session.execute` calls).

- [ ] **Step 6: Commit**

```bash
git add backend/app/schemas/target.py backend/app/api/merges.py backend/tests/test_api_merge_preview.py
git commit -m "feat: add merge-preview endpoint with side-by-side comparison"
```

---

### Task 3: Backend - Target Identity Endpoint

**Files:**
- Modify: `backend/app/schemas/target.py`
- Modify: `backend/app/api/merges.py`
- Create: `backend/tests/test_api_target_identity.py`

- [ ] **Step 1: Add Pydantic schemas**

In `backend/app/schemas/target.py`, add:

```python
class TargetIdentityRequest(BaseModel):
    primary_name: str | None = None
    object_type: str | None = None
    re_resolve: bool = False

class TargetIdentityResponse(BaseModel):
    id: UUID
    primary_name: str
    catalog_id: str | None
    common_name: str | None
    object_type: str | None
    name_locked: bool
```

- [ ] **Step 2: Write the failing test**

Create `backend/tests/test_api_target_identity.py`:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.database import get_session
from app.api.deps import require_admin


@pytest.mark.asyncio
async def test_rename_target_sets_name_locked():
    target_id = uuid4()
    target = MagicMock()
    target.id = target_id
    target.primary_name = "NGC 7000 - North America Nebula"
    target.catalog_id = "NGC 7000"
    target.common_name = "North America Nebula"
    target.object_type = "HII"
    target.name_locked = False
    target.aliases = ["NGC 7000"]
    target.merged_into_id = None

    mock_session = AsyncMock()
    result_mock = AsyncMock()
    result_mock.scalar_one_or_none = MagicMock(return_value=target)
    mock_session.execute = AsyncMock(return_value=result_mock)
    mock_session.commit = AsyncMock()

    async def override():
        yield mock_session

    app.dependency_overrides[get_session] = override
    app.dependency_overrides[require_admin] = lambda: MagicMock()

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.put(f"/api/targets/{target_id}/identity", json={
                "primary_name": "My Custom Name",
            })
        assert resp.status_code == 200
        assert target.primary_name == "My Custom Name"
        assert target.name_locked is True
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_identity_not_found_returns_404():
    mock_session = AsyncMock()
    result_mock = AsyncMock()
    result_mock.scalar_one_or_none = MagicMock(return_value=None)
    mock_session.execute = AsyncMock(return_value=result_mock)

    async def override():
        yield mock_session

    app.dependency_overrides[get_session] = override
    app.dependency_overrides[require_admin] = lambda: MagicMock()

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.put(f"/api/targets/{uuid4()}/identity", json={
                "primary_name": "Whatever",
            })
        assert resp.status_code == 404
    finally:
        app.dependency_overrides.clear()
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_api_target_identity.py -v`
Expected: FAIL (endpoint does not exist)

- [ ] **Step 4: Implement the identity endpoint**

In `backend/app/api/merges.py`, add:

```python
@router.put("/{target_id}/identity", response_model=TargetIdentityResponse)
async def update_target_identity(
    target_id: UUID,
    body: TargetIdentityRequest,
    session: AsyncSession = Depends(get_session),
    _admin=Depends(require_admin),
):
    result = await session.execute(
        select(Target).where(Target.id == target_id, Target.merged_into_id.is_(None))
    )
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(404, "Target not found")

    if body.re_resolve:
        from app.services.simbad import (
            resolve_target_name_cached,
            curate_simbad_result,
            normalize_object_name,
        )
        from app.models.simbad_cache import SimbadCache

        for alias in (target.aliases or [target.primary_name]):
            norm = normalize_object_name(alias)
            await session.execute(
                sa_delete(SimbadCache).where(
                    SimbadCache.query_name == norm,
                    SimbadCache.main_id.is_(None),
                )
            )
        await session.flush()

        lookup_name = target.catalog_id or target.primary_name
        cached = resolve_target_name_cached(lookup_name, session)
        if cached:
            curated = curate_simbad_result(cached, fits_names=target.aliases or [])
            target.catalog_id = curated.get("catalog_id")
            target.common_name = curated.get("common_name")
            target.primary_name = curated.get("primary_name", target.primary_name)
            target.object_type = curated.get("object_type")
        target.name_locked = False

    else:
        if body.primary_name is not None:
            target.primary_name = body.primary_name
            target.name_locked = True

        if body.object_type is not None:
            category_to_simbad = {
                "Emission Nebula": "HII",
                "Reflection Nebula": "RNe",
                "Dark Nebula": "DNe",
                "Planetary Nebula": "PN",
                "Supernova Remnant": "SNR",
                "Galaxy": "G",
                "Open Cluster": "OpC",
                "Globular Cluster": "GlC",
                "Star": "*",
                "Other": "Other",
            }
            target.object_type = category_to_simbad.get(body.object_type, body.object_type)

    await session.commit()
    await session.refresh(target)

    return TargetIdentityResponse(
        id=target.id,
        primary_name=target.primary_name,
        catalog_id=target.catalog_id,
        common_name=target.common_name,
        object_type=target.object_type,
        name_locked=target.name_locked,
    )
```

Add `from sqlalchemy import delete as sa_delete` to the imports at the top of `merges.py`. Add the new schema imports.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_api_target_identity.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/schemas/target.py backend/app/api/merges.py backend/tests/test_api_target_identity.py
git commit -m "feat: add target identity endpoint for rename and re-resolve"
```

---

### Task 4: Backend - Smart Rebuild `name_locked` Guard

**Files:**
- Modify: `backend/app/worker/tasks.py:1304-1371`

- [ ] **Step 1: Guard Phase 4 (re-derive from SIMBAD cache)**

In `backend/app/worker/tasks.py`, in `_smart_rebuild_inner`, Phase 4 iterates all active targets (around line 1309-1311). Add a `name_locked` check to the target loop. Find the line that loads targets (approximately `select(Target).where(Target.merged_into_id.is_(None))`) and add a filter:

After the existing check that skips targets where both `catalog_id` and `common_name` are None (the guard added in commit 8e9b66b), add:

```python
        if target.name_locked:
            continue
```

This goes inside the `for target in targets:` loop, before the SIMBAD cache lookup.

- [ ] **Step 2: Guard Phase 5 (rebuild primary_name SQL)**

Phase 5 is a bulk SQL UPDATE around lines 1347-1371. The existing WHERE clause filters to `catalog_id IS NOT NULL OR common_name IS NOT NULL`. Add an additional condition:

Change the WHERE clause from:
```python
.where(
    Target.merged_into_id.is_(None),
    sa.or_(Target.catalog_id.isnot(None), Target.common_name.isnot(None)),
)
```

To:
```python
.where(
    Target.merged_into_id.is_(None),
    Target.name_locked.is_(False),
    sa.or_(Target.catalog_id.isnot(None), Target.common_name.isnot(None)),
)
```

- [ ] **Step 3: Verify existing tests still pass**

Run: `cd backend && python -m pytest tests/ -v --timeout=30`
Expected: All existing tests pass.

- [ ] **Step 4: Commit**

```bash
git add backend/app/worker/tasks.py
git commit -m "feat: smart rebuild skips name_locked targets in phases 4-5"
```

---

### Task 5: Backend - Duplicate Detection `reason_text`

**Files:**
- Modify: `backend/app/worker/tasks.py:725-972`

- [ ] **Step 1: Populate reason_text in Pass 1 SIMBAD matches**

In `detect_duplicate_targets`, around lines 799-805 where `MergeCandidate` is created with `method="simbad"`, add the `reason_text` field:

```python
MergeCandidate(
    source_name=obj_name,
    source_image_count=img_count,
    suggested_target_id=existing_target.id,
    similarity_score=1.0,
    method="simbad",
    reason_text=f"SIMBAD resolves \"{obj_name}\" to the same object as \"{existing_target.primary_name}\"",
)
```

- [ ] **Step 2: Populate reason_text in Pass 1 trigram matches**

Around lines 853-859 where trigram `MergeCandidate` is created:

```python
MergeCandidate(
    source_name=obj_name,
    source_image_count=img_count,
    suggested_target_id=best_match.id,
    similarity_score=float(score),
    method="trigram",
    reason_text=f"Name is {int(float(score) * 100)}% similar to \"{best_match.primary_name}\"",
)
```

- [ ] **Step 3: Populate reason_text in Pass 1 orphan candidates**

Around lines 862-870 where orphan `MergeCandidate` is created:

```python
MergeCandidate(
    source_name=obj_name,
    source_image_count=img_count,
    suggested_target_id=None,
    similarity_score=0.0,
    method="orphan",
    reason_text=f"No match found in SIMBAD or existing targets",
)
```

- [ ] **Step 4: Populate reason_text in Pass 2 duplicate detection**

Around lines 958-966 where duplicate `MergeCandidate` is created, the code has access to the shared normalized name(s). Add:

```python
MergeCandidate(
    source_name=non_winner.primary_name,
    source_image_count=...,
    suggested_target_id=winner.id,
    similarity_score=1.0,
    method="duplicate",
    reason_text=f"Shares alias \"{shared_name}\" with \"{winner.primary_name}\"",
)
```

The exact variable name for the shared alias depends on the loop structure. The union-find groups targets by shared normalized names, so capture the representative shared name from the group key when constructing the candidate.

- [ ] **Step 5: Commit**

```bash
git add backend/app/worker/tasks.py
git commit -m "feat: populate reason_text on merge candidates for human-readable explanations"
```

---

### Task 6: Backend - Scan Summary

**Files:**
- Modify: `backend/app/api/scan.py`
- Modify: `backend/app/services/scan_state.py:204-291`
- Modify: `backend/app/worker/tasks.py` (detect_duplicate_targets return)
- Create: `backend/tests/test_api_scan_summary.py`

- [ ] **Step 1: Write scan summary to Redis after post-scan chain**

The post-scan chain ends when `detect_duplicate_targets` completes (it is the last task in the chain: scan -> smart_rebuild -> detect_duplicates). In `scan_state.py`, the `check_complete_sync` function at line 204 already has access to the scan stats (files ingested, failed, etc.).

Modify `check_complete_sync` in `scan_state.py` to write the initial summary after scan completes. After the existing activity log entry (around line 228-280), add:

```python
    import json
    summary = {
        "completed_at": datetime.utcnow().isoformat() + "Z",
        "files_ingested": snapshot.get("completed", 0),
        "targets_created": 0,
        "targets_updated": 0,
        "duplicates_found": 0,
        "unresolved_names": 0,
        "errors": snapshot.get("failed", 0),
    }
    r.set("galactilog:scan_summary", json.dumps(summary))
```

The `targets_created`, `targets_updated`, `duplicates_found`, and `unresolved_names` fields start at 0 and get updated by `_smart_rebuild_inner` and `detect_duplicate_targets` as they run after the scan. 

In `_smart_rebuild_inner` (tasks.py), after the stats are computed, update the Redis summary:

```python
    import json
    raw = _redis.get("galactilog:scan_summary")
    if raw:
        summary = json.loads(raw)
        summary["targets_updated"] = stats.get("aliases_added", 0)
        _redis.set("galactilog:scan_summary", json.dumps(summary))
```

In `detect_duplicate_targets` (tasks.py), at the end before the return, update the summary:

```python
    import json
    raw = _redis.get("galactilog:scan_summary")
    if raw:
        summary = json.loads(raw)
        summary["duplicates_found"] = candidates_found
        summary["unresolved_names"] = orphan_count
        _redis.set("galactilog:scan_summary", json.dumps(summary))
```

Where `orphan_count` is tracked by counting orphan candidates created during Pass 1.

- [ ] **Step 2: Write the failing test for the scan summary endpoint**

Create `backend/tests/test_api_scan_summary.py`:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient, ASGITransport
import json

from app.main import app
from app.database import get_session
from app.api.deps import get_current_user


@pytest.mark.asyncio
async def test_scan_summary_returns_data():
    summary = {
        "completed_at": "2026-04-20T03:42:00Z",
        "files_ingested": 12,
        "targets_created": 3,
        "targets_updated": 1,
        "duplicates_found": 2,
        "unresolved_names": 1,
        "errors": 0,
    }

    mock_session = AsyncMock()

    async def override():
        yield mock_session

    app.dependency_overrides[get_session] = override
    app.dependency_overrides[get_current_user] = lambda: MagicMock()

    with patch("app.api.scan.sync_redis") as mock_redis_mod:
        mock_r = MagicMock()
        mock_r.get.return_value = json.dumps(summary)
        mock_redis_mod.from_url.return_value = mock_r

        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.get("/api/scan/summary")
            assert resp.status_code == 200
            assert resp.json()["files_ingested"] == 12
        finally:
            app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_scan_summary_returns_null_when_no_data():
    mock_session = AsyncMock()

    async def override():
        yield mock_session

    app.dependency_overrides[get_session] = override
    app.dependency_overrides[get_current_user] = lambda: MagicMock()

    with patch("app.api.scan.sync_redis") as mock_redis_mod:
        mock_r = MagicMock()
        mock_r.get.return_value = None
        mock_redis_mod.from_url.return_value = mock_r

        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.get("/api/scan/summary")
            assert resp.status_code == 200
            assert resp.json() is None
        finally:
            app.dependency_overrides.clear()
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_api_scan_summary.py -v`
Expected: FAIL

- [ ] **Step 4: Add the scan summary endpoint**

In `backend/app/api/scan.py`, add:

```python
@router.get("/summary")
async def get_scan_summary(
    _user=Depends(get_current_user),
):
    import json
    r = sync_redis.from_url(settings.redis_url)
    raw = r.get("galactilog:scan_summary")
    r.close()
    if raw:
        return json.loads(raw)
    return None
```

Place it near the other scan status endpoints. Ensure `sync_redis` is imported (check if it's already used in this file, otherwise add `import redis as sync_redis`).

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_api_scan_summary.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/scan.py backend/app/services/scan_state.py backend/app/worker/tasks.py backend/tests/test_api_scan_summary.py
git commit -m "feat: add post-scan summary to Redis and GET /scan/summary endpoint"
```

---

### Task 7: Backend - Remove Dead Endpoints

**Files:**
- Modify: `backend/app/api/scan.py:167-214, 351-363`
- Modify: `backend/app/worker/tasks.py` (run_xmatch_enrichment task)

- [ ] **Step 1: Remove backfill-targets endpoint**

In `backend/app/api/scan.py`, delete the `backfill_targets` endpoint (lines 167-214, the function decorated with `@router.post("/backfill-targets")`).

- [ ] **Step 2: Remove xmatch-enrichment endpoint**

In `backend/app/api/scan.py`, delete the `trigger_xmatch_enrichment` endpoint (lines 351-363, the function decorated with `@router.post("/xmatch-enrichment")`).

- [ ] **Step 3: Remove xmatch Celery task**

In `backend/app/worker/tasks.py`, delete the `run_xmatch_enrichment` task function (around lines 1876-1926).

- [ ] **Step 4: Run existing tests to verify nothing breaks**

Run: `cd backend && python -m pytest tests/ -v --timeout=30`
Expected: All tests pass (no existing tests for these endpoints).

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/scan.py backend/app/worker/tasks.py
git commit -m "feat: remove unused backfill-targets and xmatch-enrichment endpoints"
```

---

### Task 8: Backend - Update MergeCandidate Schema

**Files:**
- Modify: `backend/app/schemas/target.py:295-304`

- [ ] **Step 1: Add reason_text to the response schema**

In `backend/app/schemas/target.py`, find `MergeCandidateResponse` (line 295) and add the `reason_text` field:

```python
class MergeCandidateResponse(BaseModel):
    id: UUID
    source_name: str
    source_image_count: int
    suggested_target_id: UUID | None
    suggested_target_name: str | None = None
    similarity_score: float
    method: str
    status: str
    created_at: datetime | None
    reason_text: str | None = None
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/schemas/target.py
git commit -m "feat: add reason_text to MergeCandidateResponse schema"
```

---

### Task 9: Frontend - API Client Updates

**Files:**
- Modify: `frontend/src/api/client.ts`

- [ ] **Step 1: Add new API methods**

In `frontend/src/api/client.ts`, add the following methods to the API client object. Place them near the existing merge methods (around line 476):

```typescript
  async mergePreview(winnerId: string, loserId?: string, loserName?: string) {
    const resp = await this.fetch("/targets/merge-preview", {
      method: "POST",
      body: JSON.stringify({
        winner_id: winnerId,
        ...(loserId ? { loser_id: loserId } : {}),
        ...(loserName ? { loser_name: loserName } : {}),
      }),
    });
    return resp.json();
  },

  async updateTargetIdentity(targetId: string, body: {
    primary_name?: string;
    object_type?: string;
    re_resolve?: boolean;
  }) {
    const resp = await this.fetch(`/targets/${targetId}/identity`, {
      method: "PUT",
      body: JSON.stringify(body),
    });
    return resp.json();
  },

  async getScanSummary() {
    const resp = await this.fetch("/scan/summary");
    return resp.json();
  },
```

- [ ] **Step 2: Remove dead API methods**

Remove `triggerXmatchEnrichment` (line 794) from the client. The backfill-targets method can also be removed if it exists (search for `backfill` in the file).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/client.ts
git commit -m "feat: add merge-preview, identity, scan-summary API methods; remove xmatch"
```

---

### Task 10: Frontend - IssueCard Component

**Files:**
- Create: `frontend/src/components/settings/IssueCard.tsx`

- [ ] **Step 1: Create the IssueCard component**

This component renders a single issue card in the Target Health list. It handles all three issue types: duplicate, unresolved, and recent merge.

```tsx
import { Component, Show } from "solid-js";
import { useAuth } from "../../store/auth";

export interface IssueCardProps {
  candidate: {
    id: string;
    source_name: string;
    source_image_count: number;
    suggested_target_id: string | null;
    suggested_target_name: string | null;
    similarity_score: number;
    method: string;
    status: string;
    reason_text: string | null;
    created_at: string | null;
  };
  onPreviewMerge: (candidate: IssueCardProps["candidate"]) => void;
  onDismiss: (candidateId: string) => void;
  onRevert?: (candidateId: string) => void;
  onRetry?: (candidateId: string) => void;
  onCreateTarget?: (candidate: IssueCardProps["candidate"]) => void;
}

export const IssueCard: Component<IssueCardProps> = (props) => {
  const auth = useAuth();
  const c = () => props.candidate;

  const issueType = () => {
    if (c().status === "accepted") return "merge";
    if (c().method === "orphan") return "unresolved";
    return "duplicate";
  };

  const explanation = () => {
    if (c().reason_text) return c().reason_text;
    switch (c().method) {
      case "simbad": return `SIMBAD resolves both names to the same object`;
      case "trigram": return `Names are ${Math.round(c().similarity_score * 100)}% similar`;
      case "duplicate": return `These targets share an alias`;
      case "orphan": return `No match found in SIMBAD or existing targets`;
      default: return c().method;
    }
  };

  const typeLabel = () => {
    switch (issueType()) {
      case "duplicate": return "Potential Duplicate";
      case "unresolved": return "Unresolved FITS Name";
      case "merge": return `Merged ${c().created_at ? new Date(c().created_at!).toLocaleDateString() : ""}`;
    }
  };

  const typeColor = () => {
    switch (issueType()) {
      case "duplicate": return "text-amber-400";
      case "unresolved": return "text-blue-400";
      case "merge": return "text-theme-tertiary";
    }
  };

  return (
    <div class={`rounded-lg border p-4 space-y-2 ${
      issueType() === "merge" ? "border-theme-border bg-theme-base opacity-70" : "border-theme-border-em bg-theme-elevated"
    }`}>
      <div class="flex items-center justify-between">
        <span class={`text-sm font-medium ${typeColor()}`}>{typeLabel()}</span>
        <span class="text-xs text-theme-tertiary">{c().source_image_count} image{c().source_image_count !== 1 ? "s" : ""}</span>
      </div>

      <div class="text-sm">
        <Show when={issueType() === "duplicate"}>
          <span class="text-theme-primary font-medium">"{c().source_name}"</span>
          <Show when={c().suggested_target_name}>
            <span class="text-theme-tertiary"> and </span>
            <span class="text-theme-primary font-medium">"{c().suggested_target_name}"</span>
          </Show>
        </Show>
        <Show when={issueType() === "unresolved"}>
          <span class="text-theme-primary font-medium">"{c().source_name}"</span>
          <span class="text-theme-tertiary"> found in {c().source_image_count} LIGHT frame{c().source_image_count !== 1 ? "s" : ""}.</span>
          <Show when={c().suggested_target_name}>
            <span class="text-theme-tertiary"> Similar to: </span>
            <span class="text-theme-primary">{c().suggested_target_name} ({Math.round(c().similarity_score * 100)}%)</span>
          </Show>
        </Show>
        <Show when={issueType() === "merge"}>
          <span class="text-theme-primary">"{c().source_name}"</span>
          <span class="text-theme-tertiary"> merged into </span>
          <span class="text-theme-primary">"{c().suggested_target_name}"</span>
        </Show>
      </div>

      <p class="text-xs text-theme-tertiary">{explanation()}</p>

      <Show when={auth.isAdmin()}>
        <div class="flex gap-2 pt-1">
          <Show when={issueType() === "duplicate"}>
            <button
              class="text-xs px-3 py-1 rounded bg-theme-accent text-white hover:bg-theme-accent/80"
              onClick={() => props.onPreviewMerge(c())}
            >Preview Merge</button>
            <button
              class="text-xs px-3 py-1 rounded border border-theme-border text-theme-secondary hover:bg-theme-hover"
              onClick={() => props.onDismiss(c().id)}
            >Not a Duplicate</button>
          </Show>
          <Show when={issueType() === "unresolved"}>
            <Show when={c().suggested_target_id}>
              <button
                class="text-xs px-3 py-1 rounded bg-theme-accent text-white hover:bg-theme-accent/80"
                onClick={() => props.onPreviewMerge(c())}
              >Assign to {c().suggested_target_name}</button>
            </Show>
            <Show when={props.onCreateTarget}>
              <button
                class="text-xs px-3 py-1 rounded border border-theme-border text-theme-secondary hover:bg-theme-hover"
                onClick={() => props.onCreateTarget!(c())}
              >Create New Target</button>
            </Show>
            <button
              class="text-xs px-3 py-1 rounded border border-theme-border text-theme-secondary hover:bg-theme-hover"
              onClick={() => props.onDismiss(c().id)}
            >Dismiss</button>
          </Show>
          <Show when={issueType() === "merge" && props.onRevert}>
            <button
              class="text-xs px-3 py-1 rounded border border-theme-border text-theme-secondary hover:bg-theme-hover"
              onClick={() => props.onRevert!(c().id)}
            >Undo Merge</button>
          </Show>
        </div>
      </Show>
    </div>
  );
};
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/settings/IssueCard.tsx
git commit -m "feat: add IssueCard component for target health issue display"
```

---

### Task 11: Frontend - MergePreviewModal

**Files:**
- Create: `frontend/src/components/MergePreviewModal.tsx`

- [ ] **Step 1: Create the MergePreviewModal component**

This replaces `MergeTargetModal.tsx`. It shows a side-by-side comparison and a "what will happen" summary before executing the merge.

```tsx
import { Component, Show, createSignal, createResource } from "solid-js";
import { api } from "../api/client";

interface MergePreviewModalProps {
  winnerId?: string;
  loserId?: string;
  loserName?: string;
  onClose: () => void;
  onMerged: () => void;
}

export const MergePreviewModal: Component<MergePreviewModalProps> = (props) => {
  const [swapped, setSwapped] = createSignal(false);
  const [merging, setMerging] = createSignal(false);

  const effectiveWinnerId = () => swapped() ? props.loserId : props.winnerId;
  const effectiveLoserId = () => swapped() ? props.winnerId : props.loserId;

  const [preview] = createResource(
    () => ({ w: effectiveWinnerId(), l: effectiveLoserId(), ln: props.loserName }),
    async ({ w, l, ln }) => {
      if (!w) return null;
      return api.mergePreview(w, l, ln);
    }
  );

  const canSwap = () => !!props.loserId;

  const handleMerge = async () => {
    setMerging(true);
    try {
      await api.mergeTargets(
        effectiveWinnerId()!,
        effectiveLoserId(),
        props.loserName,
      );
      props.onMerged();
    } catch (e) {
      console.error("Merge failed:", e);
    } finally {
      setMerging(false);
    }
  };

  const formatTime = (seconds: number) => {
    const hours = seconds / 3600;
    return hours < 1 ? `${Math.round(seconds / 60)} min` : `${hours.toFixed(1)} hr`;
  };

  return (
    <div class="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={(e) => { if (e.target === e.currentTarget) props.onClose(); }}>
      <div class="bg-theme-elevated border border-theme-border rounded-lg shadow-xl w-full max-w-2xl mx-4 max-h-[90vh] overflow-y-auto">
        <div class="p-4 border-b border-theme-border flex items-center justify-between">
          <h2 class="text-lg font-semibold text-theme-primary">Merge Preview</h2>
          <button onClick={props.onClose} class="text-theme-tertiary hover:text-theme-primary text-xl">&times;</button>
        </div>

        <Show when={preview.loading}>
          <div class="p-8 text-center text-theme-tertiary">Loading preview...</div>
        </Show>

        <Show when={preview()}>
          {(data) => (
            <>
              <div class="grid grid-cols-2 gap-4 p-4">
                {/* Winner side */}
                <div class="rounded-lg border border-theme-border p-3 space-y-2">
                  <div class="flex items-center gap-2">
                    <input
                      type="radio"
                      name="winner"
                      checked={!swapped()}
                      onChange={() => setSwapped(false)}
                      disabled={!canSwap()}
                      class="accent-theme-accent"
                    />
                    <span class="text-xs text-theme-tertiary">Keep as primary</span>
                  </div>
                  <h3 class="font-medium text-theme-primary">{data().winner.primary_name}</h3>
                  <Show when={data().winner.object_type}>
                    <p class="text-xs text-theme-secondary">{data().winner.object_type} {data().winner.constellation ? `\u00b7 ${data().winner.constellation}` : ""}</p>
                  </Show>
                  <p class="text-xs text-theme-tertiary">{data().winner.image_count} images \u00b7 {data().winner.session_count} sessions</p>
                  <p class="text-xs text-theme-tertiary">{formatTime(data().winner.integration_seconds)} integration</p>
                  <Show when={data().winner.aliases?.length}>
                    <div class="text-xs text-theme-tertiary">
                      <span class="font-medium">Aliases: </span>{data().winner.aliases.join(", ")}
                    </div>
                  </Show>
                </div>

                {/* Loser side */}
                <div class="rounded-lg border border-theme-border p-3 space-y-2">
                  <Show when={canSwap()}>
                    <div class="flex items-center gap-2">
                      <input
                        type="radio"
                        name="winner"
                        checked={swapped()}
                        onChange={() => setSwapped(true)}
                        class="accent-theme-accent"
                      />
                      <span class="text-xs text-theme-tertiary">Keep as primary</span>
                    </div>
                  </Show>
                  <h3 class="font-medium text-theme-primary">{data().loser.primary_name}</h3>
                  <Show when={data().loser.object_type}>
                    <p class="text-xs text-theme-secondary">{data().loser.object_type} {data().loser.constellation ? `\u00b7 ${data().loser.constellation}` : ""}</p>
                  </Show>
                  <p class="text-xs text-theme-tertiary">{data().loser.image_count} images {data().loser.session_count ? `\u00b7 ${data().loser.session_count} sessions` : ""}</p>
                  <Show when={data().loser.integration_seconds}>
                    <p class="text-xs text-theme-tertiary">{formatTime(data().loser.integration_seconds)} integration</p>
                  </Show>
                  <Show when={data().loser.aliases?.length}>
                    <div class="text-xs text-theme-tertiary">
                      <span class="font-medium">Aliases: </span>{data().loser.aliases.join(", ")}
                    </div>
                  </Show>
                </div>
              </div>

              {/* What will happen */}
              <div class="px-4 pb-4">
                <div class="rounded-lg bg-theme-base border border-theme-border p-3 space-y-1">
                  <h4 class="text-sm font-medium text-theme-secondary">What will happen:</h4>
                  <ul class="text-xs text-theme-tertiary space-y-0.5 list-disc list-inside">
                    <li>{data().images_to_move} image{data().images_to_move !== 1 ? "s" : ""} from "{data().loser.primary_name}" move to "{data().winner.primary_name}"</li>
                    <Show when={data().aliases_to_add?.length}>
                      <li>Alias{data().aliases_to_add.length !== 1 ? "es" : ""} "{data().aliases_to_add.join('", "')}" added to winner</li>
                    </Show>
                    <Show when={data().mosaic_panels_to_move > 0}>
                      <li>{data().mosaic_panels_to_move} mosaic panel{data().mosaic_panels_to_move !== 1 ? "s" : ""} reassigned</li>
                    </Show>
                    <li>"{data().loser.primary_name}" will be soft-deleted</li>
                  </ul>
                </div>
              </div>

              {/* Actions */}
              <div class="p-4 border-t border-theme-border flex justify-end gap-2">
                <button
                  onClick={props.onClose}
                  class="px-4 py-2 text-sm rounded border border-theme-border text-theme-secondary hover:bg-theme-hover"
                >Cancel</button>
                <button
                  onClick={handleMerge}
                  disabled={merging()}
                  class="px-4 py-2 text-sm rounded bg-theme-accent text-white hover:bg-theme-accent/80 disabled:opacity-50"
                >{merging() ? "Merging..." : "Merge"}</button>
              </div>
            </>
          )}
        </Show>
      </div>
    </div>
  );
};
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/MergePreviewModal.tsx
git commit -m "feat: add MergePreviewModal with side-by-side comparison"
```

---

### Task 12: Frontend - TargetHealthTab

**Files:**
- Create: `frontend/src/components/settings/TargetHealthTab.tsx`

- [ ] **Step 1: Create the TargetHealthTab component**

This replaces `MergesTab.tsx`. It renders the post-scan summary banner, filter pills, issue list, and Advanced section.

```tsx
import { Component, Show, For, createSignal, createResource, onMount } from "solid-js";
import { api } from "../../api/client";
import { useAuth } from "../../store/auth";
import { IssueCard } from "./IssueCard";
import { MergePreviewModal } from "../MergePreviewModal";
import { ResolveTargetModal } from "./ResolveTargetModal";
import { emitWithToast } from "../../util/toast";

type FilterType = "all" | "duplicates" | "unresolved" | "merges";

export const TargetHealthTab: Component = () => {
  const auth = useAuth();
  const [filter, setFilter] = createSignal<FilterType>("all");
  const [showAdvanced, setShowAdvanced] = createSignal(false);
  const [mergePreview, setMergePreview] = createSignal<{ winnerId?: string; loserId?: string; loserName?: string } | null>(null);
  const [resolveCandidate, setResolveCandidate] = createSignal<any>(null);

  const [summary] = createResource(() => api.getScanSummary());

  const [pendingCandidates, { refetch: refetchPending }] = createResource(() => api.getMergeCandidates("pending"));
  const [acceptedCandidates, { refetch: refetchAccepted }] = createResource(() => api.getMergeCandidates("accepted"));

  const refresh = () => {
    refetchPending();
    refetchAccepted();
  };

  const duplicates = () => (pendingCandidates() || []).filter((c: any) => c.method !== "orphan");
  const unresolved = () => (pendingCandidates() || []).filter((c: any) => c.method === "orphan");
  const merges = () => acceptedCandidates() || [];

  const filtered = () => {
    switch (filter()) {
      case "duplicates": return duplicates();
      case "unresolved": return unresolved();
      case "merges": return merges();
      default: return [...duplicates(), ...unresolved(), ...merges()];
    }
  };

  const handlePreviewMerge = (candidate: any) => {
    if (candidate.suggested_target_id) {
      if (candidate.method === "orphan" || !candidate.suggested_target_id) {
        setMergePreview({ winnerId: candidate.suggested_target_id, loserName: candidate.source_name });
      } else if (candidate.status === "pending") {
        setMergePreview({ winnerId: candidate.suggested_target_id, loserName: candidate.source_name });
      }
    }
  };

  const handleDismiss = async (candidateId: string) => {
    await api.dismissMergeCandidate(candidateId);
    refresh();
  };

  const handleRevert = async (candidateId: string) => {
    await api.revertMergeCandidate(candidateId);
    refresh();
  };

  const handleRetryAll = async () => {
    await emitWithToast(
      () => api.retryUnresolved(),
      { pending: "Retrying failed lookups...", success: "Lookups complete", error: "Retry failed" },
      "enrichment",
      600_000,
    );
    refresh();
  };

  const handleRepairLinks = async () => {
    await emitWithToast(
      () => api.smartRebuildTargets(),
      { pending: "Repairing target links...", success: "Repair complete", error: "Repair failed" },
      "rebuild",
      600_000,
    );
    refresh();
  };

  const handleFullRebuild = async () => {
    if (!confirm("This will delete all targets and re-resolve from scratch. This takes several minutes for large libraries. Continue?")) return;
    await emitWithToast(
      () => api.rebuildTargets(),
      { pending: "Rebuilding all targets...", success: "Rebuild complete", error: "Rebuild failed" },
      "rebuild",
      3_600_000,
    );
    refresh();
  };

  return (
    <div class="space-y-4">
      {/* Post-scan summary banner */}
      <Show when={summary() && !summary.loading}>
        <div class="rounded-lg border border-theme-border bg-theme-base p-3">
          <div class="text-sm text-theme-secondary space-x-3">
            <span class="font-medium">Last scan:</span>
            <Show when={summary().files_ingested > 0}>
              <span>{summary().files_ingested} files ingested</span>
            </Show>
            <Show when={summary().targets_created > 0}>
              <span class="text-green-400">{summary().targets_created} new targets</span>
            </Show>
            <Show when={summary().duplicates_found > 0}>
              <button onClick={() => setFilter("duplicates")} class="text-amber-400 hover:underline cursor-pointer">
                {summary().duplicates_found} potential duplicate{summary().duplicates_found !== 1 ? "s" : ""}
              </button>
            </Show>
            <Show when={summary().unresolved_names > 0}>
              <button onClick={() => setFilter("unresolved")} class="text-blue-400 hover:underline cursor-pointer">
                {summary().unresolved_names} unresolved
              </button>
            </Show>
            <Show when={summary().errors > 0}>
              <span class="text-red-400">{summary().errors} error{summary().errors !== 1 ? "s" : ""}</span>
            </Show>
          </div>
        </div>
      </Show>

      {/* Retry banner for unresolved */}
      <Show when={unresolved().length > 0 && auth.isAdmin()}>
        <div class="rounded-lg border border-blue-500/30 bg-blue-500/10 p-3 flex items-center justify-between">
          <span class="text-sm text-blue-300">{unresolved().length} file{unresolved().length !== 1 ? "s" : ""} couldn't be identified.</span>
          <button
            onClick={handleRetryAll}
            class="text-xs px-3 py-1 rounded bg-blue-600 text-white hover:bg-blue-500"
          >Retry Failed Lookups</button>
        </div>
      </Show>

      {/* Filter pills */}
      <div class="flex gap-2">
        <For each={[
          { key: "all" as FilterType, label: "All Issues", count: duplicates().length + unresolved().length + merges().length },
          { key: "duplicates" as FilterType, label: "Duplicates", count: duplicates().length },
          { key: "unresolved" as FilterType, label: "Unresolved", count: unresolved().length },
          { key: "merges" as FilterType, label: "Recent Merges", count: merges().length },
        ]}>
          {(pill) => (
            <button
              onClick={() => setFilter(pill.key)}
              class={`text-xs px-3 py-1.5 rounded-full border transition ${
                filter() === pill.key
                  ? "border-theme-accent bg-theme-accent/10 text-theme-accent"
                  : "border-theme-border text-theme-secondary hover:bg-theme-hover"
              }`}
            >
              {pill.label}
              <Show when={pill.count > 0}>
                <span class="ml-1.5 px-1.5 py-0.5 rounded-full bg-theme-base text-[10px]">{pill.count}</span>
              </Show>
            </button>
          )}
        </For>
      </div>

      {/* Issue list */}
      <div class="space-y-2">
        <Show when={filtered().length === 0}>
          <div class="text-center text-theme-tertiary py-8 text-sm">No issues found.</div>
        </Show>
        <For each={filtered()}>
          {(candidate) => (
            <IssueCard
              candidate={candidate}
              onPreviewMerge={handlePreviewMerge}
              onDismiss={handleDismiss}
              onRevert={handleRevert}
              onCreateTarget={(c) => setResolveCandidate(c)}
            />
          )}
        </For>
      </div>

      {/* Advanced maintenance */}
      <Show when={auth.isAdmin()}>
        <div class="border-t border-theme-border pt-4 mt-6">
          <button
            onClick={() => setShowAdvanced(!showAdvanced())}
            class="text-sm text-theme-tertiary hover:text-theme-secondary flex items-center gap-1"
          >
            <span class={`transition-transform ${showAdvanced() ? "rotate-90" : ""}`}>&#9654;</span>
            Advanced Maintenance
          </button>
          <Show when={showAdvanced()}>
            <div class="mt-3 rounded-lg border border-theme-border bg-theme-base p-4 space-y-4">
              <p class="text-xs text-theme-tertiary">These operations run automatically after each scan. Use them only if you need to force a manual run.</p>

              <div class="space-y-3">
                <div class="flex items-start justify-between">
                  <div>
                    <p class="text-sm text-theme-primary font-medium">Repair Target Links</p>
                    <p class="text-xs text-theme-tertiary">Repairs image-to-target links and re-derives target names using cached data.</p>
                  </div>
                  <button onClick={handleRepairLinks} class="text-xs px-3 py-1.5 rounded border border-theme-border text-theme-secondary hover:bg-theme-hover shrink-0">Run</button>
                </div>

                <div class="flex items-start justify-between">
                  <div>
                    <p class="text-sm text-theme-primary font-medium">Retry Failed Lookups</p>
                    <p class="text-xs text-theme-tertiary">Clears failed SIMBAD caches and retries all unresolved names. Use after an extended offline period.</p>
                  </div>
                  <button onClick={handleRetryAll} class="text-xs px-3 py-1.5 rounded border border-theme-border text-theme-secondary hover:bg-theme-hover shrink-0">Run</button>
                </div>

                <div class="flex items-start justify-between">
                  <div>
                    <p class="text-sm text-red-400 font-medium">Full Rebuild</p>
                    <p class="text-xs text-theme-tertiary">Deletes all targets and re-resolves from scratch via SIMBAD. Use only if target data is badly corrupted.</p>
                  </div>
                  <button onClick={handleFullRebuild} class="text-xs px-3 py-1.5 rounded border border-red-500/50 text-red-400 hover:bg-red-500/10 shrink-0">Run</button>
                </div>
              </div>
            </div>
          </Show>
        </div>
      </Show>

      {/* Modals */}
      <Show when={mergePreview()}>
        <MergePreviewModal
          winnerId={mergePreview()!.winnerId}
          loserId={mergePreview()!.loserId}
          loserName={mergePreview()!.loserName}
          onClose={() => setMergePreview(null)}
          onMerged={() => { setMergePreview(null); refresh(); }}
        />
      </Show>

      <Show when={resolveCandidate()}>
        <ResolveTargetModal
          candidate={resolveCandidate()}
          onClose={() => setResolveCandidate(null)}
          onResolved={() => { setResolveCandidate(null); refresh(); }}
        />
      </Show>
    </div>
  );
};
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/settings/TargetHealthTab.tsx
git commit -m "feat: add TargetHealthTab replacing MergesTab"
```

---

### Task 13: Frontend - Wire Up SettingsPage

**Files:**
- Modify: `frontend/src/pages/SettingsPage.tsx:33-60, 141-143`

- [ ] **Step 1: Update the lazy import**

In `SettingsPage.tsx`, find the MergesTab lazy import (line 33) and change it:

```typescript
// Before:
const MergesTab = lazy(() => import("../components/settings/MergesTab").then(m => ({ default: m.MergesTab })));

// After:
const TargetHealthTab = lazy(() => import("../components/settings/TargetHealthTab").then(m => ({ default: m.TargetHealthTab })));
```

- [ ] **Step 2: Update the ALL_TABS array**

Find the `ALL_TABS` array (line 43-54). Change the `targets` entry label from `"Target Management"` to `"Target Health"`.

- [ ] **Step 3: Update the tab render**

Find where the "targets" tab renders `<TargetManagementTab />` or `<MergesTab />` (around lines 58-60, 141-143). Replace with `<TargetHealthTab />`.

- [ ] **Step 4: Verify the page loads in the browser**

Start the dev server: `cd frontend && npm run dev`
Navigate to `http://localhost:3000/settings?tab=targets`
Expected: The "Target Health" tab loads with the new layout. If no pending candidates exist, it shows "No issues found."

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/SettingsPage.tsx
git commit -m "feat: wire TargetHealthTab into Settings page, rename tab to Target Health"
```

---

### Task 14: Frontend - Inline Rename on TargetDetailPage

**Files:**
- Modify: `frontend/src/pages/TargetDetailPage.tsx:222-297, 357-377`

- [ ] **Step 1: Add rename state and handler**

In `TargetDetailPage.tsx`, add new signals near the existing `showMerge` signal (line 48):

```typescript
const [editing, setEditing] = createSignal(false);
const [editName, setEditName] = createSignal("");
const [savingName, setSavingName] = createSignal(false);
```

Add the rename handler:

```typescript
const handleRename = async () => {
  if (!editName().trim() || editName() === detail().primary_name) {
    setEditing(false);
    return;
  }
  setSavingName(true);
  try {
    await api.updateTargetIdentity(detail().target_id, { primary_name: editName() });
    setEditing(false);
    refetch();
  } finally {
    setSavingName(false);
  }
};

const handleReResolve = async () => {
  setSavingName(true);
  try {
    await api.updateTargetIdentity(detail().target_id, { re_resolve: true });
    refetch();
  } finally {
    setSavingName(false);
  }
};
```

Where `refetch` is the refetch function from the `createResource` that loads `targetDetail`.

- [ ] **Step 2: Update the hero name display**

Find the `<h1>` displaying `detail().primary_name` (line 227). Replace it with an inline-editable version:

```tsx
<Show when={!editing()}>
  <h1 class="text-2xl font-semibold text-theme-primary inline-flex items-center gap-2">
    {detail().primary_name}
    <Show when={detail().name_locked}>
      <span class="text-xs text-theme-tertiary" title="Name set manually. Automatic processes will not rename this target.">&#128274;</span>
    </Show>
    <Show when={auth.isAdmin()}>
      <button
        onClick={() => { setEditName(detail().primary_name); setEditing(true); }}
        class="text-theme-tertiary hover:text-theme-primary text-sm"
        title="Edit name"
      >&#9998;</button>
      <button
        onClick={handleReResolve}
        disabled={savingName()}
        class="text-theme-tertiary hover:text-theme-primary text-sm"
        title="Re-resolve from SIMBAD"
      >&#8635;</button>
    </Show>
  </h1>
</Show>
<Show when={editing()}>
  <div class="flex items-center gap-2">
    <input
      type="text"
      value={editName()}
      onInput={(e) => setEditName(e.currentTarget.value)}
      onKeyDown={(e) => { if (e.key === "Enter") handleRename(); if (e.key === "Escape") setEditing(false); }}
      class="text-2xl font-semibold bg-theme-base border border-theme-border rounded px-2 py-1 text-theme-primary w-full"
      autofocus
    />
    <button onClick={handleRename} disabled={savingName()} class="text-green-400 hover:text-green-300 text-lg">&#10003;</button>
    <button onClick={() => setEditing(false)} class="text-theme-tertiary hover:text-theme-primary text-lg">&times;</button>
  </div>
</Show>
```

Note: The backend `TargetDetailResponse` schema needs to include `name_locked`. Check `backend/app/api/targets.py` where the detail response is built and add `name_locked` to the returned dict if not already present.

- [ ] **Step 3: Replace MergeTargetModal with MergePreviewModal**

In the imports, replace:
```typescript
// Before:
import { MergeTargetModal } from "../components/MergeTargetModal";
// After:
import { MergePreviewModal } from "../components/MergePreviewModal";
```

In the modal render section (lines 205-215), replace:
```tsx
// Before:
<MergeTargetModal
  targetId={targetDetail()!.target_id}
  targetName={targetDetail()!.primary_name}
  onClose={() => setShowMerge(false)}
  onMerged={() => { setShowMerge(false); window.location.reload(); }}
/>

// After:
<MergePreviewModal
  winnerId={targetDetail()!.target_id}
  onClose={() => setShowMerge(false)}
  onMerged={() => { setShowMerge(false); refetch(); }}
/>
```

Note: The merge button on TargetDetail now opens the preview modal directly. The user searches for a target to merge (keeping the existing search UX from MergeTargetModal), and after selecting one, the preview loads. To support this flow, add a search step before the preview: either integrate search into MergePreviewModal, or keep a thin search wrapper that feeds `loserId` into MergePreviewModal.

The simplest approach: add an optional `onSearchForTarget` mode to MergePreviewModal, or keep the "Merge" button opening a small search popover first (reusing the search from MergeTargetModal lines 26-40), then passing the selected target ID to MergePreviewModal.

Create a small wrapper for the TargetDetail use case:

```tsx
const MergeFromDetailFlow: Component<{ targetId: string; onClose: () => void; onMerged: () => void }> = (props) => {
  const [searchQuery, setSearchQuery] = createSignal("");
  const [searchResults, setSearchResults] = createSignal<any[]>([]);
  const [selectedLoserId, setSelectedLoserId] = createSignal<string | null>(null);

  const handleSearch = async (q: string) => {
    setSearchQuery(q);
    if (q.length < 2) { setSearchResults([]); return; }
    const results = await api.searchTargets(q);
    setSearchResults(results.filter((t: any) => t.id !== props.targetId));
  };

  return (
    <Show when={selectedLoserId()} fallback={
      /* search step - render a modal with search input and results list */
      <div class="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={(e) => { if (e.target === e.currentTarget) props.onClose(); }}>
        <div class="bg-theme-elevated border border-theme-border rounded-lg shadow-xl w-full max-w-md mx-4 p-4 space-y-3">
          <h2 class="text-lg font-semibold text-theme-primary">Select target to merge</h2>
          <input
            type="text"
            placeholder="Search targets..."
            value={searchQuery()}
            onInput={(e) => handleSearch(e.currentTarget.value)}
            class="w-full bg-theme-base border border-theme-border rounded px-3 py-2 text-sm text-theme-primary"
            autofocus
          />
          <div class="max-h-60 overflow-y-auto space-y-1">
            <For each={searchResults()}>
              {(t) => (
                <button
                  onClick={() => setSelectedLoserId(t.id)}
                  class="w-full text-left px-3 py-2 rounded hover:bg-theme-hover text-sm text-theme-primary"
                >{t.primary_name}</button>
              )}
            </For>
          </div>
          <div class="flex justify-end">
            <button onClick={props.onClose} class="text-sm text-theme-tertiary hover:text-theme-primary">Cancel</button>
          </div>
        </div>
      </div>
    }>
      <MergePreviewModal
        winnerId={props.targetId}
        loserId={selectedLoserId()!}
        onClose={props.onClose}
        onMerged={props.onMerged}
      />
    </Show>
  );
};
```

Use this wrapper in the TargetDetailPage render:
```tsx
<Show when={showMerge()}>
  <MergeFromDetailFlow
    targetId={targetDetail()!.target_id}
    onClose={() => setShowMerge(false)}
    onMerged={() => { setShowMerge(false); refetch(); }}
  />
</Show>
```

- [ ] **Step 4: Test in browser**

Navigate to a target detail page. Verify:
- Edit icon appears next to the name (admin only)
- Clicking edit icon shows inline text input
- Enter saves, Escape cancels
- Re-resolve icon triggers SIMBAD re-lookup
- Merge button opens search, then preview modal

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/TargetDetailPage.tsx frontend/src/components/MergePreviewModal.tsx
git commit -m "feat: add inline rename and merge preview to TargetDetailPage"
```

---

### Task 15: Frontend - Reorganize MaintenanceActions

**Files:**
- Modify: `frontend/src/components/MaintenanceActions.tsx`
- Modify: `frontend/src/store/activeJobs.ts:38-61`

- [ ] **Step 1: Reduce MaintenanceActions to two buttons**

Rewrite `MaintenanceActions.tsx` to keep only:
- **Fetch Reference Images** (was "Fetch DSS") - with the existing "Missing only" / "Re-fetch all" sub-actions
- **Regenerate Thumbnails** - with the existing purge confirmation

Remove: Fix Orphans, Re-resolve, Catalog Match, Full Rebuild (all moved to Target Health Advanced section or removed entirely).

Keep the `emitWithToast` wrapper and `busy` signal pattern. Update button labels:
- "Fetch DSS" -> "Fetch Reference Images"
- Add subtitle: "Downloads survey images from NASA SkyView"

- [ ] **Step 2: Update activeJobs labels**

In `frontend/src/store/activeJobs.ts`, update the mode labels in `rebuildStatusToJob` (lines 43-50):

```typescript
// Before:
smart: "Fix Orphans",
full: "Full Rebuild",
retry: "Re-resolve Targets",
xmatch: "Catalog Match",
ref_thumbnails: "Fetch DSS Thumbnails",
regen: "Regenerate Thumbnails",

// After:
smart: "Repairing Target Links",
full: "Full Rebuild",
retry: "Retrying Failed Lookups",
ref_thumbnails: "Fetching Reference Images",
regen: "Regenerating Thumbnails",
```

Remove the `xmatch` entry.

- [ ] **Step 3: Test in browser**

Navigate to Settings > Library tab. Verify only "Fetch Reference Images" and "Regenerate Thumbnails" appear in the maintenance section.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/MaintenanceActions.tsx frontend/src/store/activeJobs.ts
git commit -m "feat: reduce maintenance buttons to reference images and thumbnails only"
```

---

### Task 16: Backend - Add name_locked to Target Detail Response

**Files:**
- Modify: `backend/app/api/targets.py` (the detail endpoint response builder)

- [ ] **Step 1: Add name_locked to the detail response**

Find the `GET /targets/{slug}/detail` endpoint in `backend/app/api/targets.py`. Locate where the response dict is built (the return statement that constructs the target detail JSON). Add `"name_locked": target.name_locked` to the response dict.

- [ ] **Step 2: Verify in browser**

Start the backend: `cd backend && uvicorn app.main:app --reload`
Hit `GET /api/targets/{some-target}/detail` in the browser or curl.
Expected: Response includes `"name_locked": false` for existing targets.

- [ ] **Step 3: Commit**

```bash
git add backend/app/api/targets.py
git commit -m "feat: include name_locked in target detail response"
```

---

### Task 17: Integration Testing

**Files:**
- No new files

- [ ] **Step 1: Run full backend test suite**

Run: `cd backend && python -m pytest tests/ -v --timeout=60`
Expected: All tests pass.

- [ ] **Step 2: Run frontend dev server and manually test all flows**

Start both servers:
- `cd backend && uvicorn app.main:app --reload`
- `cd frontend && npm run dev`

Test these flows:
1. Settings > Target Health tab loads with issue list
2. Filter pills work (Duplicates, Unresolved, Recent Merges)
3. Post-scan summary banner appears after a scan
4. "Preview Merge" on a duplicate opens the side-by-side modal
5. Merge executes and card updates to "merged" state
6. "Not a Duplicate" dismisses a candidate
7. "Undo Merge" on a recent merge reverts it
8. Unresolved items show "Retry Failed Lookups" banner
9. Advanced section collapses/expands with three maintenance buttons
10. Target detail page: inline rename works (Enter saves, Escape cancels)
11. Target detail page: re-resolve refreshes from SIMBAD
12. Target detail page: Merge button opens search then preview modal
13. Library tab: only "Fetch Reference Images" and "Regenerate Thumbnails" in maintenance

- [ ] **Step 3: Commit any fixes discovered during testing**

```bash
git add -A
git commit -m "fix: integration test fixes for target health redesign"
```
