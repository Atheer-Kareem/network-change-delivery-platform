"""Mocked operator tests for the OpenBao Buildkite JWT configuration."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from network_change_delivery.buildkite_identity import (
    BUILDKITE_OIDC_ISSUER,
    OPENBAO_BUILDKITE_JWT_AUDIENCE,
    OPENBAO_BUILDKITE_JWT_ROLE,
)
from network_change_delivery.openbao_jwt_config import (
    JWT_CLAIM_MAPPINGS,
    JWT_CONFIG_READ,
    JWT_CONFIG_WRITE,
    JWT_MOUNT_DESCRIPTION,
    OpenBaoBuildkiteJWTConfigurator,
    buildkite_jwt_role_config,
    validate_pipeline_id,
)
from network_change_delivery.secrets import SecretError

ADMIN_TOKEN = "sensitive-openbao-admin-token"
PIPELINE_ID = "0184990a-4782-42b5-afc1-16715b10b1f0"
ROOT = Path(__file__).resolve().parents[1]


def mount_payload(
    *,
    present: bool = True,
    auth_type: str = "jwt",
    description: str | None = JWT_MOUNT_DESCRIPTION,
) -> dict[str, object]:
    mounts: dict[str, object] = {"approle/": {"type": "approle"}}
    if present:
        mounted: dict[str, object] = {"type": auth_type}
        if description is not None:
            mounted["description"] = description
        mounts["jwt/"] = mounted
    return {"data": mounts}


def config_payload(**changes: object) -> dict[str, object]:
    values: dict[str, object] = {
        **JWT_CONFIG_READ,
        "oidc_discovery_ca_pem": [],
        "jwks_url": "",
        "jwt_validation_pubkeys": [],
        "oidc_client_id": "",
        "oidc_client_secret": "",
    }
    values.update(changes)
    return {"data": values}


def role_payload(**changes: object) -> dict[str, object]:
    values = buildkite_jwt_role_config(PIPELINE_ID)
    values.update(changes)
    return {"data": values}


def configurator(handler) -> OpenBaoBuildkiteJWTConfigurator:
    return OpenBaoBuildkiteJWTConfigurator(
        "https://openbao.example",
        ADMIN_TOKEN,
        PIPELINE_ID,
        transport=httpx.MockTransport(handler),
    )


def successful_handler(requests: list[httpx.Request], *, mount_present: bool):
    mount_enabled = mount_present

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal mount_enabled
        requests.append(request)
        path = request.url.path
        if path == "/v1/sys/auth" and request.method == "GET":
            return httpx.Response(200, json=mount_payload(present=mount_enabled))
        if path == "/v1/sys/auth/jwt" and request.method == "POST":
            mount_enabled = True
            return httpx.Response(204)
        if path == "/v1/auth/jwt/config" and request.method == "POST":
            return httpx.Response(204)
        if path == "/v1/auth/jwt/config" and request.method == "GET":
            return httpx.Response(200, json=config_payload())
        if path == f"/v1/auth/jwt/role/{OPENBAO_BUILDKITE_JWT_ROLE}":
            if request.method == "POST":
                return httpx.Response(204)
            return httpx.Response(200, json=role_payload())
        raise AssertionError(f"unexpected request: {request.method} {path}")

    return handler


def test_absent_mount_is_enabled_then_exact_config_is_verified() -> None:
    requests: list[httpx.Request] = []
    assert configurator(successful_handler(requests, mount_present=False)).configure()
    assert [(request.method, request.url.path) for request in requests] == [
        ("GET", "/v1/sys/auth"),
        ("POST", "/v1/sys/auth/jwt"),
        ("GET", "/v1/sys/auth"),
        ("POST", "/v1/auth/jwt/config"),
        ("GET", "/v1/auth/jwt/config"),
        ("POST", f"/v1/auth/jwt/role/{OPENBAO_BUILDKITE_JWT_ROLE}"),
        ("GET", f"/v1/auth/jwt/role/{OPENBAO_BUILDKITE_JWT_ROLE}"),
    ]
    assert json.loads(requests[1].content) == {
        "type": "jwt",
        "description": JWT_MOUNT_DESCRIPTION,
    }
    assert json.loads(requests[3].content) == JWT_CONFIG_WRITE
    assert json.loads(requests[5].content) == buildkite_jwt_role_config(PIPELINE_ID)
    assert all(request.headers["X-Vault-Token"] == ADMIN_TOKEN for request in requests)


def test_existing_jwt_mount_is_not_enabled_again() -> None:
    requests: list[httpx.Request] = []
    assert not configurator(
        successful_handler(requests, mount_present=True)
    ).configure()
    assert ("POST", "/v1/sys/auth/jwt") not in [
        (request.method, request.url.path) for request in requests
    ]


def test_repeated_configuration_is_idempotent() -> None:
    requests: list[httpx.Request] = []
    handler = successful_handler(requests, mount_present=False)
    assert configurator(handler).configure()
    assert not configurator(handler).configure()
    assert sum(request.url.path == "/v1/sys/auth/jwt" for request in requests) == 1


def test_conflicting_jwt_mount_type_fails_closed() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=mount_payload(auth_type="approle"))

    with pytest.raises(SecretError, match="not owned by NCDP"):
        configurator(handler).configure()


@pytest.mark.parametrize("description", [None, "Other JWT workload"])
def test_unowned_existing_jwt_mount_fails_closed(description: str | None) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=mount_payload(description=description))

    with pytest.raises(SecretError, match="not owned by NCDP"):
        configurator(handler).configure()


def test_exact_role_has_identity_constraints_and_no_secret_capability() -> None:
    role = buildkite_jwt_role_config(PIPELINE_ID)
    assert role == {
        "role_type": "jwt",
        "bound_audiences": [OPENBAO_BUILDKITE_JWT_AUDIENCE],
        "bound_subject": PIPELINE_ID,
        "user_claim": "sub",
        "bound_claims_type": "string",
        "bound_claims": {"build_branch": "main", "step_key": "deploy-gate"},
        "claim_mappings": JWT_CLAIM_MAPPINGS,
        "token_no_default_policy": True,
        "token_policies": [],
        "token_ttl": 300,
        "token_max_ttl": 300,
        "token_explicit_max_ttl": 300,
        "token_num_uses": 1,
    }
    assert JWT_CONFIG_WRITE == {
        "oidc_discovery_url": BUILDKITE_OIDC_ISSUER,
        "bound_issuer": BUILDKITE_OIDC_ISSUER,
        "skip_jwks_validation": False,
    }
    assert JWT_CONFIG_READ == {
        "oidc_discovery_url": BUILDKITE_OIDC_ISSUER,
        "bound_issuer": BUILDKITE_OIDC_ISSUER,
        "status": "valid",
    }
    assert all(source.startswith("/") for source in JWT_CLAIM_MAPPINGS)
    assert JWT_CLAIM_MAPPINGS == {
        "/sub": "pipeline_id",
        "/build_commit": "build_commit",
        "/build_branch": "build_branch",
        "/step_key": "step_key",
        "/job_id": "job_id",
    }
    assert "/pipeline_id" not in JWT_CLAIM_MAPPINGS
    assert not role["token_policies"]


def test_existing_owned_role_is_rewritten_to_sub_contract() -> None:
    requests: list[httpx.Request] = []
    assert not configurator(
        successful_handler(requests, mount_present=True)
    ).configure()
    role_write = next(
        request
        for request in requests
        if request.method == "POST"
        and request.url.path == f"/v1/auth/jwt/role/{OPENBAO_BUILDKITE_JWT_ROLE}"
    )
    written = json.loads(role_write.content)
    assert written["user_claim"] == "sub"
    assert written["claim_mappings"]["/sub"] == "pipeline_id"
    assert "/pipeline_id" not in written["claim_mappings"]


@pytest.mark.parametrize(
    "value",
    ["", "pipeline-slug", PIPELINE_ID.upper(), "0184990a-4782-42b5-afc1-16715b10b1f"],
)
def test_pipeline_id_must_be_a_canonical_uuid(value: str) -> None:
    with pytest.raises(SecretError, match="pipeline ID rejected"):
        validate_pipeline_id(value)


def test_operator_inputs_are_environment_only() -> None:
    requests: list[httpx.Request] = []
    configured = OpenBaoBuildkiteJWTConfigurator.from_environment(
        {
            "NCDP_OPENBAO_URL": "https://openbao.example",
            "BAO_TOKEN": ADMIN_TOKEN,
            "NCDP_BUILDKITE_PIPELINE_ID": PIPELINE_ID,
        },
        transport=httpx.MockTransport(successful_handler(requests, mount_present=True)),
    )
    assert not configured.configure()
    assert ADMIN_TOKEN not in repr(configured)


def test_operator_script_rejects_cli_arguments() -> None:
    script = (ROOT / "scripts/openbao/configure_buildkite_jwt.py").read_text()
    assert "if len(sys.argv) != 1:" in script
    assert "command-line arguments are not accepted" in script


@pytest.mark.parametrize(
    "missing", ["NCDP_OPENBAO_URL", "BAO_TOKEN", "NCDP_BUILDKITE_PIPELINE_ID"]
)
def test_all_operator_environment_inputs_are_required(missing: str) -> None:
    environment = {
        "NCDP_OPENBAO_URL": "https://openbao.example",
        "BAO_TOKEN": ADMIN_TOKEN,
        "NCDP_BUILDKITE_PIPELINE_ID": PIPELINE_ID,
    }
    environment[missing] = ""
    with pytest.raises(SecretError, match="configuration missing") as caught:
        OpenBaoBuildkiteJWTConfigurator.from_environment(environment)
    assert ADMIN_TOKEN not in repr(caught.value)


@pytest.mark.parametrize(
    ("path", "response", "message"),
    [
        ("/v1/auth/jwt/config", config_payload(status="invalid"), "backend"),
        (
            "/v1/auth/jwt/config",
            config_payload(oidc_discovery_url="https://other.example"),
            "backend",
        ),
        ("/v1/auth/jwt/config", config_payload(bound_issuer="wrong"), "backend"),
        (
            "/v1/auth/jwt/config",
            config_payload(jwks_url="https://jwks.example"),
            "backend",
        ),
        (
            "/v1/auth/jwt/config",
            config_payload(jwt_validation_pubkeys=["public-key"]),
            "backend",
        ),
        ("/v1/auth/jwt/config", config_payload(oidc_client_id="client"), "backend"),
        ("/v1/auth/jwt/config", config_payload(oidc_client_secret="secret"), "backend"),
        (
            f"/v1/auth/jwt/role/{OPENBAO_BUILDKITE_JWT_ROLE}",
            role_payload(token_policies=["secret-read"]),
            "role",
        ),
        (
            f"/v1/auth/jwt/role/{OPENBAO_BUILDKITE_JWT_ROLE}",
            role_payload(user_claim="pipeline_id"),
            "role",
        ),
        (
            f"/v1/auth/jwt/role/{OPENBAO_BUILDKITE_JWT_ROLE}",
            role_payload(
                claim_mappings={
                    "/pipeline_id": "pipeline_id",
                    "/build_commit": "build_commit",
                    "/build_branch": "build_branch",
                    "/step_key": "step_key",
                    "/job_id": "job_id",
                }
            ),
            "role",
        ),
    ],
)
def test_read_back_mismatch_fails_closed(
    path: str, response: dict[str, object], message: str
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/sys/auth":
            return httpx.Response(200, json=mount_payload())
        if request.method == "POST":
            return httpx.Response(204)
        if request.url.path == path:
            return httpx.Response(200, json=response)
        if request.url.path == "/v1/auth/jwt/config":
            return httpx.Response(200, json=config_payload())
        return httpx.Response(200, json=role_payload())

    with pytest.raises(SecretError, match=message):
        configurator(handler).configure()


@pytest.mark.parametrize("payload", [b"not-json", [], {}, {"data": []}])
def test_malformed_mount_response_is_rejected(payload: object) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        if isinstance(payload, bytes):
            return httpx.Response(200, content=payload)
        return httpx.Response(200, json=payload)

    with pytest.raises(SecretError, match="invalid JSON or schema"):
        configurator(handler).configure()


@pytest.mark.parametrize("status", [302, 404, 500])
def test_redirects_and_unexpected_statuses_are_bounded(status: int) -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            status,
            headers={"Location": "https://other.example"},
            content=ADMIN_TOKEN.encode(),
        )

    with pytest.raises(SecretError, match=f"unexpected HTTP status {status}") as caught:
        configurator(handler).configure()
    assert calls == 1
    assert ADMIN_TOKEN not in repr(caught.value)


@pytest.mark.parametrize("error_type", [httpx.ConnectError, httpx.ReadTimeout])
def test_transport_failures_are_bounded(error_type) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise error_type(ADMIN_TOKEN, request=request)

    with pytest.raises(SecretError) as caught:
        configurator(handler).configure()
    assert str(caught.value) == "OpenBao unavailable or timed out"
    assert ADMIN_TOKEN not in repr(caught.value)


def test_admin_token_never_appears_in_authentication_error() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, content=ADMIN_TOKEN.encode())

    with pytest.raises(SecretError) as caught:
        configurator(handler).configure()
    assert str(caught.value) == "OpenBao operator request unauthorized"
    assert ADMIN_TOKEN not in repr(caught.value)
