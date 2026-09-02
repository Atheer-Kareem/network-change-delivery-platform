"""Dedicated exact-path OpenBao AppRole for Oxidized source materialization."""

from __future__ import annotations

import os
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

import httpx

from network_change_delivery.oxidized_private_paths import (
    OxidizedPrivatePathError,
    ensure_private_directory,
    validate_oxidized_root,
    validate_private_file,
)
from network_change_delivery.secrets import (
    SecretError,
    create_openbao_client,
    validate_openbao_url,
)

OXIDIZED_POLICY_NAME = "ncdp-oxidized-device-read"
OXIDIZED_ROLE_NAME = "ncdp-oxidized-source"
OXIDIZED_POLICY = """path "ncdp/data/devices/1/ssh" {
  capabilities = ["read"]
}
path "ncdp/data/devices/2/ssh" {
  capabilities = ["read"]
}
path "ncdp/data/devices/8/ssh" {
  capabilities = ["read"]
}
path "ncdp/data/devices/9/ssh" {
  capabilities = ["read"]
}
"""
OXIDIZED_ROLE = {
    "bind_secret_id": True,
    "secret_id_ttl": 1800,
    "secret_id_num_uses": 10,
    "token_no_default_policy": True,
    "token_policies": [OXIDIZED_POLICY_NAME],
    "token_ttl": 300,
    "token_max_ttl": 300,
    "token_num_uses": 1,
}


@dataclass(frozen=True, repr=False)
class OxidizedAppRoleBootstrap:
    role_id: str
    secret_id: str


class OpenBaoOxidizedConfigurator:
    """Configure, read back, and issue one dedicated materializer bootstrap."""

    def __init__(
        self,
        url: str,
        admin_token: str,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not admin_token:
            raise SecretError("OpenBao Oxidized operator configuration missing")
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
    ) -> OpenBaoOxidizedConfigurator:
        values = environment if environment is not None else os.environ
        url = values.get("NCDP_OXIDIZED_OPENBAO_URL")
        token = values.get("BAO_TOKEN")
        if not url or not token:
            raise SecretError("OpenBao Oxidized operator configuration missing")
        return cls(url, token, transport=transport)

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, object] | None = None,
        status: int,
    ) -> httpx.Response:
        try:
            response = self._client.request(
                method, path, headers=self._headers, json=body
            )
        except (httpx.TimeoutException, httpx.RequestError):
            raise SecretError("OpenBao unavailable or timed out") from None
        if response.status_code in {400, 401, 403}:
            raise SecretError("OpenBao Oxidized operator request unauthorized")
        if response.status_code != status:
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

    def _verify(self) -> None:
        mounts = self._data(self._request("GET", "/v1/sys/auth", status=200))
        approle = mounts.get("approle/")
        if not isinstance(approle, dict) or approle.get("type") != "approle":
            raise SecretError("OpenBao approle/ auth mount unavailable")
        policy_path = f"/v1/sys/policies/acl/{OXIDIZED_POLICY_NAME}"
        policy = self._data(self._request("GET", policy_path, status=200))
        if policy.get("policy") != OXIDIZED_POLICY:
            raise SecretError("OpenBao Oxidized policy verification failed")
        role_path = f"/v1/auth/approle/role/{OXIDIZED_ROLE_NAME}"
        role = self._data(self._request("GET", role_path, status=200))
        if any(role.get(key) != value for key, value in OXIDIZED_ROLE.items()):
            raise SecretError("OpenBao Oxidized role verification failed")

    def issue_bootstrap(self) -> OxidizedAppRoleBootstrap:
        """Verify existing resources and issue a bounded fresh SecretID."""
        self._verify()
        role_path = f"/v1/auth/approle/role/{OXIDIZED_ROLE_NAME}"
        role_id = self._data(
            self._request("GET", f"{role_path}/role-id", status=200)
        ).get("role_id")
        secret_id = self._data(
            self._request("POST", f"{role_path}/secret-id", body={}, status=200)
        ).get("secret_id")
        if not isinstance(role_id, str) or not role_id:
            raise SecretError("OpenBao Oxidized bootstrap issuance failed")
        if not isinstance(secret_id, str) or not secret_id:
            raise SecretError("OpenBao Oxidized bootstrap issuance failed")
        return OxidizedAppRoleBootstrap(role_id, secret_id)

    def configure(self) -> OxidizedAppRoleBootstrap:
        """Deterministically configure resources, verify, and issue bootstrap."""
        mounts = self._data(self._request("GET", "/v1/sys/auth", status=200))
        approle = mounts.get("approle/")
        if not isinstance(approle, dict) or approle.get("type") != "approle":
            raise SecretError("OpenBao approle/ auth mount unavailable")
        policy_path = f"/v1/sys/policies/acl/{OXIDIZED_POLICY_NAME}"
        self._request("PUT", policy_path, body={"policy": OXIDIZED_POLICY}, status=204)
        role_path = f"/v1/auth/approle/role/{OXIDIZED_ROLE_NAME}"
        self._request("POST", role_path, body=OXIDIZED_ROLE, status=204)
        return self.issue_bootstrap()


def persist_oxidized_bootstrap(
    root: Path, bootstrap: OxidizedAppRoleBootstrap
) -> tuple[Path, Path]:
    """Persist dedicated bootstrap values as private files without exposing them."""
    try:
        validate_oxidized_root(root)
    except OxidizedPrivatePathError as error:
        raise SecretError("Oxidized operator root rejected") from error
    for directory in (root, root / "operator"):
        try:
            ensure_private_directory(directory)
        except OxidizedPrivatePathError as error:
            raise SecretError("Oxidized operator root rejected") from error
    paths = (root / "operator" / "role-id", root / "operator" / "secret-id")
    values = (bootstrap.role_id, bootstrap.secret_id)
    for path, value in zip(paths, values, strict=True):
        temporary = path.with_suffix(".tmp")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(temporary, flags, 0o600)
            try:
                os.write(descriptor, value.encode())
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            validate_private_file(temporary)
            temporary.replace(path)
            validate_private_file(path)
        except (OSError, OxidizedPrivatePathError) as error:
            with suppress(FileNotFoundError):
                temporary.unlink()
            raise SecretError("Oxidized bootstrap persistence failed") from error
    directory_fd = os.open(root / "operator", os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
    return paths
