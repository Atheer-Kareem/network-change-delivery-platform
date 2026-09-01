"""Bounded OpenBao onboarding for the Detour B profiled device population."""

from __future__ import annotations

import os
import secrets
from collections.abc import Callable, Mapping
from dataclasses import dataclass

import httpx

from network_change_delivery.secrets import (
    SecretError,
    create_openbao_client,
    validate_openbao_url,
)

LOCAL_APPROLE_NAME = "ncdp-personal-lab"
LOCAL_POLICY_NAME = "ncdp-device-1"
LOCAL_DEVICE_IDS = (1, 2, 8, 9)
NEW_PROFILED_DEVICE_IDS = (8, 9)
NEW_PROFILED_USERNAME = "netdevops"


def exact_device_read_policy(device_ids: tuple[int, ...]) -> str:
    """Render one closed exact-path policy without list or wildcard authority."""
    if not device_ids or len(device_ids) != len(set(device_ids)):
        raise SecretError("OpenBao local device policy identity is invalid")
    if any(device_id <= 0 for device_id in device_ids):
        raise SecretError("OpenBao local device policy identity is invalid")
    return "\n".join(
        f'path "ncdp/data/devices/{device_id}/ssh" {{\n  capabilities = ["read"]\n}}\n'
        for device_id in device_ids
    )


LEGACY_LOCAL_POLICY = exact_device_read_policy((1, 2))
PROFILED_LOCAL_POLICY = exact_device_read_policy(LOCAL_DEVICE_IDS)

_EXPECTED_LOCAL_ROLE = {
    "bind_secret_id": True,
    "secret_id_ttl": 1800,
    "secret_id_num_uses": 10,
    "token_policies": [LOCAL_POLICY_NAME],
    "token_ttl": 300,
    "token_max_ttl": 300,
    "token_num_uses": 1,
}


@dataclass(frozen=True)
class ProfiledOpenBaoConfiguration:
    """Secret-free result of one idempotent B3-3 operator configuration."""

    local_policy: str
    local_approle: str
    created_device_ids: tuple[int, ...]
    reused_device_ids: tuple[int, ...]
    secret_versions: tuple[tuple[int, int], ...]


@dataclass(frozen=True, repr=False)
class ProfiledOpenBaoSession:
    """One bounded personal-lab AppRole login, with no secret-bearing repr."""

    role_id: str
    secret_id: str
    secret_id_accessor: str

    def __repr__(self) -> str:
        return "ProfiledOpenBaoSession(<redacted>)"


def _random_password() -> str:
    return secrets.token_urlsafe(48)


class OpenBaoProfiledDeviceConfigurator:
    """Create only devices 8/9 credentials and admit exact local reads 1/2/8/9."""

    def __init__(
        self,
        url: str,
        admin_token: str,
        *,
        transport: httpx.BaseTransport | None = None,
        password_factory: Callable[[], str] = _random_password,
    ) -> None:
        if not admin_token:
            raise SecretError("OpenBao profiled-device operator configuration missing")
        self._client = create_openbao_client(
            validate_openbao_url(url), transport=transport
        )
        self._headers = {"X-Vault-Token": admin_token}
        self._password_factory = password_factory

    @classmethod
    def from_environment(
        cls,
        environment: Mapping[str, str] | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
        password_factory: Callable[[], str] = _random_password,
    ) -> OpenBaoProfiledDeviceConfigurator:
        values = environment if environment is not None else os.environ
        url = values.get("NCDP_OPENBAO_URL")
        token = values.get("BAO_TOKEN")
        if not url or not token:
            raise SecretError("OpenBao profiled-device operator configuration missing")
        return cls(
            url,
            token,
            transport=transport,
            password_factory=password_factory,
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, object] | None = None,
        expected_statuses: tuple[int, ...] = (200,),
    ) -> httpx.Response:
        try:
            response = self._client.request(
                method, path, headers=self._headers, json=json
            )
        except (httpx.TimeoutException, httpx.RequestError):
            raise SecretError("OpenBao unavailable or timed out") from None
        if response.status_code in {400, 401, 403}:
            raise SecretError("OpenBao profiled-device operator request rejected")
        if response.status_code not in expected_statuses:
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

    def _verify_owned_authority(self) -> str:
        mounts = self._data(self._request("GET", "/v1/sys/mounts"))
        ncdp = mounts.get("ncdp/")
        if not (
            isinstance(ncdp, dict)
            and ncdp.get("type") == "kv"
            and isinstance(ncdp.get("options"), dict)
            and ncdp["options"].get("version") == "2"
        ):
            raise SecretError("OpenBao ncdp/ KV-v2 mount is not available")
        auth = self._data(self._request("GET", "/v1/sys/auth"))
        approle = auth.get("approle/")
        if not isinstance(approle, dict) or approle.get("type") != "approle":
            raise SecretError("OpenBao approle/ auth mount is not available")
        role = self._data(
            self._request("GET", f"/v1/auth/approle/role/{LOCAL_APPROLE_NAME}")
        )
        if any(role.get(key) != value for key, value in _EXPECTED_LOCAL_ROLE.items()):
            raise SecretError("OpenBao personal-lab AppRole verification failed")
        policy_path = f"/v1/sys/policies/acl/{LOCAL_POLICY_NAME}"
        policy = self._data(self._request("GET", policy_path)).get("policy")
        if policy not in {LEGACY_LOCAL_POLICY, PROFILED_LOCAL_POLICY}:
            raise SecretError("OpenBao personal-lab policy conflicts with B3-3")
        return policy

    def _read_secret(self, device_id: int) -> tuple[dict[str, object], int] | None:
        response = self._request(
            "GET",
            f"/v1/ncdp/data/devices/{device_id}/ssh",
            expected_statuses=(200, 404),
        )
        if response.status_code == 404:
            return None
        outer = self._data(response)
        values = outer.get("data")
        metadata = outer.get("metadata")
        version = metadata.get("version") if isinstance(metadata, dict) else None
        if (
            not isinstance(values, dict)
            or set(values) != {"username", "password"}
            or not isinstance(values.get("username"), str)
            or not values["username"]
            or not isinstance(values.get("password"), str)
            or not values["password"]
            or not isinstance(version, int)
            or isinstance(version, bool)
            or version <= 0
        ):
            raise SecretError("OpenBao credential payload invalid")
        return values, version

    def _create_secret(self, device_id: int, password: str) -> int:
        if not self._valid_generated_password(password):
            raise SecretError("generated OpenBao device credential is invalid")
        self._request(
            "POST",
            f"/v1/ncdp/data/devices/{device_id}/ssh",
            json={
                "options": {"cas": 0},
                "data": {"username": NEW_PROFILED_USERNAME, "password": password},
            },
            expected_statuses=(200,),
        )
        stored = self._read_secret(device_id)
        if stored is None or stored[0] != {
            "username": NEW_PROFILED_USERNAME,
            "password": password,
        }:
            raise SecretError("OpenBao credential write verification failed")
        return stored[1]

    @staticmethod
    def _valid_generated_password(password: object) -> bool:
        return (
            isinstance(password, str)
            and len(password) >= 43
            and password.isascii()
            and not any(character.isspace() for character in password)
        )

    def configure(self) -> ProfiledOpenBaoConfiguration:
        """Apply and verify the exact B3-3 authority without rotating existing data."""
        current_policy = self._verify_owned_authority()
        preserved = {device_id: self._read_secret(device_id) for device_id in (1, 2)}
        if any(value is None for value in preserved.values()):
            raise SecretError("OpenBao existing device credential is missing")

        created: list[int] = []
        reused: list[int] = []
        versions: dict[int, int] = {
            device_id: value[1]
            for device_id, value in preserved.items()
            if value is not None
        }
        new_passwords: dict[int, str] = {}
        missing: list[int] = []
        for device_id in NEW_PROFILED_DEVICE_IDS:
            existing = self._read_secret(device_id)
            if existing is not None:
                if existing[0].get("username") != NEW_PROFILED_USERNAME:
                    raise SecretError("OpenBao profiled-device credential conflicts")
                new_passwords[device_id] = str(existing[0]["password"])
                versions[device_id] = existing[1]
                reused.append(device_id)
                continue
            missing.append(device_id)
            password = self._password_factory()
            if not self._valid_generated_password(password):
                raise SecretError("generated OpenBao device credential is invalid")
            new_passwords[device_id] = password
        if len(set(new_passwords.values())) != len(NEW_PROFILED_DEVICE_IDS):
            raise SecretError("OpenBao profiled-device credentials are not unique")
        for device_id in missing:
            versions[device_id] = self._create_secret(
                device_id, new_passwords[device_id]
            )
            created.append(device_id)

        policy_path = f"/v1/sys/policies/acl/{LOCAL_POLICY_NAME}"
        if current_policy != PROFILED_LOCAL_POLICY:
            self._request(
                "PUT",
                policy_path,
                json={"policy": PROFILED_LOCAL_POLICY},
                expected_statuses=(204,),
            )
        if (
            self._data(self._request("GET", policy_path)).get("policy")
            != PROFILED_LOCAL_POLICY
        ):
            raise SecretError("OpenBao personal-lab policy verification failed")

        for device_id, before in preserved.items():
            if self._read_secret(device_id) != before:
                raise SecretError("OpenBao existing device credential changed")
        for device_id in NEW_PROFILED_DEVICE_IDS:
            stored = self._read_secret(device_id)
            if (
                stored is None
                or stored[0].get("username") != NEW_PROFILED_USERNAME
                or set(stored[0]) != {"username", "password"}
            ):
                raise SecretError(
                    "OpenBao profiled-device credential verification failed"
                )

        self._verify_owned_authority()
        return ProfiledOpenBaoConfiguration(
            local_policy=LOCAL_POLICY_NAME,
            local_approle=LOCAL_APPROLE_NAME,
            created_device_ids=tuple(created),
            reused_device_ids=tuple(reused),
            secret_versions=tuple(sorted(versions.items())),
        )

    def issue_bounded_session(self) -> ProfiledOpenBaoSession:
        """Verify the accepted authority and issue one existing bounded SecretID."""
        self._verify_owned_authority()
        role_path = f"/v1/auth/approle/role/{LOCAL_APPROLE_NAME}"
        role_id = self._data(self._request("GET", f"{role_path}/role-id")).get(
            "role_id"
        )
        secret_data = self._data(
            self._request("POST", f"{role_path}/secret-id", json={})
        )
        secret_id = secret_data.get("secret_id")
        accessor = secret_data.get("secret_id_accessor")
        if not all(
            isinstance(value, str) and value for value in (role_id, secret_id, accessor)
        ):
            raise SecretError("OpenBao bounded AppRole session response is invalid")
        return ProfiledOpenBaoSession(
            role_id=role_id,
            secret_id=secret_id,
            secret_id_accessor=accessor,
        )

    def retire_bounded_session(self, session: ProfiledOpenBaoSession) -> None:
        """Destroy exactly the issued SecretID by its non-secret accessor."""
        if not isinstance(session, ProfiledOpenBaoSession):
            raise SecretError("OpenBao bounded AppRole session is invalid")
        role_path = f"/v1/auth/approle/role/{LOCAL_APPROLE_NAME}"
        self._request(
            "POST",
            f"{role_path}/secret-id-accessor/destroy",
            json={"secret_id_accessor": session.secret_id_accessor},
            expected_statuses=(204,),
        )
