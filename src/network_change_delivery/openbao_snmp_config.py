"""Operator-only OpenBao contracts for versioned SNMPv3 credentials."""

from __future__ import annotations

import secrets
import string
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

import httpx

from network_change_delivery.buildkite_identity import (
    OPENBAO_BUILDKITE_JWT_AUDIENCE,
    OPENBAO_BUILDKITE_MAX_LEASE_SECONDS,
)
from network_change_delivery.openbao_jwt_config import (
    JWT_CLAIM_MAPPINGS,
    JWT_MOUNT,
    JWT_MOUNT_DESCRIPTION,
    validate_pipeline_id,
)
from network_change_delivery.secrets import (
    SecretError,
    create_openbao_client,
    validate_openbao_url,
)
from network_change_delivery.snmp_credentials import (
    SNMP_GENERATION,
    SNMP_SECRET_FIELDS,
    snmp_provision_policy_name,
    snmp_provision_role_name,
    snmp_secret_api_path,
    snmp_secret_logical_path,
    snmp_username,
    validate_snmp_generation,
)

SNMP_OBSERVABILITY_POLICY_NAME = "ncdp-observability-snmp-read"
SNMP_OBSERVABILITY_ROLE_NAME = "ncdp-observability-snmp-source"
SNMP_OBSERVABILITY_POLICY = """path "ncdp/data/devices/1/snmpv3/v1" {
  capabilities = ["read"]
}
path "ncdp/data/devices/2/snmpv3/v1" {
  capabilities = ["read"]
}
"""
SNMP_OBSERVABILITY_ROLE = {
    "bind_secret_id": True,
    "secret_id_ttl": 1800,
    "secret_id_num_uses": 2,
    "token_no_default_policy": True,
    "token_policies": [SNMP_OBSERVABILITY_POLICY_NAME],
    "token_ttl": 300,
    "token_max_ttl": 300,
    "token_num_uses": 1,
}
_SECRET_ALPHABET = string.ascii_letters + string.digits + "-_.~"
_SECRET_LENGTH = 48


def snmp_provision_policy(device_id: int, generation: str = "v1") -> str:
    logical = snmp_secret_logical_path(device_id, generation)
    path = f"ncdp/data/{logical.removeprefix('ncdp/')}"
    return f'path "{path}" {{\n  capabilities = ["read"]\n}}\n'


def snmp_provision_role_config(pipeline_id: str, device_id: int) -> dict[str, object]:
    return {
        "role_type": "jwt",
        "bound_audiences": [OPENBAO_BUILDKITE_JWT_AUDIENCE],
        "bound_subject": validate_pipeline_id(pipeline_id),
        "user_claim": "sub",
        "bound_claims_type": "string",
        "bound_claims": {"build_branch": "main", "step_key": "deploy-gate"},
        "claim_mappings": JWT_CLAIM_MAPPINGS,
        "token_no_default_policy": True,
        "token_policies": [snmp_provision_policy_name(device_id)],
        "token_ttl": OPENBAO_BUILDKITE_MAX_LEASE_SECONDS,
        "token_max_ttl": OPENBAO_BUILDKITE_MAX_LEASE_SECONDS,
        "token_explicit_max_ttl": OPENBAO_BUILDKITE_MAX_LEASE_SECONDS,
        "token_num_uses": 1,
    }


class SnmpGenerationOutcome(StrEnum):
    CREATED = "CREATED"
    ALREADY_EXISTS = "ALREADY_EXISTS"
    PARTIAL = "PARTIAL"


class SnmpGenerationPartialError(SecretError):
    """Creation may have succeeded but exact read-back was not proven."""

    outcome = SnmpGenerationOutcome.PARTIAL


@dataclass(frozen=True)
class SnmpGenerationResult:
    device_id: int
    generation: str
    logical_path: str
    username: str
    outcome: SnmpGenerationOutcome


class OpenBaoSnmpConfigurator:
    """Configure exact SNMP authorities and create immutable generations."""

    def __init__(
        self,
        url: str,
        admin_token: str,
        pipeline_id: str,
        *,
        transport: httpx.BaseTransport | None = None,
        random_choice=secrets.choice,
    ) -> None:
        if not admin_token:
            raise SecretError("OpenBao SNMP operator configuration missing")
        self._pipeline_id = validate_pipeline_id(pipeline_id)
        self._client = create_openbao_client(
            validate_openbao_url(url), transport=transport
        )
        self._headers = {"X-Vault-Token": admin_token}
        self._random_choice = random_choice

    @classmethod
    def from_environment(
        cls,
        environment: Mapping[str, str],
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> OpenBaoSnmpConfigurator:
        required = ("NCDP_OPENBAO_URL", "NCDP_BUILDKITE_PIPELINE_ID", "BAO_TOKEN")
        if any(not environment.get(name) for name in required):
            raise SecretError("OpenBao SNMP operator configuration missing")
        return cls(
            environment["NCDP_OPENBAO_URL"],
            environment["BAO_TOKEN"],
            environment["NCDP_BUILDKITE_PIPELINE_ID"],
            transport=transport,
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, object] | None = None,
        statuses: frozenset[int],
    ) -> httpx.Response:
        try:
            response = self._client.request(
                method, path, headers=self._headers, json=body
            )
        except (httpx.TimeoutException, httpx.RequestError):
            raise SecretError("OpenBao unavailable or timed out") from None
        if response.status_code not in statuses:
            raise SecretError("OpenBao SNMP operator request failed")
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

    def _verify_mounts(self) -> None:
        mounts = self._data(
            self._request("GET", "/v1/sys/auth", statuses=frozenset({200}))
        )
        jwt = mounts.get(JWT_MOUNT)
        approle = mounts.get("approle/")
        if not (
            isinstance(jwt, dict)
            and jwt.get("type") == "jwt"
            and jwt.get("description") == JWT_MOUNT_DESCRIPTION
            and isinstance(approle, dict)
            and approle.get("type") == "approle"
        ):
            raise SecretError("OpenBao SNMP auth mounts rejected")

    def _ensure_policy(self, name: str, policy: str, message: str) -> None:
        path = f"/v1/sys/policies/acl/{name}"
        existing = self._request("GET", path, statuses=frozenset({200, 404}))
        if existing.status_code == 200:
            if self._data(existing).get("policy") != policy:
                raise SecretError(message)
            return
        self._request("PUT", path, body={"policy": policy}, statuses=frozenset({204}))
        if (
            self._data(self._request("GET", path, statuses=frozenset({200}))).get(
                "policy"
            )
            != policy
        ):
            raise SecretError(message)

    def _preflight_policy(self, name: str, policy: str, message: str) -> None:
        existing = self._request(
            "GET",
            f"/v1/sys/policies/acl/{name}",
            statuses=frozenset({200, 404}),
        )
        if existing.status_code == 200 and self._data(existing).get("policy") != policy:
            raise SecretError(message)

    def _ensure_role(
        self, mount: str, name: str, role: Mapping[str, object], message: str
    ) -> None:
        path = f"/v1/auth/{mount}/role/{name}"
        existing = self._request("GET", path, statuses=frozenset({200, 404}))
        if existing.status_code == 200:
            actual = self._data(existing)
            if any(actual.get(key) != value for key, value in role.items()):
                raise SecretError(message)
            return
        self._request("POST", path, body=dict(role), statuses=frozenset({204}))
        actual = self._data(self._request("GET", path, statuses=frozenset({200})))
        if any(actual.get(key) != value for key, value in role.items()):
            raise SecretError(message)

    def _preflight_role(
        self, mount: str, name: str, role: Mapping[str, object], message: str
    ) -> None:
        existing = self._request(
            "GET",
            f"/v1/auth/{mount}/role/{name}",
            statuses=frozenset({200, 404}),
        )
        if existing.status_code == 200:
            actual = self._data(existing)
            if any(actual.get(key) != value for key, value in role.items()):
                raise SecretError(message)

    def configure_authorities(self) -> tuple[str, ...]:
        """Write, read back, and verify only exact reviewed policies and roles."""
        self._verify_mounts()
        resources: list[tuple[str, str, str, Mapping[str, object]]] = [
            (
                snmp_provision_policy_name(device_id),
                snmp_provision_policy(device_id),
                snmp_provision_role_name(device_id),
                snmp_provision_role_config(self._pipeline_id, device_id),
            )
            for device_id in (1, 2)
        ]
        resources.append(
            (
                SNMP_OBSERVABILITY_POLICY_NAME,
                SNMP_OBSERVABILITY_POLICY,
                SNMP_OBSERVABILITY_ROLE_NAME,
                SNMP_OBSERVABILITY_ROLE,
            )
        )
        for index, (policy_name, policy, role_name, role) in enumerate(resources):
            self._preflight_policy(
                policy_name, policy, "OpenBao SNMP policy verification failed"
            )
            self._preflight_role(
                "jwt" if index < 2 else "approle",
                role_name,
                role,
                "OpenBao SNMP role verification failed",
            )

        configured: list[str] = []
        for index, (policy_name, policy, role_name, role) in enumerate(resources):
            self._ensure_policy(
                policy_name, policy, "OpenBao SNMP policy verification failed"
            )
            self._ensure_role(
                "jwt" if index < 2 else "approle",
                role_name,
                role,
                "OpenBao SNMP role verification failed",
            )
            configured.extend((policy_name, role_name))
        self._verify_mounts()
        return tuple(configured)

    def create_generation(
        self, device_id: int, generation: str = "v1"
    ) -> SnmpGenerationResult:
        """Create one CAS-protected generation without temporary plaintext files."""
        generation = validate_snmp_generation(generation)
        if generation != SNMP_GENERATION:
            raise SecretError("OpenBao SNMP generation is not reviewed")
        logical = snmp_secret_logical_path(device_id, generation)
        username = snmp_username(device_id, generation)
        api_path = snmp_secret_api_path(device_id, generation)
        existing = self._request("GET", api_path, statuses=frozenset({200, 404}))
        if existing.status_code == 200:
            outer = self._data(existing)
            existing_data = outer.get("data")
            if (
                not isinstance(existing_data, dict)
                or set(existing_data) != SNMP_SECRET_FIELDS
                or existing_data.get("username") != username
                or not isinstance(existing_data.get("authentication_secret"), str)
                or not existing_data.get("authentication_secret")
                or not isinstance(existing_data.get("privacy_secret"), str)
                or not existing_data.get("privacy_secret")
                or existing_data.get("authentication_secret")
                == existing_data.get("privacy_secret")
            ):
                raise SecretError("OpenBao existing SNMP generation rejected")
            return SnmpGenerationResult(
                device_id,
                generation,
                logical,
                username,
                SnmpGenerationOutcome.ALREADY_EXISTS,
            )
        authentication = "".join(
            self._random_choice(_SECRET_ALPHABET) for _ in range(_SECRET_LENGTH)
        )
        privacy = "".join(
            self._random_choice(_SECRET_ALPHABET) for _ in range(_SECRET_LENGTH)
        )
        if authentication == privacy:
            raise SecretError("SNMP secret generation collision")
        payload = {
            "data": {
                "username": username,
                "authentication_secret": authentication,
                "privacy_secret": privacy,
            },
            "options": {"cas": 0},
        }
        created = self._request(
            "POST", api_path, body=payload, statuses=frozenset({200, 204, 400})
        )
        if created.status_code == 400:
            raise SecretError("OpenBao SNMP generation create-only conflict")
        try:
            readback = self._data(
                self._request("GET", api_path, statuses=frozenset({200}))
            ).get("data")
            if (
                not isinstance(readback, dict)
                or set(readback) != SNMP_SECRET_FIELDS
                or readback != payload["data"]
            ):
                raise SecretError("OpenBao SNMP generation verification failed")
        except SecretError:
            raise SnmpGenerationPartialError(
                "OpenBao SNMP generation may exist but read-back verification failed"
            ) from None
        return SnmpGenerationResult(
            device_id, generation, logical, username, SnmpGenerationOutcome.CREATED
        )
