"""Exact one-use SNMP OpenBao consumer tests."""

from __future__ import annotations

import subprocess

import httpx
import pytest

from network_change_delivery import cli
from network_change_delivery.buildkite_identity import BuildkiteOIDCJWT
from network_change_delivery.buildkite_policy import BuildkiteDeploymentContext
from network_change_delivery.openbao_snmp_config import SNMP_OBSERVABILITY_POLICY_NAME
from network_change_delivery.secrets import SecretError
from network_change_delivery.snmp_credentials import (
    BuildkiteOpenBaoSnmpProvisioningProvider,
    OpenBaoSnmpObservabilitySource,
    snmp_provision_policy_name,
    snmp_provision_role_name,
    snmp_username,
)
from network_change_delivery.snmp_telemetry import SnmpCredentialReference

JWT = "sensitive.header.signature"
TOKEN = "sensitive-token"
AUTH = "auth-secret-sentinel-" + "A" * 27
PRIV = "priv-secret-sentinel-" + "B" * 27
USERNAME = snmp_username(1)


def context() -> BuildkiteDeploymentContext:
    return BuildkiteDeploymentContext(
        commit="a" * 40,
        branch="main",
        pipeline_id="pipeline-id",
        build_id="build-id",
        build_number="1",
        job_id="job-id",
        step_key="deploy-gate",
        queue_key="ncdp-deploy",
    )


def reference() -> SnmpCredentialReference:
    return SnmpCredentialReference(
        device="netbox:dcim.device:1",
        reference="snmpv3:netbox:dcim.device:1:generation:v1",
        auth_selector="device_1_v1",
    )


def secret_payload() -> dict[str, object]:
    return {
        "data": {
            "data": {
                "username": USERNAME,
                "authentication_secret": AUTH,
                "privacy_secret": PRIV,
            }
        }
    }


def jwt_auth() -> dict[str, object]:
    policy = snmp_provision_policy_name(1)
    return {
        "auth": {
            "client_token": TOKEN,
            "lease_duration": 300,
            "token_policies": [policy],
            "identity_policies": [],
            "policies": [policy],
            "metadata": {
                "pipeline_id": "pipeline-id",
                "build_commit": "a" * 40,
                "build_branch": "main",
                "step_key": "deploy-gate",
                "job_id": "job-id",
            },
        }
    }


def test_provisioning_provider_requests_fresh_exact_role_and_one_path() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json=jwt_auth()
            if request.url.path.endswith("/jwt/login")
            else secret_payload(),
        )

    calls = 0

    def jwt_source() -> BuildkiteOIDCJWT:
        nonlocal calls
        calls += 1
        return BuildkiteOIDCJWT(JWT)

    provider = BuildkiteOpenBaoSnmpProvisioningProvider(
        jwt_source,
        context(),
        reference(),
        USERNAME,
        "https://openbao.example",
        transport=httpx.MockTransport(handler),
    )
    credentials = provider.load()
    assert credentials.username == USERNAME
    assert credentials.authentication_secret == AUTH
    assert credentials.privacy_secret == PRIV
    assert calls == 1
    assert [request.url.path for request in requests] == [
        "/v1/auth/jwt/login",
        "/v1/ncdp/data/devices/1/snmpv3/v1",
    ]
    assert requests[0].read().decode().find(snmp_provision_role_name(1)) >= 0
    with pytest.raises(SecretError, match="already consumed"):
        provider.load()
    assert len(requests) == 2


def test_observability_source_has_one_login_and_one_exact_read() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/approle/login"):
            return httpx.Response(
                200,
                json={
                    "auth": {
                        "client_token": TOKEN,
                        "lease_duration": 300,
                        "token_policies": [SNMP_OBSERVABILITY_POLICY_NAME],
                        "identity_policies": [],
                        "policies": [SNMP_OBSERVABILITY_POLICY_NAME],
                    }
                },
            )
        return httpx.Response(200, json=secret_payload())

    source = OpenBaoSnmpObservabilitySource(
        "https://openbao.example",
        "role-id",
        "secret-id",
        reference(),
        USERNAME,
        transport=httpx.MockTransport(handler),
    )
    assert source.load().username == USERNAME
    with pytest.raises(SecretError, match="already consumed"):
        source.load()
    assert [request.method for request in requests] == ["POST", "GET"]


@pytest.mark.parametrize(
    "payload",
    [
        {"data": {"data": {"username": USERNAME, "authentication_secret": AUTH}}},
        {
            "data": {
                "data": {
                    "username": "wrong",
                    "authentication_secret": AUTH,
                    "privacy_secret": PRIV,
                }
            }
        },
        {
            "data": {
                "data": {
                    "username": USERNAME,
                    "authentication_secret": AUTH,
                    "privacy_secret": AUTH,
                }
            }
        },
    ],
)
def test_payload_schema_identity_and_independent_secrets_fail_closed(
    payload: object,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json=jwt_auth() if request.url.path.endswith("/jwt/login") else payload
        )

    provider = BuildkiteOpenBaoSnmpProvisioningProvider(
        lambda: BuildkiteOIDCJWT(JWT),
        context(),
        reference(),
        USERNAME,
        "https://openbao.example",
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(SecretError):
        provider.load()


def test_secret_values_are_redacted_from_representations_and_errors() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, content=(AUTH + PRIV + TOKEN + JWT).encode())

    provider = BuildkiteOpenBaoSnmpProvisioningProvider(
        lambda: BuildkiteOIDCJWT(JWT),
        context(),
        reference(),
        USERNAME,
        "https://openbao.example",
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(SecretError) as caught:
        provider.load()
    rendered = repr(provider) + repr(caught.value)
    for sentinel in (AUTH, PRIV, TOKEN, JWT):
        assert sentinel not in rendered


@pytest.mark.parametrize(
    "authentication,privacy",
    [
        ("A" * 47, "B" * 48),
        ("A" * 49, "B" * 48),
        ("A" * 47 + " ", "B" * 48),
        ("A" * 47 + "\n", "B" * 48),
        ("A" * 47 + '"', "B" * 48),
        ("A" * 47 + ";", "B" * 48),
        ("A" * 47 + "$", "B" * 48),
        ("A" * 47 + "\\", "B" * 48),
        ("A" * 48, "A" * 48),
    ],
)
def test_secret_format_is_exactly_shared_contract(authentication, privacy) -> None:
    from network_change_delivery.snmp_credentials import SnmpProvisioningCredentials

    with pytest.raises(SecretError):
        SnmpProvisioningCredentials(USERNAME, authentication, privacy)


def test_protected_cli_requests_a_distinct_bounded_snmp_oidc_exchange(
    monkeypatch,
) -> None:
    calls: list[list[str]] = []

    def run(arguments, **kwargs):
        calls.append(arguments)
        assert kwargs == {"check": False, "capture_output": True, "text": True}
        return subprocess.CompletedProcess(arguments, 0, stdout=JWT + "\n", stderr="")

    monkeypatch.setattr(cli.subprocess, "run", run)
    result = cli._request_buildkite_snmp_oidc_jwt()
    assert result.value == JWT
    assert calls == [
        [
            "buildkite-agent",
            "oidc",
            "request-token",
            "--audience",
            "urn:ncdp:openbao:deploy",
            "--lifetime",
            "300",
            "--subject-claim",
            "pipeline_id",
        ]
    ]
    assert JWT not in repr(result)


def test_protected_cli_consumes_only_explicit_audit_prewrite_marker(
    monkeypatch,
) -> None:
    monkeypatch.delenv("NCDP_AUDIT_PREWRITE_VERIFIED", raising=False)
    with pytest.raises(SecretError, match="pre-write gate"):
        cli._consume_buildkite_audit_prewrite_gate()
    monkeypatch.setenv("NCDP_AUDIT_PREWRITE_VERIFIED", "1")
    cli._consume_buildkite_audit_prewrite_gate()
    assert "NCDP_AUDIT_PREWRITE_VERIFIED" not in cli.os.environ
    with pytest.raises(SecretError, match="pre-write gate"):
        cli._consume_buildkite_audit_prewrite_gate()
