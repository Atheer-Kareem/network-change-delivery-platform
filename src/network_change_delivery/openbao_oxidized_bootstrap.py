"""Minimal persistent machine bootstrap for Oxidized source refresh."""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from network_change_delivery.openbao_oxidized_config import OXIDIZED_ROLE_NAME
from network_change_delivery.secrets import (
    SecretError,
    create_openbao_client,
    validate_openbao_url,
)

BOOTSTRAP_POLICY_NAME = "ncdp-oxidized-secretid-issuer"
BOOTSTRAP_ROLE_NAME = "ncdp-oxidized-bootstrap"
BOOTSTRAP_POLICY = f"""path "auth/approle/role/{OXIDIZED_ROLE_NAME}/secret-id" {{
  capabilities = ["update"]
}}
"""
BOOTSTRAP_ROLE = {
    "bind_secret_id": True,
    "secret_id_ttl": 0,
    "secret_id_num_uses": 0,
    "token_no_default_policy": True,
    "token_policies": [BOOTSTRAP_POLICY_NAME],
    "token_ttl": 60,
    "token_max_ttl": 60,
    "token_num_uses": 1,
}


@dataclass(frozen=True, repr=False)
class OxidizedMachineBootstrap:
    role_id: str
    secret_id: str


@dataclass(frozen=True, repr=False)
class OxidizedSourceLogin:
    role_id: str
    secret_id: str


class OpenBaoOxidizedBootstrap:
    """Configure or use the exact SecretID-issuer authority."""

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
        status: int,
    ) -> httpx.Response:
        headers = {"X-Vault-Token": token} if token else None
        try:
            response = self._client.request(method, path, headers=headers, json=body)
        except (httpx.TimeoutException, httpx.RequestError):
            raise SecretError("OpenBao Oxidized bootstrap unavailable") from None
        if response.status_code != status:
            raise SecretError("OpenBao Oxidized bootstrap request failed")
        return response

    @staticmethod
    def _data(response: httpx.Response) -> dict[str, object]:
        try:
            data = response.json().get("data")
        except (AttributeError, ValueError):
            data = None
        if not isinstance(data, dict):
            raise SecretError("OpenBao Oxidized bootstrap response rejected")
        return data

    def configure(self, admin_token: str) -> OxidizedMachineBootstrap:
        if not admin_token:
            raise SecretError("OpenBao Oxidized bootstrap operator missing")
        self._request(
            "PUT",
            f"/v1/sys/policies/acl/{BOOTSTRAP_POLICY_NAME}",
            token=admin_token,
            body={"policy": BOOTSTRAP_POLICY},
            status=204,
        )
        role_path = f"/v1/auth/approle/role/{BOOTSTRAP_ROLE_NAME}"
        self._request(
            "POST", role_path, token=admin_token, body=BOOTSTRAP_ROLE, status=204
        )
        policy = self._data(
            self._request(
                "GET",
                f"/v1/sys/policies/acl/{BOOTSTRAP_POLICY_NAME}",
                token=admin_token,
                status=200,
            )
        )
        role = self._data(
            self._request("GET", role_path, token=admin_token, status=200)
        )
        if policy.get("policy") != BOOTSTRAP_POLICY or any(
            role.get(k) != v for k, v in BOOTSTRAP_ROLE.items()
        ):
            raise SecretError("OpenBao Oxidized bootstrap verification failed")
        role_id = self._data(
            self._request("GET", f"{role_path}/role-id", token=admin_token, status=200)
        ).get("role_id")
        secret_id = self._data(
            self._request(
                "POST", f"{role_path}/secret-id", token=admin_token, body={}, status=200
            )
        ).get("secret_id")
        if (
            not isinstance(role_id, str)
            or not role_id
            or not isinstance(secret_id, str)
            or not secret_id
        ):
            raise SecretError("OpenBao Oxidized bootstrap issuance failed")
        return OxidizedMachineBootstrap(role_id, secret_id)

    def issue_source_login(
        self, role_id: str, secret_id: str, source_role_id: str
    ) -> OxidizedSourceLogin:
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
        if not isinstance(token, str) or not token:
            raise SecretError("OpenBao Oxidized bootstrap login failed")
        source_path = f"/v1/auth/approle/role/{OXIDIZED_ROLE_NAME}"
        source_secret_id = self._data(
            self._request(
                "POST", f"{source_path}/secret-id", token=token, body={}, status=200
            )
        ).get("secret_id")
        if (
            not isinstance(source_role_id, str)
            or not source_role_id
            or not isinstance(source_secret_id, str)
            or not source_secret_id
        ):
            raise SecretError("OpenBao Oxidized source bootstrap failed")
        return OxidizedSourceLogin(source_role_id, source_secret_id)
