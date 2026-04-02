# Mosaic Panel Tracking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Track multi-panel mosaic astrophotography projects with auto-detection from naming conventions, manual grouping, spatial RA/Dec grid visualization, and per-panel integration tracking.

**Architecture:** New `mosaics`, `mosaic_panels`, and `mosaic_suggestions` tables. New CRUD API router. Auto-detection via configurable keywords during background task. Frontend mosaic detail page with spatial grid and panel table.

**Tech Stack:** FastAPI + SQLAlchemy + Alembic (backend), SolidJS + SVG (frontend grid), Celery (auto-detection task)

---

### Task 1: Backend — Mosaic Models

**Files:**
- Create: `backend/app/models/mosaic.py`
- Create: `backend/app/models/mosaic_panel.py`
- Create: `backend/app/models/mosaic_suggestion.py`
- Modify: `backend/app/models/__init__.py`

- [ ] **Step 1: Create Mosaic model**

Create `backend/app/models/mosaic.py`:

```python
import uuid
from datetime import datetime

from sqlalchemy import String, Text, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class Mosaic(Base):
    __tablename__ = "mosaics"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    panels: Mapped[list["MosaicPanel"]] = relationship(back_populates="mosaic", cascade="all, delete-orphan")
```

- [ ] **Step 2: Create MosaicPanel model**

Create `backend/app/models/mosaic_panel.py`:

```python
import uuid

from sqlalchemy import String, Integer, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class MosaicPanel(Base):
    __tablename__ = "mosaic_panels"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    mosaic_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("mosaics.id", ondelete="CASCADE"), nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("targets.id"), nullable=False, unique=True)
    panel_label: Mapped[str] = mapped_column(String(100), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    mosaic: Mapped["Mosaic"] = relationship(back_populates="panels")
    target: Mapped["Target"] = relationship()

    __table_args__ = (
        UniqueConstraint("mosaic_id", "target_id", name="uq_mosaic_panels_mosaic_target"),
    )
```

- [ ] **Step 3: Create MosaicSuggestion model**

Create `backend/app/models/mosaic_suggestion.py`:

```python
import uuid
from datetime import datetime

from sqlalchemy import String, DateTime
from sqlalchemy.dialects.postgresql import UUID, ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class MosaicSuggestion(Base):
    __tablename__ = "mosaic_suggestions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    suggested_name: Mapped[str] = mapped_column(String(255), nullable=False)
    target_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)), nullable=False)
    panel_labels: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
```

- [ ] **Step 4: Register models**

In `backend/app/models/__init__.py`, add:

```python
from .mosaic import Mosaic
from .mosaic_panel import MosaicPanel
from .mosaic_suggestion import MosaicSuggestion
```

Update `__all__` to include `"Mosaic"`, `"MosaicPanel"`, `"MosaicSuggestion"`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/models/mosaic.py backend/app/models/mosaic_panel.py backend/app/models/mosaic_suggestion.py backend/app/models/__init__.py
git commit -m "feat: add Mosaic, MosaicPanel, MosaicSuggestion models"
```

---

### Task 2: Backend — Mosaic Migration

**Files:**
- Create: `backend/alembic/versions/0017_add_mosaic_tables.py`

- [ ] **Step 1: Create migration**

Create `backend/alembic/versions/0017_add_mosaic_tables.py`:

```python
"""Add mosaics, mosaic_panels, and mosaic_suggestions tables."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, ARRAY

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mosaics",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False, unique=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        if_not_exists=True,
    )

    op.create_table(
        "mosaic_panels",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("mosaic_id", UUID(as_uuid=True), sa.ForeignKey("mosaics.id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_id", UUID(as_uuid=True), sa.ForeignKey("targets.id"), nullable=False, unique=True),
        sa.Column("panel_label", sa.String(100), nullable=False),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        sa.UniqueConstraint("mosaic_id", "target_id", name="uq_mosaic_panels_mosaic_target"),
        if_not_exists=True,
    )

    op.create_table(
        "mosaic_suggestions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("suggested_name", sa.String(255), nullable=False),
        sa.Column("target_ids", ARRAY(UUID(as_uuid=True)), nullable=False),
        sa.Column("panel_labels", ARRAY(sa.String), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_table("mosaic_suggestions")
    op.drop_table("mosaic_panels")
    op.drop_table("mosaics")
```

- [ ] **Step 2: Run migration**

```bash
cd backend && alembic upgrade head
```

Expected: `Running upgrade 0016 -> 0017`

- [ ] **Step 3: Commit**

```bash
git add backend/alembic/versions/0017_add_mosaic_tables.py
git commit -m "feat: add mosaic tables migration"
```

---

### Task 3: Backend — Mosaic Schemas

**Files:**
- Create: `backend/app/schemas/mosaic.py`

- [ ] **Step 1: Create mosaic schemas**

Create `backend/app/schemas/mosaic.py`:

```python
import uuid

from pydantic import BaseModel


class MosaicPanelCreate(BaseModel):
    target_id: uuid.UUID
    panel_label: str


class MosaicPanelUpdate(BaseModel):
    panel_label: str | None = None
    sort_order: int | None = None


class MosaicCreate(BaseModel):
    name: str
    notes: str | None = None
    panels: list[MosaicPanelCreate] = []


class MosaicUpdate(BaseModel):
    name: str | None = None
    notes: str | None = None


class PanelStats(BaseModel):
    panel_id: str
    target_id: str
    target_name: str
    panel_label: str
    sort_order: int
    ra: float | None = None
    dec: float | None = None
    total_integration_seconds: float
    total_frames: int
    filter_distribution: dict[str, float]
    last_session_date: str | None = None


class MosaicSummary(BaseModel):
    id: str
    name: str
    notes: str | None = None
    panel_count: int
    total_integration_seconds: float
    total_frames: int
    completion_pct: float


class MosaicDetailResponse(BaseModel):
    id: str
    name: str
    notes: str | None = None
    total_integration_seconds: float
    total_frames: int
    panels: list[PanelStats]


class MosaicSuggestionResponse(BaseModel):
    id: str
    suggested_name: str
    target_ids: list[str]
    panel_labels: list[str]
    status: str
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/schemas/mosaic.py
git commit -m "feat: add mosaic Pydantic schemas"
```

---

### Task 4: Backend — Mosaic API Router

**Files:**
- Create: `backend/app/api/mosaics.py`
- Modify: `backend/app/api/router.py`

- [ ] **Step 1: Create the mosaics router**

Create `backend/app/api/mosaics.py`:

```python
import uuid
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func, cast, Date
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_session
from app.models import Image, Target, User
from app.models.mosaic import Mosaic
from app.models.mosaic_panel import MosaicPanel
from app.models.mosaic_suggestion import MosaicSuggestion
from app.schemas.mosaic import (
    MosaicCreate, MosaicUpdate, MosaicPanelCreate, MosaicPanelUpdate,
    MosaicSummary, MosaicDetailResponse, PanelStats, MosaicSuggestionResponse,
)
from app.api.auth import get_current_user

router = APIRouter(prefix="/mosaics", tags=["mosaics"])


async def _panel_stats(panel: MosaicPanel, session: AsyncSession) -> PanelStats:
    """Compute stats for a single panel."""
    target = panel.target

    q = (
        select(
            func.sum(Image.exposure_time).label("integration"),
            func.count(Image.id).label("frames"),
            func.max(cast(Image.capture_date, Date)).label("last_date"),
        )
        .where(Image.resolved_target_id == panel.target_id)
        .where(Image.image_type == "LIGHT")
    )
    row = (await session.execute(q)).one()

    # Filter distribution
    fq = (
        select(Image.filter_used, func.sum(Image.exposure_time))
        .where(Image.resolved_target_id == panel.target_id)
        .where(Image.image_type == "LIGHT")
        .where(Image.filter_used.is_not(None))
        .group_by(Image.filter_used)
    )
    filter_dist = {r[0]: r[1] or 0 for r in (await session.execute(fq)).all()}

    return PanelStats(
        panel_id=str(panel.id),
        target_id=str(panel.target_id),
        target_name=target.primary_name,
        panel_label=panel.panel_label,
        sort_order=panel.sort_order,
        ra=target.ra,
        dec=target.dec,
        total_integration_seconds=row.integration or 0,
        total_frames=row.frames or 0,
        filter_distribution=filter_dist,
        last_session_date=str(row.last_date) if row.last_date else None,
    )


@router.get("", response_model=list[MosaicSummary])
async def list_mosaics(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    q = select(Mosaic).options(selectinload(Mosaic.panels)).order_by(Mosaic.name)
    mosaics = (await session.execute(q)).scalars().all()

    results = []
    for m in mosaics:
        total_int = 0
        total_frames = 0
        panel_integrations = []
        for p in m.panels:
            iq = (
                select(func.sum(Image.exposure_time), func.count(Image.id))
                .where(Image.resolved_target_id == p.target_id)
                .where(Image.image_type == "LIGHT")
            )
            row = (await session.execute(iq)).one()
            pi = row[0] or 0
            total_int += pi
            total_frames += row[1] or 0
            panel_integrations.append(pi)

        max_panel = max(panel_integrations) if panel_integrations else 0
        if max_panel > 0 and len(panel_integrations) > 0:
            completion = sum(min(p / max_panel, 1.0) for p in panel_integrations) / len(panel_integrations) * 100
        else:
            completion = 0

        results.append(MosaicSummary(
            id=str(m.id),
            name=m.name,
            notes=m.notes,
            panel_count=len(m.panels),
            total_integration_seconds=total_int,
            total_frames=total_frames,
            completion_pct=round(completion, 1),
        ))
    return results


@router.post("", response_model=MosaicSummary)
async def create_mosaic(
    body: MosaicCreate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    mosaic = Mosaic(name=body.name, notes=body.notes)
    session.add(mosaic)
    await session.flush()

    for p in body.panels:
        panel = MosaicPanel(
            mosaic_id=mosaic.id,
            target_id=p.target_id,
            panel_label=p.panel_label,
        )
        session.add(panel)

    await session.commit()
    return MosaicSummary(
        id=str(mosaic.id),
        name=mosaic.name,
        notes=mosaic.notes,
        panel_count=len(body.panels),
        total_integration_seconds=0,
        total_frames=0,
        completion_pct=0,
    )


@router.get("/{mosaic_id}", response_model=MosaicDetailResponse)
async def get_mosaic_detail(
    mosaic_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    q = select(Mosaic).options(
        selectinload(Mosaic.panels).selectinload(MosaicPanel.target)
    ).where(Mosaic.id == mosaic_id)
    mosaic = (await session.execute(q)).scalar_one_or_none()
    if not mosaic:
        raise HTTPException(404, "Mosaic not found")

    panels = []
    total_int = 0
    total_frames = 0
    for p in sorted(mosaic.panels, key=lambda x: x.sort_order):
        ps = await _panel_stats(p, session)
        total_int += ps.total_integration_seconds
        total_frames += ps.total_frames
        panels.append(ps)

    return MosaicDetailResponse(
        id=str(mosaic.id),
        name=mosaic.name,
        notes=mosaic.notes,
        total_integration_seconds=total_int,
        total_frames=total_frames,
        panels=panels,
    )


@router.put("/{mosaic_id}")
async def update_mosaic(
    mosaic_id: uuid.UUID,
    body: MosaicUpdate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    mosaic = await session.get(Mosaic, mosaic_id)
    if not mosaic:
        raise HTTPException(404, "Mosaic not found")
    if body.name is not None:
        mosaic.name = body.name
    if body.notes is not None:
        mosaic.notes = body.notes
    await session.commit()
    return {"status": "ok"}


@router.delete("/{mosaic_id}")
async def delete_mosaic(
    mosaic_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    mosaic = await session.get(Mosaic, mosaic_id)
    if not mosaic:
        raise HTTPException(404, "Mosaic not found")
    await session.delete(mosaic)
    await session.commit()
    return {"status": "ok"}


@router.post("/{mosaic_id}/panels")
async def add_panel(
    mosaic_id: uuid.UUID,
    body: MosaicPanelCreate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    mosaic = await session.get(Mosaic, mosaic_id)
    if not mosaic:
        raise HTTPException(404, "Mosaic not found")

    # Check target not already in a mosaic
    existing = (await session.execute(
        select(MosaicPanel).where(MosaicPanel.target_id == body.target_id)
    )).scalar_one_or_none()
    if existing:
        raise HTTPException(400, "Target already belongs to a mosaic")

    panel = MosaicPanel(
        mosaic_id=mosaic_id,
        target_id=body.target_id,
        panel_label=body.panel_label,
    )
    session.add(panel)
    await session.commit()
    return {"status": "ok", "panel_id": str(panel.id)}


@router.put("/{mosaic_id}/panels/{panel_id}")
async def update_panel(
    mosaic_id: uuid.UUID,
    panel_id: uuid.UUID,
    body: MosaicPanelUpdate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    panel = await session.get(MosaicPanel, panel_id)
    if not panel or panel.mosaic_id != mosaic_id:
        raise HTTPException(404, "Panel not found")
    if body.panel_label is not None:
        panel.panel_label = body.panel_label
    if body.sort_order is not None:
        panel.sort_order = body.sort_order
    await session.commit()
    return {"status": "ok"}


@router.delete("/{mosaic_id}/panels/{panel_id}")
async def remove_panel(
    mosaic_id: uuid.UUID,
    panel_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    panel = await session.get(MosaicPanel, panel_id)
    if not panel or panel.mosaic_id != mosaic_id:
        raise HTTPException(404, "Panel not found")
    await session.delete(panel)
    await session.commit()
    return {"status": "ok"}


# NOTE: This endpoint MUST be defined BEFORE the /{mosaic_id} routes
# to avoid FastAPI interpreting "suggestions" as a UUID path parameter.
# Place it at the TOP of the router, before any /{mosaic_id} endpoints.
@router.get("/suggestions", response_model=list[MosaicSuggestionResponse])
async def get_suggestions(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    q = select(MosaicSuggestion).where(MosaicSuggestion.status == "pending")
    rows = (await session.execute(q)).scalars().all()
    return [
        MosaicSuggestionResponse(
            id=str(r.id),
            suggested_name=r.suggested_name,
            target_ids=[str(t) for t in r.target_ids],
            panel_labels=r.panel_labels,
            status=r.status,
        )
        for r in rows
    ]
```

- [ ] **Step 2: Register the router**

In `backend/app/api/router.py`, add:

```python
from .mosaics import router as mosaics_router
```

And:

```python
api_router.include_router(mosaics_router)
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/api/mosaics.py backend/app/api/router.py
git commit -m "feat: add mosaics CRUD API router"
```

---

### Task 5: Backend — Mosaic Auto-Detection Task

**Files:**
- Create: `backend/app/services/mosaic_detection.py`

- [ ] **Step 1: Create detection service**

Create `backend/app/services/mosaic_detection.py`:

```python
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
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/services/mosaic_detection.py
git commit -m "feat: add mosaic panel auto-detection service"
```

---

### Task 6: Backend — Mosaic Settings

**Files:**
- Modify: `backend/app/schemas/settings.py`

- [ ] **Step 1: Add mosaic_keywords to GeneralSettings**

In `backend/app/schemas/settings.py`, add to `GeneralSettings`:

```python
    mosaic_keywords: list[str] = ["Panel", "P"]
```

No migration needed — stored in existing JSONB `general` column.

- [ ] **Step 2: Commit**

```bash
git add backend/app/schemas/settings.py
git commit -m "feat: add mosaic_keywords to general settings"
```

---

### Task 7: Frontend — Mosaic Types and API

**Files:**
- Modify: `frontend/src/types/index.ts`
- Modify: `frontend/src/api/client.ts`

- [ ] **Step 1: Add mosaic types**

In `frontend/src/types/index.ts`, add:

```typescript
// === Mosaics ===

export interface PanelStats {
  panel_id: string;
  target_id: string;
  target_name: string;
  panel_label: string;
  sort_order: number;
  ra: number | null;
  dec: number | null;
  total_integration_seconds: number;
  total_frames: number;
  filter_distribution: Record<string, number>;
  last_session_date: string | null;
}

export interface MosaicSummary {
  id: string;
  name: string;
  notes: string | null;
  panel_count: number;
  total_integration_seconds: number;
  total_frames: number;
  completion_pct: number;
}

export interface MosaicDetailResponse {
  id: string;
  name: string;
  notes: string | null;
  total_integration_seconds: number;
  total_frames: number;
  panels: PanelStats[];
}

export interface MosaicSuggestionResponse {
  id: string;
  suggested_name: string;
  target_ids: string[];
  panel_labels: string[];
  status: string;
}
```

- [ ] **Step 2: Add API methods**

In `frontend/src/api/client.ts`, add to the `api` object:

```typescript
  // Mosaics
  getMosaics: () =>
    fetchJson<import("../types").MosaicSummary[]>("/mosaics"),

  createMosaic: (name: string, notes?: string, panels?: { target_id: string; panel_label: string }[]) =>
    fetchJson<import("../types").MosaicSummary>("/mosaics", {
      method: "POST",
      body: JSON.stringify({ name, notes, panels: panels || [] }),
    }),

  getMosaicDetail: (id: string) =>
    fetchJson<import("../types").MosaicDetailResponse>(`/mosaics/${id}`),

  updateMosaic: (id: string, data: { name?: string; notes?: string }) =>
    fetchJson<{ status: string }>(`/mosaics/${id}`, {
      method: "PUT",
      body: JSON.stringify(data),
    }),

  deleteMosaic: (id: string) =>
    fetchJson<{ status: string }>(`/mosaics/${id}`, { method: "DELETE" }),

  addMosaicPanel: (mosaicId: string, targetId: string, label: string) =>
    fetchJson<{ status: string; panel_id: string }>(`/mosaics/${mosaicId}/panels`, {
      method: "POST",
      body: JSON.stringify({ target_id: targetId, panel_label: label }),
    }),

  updateMosaicPanel: (mosaicId: string, panelId: string, data: { panel_label?: string; sort_order?: number }) =>
    fetchJson<{ status: string }>(`/mosaics/${mosaicId}/panels/${panelId}`, {
      method: "PUT",
      body: JSON.stringify(data),
    }),

  removeMosaicPanel: (mosaicId: string, panelId: string) =>
    fetchJson<{ status: string }>(`/mosaics/${mosaicId}/panels/${panelId}`, { method: "DELETE" }),

  getMosaicSuggestions: () =>
    fetchJson<import("../types").MosaicSuggestionResponse[]>("/mosaics/suggestions"),
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/types/index.ts frontend/src/api/client.ts
git commit -m "feat: add mosaic API client methods and types"
```

---

### Task 8: Frontend — Mosaic Grid Component

**Files:**
- Create: `frontend/src/components/mosaics/MosaicGrid.tsx`

- [ ] **Step 1: Create the spatial grid component**

Create `frontend/src/components/mosaics/MosaicGrid.tsx`:

```typescript
import { Component, For, Show, createMemo, createSignal } from "solid-js";
import type { PanelStats } from "../../types";

function formatHours(seconds: number): string {
  return (seconds / 3600).toFixed(1) + "h";
}

function getCompletionColor(pct: number): string {
  if (pct >= 80) return "var(--color-success, #26a641)";
  if (pct >= 40) return "var(--color-warning, #d29922)";
  return "var(--color-error, #f85149)";
}

interface Props {
  panels: PanelStats[];
}

const MosaicGrid: Component<Props> = (props) => {
  const [tooltip, setTooltip] = createSignal<{ x: number; y: number; panel: PanelStats } | null>(null);

  const gridData = createMemo(() => {
    const panels = props.panels;
    if (panels.length === 0) return { positions: [], width: 0, height: 0 };

    // Compute relative RA/Dec positions
    const withCoords = panels.filter((p) => p.ra != null && p.dec != null);
    const withoutCoords = panels.filter((p) => p.ra == null || p.dec == null);

    // Max integration for color scaling
    const maxInt = Math.max(...panels.map((p) => p.total_integration_seconds), 1);

    if (withCoords.length < 2) {
      // Fall back to a simple row layout
      const CELL = 80;
      const GAP = 10;
      return {
        positions: panels.map((p, i) => ({
          panel: p,
          x: i * (CELL + GAP),
          y: 0,
          width: CELL,
          height: CELL,
          pct: (p.total_integration_seconds / maxInt) * 100,
        })),
        width: panels.length * (CELL + GAP),
        height: CELL,
      };
    }

    // Map RA/Dec to pixel positions
    const ras = withCoords.map((p) => p.ra!);
    const decs = withCoords.map((p) => p.dec!);
    const minRa = Math.min(...ras);
    const maxRa = Math.max(...ras);
    const minDec = Math.min(...decs);
    const maxDec = Math.max(...decs);
    const raRange = maxRa - minRa || 1;
    const decRange = maxDec - minDec || 1;

    const GRID_SIZE = 400;
    const CELL = 70;
    const PADDING = 50;

    const positions = withCoords.map((p) => {
      // RA increases to the left in sky coordinates, invert for display
      const xNorm = 1 - (p.ra! - minRa) / raRange;
      const yNorm = 1 - (p.dec! - minDec) / decRange;
      return {
        panel: p,
        x: PADDING + xNorm * (GRID_SIZE - 2 * PADDING - CELL),
        y: PADDING + yNorm * (GRID_SIZE - 2 * PADDING - CELL),
        width: CELL,
        height: CELL,
        pct: (p.total_integration_seconds / maxInt) * 100,
      };
    });

    // Place panels without coordinates in a row below
    withoutCoords.forEach((p, i) => {
      positions.push({
        panel: p,
        x: PADDING + i * (CELL + 10),
        y: GRID_SIZE - CELL,
        width: CELL,
        height: CELL,
        pct: (p.total_integration_seconds / maxInt) * 100,
      });
    });

    return { positions, width: GRID_SIZE, height: GRID_SIZE };
  });

  return (
    <div class="relative" onMouseLeave={() => setTooltip(null)}>
      <svg
        width={gridData().width}
        height={gridData().height}
        class="block mx-auto"
      >
        <For each={gridData().positions}>
          {(pos) => (
            <g
              onMouseEnter={(e) => setTooltip({ x: e.clientX, y: e.clientY, panel: pos.panel })}
              onMouseLeave={() => setTooltip(null)}
              class="cursor-pointer"
            >
              <rect
                x={pos.x}
                y={pos.y}
                width={pos.width}
                height={pos.height}
                rx={4}
                fill={getCompletionColor(pos.pct)}
                opacity={0.8}
                stroke="var(--color-theme-border)"
                stroke-width={1}
              />
              <text
                x={pos.x + pos.width / 2}
                y={pos.y + pos.height / 2 - 6}
                text-anchor="middle"
                class="fill-white"
                font-size="11"
                font-weight="bold"
              >
                {pos.panel.panel_label}
              </text>
              <text
                x={pos.x + pos.width / 2}
                y={pos.y + pos.height / 2 + 10}
                text-anchor="middle"
                class="fill-white"
                font-size="9"
                opacity={0.8}
              >
                {formatHours(pos.panel.total_integration_seconds)}
              </text>
            </g>
          )}
        </For>
      </svg>

      <Show when={tooltip()}>
        {(t) => (
          <div
            class="fixed z-50 bg-theme-elevated border border-theme-border rounded px-3 py-2 text-xs shadow-[var(--shadow-md)] pointer-events-none"
            style={{ left: `${t().x + 10}px`, top: `${t().y - 60}px` }}
          >
            <div class="font-medium text-theme-text-primary">{t().panel.target_name}</div>
            <div class="text-theme-text-secondary">
              {formatHours(t().panel.total_integration_seconds)} &middot; {t().panel.total_frames} frames
            </div>
            <div class="text-theme-text-secondary">
              {Object.entries(t().panel.filter_distribution).map(([f, s]) => `${f}: ${formatHours(s)}`).join(", ")}
            </div>
          </div>
        )}
      </Show>

      {/* Legend */}
      <div class="flex items-center justify-center gap-4 mt-2 text-xs text-theme-text-secondary">
        <span class="flex items-center gap-1">
          <div class="w-3 h-3 rounded" style={{ background: "var(--color-error, #f85149)" }} /> &lt;40%
        </span>
        <span class="flex items-center gap-1">
          <div class="w-3 h-3 rounded" style={{ background: "var(--color-warning, #d29922)" }} /> 40-80%
        </span>
        <span class="flex items-center gap-1">
          <div class="w-3 h-3 rounded" style={{ background: "var(--color-success, #26a641)" }} /> &gt;80%
        </span>
      </div>
    </div>
  );
};

export default MosaicGrid;
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/mosaics/MosaicGrid.tsx
git commit -m "feat: add MosaicGrid spatial visualization component"
```

---

### Task 9: Frontend — Mosaic Detail Page

**Files:**
- Create: `frontend/src/pages/MosaicDetailPage.tsx`
- Modify: `frontend/src/index.tsx` (add route)

- [ ] **Step 1: Create the mosaic detail page**

Create `frontend/src/pages/MosaicDetailPage.tsx`:

```typescript
import { Component, Show, For, createResource, createSignal } from "solid-js";
import { A, useParams } from "@solidjs/router";
import { api } from "../api/client";
import MosaicGrid from "../components/mosaics/MosaicGrid";

function formatHours(seconds: number): string {
  const h = seconds / 3600;
  return h < 1 ? `${Math.round(h * 60)}m` : `${h.toFixed(1)}h`;
}

const MosaicDetailPage: Component = () => {
  const params = useParams<{ mosaicId: string }>();
  const [mosaic, { refetch }] = createResource(() => params.mosaicId, (id) => api.getMosaicDetail(id));

  const [notes, setNotes] = createSignal("");
  const [notesSaving, setNotesSaving] = createSignal(false);
  let notesTimer: ReturnType<typeof setTimeout> | undefined;

  const saveNotes = (text: string) => {
    clearTimeout(notesTimer);
    notesTimer = setTimeout(async () => {
      setNotesSaving(true);
      try {
        await api.updateMosaic(params.mosaicId, { notes: text || undefined });
      } finally {
        setNotesSaving(false);
      }
    }, 1000);
  };

  return (
    <div class="p-4 space-y-4 max-w-7xl mx-auto">
      <A href="/" class="text-xs text-theme-accent hover:underline">&larr; Dashboard</A>

      <Show when={mosaic()} fallback={<div class="text-center text-theme-text-secondary py-8">Loading...</div>}>
        {(data) => (
          <>
            {/* Header */}
            <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] p-4">
              <h2 class="text-lg font-bold text-theme-text-primary">{data().name}</h2>
              <div class="flex gap-4 mt-2 text-xs text-theme-text-secondary">
                <span>{data().panels.length} panels</span>
                <span>{formatHours(data().total_integration_seconds)} total</span>
                <span>{data().total_frames} frames</span>
              </div>
            </div>

            {/* Notes */}
            <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] p-4">
              <div class="flex items-center justify-between mb-2">
                <h3 class="text-sm font-medium text-theme-text-primary">Notes</h3>
                <Show when={notesSaving()}>
                  <span class="text-xs text-theme-text-secondary">Saving...</span>
                </Show>
              </div>
              <textarea
                class="w-full bg-theme-elevated border border-theme-border rounded px-3 py-2 text-sm text-theme-text-primary placeholder-theme-text-secondary resize-y min-h-[50px]"
                placeholder="Add notes about this mosaic project..."
                value={notes() || data().notes || ""}
                onInput={(e) => {
                  const val = e.currentTarget.value;
                  setNotes(val);
                  saveNotes(val);
                }}
              />
            </div>

            {/* Spatial Grid */}
            <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] p-4">
              <h3 class="text-sm font-medium text-theme-text-primary mb-3">Panel Layout</h3>
              <MosaicGrid panels={data().panels} />
            </div>

            {/* Panel Table */}
            <div class="bg-theme-surface border border-theme-border rounded-[var(--radius-md)] shadow-[var(--shadow-sm)] overflow-hidden">
              <table class="w-full text-xs">
                <thead>
                  <tr class="bg-theme-elevated text-theme-text-secondary">
                    <th class="px-3 py-2 text-left">Panel</th>
                    <th class="px-3 py-2 text-left">Target</th>
                    <th class="px-3 py-2 text-right">Integration</th>
                    <th class="px-3 py-2 text-right">Frames</th>
                    <th class="px-3 py-2 text-left">Filters</th>
                    <th class="px-3 py-2 text-left">Last Session</th>
                    <th class="px-3 py-2"></th>
                  </tr>
                </thead>
                <tbody>
                  <For each={data().panels}>
                    {(panel) => (
                      <tr class="border-t border-theme-border hover:bg-theme-elevated/50">
                        <td class="px-3 py-2 text-theme-text-primary font-medium">{panel.panel_label}</td>
                        <td class="px-3 py-2 text-theme-text-primary">{panel.target_name}</td>
                        <td class="px-3 py-2 text-right text-theme-text-primary">{formatHours(panel.total_integration_seconds)}</td>
                        <td class="px-3 py-2 text-right text-theme-text-secondary">{panel.total_frames}</td>
                        <td class="px-3 py-2 text-theme-text-secondary">
                          {Object.entries(panel.filter_distribution)
                            .map(([f, s]) => `${f}: ${formatHours(s)}`)
                            .join(", ")}
                        </td>
                        <td class="px-3 py-2 text-theme-text-secondary">{panel.last_session_date || "—"}</td>
                        <td class="px-3 py-2">
                          <A
                            href={`/targets/${encodeURIComponent(panel.target_id)}`}
                            class="text-theme-accent hover:underline"
                          >
                            Detail
                          </A>
                        </td>
                      </tr>
                    )}
                  </For>
                </tbody>
              </table>
            </div>
          </>
        )}
      </Show>
    </div>
  );
};

export default MosaicDetailPage;
```

- [ ] **Step 2: Add route**

In `frontend/src/index.tsx`, add import:

```typescript
import MosaicDetailPage from "./pages/MosaicDetailPage";
```

Add route:

```typescript
          <Route path="/mosaics/:mosaicId" component={Protected(MosaicDetailPage)} />
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/MosaicDetailPage.tsx frontend/src/index.tsx
git commit -m "feat: add mosaic detail page with grid and panel table"
```

---

### Task 10: Frontend — Mosaic Dashboard Integration

**Files:**
- Modify: `frontend/src/components/NavBar.tsx` (optional — mosaics may not need top-nav, but should be accessible)

- [ ] **Step 1: Add mosaic indicator on target feed**

This is a lighter integration step. In the target feed/aggregation, targets that belong to a mosaic should show a small icon. This requires a new API field.

In `backend/app/schemas/target.py`, add to `TargetAggregation`:

```python
    mosaic_id: str | None = None
    mosaic_name: str | None = None
```

In `backend/app/api/targets.py`, in the `list_targets_aggregated` endpoint, after loading targets, query for mosaic membership:

```python
    # Mosaic membership lookup
    from app.models.mosaic_panel import MosaicPanel
    from app.models.mosaic import Mosaic
    panel_q = select(MosaicPanel.target_id, Mosaic.id, Mosaic.name).join(Mosaic)
    panel_rows = (await session.execute(panel_q)).all()
    mosaic_map = {r[0]: (str(r[1]), r[2]) for r in panel_rows}
```

Then when building `TargetAggregation` objects, add:

```python
    mosaic_id=mosaic_map.get(target_id, (None, None))[0],
    mosaic_name=mosaic_map.get(target_id, (None, None))[1],
```

In the frontend `TargetAggregation` type, add:

```typescript
  mosaic_id: string | null;
  mosaic_name: string | null;
```

In the target feed row component, add a small mosaic icon that links to the mosaic detail:

```typescript
  {target.mosaic_id && (
    <A href={`/mosaics/${target.mosaic_id}`} class="text-theme-accent" title={`Mosaic: ${target.mosaic_name}`}>
      <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
        <rect x="2" y="2" width="9" height="9" rx="1" /><rect x="13" y="2" width="9" height="9" rx="1" />
        <rect x="2" y="13" width="9" height="9" rx="1" /><rect x="13" y="13" width="9" height="9" rx="1" />
      </svg>
    </A>
  )}
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/schemas/target.py backend/app/api/targets.py frontend/src/types/index.ts
git commit -m "feat: add mosaic badge to target feed"
```

- [ ] **Step 3: Verify in browser**

If you have mosaic data, navigate to the dashboard and verify the mosaic icon appears. Click it to verify it navigates to the mosaic detail page.

- [ ] **Step 4: Final commit — verify everything works end-to-end**

```bash
git add -A
git status
```

Review any uncommitted changes. If clean, mosaics feature is complete.
