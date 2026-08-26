from __future__ import annotations

import json

import httpx
import pytest

from network_change_delivery.buildkite_staging import (
    staging_policy_name,
    staging_role_name,
)
from network_change_delivery.openbao_jwt_config import (
    JWT_CONFIG_READ,
    JWT_MOUNT_DESCRIPTION,
)
from network_change_delivery.openbao_staging_config import (
    OpenBaoBuildkiteStagingConfigurator,
    staging_policy,
    staging_role_config,
)
from network_change_delivery.secrets import SecretError

PIPELINE_ID = "01a02ab4-2472-4726-be31-dbf4f216210f"
ADMIN_TOKEN = "admin-token"


def handler(requests: list[httpx.Request], *, broaden: str | None = None):
    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        path = request.url.path
        if path == "/v1/sys/auth":
            return httpx.Response(
                200,
                json={
                    "data": {
                        "jwt/": {
                            "type": "jwt",
                            "description": JWT_MOUNT_DESCRIPTION,
                        }
                    }
                },
            )
        if path == "/v1/auth/jwt/config":
            return httpx.Response(200, json={"data": JWT_CONFIG_READ})
        for device_id in (1, 2):
            if path == f"/v1/sys/policies/acl/{staging_policy_name(device_id)}":
                if request.method == "PUT":
                    return httpx.Response(204)
                policy = staging_policy(device_id)
                if broaden == "policy":
                    policy += 'path "ncdp/data/devices/9/ssh" { capabilities=["read"] }'
                return httpx.Response(200, json={"data": {"policy": policy}})
            if path == f"/v1/auth/jwt/role/{staging_role_name(device_id)}":
                if request.method == "POST":
                    return httpx.Response(204)
                role = staging_role_config(PIPELINE_ID, device_id)
                if broaden == "role":
                    role["token_num_uses"] = 0
                return httpx.Response(200, json={"data": role})
        raise AssertionError(path)

    return respond


def test_configures_and_verifies_exact_two_staging_roles() -> None:
    requests: list[httpx.Request] = []
    configured = OpenBaoBuildkiteStagingConfigurator(
        "https://openbao.example",
        ADMIN_TOKEN,
        PIPELINE_ID,
        transport=httpx.MockTransport(handler(requests)),
    ).configure()
    assert configured == (
        (staging_policy_name(1), staging_role_name(1)),
        (staging_policy_name(2), staging_role_name(2)),
    )
    assert all(request.headers["X-Vault-Token"] == ADMIN_TOKEN for request in requests)
    for device_id in (1, 2):
        role = staging_role_config(PIPELINE_ID, device_id)
        assert role["bound_audiences"] == ["urn:ncdp:openbao:staging"]
        assert role["bound_claims"] == {"step_key": "cml-staging"}
        assert role["token_policies"] == [staging_policy_name(device_id)]
        assert role["token_num_uses"] == 1
        assert role["claim_mappings"]["/build_id"] == "build_id"
        assert staging_policy(device_id).count("path ") == 1


@pytest.mark.parametrize("broaden", ["policy", "role"])
def test_readback_rejects_broader_configuration(broaden: str) -> None:
    with pytest.raises(SecretError, match="verification failed"):
        OpenBaoBuildkiteStagingConfigurator(
            "https://openbao.example",
            ADMIN_TOKEN,
            PIPELINE_ID,
            transport=httpx.MockTransport(handler([], broaden=broaden)),
        ).configure()


def test_configurator_does_not_modify_deployment_roles() -> None:
    requests: list[httpx.Request] = []
    OpenBaoBuildkiteStagingConfigurator(
        "https://openbao.example",
        ADMIN_TOKEN,
        PIPELINE_ID,
        transport=httpx.MockTransport(handler(requests)),
    ).configure()
    paths = {request.url.path for request in requests}
    assert not any("deploy" in path for path in paths)
    assert all(
        "ncdp-buildkite-staging" in path
        or path in {"/v1/sys/auth", "/v1/auth/jwt/config"}
        for path in paths
    )
    assert (
        json.dumps([request.content.decode() for request in requests]).find(ADMIN_TOKEN)
        == -1
    )
