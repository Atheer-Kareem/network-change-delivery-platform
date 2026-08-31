"""Buildkite workload identity boundary for ephemeral CML staging."""

from __future__ import annotations

import os
import re
import stat
from collections.abc import Mapping
from pathlib import Path
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, model_validator

from network_change_delivery.buildkite_identity import BuildkiteOIDCJWT
from network_change_delivery.secrets import (
    CredentialReference,
    DeviceCredentials,
    SecretError,
    create_openbao_client,
    netbox_device_id,
    validate_openbao_url,
)

OPENBAO_STAGING_AUDIENCE = "urn:ncdp:openbao:staging"
OPENBAO_STAGING_MAX_LEASE_SECONDS = 300
STAGING_DEVICE_IDS = frozenset({1, 2, 8, 9})


def staging_policy_name(device_id: int) -> str:
    return f"ncdp-buildkite-staging-device-{device_id}-read"


def staging_role_name(device_id: int) -> str:
    return f"ncdp-buildkite-staging-device-{device_id}"


class BuildkiteStagingContext(BaseModel):
    """Validated immutable context for exactly one serialized staging job."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    pipeline_id: str
    build_id: str
    commit: str
    branch: str
    step_key: str
    job_id: str
    queue_key: str
    retry_count: str

    @model_validator(mode="after")
    def validate_context(self) -> BuildkiteStagingContext:
        for value, label in (
            (self.pipeline_id, "pipeline"),
            (self.build_id, "build"),
            (self.job_id, "job"),
        ):
            try:
                parsed = UUID(value)
            except ValueError:
                raise ValueError(
                    f"Buildkite {label} ID must be a canonical UUID"
                ) from None
            if str(parsed) != value:
                raise ValueError(f"Buildkite {label} ID must be a canonical UUID")
        if not re.fullmatch(r"[0-9a-f]{40}", self.commit):
            raise ValueError("Buildkite commit must be a lowercase SHA-1")
        if (
            not self.branch
            or len(self.branch) > 255
            or any(character in "\r\n\x00" for character in self.branch)
        ):
            raise ValueError("Buildkite branch is invalid")
        if self.step_key != "cml-staging" or self.queue_key != "ncdp-staging":
            raise ValueError("Buildkite staging step or queue is invalid")
        if self.retry_count != "0":
            raise ValueError("retried Buildkite staging job is not authorized")
        return self

    @property
    def staging_run_id(self) -> str:
        return f"bk-{self.build_id}"


def staging_context_from_environment(
    environment: Mapping[str, str] | None = None,
) -> BuildkiteStagingContext:
    values = environment if environment is not None else os.environ
    return BuildkiteStagingContext(
        pipeline_id=values.get("BUILDKITE_PIPELINE_ID", ""),
        build_id=values.get("BUILDKITE_BUILD_ID", ""),
        commit=values.get("BUILDKITE_COMMIT", ""),
        branch=values.get("BUILDKITE_BRANCH", ""),
        step_key=values.get("BUILDKITE_STEP_KEY", ""),
        job_id=values.get("BUILDKITE_JOB_ID", ""),
        queue_key=values.get("BUILDKITE_AGENT_META_DATA_QUEUE", ""),
        retry_count=values.get("BUILDKITE_RETRY_COUNT", "0"),
    )


def validate_staging_state_root(
    root: Path,
    checkout: Path,
    *,
    owner_uid: int | None = None,
) -> Path:
    """Validate an agent-owned persistent root outside the repository checkout."""
    if not root.is_absolute() or root.is_symlink() or not root.is_dir():
        raise ValueError("Buildkite staging state root is invalid")
    root_resolved = root.resolve(strict=True)
    checkout_resolved = checkout.resolve(strict=True)
    if root_resolved == checkout_resolved or root_resolved.is_relative_to(
        checkout_resolved
    ):
        raise ValueError("Buildkite staging state root must be outside checkout")
    metadata = root.stat(follow_symlinks=False)
    expected_uid = os.getuid() if owner_uid is None else owner_uid
    if metadata.st_uid != expected_uid:
        raise ValueError("Buildkite staging state root owner is invalid")
    mode = stat.S_IMODE(metadata.st_mode)
    if mode & 0o077 or (mode & 0o700) != 0o700:
        raise ValueError("Buildkite staging state root permissions are invalid")
    return root_resolved


class BuildkiteStagingSecretProvider:
    """Reuse one JWT for exact one-use, device-scoped OpenBao logins."""

    _LOGIN_PATH = "/v1/auth/jwt/login"

    def __init__(
        self,
        jwt: BuildkiteOIDCJWT,
        context: BuildkiteStagingContext,
        url: str | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        configured_url = os.environ.get("NCDP_OPENBAO_URL") if url is None else url
        if not configured_url:
            raise SecretError("OpenBao configuration missing")
        self._jwt = jwt
        self._context = context
        self._client = create_openbao_client(
            validate_openbao_url(configured_url), transport=transport
        )
        self._loaded: set[int] = set()

    @staticmethod
    def reference(device) -> CredentialReference:
        device_id = netbox_device_id(device)
        if device_id not in STAGING_DEVICE_IDS:
            raise SecretError("Buildkite staging device identity rejected")
        return CredentialReference(
            "openbao", f"openbao:kv-v2:ncdp/devices/{device_id}/ssh"
        )

    def load(self, device) -> DeviceCredentials:
        device_id = netbox_device_id(device)
        self.reference(device)
        if device_id in self._loaded:
            raise SecretError("Buildkite staging credential already consumed")
        self._loaded.add(device_id)
        try:
            response = self._client.post(
                self._LOGIN_PATH,
                json={
                    "role": staging_role_name(device_id),
                    "jwt": self._jwt.value,
                },
            )
        except (httpx.TimeoutException, httpx.RequestError):
            raise SecretError("OpenBao unavailable or timed out") from None
        if response.status_code in {400, 401, 403}:
            raise SecretError("OpenBao JWT authentication failed")
        if response.status_code != 200:
            raise SecretError(
                f"OpenBao returned unexpected HTTP status {response.status_code}"
            )
        auth = self._auth(response)
        policy = staging_policy_name(device_id)
        token = auth.get("client_token")
        lease = auth.get("lease_duration")
        if (
            not isinstance(token, str)
            or not token
            or not isinstance(lease, int)
            or isinstance(lease, bool)
            or lease <= 0
            or lease > OPENBAO_STAGING_MAX_LEASE_SECONDS
        ):
            raise SecretError("OpenBao issued unacceptable token")
        if auth.get("token_policies") != [policy] or auth.get("policies") != [policy]:
            raise SecretError("OpenBao issued unauthorized policy capability")
        if auth.get("identity_policies") not in (None, []):
            raise SecretError("OpenBao issued unauthorized policy capability")
        self._verify_identity(auth.get("metadata"))
        return self._read(device_id, token)

    @staticmethod
    def _auth(response: httpx.Response) -> dict[str, object]:
        try:
            payload = response.json()
        except ValueError:
            raise SecretError("OpenBao returned invalid JSON or schema") from None
        auth = payload.get("auth") if isinstance(payload, dict) else None
        if not isinstance(auth, dict):
            raise SecretError("OpenBao returned invalid JSON or schema")
        return auth

    def _verify_identity(self, metadata: object) -> None:
        if not isinstance(metadata, dict):
            raise SecretError("OpenBao returned invalid identity metadata")
        expected = {
            "pipeline_id": self._context.pipeline_id,
            "build_id": self._context.build_id,
            "build_commit": self._context.commit,
            "build_branch": self._context.branch,
            "step_key": self._context.step_key,
            "job_id": self._context.job_id,
        }
        for claim, value in expected.items():
            if metadata.get(claim) != value:
                raise SecretError(f"OpenBao Buildkite identity mismatch: {claim}")

    def _read(self, device_id: int, token: str) -> DeviceCredentials:
        try:
            response = self._client.get(
                f"/v1/ncdp/data/devices/{device_id}/ssh",
                headers={"X-Vault-Token": token},
            )
        except (httpx.TimeoutException, httpx.RequestError):
            raise SecretError("OpenBao unavailable or timed out") from None
        if response.status_code in {403, 404}:
            raise SecretError("OpenBao staging secret read rejected")
        if response.status_code != 200:
            raise SecretError(
                f"OpenBao returned unexpected HTTP status {response.status_code}"
            )
        try:
            payload = response.json()
        except ValueError:
            raise SecretError("OpenBao returned invalid JSON or schema") from None
        outer = payload.get("data") if isinstance(payload, dict) else None
        values = outer.get("data") if isinstance(outer, dict) else None
        if not isinstance(values, dict) or set(values) != {"username", "password"}:
            raise SecretError("OpenBao credential payload invalid")
        username = values.get("username")
        password = values.get("password")
        if not isinstance(username, str) or not username:
            raise SecretError("OpenBao credential payload invalid")
        if not isinstance(password, str) or not password:
            raise SecretError("OpenBao credential payload invalid")
        return DeviceCredentials(username=username, password=password)
