"""Secret-safe Buildkite JWT authentication through OpenBao."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import TextIO

import httpx

from network_change_delivery.buildkite_policy import BuildkiteDeploymentContext
from network_change_delivery.secrets import (
    SecretError,
    create_openbao_client,
    validate_openbao_url,
)

BUILDKITE_OIDC_ISSUER = "https://agent.buildkite.com"
BUILDKITE_OIDC_SUBJECT_CLAIM = "pipeline_id"
BUILDKITE_OIDC_TOKEN_LIFETIME_SECONDS = 300
OPENBAO_BUILDKITE_JWT_ROLE = "ncdp-buildkite-deploy"
OPENBAO_BUILDKITE_JWT_AUDIENCE = "urn:ncdp:openbao:deploy"
OPENBAO_BUILDKITE_MAX_LEASE_SECONDS = 300
BUILDKITE_JWT_MAX_INPUT_BYTES = 8192

_JWT_TRANSPORT = re.compile(r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")
_IDENTITY_FIELDS = {
    "pipeline_id": "pipeline_id",
    "build_commit": "commit",
    "build_branch": "branch",
    "step_key": "step_key",
    "job_id": "job_id",
}


@dataclass(frozen=True, repr=False)
class BuildkiteOIDCJWT:
    """One ephemeral Buildkite bearer JWT with a secret-safe representation."""

    value: str

    def __repr__(self) -> str:
        return "BuildkiteOIDCJWT(<redacted>)"


@dataclass(frozen=True, repr=False)
class OpenBaoJWTAuthentication:
    """Ephemeral OpenBao capability bound to verified Buildkite metadata."""

    client_token: str
    lease_duration: int
    identity_metadata: dict[str, str]

    def __repr__(self) -> str:
        return (
            "OpenBaoJWTAuthentication(lease_duration="
            f"{self.lease_duration}, identity_metadata={self.identity_metadata!r}, "
            "client_token=<redacted>)"
        )


def read_buildkite_oidc_jwt(stream: TextIO) -> BuildkiteOIDCJWT:
    """Read exactly one bounded compact JWT from a secret-bearing stream."""
    value = stream.read(BUILDKITE_JWT_MAX_INPUT_BYTES + 2)
    if len(value.encode("utf-8")) > BUILDKITE_JWT_MAX_INPUT_BYTES + 1:
        raise SecretError("Buildkite OIDC JWT input rejected")
    if value.endswith("\n"):
        value = value[:-1]
    if (
        not value
        or "\n" in value
        or "\r" in value
        or not _JWT_TRANSPORT.fullmatch(value)
    ):
        raise SecretError("Buildkite OIDC JWT input rejected")
    if len(value.encode("utf-8")) > BUILDKITE_JWT_MAX_INPUT_BYTES:
        raise SecretError("Buildkite OIDC JWT input rejected")
    return BuildkiteOIDCJWT(value)


class OpenBaoBuildkiteJWTAuthenticator:
    """Authenticate a Buildkite JWT and bind OpenBao metadata to the current job."""

    _LOGIN_PATH = "/v1/auth/jwt/login"

    def __init__(
        self,
        url: str | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        configured_url = os.environ.get("NCDP_OPENBAO_URL") if url is None else url
        if not configured_url:
            raise SecretError("OpenBao configuration missing")
        self._client = create_openbao_client(
            validate_openbao_url(configured_url), transport=transport
        )

    def authenticate(
        self,
        jwt: BuildkiteOIDCJWT,
        context: BuildkiteDeploymentContext,
    ) -> OpenBaoJWTAuthentication:
        """Exchange one JWT, then verify the returned cryptographic identity binding."""
        try:
            response = self._client.post(
                self._LOGIN_PATH,
                json={"role": OPENBAO_BUILDKITE_JWT_ROLE, "jwt": jwt.value},
            )
        except (httpx.TimeoutException, httpx.RequestError):
            raise SecretError("OpenBao unavailable or timed out") from None
        if response.status_code in {400, 401, 403}:
            raise SecretError("OpenBao JWT authentication failed")
        if response.status_code != 200:
            raise SecretError(
                f"OpenBao returned unexpected HTTP status {response.status_code}"
            )
        try:
            payload = response.json()
        except ValueError:
            raise SecretError("OpenBao returned invalid JSON or schema") from None
        if not isinstance(payload, dict):
            raise SecretError("OpenBao returned invalid JSON or schema")
        auth = payload.get("auth")
        if not isinstance(auth, dict):
            raise SecretError("OpenBao returned invalid JSON or schema")
        token = auth.get("client_token")
        lease = auth.get("lease_duration")
        if not isinstance(token, str) or not token:
            raise SecretError("OpenBao issued unacceptable token")
        if (
            not isinstance(lease, int)
            or isinstance(lease, bool)
            or lease <= 0
            or lease > OPENBAO_BUILDKITE_MAX_LEASE_SECONDS
        ):
            raise SecretError("OpenBao issued unacceptable token")
        metadata = auth.get("metadata")
        if not isinstance(metadata, dict):
            raise SecretError("OpenBao returned invalid identity metadata")
        identity: dict[str, str] = {}
        for claim, context_field in _IDENTITY_FIELDS.items():
            value = metadata.get(claim)
            if not isinstance(value, str) or not value:
                raise SecretError("OpenBao returned invalid identity metadata")
            if value != getattr(context, context_field):
                raise SecretError(f"OpenBao Buildkite identity mismatch: {claim}")
            identity[claim] = value
        return OpenBaoJWTAuthentication(token, lease, identity)
