"""Tests for CaseTemplateManager service.

Covers:
- create_template() creates draft template
- edit_template() edits draft, rejects published
- publish_template() publishes template
- list_templates() with status filter
- increment_reference() and record_adoption() tracking

Validates: Requirements 9.8, 9.9
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.models.case import CaseTemplate
from app.services.case_template_manager import (
    CaseTemplateManager,
    TemplateAlreadyPublishedError,
    TemplateNotFoundError,
)


def _create_test_template(mgr: CaseTemplateManager) -> CaseTemplate:
    return mgr.create_template(
        template_name="Equipment Failure - Local Repair",
        applicable_incident_types=["equipment_failure"],
        recommended_strategy="local_repair",
        key_parameter_thresholds={"affected_ratio_max": 0.2},
        created_by="manager-1",
    )


# ── create_template ────────────────────────────────────────────────


def test_create_template():
    """create_template creates a draft template."""
    mgr = CaseTemplateManager()
    template = _create_test_template(mgr)

    assert isinstance(template, CaseTemplate)
    assert template.status == "draft"
    assert template.template_name == "Equipment Failure - Local Repair"
    assert template.reference_count == 0
    assert template.adoption_rate == 0.0
    assert template.created_by == "manager-1"


# ── edit_template ──────────────────────────────────────────────────


def test_edit_template_draft():
    """edit_template updates draft template fields."""
    mgr = CaseTemplateManager()
    template = _create_test_template(mgr)

    updated = mgr.edit_template(
        template_id=template.template_id,
        template_name="Updated Name",
        recommended_strategy="global_reschedule",
    )

    assert updated.template_name == "Updated Name"
    assert updated.recommended_strategy == "global_reschedule"
    # Unchanged fields remain
    assert updated.applicable_incident_types == ["equipment_failure"]


def test_edit_published_template_raises():
    """edit_template raises error for published template."""
    mgr = CaseTemplateManager()
    template = _create_test_template(mgr)
    mgr.publish_template(template.template_id)

    with pytest.raises(TemplateAlreadyPublishedError):
        mgr.edit_template(
            template_id=template.template_id,
            template_name="Should Fail",
        )


def test_edit_nonexistent_template_raises():
    """edit_template raises error for unknown template."""
    mgr = CaseTemplateManager()

    with pytest.raises(TemplateNotFoundError):
        mgr.edit_template(template_id=uuid4(), template_name="Nope")


# ── publish_template ───────────────────────────────────────────────


def test_publish_template():
    """publish_template changes status to published."""
    mgr = CaseTemplateManager()
    template = _create_test_template(mgr)

    published = mgr.publish_template(template.template_id)

    assert published.status == "published"


def test_publish_nonexistent_raises():
    """publish_template raises error for unknown template."""
    mgr = CaseTemplateManager()

    with pytest.raises(TemplateNotFoundError):
        mgr.publish_template(uuid4())


# ── list_templates ─────────────────────────────────────────────────


def test_list_templates_all():
    """list_templates returns all templates."""
    mgr = CaseTemplateManager()
    _create_test_template(mgr)
    _create_test_template(mgr)

    templates = mgr.list_templates()
    assert len(templates) == 2


def test_list_templates_by_status():
    """list_templates filters by status."""
    mgr = CaseTemplateManager()
    t1 = _create_test_template(mgr)
    _create_test_template(mgr)
    mgr.publish_template(t1.template_id)

    published = mgr.list_templates(status="published")
    assert len(published) == 1
    assert published[0].status == "published"

    drafts = mgr.list_templates(status="draft")
    assert len(drafts) == 1
    assert drafts[0].status == "draft"


# ── get_template ───────────────────────────────────────────────────


def test_get_template():
    """get_template returns template by ID."""
    mgr = CaseTemplateManager()
    template = _create_test_template(mgr)

    found = mgr.get_template(template.template_id)
    assert found is not None
    assert found.template_id == template.template_id


def test_get_template_not_found():
    """get_template returns None for unknown ID."""
    mgr = CaseTemplateManager()
    assert mgr.get_template(uuid4()) is None


# ── reference tracking (Req 9.9) ──────────────────────────────────


def test_increment_reference():
    """increment_reference increases reference_count."""
    mgr = CaseTemplateManager()
    template = _create_test_template(mgr)

    mgr.increment_reference(template.template_id)
    mgr.increment_reference(template.template_id)

    updated = mgr.get_template(template.template_id)
    assert updated is not None
    assert updated.reference_count == 2


def test_record_adoption():
    """record_adoption updates adoption_rate correctly."""
    mgr = CaseTemplateManager()
    template = _create_test_template(mgr)

    # 3 references, 2 adopted
    mgr.increment_reference(template.template_id)
    mgr.record_adoption(template.template_id, was_adopted=True)

    mgr.increment_reference(template.template_id)
    mgr.record_adoption(template.template_id, was_adopted=True)

    mgr.increment_reference(template.template_id)
    mgr.record_adoption(template.template_id, was_adopted=False)

    updated = mgr.get_template(template.template_id)
    assert updated is not None
    assert updated.reference_count == 3
    assert updated.adoption_rate == pytest.approx(2 / 3, abs=0.01)


# ── get_published_templates ────────────────────────────────────────


def test_get_published_templates():
    """get_published_templates returns only published templates."""
    mgr = CaseTemplateManager()
    t1 = _create_test_template(mgr)
    _create_test_template(mgr)
    mgr.publish_template(t1.template_id)

    published = mgr.get_published_templates()
    assert len(published) == 1
    assert published[0].template_id == t1.template_id
