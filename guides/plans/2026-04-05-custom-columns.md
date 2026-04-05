# Custom Columns & Column Visibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add user-defined custom columns (boolean/text/dropdown) on targets, sessions, and rigs, plus a column picker to hide/show any column in the dashboard and session tables.

**Architecture:** Two new DB tables (`custom_column`, `custom_column_value`) with a CRUD API router, integrated into the existing aggregation and session detail endpoints. Column visibility extends the existing `UserSettings.display` JSONB. Frontend adds a Settings tab for column management, a reusable column picker popover, and inline-editable cells in all tables.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 async, Alembic, PostgreSQL, SolidJS, TypeScript, Tailwind CSS v4

---

## File Structure

### Backend — New Files
- `backend/app/models/custom_column.py` — CustomColumn and CustomColumnValue ORM models
- `backend/app/schemas/custom_column.py` — Pydantic schemas for custom column CRUD and values
- `backend/app/api/custom_columns.py` — FastAPI router for custom column endpoints
- `backend/alembic/versions/0019_add_custom_columns.py` — Migration
- `backend/tests/test_custom_columns.py` — Tests for custom column API

### Backend — Modified Files
- `backend/app/models/__init__.py` — Export new models
- `backend/app/api/router.py` — Register new router
- `backend/app/api/targets.py` — Include custom values in aggregation + session detail responses
- `backend/app/schemas/target.py` — Add `custom_values` field to response schemas
- `backend/app/schemas/settings.py` — Add `ColumnVisibility` schema
- `backend/app/api/settings.py` — Handle column_visibility in display settings

### Frontend — New Files
- `frontend/src/components/ColumnPicker.tsx` — Reusable column visibility popover
- `frontend/src/components/CustomColumnsTab.tsx` — Settings tab for managing custom column definitions
- `frontend/src/components/InlineEditCell.tsx` — Inline-editable cell (boolean/text/dropdown)

### Frontend — Modified Files
- `frontend/src/types/index.ts` — Add custom column types
- `frontend/src/api/client.ts` — Add custom column API methods
- `frontend/src/pages/SettingsPage.tsx` — Add Custom Columns tab
- `frontend/src/components/TargetTable.tsx` — Custom columns + visibility
- `frontend/src/components/TargetRow.tsx` — Render custom column cells
- `frontend/src/components/SessionTable.tsx` — Custom columns + visibility
- `frontend/src/components/SessionAccordionCard.tsx` — Rig-level custom columns
- `frontend/src/components/SettingsProvider.tsx` — Expose custom columns + column visibility
- `frontend/src/utils/displaySettings.ts` — Add column visibility helpers

---

## Task 1: Backend Models

**Files:**
- Create: `backend/app/models/custom_column.py`
- Modify: `backend/app/models/__init__.py`

- [ ] **Step 1: Create the CustomColumn and CustomColumnValue models**

```python
# backend/app/models/custom_column.py
import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    String, Integer, DateTime, Date, Enum, ForeignKey, Index, Text, func,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class ColumnType(str, enum.Enum):
    boolean = "boolean"
    text = "text"
    dropdown = "dropdown"


class AppliesTo(str, enum.Enum):
    target = "target"
    session = "session"
    rig = "rig"


class CustomColumn(Base):
    __tablename__ = "custom_columns"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    column_type: Mapped[ColumnType] = mapped_column(Enum(ColumnType, name="column_type_enum"), nullable=False)
    applies_to: Mapped[AppliesTo] = mapped_column(Enum(AppliesTo, name="applies_to_enum"), nullable=False)
    dropdown_options: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )

    values: Mapped[list["CustomColumnValue"]] = relationship(
        back_populates="column", cascade="all, delete-orphan",
    )


class CustomColumnValue(Base):
    __tablename__ = "custom_column_values"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    column_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("custom_columns.id", ondelete="CASCADE"), nullable=False,
    )
    target_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("targets.id", ondelete="CASCADE"), nullable=False,
    )
    session_date: Mapped[datetime | None] = mapped_column(Date, nullable=True)
    rig_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
    )

    column: Mapped["CustomColumn"] = relationship(back_populates="values")

    __table_args__ = (
        Index(
            "uq_custom_column_value",
            "column_id", "target_id",
            func.coalesce(session_date, "1970-01-01"),
            func.coalesce(rig_label, ""),
            unique=True,
        ),
        Index("ix_custom_column_values_target", "target_id"),
        Index("ix_custom_column_values_column", "column_id"),
    )
```

- [ ] **Step 2: Export new models from `__init__.py`**

Add to `backend/app/models/__init__.py`:

```python
from .custom_column import CustomColumn, CustomColumnValue, ColumnType, AppliesTo
```

And add them to the `__all__` list:

```python
__all__ = [..., "CustomColumn", "CustomColumnValue", "ColumnType", "AppliesTo"]
```

- [ ] **Step 3: Verify models import correctly**

Run: `cd /c/Users/Kumar/git/GalactiLog/backend && python -c "from app.models import CustomColumn, CustomColumnValue; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add backend/app/models/custom_column.py backend/app/models/__init__.py
git commit -m "feat: add CustomColumn and CustomColumnValue ORM models"
```

---

## Task 2: Alembic Migration

**Files:**
- Create: `backend/alembic/versions/0019_add_custom_columns.py`

- [ ] **Step 1: Generate the migration**

Run: `cd /c/Users/Kumar/git/GalactiLog/backend && alembic revision --autogenerate -m "add custom columns tables"`

- [ ] **Step 2: Review and adjust the generated migration**

Ensure the migration uses the defensive pattern. The generated file should create two tables. Edit to add defensive guards:

```python
"""add custom columns tables

Revision ID: <auto>
Revises: <auto>
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, ARRAY


# revision identifiers
revision = "<auto>"
down_revision = "<auto>"
branch_labels = None
depends_on = None


def _table_exists(table: str) -> bool:
    conn = op.get_bind()
    result = conn.execute(sa.text(
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_name = :table"
    ), {"table": table})
    return result.scalar() is not None


def upgrade() -> None:
    if not _table_exists("custom_columns"):
        op.create_table(
            "custom_columns",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("slug", sa.String(255), nullable=False, unique=True),
            sa.Column("column_type", sa.Enum("boolean", "text", "dropdown", name="column_type_enum"), nullable=False),
            sa.Column("applies_to", sa.Enum("target", "session", "rig", name="applies_to_enum"), nullable=False),
            sa.Column("dropdown_options", ARRAY(sa.String), nullable=True),
            sa.Column("display_order", sa.Integer, nullable=False, server_default="0"),
            sa.Column("created_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )

    if not _table_exists("custom_column_values"):
        op.create_table(
            "custom_column_values",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column("column_id", UUID(as_uuid=True), sa.ForeignKey("custom_columns.id", ondelete="CASCADE"), nullable=False),
            sa.Column("target_id", UUID(as_uuid=True), sa.ForeignKey("targets.id", ondelete="CASCADE"), nullable=False),
            sa.Column("session_date", sa.Date, nullable=True),
            sa.Column("rig_label", sa.String(255), nullable=True),
            sa.Column("value", sa.Text, nullable=False),
            sa.Column("updated_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index(
            "uq_custom_column_value",
            "custom_column_values",
            [
                "column_id", "target_id",
                sa.text("COALESCE(session_date, '1970-01-01')"),
                sa.text("COALESCE(rig_label, '')"),
            ],
            unique=True,
        )
        op.create_index("ix_custom_column_values_target", "custom_column_values", ["target_id"])
        op.create_index("ix_custom_column_values_column", "custom_column_values", ["column_id"])


def downgrade() -> None:
    op.drop_table("custom_column_values")
    op.drop_table("custom_columns")
    op.execute("DROP TYPE IF EXISTS column_type_enum")
    op.execute("DROP TYPE IF EXISTS applies_to_enum")
```

- [ ] **Step 3: Run the migration locally**

Run: `cd /c/Users/Kumar/git/GalactiLog/backend && alembic upgrade head`
Expected: Migration applied successfully, no errors.

- [ ] **Step 4: Commit**

```bash
git add backend/alembic/versions/0019_add_custom_columns.py
git commit -m "migration: add custom_columns and custom_column_values tables"
```

---

## Task 3: Backend Schemas

**Files:**
- Create: `backend/app/schemas/custom_column.py`
- Modify: `backend/app/schemas/target.py`
- Modify: `backend/app/schemas/settings.py`

- [ ] **Step 1: Create custom column schemas**

```python
# backend/app/schemas/custom_column.py
from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field


class CustomColumnCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    column_type: str = Field(..., pattern=r"^(boolean|text|dropdown)$")
    applies_to: str = Field(..., pattern=r"^(target|session|rig)$")
    dropdown_options: list[str] | None = None


class CustomColumnUpdate(BaseModel):
    name: str | None = None
    dropdown_options: list[str] | None = None
    display_order: int | None = None


class CustomColumnResponse(BaseModel):
    id: str
    name: str
    slug: str
    column_type: str
    applies_to: str
    dropdown_options: list[str] | None = None
    display_order: int
    created_by: str
    created_at: datetime

    model_config = {"from_attributes": True}


class CustomColumnValueSet(BaseModel):
    column_id: str
    target_id: str
    session_date: date | None = None
    rig_label: str | None = None
    value: str


class CustomColumnValueResponse(BaseModel):
    column_id: str
    column_slug: str
    target_id: str
    session_date: date | None = None
    rig_label: str | None = None
    value: str
    updated_by: str
    updated_at: datetime
```

- [ ] **Step 2: Add `custom_values` field to `TargetAggregation` in `backend/app/schemas/target.py`**

Add to the `TargetAggregation` class (after `mosaic_name`):

```python
    custom_values: dict[str, str] | None = None  # slug -> value, target-level only
```

- [ ] **Step 3: Add `custom_values` field to `SessionDetailResponse` in `backend/app/schemas/target.py`**

Add to the `SessionDetailResponse` class (after `rigs`):

```python
    custom_values: list[dict] | None = None  # list of {column_slug, session_date, rig_label, value}
```

- [ ] **Step 4: Add `ColumnVisibility` to `backend/app/schemas/settings.py`**

Add after the `DisplaySettings` class:

```python
class TableColumnVisibility(BaseModel):
    builtin: dict[str, bool] = {}
    custom: dict[str, bool] = {}


class ColumnVisibility(BaseModel):
    dashboard: TableColumnVisibility = TableColumnVisibility()
    session_table: TableColumnVisibility = TableColumnVisibility()
    session_detail: TableColumnVisibility = TableColumnVisibility()
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/custom_column.py backend/app/schemas/target.py backend/app/schemas/settings.py
git commit -m "feat: add custom column schemas and extend target/settings schemas"
```

---

## Task 4: Backend Custom Columns API Router

**Files:**
- Create: `backend/app/api/custom_columns.py`
- Modify: `backend/app/api/router.py`

- [ ] **Step 1: Write tests for custom column CRUD**

Create `backend/tests/test_custom_columns.py`:

```python
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_custom_column(client: AsyncClient, auth_headers: dict):
    resp = await client.post("/api/custom-columns", json={
        "name": "Processed",
        "column_type": "boolean",
        "applies_to": "target",
    }, headers=auth_headers)
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Processed"
    assert data["slug"] == "processed"
    assert data["column_type"] == "boolean"
    assert data["applies_to"] == "target"


@pytest.mark.asyncio
async def test_create_dropdown_column(client: AsyncClient, auth_headers: dict):
    resp = await client.post("/api/custom-columns", json={
        "name": "Processing Status",
        "column_type": "dropdown",
        "applies_to": "session",
        "dropdown_options": ["Not Started", "In Progress", "Done"],
    }, headers=auth_headers)
    assert resp.status_code == 201
    data = resp.json()
    assert data["dropdown_options"] == ["Not Started", "In Progress", "Done"]


@pytest.mark.asyncio
async def test_list_custom_columns(client: AsyncClient, auth_headers: dict):
    # Create two columns
    await client.post("/api/custom-columns", json={
        "name": "Col A", "column_type": "boolean", "applies_to": "target",
    }, headers=auth_headers)
    await client.post("/api/custom-columns", json={
        "name": "Col B", "column_type": "text", "applies_to": "session",
    }, headers=auth_headers)

    resp = await client.get("/api/custom-columns", headers=auth_headers)
    assert resp.status_code == 200
    assert len(resp.json()) >= 2


@pytest.mark.asyncio
async def test_update_custom_column(client: AsyncClient, auth_headers: dict):
    create = await client.post("/api/custom-columns", json={
        "name": "Old Name", "column_type": "text", "applies_to": "target",
    }, headers=auth_headers)
    col_id = create.json()["id"]

    resp = await client.patch(f"/api/custom-columns/{col_id}", json={
        "name": "New Name",
    }, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["name"] == "New Name"
    assert resp.json()["slug"] == "new-name"


@pytest.mark.asyncio
async def test_delete_custom_column(client: AsyncClient, auth_headers: dict):
    create = await client.post("/api/custom-columns", json={
        "name": "To Delete", "column_type": "boolean", "applies_to": "target",
    }, headers=auth_headers)
    col_id = create.json()["id"]

    resp = await client.delete(f"/api/custom-columns/{col_id}", headers=auth_headers)
    assert resp.status_code == 204

    resp = await client.get("/api/custom-columns", headers=auth_headers)
    ids = [c["id"] for c in resp.json()]
    assert col_id not in ids


@pytest.mark.asyncio
async def test_duplicate_name_gets_unique_slug(client: AsyncClient, auth_headers: dict):
    await client.post("/api/custom-columns", json={
        "name": "Status", "column_type": "boolean", "applies_to": "target",
    }, headers=auth_headers)
    resp = await client.post("/api/custom-columns", json={
        "name": "Status", "column_type": "text", "applies_to": "session",
    }, headers=auth_headers)
    assert resp.status_code == 201
    assert resp.json()["slug"] != "status"  # should be deduplicated
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /c/Users/Kumar/git/GalactiLog/backend && pytest tests/test_custom_columns.py -v`
Expected: FAIL — no route registered yet.

- [ ] **Step 3: Create the custom columns router**

```python
# backend/app/api/custom_columns.py
import re
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.api.deps import get_current_user
from app.models.user import User
from app.models.custom_column import CustomColumn, CustomColumnValue, ColumnType, AppliesTo
from app.schemas.custom_column import (
    CustomColumnCreate,
    CustomColumnUpdate,
    CustomColumnResponse,
    CustomColumnValueSet,
    CustomColumnValueResponse,
)

router = APIRouter(prefix="/custom-columns", tags=["custom-columns"])


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "column"


async def _unique_slug(session: AsyncSession, base_slug: str, exclude_id: uuid.UUID | None = None) -> str:
    slug = base_slug
    suffix = 0
    while True:
        q = select(CustomColumn.id).where(CustomColumn.slug == slug)
        if exclude_id:
            q = q.where(CustomColumn.id != exclude_id)
        exists = (await session.execute(q)).scalar_one_or_none()
        if not exists:
            return slug
        suffix += 1
        slug = f"{base_slug}-{suffix}"


@router.get("", response_model=list[CustomColumnResponse])
async def list_custom_columns(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    q = select(CustomColumn).order_by(CustomColumn.display_order, CustomColumn.created_at)
    rows = (await session.execute(q)).scalars().all()
    return [
        CustomColumnResponse(
            id=str(r.id), name=r.name, slug=r.slug,
            column_type=r.column_type.value, applies_to=r.applies_to.value,
            dropdown_options=r.dropdown_options, display_order=r.display_order,
            created_by=str(r.created_by), created_at=r.created_at,
        )
        for r in rows
    ]


@router.post("", response_model=CustomColumnResponse, status_code=status.HTTP_201_CREATED)
async def create_custom_column(
    body: CustomColumnCreate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    base_slug = _slugify(body.name)
    slug = await _unique_slug(session, base_slug)

    # Get next display_order
    max_order = (await session.execute(
        select(func.coalesce(func.max(CustomColumn.display_order), -1))
    )).scalar()

    col = CustomColumn(
        name=body.name,
        slug=slug,
        column_type=ColumnType(body.column_type),
        applies_to=AppliesTo(body.applies_to),
        dropdown_options=body.dropdown_options if body.column_type == "dropdown" else None,
        display_order=max_order + 1,
        created_by=user.id,
    )
    session.add(col)
    await session.commit()
    await session.refresh(col)

    return CustomColumnResponse(
        id=str(col.id), name=col.name, slug=col.slug,
        column_type=col.column_type.value, applies_to=col.applies_to.value,
        dropdown_options=col.dropdown_options, display_order=col.display_order,
        created_by=str(col.created_by), created_at=col.created_at,
    )


@router.patch("/{column_id}", response_model=CustomColumnResponse)
async def update_custom_column(
    column_id: uuid.UUID,
    body: CustomColumnUpdate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    col = await session.get(CustomColumn, column_id)
    if not col:
        raise HTTPException(status_code=404, detail="Column not found")

    if body.name is not None:
        col.name = body.name
        col.slug = await _unique_slug(session, _slugify(body.name), exclude_id=col.id)
    if body.dropdown_options is not None and col.column_type == ColumnType.dropdown:
        col.dropdown_options = body.dropdown_options
    if body.display_order is not None:
        col.display_order = body.display_order

    await session.commit()
    await session.refresh(col)

    return CustomColumnResponse(
        id=str(col.id), name=col.name, slug=col.slug,
        column_type=col.column_type.value, applies_to=col.applies_to.value,
        dropdown_options=col.dropdown_options, display_order=col.display_order,
        created_by=str(col.created_by), created_at=col.created_at,
    )


@router.delete("/{column_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_custom_column(
    column_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    col = await session.get(CustomColumn, column_id)
    if not col:
        raise HTTPException(status_code=404, detail="Column not found")
    await session.delete(col)
    await session.commit()


# --- Values ---

@router.get("/values/{target_id}", response_model=list[CustomColumnValueResponse])
async def get_custom_values(
    target_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    q = (
        select(CustomColumnValue, CustomColumn.slug)
        .join(CustomColumn)
        .where(CustomColumnValue.target_id == target_id)
    )
    rows = (await session.execute(q)).all()
    return [
        CustomColumnValueResponse(
            column_id=str(v.column_id), column_slug=slug,
            target_id=str(v.target_id), session_date=v.session_date,
            rig_label=v.rig_label, value=v.value,
            updated_by=str(v.updated_by), updated_at=v.updated_at,
        )
        for v, slug in rows
    ]


@router.put("/values")
async def set_custom_value(
    body: CustomColumnValueSet,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    col_id = uuid.UUID(body.column_id)
    target_id = uuid.UUID(body.target_id)

    # Check column exists
    col = await session.get(CustomColumn, col_id)
    if not col:
        raise HTTPException(status_code=404, detail="Column not found")

    # Validate value against column type
    if col.column_type == ColumnType.boolean and body.value not in ("true", "false"):
        raise HTTPException(status_code=422, detail="Boolean columns require 'true' or 'false'")
    if col.column_type == ColumnType.dropdown and col.dropdown_options and body.value not in col.dropdown_options:
        raise HTTPException(status_code=422, detail=f"Value must be one of: {col.dropdown_options}")

    # Upsert: find existing or create
    from sqlalchemy import and_
    conditions = [
        CustomColumnValue.column_id == col_id,
        CustomColumnValue.target_id == target_id,
    ]
    if body.session_date is not None:
        conditions.append(CustomColumnValue.session_date == body.session_date)
    else:
        conditions.append(CustomColumnValue.session_date.is_(None))
    if body.rig_label is not None:
        conditions.append(CustomColumnValue.rig_label == body.rig_label)
    else:
        conditions.append(CustomColumnValue.rig_label.is_(None))

    existing = (await session.execute(
        select(CustomColumnValue).where(and_(*conditions))
    )).scalar_one_or_none()

    if existing:
        existing.value = body.value
        existing.updated_by = user.id
    else:
        val = CustomColumnValue(
            column_id=col_id,
            target_id=target_id,
            session_date=body.session_date,
            rig_label=body.rig_label,
            value=body.value,
            updated_by=user.id,
        )
        session.add(val)

    await session.commit()
    return {"ok": True}
```

- [ ] **Step 4: Register the router in `backend/app/api/router.py`**

Add import:
```python
from .custom_columns import router as custom_columns_router
```

Add registration after the mosaics router line:
```python
api_router.include_router(custom_columns_router)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /c/Users/Kumar/git/GalactiLog/backend && pytest tests/test_custom_columns.py -v`
Expected: All tests PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/custom_columns.py backend/app/api/router.py backend/tests/test_custom_columns.py
git commit -m "feat: add custom columns CRUD API with tests"
```

---

## Task 5: Integrate Custom Values into Targets Aggregation

**Files:**
- Modify: `backend/app/api/targets.py:730-1123`

- [ ] **Step 1: Write test for custom values in aggregation response**

Add to `backend/tests/test_custom_columns.py`:

```python
@pytest.mark.asyncio
async def test_aggregation_includes_custom_values(client: AsyncClient, auth_headers: dict, sample_target_id: str):
    # Create a column
    col = await client.post("/api/custom-columns", json={
        "name": "Backed Up", "column_type": "boolean", "applies_to": "target",
    }, headers=auth_headers)
    col_id = col.json()["id"]

    # Set a value
    await client.put("/api/custom-columns/values", json={
        "column_id": col_id, "target_id": sample_target_id, "value": "true",
    }, headers=auth_headers)

    # Fetch aggregation with custom values
    resp = await client.get("/api/targets?include_custom=true", headers=auth_headers)
    assert resp.status_code == 200
    targets = resp.json()["targets"]
    target = next((t for t in targets if t["target_id"] == sample_target_id), None)
    assert target is not None
    assert target["custom_values"]["backed-up"] == "true"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /c/Users/Kumar/git/GalactiLog/backend && pytest tests/test_custom_columns.py::test_aggregation_includes_custom_values -v`
Expected: FAIL — `include_custom` param not recognized or `custom_values` not in response.

- [ ] **Step 3: Add `include_custom` query param and custom value loading to `list_targets_aggregated`**

In `backend/app/api/targets.py`, add the query parameter to the function signature (around line 768):

```python
    include_custom: bool = Query(False),
```

Then in Phase 5 (around line 1078), before the response assembly loop, add:

```python
    # Phase 4c: Custom column values (target-level)
    custom_values_map: dict[str, dict[str, str]] = {}
    if include_custom:
        from app.models.custom_column import CustomColumn, CustomColumnValue, AppliesTo
        cv_q = (
            select(CustomColumnValue.target_id, CustomColumn.slug, CustomColumnValue.value)
            .join(CustomColumn)
            .where(CustomColumn.applies_to == AppliesTo.target)
        )
        cv_rows = (await session.execute(cv_q)).all()
        for tid, slug, val in cv_rows:
            tid_str = str(tid)
            if tid_str not in custom_values_map:
                custom_values_map[tid_str] = {}
            custom_values_map[tid_str][slug] = val
```

Then in the `target_list.append(TargetAggregation(...))` call (around line 1102), add the field:

```python
            custom_values=custom_values_map.get(basics["target_key"]) if include_custom else None,
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /c/Users/Kumar/git/GalactiLog/backend && pytest tests/test_custom_columns.py::test_aggregation_includes_custom_values -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/targets.py backend/app/schemas/target.py backend/tests/test_custom_columns.py
git commit -m "feat: include custom column values in target aggregation response"
```

---

## Task 6: Integrate Custom Values into Session Detail

**Files:**
- Modify: `backend/app/api/targets.py:1198-1511`

- [ ] **Step 1: Write test for custom values in session detail response**

Add to `backend/tests/test_custom_columns.py`:

```python
@pytest.mark.asyncio
async def test_session_detail_includes_custom_values(
    client: AsyncClient, auth_headers: dict, sample_target_id: str, sample_session_date: str,
):
    # Create a session-level column
    col = await client.post("/api/custom-columns", json={
        "name": "Quality Check", "column_type": "dropdown", "applies_to": "session",
        "dropdown_options": ["Pending", "Passed", "Failed"],
    }, headers=auth_headers)
    col_id = col.json()["id"]

    # Set value
    await client.put("/api/custom-columns/values", json={
        "column_id": col_id, "target_id": sample_target_id,
        "session_date": sample_session_date, "value": "Passed",
    }, headers=auth_headers)

    # Fetch session detail
    resp = await client.get(
        f"/api/targets/{sample_target_id}/sessions/{sample_session_date}",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    cv = resp.json()["custom_values"]
    assert any(v["column_slug"] == "quality-check" and v["value"] == "Passed" for v in cv)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /c/Users/Kumar/git/GalactiLog/backend && pytest tests/test_custom_columns.py::test_session_detail_includes_custom_values -v`
Expected: FAIL

- [ ] **Step 3: Add custom value loading to `get_session_detail`**

In `backend/app/api/targets.py`, in the `get_session_detail` function, after the session note fetch (around line 1467) and before the return, add:

```python
    # Fetch custom column values for this session (session + rig level)
    from app.models.custom_column import CustomColumn, CustomColumnValue, AppliesTo
    custom_values_list = None
    if resolved_target_id:
        cv_q = (
            select(CustomColumn.slug, CustomColumnValue.session_date,
                   CustomColumnValue.rig_label, CustomColumnValue.value)
            .join(CustomColumn)
            .where(
                CustomColumnValue.target_id == resolved_target_id,
                CustomColumn.applies_to.in_([AppliesTo.session, AppliesTo.rig]),
                CustomColumnValue.session_date == date_type.fromisoformat(date),
            )
        )
        cv_rows = (await session.execute(cv_q)).all()
        if cv_rows:
            custom_values_list = [
                {
                    "column_slug": slug,
                    "session_date": str(sd) if sd else None,
                    "rig_label": rl,
                    "value": val,
                }
                for slug, sd, rl, val in cv_rows
            ]
```

Then in the `SessionDetailResponse(...)` constructor, add:

```python
        custom_values=custom_values_list,
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /c/Users/Kumar/git/GalactiLog/backend && pytest tests/test_custom_columns.py::test_session_detail_includes_custom_values -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/targets.py backend/tests/test_custom_columns.py
git commit -m "feat: include custom column values in session detail response"
```

---

## Task 7: Column Visibility in Settings

**Files:**
- Modify: `backend/app/api/settings.py`
- Modify: `backend/app/schemas/settings.py`

- [ ] **Step 1: Add column visibility endpoint**

The column visibility is per-user and stored in `UserSettings.display` JSONB. Since the current `UserSettings` model is a singleton (one row), and the design says visibility is per-user, we need to store it differently. The simplest approach: add a `column_visibility` JSONB column to the `users` table, or store it as a separate key in the display settings keyed by user ID. 

Given the current singleton pattern, the cleanest approach is to add a `PUT /settings/column-visibility` endpoint that stores the data in the existing `display` JSONB under a `column_visibility` key.

In `backend/app/schemas/settings.py`, after the `ColumnVisibility` class added in Task 3, add:

```python
class ColumnVisibilityUpdate(BaseModel):
    column_visibility: ColumnVisibility
```

In `backend/app/api/settings.py`, add a new endpoint:

```python
from app.schemas.settings import ColumnVisibility

@router.get("/column-visibility/{user_id}")
async def get_column_visibility(
    user_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    # Only allow reading own visibility
    if user.id != user_id:
        raise HTTPException(status_code=403, detail="Forbidden")
    row = await _get_or_create_settings(session)
    all_vis = row.display.get("column_visibility_per_user", {})
    user_vis = all_vis.get(str(user_id), {})
    return user_vis


@router.put("/column-visibility")
async def update_column_visibility(
    payload: ColumnVisibility,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    row = await _get_or_create_settings(session)
    display = dict(row.display) if row.display else {}
    per_user = display.get("column_visibility_per_user", {})
    per_user[str(user.id)] = payload.model_dump()
    display["column_visibility_per_user"] = per_user
    row.display = display
    await session.commit()
    return {"ok": True}
```

Add the needed import at the top of `backend/app/api/settings.py`:

```python
import uuid
from fastapi import HTTPException
```

- [ ] **Step 2: Verify endpoint works**

Run: `cd /c/Users/Kumar/git/GalactiLog/backend && pytest -v -k "settings"` (to ensure existing settings tests still pass)
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add backend/app/api/settings.py backend/app/schemas/settings.py
git commit -m "feat: add per-user column visibility endpoints"
```

---

## Task 8: Frontend Types

**Files:**
- Modify: `frontend/src/types/index.ts`

- [ ] **Step 1: Add custom column types**

Add to `frontend/src/types/index.ts`:

```typescript
// Custom Columns
export interface CustomColumn {
  id: string;
  name: string;
  slug: string;
  column_type: "boolean" | "text" | "dropdown";
  applies_to: "target" | "session" | "rig";
  dropdown_options: string[] | null;
  display_order: number;
  created_by: string;
  created_at: string;
}

export interface CustomColumnValue {
  column_slug: string;
  session_date: string | null;
  rig_label: string | null;
  value: string;
}

export interface TableColumnVisibility {
  builtin: Record<string, boolean>;
  custom: Record<string, boolean>;
}

export interface ColumnVisibility {
  dashboard: TableColumnVisibility;
  session_table: TableColumnVisibility;
  session_detail: TableColumnVisibility;
}
```

Also update `TargetAggregation` to include the optional `custom_values`:

```typescript
  custom_values?: Record<string, string> | null;
```

And update `SessionDetail` to include:

```typescript
  custom_values?: CustomColumnValue[] | null;
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/types/index.ts
git commit -m "feat: add custom column TypeScript types"
```

---

## Task 9: Frontend API Client

**Files:**
- Modify: `frontend/src/api/client.ts`

- [ ] **Step 1: Add custom column API methods**

Add to the API client object in `frontend/src/api/client.ts`:

```typescript
  // Custom Columns
  async getCustomColumns(): Promise<CustomColumn[]> {
    const resp = await this.fetch("/custom-columns");
    return resp.json();
  },

  async createCustomColumn(body: {
    name: string;
    column_type: string;
    applies_to: string;
    dropdown_options?: string[];
  }): Promise<CustomColumn> {
    const resp = await this.fetch("/custom-columns", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    return resp.json();
  },

  async updateCustomColumn(id: string, body: {
    name?: string;
    dropdown_options?: string[];
    display_order?: number;
  }): Promise<CustomColumn> {
    const resp = await this.fetch(`/custom-columns/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    return resp.json();
  },

  async deleteCustomColumn(id: string): Promise<void> {
    await this.fetch(`/custom-columns/${id}`, { method: "DELETE" });
  },

  async getCustomValues(targetId: string): Promise<CustomColumnValue[]> {
    const resp = await this.fetch(`/custom-columns/values/${targetId}`);
    return resp.json();
  },

  async setCustomValue(body: {
    column_id: string;
    target_id: string;
    session_date?: string | null;
    rig_label?: string | null;
    value: string;
  }): Promise<void> {
    await this.fetch("/custom-columns/values", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  },

  async getColumnVisibility(userId: string): Promise<ColumnVisibility> {
    const resp = await this.fetch(`/settings/column-visibility/${userId}`);
    return resp.json();
  },

  async updateColumnVisibility(body: ColumnVisibility): Promise<void> {
    await this.fetch("/settings/column-visibility", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  },
```

Add the import for the new types at the top:

```typescript
import type { CustomColumn, CustomColumnValue, ColumnVisibility } from "../types";
```

- [ ] **Step 2: Update `getTargets` to pass `include_custom=true`**

In the `buildTargetQuery` function, add `include_custom=true` to the query string:

```typescript
params.append("include_custom=true");
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/client.ts
git commit -m "feat: add custom column API client methods"
```

---

## Task 10: Custom Columns Settings Tab

**Files:**
- Create: `frontend/src/components/CustomColumnsTab.tsx`
- Modify: `frontend/src/pages/SettingsPage.tsx`

- [ ] **Step 1: Create the CustomColumnsTab component**

```typescript
// frontend/src/components/CustomColumnsTab.tsx
import { createSignal, createResource, For, Show } from "solid-js";
import api from "../api/client";
import type { CustomColumn } from "../types";

export default function CustomColumnsTab() {
  const [columns, { refetch }] = createResource(() => api.getCustomColumns());
  const [newName, setNewName] = createSignal("");
  const [newType, setNewType] = createSignal<"boolean" | "text" | "dropdown">("boolean");
  const [newAppliesTo, setNewAppliesTo] = createSignal<"target" | "session" | "rig">("target");
  const [newOptions, setNewOptions] = createSignal("");
  const [editingId, setEditingId] = createSignal<string | null>(null);
  const [editName, setEditName] = createSignal("");
  const [editOptions, setEditOptions] = createSignal("");

  async function handleCreate() {
    const name = newName().trim();
    if (!name) return;
    const body: Parameters<typeof api.createCustomColumn>[0] = {
      name,
      column_type: newType(),
      applies_to: newAppliesTo(),
    };
    if (newType() === "dropdown") {
      body.dropdown_options = newOptions().split(",").map((s) => s.trim()).filter(Boolean);
    }
    await api.createCustomColumn(body);
    setNewName("");
    setNewOptions("");
    refetch();
  }

  async function handleDelete(id: string) {
    if (!confirm("Delete this column and all its values?")) return;
    await api.deleteCustomColumn(id);
    refetch();
  }

  function startEdit(col: CustomColumn) {
    setEditingId(col.id);
    setEditName(col.name);
    setEditOptions(col.dropdown_options?.join(", ") ?? "");
  }

  async function handleSaveEdit(col: CustomColumn) {
    const updates: Parameters<typeof api.updateCustomColumn>[1] = {};
    const name = editName().trim();
    if (name && name !== col.name) updates.name = name;
    if (col.column_type === "dropdown") {
      updates.dropdown_options = editOptions().split(",").map((s) => s.trim()).filter(Boolean);
    }
    await api.updateCustomColumn(col.id, updates);
    setEditingId(null);
    refetch();
  }

  async function moveColumn(col: CustomColumn, direction: -1 | 1) {
    await api.updateCustomColumn(col.id, { display_order: col.display_order + direction });
    refetch();
  }

  return (
    <div class="space-y-6">
      <h3 class="text-lg font-semibold">Custom Columns</h3>
      <p class="text-sm text-[var(--text-secondary)]">
        Define custom columns that appear in the dashboard and session tables.
        All users share the same column definitions and values.
      </p>

      {/* Create Form */}
      <div class="rounded-lg border border-[var(--border)] p-4 space-y-3">
        <h4 class="font-medium">Add Column</h4>
        <div class="flex flex-wrap gap-3 items-end">
          <div>
            <label class="block text-xs mb-1">Name</label>
            <input
              type="text"
              value={newName()}
              onInput={(e) => setNewName(e.currentTarget.value)}
              class="px-2 py-1 rounded border border-[var(--border)] bg-[var(--bg-secondary)] text-sm"
              placeholder="e.g. Processed"
            />
          </div>
          <div>
            <label class="block text-xs mb-1">Type</label>
            <select
              value={newType()}
              onChange={(e) => setNewType(e.currentTarget.value as any)}
              class="px-2 py-1 rounded border border-[var(--border)] bg-[var(--bg-secondary)] text-sm"
            >
              <option value="boolean">Boolean</option>
              <option value="text">Text</option>
              <option value="dropdown">Dropdown</option>
            </select>
          </div>
          <div>
            <label class="block text-xs mb-1">Applies To</label>
            <select
              value={newAppliesTo()}
              onChange={(e) => setNewAppliesTo(e.currentTarget.value as any)}
              class="px-2 py-1 rounded border border-[var(--border)] bg-[var(--bg-secondary)] text-sm"
            >
              <option value="target">Target</option>
              <option value="session">Session</option>
              <option value="rig">Rig</option>
            </select>
          </div>
          <Show when={newType() === "dropdown"}>
            <div>
              <label class="block text-xs mb-1">Options (comma-separated)</label>
              <input
                type="text"
                value={newOptions()}
                onInput={(e) => setNewOptions(e.currentTarget.value)}
                class="px-2 py-1 rounded border border-[var(--border)] bg-[var(--bg-secondary)] text-sm"
                placeholder="e.g. Pending, Done, Failed"
              />
            </div>
          </Show>
          <button
            onClick={handleCreate}
            class="px-3 py-1 rounded bg-[var(--accent)] text-white text-sm hover:opacity-90"
          >
            Add
          </button>
        </div>
      </div>

      {/* Existing Columns */}
      <Show when={columns()?.length} fallback={<p class="text-sm text-[var(--text-secondary)]">No custom columns defined yet.</p>}>
        <table class="w-full text-sm">
          <thead>
            <tr class="border-b border-[var(--border)] text-left text-[var(--text-secondary)]">
              <th class="py-2 px-2">Order</th>
              <th class="py-2 px-2">Name</th>
              <th class="py-2 px-2">Type</th>
              <th class="py-2 px-2">Applies To</th>
              <th class="py-2 px-2">Options</th>
              <th class="py-2 px-2">Actions</th>
            </tr>
          </thead>
          <tbody>
            <For each={columns()}>
              {(col) => (
                <tr class="border-b border-[var(--border)]">
                  <td class="py-2 px-2">
                    <div class="flex gap-1">
                      <button onClick={() => moveColumn(col, -1)} class="text-xs hover:text-[var(--accent)]" title="Move up">^</button>
                      <button onClick={() => moveColumn(col, 1)} class="text-xs hover:text-[var(--accent)]" title="Move down">v</button>
                    </div>
                  </td>
                  <td class="py-2 px-2">
                    <Show when={editingId() === col.id} fallback={col.name}>
                      <input
                        type="text"
                        value={editName()}
                        onInput={(e) => setEditName(e.currentTarget.value)}
                        class="px-1 py-0.5 rounded border border-[var(--border)] bg-[var(--bg-secondary)] text-sm w-full"
                      />
                    </Show>
                  </td>
                  <td class="py-2 px-2 capitalize">{col.column_type}</td>
                  <td class="py-2 px-2 capitalize">{col.applies_to}</td>
                  <td class="py-2 px-2">
                    <Show when={editingId() === col.id && col.column_type === "dropdown"} fallback={col.dropdown_options?.join(", ") ?? "-"}>
                      <input
                        type="text"
                        value={editOptions()}
                        onInput={(e) => setEditOptions(e.currentTarget.value)}
                        class="px-1 py-0.5 rounded border border-[var(--border)] bg-[var(--bg-secondary)] text-sm w-full"
                      />
                    </Show>
                  </td>
                  <td class="py-2 px-2">
                    <div class="flex gap-2">
                      <Show
                        when={editingId() === col.id}
                        fallback={
                          <button onClick={() => startEdit(col)} class="text-xs text-[var(--accent)] hover:underline">Edit</button>
                        }
                      >
                        <button onClick={() => handleSaveEdit(col)} class="text-xs text-green-500 hover:underline">Save</button>
                        <button onClick={() => setEditingId(null)} class="text-xs text-[var(--text-secondary)] hover:underline">Cancel</button>
                      </Show>
                      <button onClick={() => handleDelete(col.id)} class="text-xs text-red-500 hover:underline">Delete</button>
                    </div>
                  </td>
                </tr>
              )}
            </For>
          </tbody>
        </table>
      </Show>
    </div>
  );
}
```

- [ ] **Step 2: Add the tab to SettingsPage**

In `frontend/src/pages/SettingsPage.tsx`, add to the `ALL_TABS` array:

```typescript
  { id: "custom-columns", label: "Custom Columns" },
```

Add the import:

```typescript
import CustomColumnsTab from "../components/CustomColumnsTab";
```

Add the tab content render (alongside the other `<Show>` blocks):

```tsx
<Show when={activeTab() === "custom-columns"}>
  <CustomColumnsTab />
</Show>
```

- [ ] **Step 3: Verify the tab renders**

Run: `cd /c/Users/Kumar/git/GalactiLog/frontend && npm run dev`
Navigate to Settings -> Custom Columns tab. Verify the create form renders.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/CustomColumnsTab.tsx frontend/src/pages/SettingsPage.tsx
git commit -m "feat: add Custom Columns settings tab"
```

---

## Task 11: InlineEditCell Component

**Files:**
- Create: `frontend/src/components/InlineEditCell.tsx`

- [ ] **Step 1: Create the inline edit cell component**

```typescript
// frontend/src/components/InlineEditCell.tsx
import { createSignal, Show } from "solid-js";

interface Props {
  columnType: "boolean" | "text" | "dropdown";
  value: string | undefined;
  dropdownOptions?: string[] | null;
  onSave: (value: string) => void;
}

export default function InlineEditCell(props: Props) {
  const [editing, setEditing] = createSignal(false);
  const [draft, setDraft] = createSignal("");

  function startEdit() {
    setDraft(props.value ?? "");
    setEditing(true);
  }

  function save() {
    props.onSave(draft());
    setEditing(false);
  }

  function handleKeyDown(e: KeyboardEvent) {
    if (e.key === "Enter") save();
    if (e.key === "Escape") setEditing(false);
  }

  // Boolean: simple checkbox, no edit mode needed
  if (props.columnType === "boolean") {
    return (
      <input
        type="checkbox"
        checked={props.value === "true"}
        onChange={(e) => props.onSave(e.currentTarget.checked ? "true" : "false")}
        class="cursor-pointer"
      />
    );
  }

  // Dropdown: always shows select
  if (props.columnType === "dropdown") {
    return (
      <select
        value={props.value ?? ""}
        onChange={(e) => props.onSave(e.currentTarget.value)}
        class="px-1 py-0.5 rounded border border-[var(--border)] bg-transparent text-sm"
      >
        <option value="">-</option>
        {props.dropdownOptions?.map((opt) => (
          <option value={opt}>{opt}</option>
        ))}
      </select>
    );
  }

  // Text: click-to-edit
  return (
    <Show
      when={editing()}
      fallback={
        <span
          onClick={startEdit}
          class="cursor-pointer min-w-[2rem] inline-block hover:bg-[var(--bg-secondary)] rounded px-1"
          title="Click to edit"
        >
          {props.value || "-"}
        </span>
      }
    >
      <input
        type="text"
        value={draft()}
        onInput={(e) => setDraft(e.currentTarget.value)}
        onBlur={save}
        onKeyDown={handleKeyDown}
        class="px-1 py-0.5 rounded border border-[var(--border)] bg-transparent text-sm w-full"
        autofocus
      />
    </Show>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/InlineEditCell.tsx
git commit -m "feat: add InlineEditCell component for custom column values"
```

---

## Task 12: Column Visibility Helpers

**Files:**
- Modify: `frontend/src/utils/displaySettings.ts`
- Modify: `frontend/src/components/SettingsProvider.tsx`

- [ ] **Step 1: Add column visibility helper functions**

Add to `frontend/src/utils/displaySettings.ts`:

```typescript
import type { ColumnVisibility, TableColumnVisibility } from "../types";

export function isColumnVisible(
  visibility: ColumnVisibility | undefined,
  table: keyof ColumnVisibility,
  kind: "builtin" | "custom",
  key: string,
): boolean {
  if (!visibility) return true; // default: all visible
  const tableVis = visibility[table];
  if (!tableVis) return true;
  const section = tableVis[kind];
  if (!section || !(key in section)) return true; // default visible if not set
  return section[key];
}
```

- [ ] **Step 2: Add custom columns and column visibility to SettingsProvider**

In `frontend/src/components/SettingsProvider.tsx`, add to the context:

```typescript
customColumns: Resource<CustomColumn[] | undefined>;
refetchCustomColumns: () => void;
columnVisibility: () => ColumnVisibility | undefined;
saveColumnVisibility: (vis: ColumnVisibility) => Promise<void>;
```

Add the resource and methods in the provider:

```typescript
const [customColumns, { refetch: refetchCustomColumns }] = createResource(() => api.getCustomColumns());

// Column visibility stored locally until we have the user ID
const [columnVisibility, setColumnVisibility] = createSignal<ColumnVisibility | undefined>(undefined);

// Load column visibility when user is available
// (The user context would need to provide the user ID — fetch from /api/auth/me or similar)

async function saveColumnVisibility(vis: ColumnVisibility) {
  await api.updateColumnVisibility(vis);
  setColumnVisibility(vis);
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/utils/displaySettings.ts frontend/src/components/SettingsProvider.tsx
git commit -m "feat: add column visibility helpers and context"
```

---

## Task 13: ColumnPicker Component

**Files:**
- Create: `frontend/src/components/ColumnPicker.tsx`

- [ ] **Step 1: Create the ColumnPicker popover**

```typescript
// frontend/src/components/ColumnPicker.tsx
import { createSignal, For, Show } from "solid-js";
import type { CustomColumn, ColumnVisibility } from "../types";
import { isColumnVisible } from "../utils/displaySettings";

interface BuiltinColumn {
  key: string;
  label: string;
  alwaysVisible?: boolean;
}

interface Props {
  table: keyof ColumnVisibility;
  builtinColumns: BuiltinColumn[];
  customColumns: CustomColumn[];
  visibility: ColumnVisibility | undefined;
  onToggle: (kind: "builtin" | "custom", key: string, visible: boolean) => void;
}

export default function ColumnPicker(props: Props) {
  const [open, setOpen] = createSignal(false);

  return (
    <div class="relative inline-block">
      <button
        onClick={() => setOpen(!open())}
        class="p-1 rounded hover:bg-[var(--bg-secondary)] text-[var(--text-secondary)]"
        title="Configure columns"
      >
        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 6V4m0 2a2 2 0 100 4m0-4a2 2 0 110 4m-6 8a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4m6 6v10m6-2a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4" />
        </svg>
      </button>

      <Show when={open()}>
        <div
          class="absolute right-0 top-full mt-1 z-50 bg-[var(--bg-primary)] border border-[var(--border)] rounded-lg shadow-lg p-3 min-w-[200px]"
          onClick={(e) => e.stopPropagation()}
        >
          <div class="text-xs font-semibold text-[var(--text-secondary)] mb-2">Built-in</div>
          <For each={props.builtinColumns}>
            {(col) => (
              <label class="flex items-center gap-2 py-0.5 text-sm">
                <input
                  type="checkbox"
                  checked={col.alwaysVisible || isColumnVisible(props.visibility, props.table, "builtin", col.key)}
                  disabled={col.alwaysVisible}
                  onChange={(e) => props.onToggle("builtin", col.key, e.currentTarget.checked)}
                />
                {col.label}
              </label>
            )}
          </For>

          <Show when={props.customColumns.length > 0}>
            <div class="text-xs font-semibold text-[var(--text-secondary)] mt-3 mb-2">Custom</div>
            <For each={props.customColumns}>
              {(col) => (
                <label class="flex items-center gap-2 py-0.5 text-sm">
                  <input
                    type="checkbox"
                    checked={isColumnVisible(props.visibility, props.table, "custom", col.slug)}
                    onChange={(e) => props.onToggle("custom", col.slug, e.currentTarget.checked)}
                  />
                  {col.name}
                </label>
              )}
            </For>
          </Show>

          <button
            onClick={() => setOpen(false)}
            class="mt-2 text-xs text-[var(--text-secondary)] hover:underline w-full text-right"
          >
            Close
          </button>
        </div>
      </Show>
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/ColumnPicker.tsx
git commit -m "feat: add ColumnPicker popover component"
```

---

## Task 14: Dashboard Table — Custom Columns + Visibility

**Files:**
- Modify: `frontend/src/components/TargetTable.tsx`
- Modify: `frontend/src/components/TargetRow.tsx` (or equivalent row component)

- [ ] **Step 1: Add ColumnPicker and custom column headers to TargetTable**

In `frontend/src/components/TargetTable.tsx`, import the new components and context:

```typescript
import ColumnPicker from "./ColumnPicker";
import { isColumnVisible } from "../utils/displaySettings";
import { useSettingsContext } from "./SettingsProvider";
```

Add the column picker button in the header row (next to the last header cell):

```tsx
<ColumnPicker
  table="dashboard"
  builtinColumns={[
    { key: "name", label: "Target Name", alwaysVisible: true },
    { key: "designation", label: "Designation" },
    { key: "palette", label: "Palette" },
    { key: "integration", label: "Integration Time" },
    { key: "equipment", label: "Equipment Profile" },
    { key: "last_session", label: "Last Session" },
  ]}
  customColumns={ctx.customColumns() ?? []}
  visibility={ctx.columnVisibility()}
  onToggle={handleColumnToggle}
/>
```

Wrap each existing `<th>` and corresponding `<td>` in the row component with visibility checks:

```tsx
<Show when={isColumnVisible(vis, "dashboard", "builtin", "designation")}>
  <th>Designation</th>
</Show>
```

Add custom column headers after the built-in ones:

```tsx
<For each={(ctx.customColumns() ?? []).filter(c => c.applies_to === "target")}>
  {(col) => (
    <Show when={isColumnVisible(vis, "dashboard", "custom", col.slug)}>
      <th class="py-2 px-3 text-right">{col.name}</th>
    </Show>
  )}
</For>
```

- [ ] **Step 2: Render custom column values in TargetRow**

In the target row component, add custom column cells after the built-in cells:

```tsx
<For each={(ctx.customColumns() ?? []).filter(c => c.applies_to === "target")}>
  {(col) => (
    <Show when={isColumnVisible(vis, "dashboard", "custom", col.slug)}>
      <td class="py-2 px-3 text-right">
        <InlineEditCell
          columnType={col.column_type}
          value={target.custom_values?.[col.slug]}
          dropdownOptions={col.dropdown_options}
          onSave={(val) => api.setCustomValue({
            column_id: col.id,
            target_id: target.target_id,
            value: val,
          })}
        />
      </td>
    </Show>
  )}
</For>
```

- [ ] **Step 3: Add the `handleColumnToggle` function**

```typescript
function handleColumnToggle(kind: "builtin" | "custom", key: string, visible: boolean) {
  const vis = ctx.columnVisibility() ?? { dashboard: { builtin: {}, custom: {} }, session_table: { builtin: {}, custom: {} }, session_detail: { builtin: {}, custom: {} } };
  const updated = { ...vis };
  updated.dashboard = { ...updated.dashboard };
  updated.dashboard[kind] = { ...updated.dashboard[kind], [key]: visible };
  ctx.saveColumnVisibility(updated);
}
```

- [ ] **Step 4: Verify the dashboard renders with custom columns**

Run the frontend dev server and navigate to the dashboard. Create a custom column in Settings, verify it appears in the dashboard table. Toggle visibility via the column picker.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/TargetTable.tsx frontend/src/components/TargetRow.tsx
git commit -m "feat: add custom columns and column visibility to dashboard table"
```

---

## Task 15: Session Table — Custom Columns + Visibility

**Files:**
- Modify: `frontend/src/components/SessionTable.tsx`

- [ ] **Step 1: Add custom columns to SessionTable**

Same pattern as Task 14 but for `session_table`. Add ColumnPicker to the header area. Add custom column headers for `applies_to === "session"` columns. Session-level values come from the session detail or need a separate fetch.

Since `SessionTable` shows `SessionSummary` rows (which don't have custom values in the aggregation response), the inline edit cells will need to call `api.setCustomValue` with the `session_date` and `target_id`.

Add after the existing header cells:

```tsx
<For each={(ctx.customColumns() ?? []).filter(c => c.applies_to === "session")}>
  {(col) => (
    <Show when={isColumnVisible(vis, "session_table", "custom", col.slug)}>
      <th class="py-1 px-2 text-right text-xs">{col.name}</th>
    </Show>
  )}
</For>
```

Add in each session row (the values will need to be fetched or passed through). For simplicity, the session row can call the values API lazily or the parent can pass them down.

- [ ] **Step 2: Verify session table renders**

Navigate to a target's session list. Verify custom session columns appear and are editable.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/SessionTable.tsx
git commit -m "feat: add custom columns and column visibility to session table"
```

---

## Task 16: Session Detail — Rig-Level Custom Columns

**Files:**
- Modify: `frontend/src/components/SessionAccordionCard.tsx`

- [ ] **Step 1: Add rig-level custom columns to SessionAccordionCard**

In the multi-rig section of `SessionAccordionCard.tsx` (around where per-rig metrics are displayed), add custom column cells for `applies_to === "rig"` columns.

The `custom_values` from the session detail response includes rig-level values with `rig_label` set. Filter to match:

```tsx
<For each={(ctx.customColumns() ?? []).filter(c => c.applies_to === "rig")}>
  {(col) => {
    const val = () => detail()?.custom_values?.find(
      cv => cv.column_slug === col.slug && cv.rig_label === rig.rig_label
    );
    return (
      <div class="flex items-center gap-2 text-sm">
        <span class="text-[var(--text-secondary)]">{col.name}:</span>
        <InlineEditCell
          columnType={col.column_type}
          value={val()?.value}
          dropdownOptions={col.dropdown_options}
          onSave={(v) => api.setCustomValue({
            column_id: col.id,
            target_id: targetId,
            session_date: detail()?.session_date,
            rig_label: rig.rig_label,
            value: v,
          })}
        />
      </div>
    );
  }}
</For>
```

Also add session-level custom columns in the session summary section (not per-rig):

```tsx
<For each={(ctx.customColumns() ?? []).filter(c => c.applies_to === "session")}>
  {(col) => {
    const val = () => detail()?.custom_values?.find(
      cv => cv.column_slug === col.slug && !cv.rig_label
    );
    return (
      <div class="flex items-center gap-2 text-sm">
        <span class="text-[var(--text-secondary)]">{col.name}:</span>
        <InlineEditCell
          columnType={col.column_type}
          value={val()?.value}
          dropdownOptions={col.dropdown_options}
          onSave={(v) => api.setCustomValue({
            column_id: col.id,
            target_id: targetId,
            session_date: detail()?.session_date,
            value: v,
          })}
        />
      </div>
    );
  }}
</For>
```

- [ ] **Step 2: Verify rig-level custom columns render**

Expand a multi-rig session. Verify rig-level custom columns appear per rig and are editable.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/SessionAccordionCard.tsx
git commit -m "feat: add session and rig-level custom columns to session detail"
```

---

## Task 17: End-to-End Verification

- [ ] **Step 1: Run backend tests**

Run: `cd /c/Users/Kumar/git/GalactiLog/backend && pytest -v`
Expected: All tests PASS.

- [ ] **Step 2: Run frontend build**

Run: `cd /c/Users/Kumar/git/GalactiLog/frontend && npm run build`
Expected: Build succeeds with no TypeScript errors.

- [ ] **Step 3: Manual smoke test**

1. Start full stack: `docker-compose up`
2. Go to Settings -> Custom Columns -> Create "Processed" (boolean, target)
3. Go to Settings -> Custom Columns -> Create "QC Status" (dropdown, session, options: Pending/Passed/Failed)
4. Go to Settings -> Custom Columns -> Create "Rig Calibrated" (boolean, rig)
5. Dashboard: Verify "Processed" column appears, toggle checkbox on a target
6. Dashboard: Click column picker, hide "Equipment Profile", verify it disappears
7. Session table: Verify "QC Status" column appears, set a value
8. Session detail: Expand a multi-rig session, verify "Rig Calibrated" appears per rig
9. Column picker: Hide a custom column, verify it disappears

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "feat: custom columns and column visibility — complete feature"
```
