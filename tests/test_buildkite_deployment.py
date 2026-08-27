"""Buildkite one-device live-deployment boundary tests."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from network_change_delivery.buildkite_deployment import (
    LIVE_DEPLOYMENT_REQUEST,
    MAX_LIVE_DEPLOYMENT_REQUEST_BYTES,
    BuildkiteOpenBaoDeploymentSecretProvider,
    LiveDeploymentRequest,
    cml_deploy_role_name,
    cml_device_policy_name,
    load_live_deployment_request,
    load_live_deployment_request_at_commit,
)
from network_change_delivery.buildkite_identity import BuildkiteOIDCJWT
from network_change_delivery.buildkite_policy import BuildkiteDeploymentContext
from network_change_delivery.models import InventoryDevice
from network_change_delivery.promotion import PromotionError
from network_change_delivery.secrets import SecretError

JWT = "sensitive.header.signature"
TOKEN = "sensitive-openbao-token"
USERNAME = "sensitive-device-user"
PASSWORD = "sensitive-device-password"
REQUEST_YAML = """schema_version: "1"
action: deploy
change_id: CHG-1
plan_digest: sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
inventory_object_id: netbox:dcim.device:1
"""
requires_git = pytest.mark.skipif(shutil.which("git") is None, reason="git unavailable")


def git(root: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def git_repository(root: Path) -> str:
    git(root, "init", "-q")
    git(root, "config", "user.email", "tests@example.invalid")
    git(root, "config", "user.name", "Tests")
    (root / "README").write_text("base\n", encoding="utf-8")
    git(root, "add", "README")
    git(root, "commit", "-qm", "base")
    return git(root, "rev-parse", "HEAD")


def commit_request(root: Path, contents: str = REQUEST_YAML) -> str:
    path = root / LIVE_DEPLOYMENT_REQUEST
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents, encoding="utf-8")
    git(root, "add", LIVE_DEPLOYMENT_REQUEST.as_posix())
    git(root, "commit", "-qm", "request")
    return git(root, "rev-parse", "HEAD")


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


def device(**changes: object) -> InventoryDevice:
    values: dict[str, object] = {
        "name": "core-02",
        "host": "192.0.2.10",
        "platform": "cisco_iosxe",
        "expected_hostname": "core-02",
        "inventory_source": "netbox",
        "inventory_object_id": "netbox:dcim.device:1",
        "inventory_interface_object_id": "netbox:dcim.interface:2",
    }
    values.update(changes)
    return InventoryDevice.model_validate(values)


def auth_payload(**changes: object) -> dict[str, object]:
    policy = cml_device_policy_name(1)
    auth: dict[str, object] = {
        "client_token": TOKEN,
        "lease_duration": 300,
        "token_policies": [policy],
        "identity_policies": [],
        "policies": [policy],
        "metadata": {
            "pipeline_id": "pipeline-uuid",
            "build_commit": "a" * 40,
            "build_branch": "main",
            "step_key": "deploy-gate",
            "job_id": "job-uuid",
        },
    }
    auth.update(changes)
    return {"auth": auth}


def secret_payload(**changes: object) -> dict[str, object]:
    credentials: dict[str, object] = {"username": USERNAME, "password": PASSWORD}
    credentials.update(changes)
    return {"data": {"data": credentials, "metadata": {"version": 1}}}


def provider(handler) -> BuildkiteOpenBaoDeploymentSecretProvider:
    return BuildkiteOpenBaoDeploymentSecretProvider(
        BuildkiteOIDCJWT(JWT),
        context(),
        "https://openbao.example",
        transport=httpx.MockTransport(handler),
    )


def test_exact_role_login_policy_identity_and_one_kv_get() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/v1/auth/jwt/login":
            return httpx.Response(200, json=auth_payload())
        return httpx.Response(200, json=secret_payload())

    source = provider(handler)
    assert source.reference(device()).reference == ("openbao:kv-v2:ncdp/devices/1/ssh")
    credentials = source.load(device())
    assert credentials.username == USERNAME
    assert credentials.password == PASSWORD
    assert [request.method for request in requests] == ["POST", "GET"]
    assert json.loads(requests[0].content) == {
        "role": cml_deploy_role_name(1),
        "jwt": JWT,
    }
    assert requests[1].url.path == "/v1/ncdp/data/devices/1/ssh"
    assert requests[1].headers["X-Vault-Token"] == TOKEN
    assert "X-Vault-Token" not in requests[0].headers


def test_second_load_is_rejected_without_another_request() -> None:
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        if request.url.path == "/v1/auth/jwt/login":
            return httpx.Response(200, json=auth_payload())
        return httpx.Response(200, json=secret_payload())

    source = provider(handler)
    source.load(device())
    with pytest.raises(SecretError, match="already consumed"):
        source.load(device())
    assert requests == ["/v1/auth/jwt/login", "/v1/ncdp/data/devices/1/ssh"]


def test_reference_binds_load_to_the_same_stable_device_identity() -> None:
    source = provider(lambda _request: pytest.fail("OpenBao must not be contacted"))
    source.reference(device())
    with pytest.raises(SecretError, match="device identity changed"):
        source.load(
            device(
                inventory_object_id="netbox:dcim.device:2",
                inventory_interface_object_id="netbox:dcim.interface:3",
            )
        )


@pytest.mark.parametrize(
    "change",
    [
        {"lease_duration": 301},
        {"token_policies": []},
        {"token_policies": ["default"]},
        {"identity_policies": ["identity"]},
        {"policies": []},
        {"policies": [cml_device_policy_name(1), "other"]},
        {"external_namespace_policies": {"root": ["other"]}},
        {"external_namespace_policy_paths": ["other"]},
    ],
)
def test_lease_and_exact_policy_results_fail_closed(change: dict[str, object]) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=auth_payload(**change))

    with pytest.raises(SecretError):
        provider(handler).load(device())


@pytest.mark.parametrize(
    ("claim", "context_field"),
    [
        ("pipeline_id", "pipeline_id"),
        ("build_commit", "commit"),
        ("build_branch", "branch"),
        ("step_key", "step_key"),
        ("job_id", "job_id"),
    ],
)
def test_each_mapped_identity_field_is_exact(claim: str, context_field: str) -> None:
    del context_field
    metadata = auth_payload()["auth"]["metadata"]
    assert isinstance(metadata, dict)
    metadata[claim] = "wrong"

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=auth_payload(metadata=metadata))

    with pytest.raises(SecretError, match=f"identity mismatch: {claim}"):
        provider(handler).load(device())


def test_secret_values_never_enter_errors_or_representations() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, content=(JWT + TOKEN + PASSWORD).encode())

    source = provider(handler)
    with pytest.raises(SecretError) as caught:
        source.load(device())
    rendered = repr(source) + repr(caught.value)
    for secret in (JWT, TOKEN, USERNAME, PASSWORD):
        assert secret not in rendered


@pytest.mark.parametrize(
    "payload",
    [
        {"data": {}},
        {"data": {"data": {"username": USERNAME}}},
        {"data": {"data": {"username": "", "password": PASSWORD}}},
        {"data": {"data": {"username": USERNAME, "password": ""}}},
        {
            "data": {
                "data": {
                    "username": USERNAME,
                    "password": PASSWORD,
                    "extra": "rejected",
                }
            }
        },
    ],
)
def test_credential_payload_requires_exact_nonempty_pair(payload: object) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if request.url.path == "/v1/auth/jwt/login":
            return httpx.Response(200, json=auth_payload())
        return httpx.Response(200, json=payload)

    with pytest.raises(SecretError, match="credential payload invalid"):
        provider(handler).load(device())
    assert calls == 2


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"schema_version": "1", "action": "read"},
        {
            "schema_version": "1",
            "action": "deploy",
            "change_id": "CHG-1",
            "plan_digest": "sha256:" + "a" * 64,
            "inventory_object_id": "netbox:dcim.device:1",
            "extra": "rejected",
        },
    ],
)
def test_live_request_schema_is_strict(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        LiveDeploymentRequest.model_validate(payload)


def test_live_request_file_load_and_exact_plan_binding(tmp_path: Path) -> None:
    request_path = tmp_path / "request.yaml"
    request_path.write_text(
        """schema_version: "1"
action: deploy
change_id: CHG-1
plan_digest: sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
inventory_object_id: netbox:dcim.device:1
""",
        encoding="utf-8",
    )
    request = load_live_deployment_request(request_path)

    class Plan:
        change_id = "CHG-1"
        digest = "sha256:" + "a" * 64
        inventory_object_id = "netbox:dcim.device:1"

    request.verify_plan(Plan())  # type: ignore[arg-type]
    for field, wrong in (
        ("change_id", "CHG-2"),
        ("plan_digest", "sha256:" + "b" * 64),
        ("inventory_object_id", "netbox:dcim.device:2"),
    ):
        changed = request.model_copy(update={field: wrong})
        with pytest.raises(PromotionError, match="does not match"):
            changed.verify_plan(Plan())  # type: ignore[arg-type]


@requires_git
def test_committed_request_added_or_changed_is_loaded_from_commit_object(
    tmp_path: Path,
) -> None:
    git_repository(tmp_path)
    commit = commit_request(tmp_path)
    path = tmp_path / LIVE_DEPLOYMENT_REQUEST
    path.write_text(REQUEST_YAML.replace("CHG-1", "WORKTREE"), encoding="utf-8")
    request = load_live_deployment_request_at_commit(commit, root=tmp_path)
    assert request is not None
    assert request.change_id == "CHG-1"

    path.write_text(REQUEST_YAML.replace("CHG-1", "CHG-2"), encoding="utf-8")
    git(tmp_path, "add", LIVE_DEPLOYMENT_REQUEST.as_posix())
    git(tmp_path, "commit", "-qm", "change request")
    changed_commit = git(tmp_path, "rev-parse", "HEAD")
    path.write_text(REQUEST_YAML.replace("CHG-1", "WORKTREE"), encoding="utf-8")
    changed = load_live_deployment_request_at_commit(changed_commit, root=tmp_path)
    assert changed is not None
    assert changed.change_id == "CHG-2"


@requires_git
def test_comment_only_retry_authorization_changes_blob_not_request(
    tmp_path: Path,
) -> None:
    git_repository(tmp_path)
    original_commit = commit_request(tmp_path)
    original = load_live_deployment_request_at_commit(original_commit, root=tmp_path)
    assert original is not None
    original_blob = git(
        tmp_path, "rev-parse", f"{original_commit}:{LIVE_DEPLOYMENT_REQUEST.as_posix()}"
    )

    path = tmp_path / LIVE_DEPLOYMENT_REQUEST
    path.write_text("# retry-authorization: 1\n" + REQUEST_YAML, encoding="utf-8")
    git(tmp_path, "add", LIVE_DEPLOYMENT_REQUEST.as_posix())
    git(tmp_path, "commit", "-qm", "authorize first retry")
    first_retry_commit = git(tmp_path, "rev-parse", "HEAD")
    first_retry = load_live_deployment_request_at_commit(
        first_retry_commit, root=tmp_path
    )
    first_retry_blob = git(
        tmp_path,
        "rev-parse",
        f"{first_retry_commit}:{LIVE_DEPLOYMENT_REQUEST.as_posix()}",
    )

    path.write_text("# retry-authorization: 2\n" + REQUEST_YAML, encoding="utf-8")
    git(tmp_path, "add", LIVE_DEPLOYMENT_REQUEST.as_posix())
    git(tmp_path, "commit", "-qm", "authorize second retry")
    second_retry_commit = git(tmp_path, "rev-parse", "HEAD")
    second_retry = load_live_deployment_request_at_commit(
        second_retry_commit, root=tmp_path
    )
    second_retry_blob = git(
        tmp_path,
        "rev-parse",
        f"{second_retry_commit}:{LIVE_DEPLOYMENT_REQUEST.as_posix()}",
    )

    assert first_retry == second_retry == original
    assert len({original_blob, first_retry_blob, second_retry_blob}) == 3


def test_committed_request_requires_exact_lowercase_commit() -> None:
    for commit in ("a" * 39, "A" * 40, "main"):
        with pytest.raises(PromotionError, match="commit rejected"):
            load_live_deployment_request_at_commit(commit)


@requires_git
def test_worktree_creation_cannot_authorize_absent_committed_request(
    tmp_path: Path,
) -> None:
    git_repository(tmp_path)
    (tmp_path / "README").write_text("current\n", encoding="utf-8")
    git(tmp_path, "add", "README")
    git(tmp_path, "commit", "-qm", "current")
    commit = git(tmp_path, "rev-parse", "HEAD")
    path = tmp_path / LIVE_DEPLOYMENT_REQUEST
    path.parent.mkdir(parents=True)
    path.write_text(REQUEST_YAML, encoding="utf-8")
    assert load_live_deployment_request_at_commit(commit, root=tmp_path) is None


@requires_git
def test_worktree_deletion_cannot_remove_committed_request(tmp_path: Path) -> None:
    git_repository(tmp_path)
    commit = commit_request(tmp_path)
    (tmp_path / LIVE_DEPLOYMENT_REQUEST).unlink()
    request = load_live_deployment_request_at_commit(commit, root=tmp_path)
    assert request is not None
    assert request.change_id == "CHG-1"


@requires_git
def test_unchanged_or_deleted_committed_request_is_not_eligible(tmp_path: Path) -> None:
    git_repository(tmp_path)
    commit_request(tmp_path)
    (tmp_path / "README").write_text("unrelated\n", encoding="utf-8")
    git(tmp_path, "add", "README")
    git(tmp_path, "commit", "-qm", "unrelated")
    unchanged = git(tmp_path, "rev-parse", "HEAD")
    assert load_live_deployment_request_at_commit(unchanged, root=tmp_path) is None

    (tmp_path / LIVE_DEPLOYMENT_REQUEST).unlink()
    git(tmp_path, "add", "-u")
    git(tmp_path, "commit", "-qm", "delete request")
    deleted = git(tmp_path, "rev-parse", "HEAD")
    assert load_live_deployment_request_at_commit(deleted, root=tmp_path) is None


@requires_git
def test_committed_symlink_request_is_rejected(tmp_path: Path) -> None:
    git_repository(tmp_path)
    target = tmp_path / "request-target.yaml"
    target.write_text(REQUEST_YAML, encoding="utf-8")
    path = tmp_path / LIVE_DEPLOYMENT_REQUEST
    path.parent.mkdir(parents=True)
    path.symlink_to(target)
    git(tmp_path, "add", LIVE_DEPLOYMENT_REQUEST.as_posix())
    git(tmp_path, "commit", "-qm", "symlink request")
    with pytest.raises(PromotionError, match="not a regular blob"):
        load_live_deployment_request_at_commit(
            git(tmp_path, "rev-parse", "HEAD"), root=tmp_path
        )


@pytest.mark.parametrize(
    "contents",
    ["not: [valid", "x" * (MAX_LIVE_DEPLOYMENT_REQUEST_BYTES + 1)],
)
@requires_git
def test_malformed_or_oversized_committed_request_fails_closed(
    tmp_path: Path, contents: str
) -> None:
    git_repository(tmp_path)
    commit = commit_request(tmp_path, contents)
    with pytest.raises(PromotionError, match="committed live deployment request"):
        load_live_deployment_request_at_commit(commit, root=tmp_path)
