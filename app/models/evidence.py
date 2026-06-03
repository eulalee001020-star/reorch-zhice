"""Evidence Center models."""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import Field

from app.models.base import ReOrchModel


class EvidenceTable(ReOrchModel):
    """A small auditable table extracted or computed for evidence review."""

    columns: list[str] = Field(default_factory=list)
    rows: list[dict[str, str]] = Field(default_factory=list)


class EvidenceItem(ReOrchModel):
    """One evidence block shown in Evidence Center."""

    evidence_id: str
    category: str
    title: str
    status: str
    summary: str
    source_path: str | None = None
    source_refs: list[str] = Field(default_factory=list)
    metrics: dict = Field(default_factory=dict)
    table: EvidenceTable | None = None
    limitations: list[str] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))


class EvidenceCenterResponse(ReOrchModel):
    """Evidence Center aggregate response."""

    generated_at: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))
    items: list[EvidenceItem] = Field(default_factory=list)
    summary_counts: dict = Field(default_factory=dict)
