"""Cryptographic verification for external recovery approval attestations."""

from __future__ import annotations

import hashlib
import hmac

from app.core.config import settings
from app.models.feasibility_restoration import RecoveryApprovalAttestation


class RecoveryApprovalPolicy:
    """Bind approvals to an action, policy version, role, time, and source."""

    @staticmethod
    def sign(
        approval: RecoveryApprovalAttestation,
        *,
        secret: str | None = None,
    ) -> str:
        signing_secret = secret or settings.auth.recovery_approval_secret
        if len(signing_secret) < 32:
            raise ValueError("recovery_approval_secret_must_be_at_least_32_characters")
        return hmac.new(
            signing_secret.encode("utf-8"),
            RecoveryApprovalPolicy._payload(approval),
            hashlib.sha256,
        ).hexdigest()

    @staticmethod
    def verify(approval: RecoveryApprovalAttestation) -> tuple[bool, str | None]:
        secret = settings.auth.recovery_approval_secret
        if len(secret) < 32:
            return False, "recovery_approval_secret_not_configured"
        if not approval.signature:
            return False, "approval_signature_missing"
        expected = RecoveryApprovalPolicy.sign(approval, secret=secret)
        if not hmac.compare_digest(expected, approval.signature):
            return False, "approval_signature_invalid"
        return True, None

    @staticmethod
    def _payload(approval: RecoveryApprovalAttestation) -> bytes:
        return "|".join(
            (
                approval.action_id,
                approval.policy_id,
                approval.policy_version,
                approval.approver_id,
                approval.approver_role,
                approval.approved_at.isoformat(),
                approval.expires_at.isoformat() if approval.expires_at else "",
                approval.source_ref,
            )
        ).encode("utf-8")
