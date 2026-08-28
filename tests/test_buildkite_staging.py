from __future__ import annotations

import json

import httpx
import pytest
from pydantic import ValidationError

from network_change_delivery.buildkite_identity import BuildkiteOIDCJWT
from network_change_delivery.buildkite_staging import (
    BuildkiteStagingContext,
    BuildkiteStagingSecretProvider,
    staging_context_from_environment,
    staging_policy_name,
    staging_role_name,
    validate_staging_state_root,
)
from network_change_delivery.models import InventoryDevice
from network_change_delivery.secrets import SecretError

JWT = "header.payload.signature"
PIPELINE_ID = "01a02ab4-2472-4726-be31-dbf4f216210f"
BUILD_ID = "79c012df-23bf-49b3-a6dd-f28799c4bb24"
JOB_ID = "66051b16-7d3d-4c10-a81d-ec7bb630231d"
COMMIT = "a" * 40


def context(**changes: str) -> BuildkiteStagingContext:
    values = {
        "pipeline_id": PIPELINE_ID,
        "build_id": BUILD_ID,
        "commit": COMMIT,
        "branch": "feature/staging",
        "step_key": "cml-staging",
        "job_id": JOB_ID,
        "queue_key": "ncdp-staging",
        "retry_count": "0",
    }
    values.update(changes)
    return BuildkiteStagingContext.model_validate(values)


def device(device_id: int) -> InventoryDevice:
    return InventoryDevice(
        name="stg-core-02" if device_id == 6 else "stg-edge-junos-01",
        host="192.168.4.30" if device_id == 6 else "192.168.4.31",
        port=22 if device_id == 6 else 830,
        platform="cisco_iosxe" if device_id == 6 else "junos",
        expected_hostname="stg-core-02" if device_id == 6 else "stg-edge-junos-01",
        inventory_source="netbox",
        inventory_object_id=f"netbox:dcim.device:{device_id}",
    )


def test_buildkite_context_derives_uuid_bound_run_id() -> None:
    value = context()
    assert value.staging_run_id == f"bk-{BUILD_ID}"
    assert len(value.staging_run_id) == 39
    loaded = staging_context_from_environment(
        {
            "BUILDKITE_PIPELINE_ID": PIPELINE_ID,
            "BUILDKITE_BUILD_ID": BUILD_ID,
            "BUILDKITE_COMMIT": COMMIT,
            "BUILDKITE_BRANCH": "feature/staging",
            "BUILDKITE_STEP_KEY": "cml-staging",
            "BUILDKITE_JOB_ID": JOB_ID,
            "BUILDKITE_AGENT_META_DATA_QUEUE": "ncdp-staging",
            "BUILDKITE_RETRY_COUNT": "0",
        }
    )
    assert loaded == value


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("build_id", "not-a-uuid"),
        ("commit", "A" * 40),
        ("step_key", "deploy-gate"),
        ("queue_key", "ncdp-deploy"),
        ("retry_count", "1"),
    ],
)
def test_staging_context_rejects_wrong_job_boundary(field: str, value: str) -> None:
    with pytest.raises(ValidationError):
        context(**{field: value})


def handler(requests: list[httpx.Request]):
    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        body = json.loads(request.content) if request.content else {}
        if request.url.path == "/v1/auth/jwt/login":
            role = body["role"]
            device_id = 6 if role.endswith("-6") else 7
            policy = staging_policy_name(device_id)
            return httpx.Response(
                200,
                json={
                    "auth": {
                        "client_token": f"token-{device_id}",
                        "lease_duration": 300,
                        "token_policies": [policy],
                        "identity_policies": [],
                        "policies": [policy],
                        "metadata": {
                            "pipeline_id": PIPELINE_ID,
                            "build_id": BUILD_ID,
                            "build_commit": COMMIT,
                            "build_branch": "feature/staging",
                            "step_key": "cml-staging",
                            "job_id": JOB_ID,
                        },
                    }
                },
            )
        device_id = int(request.url.path.split("/")[5])
        assert request.headers["X-Vault-Token"] == f"token-{device_id}"
        return httpx.Response(
            200,
            json={"data": {"data": {"username": "user", "password": "secret"}}},
        )

    return respond


def test_one_jwt_authenticates_separately_to_both_exact_roles() -> None:
    requests: list[httpx.Request] = []
    provider = BuildkiteStagingSecretProvider(
        BuildkiteOIDCJWT(JWT),
        context(),
        "https://openbao.example",
        transport=httpx.MockTransport(handler(requests)),
    )
    for device_id in (6, 7):
        target = device(device_id)
        assert provider.reference(target).reference.endswith(f"/{device_id}/ssh")
        assert provider.load(target).username == "user"
    logins = [request for request in requests if request.url.path.endswith("login")]
    assert [json.loads(request.content)["role"] for request in logins] == [
        staging_role_name(6),
        staging_role_name(7),
    ]
    assert all(json.loads(request.content)["jwt"] == JWT for request in logins)


def test_staging_secret_provider_rejects_repeat_and_unknown_device() -> None:
    provider = BuildkiteStagingSecretProvider(
        BuildkiteOIDCJWT(JWT),
        context(),
        "https://openbao.example",
        transport=httpx.MockTransport(handler([])),
    )
    provider.load(device(6))
    with pytest.raises(SecretError, match="already consumed"):
        provider.load(device(6))
    with pytest.raises(SecretError, match="identity rejected"):
        provider.reference(device(1))


def test_state_root_requires_owned_private_external_directory(
    tmp_path, monkeypatch
) -> None:
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    root = tmp_path / "state"
    root.mkdir(mode=0o700)
    assert validate_staging_state_root(root, checkout) == root.resolve()
    root.chmod(0o750)
    with pytest.raises(ValueError, match="permissions"):
        validate_staging_state_root(root, checkout)
    inside = checkout / "state"
    inside.mkdir(mode=0o700)
    with pytest.raises(ValueError, match="outside checkout"):
        validate_staging_state_root(inside, checkout)
    link = tmp_path / "linked"
    link.symlink_to(inside, target_is_directory=True)
    with pytest.raises(ValueError, match="invalid"):
        validate_staging_state_root(link, checkout)
    root.chmod(0o700)
    monkeypatch.setattr(
        "network_change_delivery.buildkite_staging.os.getuid", lambda: 7
    )
    with pytest.raises(ValueError, match="owner"):
        validate_staging_state_root(root, checkout)
