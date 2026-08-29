"""Bounded SecretID issuer for the future persistent SNMP materializer."""

from __future__ import annotations

import os
import tempfile
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

import httpx

from network_change_delivery.observability_private_paths import (
    ObservabilityPrivatePathError,
    ensure_private_tree,
    validate_private_file,
)
from network_change_delivery.openbao_snmp_config import SNMP_OBSERVABILITY_ROLE_NAME
from network_change_delivery.secrets import (
    SecretError,
    create_openbao_client,
    validate_openbao_url,
)

SNMP_BOOTSTRAP_POLICY_NAME = "ncdp-observability-snmp-secretid-issuer"
SNMP_BOOTSTRAP_ROLE_NAME = "ncdp-observability-snmp-bootstrap"
_SOURCE_SECRET_ID_PATH = f"auth/approle/role/{SNMP_OBSERVABILITY_ROLE_NAME}/secret-id"
SNMP_BOOTSTRAP_POLICY = f"""path "{_SOURCE_SECRET_ID_PATH}" {{
  capabilities = ["update"]
}}
"""
SNMP_BOOTSTRAP_ROLE = {
    "bind_secret_id": True,
    "secret_id_ttl": 0,
    "secret_id_num_uses": 0,
    "token_no_default_policy": True,
    "token_policies": [SNMP_BOOTSTRAP_POLICY_NAME],
    "token_ttl": 60,
    "token_max_ttl": 60,
    "token_num_uses": 1,
}


@dataclass(frozen=True, repr=False)
class SnmpMachineBootstrap:
    bootstrap_role_id: str
    bootstrap_secret_id: str
    source_role_id: str

    def __post_init__(self) -> None:
        _validate_private_identifiers(
            self.bootstrap_role_id,
            self.bootstrap_secret_id,
            self.source_role_id,
        )


@dataclass(frozen=True, repr=False)
class SnmpSourceLogin:
    role_id: str
    secret_id: str

    def __post_init__(self) -> None:
        _validate_private_identifiers(self.role_id, self.secret_id)


def _validate_private_identifiers(*values: str) -> None:
    if any(
        not value
        or len(value) > 8192
        or any(ord(character) < 0x21 or ord(character) > 0x7E for character in value)
        for value in values
    ):
        raise SecretError("OpenBao SNMP bootstrap identifier rejected")


class OpenBaoSnmpBootstrap:
    """Configure or consume only the SNMP source SecretID issuer."""

    def __init__(
        self, url: str, *, transport: httpx.BaseTransport | None = None
    ) -> None:
        self._client = create_openbao_client(
            validate_openbao_url(url), transport=transport
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        token: str | None = None,
        body: dict[str, object] | None = None,
        status: int | frozenset[int],
    ) -> httpx.Response:
        try:
            response = self._client.request(
                method,
                path,
                headers={"X-Vault-Token": token} if token else None,
                json=body,
            )
        except (httpx.TimeoutException, httpx.RequestError):
            raise SecretError("OpenBao SNMP bootstrap unavailable") from None
        expected = status if isinstance(status, frozenset) else frozenset({status})
        if response.status_code not in expected:
            raise SecretError("OpenBao SNMP bootstrap request failed")
        return response

    @staticmethod
    def _data(response: httpx.Response) -> dict[str, object]:
        try:
            data = response.json().get("data")
        except (AttributeError, ValueError):
            data = None
        if not isinstance(data, dict):
            raise SecretError("OpenBao SNMP bootstrap response rejected")
        return data

    def configure(self, admin_token: str) -> SnmpMachineBootstrap:
        """Configure, verify, and issue one long-lived private bootstrap pair."""
        if not admin_token:
            raise SecretError("OpenBao SNMP bootstrap operator missing")
        policy_path = f"/v1/sys/policies/acl/{SNMP_BOOTSTRAP_POLICY_NAME}"
        role_path = f"/v1/auth/approle/role/{SNMP_BOOTSTRAP_ROLE_NAME}"
        policy_response = self._request(
            "GET", policy_path, token=admin_token, status=frozenset({200, 404})
        )
        role_response = self._request(
            "GET", role_path, token=admin_token, status=frozenset({200, 404})
        )
        if (
            policy_response.status_code == 200
            and self._data(policy_response).get("policy") != SNMP_BOOTSTRAP_POLICY
        ):
            raise SecretError("OpenBao SNMP bootstrap verification failed")
        if role_response.status_code == 200 and any(
            self._data(role_response).get(key) != value
            for key, value in SNMP_BOOTSTRAP_ROLE.items()
        ):
            raise SecretError("OpenBao SNMP bootstrap verification failed")
        if policy_response.status_code == 404:
            self._request(
                "PUT",
                policy_path,
                token=admin_token,
                body={"policy": SNMP_BOOTSTRAP_POLICY},
                status=204,
            )
            policy_response = self._request(
                "GET", policy_path, token=admin_token, status=200
            )
        if role_response.status_code == 404:
            self._request(
                "POST",
                role_path,
                token=admin_token,
                body=SNMP_BOOTSTRAP_ROLE,
                status=204,
            )
            role_response = self._request(
                "GET", role_path, token=admin_token, status=200
            )
        policy = self._data(policy_response)
        role = self._data(role_response)
        if policy.get("policy") != SNMP_BOOTSTRAP_POLICY or any(
            role.get(key) != value for key, value in SNMP_BOOTSTRAP_ROLE.items()
        ):
            raise SecretError("OpenBao SNMP bootstrap verification failed")
        bootstrap_role_id = self._data(
            self._request("GET", f"{role_path}/role-id", token=admin_token, status=200)
        ).get("role_id")
        bootstrap_secret_id = self._data(
            self._request(
                "POST",
                f"{role_path}/secret-id",
                token=admin_token,
                body={},
                status=200,
            )
        ).get("secret_id")
        source_role_id = self._data(
            self._request(
                "GET",
                f"/v1/auth/approle/role/{SNMP_OBSERVABILITY_ROLE_NAME}/role-id",
                token=admin_token,
                status=200,
            )
        ).get("role_id")
        if (
            not isinstance(bootstrap_role_id, str)
            or not bootstrap_role_id
            or not isinstance(bootstrap_secret_id, str)
            or not bootstrap_secret_id
            or not isinstance(source_role_id, str)
            or not source_role_id
        ):
            raise SecretError("OpenBao SNMP bootstrap issuance failed")
        return SnmpMachineBootstrap(
            bootstrap_role_id, bootstrap_secret_id, source_role_id
        )

    def issue_source_login(
        self, role_id: str, secret_id: str, source_role_id: str
    ) -> SnmpSourceLogin:
        """Spend one bootstrap token to issue one bounded source SecretID."""
        response = self._request(
            "POST",
            "/v1/auth/approle/login",
            body={"role_id": role_id, "secret_id": secret_id},
            status=200,
        )
        try:
            auth = response.json().get("auth")
        except (AttributeError, ValueError):
            auth = None
        token = auth.get("client_token") if isinstance(auth, dict) else None
        lease = auth.get("lease_duration") if isinstance(auth, dict) else None
        if (
            not isinstance(token, str)
            or not token
            or not isinstance(lease, int)
            or isinstance(lease, bool)
            or not 0 < lease <= 60
            or auth.get("token_policies") != [SNMP_BOOTSTRAP_POLICY_NAME]
            or auth.get("policies") != [SNMP_BOOTSTRAP_POLICY_NAME]
            or auth.get("identity_policies") not in (None, [])
        ):
            raise SecretError("OpenBao SNMP bootstrap login failed")
        for field in ("external_namespace_policies", "external_namespace_policy_paths"):
            if auth.get(field) not in (None, [], {}):
                raise SecretError("OpenBao SNMP bootstrap login failed")
        source_path = f"/v1/auth/approle/role/{SNMP_OBSERVABILITY_ROLE_NAME}"
        source_secret_id = self._data(
            self._request(
                "POST",
                f"{source_path}/secret-id",
                token=token,
                body={},
                status=200,
            )
        ).get("secret_id")
        if (
            not isinstance(source_role_id, str)
            or not source_role_id
            or not isinstance(source_secret_id, str)
            or not source_secret_id
        ):
            raise SecretError("OpenBao SNMP source bootstrap failed")
        return SnmpSourceLogin(source_role_id, source_secret_id)


def persist_snmp_machine_bootstrap(
    root: Path, bootstrap: SnmpMachineBootstrap
) -> tuple[Path, Path, Path]:
    """Atomically publish distinct private machine-bootstrap files."""
    try:
        ensure_private_tree(root, "snmp-openbao")
        directory = root / "snmp-openbao"
        paths = (
            directory / "bootstrap-role-id",
            directory / "bootstrap-secret-id",
            directory / "source-role-id",
        )
        for path, value in zip(
            paths,
            (
                bootstrap.bootstrap_role_id,
                bootstrap.bootstrap_secret_id,
                bootstrap.source_role_id,
            ),
            strict=True,
        ):
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{path.name}.", dir=directory
            )
            temporary = Path(temporary_name)
            try:
                try:
                    os.fchmod(descriptor, 0o600)
                    os.write(descriptor, value.encode())
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
                validate_private_file(temporary, maximum_bytes=8192)
                temporary.replace(path)
                validate_private_file(path, maximum_bytes=8192)
            except (OSError, ObservabilityPrivatePathError):
                with suppress(FileNotFoundError):
                    temporary.unlink()
                raise
        directory_descriptor = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
        return paths
    except (OSError, ObservabilityPrivatePathError) as error:
        raise SecretError("SNMP machine bootstrap persistence failed") from error
