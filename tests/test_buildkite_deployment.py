"""Buildkite one-device live-deployment boundary tests."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from network_change_delivery.buildkite_deployment import (
    BuildkiteOpenBaoDeploymentSecretProvider,
    LiveDeploymentRequest,
    cml_deploy_role_name,
    cml_device_policy_name,
    load_live_deployment_request,
)
from network_change_delivery.buildkite_identity import BuildkiteOIDCJWT
from network_change_delivery.buildkite_policy import BuildkiteDeploymentContext
from network_change_delivery.models import InventoryDevice
from network_change_delivery.promotion import PromotionError
from network_change_delivery.secrets import SecretError

JWT = "sensitive.header.signature"
TOKEN = "sensitive-openbao-token"
USERNAME = "sensitive-device-user"
PASSWORD = "sensitive-device-password"


def context(**changes: str) -> BuildkiteDeploymentContext:
    values = {
        "commit": "a" * 40,
        "branch": "main",
        "pipeline_id": "pipeline-uuid",
        "build_id": "build-uuid",
        "build_number": "17",
        "job_id": "job-uuid",
        "step_key": "deploy-gate",
        "queue_key": "ncdp-deploy",
    }
    values.update(changes)
    return BuildkiteDeploymentContext.model_validate(values)


def device(**changes: object) -> InventoryDevice:
    values: dict[str, object] = {
        "name": "core-02",
        "host": "192.0.2.10",
        "platform": "cisco_iosxe",
        "expected_hostname": "core-02",
        "inventory_source": "netbox",
        "inventory_object_id": "netbox:dcim.device:1",
        "inventory_interface_object_id": "netbox:dcim.interface:2",
    }
    values.update(changes)
    return InventoryDevice.model_validate(values)


def auth_payload(**changes: object) -> dict[str, object]:
    policy = cml_device_policy_name(1)
    auth: dict[str, object] = {
        "client_token": TOKEN,
        "lease_duration": 300,
        "token_policies": [policy],
        "identity_policies": [],
        "policies": [policy],
        "metadata": {
            "pipeline_id": "pipeline-uuid",
            "build_commit": "a" * 40,
            "build_branch": "main",
            "step_key": "deploy-gate",
            "job_id": "job-uuid",
        },
    }
    auth.update(changes)
    return {"auth": auth}


def secret_payload(**changes: object) -> dict[str, object]:
    credentials: dict[str, object] = {"username": USERNAME, "password": PASSWORD}
    credentials.update(changes)
    return {"data": {"data": credentials, "metadata": {"version": 1}}}


def provider(handler) -> BuildkiteOpenBaoDeploymentSecretProvider:
    return BuildkiteOpenBaoDeploymentSecretProvider(
        BuildkiteOIDCJWT(JWT),
        context(),
        "https://openbao.example",
        transport=httpx.MockTransport(handler),
    )


def test_exact_role_login_policy_identity_and_one_kv_get() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/v1/auth/jwt/login":
            return httpx.Response(200, json=auth_payload())
        return httpx.Response(200, json=secret_payload())

    source = provider(handler)
    assert source.reference(device()).reference == ("openbao:kv-v2:ncdp/devices/1/ssh")
    credentials = source.load(device())
    assert credentials.username == USERNAME
    assert credentials.password == PASSWORD
    assert [request.method for request in requests] == ["POST", "GET"]
    assert json.loads(requests[0].content) == {
        "role": cml_deploy_role_name(1),
        "jwt": JWT,
    }
    assert requests[1].url.path == "/v1/ncdp/data/devices/1/ssh"
    assert requests[1].headers["X-Vault-Token"] == TOKEN
    assert "X-Vault-Token" not in requests[0].headers


def test_second_load_is_rejected_without_another_request() -> None:
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        if request.url.path == "/v1/auth/jwt/login":
            return httpx.Response(200, json=auth_payload())
        return httpx.Response(200, json=secret_payload())

    source = provider(handler)
    source.load(device())
    with pytest.raises(SecretError, match="already consumed"):
        source.load(device())
    assert requests == ["/v1/auth/jwt/login", "/v1/ncdp/data/devices/1/ssh"]


def test_reference_binds_load_to_the_same_stable_device_identity() -> None:
    source = provider(lambda _request: pytest.fail("OpenBao must not be contacted"))
    source.reference(device())
    with pytest.raises(SecretError, match="device identity changed"):
        source.load(
            device(
                inventory_object_id="netbox:dcim.device:2",
                inventory_interface_object_id="netbox:dcim.interface:3",
            )
        )


@pytest.mark.parametrize(
    "change",
    [
        {"lease_duration": 301},
        {"token_policies": []},
        {"token_policies": ["default"]},
        {"identity_policies": ["identity"]},
        {"policies": []},
        {"policies": [cml_device_policy_name(1), "other"]},
        {"external_namespace_policies": {"root": ["other"]}},
        {"external_namespace_policy_paths": ["other"]},
    ],
)
def test_lease_and_exact_policy_results_fail_closed(change: dict[str, object]) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=auth_payload(**change))

    with pytest.raises(SecretError):
        provider(handler).load(device())


@pytest.mark.parametrize(
    ("claim", "context_field"),
    [
        ("pipeline_id", "pipeline_id"),
        ("build_commit", "commit"),
        ("build_branch", "branch"),
        ("step_key", "step_key"),
        ("job_id", "job_id"),
    ],
)
def test_each_mapped_identity_field_is_exact(claim: str, context_field: str) -> None:
    del context_field
    metadata = auth_payload()["auth"]["metadata"]
    assert isinstance(metadata, dict)
    metadata[claim] = "wrong"

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=auth_payload(metadata=metadata))

    with pytest.raises(SecretError, match=f"identity mismatch: {claim}"):
        provider(handler).load(device())


def test_secret_values_never_enter_errors_or_representations() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, content=(JWT + TOKEN + PASSWORD).encode())

    source = provider(handler)
    with pytest.raises(SecretError) as caught:
        source.load(device())
    rendered = repr(source) + repr(caught.value)
    for secret in (JWT, TOKEN, USERNAME, PASSWORD):
        assert secret not in rendered


@pytest.mark.parametrize(
    "payload",
    [
        {"data": {}},
        {"data": {"data": {"username": USERNAME}}},
        {"data": {"data": {"username": "", "password": PASSWORD}}},
        {"data": {"data": {"username": USERNAME, "password": ""}}},
        {
            "data": {
                "data": {
                    "username": USERNAME,
                    "password": PASSWORD,
                    "extra": "rejected",
                }
            }
        },
    ],
)
def test_credential_payload_requires_exact_nonempty_pair(payload: object) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if request.url.path == "/v1/auth/jwt/login":
            return httpx.Response(200, json=auth_payload())
        return httpx.Response(200, json=payload)

    with pytest.raises(SecretError, match="credential payload invalid"):
        provider(handler).load(device())
    assert calls == 2


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"schema_version": "1", "action": "read"},
        {
            "schema_version": "1",
            "action": "deploy",
            "change_id": "CHG-1",
            "plan_digest": "sha256:" + "a" * 64,
            "inventory_object_id": "netbox:dcim.device:1",
            "extra": "rejected",
        },
    ],
)
def test_live_request_schema_is_strict(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        LiveDeploymentRequest.model_validate(payload)


def test_live_request_file_load_and_exact_plan_binding(tmp_path: Path) -> None:
    request_path = tmp_path / "request.yaml"
    request_path.write_text(
        """schema_version: "1"
action: deploy
change_id: CHG-1
plan_digest: sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
inventory_object_id: netbox:dcim.device:1
""",
        encoding="utf-8",
    )
    request = load_live_deployment_request(request_path)

    class Plan:
        change_id = "CHG-1"
        digest = "sha256:" + "a" * 64
        inventory_object_id = "netbox:dcim.device:1"

    request.verify_plan(Plan())  # type: ignore[arg-type]
    for field, wrong in (
        ("change_id", "CHG-2"),
        ("plan_digest", "sha256:" + "b" * 64),
        ("inventory_object_id", "netbox:dcim.device:2"),
    ):
        changed = request.model_copy(update={field: wrong})
        with pytest.raises(PromotionError, match="does not match"):
            changed.verify_plan(Plan())  # type: ignore[arg-type]
