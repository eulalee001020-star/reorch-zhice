"""Authentication API endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.auth import (
    CurrentUser,
    LoginRequest,
    LoginResponse,
    authenticate_user,
    get_current_user,
)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse, summary="登录并获取 API Key")
async def login(body: LoginRequest) -> LoginResponse:
    return await authenticate_user(body.username, body.password)


@router.get("/me", response_model=CurrentUser, summary="查询当前用户上下文")
async def me(current_user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    return current_user
