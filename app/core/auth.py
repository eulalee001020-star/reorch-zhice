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

# ── Roles ───────────────────────────────────────────────────────────


class Role(str, Enum):
    PLANNER = "Planner"
    SHOP_FLOOR_EXECUTOR = "Shop_Floor_Executor"
    MANAGEMENT = "Management"
    IT_ADMIN = "IT_Admin"


# ── API Key scheme ──────────────────────────────────────────────────

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

# MVP: in-memory API key → user mapping.
# Replace with DB / external IdP lookup in production.
_API_KEY_STORE: dict[str, "APIKeyRecord"] = {
    "planner-key-001": APIKeyRecord(user_id="planner-1", role=Role.PLANNER)
    if False
    else None,  # populated at module level below
}


class APIKeyRecord(BaseModel):
    user_id: str
    role: Role


# Re-populate after class definition
_API_KEY_STORE = {
    "planner-key-001": APIKeyRecord(user_id="planner-1", role=Role.PLANNER),
    "executor-key-001": APIKeyRecord(
        user_id="executor-1", role=Role.SHOP_FLOOR_EXECUTOR
    ),
    "mgmt-key-001": APIKeyRecord(user_id="mgmt-1", role=Role.MANAGEMENT),
    "admin-key-001": APIKeyRecord(user_id="admin-1", role=Role.IT_ADMIN),
}


# ── Current user dependency ─────────────────────────────────────────


class CurrentUser(BaseModel):
    user_id: str
    role: Role


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
    return CurrentUser(user_id=record.user_id, role=record.role)


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
    return CurrentUser(user_id=record.user_id, role=record.role)


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
