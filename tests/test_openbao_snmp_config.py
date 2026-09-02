"""Offline OpenBao SNMP policy, role, and create-only generation tests."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from network_change_delivery.openbao_cml_config import cml_device_policy
from network_change_delivery.openbao_jwt_config import JWT_MOUNT_DESCRIPTION
from network_change_delivery.openbao_snmp_config import (
    SNMP_OBSERVABILITY_POLICY,
    SNMP_OBSERVABILITY_POLICY_NAME,
    SNMP_OBSERVABILITY_ROLE,
    SNMP_OBSERVABILITY_ROLE_NAME,
    OpenBaoSnmpConfigurator,
    SnmpGenerationOutcome,
    SnmpGenerationPartialError,
    snmp_provision_policy,
    snmp_provision_role_config,
)
from network_change_delivery.secrets import SecretError
from network_change_delivery.snmp_credentials import (
    snmp_provision_policy_name,
    snmp_provision_role_name,
    snmp_username,
)

PIPELINE_ID = "01a02ab4-2472-4726-be31-dbf4f216210f"
ADMIN = "admin-token-sentinel"


def data(value: dict[str, object]) -> dict[str, object]:
    return {"data": value}


def configure_handler(requests: list[httpx.Request]):
    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        path = request.url.path
        if path == "/v1/sys/auth":
            return httpx.Response(
                200,
                json=data(
                    {
                        "jwt/": {"type": "jwt", "description": JWT_MOUNT_DESCRIPTION},
                        "approle/": {"type": "approle"},
                    }
                ),
            )
        for device_id in (1, 2):
            if path == f"/v1/sys/policies/acl/{snmp_provision_policy_name(device_id)}":
                return (
                    httpx.Response(204)
                    if request.method == "PUT"
                    else httpx.Response(
                        200, json=data({"policy": snmp_provision_policy(device_id)})
                    )
                )
            if path == f"/v1/auth/jwt/role/{snmp_provision_role_name(device_id)}":
                return (
                    httpx.Response(204)
                    if request.method == "POST"
                    else httpx.Response(
                        200,
                        json=data(snmp_provision_role_config(PIPELINE_ID, device_id)),
                    )
                )
        if path == f"/v1/sys/policies/acl/{SNMP_OBSERVABILITY_POLICY_NAME}":
            return (
                httpx.Response(204)
                if request.method == "PUT"
                else httpx.Response(
                    200, json=data({"policy": SNMP_OBSERVABILITY_POLICY})
                )
            )
        if path == f"/v1/auth/approle/role/{SNMP_OBSERVABILITY_ROLE_NAME}":
            return (
                httpx.Response(204)
                if request.method == "POST"
                else httpx.Response(200, json=data(SNMP_OBSERVABILITY_ROLE))
            )
        raise AssertionError(f"unexpected request {request.method} {path}")

    return handler


def configurator(handler, *, random_choice=None) -> OpenBaoSnmpConfigurator:
    kwargs = {} if random_choice is None else {"random_choice": random_choice}
    return OpenBaoSnmpConfigurator(
        "https://openbao.example",
        ADMIN,
        PIPELINE_ID,
        transport=httpx.MockTransport(handler),
        **kwargs,
    )


def test_exact_authorities_are_configured_and_read_back() -> None:
    requests: list[httpx.Request] = []
    names = configurator(configure_handler(requests)).configure_authorities()
    assert names == (
        snmp_provision_policy_name(1),
        snmp_provision_role_name(1),
        snmp_provision_policy_name(2),
        snmp_provision_role_name(2),
        SNMP_OBSERVABILITY_POLICY_NAME,
        SNMP_OBSERVABILITY_ROLE_NAME,
    )
    assert all(request.headers["X-Vault-Token"] == ADMIN for request in requests)
    for device_id in (1, 2):
        policy = snmp_provision_policy(device_id)
        assert policy.count("path ") == 1
        assert f"devices/{device_id}/snmpv3/v1" in policy
        assert 'capabilities = ["read"]' in policy
        for forbidden in ("ssh", "*", "list", "create", "update", "delete"):
            assert forbidden not in policy
        role = snmp_provision_role_config(PIPELINE_ID, device_id)
        assert role["bound_claims"] == {
            "build_branch": "main",
            "step_key": "deploy-gate",
        }
        assert role["token_no_default_policy"] is True
        assert role["token_num_uses"] == 1
        assert role["token_policies"] == [snmp_provision_policy_name(device_id)]
    assert "ssh" not in SNMP_OBSERVABILITY_POLICY
    assert 'capabilities = ["read"]' in SNMP_OBSERVABILITY_POLICY
    assert SNMP_OBSERVABILITY_POLICY.count("path ") == 2
    assert "devices/8/" not in SNMP_OBSERVABILITY_POLICY
    assert "devices/9/" not in SNMP_OBSERVABILITY_POLICY
    assert SNMP_OBSERVABILITY_ROLE["secret_id_num_uses"] == 2
    assert SNMP_OBSERVABILITY_ROLE["token_no_default_policy"] is True
    assert SNMP_OBSERVABILITY_ROLE["token_num_uses"] == 1
    for device_id in (1, 2):
        assert "snmpv3" not in cml_device_policy(device_id)
        assert "ssh" not in snmp_provision_policy(device_id)


def test_generation_is_random_independent_cas_zero_and_read_back_verified() -> None:
    requests: list[httpx.Request] = []
    sequence = iter(("A" * 48) + ("B" * 48))

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET" and len(requests) == 1:
            return httpx.Response(404)
        if request.method == "POST":
            return httpx.Response(204)
        written = json.loads(requests[1].content)["data"]
        return httpx.Response(
            200, json=data({"data": written, "metadata": {"version": 1}})
        )

    result = configurator(
        handler, random_choice=lambda _alphabet: next(sequence)
    ).create_generation(1, "v1")
    assert result.outcome is SnmpGenerationOutcome.CREATED
    assert result.username == snmp_username(1)
    body = json.loads(requests[1].content)
    assert body["options"] == {"cas": 0}
    assert body["data"]["authentication_secret"] == "A" * 48
    assert body["data"]["privacy_secret"] == "B" * 48
    assert body["data"]["authentication_secret"] != body["data"]["privacy_secret"]
    assert requests[1].url.path == "/v1/ncdp/data/devices/1/snmpv3/v1"


def test_existing_generation_is_never_overwritten() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json=data(
                {
                    "data": {
                        "username": snmp_username(2),
                        "authentication_secret": "A" * 48,
                        "privacy_secret": "B" * 48,
                    }
                }
            ),
        )

    result = configurator(handler).create_generation(2, "v1")
    assert result.outcome is SnmpGenerationOutcome.ALREADY_EXISTS
    assert [request.method for request in requests] == ["GET"]


def test_unreviewed_generation_is_rejected_before_openbao_access() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(500)

    with pytest.raises(SecretError, match="not reviewed"):
        configurator(handler).create_generation(1, "v2")
    assert requests == []


def test_foreign_existing_generation_fails_closed_without_overwrite() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=data({"data": {"username": "foreign"}}))

    with pytest.raises(SecretError, match="existing SNMP generation rejected"):
        configurator(handler).create_generation(1, "v1")
    assert [request.method for request in requests] == ["GET"]


def test_successful_create_with_failed_readback_is_classified_partial() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(404)
        if len(requests) == 2:
            return httpx.Response(204)
        return httpx.Response(503)

    with pytest.raises(SnmpGenerationPartialError) as caught:
        configurator(handler).create_generation(1, "v1")
    assert caught.value.outcome is SnmpGenerationOutcome.PARTIAL
    assert [request.method for request in requests] == ["GET", "POST", "GET"]


def test_foreign_policy_fails_closed_before_any_authority_write() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/v1/sys/auth":
            return httpx.Response(
                200,
                json=data(
                    {
                        "jwt/": {"type": "jwt", "description": JWT_MOUNT_DESCRIPTION},
                        "approle/": {"type": "approle"},
                    }
                ),
            )
        return httpx.Response(200, json=data({"policy": 'path "foreign" {}'}))

    with pytest.raises(SecretError, match="policy verification"):
        configurator(handler).configure_authorities()
    assert [request.method for request in requests] == ["GET", "GET"]


def test_foreign_role_fails_closed_without_reconfiguration() -> None:
    requests: list[httpx.Request] = []
    ordinary = configure_handler(requests)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == f"/v1/auth/jwt/role/{snmp_provision_role_name(1)}":
            requests.append(request)
            role = snmp_provision_role_config(PIPELINE_ID, 1)
            role["token_policies"] = ["foreign"]
            return httpx.Response(200, json=data(role))
        return ordinary(request)

    with pytest.raises(SecretError, match="role verification"):
        configurator(handler).configure_authorities()
    assert all(request.method == "GET" for request in requests)


def test_cas_conflict_and_foreign_readback_fail_without_secret_output() -> None:
    def conflict(request: httpx.Request) -> httpx.Response:
        return (
            httpx.Response(404)
            if request.method == "GET"
            else httpx.Response(400, content=ADMIN.encode())
        )

    with pytest.raises(SecretError) as caught:
        configurator(conflict).create_generation(1)
    assert ADMIN not in repr(caught.value)


def test_operator_script_has_no_argument_or_value_output_boundary() -> None:
    text = Path("scripts/openbao/configure_snmp_authority.py").read_text(
        encoding="utf-8"
    )
    assert "if len(sys.argv) != 1:" in text
    assert "command-line arguments are not accepted" in text
    assert "authentication_secret" not in text
    assert "privacy_secret" not in text
