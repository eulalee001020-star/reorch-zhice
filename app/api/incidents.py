"""Anomaly Intake Center API endpoints.

Validates: Requirements 1.1, 10.5, 18.1

Provides:
- POST /api/v1/incidents — receive anomaly events (OpenAPI 3.0)
- GET  /api/v1/incidents — list incidents with filtering
- GET  /api/v1/incidents/{incident_id} — get incident details
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.auth import CurrentUser, get_optional_current_user
from app.models.enums import IncidentSeverity, IncidentStatus, IncidentType
from app.models.incident import Incident, IncidentCreateRequest
from app.services.persistence import fetch_incident, list_incidents_from_db, persist_incident
from app.services.anomaly_intake_center import (
    AnomalyIntakeCenter,
    IntakeValidationError,
    SourceNotAllowedError,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/incidents", tags=["incidents"])

# ---------------------------------------------------------------------------
# Local fallback cache used only when PostgreSQL is unavailable in dev/test.
# ---------------------------------------------------------------------------
_incident_store: dict[str, Incident] = {}


def _get_intake_center() -> AnomalyIntakeCenter:
    """Build a lightweight AnomalyIntakeCenter for the API layer.

    Uses a thin wrapper that skips Redis/Kafka so the endpoint can work
    with the in-memory store.  A proper DI container will replace this
    once the DB session layer is ready.
    """
    from app.core.kafka_producer import KafkaProducer
    from app.core.redis_client import redis_client

    return AnomalyIntakeCenter(
        redis_client=redis_client,
        kafka_producer=KafkaProducer(),
    )


# ---------------------------------------------------------------------------
# POST /api/v1/incidents — receive anomaly event
# ---------------------------------------------------------------------------


@router.post(
    "",
    response_model=Incident,
    status_code=status.HTTP_201_CREATED,
    summary="接收异常事件",
    description=(
        "接收来自外部系统（MES、IoT、人工上报）的异常事件，"
        "执行字段校验、来源校验、严重等级分级、去重合并，"
        "并发布到事件流。返回创建（或去重后的主）Incident。"
    ),
    responses={
        422: {"description": "字段校验失败 — 缺少必要字段"},
        403: {"description": "上报来源不在合法来源列表中"},
    },
)
async def create_incident(
    body: IncidentCreateRequest,
    current_user: CurrentUser = Depends(get_optional_current_user),
) -> Incident:
    intake = _get_intake_center()
    try:
        incident = await intake.receive_event(body)
    except IntakeValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "message": exc.reason,
                "missing_fields": exc.missing_fields,
            },
        )
    except SourceNotAllowedError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"message": str(exc), "source": exc.source},
        )

    # Persist in the in-memory store keyed by incident_id string
    key = str(incident.incident_id)
    incident.created_by = current_user.user_id
    _incident_store[key] = incident
    await persist_incident(incident, user_id=current_user.user_id)
    return incident


# ---------------------------------------------------------------------------
# GET /api/v1/incidents — list incidents with optional filters
# ---------------------------------------------------------------------------


@router.get(
    "",
    response_model=list[Incident],
    summary="查询异常列表",
    description=(
        "查询异常事件列表，支持按类型、严重等级、状态和时间范围筛选。"
    ),
)
async def list_incidents(
    incident_type: Optional[IncidentType] = Query(
        None, description="按异常类型筛选"
    ),
    severity: Optional[IncidentSeverity] = Query(
        None, description="按严重等级筛选"
    ),
    status_filter: Optional[IncidentStatus] = Query(
        None, alias="status", description="按状态筛选"
    ),
    start_time: Optional[datetime] = Query(
        None, description="筛选发生时间 >= start_time"
    ),
    end_time: Optional[datetime] = Query(
        None, description="筛选发生时间 <= end_time"
    ),
) -> list[Incident]:
    if not _incident_store:
        db_results = await list_incidents_from_db(
            incident_type=incident_type.value if incident_type is not None else None,
            severity=severity.value if severity is not None else None,
            status=status_filter.value if status_filter is not None else None,
            start_time=start_time,
            end_time=end_time,
        )
        if db_results is not None:
            return db_results

    results: list[Incident] = list(_incident_store.values())

    if incident_type is not None:
        results = [i for i in results if i.incident_type == incident_type]
    if severity is not None:
        results = [i for i in results if i.severity == severity]
    if status_filter is not None:
        results = [i for i in results if i.status == status_filter]
    if start_time is not None:
        results = [i for i in results if i.occurred_at >= start_time]
    if end_time is not None:
        results = [i for i in results if i.occurred_at <= end_time]

    # Sort by severity (P1 first) then by occurred_at descending
    _severity_order = {
        IncidentSeverity.P1_CRITICAL.value: 0,
        IncidentSeverity.P2_HIGH.value: 1,
        IncidentSeverity.P3_MEDIUM.value: 2,
        IncidentSeverity.P4_LOW.value: 3,
    }
    results.sort(
        key=lambda i: (
            _severity_order.get(i.severity, 99),
            -(i.occurred_at.timestamp() if i.occurred_at else 0),
        )
    )
    return results


# ---------------------------------------------------------------------------
# GET /api/v1/incidents/{incident_id} — get incident details
# ---------------------------------------------------------------------------


@router.get(
    "/{incident_id}",
    response_model=Incident,
    summary="查询异常详情",
    description="根据 incident_id 查询单个异常事件的完整详情。",
    responses={404: {"description": "Incident 不存在"}},
)
async def get_incident(incident_id: UUID) -> Incident:
    key = str(incident_id)
    incident = _incident_store.get(key)
    if incident is None:
        incident = await fetch_incident(incident_id)
        if incident is not None:
            _incident_store[key] = incident
    if incident is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Incident {incident_id} not found",
        )
    return incident
