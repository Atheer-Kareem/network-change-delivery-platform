"""Secret-safe SNMPv3 credential identities and exact OpenBao consumers."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

import httpx

from network_change_delivery.buildkite_identity import (
    OPENBAO_BUILDKITE_MAX_LEASE_SECONDS,
    BuildkiteOIDCJWT,
)
from network_change_delivery.buildkite_policy import BuildkiteDeploymentContext
from network_change_delivery.secrets import (
    SecretError,
    create_openbao_client,
    validate_openbao_url,
)
from network_change_delivery.snmp_telemetry import SnmpCredentialReference

SNMP_GENERATION = "v1"
SNMP_AUTH_PROTOCOL = "SHA256"
SNMP_PRIVACY_PROTOCOL = "AES128"
SNMP_SECURITY_LEVEL = "authPriv"
SNMP_SECRET_FIELDS = frozenset({"username", "authentication_secret", "privacy_secret"})

_GENERATION = re.compile(r"v[1-9][0-9]{0,8}")
_USERNAME = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,31}")
_IDENTITY_FIELDS = {
    "pipeline_id": "pipeline_id",
    "build_commit": "commit",
    "build_branch": "branch",
    "step_key": "step_key",
    "job_id": "job_id",
}


def validate_snmp_generation(value: str) -> str:
    """Require one immutable, canonical versioned generation."""
    if _GENERATION.fullmatch(value) is None:
        raise SecretError("SNMP credential generation rejected")
    return value


def snmp_username(device_id: int, generation: str = SNMP_GENERATION) -> str:
    """Return one deterministic cross-vendor-safe controlled principal."""
    if device_id not in {1, 2}:
        raise SecretError("SNMP credential device rejected")
    generation = validate_snmp_generation(generation)
    value = f"ncdp_snmp_d{device_id}_{generation}"
    if _USERNAME.fullmatch(value) is None:
        raise SecretError("SNMP credential username rejected")
    return value


def snmp_secret_logical_path(device_id: int, generation: str) -> str:
    if device_id not in {1, 2}:
        raise SecretError("SNMP credential device rejected")
    return f"ncdp/devices/{device_id}/snmpv3/{validate_snmp_generation(generation)}"


def snmp_secret_api_path(device_id: int, generation: str) -> str:
    logical = snmp_secret_logical_path(device_id, generation)
    return f"/v1/ncdp/data/{logical.removeprefix('ncdp/')}"


def snmp_provision_role_name(device_id: int) -> str:
    if device_id not in {1, 2}:
        raise SecretError("SNMP credential device rejected")
    return f"ncdp-buildkite-snmp-provision-device-{device_id}"


def snmp_provision_policy_name(device_id: int) -> str:
    if device_id not in {1, 2}:
        raise SecretError("SNMP credential device rejected")
    return f"ncdp-buildkite-snmp-device-{device_id}-v1-read"


@dataclass(frozen=True, repr=False)
class SnmpProvisioningCredentials:
    """Ephemeral runtime-only authPriv values with a redacted representation."""

    username: str
    authentication_secret: str
    privacy_secret: str

    def __post_init__(self) -> None:
        if _USERNAME.fullmatch(self.username) is None:
            raise SecretError("OpenBao SNMP credential payload invalid")
        if (
            len(self.authentication_secret) < 16
            or len(self.privacy_secret) < 16
            or self.authentication_secret == self.privacy_secret
        ):
            raise SecretError("OpenBao SNMP credential payload invalid")

    def __repr__(self) -> str:
        return (
            "SnmpProvisioningCredentials(username=<controlled>, "
            "authentication_secret=<redacted>, privacy_secret=<redacted>)"
        )


def _response_data(response: httpx.Response) -> dict[str, object]:
    try:
        payload = response.json()
    except ValueError:
        raise SecretError("OpenBao returned invalid JSON or schema") from None
    if not isinstance(payload, dict):
        raise SecretError("OpenBao returned invalid JSON or schema")
    return payload


def _credentials(
    response: httpx.Response, expected_username: str
) -> SnmpProvisioningCredentials:
    payload = _response_data(response)
    outer = payload.get("data")
    data = outer.get("data") if isinstance(outer, dict) else None
    if not isinstance(data, dict) or set(data) != SNMP_SECRET_FIELDS:
        raise SecretError("OpenBao SNMP credential payload invalid")
    values = (
        data.get("username"),
        data.get("authentication_secret"),
        data.get("privacy_secret"),
    )
    if not all(isinstance(value, str) and value for value in values):
        raise SecretError("OpenBao SNMP credential payload invalid")
    username, authentication, privacy = values
    if username != expected_username:
        raise SecretError("OpenBao SNMP credential identity mismatch")
    return SnmpProvisioningCredentials(username, authentication, privacy)  # type: ignore[arg-type]


class BuildkiteOpenBaoSnmpProvisioningProvider:
    """One fresh JWT, one exact role, and one exact generation read."""

    def __init__(
        self,
        jwt_source: Callable[[], BuildkiteOIDCJWT],
        context: BuildkiteDeploymentContext,
        credential: SnmpCredentialReference,
        username: str,
        url: str,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._jwt_source: Callable[[], BuildkiteOIDCJWT] | None = jwt_source
        self._context = context
        self._credential = credential
        self._username = username
        self._client = create_openbao_client(
            validate_openbao_url(url), transport=transport
        )
        self._consumed = False

    def load(self) -> SnmpProvisioningCredentials:
        """Acquire capability only when called, then consume it exactly once."""
        if self._consumed or self._jwt_source is None:
            raise SecretError("Buildkite SNMP credential already consumed")
        self._consumed = True
        source, self._jwt_source = self._jwt_source, None
        jwt = source()
        device_id, generation = _reference_parts(self._credential)
        policy = snmp_provision_policy_name(device_id)
        try:
            login = self._client.post(
                "/v1/auth/jwt/login",
                json={"role": snmp_provision_role_name(device_id), "jwt": jwt.value},
            )
        except (httpx.TimeoutException, httpx.RequestError):
            raise SecretError("OpenBao unavailable or timed out") from None
        if login.status_code != 200:
            raise SecretError("OpenBao SNMP JWT authentication failed")
        auth = _response_data(login).get("auth")
        if not isinstance(auth, dict):
            raise SecretError("OpenBao returned invalid JSON or schema")
        token = auth.get("client_token")
        lease = auth.get("lease_duration")
        if (
            not isinstance(token, str)
            or not token
            or not isinstance(lease, int)
            or isinstance(lease, bool)
            or not 0 < lease <= OPENBAO_BUILDKITE_MAX_LEASE_SECONDS
            or auth.get("token_policies") != [policy]
            or auth.get("policies") != [policy]
            or auth.get("identity_policies") not in (None, [])
        ):
            raise SecretError("OpenBao issued unauthorized SNMP capability")
        for field in ("external_namespace_policies", "external_namespace_policy_paths"):
            if auth.get(field) not in (None, [], {}):
                raise SecretError("OpenBao issued unauthorized SNMP capability")
        metadata = auth.get("metadata")
        if not isinstance(metadata, dict):
            raise SecretError("OpenBao returned invalid identity metadata")
        for claim, field in _IDENTITY_FIELDS.items():
            if metadata.get(claim) != getattr(self._context, field):
                raise SecretError(f"OpenBao Buildkite identity mismatch: {claim}")
        try:
            response = self._client.get(
                snmp_secret_api_path(device_id, generation),
                headers={"X-Vault-Token": token},
            )
        except (httpx.TimeoutException, httpx.RequestError):
            raise SecretError("OpenBao unavailable or timed out") from None
        if response.status_code != 200:
            raise SecretError("OpenBao SNMP secret read failed")
        return _credentials(response, self._username)


class OpenBaoSnmpObservabilitySource:
    """One AppRole login and one exact device-generation read per instance."""

    def __init__(
        self,
        url: str,
        role_id: str,
        secret_id: str,
        credential: SnmpCredentialReference,
        username: str,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not role_id or not secret_id:
            raise SecretError("OpenBao SNMP source configuration missing")
        self._client = create_openbao_client(
            validate_openbao_url(url), transport=transport
        )
        self._role_id = role_id
        self._secret_id = secret_id
        self._credential = credential
        self._username = username
        self._consumed = False

    def load(self) -> SnmpProvisioningCredentials:
        if self._consumed:
            raise SecretError("OpenBao SNMP source credential already consumed")
        self._consumed = True
        device_id, generation = _reference_parts(self._credential)
        try:
            login = self._client.post(
                "/v1/auth/approle/login",
                json={"role_id": self._role_id, "secret_id": self._secret_id},
            )
        except (httpx.TimeoutException, httpx.RequestError):
            raise SecretError("OpenBao unavailable or timed out") from None
        if login.status_code != 200:
            raise SecretError("OpenBao SNMP source authentication failed")
        auth = _response_data(login).get("auth")
        if not isinstance(auth, dict):
            raise SecretError("OpenBao returned invalid JSON or schema")
        from network_change_delivery.openbao_snmp_config import (
            SNMP_OBSERVABILITY_POLICY_NAME,
        )

        token = auth.get("client_token")
        lease = auth.get("lease_duration")
        if (
            not isinstance(token, str)
            or not token
            or not isinstance(lease, int)
            or isinstance(lease, bool)
            or not 0 < lease <= 300
            or auth.get("token_policies") != [SNMP_OBSERVABILITY_POLICY_NAME]
            or auth.get("policies") != [SNMP_OBSERVABILITY_POLICY_NAME]
            or auth.get("identity_policies") not in (None, [])
        ):
            raise SecretError("OpenBao issued unauthorized SNMP source capability")
        for field in ("external_namespace_policies", "external_namespace_policy_paths"):
            if auth.get(field) not in (None, [], {}):
                raise SecretError("OpenBao issued unauthorized SNMP source capability")
        try:
            response = self._client.get(
                snmp_secret_api_path(device_id, generation),
                headers={"X-Vault-Token": token},
            )
        except (httpx.TimeoutException, httpx.RequestError):
            raise SecretError("OpenBao unavailable or timed out") from None
        if response.status_code != 200:
            raise SecretError("OpenBao SNMP source read failed")
        return _credentials(response, self._username)


def _reference_parts(reference: SnmpCredentialReference) -> tuple[int, str]:
    device_id = int(reference.device.removeprefix("netbox:dcim.device:"))
    prefix = f"snmpv3:netbox:dcim.device:{device_id}:generation:"
    generation = reference.reference.removeprefix(prefix)
    if reference.reference != prefix + generation:
        raise SecretError("SNMP credential reference rejected")
    validate_snmp_generation(generation)
    if reference.auth_selector != f"device_{device_id}_{generation}":
        raise SecretError("SNMP credential selector rejected")
    return device_id, generation
