"""Admin management of public-API keys.

Cookie auth, admin only: every endpoint declares `Depends(require_admin)`
itself, following the project's per-endpoint auth convention (there is no
global middleware, so an endpoint that omits it is public).

The raw key leaves the server exactly once, in the POST response. Everything
else exposes only the prefix.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin
from app.database import get_session
from app.models.api_key import ApiKey
from app.models.user import User
from app.schemas.api_key import ApiKeyCreateRequest, ApiKeyCreateResponse, ApiKeyResponse
from app.services.activity import emit
from app.services.api_keys import create_api_key, revoke_api_key
from app.services.auth import audit_log
from app.config import client_ip_from_request

router = APIRouter(prefix="/apikeys", tags=["apikeys"])


@router.get("", response_model=list[ApiKeyResponse])
async def list_api_keys(
    session: AsyncSession = Depends(get_session),
    admin: User = Depends(require_admin),
):
    result = await session.execute(select(ApiKey).order_by(ApiKey.created_at))
    return [ApiKeyResponse.model_validate(k) for k in result.scalars().all()]


@router.post("", response_model=ApiKeyCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_key(
    body: ApiKeyCreateRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
    admin: User = Depends(require_admin),
):
    key, raw = await create_api_key(session, body.name, body.can_write)

    audit_log(
        "api_key_create", user_id=admin.id, username=admin.username,
        source_ip=client_ip_from_request(request), success=True,
        detail=f"Created API key {key.prefix} ({body.name})",
    )
    await emit(
        session, category="user_action", severity="info",
        event_type="api_key_created",
        message=f"API key '{key.name}' created", actor=admin.username,
        details={"prefix": key.prefix, "can_write": key.can_write},
    )
    return ApiKeyCreateResponse(
        key=raw,
        id=key.id,
        name=key.name,
        prefix=key.prefix,
        can_write=key.can_write,
        created_at=key.created_at,
    )


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_key(
    key_id: uuid.UUID,
    request: Request,
    session: AsyncSession = Depends(get_session),
    admin: User = Depends(require_admin),
):
    # Read the prefix before revoking: it is what the create audit line
    # records, so logging it here is what lets the two be joined. The commit
    # inside revoke_api_key expires the instance, hence the local copy.
    key = await session.get(ApiKey, key_id)
    if key is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found")
    prefix, name = key.prefix, key.name

    await revoke_api_key(session, key_id)

    audit_log(
        "api_key_revoke", user_id=admin.id, username=admin.username,
        source_ip=client_ip_from_request(request), success=True,
        detail=f"Revoked API key {prefix} ({name})",
    )
    await emit(
        session, category="user_action", severity="warning",
        event_type="api_key_revoked",
        message=f"API key '{name}' revoked", actor=admin.username,
        details={"id": str(key_id), "prefix": prefix},
    )
