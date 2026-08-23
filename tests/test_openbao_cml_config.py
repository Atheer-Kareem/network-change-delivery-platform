"""Mocked tests for the one-device Buildkite CML OpenBao operator."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from network_change_delivery.buildkite_deployment import (
    cml_deploy_role_name,
    cml_device_policy_name,
)
from network_change_delivery.buildkite_identity import OPENBAO_BUILDKITE_JWT_ROLE
from network_change_delivery.openbao_cml_config import (
    OpenBaoBuildkiteCMLConfigurator,
    cml_deploy_role_config,
    cml_device_policy,
    validate_device_id,
)
from network_change_delivery.openbao_jwt_config import (
    JWT_MOUNT_DESCRIPTION,
    buildkite_jwt_role_config,
)
from network_change_delivery.secrets import SecretError

ADMIN_TOKEN = "sensitive-admin-token"
PIPELINE_ID = "01a02ab4-2472-4726-be31-dbf4f216210f"
DEVICE_ID = 1
ROOT = Path(__file__).resolve().parents[1]


def data(value: dict[str, object]) -> dict[str, object]:
    return {"data": value}


def configurator(handler) -> OpenBaoBuildkiteCMLConfigurator:
    return OpenBaoBuildkiteCMLConfigurator(
        "https://openbao.example",
        ADMIN_TOKEN,
        PIPELINE_ID,
        str(DEVICE_ID),
        transport=httpx.MockTransport(handler),
    )


def successful_handler(requests: list[httpx.Request]):
    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        path = request.url.path
        if path == "/v1/sys/auth":
            return httpx.Response(
                200,
                json=data(
                    {
                        "jwt/": {
                            "type": "jwt",
                            "description": JWT_MOUNT_DESCRIPTION,
                        }
                    }
                ),
            )
        if path == f"/v1/auth/jwt/role/{OPENBAO_BUILDKITE_JWT_ROLE}":
            return httpx.Response(
                200, json=data(buildkite_jwt_role_config(PIPELINE_ID))
            )
        if path == f"/v1/sys/policies/acl/{cml_device_policy_name(DEVICE_ID)}":
            if request.method == "PUT":
                return httpx.Response(204)
            return httpx.Response(
                200, json=data({"policy": cml_device_policy(DEVICE_ID)})
            )
        if path == f"/v1/auth/jwt/role/{cml_deploy_role_name(DEVICE_ID)}":
            if request.method == "POST":
                return httpx.Response(204)
            return httpx.Response(
                200,
                json=data(cml_deploy_role_config(PIPELINE_ID, DEVICE_ID)),
            )
        raise AssertionError(f"unexpected request: {request.method} {path}")

    return handler


def test_exact_read_policy_and_device_role_are_idempotently_written() -> None:
    requests: list[httpx.Request] = []
    expected = (
        cml_device_policy_name(DEVICE_ID),
        cml_deploy_role_name(DEVICE_ID),
    )
    assert configurator(successful_handler(requests)).configure() == expected
    assert configurator(successful_handler(requests)).configure() == expected
    policy_writes = [request for request in requests if request.method == "PUT"]
    role_writes = [request for request in requests if request.method == "POST"]
    assert len(policy_writes) == 2
    assert len(role_writes) == 2
    assert json.loads(policy_writes[0].content) == {
        "policy": 'path "ncdp/data/devices/1/ssh" {\n  capabilities = ["read"]\n}\n'
    }
    assert json.loads(role_writes[0].content) == cml_deploy_role_config(
        PIPELINE_ID, DEVICE_ID
    )
    assert all(request.headers["X-Vault-Token"] == ADMIN_TOKEN for request in requests)


def test_role_preserves_identity_constraints_and_exact_single_policy() -> None:
    role = cml_deploy_role_config(PIPELINE_ID, DEVICE_ID)
    assert role["role_type"] == "jwt"
    assert role["bound_subject"] == PIPELINE_ID
    assert role["bound_audiences"] == ["urn:ncdp:openbao:deploy"]
    assert role["user_claim"] == "sub"
    assert role["bound_claims"] == {
        "build_branch": "main",
        "step_key": "deploy-gate",
    }
    assert role["token_no_default_policy"] is True
    assert role["token_policies"] == [cml_device_policy_name(DEVICE_ID)]
    assert role["token_ttl"] == role["token_max_ttl"] == 300
    assert role["token_explicit_max_ttl"] == 300
    assert role["token_num_uses"] == 1
    policy = cml_device_policy(DEVICE_ID)
    assert policy.count("path ") == 1
    assert 'capabilities = ["read"]' in policy
    for capability in ("list", "create", "update", "patch", "delete"):
        assert capability not in policy
    assert "auth/" not in policy and "sys/" not in policy


def test_accepted_7b_role_is_only_read_and_verified_unchanged() -> None:
    requests: list[httpx.Request] = []
    configurator(successful_handler(requests)).configure()
    identity_requests = [
        request
        for request in requests
        if request.url.path == f"/v1/auth/jwt/role/{OPENBAO_BUILDKITE_JWT_ROLE}"
    ]
    assert [request.method for request in identity_requests] == ["GET", "GET"]
    assert buildkite_jwt_role_config(PIPELINE_ID)["token_policies"] == []


@pytest.mark.parametrize("value", ["", "0", "-1", "01", "device-1"])
def test_device_id_requires_canonical_positive_integer(value: str) -> None:
    with pytest.raises(SecretError, match="device ID rejected"):
        validate_device_id(value)


def test_environment_only_and_script_rejects_arguments() -> None:
    requests: list[httpx.Request] = []
    configured = OpenBaoBuildkiteCMLConfigurator.from_environment(
        {
            "NCDP_OPENBAO_URL": "https://openbao.example",
            "NCDP_BUILDKITE_PIPELINE_ID": PIPELINE_ID,
            "NCDP_BUILDKITE_CML_DEVICE_ID": "1",
            "BAO_TOKEN": ADMIN_TOKEN,
        },
        transport=httpx.MockTransport(successful_handler(requests)),
    )
    configured.configure()
    assert ADMIN_TOKEN not in repr(configured)
    script = (ROOT / "scripts/openbao/configure_buildkite_cml_deploy.py").read_text()
    assert "if len(sys.argv) != 1:" in script
    assert "command-line arguments are not accepted" in script


def test_unowned_mount_and_changed_identity_role_fail_before_writes() -> None:
    def unowned(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        return httpx.Response(200, json=data({"jwt/": {"type": "jwt"}}))

    with pytest.raises(SecretError, match="not owned"):
        configurator(unowned).configure()

    def changed(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        if request.url.path == "/v1/sys/auth":
            return httpx.Response(
                200,
                json=data(
                    {
                        "jwt/": {
                            "type": "jwt",
                            "description": JWT_MOUNT_DESCRIPTION,
                        }
                    }
                ),
            )
        role = buildkite_jwt_role_config(PIPELINE_ID)
        role["token_policies"] = ["unexpected"]
        return httpx.Response(200, json=data(role))

    with pytest.raises(SecretError, match="identity role verification"):
        configurator(changed).configure()


@pytest.mark.parametrize("boundary", ["policy", "role"])
def test_exact_policy_and_role_readback_rejects_broader_state(boundary: str) -> None:
    requests: list[httpx.Request] = []
    normal = successful_handler(requests)

    def handler(request: httpx.Request) -> httpx.Response:
        response = normal(request)
        if request.method != "GET":
            return response
        if (
            boundary == "policy"
            and request.url.path
            == f"/v1/sys/policies/acl/{cml_device_policy_name(DEVICE_ID)}"
        ):
            return httpx.Response(
                200,
                json=data(
                    {
                        "policy": cml_device_policy(DEVICE_ID)
                        + 'path "ncdp/data/devices/2/ssh" { capabilities = ["read"] }\n'
                    }
                ),
            )
        if (
            boundary == "role"
            and request.url.path
            == f"/v1/auth/jwt/role/{cml_deploy_role_name(DEVICE_ID)}"
        ):
            role = cml_deploy_role_config(PIPELINE_ID, DEVICE_ID)
            role["token_policies"] = [cml_device_policy_name(DEVICE_ID), "other"]
            return httpx.Response(200, json=data(role))
        return response

    expected = "policy verification" if boundary == "policy" else "role verification"
    with pytest.raises(SecretError, match=expected):
        configurator(handler).configure()


def test_operator_error_never_exposes_admin_token() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, content=ADMIN_TOKEN.encode())

    with pytest.raises(SecretError) as caught:
        configurator(handler).configure()
    assert ADMIN_TOKEN not in repr(caught.value)
