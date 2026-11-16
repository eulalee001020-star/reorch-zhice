"""Server-side authorization for external MES writeback."""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.core.auth import CurrentUser, Role
from app.core.config import settings
from app.models.decision import DecisionRecord


class WritebackPolicyError(RuntimeError):
    """Raised when an external writeback request exceeds the deployment policy."""


@dataclass(frozen=True)
class WritebackExecutionPermit:
    """Short-lived capability issued only after the second-approval gate."""

    decision_record_id: str
    confirmed_plan_id: str
    approver_user_id: str
    adapter_id: str
    certification_id: str
    expires_at: str
    signature: str


class WritebackPolicy:
    """Keep writeback disabled until an explicit sandbox deployment is approved."""

    @staticmethod
    def authorize_sandbox_execution(
        *,
        decision_record: DecisionRecord,
        approver: CurrentUser,
        approval_note: str,
        adapter_id: str = "",
        certification_id: str = "",
    ) -> WritebackExecutionPermit:
        if not settings.auth.require_api_key:
            raise WritebackPolicyError(
                "sandbox_writeback_requires_AUTH_REQUIRE_API_KEY_true"
            )
        if approver.user_id == "system":
            raise WritebackPolicyError("sandbox_writeback_requires_authenticated_approver")
        if approver.role not in {Role.MANAGEMENT, Role.IT_ADMIN}:
            raise WritebackPolicyError(
                "sandbox_writeback_requires_management_or_it_admin_approval"
            )
        if approver.user_id == decision_record.confirmed_by:
            raise WritebackPolicyError(
                "sandbox_writeback_requires_second_person_approval"
            )
        if len(approval_note.strip()) < 8:
            raise WritebackPolicyError("sandbox_writeback_requires_approval_note")
        if settings.integration.writeback_mode != "sandbox":
            raise WritebackPolicyError(
                "sandbox_writeback_disabled_by_INTEGRATION_WRITEBACK_MODE"
            )
        if settings.integration.mes_target_environment != "sandbox":
            raise WritebackPolicyError(
                "sandbox_writeback_requires_MES_TARGET_ENVIRONMENT_sandbox"
            )
        if not settings.integration.mes_base_url:
            raise WritebackPolicyError("sandbox_writeback_requires_MES_BASE_URL")
        if len(settings.auth.writeback_permit_secret) < 32:
            raise WritebackPolicyError(
                "sandbox_writeback_requires_32_char_AUTH_WRITEBACK_PERMIT_SECRET"
            )

        expires_at = datetime.now(tz=timezone.utc) + timedelta(
            seconds=settings.auth.writeback_permit_ttl_seconds
        )
        unsigned = WritebackExecutionPermit(
            decision_record_id=str(decision_record.decision_record_id),
            confirmed_plan_id=str(decision_record.confirmed_plan_id),
            approver_user_id=approver.user_id,
            adapter_id=adapter_id,
            certification_id=certification_id,
            expires_at=expires_at.isoformat(),
            signature="",
        )
        return WritebackExecutionPermit(
            decision_record_id=unsigned.decision_record_id,
            confirmed_plan_id=unsigned.confirmed_plan_id,
            approver_user_id=unsigned.approver_user_id,
            adapter_id=unsigned.adapter_id,
            certification_id=unsigned.certification_id,
            expires_at=unsigned.expires_at,
            signature=WritebackPolicy._sign(unsigned),
        )

    @staticmethod
    def assert_adapter_send_allowed(
        *,
        execution_permit: WritebackExecutionPermit | None = None,
        decision_record_id: str | None = None,
        confirmed_plan_id: str | None = None,
    ) -> None:
        """Protect the adapter even if a caller bypasses the HTTP endpoint."""
        if not settings.integration.mes_base_url:
            return
        if settings.integration.writeback_mode != "sandbox":
            raise WritebackPolicyError("external_mes_writeback_is_disabled")
        if settings.integration.mes_target_environment != "sandbox":
            raise WritebackPolicyError("production_mes_writeback_is_not_supported")
        if execution_permit is None:
            raise WritebackPolicyError("external_mes_writeback_requires_execution_permit")
        if len(settings.auth.writeback_permit_secret) < 32:
            raise WritebackPolicyError("external_mes_writeback_permit_secret_is_invalid")
        if decision_record_id and execution_permit.decision_record_id != decision_record_id:
            raise WritebackPolicyError("writeback_permit_decision_mismatch")
        if confirmed_plan_id and execution_permit.confirmed_plan_id != confirmed_plan_id:
            raise WritebackPolicyError("writeback_permit_plan_mismatch")

        try:
            expires_at = datetime.fromisoformat(execution_permit.expires_at)
        except ValueError as exc:
            raise WritebackPolicyError("writeback_permit_expiry_is_invalid") from exc
        if expires_at.tzinfo is None or expires_at <= datetime.now(tz=timezone.utc):
            raise WritebackPolicyError("writeback_permit_has_expired")

        expected = WritebackPolicy._sign(execution_permit)
        if not hmac.compare_digest(expected, execution_permit.signature):
            raise WritebackPolicyError("writeback_permit_signature_is_invalid")

    @staticmethod
    def _sign(permit: WritebackExecutionPermit) -> str:
        payload = "|".join(
            (
                permit.decision_record_id,
                permit.confirmed_plan_id,
                permit.approver_user_id,
                permit.adapter_id,
                permit.certification_id,
                permit.expires_at,
            )
        ).encode("utf-8")
        return hmac.new(
            settings.auth.writeback_permit_secret.encode("utf-8"),
            payload,
            hashlib.sha256,
        ).hexdigest()
