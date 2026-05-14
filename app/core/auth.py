"""RBAC middleware and API Key authentication.

Validates: Requirements 16.2, 18.7

Roles:
- Planner: 确认/微调/否决方案
- Shop_Floor_Executor: 仅查看
- Management: 查看 + 审批 P1 级异常
- IT_Admin: 全部权限
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader
from pydantic import BaseModel

from app.core.config import settings

# ── Roles ───────────────────────────────────────────────────────────


class Role(str, Enum):
    PLANNER = "Planner"
    SHOP_FLOOR_EXECUTOR = "Shop_Floor_Executor"
    MANAGEMENT = "Management"
    IT_ADMIN = "IT_Admin"


# ── API Key scheme ──────────────────────────────────────────────────

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

class APIKeyRecord(BaseModel):
    user_id: str
    role: Role
    username: str
    display_name: str
    api_key: str


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    api_key: str
    user: "CurrentUser"


def _parse_auth_users() -> tuple[dict[str, APIKeyRecord], dict[str, tuple[str, APIKeyRecord]]]:
    api_keys: dict[str, APIKeyRecord] = {}
    credentials: dict[str, tuple[str, APIKeyRecord]] = {}

    for item in settings.auth.users.split(","):
        parts = [p.strip() for p in item.split(":")]
        if len(parts) < 5:
            continue
        username, password, user_id, role_name, api_key = parts[:5]
        display_name = parts[5] if len(parts) >= 6 and parts[5] else username
        role = Role(role_name)
        record = APIKeyRecord(
            user_id=user_id,
            role=role,
            username=username,
            display_name=display_name,
            api_key=api_key,
        )
        api_keys[api_key] = record
        credentials[username] = (password, record)

    return api_keys, credentials


_API_KEY_STORE, _CREDENTIAL_STORE = _parse_auth_users()


# ── Current user dependency ─────────────────────────────────────────


class CurrentUser(BaseModel):
    user_id: str
    role: Role
    username: str = "system"
    display_name: str = "System"


async def get_current_user(
    api_key: Annotated[str | None, Security(_api_key_header)] = None,
) -> CurrentUser:
    """Resolve the current user from the X-API-Key header."""
    if api_key is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-API-Key header",
        )
    record = _API_KEY_STORE.get(api_key)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )
    return CurrentUser(
        user_id=record.user_id,
        role=record.role,
        username=record.username,
        display_name=record.display_name,
    )


async def get_optional_current_user(
    api_key: Annotated[str | None, Security(_api_key_header)] = None,
) -> CurrentUser:
    """Resolve current user when available, otherwise return a system user.

    This keeps local MVP endpoints usable while still allowing production API
    callers to attach auditable role/user context with ``X-API-Key``.
    """
    if api_key is None:
        return CurrentUser(user_id="system", role=Role.IT_ADMIN)
    record = _API_KEY_STORE.get(api_key)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )
    return CurrentUser(
        user_id=record.user_id,
        role=record.role,
        username=record.username,
        display_name=record.display_name,
    )


async def authenticate_user(username: str, password: str) -> LoginResponse:
    """Validate PoC credentials and return an API key-backed session."""
    stored = _CREDENTIAL_STORE.get(username)
    if stored is None or stored[0] != password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )
    record = stored[1]
    return LoginResponse(
        api_key=record.api_key,
        user=CurrentUser(
            user_id=record.user_id,
            role=record.role,
            username=record.username,
            display_name=record.display_name,
        ),
    )


# ── Role-based access dependency factory ────────────────────────────


def require_role(*allowed_roles: Role):
    """Dependency factory that restricts access to specific roles.

    Usage::

        @router.post("/confirm", dependencies=[Depends(require_role(Role.PLANNER, Role.IT_ADMIN))])
        async def confirm_plan(...): ...
    """

    async def _check_role(
        current_user: Annotated[CurrentUser, Depends(get_current_user)],
    ) -> CurrentUser:
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{current_user.role.value}' is not permitted. "
                f"Required: {[r.value for r in allowed_roles]}",
            )
        return current_user

    return _check_role
