from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from network_change_delivery.inventory import InventoryError, NetBoxInventoryProvider
from network_change_delivery.protected_staging import (
    BROWNFIELD_LAB_UUID,
    EXPECTED_TERRAFORM_ADDRESSES,
    CMLAuthority,
    CMLLabObservation,
    ProtectedCMLClient,
    ProtectedCMLCredentials,
    ProtectedStagingError,
    ProtectedStagingEvidence,
    ProtectedStagingInventoryResolver,
    ProtectedStagingManifest,
    ProtectedStagingSecretAuthority,
    ProtectedTerraformExecutor,
    StagingTargetAuthority,
    admit_cml_labs,
    parse_structural_plan,
    request_staging_oidc_jwt,
    validate_cleanup_authority,
    validate_plan,
    validate_protected_bundle,
)
from network_change_delivery.secrets import SecretError

SHA1 = "a" * 40
SHA256 = "b" * 64


def authority(role: str) -> StagingTargetAuthority:
    if role == "cisco":
        values = (
            6,
            "stg-core-02",
            "cisco-ios-xe",
            "GigabitEthernet1",
            ".30",
            1,
            "core-02",
        )
    else:
        values = (
            7,
            "stg-edge-junos-01",
            "juniper-junos",
            "fxp0",
            ".31",
            2,
            "edge-junos-01",
        )
    device_id, name, platform, interface, suffix, homolog_id, homolog_name = values
    return StagingTargetAuthority(
        device_id=device_id,
        name=name,
        environment="staging",
        status="staged",
        role_slug="ncdp-staging",
        platform_slug=platform,
        management_interface=interface,
        management_ip=f"192.168.4{suffix}",
        live_homolog_id=homolog_id,
        live_homolog_name=homolog_name,
        openbao_role=f"ncdp-buildkite-staging-device-{device_id}",
        credential_reference=f"openbao:kv-v2:ncdp/devices/{device_id}/ssh",
    )


def manifest(**changes) -> ProtectedStagingManifest:
    controller_path = "src/network_change_delivery/protected_staging_controller.py"
    values = {
        "source_commit": SHA1,
        "bundle_digest": SHA256,
        "controller_artifact_digest": SHA256,
        "file_digests": {controller_path: SHA256, "terraform/main.tf": SHA256},
        "cisco": authority("cisco"),
        "junos": authority("junos"),
        "live_deny_device_ids": (1, 2, 3),
        "live_deny_management_ips": (
            "192.168.4.14",
            "192.168.4.15",
            "192.168.4.20",
        ),
        "cml": CMLAuthority(
            controller_identity="personal-cml",
            controller_url="https://cml.example",
        ),
        "terraform_addresses": tuple(sorted(EXPECTED_TERRAFORM_ADDRESSES)),
        "lifecycle_update_address": "module.managed_pair.cml2_lifecycle.managed_pair",
    }
    values.update(changes)
    return ProtectedStagingManifest.model_validate(values)


@pytest.mark.parametrize(
    "change",
    [
        {"schema_version": 2},
        {"live_deny_device_ids": (1, 2)},
        {"live_deny_management_ips": ("192.168.4.30",)},
        {"terraform_addresses": ("cml2_lab.staging",)},
        {"source_commit": "wrong"},
        {"bundle_digest": "wrong"},
    ],
)
def test_manifest_rejects_changed_authority(change) -> None:
    with pytest.raises(ValidationError):
        manifest(**change)


def test_manifest_rejects_unknown_fields_and_wrong_staging_identity() -> None:
    payload = manifest().model_dump()
    payload["unexpected"] = True
    with pytest.raises(ValidationError):
        ProtectedStagingManifest.model_validate(payload)


@pytest.mark.parametrize(
    ("role", "field", "value"),
    [
        ("cisco", "device_id", 7),
        ("cisco", "platform_slug", "juniper-junos"),
        ("cisco", "management_ip", "192.168.4.14"),
        ("cisco", "credential_reference", "openbao:kv-v2:ncdp/devices/1/ssh"),
        ("junos", "openbao_role", "arbitrary-role"),
    ],
)
def test_manifest_rejects_changed_target_fields(role, field, value) -> None:
    payload = manifest().model_dump()
    payload[role][field] = value
    with pytest.raises(ValidationError):
        ProtectedStagingManifest.model_validate(payload)


def test_manifest_requires_exact_brownfield_denial() -> None:
    payload = manifest().model_dump()
    payload["cml"]["denied_lab_uuids"] = []
    with pytest.raises(ValidationError):
        ProtectedStagingManifest.model_validate(payload)
    payload = manifest().model_dump()
    payload["cisco"]["device_id"] = 1
    with pytest.raises(ValidationError):
        ProtectedStagingManifest.model_validate(payload)


def netbox_device(device_id: int, **changes) -> dict[str, object]:
    staging = device_id in {6, 7}
    cisco = device_id in {1, 6}
    value = {
        "id": device_id,
        "name": ("stg-" if staging else "") + ("core-02" if cisco else "edge-junos-01"),
        "status": {"value": "staged" if staging else "active"},
        "role": {"slug": "ncdp-staging" if staging else "router"},
        "platform": {"slug": "cisco-ios-xe" if cisco else "juniper-junos"},
        "primary_ip4": {"address": f"192.168.4.{30 if device_id == 6 else 31}/24"}
        if staging
        else {"address": f"192.168.4.{14 if device_id == 1 else 20}/24"},
        "tags": [],
        "custom_fields": {
            "ncdp_environment": "staging" if staging else "live",
            "ncdp_live_homolog": {"id": device_id - 5} if staging else None,
        },
    }
    value.update(changes)
    return value


def netbox_transport(overrides: dict[int, dict[str, object]] | None = None):
    overrides = overrides or {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.startswith("/api/dcim/devices/"):
            device_id = int(request.url.path.rstrip("/").split("/")[-1])
            return httpx.Response(
                200, json=overrides.get(device_id, netbox_device(device_id))
            )
        device_id = int(request.url.params["device_id"])
        return httpx.Response(
            200,
            json={
                "count": 1,
                "next": None,
                "results": [
                    {
                        "id": 9 if device_id == 6 else 10,
                        "name": "GigabitEthernet1" if device_id == 6 else "fxp0",
                    }
                ],
            },
        )

    return httpx.MockTransport(handler)


def test_protected_resolver_accepts_exact_staging_pair() -> None:
    targets = ProtectedStagingInventoryResolver(
        manifest(),
        "https://netbox.example",
        "reader",
        transport=netbox_transport(),
    ).resolve()
    assert [
        (target.device_id, target.host, target.live_homolog_id) for target in targets
    ] == [
        (6, "192.168.4.30", 1),
        (7, "192.168.4.31", 2),
    ]
    assert NetBoxInventoryProvider.resolve.__qualname__.startswith(
        "NetBoxInventoryProvider"
    )


@pytest.mark.parametrize(
    "override",
    [
        {"name": "core-02"},
        {"status": {"value": "active"}},
        {"role": {"slug": "router"}},
        {"platform": {"slug": "juniper-junos"}},
        {"primary_ip4": {"address": "192.168.4.14/24"}},
        {"tags": [{"slug": "ncdp-managed"}]},
        {"custom_fields": {"ncdp_environment": None, "ncdp_live_homolog": {"id": 1}}},
        {"custom_fields": {"ncdp_environment": "live", "ncdp_live_homolog": {"id": 1}}},
        {
            "custom_fields": {
                "ncdp_environment": "staging",
                "ncdp_live_homolog": {"id": 2},
            }
        },
        {
            "custom_fields": {
                "ncdp_environment": "staging",
                "ncdp_live_homolog": "core-02",
            }
        },
    ],
)
def test_protected_resolver_rejects_staging_drift(override) -> None:
    with pytest.raises(InventoryError):
        ProtectedStagingInventoryResolver(
            manifest(),
            "https://netbox.example",
            "reader",
            transport=netbox_transport({6: netbox_device(6, **override)}),
        ).resolve()


def test_protected_resolver_rejects_endpoint_identity_substitution() -> None:
    with pytest.raises(InventoryError, match="identity changed"):
        ProtectedStagingInventoryResolver(
            manifest(),
            "https://netbox.example",
            "reader",
            transport=netbox_transport({6: netbox_device(7)}),
        ).resolve()


def test_protected_resolver_rejects_ambiguous_interface() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.startswith("/api/dcim/devices/"):
            device_id = int(request.url.path.rstrip("/").split("/")[-1])
            return httpx.Response(200, json=netbox_device(device_id))
        return httpx.Response(
            200,
            json={"count": 2, "next": "next", "results": [{"id": 9}]},
        )

    with pytest.raises(InventoryError, match="ambiguous"):
        ProtectedStagingInventoryResolver(
            manifest(),
            "https://netbox.example",
            "reader",
            transport=httpx.MockTransport(handler),
        ).resolve()


@pytest.mark.parametrize("device_id", [1, 2, 3, 8])
def test_protected_secret_authority_denies_non_staging_ids(device_id: int) -> None:
    with pytest.raises(SecretError, match="identity rejected"):
        ProtectedStagingSecretAuthority.resolve(device_id)


def test_protected_secret_authority_accepts_only_6_and_7() -> None:
    for device_id in (6, 7):
        role, reference = ProtectedStagingSecretAuthority.resolve(device_id)
        assert role == f"ncdp-buildkite-staging-device-{device_id}"
        assert reference.reference == f"openbao:kv-v2:ncdp/devices/{device_id}/ssh"


def event(address: str, action: str, secret: str = "hidden") -> str:
    return json.dumps(
        {
            "type": "planned_change",
            "change": {
                "resource": {"addr": address},
                "action": action,
                "before": {"password": secret},
                "after": {"configuration": secret},
            },
        }
    )


def test_plan_parser_retains_only_addresses_and_actions() -> None:
    changes = parse_structural_plan([event("cml2_lab.staging", "create")])
    assert changes == {"cml2_lab.staging": "create"}
    assert "hidden" not in repr(changes)


@pytest.mark.parametrize("phase,action", [("create", "create"), ("destroy", "delete")])
def test_exact_full_graph_plan_contract(phase, action) -> None:
    validate_plan(phase, dict.fromkeys(EXPECTED_TERRAFORM_ADDRESSES, action))
    with pytest.raises(ProtectedStagingError):
        validate_plan(phase, {"cml2_lab.staging": action})
    with pytest.raises(ProtectedStagingError):
        validate_plan(
            phase,
            {**dict.fromkeys(EXPECTED_TERRAFORM_ADDRESSES, action), "x.y": action},
        )


def test_start_contract_is_lifecycle_update_only() -> None:
    validate_plan(
        "start", {"module.managed_pair.cml2_lifecycle.managed_pair": "update"}
    )
    with pytest.raises(ProtectedStagingError):
        validate_plan("start", {"cml2_lab.staging": "update"})


class FakeTerraformRunner:
    def __init__(self, action: str) -> None:
        self.action = action
        self.calls = []

    def run(self, arguments, *, cwd, environment):
        self.calls.append((tuple(arguments), cwd, dict(environment)))
        if arguments[0] == "plan":
            return tuple(
                event(address, self.action) for address in EXPECTED_TERRAFORM_ADDRESSES
            )
        return ()


def test_executor_applies_exact_approved_saved_plan(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    terraform = bundle / "infrastructure/cml/ephemeral"
    state = tmp_path / "state"
    terraform.mkdir(parents=True)
    state.mkdir(mode=0o700)
    runner = FakeTerraformRunner("create")
    executor = ProtectedTerraformExecutor(bundle, state, runner, {"PATH": "/bin"})
    executor.initialize()
    executor.execute("create")
    init_args, plan_args, apply_args = (
        runner.calls[0][0],
        runner.calls[1][0],
        runner.calls[2][0],
    )
    plan = state / "create.tfplan"
    assert f"-out={plan}" in plan_args
    assert f"-backend-config=path={state / 'terraform.tfstate'}" in init_args
    assert apply_args == ("apply", "-json", "-input=false", str(plan))
    assert not plan.exists()
    assert runner.calls[0][2] == {
        "PATH": "/bin",
        "TF_DATA_DIR": str(state / "terraform-data"),
    }


def test_executor_rejects_checkout_or_symlink_roots(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    root = bundle / "infrastructure/cml/ephemeral"
    root.mkdir(parents=True)
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    link = tmp_path / "link"
    link.symlink_to(bundle, target_is_directory=True)
    with pytest.raises(ProtectedStagingError, match="root"):
        ProtectedTerraformExecutor(link, state, FakeTerraformRunner("create"), {})


def test_rejected_plan_is_never_applied(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    (bundle / "infrastructure/cml/ephemeral").mkdir(parents=True)
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    runner = FakeTerraformRunner("update")
    with pytest.raises(ProtectedStagingError, match="graph rejected"):
        ProtectedTerraformExecutor(bundle, state, runner, {}).execute("create")
    assert len(runner.calls) == 1


def test_protected_cml_client_uses_only_explicit_credentials(monkeypatch) -> None:
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("authenticate"):
            assert json.loads(request.content) == {
                "username": "protected-user",
                "password": "protected-password",
            }
            return httpx.Response(200, json={"token": "in-memory-token"})
        assert request.headers["Authorization"] == "Bearer in-memory-token"
        return httpx.Response(200, json=[])

    monkeypatch.setenv("CML2_TOKEN", "ambient-rejected-by-construction")
    credentials = ProtectedCMLCredentials("protected-user", "protected-password")
    client = ProtectedCMLClient(
        manifest().cml,
        credentials,
        transport=httpx.MockTransport(handler),
    )
    assert "protected-password" not in repr(credentials)
    client.authenticate()
    assert client.labs() == ()
    client.close()
    assert len(requests) == 2


def test_bundle_validation_rejects_checkout_symlink_and_digest_drift(
    tmp_path: Path,
) -> None:
    checkout = tmp_path / "checkout"
    bundle = tmp_path / "bundle"
    checkout.mkdir()
    bundle.mkdir(mode=0o700)
    file = bundle / "terraform/main.tf"
    controller = bundle / "src/network_change_delivery/protected_staging_controller.py"
    file.parent.mkdir()
    controller.parent.mkdir(parents=True)
    file.write_text("safe", encoding="utf-8")
    controller.write_text("controller", encoding="utf-8")
    digest = __import__("hashlib").sha256(file.read_bytes()).hexdigest()
    controller_digest = (
        __import__("hashlib").sha256(controller.read_bytes()).hexdigest()
    )
    files = {
        "terraform/main.tf": digest,
        "src/network_change_delivery/protected_staging_controller.py": (
            controller_digest
        ),
    }
    combined = (
        __import__("hashlib")
        .sha256(json.dumps(files, sort_keys=True, separators=(",", ":")).encode())
        .hexdigest()
    )
    accepted = manifest(
        bundle_digest=combined,
        controller_artifact_digest=controller_digest,
        file_digests=files,
    )
    assert validate_protected_bundle(bundle, checkout, accepted) == bundle.resolve()
    file.write_text("drift", encoding="utf-8")
    with pytest.raises(ProtectedStagingError, match="digest"):
        validate_protected_bundle(bundle, checkout, accepted)
    link = tmp_path / "link"
    link.symlink_to(bundle, target_is_directory=True)
    with pytest.raises(ProtectedStagingError, match="root"):
        validate_protected_bundle(link, checkout, accepted)


def test_cleanup_authority_rejects_brownfield_and_foreign_graph() -> None:
    disposable = "11111111-1111-1111-1111-111111111111"
    validate_cleanup_authority({"cml2_lab.staging"}, disposable, manifest())
    with pytest.raises(ProtectedStagingError, match="brownfield"):
        validate_cleanup_authority(
            {"cml2_lab.staging"}, BROWNFIELD_LAB_UUID, manifest()
        )
    with pytest.raises(ProtectedStagingError, match="graph"):
        validate_cleanup_authority({"foreign.resource"}, disposable, manifest())


def test_brownfield_and_any_existing_staging_lab_fail_closed() -> None:
    admit_cml_labs(
        manifest(),
        "bk-00000000-0000-0000-0000-000000000000",
        [CMLLabObservation(BROWNFIELD_LAB_UUID, "Brownfield live")],
    )
    with pytest.raises(ProtectedStagingError, match="ambiguous"):
        admit_cml_labs(
            manifest(),
            "bk-00000000-0000-0000-0000-000000000000",
            [
                CMLLabObservation(
                    "11111111-1111-1111-1111-111111111111", "NCDP Staging old"
                )
            ],
        )


def test_oidc_request_is_exact_and_jwt_is_never_a_path() -> None:
    calls = []

    def runner(arguments):
        calls.append(arguments)
        return "header.payload.signature\n"

    jwt = request_staging_oidc_jwt(runner)
    assert repr(jwt) == "BuildkiteOIDCJWT(<redacted>)"
    assert calls == [
        (
            "buildkite-agent",
            "oidc",
            "request-token",
            "--audience",
            "urn:ncdp:openbao:staging",
        )
    ]


def test_evidence_is_allowlisted_and_rejects_secret_fields() -> None:
    evidence = ProtectedStagingEvidence(
        pipeline_id="pipeline",
        build_id="build",
        source_commit=SHA1,
        protected_bundle_digest=SHA256,
        manifest_digest=SHA256,
        run_id="bk-build",
        staging_device_ids=(6, 7),
        homolog_ids=(1, 2),
        management_ips=("192.168.4.30", "192.168.4.31"),
        credential_references=(
            "openbao:kv-v2:ncdp/devices/6/ssh",
            "openbao:kv-v2:ncdp/devices/7/ssh",
        ),
    )
    assert "password" not in json.dumps(evidence.safe_dict())
    with pytest.raises(ValidationError):
        ProtectedStagingEvidence.model_validate({**evidence.model_dump(), "token": "x"})
