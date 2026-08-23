"""Deterministic operator configuration for Buildkite JWT auth in OpenBao."""

from __future__ import annotations

import os
from collections.abc import Mapping
from uuid import UUID

import httpx

from network_change_delivery.buildkite_identity import (
    BUILDKITE_OIDC_ISSUER,
    OPENBAO_BUILDKITE_JWT_AUDIENCE,
    OPENBAO_BUILDKITE_JWT_ROLE,
    OPENBAO_BUILDKITE_MAX_LEASE_SECONDS,
)
from network_change_delivery.secrets import (
    SecretError,
    create_openbao_client,
    validate_openbao_url,
)

JWT_MOUNT = "jwt/"
JWT_MOUNT_DESCRIPTION = "NCDP Buildkite workload identity"
JWT_CONFIG_WRITE = {
    "oidc_discovery_url": BUILDKITE_OIDC_ISSUER,
    "bound_issuer": BUILDKITE_OIDC_ISSUER,
    "skip_jwks_validation": False,
}
JWT_CONFIG_READ = {
    "oidc_discovery_url": BUILDKITE_OIDC_ISSUER,
    "bound_issuer": BUILDKITE_OIDC_ISSUER,
    "status": "valid",
}
JWT_CLAIM_MAPPINGS = {
    "/sub": "pipeline_id",
    "/build_commit": "build_commit",
    "/build_branch": "build_branch",
    "/step_key": "step_key",
    "/job_id": "job_id",
}


def validate_pipeline_id(value: str) -> str:
    """Require one canonical immutable Buildkite pipeline UUID."""
    try:
        parsed = UUID(value)
    except (AttributeError, ValueError):
        raise SecretError("Buildkite pipeline ID rejected") from None
    if str(parsed) != value:
        raise SecretError("Buildkite pipeline ID rejected")
    return value


def buildkite_jwt_role_config(pipeline_id: str) -> dict[str, object]:
    """Return the exact no-secret-capability JWT role contract."""
    return {
        "role_type": "jwt",
        "bound_audiences": [OPENBAO_BUILDKITE_JWT_AUDIENCE],
        "bound_subject": validate_pipeline_id(pipeline_id),
        "user_claim": "sub",
        "bound_claims_type": "string",
        "bound_claims": {"build_branch": "main", "step_key": "deploy-gate"},
        "claim_mappings": JWT_CLAIM_MAPPINGS,
        "token_no_default_policy": True,
        "token_policies": [],
        "token_ttl": OPENBAO_BUILDKITE_MAX_LEASE_SECONDS,
        "token_max_ttl": OPENBAO_BUILDKITE_MAX_LEASE_SECONDS,
        "token_explicit_max_ttl": OPENBAO_BUILDKITE_MAX_LEASE_SECONDS,
        "token_num_uses": 1,
    }


class OpenBaoBuildkiteJWTConfigurator:
    """Idempotently establish and verify the dedicated JWT auth boundary."""

    def __init__(
        self,
        url: str,
        admin_token: str,
        pipeline_id: str,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not admin_token:
            raise SecretError("OpenBao operator configuration missing")
        self._pipeline_id = validate_pipeline_id(pipeline_id)
        self._client = create_openbao_client(
            validate_openbao_url(url), transport=transport
        )
        self._headers = {"X-Vault-Token": admin_token}

    @classmethod
    def from_environment(
        cls,
        environment: Mapping[str, str] | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> OpenBaoBuildkiteJWTConfigurator:
        """Load the admin token and non-secret configuration only from environment."""
        values = environment if environment is not None else os.environ
        url = values.get("NCDP_OPENBAO_URL", "")
        token = values.get("BAO_TOKEN", "")
        pipeline_id = values.get("NCDP_BUILDKITE_PIPELINE_ID", "")
        if not url or not token or not pipeline_id:
            raise SecretError("OpenBao operator configuration missing")
        return cls(url, token, pipeline_id, transport=transport)

    @staticmethod
    def _payload(response: httpx.Response) -> dict[str, object]:
        try:
            payload = response.json()
        except ValueError:
            raise SecretError("OpenBao returned invalid JSON or schema") from None
        if not isinstance(payload, dict):
            raise SecretError("OpenBao returned invalid JSON or schema")
        return payload

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, object] | None = None,
        expected_status: int,
    ) -> httpx.Response:
        try:
            response = self._client.request(
                method, path, headers=self._headers, json=json
            )
        except (httpx.TimeoutException, httpx.RequestError):
            raise SecretError("OpenBao unavailable or timed out") from None
        if response.status_code in {400, 401, 403}:
            raise SecretError("OpenBao operator request unauthorized")
        if response.status_code != expected_status:
            raise SecretError(
                f"OpenBao returned unexpected HTTP status {response.status_code}"
            )
        return response

    def _auth_mounts(self) -> dict[str, object]:
        response = self._request("GET", "/v1/sys/auth", expected_status=200)
        data = self._payload(response).get("data")
        if not isinstance(data, dict):
            raise SecretError("OpenBao returned invalid JSON or schema")
        return data

    def _ensure_mount(self) -> bool:
        mounts = self._auth_mounts()
        mounted = mounts.get(JWT_MOUNT)
        if mounted is None:
            self._request(
                "POST",
                "/v1/sys/auth/jwt",
                json={"type": "jwt", "description": JWT_MOUNT_DESCRIPTION},
                expected_status=204,
            )
            mounted = self._auth_mounts().get(JWT_MOUNT)
            if not self._owned_mount(mounted):
                raise SecretError("OpenBao JWT auth mount verification failed")
            return True
        if not self._owned_mount(mounted):
            raise SecretError("OpenBao jwt/ auth mount is not owned by NCDP")
        return False

    @staticmethod
    def _owned_mount(mounted: object) -> bool:
        return (
            isinstance(mounted, dict)
            and mounted.get("type") == "jwt"
            and mounted.get("description") == JWT_MOUNT_DESCRIPTION
        )

    @staticmethod
    def _verify_fields(
        actual: object, expected: Mapping[str, object], message: str
    ) -> None:
        if not isinstance(actual, dict):
            raise SecretError(message)
        if any(actual.get(key) != value for key, value in expected.items()):
            raise SecretError(message)

    def configure(self) -> bool:
        """Configure, read back, and verify the exact JWT backend and role."""
        enabled = self._ensure_mount()
        self._request(
            "POST",
            "/v1/auth/jwt/config",
            json=JWT_CONFIG_WRITE,
            expected_status=204,
        )
        config_response = self._request(
            "GET", "/v1/auth/jwt/config", expected_status=200
        )
        config_data = self._payload(config_response).get("data")
        self._verify_fields(
            config_data, JWT_CONFIG_READ, "OpenBao JWT backend verification failed"
        )
        if isinstance(config_data, dict):
            for field in ("oidc_client_id", "oidc_client_secret", "jwks_url"):
                if config_data.get(field) not in (None, ""):
                    raise SecretError("OpenBao JWT backend verification failed")
            if config_data.get("jwt_validation_pubkeys") not in (None, "", []):
                raise SecretError("OpenBao JWT backend verification failed")

        role = buildkite_jwt_role_config(self._pipeline_id)
        role_path = f"/v1/auth/jwt/role/{OPENBAO_BUILDKITE_JWT_ROLE}"
        self._request("POST", role_path, json=role, expected_status=204)
        role_response = self._request("GET", role_path, expected_status=200)
        self._verify_fields(
            self._payload(role_response).get("data"),
            role,
            "OpenBao Buildkite JWT role verification failed",
        )
        return enabled


def configure_from_environment(environment: Mapping[str, str] | None = None) -> bool:
    """Run operator configuration from its environment-only boundary."""
    return OpenBaoBuildkiteJWTConfigurator.from_environment(environment).configure()
