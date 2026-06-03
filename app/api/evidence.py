"""Evidence Center API."""

from __future__ import annotations

from fastapi import APIRouter

from app.models.evidence import EvidenceCenterResponse
from app.services.evidence_center import EvidenceCenterService

router = APIRouter(prefix="/api/v1/evidence", tags=["evidence"])


@router.get(
    "/center",
    response_model=EvidenceCenterResponse,
    summary="查看 replay、失败样本、LLM eval、Data Readiness 和质量门证据",
)
async def get_evidence_center() -> EvidenceCenterResponse:
    return EvidenceCenterService().build()
