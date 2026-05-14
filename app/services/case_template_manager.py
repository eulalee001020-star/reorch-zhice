"""CaseTemplate Manager — management service for reviewing, editing,
and publishing case templates.

Validates: Requirements 9.8, 9.9

Provides:
- create_template(): create a new draft CaseTemplate
- edit_template(): edit an existing template
- publish_template(): publish a template (makes it available to Strategy_Selector)
- list_templates(): list all templates with optional status filter
- get_template(): get a single template by ID
- increment_reference(): track reference_count when template is used
- record_adoption(): update adoption_rate based on usage outcomes
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID, uuid4

from app.models.case import CaseTemplate

logger = logging.getLogger(__name__)


class TemplateNotFoundError(Exception):
    """Raised when a template is not found."""


class TemplateAlreadyPublishedError(Exception):
    """Raised when trying to edit a published template without unpublishing."""


class CaseTemplateManager:
    """Manages CaseTemplate lifecycle: create, edit, publish, track usage.

    Uses in-memory store for MVP. Production would use PostgreSQL.
    """

    def __init__(self) -> None:
        self._template_store: dict[str, CaseTemplate] = {}

    def create_template(
        self,
        template_name: str,
        applicable_incident_types: list[str],
        recommended_strategy: str,
        key_parameter_thresholds: dict,
        created_by: str,
    ) -> CaseTemplate:
        """Create a new draft CaseTemplate (Req 9.8)."""
        template = CaseTemplate(
            template_id=uuid4(),
            template_name=template_name,
            applicable_incident_types=applicable_incident_types,
            recommended_strategy=recommended_strategy,
            key_parameter_thresholds=key_parameter_thresholds,
            status="draft",
            reference_count=0,
            adoption_rate=0.0,
            created_by=created_by,
            created_at=datetime.now(tz=timezone.utc),
        )
        self._template_store[str(template.template_id)] = template

        logger.info(
            "Template created: %s (%s) by %s",
            template.template_id,
            template_name,
            created_by,
        )
        return template

    def edit_template(
        self,
        template_id: UUID,
        template_name: str | None = None,
        applicable_incident_types: list[str] | None = None,
        recommended_strategy: str | None = None,
        key_parameter_thresholds: dict | None = None,
    ) -> CaseTemplate:
        """Edit an existing template. Only draft templates can be edited (Req 9.8)."""
        template = self._get_template_or_raise(template_id)

        if template.status == "published":
            raise TemplateAlreadyPublishedError(
                f"Template {template_id} is published. Unpublish before editing."
            )

        if template_name is not None:
            template.template_name = template_name
        if applicable_incident_types is not None:
            template.applicable_incident_types = applicable_incident_types
        if recommended_strategy is not None:
            template.recommended_strategy = recommended_strategy
        if key_parameter_thresholds is not None:
            template.key_parameter_thresholds = key_parameter_thresholds

        self._template_store[str(template_id)] = template

        logger.info("Template edited: %s", template_id)
        return template

    def publish_template(self, template_id: UUID) -> CaseTemplate:
        """Publish a template, making it available to Strategy_Selector (Req 9.8)."""
        template = self._get_template_or_raise(template_id)
        template.status = "published"
        self._template_store[str(template_id)] = template

        logger.info("Template published: %s (%s)", template_id, template.template_name)
        return template

    def list_templates(self, status: str | None = None) -> list[CaseTemplate]:
        """List all templates, optionally filtered by status."""
        templates = list(self._template_store.values())
        if status:
            templates = [t for t in templates if t.status == status]
        return sorted(templates, key=lambda t: t.created_at, reverse=True)

    def get_template(self, template_id: UUID) -> CaseTemplate | None:
        """Get a single template by ID."""
        return self._template_store.get(str(template_id))

    def get_published_templates(self) -> list[CaseTemplate]:
        """Get all published templates (available to Strategy_Selector)."""
        return [
            t for t in self._template_store.values() if t.status == "published"
        ]

    def increment_reference(self, template_id: UUID) -> CaseTemplate:
        """Increment reference_count when a template is used (Req 9.9)."""
        template = self._get_template_or_raise(template_id)
        template.reference_count += 1
        self._template_store[str(template_id)] = template
        return template

    def record_adoption(
        self, template_id: UUID, was_adopted: bool
    ) -> CaseTemplate:
        """Update adoption_rate based on usage outcome (Req 9.9).

        adoption_rate = adopted_count / reference_count
        """
        template = self._get_template_or_raise(template_id)

        # Track adoption in key_parameter_thresholds as a simple counter
        adopted = template.key_parameter_thresholds.get("_adopted_count", 0)
        if was_adopted:
            adopted += 1
            template.key_parameter_thresholds["_adopted_count"] = adopted

        if template.reference_count > 0:
            template.adoption_rate = round(adopted / template.reference_count, 4)

        self._template_store[str(template_id)] = template
        return template

    # ── Private helpers ────────────────────────────────────────────

    def _get_template_or_raise(self, template_id: UUID) -> CaseTemplate:
        """Get template or raise TemplateNotFoundError."""
        template = self._template_store.get(str(template_id))
        if template is None:
            raise TemplateNotFoundError(
                f"Template {template_id} not found."
            )
        return template
