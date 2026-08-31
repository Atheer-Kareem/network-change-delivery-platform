"""Detour B3-3 exact local OpenBao onboarding tests."""

from __future__ import annotations

import json

import httpx
import pytest

from network_change_delivery.openbao_profiled_config import (
    LEGACY_LOCAL_POLICY,
    LOCAL_APPROLE_NAME,
    LOCAL_DEVICE_IDS,
    LOCAL_POLICY_NAME,
    NEW_PROFILED_USERNAME,
    PROFILED_LOCAL_POLICY,
    OpenBaoProfiledDeviceConfigurator,
    exact_device_read_policy,
)
from network_change_delivery.secrets import SecretError

ADMIN_TOKEN = "private-admin-token"
PASSWORD_8 = "a" * 48
PASSWORD_9 = "b" * 48


class OpenBaoState:
    def __init__(self) -> None:
        self.policy = LEGACY_LOCAL_POLICY
        self.secrets: dict[int, tuple[dict[str, str], int]] = {
            1: ({"username": "netdevops", "password": "existing-one"}, 7),
            2: ({"username": "junos-user", "password": "existing-two"}, 5),
        }
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path == "/v1/sys/mounts":
            return httpx.Response(
                200,
                json={"data": {"ncdp/": {"type": "kv", "options": {"version": "2"}}}},
            )
        if path == "/v1/sys/auth":
            return httpx.Response(200, json={"data": {"approle/": {"type": "approle"}}})
        if path == f"/v1/auth/approle/role/{LOCAL_APPROLE_NAME}":
            return httpx.Response(
                200,
                json={
                    "data": {
                        "bind_secret_id": True,
                        "secret_id_ttl": 1800,
                        "secret_id_num_uses": 10,
                        "token_policies": [LOCAL_POLICY_NAME],
                        "token_ttl": 300,
                        "token_max_ttl": 300,
                        "token_num_uses": 1,
                    }
                },
            )
        if path == f"/v1/sys/policies/acl/{LOCAL_POLICY_NAME}":
            if request.method == "PUT":
                self.policy = json.loads(request.content)["policy"]
                return httpx.Response(204)
            return httpx.Response(200, json={"data": {"policy": self.policy}})
        if path.startswith("/v1/ncdp/data/devices/") and path.endswith("/ssh"):
            device_id = int(path.split("/")[5])
            if request.method == "POST":
                body = json.loads(request.content)
                if device_id in self.secrets or body.get("options") != {"cas": 0}:
                    return httpx.Response(400)
                self.secrets[device_id] = (body["data"], 1)
                return httpx.Response(200, json={"data": {"version": 1}})
            stored = self.secrets.get(device_id)
            if stored is None:
                return httpx.Response(404)
            values, version = stored
            return httpx.Response(
                200,
                json={"data": {"data": values, "metadata": {"version": version}}},
            )
        raise AssertionError(path)


def configurator(
    state: OpenBaoState, passwords: list[str]
) -> OpenBaoProfiledDeviceConfigurator:
    values = iter(passwords)
    return OpenBaoProfiledDeviceConfigurator(
        "https://openbao.example",
        ADMIN_TOKEN,
        transport=httpx.MockTransport(state.handler),
        password_factory=lambda: next(values),
    )


def test_exact_local_policy_contains_only_four_read_paths() -> None:
    assert LOCAL_DEVICE_IDS == (1, 2, 8, 9)
    assert exact_device_read_policy(LOCAL_DEVICE_IDS) == PROFILED_LOCAL_POLICY
    assert PROFILED_LOCAL_POLICY.count("path ") == 4
    assert PROFILED_LOCAL_POLICY.count('capabilities = ["read"]') == 4
    assert "*" not in PROFILED_LOCAL_POLICY
    assert "list" not in PROFILED_LOCAL_POLICY
    assert "write" not in PROFILED_LOCAL_POLICY


def test_operator_configuration_is_idempotent_and_does_not_rotate() -> None:
    state = OpenBaoState()
    before = dict(state.secrets)
    first = configurator(state, [PASSWORD_8, PASSWORD_9]).configure()
    after_first = dict(state.secrets)
    second = configurator(state, []).configure()

    assert first.created_device_ids == (8, 9)
    assert first.reused_device_ids == ()
    assert second.created_device_ids == ()
    assert second.reused_device_ids == (8, 9)
    assert state.secrets == after_first
    assert state.secrets[1] == before[1]
    assert state.secrets[2] == before[2]
    assert state.secrets[8][0]["username"] == NEW_PROFILED_USERNAME
    assert state.secrets[9][0]["username"] == NEW_PROFILED_USERNAME
    assert state.secrets[8][0]["password"] != state.secrets[9][0]["password"]
    writes = [
        request.url.path for request in state.requests if request.method == "POST"
    ]
    assert writes.count("/v1/ncdp/data/devices/8/ssh") == 1
    assert writes.count("/v1/ncdp/data/devices/9/ssh") == 1
    assert not any("deploy" in request.url.path for request in state.requests)
    assert not any("snmp" in request.url.path for request in state.requests)
    for value in (ADMIN_TOKEN, PASSWORD_8, PASSWORD_9):
        assert value not in repr(first)
        assert value not in repr(second)


def test_existing_profiled_path_with_wrong_schema_or_username_fails_closed() -> None:
    state = OpenBaoState()
    state.secrets[8] = ({"username": "wrong", "password": "existing"}, 1)
    with pytest.raises(SecretError, match="credential conflicts") as caught:
        configurator(state, []).configure()
    assert "wrong" not in repr(caught.value)
    assert "existing" not in repr(caught.value)


def test_generated_password_collision_fails_before_any_secret_write() -> None:
    state = OpenBaoState()
    with pytest.raises(SecretError, match="not unique"):
        configurator(state, [PASSWORD_8, PASSWORD_8]).configure()
    assert set(state.secrets) == {1, 2}


def test_environment_configuration_requires_operator_token_safely() -> None:
    with pytest.raises(SecretError, match="configuration missing"):
        OpenBaoProfiledDeviceConfigurator.from_environment(
            {"NCDP_OPENBAO_URL": "https://openbao.example", "BAO_TOKEN": ""}
        )
