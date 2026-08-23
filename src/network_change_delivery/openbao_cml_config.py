"""Deterministic operator configuration for one-device Buildkite deployment."""

from __future__ import annotations

import os
from collections.abc import Mapping

import httpx

from network_change_delivery.buildkite_deployment import (
    cml_deploy_role_name,
    cml_device_policy_name,
)
from network_change_delivery.buildkite_identity import (
    OPENBAO_BUILDKITE_JWT_AUDIENCE,
    OPENBAO_BUILDKITE_JWT_ROLE,
    OPENBAO_BUILDKITE_MAX_LEASE_SECONDS,
)
from network_change_delivery.openbao_jwt_config import (
    JWT_CLAIM_MAPPINGS,
    JWT_MOUNT,
    JWT_MOUNT_DESCRIPTION,
    buildkite_jwt_role_config,
    validate_pipeline_id,
)
from network_change_delivery.secrets import (
    SecretError,
    create_openbao_client,
    validate_openbao_url,
)


def validate_device_id(value: str) -> int:
    if not value.isdigit() or value.startswith("0") or int(value) <= 0:
        raise SecretError("Buildkite CML device ID rejected")
    return int(value)


def cml_device_policy(device_id: int) -> str:
    return (
        f'path "ncdp/data/devices/{device_id}/ssh" {{\n  capabilities = ["read"]\n}}\n'
    )


def cml_deploy_role_config(pipeline_id: str, device_id: int) -> dict[str, object]:
    policy = cml_device_policy_name(device_id)
    return {
        "role_type": "jwt",
        "bound_audiences": [OPENBAO_BUILDKITE_JWT_AUDIENCE],
        "bound_subject": validate_pipeline_id(pipeline_id),
        "user_claim": "sub",
        "bound_claims_type": "string",
        "bound_claims": {"build_branch": "main", "step_key": "deploy-gate"},
        "claim_mappings": JWT_CLAIM_MAPPINGS,
        "token_no_default_policy": True,
        "token_policies": [policy],
        "token_ttl": OPENBAO_BUILDKITE_MAX_LEASE_SECONDS,
        "token_max_ttl": OPENBAO_BUILDKITE_MAX_LEASE_SECONDS,
        "token_explicit_max_ttl": OPENBAO_BUILDKITE_MAX_LEASE_SECONDS,
        "token_num_uses": 1,
    }


class OpenBaoBuildkiteCMLConfigurator:
    """Verify the accepted mount and configure one exact deployment capability."""

    def __init__(
        self,
        url: str,
        admin_token: str,
        pipeline_id: str,
        device_id: str,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not admin_token:
            raise SecretError("OpenBao CML operator configuration missing")
        self._pipeline_id = validate_pipeline_id(pipeline_id)
        self._device_id = validate_device_id(device_id)
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
    ) -> OpenBaoBuildkiteCMLConfigurator:
        values = environment if environment is not None else os.environ
        required = (
            "NCDP_OPENBAO_URL",
            "NCDP_BUILDKITE_PIPELINE_ID",
            "NCDP_BUILDKITE_CML_DEVICE_ID",
            "BAO_TOKEN",
        )
        if any(not values.get(name) for name in required):
            raise SecretError("OpenBao CML operator configuration missing")
        return cls(
            values["NCDP_OPENBAO_URL"],
            values["BAO_TOKEN"],
            values["NCDP_BUILDKITE_PIPELINE_ID"],
            values["NCDP_BUILDKITE_CML_DEVICE_ID"],
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
            raise SecretError("OpenBao CML operator request unauthorized")
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

    def _verify_mount_and_identity_role(self) -> None:
        mounts = self._data(self._request("GET", "/v1/sys/auth", expected_status=200))
        mount = mounts.get(JWT_MOUNT)
        if not (
            isinstance(mount, dict)
            and mount.get("type") == "jwt"
            and mount.get("description") == JWT_MOUNT_DESCRIPTION
        ):
            raise SecretError("OpenBao jwt/ auth mount is not owned by NCDP")
        role = self._data(
            self._request(
                "GET",
                f"/v1/auth/jwt/role/{OPENBAO_BUILDKITE_JWT_ROLE}",
                expected_status=200,
            )
        )
        if any(
            role.get(key) != value
            for key, value in buildkite_jwt_role_config(self._pipeline_id).items()
        ):
            raise SecretError("OpenBao Buildkite identity role verification failed")

    def configure(self) -> tuple[str, str]:
        self._verify_mount_and_identity_role()
        policy_name = cml_device_policy_name(self._device_id)
        policy = cml_device_policy(self._device_id)
        policy_path = f"/v1/sys/policies/acl/{policy_name}"
        self._request("PUT", policy_path, json={"policy": policy}, expected_status=204)
        policy_data = self._data(self._request("GET", policy_path, expected_status=200))
        if policy_data.get("policy") != policy:
            raise SecretError("OpenBao CML policy verification failed")

        role_name = cml_deploy_role_name(self._device_id)
        role = cml_deploy_role_config(self._pipeline_id, self._device_id)
        role_path = f"/v1/auth/jwt/role/{role_name}"
        self._request("POST", role_path, json=role, expected_status=204)
        role_data = self._data(self._request("GET", role_path, expected_status=200))
        if any(role_data.get(key) != value for key, value in role.items()):
            raise SecretError("OpenBao CML deployment role verification failed")
        self._verify_mount_and_identity_role()
        return policy_name, role_name


def configure_cml_from_environment(
    environment: Mapping[str, str] | None = None,
) -> tuple[str, str]:
    return OpenBaoBuildkiteCMLConfigurator.from_environment(environment).configure()
