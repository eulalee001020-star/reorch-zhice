"""Layer 5 Case Library & Template Management API endpoints.

Validates: Requirements 9.3, 9.8, 14.1, 14.4

Provides:
- GET  /api/v1/cases — list cases (filter by incident_type, strategy_type, time_range)
- GET  /api/v1/cases/{case_id} — case detail
- GET  /api/v1/case-templates — list templates
- POST /api/v1/case-templates — create template
- PUT  /api/v1/case-templates/{template_id} — edit template
- POST /api/v1/case-templates/{template_id}/publish — publish template
- GET  /api/v1/planners/{planner_id}/preference-profile — query preference profile
"""

from __future__ import annotations

import logging
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.models.case import CaseRecord, CaseTemplate, PreferenceProfile
from app.services.case_library import CaseLibrary
from app.services.case_template_manager import (
    CaseTemplateManager,
    TemplateAlreadyPublishedError,
    TemplateNotFoundError,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["cases"])

# ---------------------------------------------------------------------------
# Shared service instances (MVP in-memory)
# ---------------------------------------------------------------------------
_case_library = CaseLibrary()
_template_manager = CaseTemplateManager()


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class CreateTemplateRequest(BaseModel):
    """Body for POST /case-templates."""

    template_name: str = Field(description="模板名称")
    applicable_incident_types: list[str] = Field(
        default_factory=list, description="适用异常类型列表"
    )
    recommended_strategy: str = Field(description="推荐策略类型")
    key_parameter_thresholds: dict = Field(
        default_factory=dict, description="关键参数阈值"
    )
    created_by: str = Field(description="创建人标识")


class EditTemplateRequest(BaseModel):
    """Body for PUT /case-templates/{template_id}."""

    template_name: str | None = Field(default=None, description="模板名称")
    applicable_incident_types: list[str] | None = Field(
        default=None, description="适用异常类型列表"
    )
    recommended_strategy: str | None = Field(
        default=None, description="推荐策略类型"
    )
    key_parameter_thresholds: dict | None = Field(
        default=None, description="关键参数阈值"
    )


class PublishResponse(BaseModel):
    """Response for template publish."""

    template_id: str
    status: str
    message: str


# ---------------------------------------------------------------------------
# GET /api/v1/cases
# ---------------------------------------------------------------------------


@router.get(
    "/api/v1/cases",
    response_model=list[CaseRecord],
    summary="查询案例列表",
    description="查询历史案例列表，支持按异常类型、策略类型、时间范围、执行结果筛选。",
)
async def list_cases(
    incident_type: str | None = Query(default=None, description="异常类型筛选"),
    strategy_type: str | None = Query(default=None, description="策略类型筛选"),
    time_from: datetime | None = Query(default=None, description="开始时间"),
    time_to: datetime | None = Query(default=None, description="结束时间"),
    is_override: bool | None = Query(default=None, description="是否 Override"),
) -> list[CaseRecord]:
    return _case_library.list_cases(
        incident_type=incident_type,
        strategy_type=strategy_type,
        time_from=time_from,
        time_to=time_to,
        is_override=is_override,
    )


# ---------------------------------------------------------------------------
# GET /api/v1/cases/{case_id}
# ---------------------------------------------------------------------------


@router.get(
    "/api/v1/cases/{case_id}",
    response_model=CaseRecord,
    summary="查询案例详情",
    description="根据 case_id 查询案例完整详情。",
    responses={404: {"description": "案例不存在"}},
)
async def get_case(case_id: UUID) -> CaseRecord:
    case = _case_library.get_case(case_id)
    if case is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Case {case_id} not found.",
        )
    return case


# ---------------------------------------------------------------------------
# GET /api/v1/case-templates
# ---------------------------------------------------------------------------


@router.get(
    "/api/v1/case-templates",
    response_model=list[CaseTemplate],
    summary="查询模板列表",
    description="查询所有案例模板，支持按状态筛选。",
)
async def list_templates(
    template_status: str | None = Query(
        default=None, alias="status", description="模板状态筛选 (draft/published)"
    ),
) -> list[CaseTemplate]:
    return _template_manager.list_templates(status=template_status)


# ---------------------------------------------------------------------------
# POST /api/v1/case-templates
# ---------------------------------------------------------------------------


@router.post(
    "/api/v1/case-templates",
    response_model=CaseTemplate,
    status_code=status.HTTP_201_CREATED,
    summary="创建模板",
    description="创建新的案例模板（草稿状态）。",
)
async def create_template(body: CreateTemplateRequest) -> CaseTemplate:
    return _template_manager.create_template(
        template_name=body.template_name,
        applicable_incident_types=body.applicable_incident_types,
        recommended_strategy=body.recommended_strategy,
        key_parameter_thresholds=body.key_parameter_thresholds,
        created_by=body.created_by,
    )


# ---------------------------------------------------------------------------
# PUT /api/v1/case-templates/{template_id}
# ---------------------------------------------------------------------------


@router.put(
    "/api/v1/case-templates/{template_id}",
    response_model=CaseTemplate,
    summary="编辑模板",
    description="编辑已有模板（仅草稿状态可编辑）。",
    responses={
        400: {"description": "模板已发布，无法编辑"},
        404: {"description": "模板不存在"},
    },
)
async def edit_template(
    template_id: UUID, body: EditTemplateRequest
) -> CaseTemplate:
    try:
        return _template_manager.edit_template(
            template_id=template_id,
            template_name=body.template_name,
            applicable_incident_types=body.applicable_incident_types,
            recommended_strategy=body.recommended_strategy,
            key_parameter_thresholds=body.key_parameter_thresholds,
        )
    except TemplateNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Template {template_id} not found.",
        )
    except TemplateAlreadyPublishedError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Template {template_id} is published. Cannot edit.",
        )


# ---------------------------------------------------------------------------
# POST /api/v1/case-templates/{template_id}/publish
# ---------------------------------------------------------------------------


@router.post(
    "/api/v1/case-templates/{template_id}/publish",
    response_model=PublishResponse,
    summary="发布模板",
    description="发布模板，使其可被 Strategy_Selector 引用。",
    responses={404: {"description": "模板不存在"}},
)
async def publish_template(template_id: UUID) -> PublishResponse:
    try:
        template = _template_manager.publish_template(template_id)
        return PublishResponse(
            template_id=str(template.template_id),
            status=template.status,
            message=f"Template '{template.template_name}' published successfully.",
        )
    except TemplateNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Template {template_id} not found.",
        )


# ---------------------------------------------------------------------------
# GET /api/v1/planners/{planner_id}/preference-profile
# ---------------------------------------------------------------------------


@router.get(
    "/api/v1/planners/{planner_id}/preference-profile",
    response_model=PreferenceProfile,
    summary="查询偏好画像",
    description="查询指定 Planner 的偏好画像。",
)
async def get_preference_profile(planner_id: str) -> PreferenceProfile:
    return _case_library.get_preference_profile(planner_id)
