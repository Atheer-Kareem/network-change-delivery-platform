"""Protected Buildkite single-device deployment boundaries."""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Literal

import httpx
import yaml
from pydantic import BaseModel, ConfigDict, model_validator

from network_change_delivery.buildkite_identity import (
    OPENBAO_BUILDKITE_MAX_LEASE_SECONDS,
    BuildkiteOIDCJWT,
)
from network_change_delivery.buildkite_policy import BuildkiteDeploymentContext
from network_change_delivery.models import DeploymentPlan
from network_change_delivery.promotion import (
    DeploymentPromotionManifest,
    PromotionError,
    verify_promotion_bundle,
)
from network_change_delivery.secrets import (
    CredentialReference,
    DeviceCredentials,
    SecretError,
    create_openbao_client,
    netbox_device_id,
    validate_openbao_url,
)
from network_change_delivery.snmp_provisioning import SnmpProvisioningPlan

LIVE_DEPLOYMENT_REQUEST = Path("deployments/live/request.yaml")
MAX_LIVE_DEPLOYMENT_REQUEST_BYTES = 16 * 1024
_IDENTITY_FIELDS = {
    "pipeline_id": "pipeline_id",
    "build_commit": "commit",
    "build_branch": "branch",
    "step_key": "step_key",
    "job_id": "job_id",
}


def cml_deploy_role_name(device_id: int) -> str:
    return f"ncdp-buildkite-cml-deploy-device-{device_id}"


def cml_device_policy_name(device_id: int) -> str:
    return f"ncdp-buildkite-cml-device-{device_id}-read"


def live_deployment_request_changed(
    commit: str,
    *,
    root: Path = Path(),
    request_path: Path = LIVE_DEPLOYMENT_REQUEST,
) -> bool:
    """Return whether the exact commit changes and contains a regular request blob."""
    return (
        _live_deployment_request_blob(commit, root=root, request_path=request_path)
        is not None
    )


def _run_git(
    arguments: list[str], *, root: Path, capture_output: bool = False
) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            ["git", *arguments],
            cwd=root,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE if capture_output else subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except OSError as error:
        raise PromotionError(
            "unable to verify committed live deployment request"
        ) from error


def _live_deployment_request_blob(
    commit: str,
    *,
    root: Path = Path(),
    request_path: Path = LIVE_DEPLOYMENT_REQUEST,
) -> bytes | None:
    if re.fullmatch(r"[0-9a-f]{40}", commit) is None:
        raise PromotionError("Buildkite live request commit rejected")
    changed = _run_git(
        [
            "diff",
            "--quiet",
            f"{commit}^",
            commit,
            "--",
            request_path.as_posix(),
        ],
        root=root,
    )
    if changed.returncode == 0:
        return None
    if changed.returncode != 1:
        raise PromotionError("unable to verify committed live deployment request")

    tree = _run_git(
        ["ls-tree", "-z", commit, "--", request_path.as_posix()],
        root=root,
        capture_output=True,
    )
    if tree.returncode != 0:
        raise PromotionError("unable to verify committed live deployment request")
    if not tree.stdout:
        return None
    entries = tree.stdout.removesuffix(b"\0").split(b"\0")
    if len(entries) != 1:
        raise PromotionError("committed live deployment request is not a regular blob")
    try:
        metadata, stored_path = entries[0].split(b"\t", 1)
        mode, object_type, object_id = metadata.split(b" ", 2)
    except ValueError:
        raise PromotionError("committed live deployment request is invalid") from None
    if (
        mode not in {b"100644", b"100755"}
        or object_type != b"blob"
        or stored_path != request_path.as_posix().encode("utf-8")
        or re.fullmatch(rb"[0-9a-f]{40,64}", object_id) is None
    ):
        raise PromotionError("committed live deployment request is not a regular blob")

    size = _run_git(
        ["cat-file", "-s", object_id.decode("ascii")],
        root=root,
        capture_output=True,
    )
    try:
        byte_count = int(size.stdout.strip())
    except ValueError:
        raise PromotionError("committed live deployment request is invalid") from None
    if (
        size.returncode != 0
        or byte_count < 0
        or byte_count > MAX_LIVE_DEPLOYMENT_REQUEST_BYTES
    ):
        raise PromotionError("committed live deployment request size rejected")
    blob = _run_git(
        ["cat-file", "blob", object_id.decode("ascii")],
        root=root,
        capture_output=True,
    )
    if blob.returncode != 0 or len(blob.stdout) != byte_count:
        raise PromotionError("committed live deployment request is invalid")
    return blob.stdout


class LiveDeploymentRequest(BaseModel):
    """Strict commit-owned authorization request for one promoted plan."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal["1"]
    action: Literal["deploy"]
    change_id: str
    plan_digest: str
    inventory_object_id: str

    @model_validator(mode="after")
    def validate_bounded_values(self) -> LiveDeploymentRequest:
        if not self.change_id or len(self.change_id) > 128:
            raise ValueError("live deployment request rejected")
        if not self.plan_digest.startswith("sha256:") or len(self.plan_digest) != 71:
            raise ValueError("live deployment request rejected")
        if any(
            character not in "0123456789abcdef" for character in self.plan_digest[7:]
        ):
            raise ValueError("live deployment request rejected")
        if (
            re.fullmatch(r"netbox:dcim\.device:[1-9][0-9]*", self.inventory_object_id)
            is None
        ):
            raise ValueError("live deployment request rejected")
        return self

    def verify_plan(self, plan: DeploymentPlan | SnmpProvisioningPlan) -> None:
        if (
            self.change_id != plan.change_id
            or self.plan_digest != plan.digest
            or self.inventory_object_id != plan.inventory_object_id
        ):
            raise PromotionError("live deployment request does not match promotion")


def load_live_deployment_request(
    path: Path = LIVE_DEPLOYMENT_REQUEST,
) -> LiveDeploymentRequest:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        return LiveDeploymentRequest.model_validate(payload)
    except (OSError, yaml.YAMLError, ValueError) as error:
        raise PromotionError("live deployment request is invalid") from error


def load_live_deployment_request_at_commit(
    commit: str,
    *,
    root: Path = Path(),
    request_path: Path = LIVE_DEPLOYMENT_REQUEST,
) -> LiveDeploymentRequest | None:
    """Load only the bounded request blob stored by the exact changed commit."""
    blob = _live_deployment_request_blob(commit, root=root, request_path=request_path)
    if blob is None:
        return None
    try:
        payload = yaml.safe_load(blob.decode("utf-8"))
        return LiveDeploymentRequest.model_validate(payload)
    except (UnicodeDecodeError, yaml.YAMLError, ValueError) as error:
        raise PromotionError("committed live deployment request is invalid") from error


def load_promoted_single_plan(
    promotion: Path, commit: str
) -> tuple[DeploymentPromotionManifest, DeploymentPlan | SnmpProvisioningPlan]:
    manifest = verify_promotion_bundle(promotion, commit)
    try:
        payload = json.loads((promotion / "plan.json").read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or "members" in payload:
            raise ValueError
        plan = (
            SnmpProvisioningPlan.model_validate(payload)
            if payload.get("plan_type") == "snmp_provisioning_plan"
            else DeploymentPlan.model_validate(payload)
        )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise PromotionError("live deployment requires one DeploymentPlan") from error
    if not plan.verify_digest() or plan.digest != manifest.plan_digest:
        raise PromotionError("promoted plan digest does not match manifest")
    if plan.inventory_source != "netbox" or plan.inventory_object_id is None:
        raise PromotionError("live deployment plan provenance rejected")
    expected_reference = f"openbao:kv-v2:ncdp/devices/{_plan_device_id(plan)}/ssh"
    if isinstance(plan, SnmpProvisioningPlan):
        if plan.connection_credential_reference != expected_reference:
            raise PromotionError("live deployment plan provenance rejected")
    elif (
        plan.credential_source != "openbao"
        or plan.credential_reference != expected_reference
    ):
        raise PromotionError("live deployment plan provenance rejected")
    return manifest, plan


def _plan_device_id(plan: DeploymentPlan | SnmpProvisioningPlan) -> int:
    value = plan.inventory_object_id or ""
    prefix = "netbox:dcim.device:"
    suffix = value.removeprefix(prefix)
    if value != prefix + suffix or not suffix.isdigit() or int(suffix) <= 0:
        raise PromotionError("live deployment plan provenance rejected")
    return int(suffix)


class BuildkiteOpenBaoDeploymentSecretProvider:
    """One-JWT, one-login, one-device, one-secret-read provider."""

    _LOGIN_PATH = "/v1/auth/jwt/login"

    def __init__(
        self,
        jwt: BuildkiteOIDCJWT,
        context: BuildkiteDeploymentContext,
        url: str | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        configured_url = os.environ.get("NCDP_OPENBAO_URL") if url is None else url
        if not configured_url:
            raise SecretError("OpenBao configuration missing")
        self._jwt: BuildkiteOIDCJWT | None = jwt
        self._context = context
        self._client = create_openbao_client(
            validate_openbao_url(configured_url), transport=transport
        )
        self._loaded = False
        self._device_id: int | None = None

    def reference(self, device) -> CredentialReference:
        device_id = netbox_device_id(device)
        if self._device_id not in (None, device_id):
            raise SecretError("Buildkite OpenBao device identity changed")
        self._device_id = device_id
        return CredentialReference(
            "openbao", f"openbao:kv-v2:ncdp/devices/{device_id}/ssh"
        )

    def load(self, device) -> DeviceCredentials:
        if self._loaded:
            raise SecretError("Buildkite OpenBao credential already consumed")
        self._loaded = True
        jwt = self._jwt
        self._jwt = None
        if jwt is None:
            raise SecretError("Buildkite OpenBao credential already consumed")
        device_id = netbox_device_id(device)
        if self._device_id not in (None, device_id):
            raise SecretError("Buildkite OpenBao device identity changed")
        self._device_id = device_id
        policy = cml_device_policy_name(device_id)
        try:
            response = self._client.post(
                self._LOGIN_PATH,
                json={"role": cml_deploy_role_name(device_id), "jwt": jwt.value},
            )
        except (httpx.TimeoutException, httpx.RequestError):
            raise SecretError("OpenBao unavailable or timed out") from None
        if response.status_code in {400, 401, 403}:
            raise SecretError("OpenBao JWT authentication failed")
        if response.status_code != 200:
            raise SecretError(
                f"OpenBao returned unexpected HTTP status {response.status_code}"
            )
        auth = self._auth_payload(response)
        token = auth.get("client_token")
        lease = auth.get("lease_duration")
        if not isinstance(token, str) or not token or not _valid_lease(lease):
            raise SecretError("OpenBao issued unacceptable token")
        if auth.get("token_policies") != [policy] or auth.get("policies") != [policy]:
            raise SecretError("OpenBao issued unauthorized policy capability")
        if auth.get("identity_policies") not in (None, []):
            raise SecretError("OpenBao issued unauthorized policy capability")
        for field in ("external_namespace_policies", "external_namespace_policy_paths"):
            if auth.get(field) not in (None, [], {}):
                raise SecretError("OpenBao issued unauthorized policy capability")
        self._verify_identity(auth.get("metadata"))
        return self._read_credentials(device_id, token)

    @staticmethod
    def _auth_payload(response: httpx.Response) -> dict[str, object]:
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
        for claim, context_field in _IDENTITY_FIELDS.items():
            value = metadata.get(claim)
            if not isinstance(value, str) or not value:
                raise SecretError("OpenBao returned invalid identity metadata")
            if value != getattr(self._context, context_field):
                raise SecretError(f"OpenBao Buildkite identity mismatch: {claim}")

    def _read_credentials(self, device_id: int, token: str) -> DeviceCredentials:
        try:
            response = self._client.get(
                f"/v1/ncdp/data/devices/{device_id}/ssh",
                headers={"X-Vault-Token": token},
            )
        except (httpx.TimeoutException, httpx.RequestError):
            raise SecretError("OpenBao unavailable or timed out") from None
        if response.status_code == 403:
            raise SecretError("OpenBao secret read unauthorized")
        if response.status_code == 404:
            raise SecretError("OpenBao secret not found")
        if response.status_code != 200:
            raise SecretError(
                f"OpenBao returned unexpected HTTP status {response.status_code}"
            )
        try:
            payload = response.json()
        except ValueError:
            raise SecretError("OpenBao returned invalid JSON or schema") from None
        outer = payload.get("data") if isinstance(payload, dict) else None
        credentials = outer.get("data") if isinstance(outer, dict) else None
        if not isinstance(credentials, dict) or set(credentials) != {
            "username",
            "password",
        }:
            raise SecretError("OpenBao credential payload invalid")
        username = credentials.get("username")
        password = credentials.get("password")
        if not isinstance(username, str) or not username:
            raise SecretError("OpenBao credential payload invalid")
        if not isinstance(password, str) or not password:
            raise SecretError("OpenBao credential payload invalid")
        return DeviceCredentials(username, password)


def _valid_lease(value: object) -> bool:
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and 0 < value <= OPENBAO_BUILDKITE_MAX_LEASE_SECONDS
    )
