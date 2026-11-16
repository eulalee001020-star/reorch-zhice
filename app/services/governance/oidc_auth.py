"""Fail-closed OIDC token verification and enterprise role mapping."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import jwt
from jwt import PyJWKClient


@dataclass(frozen=True)
class OIDCPrincipal:
    user_id: str
    username: str
    display_name: str
    role: str
    tenant_id: str
    claims: dict[str, Any]


class OIDCVerificationError(ValueError):
    pass


class OIDCTokenVerifier:
    """Verify signature and required claims before mapping authorization."""

    def __init__(
        self,
        *,
        issuer: str,
        audience: str,
        algorithms: list[str],
        role_claim: str,
        tenant_claim: str,
        role_mapping: dict[str, str],
        jwks_url: str | None = None,
        verification_key: str | bytes | None = None,
    ) -> None:
        if not issuer or not audience:
            raise OIDCVerificationError("oidc_issuer_and_audience_required")
        if not algorithms:
            raise OIDCVerificationError("oidc_algorithms_required")
        if not jwks_url and verification_key is None:
            raise OIDCVerificationError("oidc_jwks_or_verification_key_required")
        self.issuer = issuer
        self.audience = audience
        self.algorithms = algorithms
        self.role_claim = role_claim
        self.tenant_claim = tenant_claim
        self.role_mapping = role_mapping
        self.jwks_client = PyJWKClient(jwks_url, cache_keys=True) if jwks_url else None
        self.verification_key = verification_key

    def verify(self, token: str) -> OIDCPrincipal:
        try:
            header = jwt.get_unverified_header(token)
            algorithm = str(header.get("alg", ""))
            if algorithm not in self.algorithms or algorithm.lower() == "none":
                raise OIDCVerificationError("oidc_algorithm_not_allowed")
            key = self.verification_key
            if self.jwks_client is not None:
                key = self.jwks_client.get_signing_key_from_jwt(token).key
            claims = jwt.decode(
                token,
                key=key,
                algorithms=self.algorithms,
                issuer=self.issuer,
                audience=self.audience,
                options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            )
        except OIDCVerificationError:
            raise
        except Exception as exc:
            raise OIDCVerificationError(f"oidc_token_rejected:{type(exc).__name__}") from exc

        role_values = _claim_values(claims, self.role_claim)
        mapped_roles = [self.role_mapping.get(value.lower()) for value in role_values]
        mapped_roles = [value for value in mapped_roles if value]
        if not mapped_roles:
            raise OIDCVerificationError("oidc_role_not_mapped")
        tenant_id = str(_nested_claim(claims, self.tenant_claim) or "")
        if not tenant_id:
            raise OIDCVerificationError("oidc_tenant_claim_missing")
        user_id = str(claims.get("sub") or "")
        username = str(
            claims.get("preferred_username") or claims.get("email") or user_id
        )
        return OIDCPrincipal(
            user_id=user_id,
            username=username,
            display_name=str(claims.get("name") or username),
            role=mapped_roles[0],
            tenant_id=tenant_id,
            claims=claims,
        )


def parse_role_mapping(value: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in value.split(","):
        source, separator, target = item.partition("=")
        if separator and source.strip() and target.strip():
            result[source.strip().lower()] = target.strip()
    return result


def _claim_values(claims: dict[str, Any], claim_path: str) -> list[str]:
    value = _nested_claim(claims, claim_path)
    if isinstance(value, str):
        return [item for item in value.replace(",", " ").split() if item]
    if isinstance(value, list):
        return [str(item) for item in value]
    return []


def _nested_claim(claims: dict[str, Any], claim_path: str) -> Any:
    value: Any = claims
    for part in claim_path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value
