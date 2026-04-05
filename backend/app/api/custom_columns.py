import re
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, func, and_
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

    col = await session.get(CustomColumn, col_id)
    if not col:
        raise HTTPException(status_code=404, detail="Column not found")

    if col.column_type == ColumnType.boolean and body.value not in ("true", "false"):
        raise HTTPException(status_code=422, detail="Boolean columns require 'true' or 'false'")
    if col.column_type == ColumnType.dropdown and col.dropdown_options and body.value not in col.dropdown_options:
        raise HTTPException(status_code=422, detail=f"Value must be one of: {col.dropdown_options}")

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
