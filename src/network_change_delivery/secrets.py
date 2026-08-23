"""Target-aware, secret-safe device credential provider boundaries."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, Protocol
from urllib.parse import urlparse

import httpx

from network_change_delivery.models import InventoryDevice

USERNAME_VARIABLE = "NCDP_DEVICE_USERNAME"
PASSWORD_VARIABLE = "NCDP_DEVICE_PASSWORD"
ENVIRONMENT_REFERENCE = "environment:NCDP_DEVICE_USERNAME+NCDP_DEVICE_PASSWORD"
_NETBOX_DEVICE_IDENTITY = re.compile(r"netbox:dcim\.device:([1-9][0-9]*)")


def validate_openbao_url(value: str) -> str:
    """Validate the shared OpenBao transport boundary."""
    try:
        parsed = urlparse(value)
        hostname = parsed.hostname
        _port = parsed.port
    except ValueError:
        raise SecretError("OpenBao URL rejected") from None
    if parsed.scheme not in {"http", "https"} or not hostname:
        raise SecretError("OpenBao URL rejected")
    if (
        parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise SecretError("OpenBao URL rejected")
    if parsed.scheme == "http" and hostname.casefold() not in {
        "127.0.0.1",
        "::1",
        "localhost",
    }:
        raise SecretError("OpenBao URL rejected: HTTP requires loopback")
    return value.rstrip("/")


def create_openbao_client(
    base_url: str, *, transport: httpx.BaseTransport | None = None
) -> httpx.Client:
    """Create one hardened, environment-independent OpenBao HTTP client."""
    try:
        return httpx.Client(
            base_url=base_url,
            timeout=httpx.Timeout(5.0, connect=3.0),
            follow_redirects=False,
            verify=True,
            trust_env=False,
            transport=transport,
        )
    except (TypeError, ValueError):
        raise SecretError("OpenBao configuration missing") from None


class SecretError(ValueError):
    """Raised without exposing secret values."""


@dataclass(frozen=True)
class CredentialReference:
    """Stable non-secret credential provenance."""

    source: Literal["environment", "openbao"]
    reference: str


@dataclass(frozen=True, repr=False)
class DeviceCredentials:
    """Ephemeral credentials that must never enter evidence or plans."""

    username: str
    password: str


class SecretProvider(Protocol):
    """Boundary for target-aware credential provenance and retrieval."""

    def reference(self, device: InventoryDevice) -> CredentialReference:
        """Resolve stable non-secret credential provenance."""

    def load(self, device: InventoryDevice) -> DeviceCredentials:
        """Load ephemeral credentials for one resolved device."""


class EnvironmentSecretProvider:
    """Explicit environment provider for tests and offline development."""

    def __init__(self, environment: Mapping[str, str] | None = None) -> None:
        self._environment = environment if environment is not None else os.environ

    def reference(self, device: InventoryDevice) -> CredentialReference:
        """Return the stable environment variable reference."""
        del device
        return CredentialReference("environment", ENVIRONMENT_REFERENCE)

    def load(self, device: InventoryDevice) -> DeviceCredentials:
        """Load both required variables without logging values."""
        del device
        missing = [
            name
            for name in (USERNAME_VARIABLE, PASSWORD_VARIABLE)
            if not self._environment.get(name)
        ]
        if missing:
            raise SecretError(
                f"missing required environment variables: {', '.join(missing)}"
            )
        return DeviceCredentials(
            username=self._environment[USERNAME_VARIABLE],
            password=self._environment[PASSWORD_VARIABLE],
        )


class OpenBaoSecretProvider:
    """AppRole-authenticated, exact-path OpenBao KV-v2 credential adapter."""

    _LOGIN_PATH = "/v1/auth/approle/login"

    def __init__(
        self,
        url: str | None = None,
        role_id: str | None = None,
        secret_id: str | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        configured_url = os.environ.get("NCDP_OPENBAO_URL") if url is None else url
        configured_role_id = (
            os.environ.get("NCDP_OPENBAO_ROLE_ID") if role_id is None else role_id
        )
        configured_secret_id = (
            os.environ.get("NCDP_OPENBAO_SECRET_ID") if secret_id is None else secret_id
        )
        if not configured_url or not configured_role_id or not configured_secret_id:
            raise SecretError("OpenBao configuration missing")
        self._base_url = validate_openbao_url(configured_url)
        self._role_id = configured_role_id
        self._secret_id = configured_secret_id
        self._client = create_openbao_client(self._base_url, transport=transport)

    @staticmethod
    def _device_id(device: InventoryDevice) -> int:
        if device.inventory_source != "netbox" or device.inventory_object_id is None:
            raise SecretError("OpenBao requires NetBox-backed inventory identity")
        match = _NETBOX_DEVICE_IDENTITY.fullmatch(device.inventory_object_id)
        if match is None:
            raise SecretError("OpenBao requires NetBox-backed inventory identity")
        return int(match.group(1))

    def reference(self, device: InventoryDevice) -> CredentialReference:
        """Derive fixed non-secret provenance from stable NetBox identity."""
        device_id = self._device_id(device)
        return CredentialReference(
            "openbao", f"openbao:kv-v2:ncdp/devices/{device_id}/ssh"
        )

    @staticmethod
    def _json(response: httpx.Response) -> dict[str, object]:
        try:
            payload = response.json()
        except ValueError:
            raise SecretError("OpenBao returned invalid JSON or schema") from None
        if not isinstance(payload, dict):
            raise SecretError("OpenBao returned invalid JSON or schema")
        return payload

    def _login(self) -> str:
        try:
            response = self._client.post(
                self._LOGIN_PATH,
                json={"role_id": self._role_id, "secret_id": self._secret_id},
            )
        except (httpx.TimeoutException, httpx.RequestError):
            raise SecretError("OpenBao unavailable or timed out") from None
        if response.status_code in {400, 401, 403}:
            raise SecretError("OpenBao authentication failed")
        if response.status_code != 200:
            raise SecretError(
                f"OpenBao returned unexpected HTTP status {response.status_code}"
            )
        payload = self._json(response)
        auth = payload.get("auth")
        if not isinstance(auth, dict):
            raise SecretError("OpenBao returned invalid JSON or schema")
        token = auth.get("client_token")
        lease_duration = auth.get("lease_duration")
        if not isinstance(token, str) or not token:
            raise SecretError("OpenBao issued unacceptable token")
        if (
            not isinstance(lease_duration, int)
            or isinstance(lease_duration, bool)
            or lease_duration <= 0
            or lease_duration > 600
        ):
            raise SecretError("OpenBao issued unacceptable token")
        return token

    def load(self, device: InventoryDevice) -> DeviceCredentials:
        """Authenticate once and consume the single-use token on one exact GET."""
        device_id = self._device_id(device)
        token = self._login()
        try:
            response = self._client.get(
                f"/v1/ncdp/data/devices/{device_id}/ssh",
                headers={"X-Vault-Token": token},
            )
        except (httpx.TimeoutException, httpx.RequestError):
            raise SecretError("OpenBao unavailable or timed out") from None
        if response.status_code == 403:
            raise SecretError("OpenBao secret read unauthorized")
        if response.status_code == 404:
            raise SecretError("OpenBao secret not found")
        if response.status_code != 200:
            raise SecretError(
                f"OpenBao returned unexpected HTTP status {response.status_code}"
            )
        payload = self._json(response)
        outer_data = payload.get("data")
        credential_data = (
            outer_data.get("data") if isinstance(outer_data, dict) else None
        )
        if not isinstance(credential_data, dict):
            raise SecretError("OpenBao returned invalid JSON or schema")
        if set(credential_data) != {"username", "password"}:
            raise SecretError("OpenBao credential payload invalid")
        username = credential_data.get("username")
        password = credential_data.get("password")
        if not isinstance(username, str) or not username:
            raise SecretError("OpenBao credential payload invalid")
        if not isinstance(password, str) or not password:
            raise SecretError("OpenBao credential payload invalid")
        return DeviceCredentials(username=username, password=password)
