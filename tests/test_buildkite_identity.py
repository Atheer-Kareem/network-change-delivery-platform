"""Buildkite JWT identity tests at the real OpenBao HTTP boundary."""

from __future__ import annotations

import json
from io import StringIO

import httpx
import pytest

import network_change_delivery.secrets as secrets_module
from network_change_delivery.buildkite_identity import (
    BUILDKITE_JWT_MAX_INPUT_BYTES,
    BUILDKITE_OIDC_ISSUER,
    OPENBAO_BUILDKITE_JWT_AUDIENCE,
    OPENBAO_BUILDKITE_JWT_ROLE,
    BuildkiteOIDCJWT,
    OpenBaoBuildkiteJWTAuthenticator,
    read_buildkite_oidc_jwt,
)
from network_change_delivery.buildkite_policy import BuildkiteDeploymentContext
from network_change_delivery.secrets import SecretError

JWT = "secret-header.secret-payload.secret-signature"
CLIENT_TOKEN = "sensitive-openbao-client-token"


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


def metadata(**changes: object) -> dict[str, object]:
    values: dict[str, object] = {
        "pipeline_id": "pipeline-uuid",
        "build_commit": "a" * 40,
        "build_branch": "main",
        "step_key": "deploy-gate",
        "job_id": "job-uuid",
    }
    values.update(changes)
    return values


def login_payload(**auth_changes: object) -> dict[str, object]:
    auth: dict[str, object] = {
        "client_token": CLIENT_TOKEN,
        "lease_duration": 300,
        "metadata": metadata(),
    }
    auth.update(auth_changes)
    return {"auth": auth}


def authenticator(handler) -> OpenBaoBuildkiteJWTAuthenticator:
    return OpenBaoBuildkiteJWTAuthenticator(
        "https://openbao.example", transport=httpx.MockTransport(handler)
    )


def test_fixed_external_identity_contract() -> None:
    assert BUILDKITE_OIDC_ISSUER == "https://agent.buildkite.com"
    assert OPENBAO_BUILDKITE_JWT_AUDIENCE == "urn:ncdp:openbao:deploy"
    assert OPENBAO_BUILDKITE_JWT_ROLE == "ncdp-buildkite-deploy"


def test_jwt_auth_uses_the_shared_hardened_http_client(monkeypatch) -> None:
    options: dict[str, object] = {}

    def client_spy(**kwargs: object) -> object:
        options.update(kwargs)
        return object()

    monkeypatch.setattr(secrets_module.httpx, "Client", client_spy)
    OpenBaoBuildkiteJWTAuthenticator("https://openbao.example")
    assert options["trust_env"] is False
    assert options["verify"] is True
    assert options["follow_redirects"] is False


def test_exact_jwt_login_request_and_verified_result() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=login_payload())

    result = authenticator(handler).authenticate(BuildkiteOIDCJWT(JWT), context())
    assert len(requests) == 1
    request = requests[0]
    assert request.method == "POST"
    assert request.url.path == "/v1/auth/jwt/login"
    assert request.url.query == b""
    assert json.loads(request.content) == {
        "role": OPENBAO_BUILDKITE_JWT_ROLE,
        "jwt": JWT,
    }
    assert "X-Vault-Token" not in request.headers
    assert result.lease_duration == 300
    assert result.identity_metadata == metadata()


def test_secret_representations_are_redacted() -> None:
    jwt = BuildkiteOIDCJWT(JWT)
    result = authenticator(
        lambda _request: httpx.Response(200, json=login_payload())
    ).authenticate(jwt, context())
    assert JWT not in repr(jwt)
    assert CLIENT_TOKEN not in repr(result)


@pytest.mark.parametrize(
    "value",
    [
        "",
        "\n",
        "header.payload",
        "header.payload.signature\nextra",
        "header.payload.signature\r\n",
        "header.payload.signature ",
        "x" * (BUILDKITE_JWT_MAX_INPUT_BYTES + 1),
    ],
)
def test_jwt_stdin_transport_rejects_invalid_input(value: str) -> None:
    with pytest.raises(SecretError, match="input rejected") as caught:
        read_buildkite_oidc_jwt(StringIO(value))
    if value:
        assert value not in str(caught.value)


def test_jwt_stdin_accepts_one_compact_value_with_optional_newline() -> None:
    assert read_buildkite_oidc_jwt(StringIO(JWT)).value == JWT
    assert read_buildkite_oidc_jwt(StringIO(JWT + "\n")).value == JWT


@pytest.mark.parametrize("payload", [b"not-json", [], {}, {"auth": []}])
def test_malformed_login_json_or_schema_is_rejected(payload: object) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        if isinstance(payload, bytes):
            return httpx.Response(200, content=payload)
        return httpx.Response(200, json=payload)

    with pytest.raises(SecretError, match="invalid JSON or schema"):
        authenticator(handler).authenticate(BuildkiteOIDCJWT(JWT), context())


@pytest.mark.parametrize(
    "change",
    [
        {"client_token": None},
        {"client_token": ""},
        {"lease_duration": None},
        {"lease_duration": 0},
        {"lease_duration": -1},
        {"lease_duration": True},
        {"lease_duration": "300"},
        {"lease_duration": 301},
    ],
)
def test_unacceptable_token_and_lease_are_rejected(change: dict[str, object]) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=login_payload(**change))

    with pytest.raises(SecretError, match="unacceptable token") as caught:
        authenticator(handler).authenticate(BuildkiteOIDCJWT(JWT), context())
    assert JWT not in repr(caught.value)
    assert CLIENT_TOKEN not in repr(caught.value)


@pytest.mark.parametrize(
    "value",
    [None, [], {}, {"pipeline_id": "pipeline-uuid"}, metadata(job_id=7)],
)
def test_absent_or_malformed_identity_metadata_is_rejected(value: object) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=login_payload(metadata=value))

    with pytest.raises(SecretError, match="invalid identity metadata"):
        authenticator(handler).authenticate(BuildkiteOIDCJWT(JWT), context())


@pytest.mark.parametrize(
    ("claim", "wrong"),
    [
        ("pipeline_id", "other-pipeline"),
        ("build_commit", "b" * 40),
        ("build_branch", "feature"),
        ("step_key", "other-step"),
        ("job_id", "other-job"),
    ],
)
def test_each_identity_mismatch_fails_closed(claim: str, wrong: str) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json=login_payload(metadata=metadata(**{claim: wrong}))
        )

    with pytest.raises(SecretError, match=f"identity mismatch: {claim}") as caught:
        authenticator(handler).authenticate(BuildkiteOIDCJWT(JWT), context())
    assert JWT not in repr(caught.value)
    assert CLIENT_TOKEN not in repr(caught.value)


@pytest.mark.parametrize("status", [400, 401, 403])
def test_authentication_failures_are_bounded(status: int) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, content=JWT.encode())

    with pytest.raises(SecretError) as caught:
        authenticator(handler).authenticate(BuildkiteOIDCJWT(JWT), context())
    assert str(caught.value) == "OpenBao JWT authentication failed"
    assert JWT not in repr(caught.value)


@pytest.mark.parametrize("status", [302, 404, 500])
def test_redirects_and_unexpected_statuses_are_not_followed(status: int) -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            status, headers={"Location": "https://other.example"}, content=JWT.encode()
        )

    with pytest.raises(SecretError, match=f"unexpected HTTP status {status}") as caught:
        authenticator(handler).authenticate(BuildkiteOIDCJWT(JWT), context())
    assert calls == 1
    assert JWT not in repr(caught.value)


@pytest.mark.parametrize("error_type", [httpx.ConnectError, httpx.ReadTimeout])
def test_transport_failures_are_bounded(error_type) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise error_type(JWT, request=request)

    with pytest.raises(SecretError) as caught:
        authenticator(handler).authenticate(BuildkiteOIDCJWT(JWT), context())
    assert str(caught.value) == "OpenBao unavailable or timed out"
    assert JWT not in repr(caught.value)
