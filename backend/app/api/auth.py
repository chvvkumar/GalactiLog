import uuid

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings, limiter, get_async_redis
from app.database import get_session
from app.models.user import User, UserRole
from app.schemas.auth import (
    LoginRequest,
    LoginResponse,
    MeResponse,
    PasswordChangeRequest,
    UserCreateRequest,
    UserResponse,
    UserUpdateRequest,
)
from app.services.auth import (
    audit_log,
    create_access_token,
    generate_refresh_token,
    get_user_by_id,
    get_user_by_username,
    hash_password,
    hash_token,
    revoke_family,
    rotate_refresh_token,
    store_refresh_token,
    verify_password,
    verify_password_timing_safe,
)
from app.api.deps import get_current_user, require_admin

router = APIRouter(prefix="/auth", tags=["auth"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _set_auth_cookies(response: Response, access_token: str, refresh_token: str) -> None:
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        secure=settings.secure_cookies,
        samesite="strict",
        path="/",
    )
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=settings.secure_cookies,
        samesite="strict",
        path="/api/auth/refresh",
    )


def _clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(key="access_token", path="/")
    response.delete_cookie(key="refresh_token", path="/api/auth/refresh")


def _get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def _increment_login_failures(redis, username: str) -> None:
    key = f"auth:failures:{username}"
    failures = await redis.incr(key)
    if failures == 1:
        await redis.expire(key, 900)
    if failures >= 5:
        await redis.setex(f"auth:lockout:{username}", 1800, "locked")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/login", response_model=LoginResponse)
@limiter.limit("20/minute")
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
):
    ip = _get_client_ip(request)

    # Check account lockout
    redis = get_async_redis()
    try:
        locked = await redis.exists(f"auth:lockout:{body.username}")
        if locked:
            audit_log("login", username=body.username, source_ip=ip, success=False, detail="Account locked")
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Account temporarily locked")

        user = await get_user_by_username(session, body.username)

        password_hash = user.password_hash if user else None
        valid = verify_password_timing_safe(body.password, password_hash)

        if not valid or user is None or not user.is_active:
            await _increment_login_failures(redis, body.username)
            audit_log("login", username=body.username, source_ip=ip, success=False, detail="Invalid credentials")
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

        # Successful login — clear failure counter
        await redis.delete(f"auth:failures:{body.username}")
    finally:
        await redis.aclose()

    access = create_access_token(user.id, user.role.value)
    refresh = generate_refresh_token()
    await store_refresh_token(session, user.id, refresh)
    await session.commit()

    _set_auth_cookies(response, access, refresh)
    audit_log("login", user_id=user.id, username=user.username, source_ip=ip, success=True)

    return LoginResponse(username=user.username, role=user.role.value)


@router.post("/refresh")
@limiter.limit("10/minute")
async def refresh(
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
    refresh_token: str | None = Cookie(default=None),
):
    ip = _get_client_ip(request)

    if not refresh_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No refresh token")

    old_rt, was_reuse = await rotate_refresh_token(session, refresh_token)

    if was_reuse:
        await session.commit()
        _clear_auth_cookies(response)
        audit_log("refresh", source_ip=ip, success=False, detail="Token reuse detected — family revoked")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token reuse detected")

    if old_rt is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

    user = await get_user_by_id(session, old_rt.user_id)
    if user is None or not user.is_active:
        await session.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")

    access = create_access_token(user.id, user.role.value)
    new_refresh = generate_refresh_token()
    await store_refresh_token(session, user.id, new_refresh, family_id=old_rt.family_id)
    await session.commit()

    _set_auth_cookies(response, access, new_refresh)
    audit_log("refresh", user_id=user.id, source_ip=ip)
    return {"status": "ok"}


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
    refresh_token: str | None = Cookie(default=None),
):
    ip = _get_client_ip(request)

    if refresh_token:
        from app.models.refresh_token import RefreshToken
        from sqlalchemy import select

        token_hash = hash_token(refresh_token)
        result = await session.execute(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        )
        rt = result.scalar_one_or_none()
        if rt:
            await revoke_family(session, rt.family_id)
            await session.commit()

    _clear_auth_cookies(response)
    audit_log("logout", user_id=user.id, username=user.username, source_ip=ip, success=True)
    return {"status": "ok"}


@router.get("/me", response_model=MeResponse)
async def me(user: User = Depends(get_current_user)):
    return MeResponse(id=user.id, username=user.username, role=user.role.value)


@router.put("/password")
async def change_password(
    body: PasswordChangeRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    ip = _get_client_ip(request)

    if not verify_password(body.current_password, user.password_hash):
        audit_log("password_change", user_id=user.id, username=user.username, source_ip=ip, success=False, detail="Wrong current password")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect")

    user.password_hash = hash_password(body.new_password)
    await session.commit()

    audit_log("password_change", user_id=user.id, username=user.username, source_ip=ip, success=True)
    return {"status": "ok"}


@router.post("/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    body: UserCreateRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
    admin: User = Depends(require_admin),
):
    ip = _get_client_ip(request)

    existing = await get_user_by_username(session, body.username)
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already exists")

    new_user = User(
        username=body.username,
        password_hash=hash_password(body.password),
        role=UserRole(body.role),
    )
    session.add(new_user)
    await session.commit()
    await session.refresh(new_user)

    audit_log("user_create", user_id=admin.id, username=admin.username, source_ip=ip, success=True, detail=f"Created user {body.username}")
    return UserResponse.model_validate(new_user)


@router.put("/users/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: uuid.UUID,
    body: UserUpdateRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
    admin: User = Depends(require_admin),
):
    ip = _get_client_ip(request)

    target_user = await get_user_by_id(session, user_id)
    if target_user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if target_user.id == admin.id:
        if body.is_active is False:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot deactivate yourself")
        if body.role is not None and body.role != admin.role.value:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot change your own role")

    if body.role is not None:
        target_user.role = UserRole(body.role)
    if body.is_active is not None:
        target_user.is_active = body.is_active

    await session.commit()
    await session.refresh(target_user)

    audit_log("user_update", user_id=admin.id, username=admin.username, source_ip=ip, success=True, detail=f"Updated user {target_user.username}")
    return UserResponse.model_validate(target_user)


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: uuid.UUID,
    request: Request,
    session: AsyncSession = Depends(get_session),
    admin: User = Depends(require_admin),
):
    ip = _get_client_ip(request)

    if user_id == admin.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot delete yourself")

    target_user = await get_user_by_id(session, user_id)
    if target_user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    await session.delete(target_user)
    await session.commit()

    audit_log("user_delete", user_id=admin.id, username=admin.username, source_ip=ip, success=True, detail=f"Deleted user {target_user.username}")
