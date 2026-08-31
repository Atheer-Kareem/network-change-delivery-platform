"""Idempotent OpenBao configuration for Buildkite CML staging identity."""

from __future__ import annotations

import os
from collections.abc import Mapping

import httpx

from network_change_delivery.buildkite_staging import (
    OPENBAO_STAGING_AUDIENCE,
    OPENBAO_STAGING_MAX_LEASE_SECONDS,
    STAGING_DEVICE_IDS,
    staging_policy_name,
    staging_role_name,
)
from network_change_delivery.openbao_jwt_config import (
    JWT_CONFIG_READ,
    JWT_MOUNT,
    JWT_MOUNT_DESCRIPTION,
    validate_pipeline_id,
)
from network_change_delivery.secrets import (
    SecretError,
    create_openbao_client,
    validate_openbao_url,
)

STAGING_CLAIM_MAPPINGS = {
    "/sub": "pipeline_id",
    "/build_id": "build_id",
    "/build_commit": "build_commit",
    "/build_branch": "build_branch",
    "/step_key": "step_key",
    "/job_id": "job_id",
}


def staging_policy(device_id: int) -> str:
    if device_id not in STAGING_DEVICE_IDS:
        raise SecretError("Buildkite staging device ID rejected")
    return (
        f'path "ncdp/data/devices/{device_id}/ssh" {{\n  capabilities = ["read"]\n}}\n'
    )


def staging_role_config(pipeline_id: str, device_id: int) -> dict[str, object]:
    policy = staging_policy_name(device_id)
    staging_policy(device_id)
    return {
        "role_type": "jwt",
        "bound_audiences": [OPENBAO_STAGING_AUDIENCE],
        "bound_subject": validate_pipeline_id(pipeline_id),
        "user_claim": "sub",
        "bound_claims_type": "string",
        "bound_claims": {"step_key": "cml-staging"},
        "claim_mappings": STAGING_CLAIM_MAPPINGS,
        "token_no_default_policy": True,
        "token_policies": [policy],
        "token_ttl": OPENBAO_STAGING_MAX_LEASE_SECONDS,
        "token_max_ttl": OPENBAO_STAGING_MAX_LEASE_SECONDS,
        "token_explicit_max_ttl": OPENBAO_STAGING_MAX_LEASE_SECONDS,
        "token_num_uses": 1,
    }


class OpenBaoBuildkiteStagingConfigurator:
    """Verify the owned mount and configure both exact staging capabilities."""

    def __init__(
        self,
        url: str,
        admin_token: str,
        pipeline_id: str,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not admin_token:
            raise SecretError("OpenBao staging operator configuration missing")
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
    ) -> OpenBaoBuildkiteStagingConfigurator:
        values = environment if environment is not None else os.environ
        required = ("NCDP_OPENBAO_URL", "NCDP_BUILDKITE_PIPELINE_ID", "BAO_TOKEN")
        if any(not values.get(name) for name in required):
            raise SecretError("OpenBao staging operator configuration missing")
        return cls(
            values["NCDP_OPENBAO_URL"],
            values["BAO_TOKEN"],
            values["NCDP_BUILDKITE_PIPELINE_ID"],
            transport=transport,
        )

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
            raise SecretError("OpenBao staging operator request unauthorized")
        if response.status_code != expected_status:
            raise SecretError(
                f"OpenBao returned unexpected HTTP status {response.status_code}"
            )
        return response

    @staticmethod
    def _data(response: httpx.Response) -> dict[str, object]:
        try:
            payload = response.json()
        except ValueError:
            raise SecretError("OpenBao returned invalid JSON or schema") from None
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            raise SecretError("OpenBao returned invalid JSON or schema")
        return data

    def configure(self) -> tuple[tuple[str, str], ...]:
        mounts = self._data(self._request("GET", "/v1/sys/auth", expected_status=200))
        mount = mounts.get(JWT_MOUNT)
        if not (
            isinstance(mount, dict)
            and mount.get("type") == "jwt"
            and mount.get("description") == JWT_MOUNT_DESCRIPTION
        ):
            raise SecretError("OpenBao jwt/ auth mount is not owned by NCDP")
        backend = self._data(
            self._request("GET", "/v1/auth/jwt/config", expected_status=200)
        )
        if any(backend.get(key) != value for key, value in JWT_CONFIG_READ.items()):
            raise SecretError("OpenBao staging JWT backend verification failed")
        for field in ("oidc_client_id", "oidc_client_secret", "jwks_url"):
            if backend.get(field) not in (None, ""):
                raise SecretError("OpenBao staging JWT backend verification failed")
        if backend.get("jwt_validation_pubkeys") not in (None, "", []):
            raise SecretError("OpenBao staging JWT backend verification failed")
        configured: list[tuple[str, str]] = []
        for device_id in sorted(STAGING_DEVICE_IDS):
            policy_name = staging_policy_name(device_id)
            policy = staging_policy(device_id)
            policy_path = f"/v1/sys/policies/acl/{policy_name}"
            self._request(
                "PUT", policy_path, json={"policy": policy}, expected_status=204
            )
            policy_data = self._data(
                self._request("GET", policy_path, expected_status=200)
            )
            if policy_data.get("policy") != policy:
                raise SecretError("OpenBao staging policy verification failed")
            role_name = staging_role_name(device_id)
            role = staging_role_config(self._pipeline_id, device_id)
            role_path = f"/v1/auth/jwt/role/{role_name}"
            self._request("POST", role_path, json=role, expected_status=204)
            role_data = self._data(self._request("GET", role_path, expected_status=200))
            if any(role_data.get(key) != value for key, value in role.items()):
                raise SecretError("OpenBao staging role verification failed")
            configured.append((policy_name, role_name))
        return tuple(configured)
