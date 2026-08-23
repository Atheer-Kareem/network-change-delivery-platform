"""Buildkite JWT identity tests at the real OpenBao HTTP boundary."""

from __future__ import annotations

import base64
import json
from io import StringIO

import httpx
import pytest

import network_change_delivery.secrets as secrets_module
from network_change_delivery.buildkite_identity import (
    BUILDKITE_JWT_MAX_INPUT_BYTES,
    BUILDKITE_OIDC_ISSUER,
    BUILDKITE_OIDC_SUBJECT_CLAIM,
    BUILDKITE_OIDC_TOKEN_LIFETIME_SECONDS,
    OPENBAO_BUILDKITE_JWT_AUDIENCE,
    OPENBAO_BUILDKITE_JWT_ROLE,
    OPENBAO_BUILDKITE_MAX_LEASE_SECONDS,
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
        "token_policies": [],
        "identity_policies": [],
        "policies": [],
        "metadata": metadata(),
    }
    auth.update(auth_changes)
    return {"auth": auth}


def authenticator(handler) -> OpenBaoBuildkiteJWTAuthenticator:
    return OpenBaoBuildkiteJWTAuthenticator(
        "https://openbao.example", transport=httpx.MockTransport(handler)
    )


def diagnostic_jwt(**payload_changes: object) -> BuildkiteOIDCJWT:
    def encode(value: object) -> str:
        raw = json.dumps(value, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    payload: dict[str, object] = {
        "iss": BUILDKITE_OIDC_ISSUER,
        "sub": "pipeline-uuid",
        "aud": OPENBAO_BUILDKITE_JWT_AUDIENCE,
        "pipeline_id": None,
        "build_branch": "main",
        "build_commit": "a" * 40,
        "step_key": "deploy-gate",
        "job_id": "job-uuid",
        "iat": 100,
        "nbf": 100,
        "exp": 400,
        "ignored_secret_claim": "must-not-print",
    }
    payload.update(payload_changes)
    return BuildkiteOIDCJWT(
        f"{encode({'alg': 'RS256', 'kid': 'key-1', 'ignored': 'hidden'})}."
        f"{encode(payload)}.signature"
    )


def test_fixed_external_identity_contract() -> None:
    assert BUILDKITE_OIDC_ISSUER == "https://agent.buildkite.com"
    assert BUILDKITE_OIDC_SUBJECT_CLAIM == "pipeline_id"
    assert BUILDKITE_OIDC_TOKEN_LIFETIME_SECONDS == 300
    assert OPENBAO_BUILDKITE_JWT_AUDIENCE == "urn:ncdp:openbao:deploy"
    assert OPENBAO_BUILDKITE_JWT_ROLE == "ncdp-buildkite-deploy"
    assert OPENBAO_BUILDKITE_MAX_LEASE_SECONDS == 300


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
    "change",
    [
        {"token_policies": ["default"], "policies": ["default"]},
        {"token_policies": ["unexpected"], "policies": ["unexpected"]},
        {"identity_policies": ["identity-policy"], "policies": ["identity-policy"]},
        {"policies": ["aggregate-policy"]},
        {"token_policies": "not-a-list"},
        {"identity_policies": {}},
        {"policies": False},
    ],
)
def test_effective_policy_capability_is_rejected(change: dict[str, object]) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=login_payload(**change))

    with pytest.raises(SecretError) as caught:
        authenticator(handler).authenticate(BuildkiteOIDCJWT(JWT), context())
    assert str(caught.value) == "OpenBao issued unauthorized policy capability"
    assert JWT not in repr(caught.value)
    assert CLIENT_TOKEN not in repr(caught.value)


@pytest.mark.parametrize(
    "change",
    [
        {"token_policies": None, "identity_policies": None, "policies": None},
        {},
    ],
)
def test_null_or_omitted_empty_policy_fields_are_accepted(
    change: dict[str, object],
) -> None:
    payload = login_payload(**change)
    if not change:
        auth = payload["auth"]
        assert isinstance(auth, dict)
        auth.pop("token_policies")
        auth.pop("identity_policies")
        auth.pop("policies")

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    result = authenticator(handler).authenticate(BuildkiteOIDCJWT(JWT), context())
    assert result.identity_metadata == metadata()


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


def test_diagnostic_prints_selected_claims_exact_comparisons_and_no_jwt() -> None:
    jwt = diagnostic_jwt()
    output = StringIO()
    auth = authenticator(
        lambda _request: httpx.Response(
            400, json={"errors": [f"claim mismatch {jwt.value}"]}
        )
    )
    with pytest.raises(SecretError, match="diagnostic login failed"):
        auth.diagnose(jwt, context(), output)
    rendered = output.getvalue()
    for field in (
        "alg",
        "kid",
        "iss",
        "sub",
        "aud",
        "pipeline_id",
        "build_branch",
        "build_commit",
        "step_key",
        "job_id",
        "iat",
        "nbf",
        "exp",
    ):
        assert f"{field}=" in rendered
    for field in ("sub", "build_branch", "build_commit", "step_key", "job_id"):
        assert f"{field}: actual=" in rendered
        assert "match=True" in rendered
    assert "Pipeline identity source: sub" in rendered
    assert "pipeline_id=null" in rendered
    assert "pipeline_id: actual=" not in rendered
    assert "HTTP status: 400" in rendered
    assert "claim mismatch <redacted-jwt>" in rendered
    assert jwt.value not in rendered
    assert "must-not-print" not in rendered
    assert "ignored_secret_claim" not in rendered
    assert "hidden" not in rendered


def test_diagnostic_reports_wrong_subject_as_pipeline_identity_mismatch() -> None:
    jwt = diagnostic_jwt(sub="other-pipeline", pipeline_id=None)
    output = StringIO()
    auth = authenticator(
        lambda _request: httpx.Response(400, json={"errors": ["subject claim invalid"]})
    )
    with pytest.raises(SecretError, match="diagnostic login failed"):
        auth.diagnose(jwt, context(), output)
    rendered = output.getvalue()
    assert "Pipeline identity source: sub" in rendered
    assert (
        'sub: actual="other-pipeline" expected="pipeline-uuid" match=False' in rendered
    )
    assert "subject claim invalid" in rendered


@pytest.mark.parametrize("content", [b"not-json", b"[]", b'{"errors":"bad"}'])
def test_diagnostic_bounds_malformed_openbao_error_response(content: bytes) -> None:
    jwt = diagnostic_jwt()
    output = StringIO()
    auth = authenticator(lambda _request: httpx.Response(401, content=content))
    with pytest.raises(SecretError, match="diagnostic login failed"):
        auth.diagnose(jwt, context(), output)
    assert "malformed OpenBao error response" in output.getvalue()
    assert jwt.value not in output.getvalue()


def test_diagnostic_success_discards_token_and_stops() -> None:
    jwt = diagnostic_jwt()
    output = StringIO()
    auth = authenticator(lambda _request: httpx.Response(200, json=login_payload()))
    assert auth.diagnose(jwt, context(), output) is None
    assert "stopping before promotion" in output.getvalue()
    assert CLIENT_TOKEN not in output.getvalue()
    assert jwt.value not in output.getvalue()


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
