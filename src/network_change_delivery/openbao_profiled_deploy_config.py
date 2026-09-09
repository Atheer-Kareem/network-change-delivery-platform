"""Personal-Mac persistent deploy identity; no device/configuration write authority."""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import httpx

from network_change_delivery.openbao_profiled_config import exact_device_read_policy
from network_change_delivery.secrets import (
    OpenBaoSecretProvider,
    SecretError,
    create_openbao_client,
    validate_openbao_url,
)

ROLE_NAME = "ncdp-buildkite-profiled-deploy"
POLICY_NAME = "ncdp-buildkite-profiled-deploy-read"
DEVICE_IDS = (1, 2, 8, 9)
POLICY = exact_device_read_policy(DEVICE_IDS)
ROLE = {
    "bind_secret_id": True,
    "secret_id_ttl": 0,
    "secret_id_num_uses": 0,
    "token_ttl": 300,
    "token_max_ttl": 300,
    "token_explicit_max_ttl": 300,
    "token_num_uses": 1,
    "token_no_default_policy": True,
    "token_policies": [POLICY_NAME],
    "token_type": "service",
    "token_period": 0,
    "secret_id_bound_cidrs": [],
    "token_bound_cidrs": [],
}
ROLE_PATH = f"/v1/auth/approle/role/{ROLE_NAME}"
POLICY_PATH = f"/v1/sys/policies/acl/{POLICY_NAME}"


@dataclass(frozen=True, repr=False)
class DeployAgentCredentials:
    role_id: str
    secret_id: str


class OpenBaoProfiledDeployConfigurator:
    """Only the dedicated role/policy and its credentials; no general role edits."""

    def __init__(self, url: str, token: str, *, transport=None):
        if not token:
            raise SecretError("operator authority missing")
        self.url = validate_openbao_url(url)
        self.transport = transport
        self.client = create_openbao_client(self.url, transport=transport)
        self.headers = {"X-Vault-Token": token}

    def request(self, method, path, *, body=None, statuses=(200,)):
        try:
            response = self.client.request(
                method, path, headers=self.headers, json=body
            )
        except httpx.RequestError:
            raise SecretError("deploy identity request uncertain; no retry") from None
        if response.status_code not in statuses:
            raise SecretError("deploy identity request rejected")
        return response

    @staticmethod
    def data(response):
        try:
            value = response.json()["data"]
            if isinstance(value, dict):
                return value
        except (ValueError, KeyError, TypeError):
            pass
        raise SecretError("deploy identity response rejected")

    def configure(self):
        for path, expected, method in (
            (POLICY_PATH, {"policy": POLICY}, "PUT"),
            (ROLE_PATH, ROLE, "POST"),
        ):
            response = self.request("GET", path, statuses=(200, 404))
            actual = self.data(response) if response.status_code == 200 else {}
            if any(actual.get(k) != v for k, v in expected.items()):
                self.request(method, path, body=expected, statuses=(204,))
            actual = self.data(self.request("GET", path))
            if any(actual.get(k) != v for k, v in expected.items()):
                raise SecretError("deploy identity read-back failed")

    def issue(self):
        role_id = self.data(self.request("GET", ROLE_PATH + "/role-id"))["role_id"]
        data = self.data(self.request("POST", ROLE_PATH + "/secret-id", body={}))
        if data.get("secret_id_ttl") != 0 or data.get("secret_id_num_uses") != 0:
            raise SecretError("persistent SecretID response rejected")
        return DeployAgentCredentials(role_id, data["secret_id"])

    def verify(self, credentials):
        """Verify persistence and actual provider reads; never connect to a device."""
        for path, expected in ((POLICY_PATH, {"policy": POLICY}), (ROLE_PATH, ROLE)):
            actual = self.data(self.request("GET", path))
            if any(actual.get(k) != v for k, v in expected.items()):
                raise SecretError("installed deploy role/policy contract rejected")
        role_id = self.data(self.request("GET", ROLE_PATH + "/role-id"))["role_id"]
        if credentials.role_id != role_id:
            raise SecretError("dedicated role identity mismatch")
        data = self.data(
            self.request(
                "POST",
                ROLE_PATH + "/secret-id/lookup",
                body={"secret_id": credentials.secret_id},
            )
        )
        if (
            data.get("secret_id_ttl") != 0
            or data.get("secret_id_num_uses") != 0
            or data.get("expiration_time") != "0001-01-01T00:00:00Z"
        ):
            raise SecretError("installed SecretID is not persistent")
        operator = self

        class VerifiedProvider(OpenBaoSecretProvider):
            def _login(self):
                token = super()._login()
                # Operator lookup does not spend the issued token's single use.
                info = operator.data(
                    operator.request(
                        "POST", "/v1/auth/token/lookup", body={"token": token}
                    )
                )
                if (
                    not 0 < info.get("ttl", 0) <= 300
                    or info.get("creation_ttl") != 300
                    or info.get("num_uses") != 1
                    or info.get("policies") != [POLICY_NAME]
                    or info.get("identity_policies", [])
                ):
                    raise SecretError("issued deploy token contract rejected")
                return token

        provider = VerifiedProvider(
            self.url,
            credentials.role_id,
            credentials.secret_id,
            transport=self.transport,
        )
        for device_id in DEVICE_IDS:
            provider.load(
                SimpleNamespace(
                    inventory_source="netbox",
                    inventory_object_id=f"netbox:dcim.device:{device_id}",
                )
            )

        # A separate one-use token proves an unrelated exact path is denied.
        # Require HTTP 403; transport uncertainty or other failures are not denial.
        token = provider._login()
        try:
            response = provider._client.get(
                "/v1/ncdp/data/devices/999999/ssh", headers={"X-Vault-Token": token}
            )
        except httpx.RequestError:
            raise SecretError(
                "unrelated path verification uncertain; no retry"
            ) from None
        if response.status_code != 403:
            raise SecretError("unrelated device path was not explicitly denied")


class ProtectedRolloutCredentialAuthority:
    """Static permission decision; child planning still proves secret availability."""

    def admit(self, device_identity: str):
        from network_change_delivery.profiled_rollout import RolloutCredentialAdmission

        if device_identity not in tuple(f"netbox:dcim.device:{i}" for i in DEVICE_IDS):
            raise SecretError("protected rollout credential permission denied")
        device_id = device_identity.rsplit(":", 1)[1]
        return RolloutCredentialAdmission(
            authority=ROLE_NAME,
            device_identity=device_identity,
            credential_reference=f"openbao:kv-v2:ncdp/devices/{device_id}/ssh",
            permitted=True,
        )
