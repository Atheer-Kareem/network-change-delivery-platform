from __future__ import annotations

import hashlib
import json
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from network_change_delivery.protected_staging import (
    EXPECTED_TERRAFORM_ADDRESSES,
    CMLAuthority,
    ProtectedStagingError,
    ProtectedStagingManifest,
    ProtectedStagingTarget,
    ProtectedTerraformExecutor,
    ProtectedTerraformOutputs,
    StagingTargetAuthority,
)
from network_change_delivery.protected_staging_runtime import (
    FailureCode,
    LifecycleIdentity,
    ProtectedOperationError,
    ProtectedRecoveryMetadata,
    ProtectedRuntimeEvidence,
    ProtectedStaticInventory,
    build_protected_terraform_environment,
    derive_run_directory,
    read_protected_file,
    recover_protected_run,
    run_protected_lifecycle,
    validate_protected_executable,
    verify_ca_digest,
    write_recovery_metadata,
)

PIPELINE = UUID("00000000-0000-0000-0000-000000000001")
BUILD = UUID("00000000-0000-0000-0000-000000000002")
JOB = UUID("00000000-0000-0000-0000-000000000003")
LAB = UUID("11111111-1111-1111-1111-111111111111")
SHA1 = "a" * 40
SHA256 = "b" * 64


def target(device_id: int) -> StagingTargetAuthority:
    cisco = device_id == 6
    return StagingTargetAuthority(
        device_id=device_id,
        name="stg-core-02" if cisco else "stg-edge-junos-01",
        site_id=1,
        device_type_id=1 if cisco else 2,
        environment="staging",
        status="staged",
        role_slug="ncdp-staging",
        platform_slug="cisco-ios-xe" if cisco else "juniper-junos",
        management_interface="GigabitEthernet1" if cisco else "fxp0",
        management_interface_id=9 if cisco else 10,
        management_interface_type="1000base-t",
        management_interface_enabled=True,
        management_interface_mgmt_only=False,
        management_ip_address_id=9 if cisco else 10,
        management_cidr="192.168.4.30/24" if cisco else "192.168.4.31/24",
        management_ip="192.168.4.30" if cisco else "192.168.4.31",
        live_homolog_id=1 if cisco else 2,
        live_homolog_name="core-02" if cisco else "edge-junos-01",
        live_primary_cidr="192.168.4.14/24" if cisco else "192.168.4.20/24",
        openbao_role=f"ncdp-buildkite-staging-device-{device_id}",
        credential_reference=f"openbao:kv-v2:ncdp/devices/{device_id}/ssh",
    )


def manifest(**changes) -> ProtectedStagingManifest:
    controller = "src/network_change_delivery/protected_staging_controller.py"
    values = {
        "schema_version": 3,
        "buildkite_pipeline_id": PIPELINE,
        "source_commit": SHA1,
        "netbox_url": "https://netbox.example",
        "openbao_url": "https://bao.example",
        "source_bundle_digest": SHA256,
        "source_inventory_sha256": SHA256,
        "runtime_inventory_sha256": SHA256,
        "runtime_digest": SHA256,
        "project_wheel_sha256": SHA256,
        "production_requirements_sha256": SHA256,
        "controller_artifact_digest": SHA256,
        "file_digests": {controller: SHA256},
        "cisco": target(6),
        "junos": target(7),
        "live_deny_device_ids": (1, 2, 3),
        "live_deny_management_ips": (
            "192.168.4.14",
            "192.168.4.15",
            "192.168.4.20",
        ),
        "cml": CMLAuthority(
            controller_identity="personal-cml",
            controller_url="https://cml.example",
            ca_pem_sha256=SHA256,
        ),
        "terraform_addresses": tuple(sorted(EXPECTED_TERRAFORM_ADDRESSES)),
        "lifecycle_update_address": ("module.managed_pair.cml2_lifecycle.managed_pair"),
    }
    values.update(changes)
    return ProtectedStagingManifest.model_validate(values)


def outputs(run_id: str) -> ProtectedTerraformOutputs:
    return ProtectedTerraformOutputs(
        staging_run_id=run_id,
        lab_title=f"NCDP Staging {run_id}",
        lab_id=LAB,
        node_ids={
            "system_bridge": UUID("10000000-0000-0000-0000-000000000001"),
            "management_switch": UUID("10000000-0000-0000-0000-000000000002"),
            "cisco": UUID("10000000-0000-0000-0000-000000000003"),
            "junos": UUID("10000000-0000-0000-0000-000000000004"),
        },
        link_ids={
            "system_bridge_management": UUID("20000000-0000-0000-0000-000000000001"),
            "management_cisco": UUID("20000000-0000-0000-0000-000000000002"),
            "management_junos": UUID("20000000-0000-0000-0000-000000000003"),
            "cisco_junos": UUID("20000000-0000-0000-0000-000000000004"),
        },
        lifecycle_state="DEFINED_ON_CORE",
    )


def identity() -> LifecycleIdentity:
    return LifecycleIdentity(PIPELINE, BUILD, JOB, SHA1, SHA256, SHA256)


class FakeOperations:
    def __init__(
        self,
        *,
        state: set[str] | None = None,
        failure: str | None = None,
    ) -> None:
        self.state = set(EXPECTED_TERRAFORM_ADDRESSES) if state is None else set(state)
        self.failure = failure
        self.calls: list[str] = []

    def _call(self, name: str) -> None:
        self.calls.append(name)
        if self.failure == name:
            raise ProtectedStagingError(f"sanitized {name}")

    def admit(self) -> None:
        self._call("admit")

    def create(self) -> ProtectedTerraformOutputs:
        self._call("create")
        return outputs(f"bk-{BUILD}")

    def verify_realization(self, _outputs) -> None:
        self._call("verify")

    def start(self) -> None:
        self._call("start")

    def readiness(self) -> dict[str, float]:
        self._call("readiness")
        return {"cisco_tcp22": 1.0, "junos_tcp830": 2.0}

    def establish_host_trust(self) -> None:
        self._call("trust")

    def validate_read_only(self) -> dict[str, int]:
        self._call("validate")
        return {"cisco": 1, "junos": 1}

    def state_addresses(self) -> set[str]:
        self.calls.append("state")
        return set(self.state)

    def cleanup_retained(self) -> bool:
        self._call("cleanup")
        self.state.clear()
        return True

    def prove_absent(self, _lab_id, _lab_title) -> None:
        self._call("absent")

    def prove_title_absent(self, _lab_title) -> None:
        self._call("absent-title")


def run_directory(tmp_path: Path) -> Path:
    root = tmp_path / "state"
    root.mkdir(mode=0o700)
    _run_id, directory = derive_run_directory(root, BUILD)
    return directory


def test_schema_three_binds_pipeline_endpoints_source_and_runtime() -> None:
    assert manifest().schema_version == 3
    with pytest.raises(ValidationError):
        manifest(buildkite_pipeline_id="not-a-uuid")
    with pytest.raises(ValidationError):
        manifest(netbox_url="https://other.example/path")
    with pytest.raises(ValidationError):
        manifest(openbao_url="http://bao.example")


def test_protected_file_rejects_mode_symlink_empty_and_checkout(tmp_path: Path) -> None:
    checkout = tmp_path / "checkout"
    external = tmp_path / "external"
    checkout.mkdir()
    external.mkdir()
    secret = external / "secret"
    secret.write_text("value", encoding="utf-8")
    secret.chmod(0o600)
    assert read_protected_file(secret, checkout) == b"value"
    secret.chmod(0o640)
    with pytest.raises(ProtectedStagingError):
        read_protected_file(secret, checkout)
    secret.chmod(0o600)
    link = external / "link"
    link.symlink_to(secret)
    with pytest.raises(ProtectedStagingError):
        read_protected_file(link, checkout)
    empty = external / "empty"
    empty.touch(mode=0o600)
    with pytest.raises(ProtectedStagingError):
        read_protected_file(empty, checkout)
    inside = checkout / "secret"
    inside.write_text("value", encoding="utf-8")
    inside.chmod(0o600)
    with pytest.raises(ProtectedStagingError):
        read_protected_file(inside, checkout)


def test_protected_tool_requires_absolute_private_non_checkout_path(
    tmp_path: Path,
) -> None:
    checkout = tmp_path / "checkout"
    external = tmp_path / "tools"
    checkout.mkdir()
    external.mkdir()
    tool = external / "terraform"
    tool.write_text("#!/bin/sh\n", encoding="utf-8")
    tool.chmod(0o700)
    assert (
        validate_protected_executable(
            tool,
            checkout,
            expected_version="1.15.8",
            version_runner=lambda _path, _args: "1.15.8",
        )
        == tool
    )
    tool.chmod(0o720)
    with pytest.raises(ProtectedStagingError):
        validate_protected_executable(tool, checkout)


def test_terraform_environment_is_constructed_not_inherited(monkeypatch) -> None:
    monkeypatch.setenv("TF_LOG", "TRACE")
    monkeypatch.setenv("NCDP_NETBOX_TOKEN", "forbidden")
    variables = {
        "TF_VAR_staging_run_id": f"bk-{BUILD}",
        "TF_VAR_lifecycle_state": "DEFINED_ON_CORE",
        "TF_VAR_cisco_bootstrap_hostname": "stg-core-02",
        "TF_VAR_cisco_bootstrap_management_cidr": "192.168.4.30/24",
        "TF_VAR_cisco_bootstrap_username": "cisco-user",
        "TF_VAR_cisco_bootstrap_password": "cisco-password",
        "TF_VAR_junos_bootstrap_hostname": "stg-edge-junos-01",
        "TF_VAR_junos_bootstrap_management_cidr": "192.168.4.31/24",
        "TF_VAR_junos_bootstrap_username": "junos-user",
        "TF_VAR_junos_bootstrap_password_hash": "$6$salt$hash",
    }
    environment = build_protected_terraform_environment(
        terraform_data_dir=Path("/protected/data"),
        cml_address="https://cml.example",
        cml_token="memory-only",
        cml_ca_pem="pem",
        variables=variables,
        trusted_path="/protected/bin",
    )
    assert set(environment) == {
        "PATH",
        "TF_IN_AUTOMATION",
        "TF_DATA_DIR",
        "CML2_ADDRESS",
        "CML2_TOKEN",
        "CML2_CACERT",
        *variables,
    }
    assert "TF_LOG" not in environment and "NCDP_NETBOX_TOKEN" not in environment


def test_static_inventory_accepts_only_exact_pair() -> None:
    targets = (
        ProtectedStagingTarget(
            device_id=6,
            name="stg-core-02",
            host="192.168.4.30",
            platform="cisco_iosxe",
            management_interface="GigabitEthernet1",
            interface_id=9,
            management_cidr="192.168.4.30/24",
            ip_address_id=9,
            live_homolog_id=1,
            credential_reference="openbao:kv-v2:ncdp/devices/6/ssh",
            openbao_role="ncdp-buildkite-staging-device-6",
        ),
        ProtectedStagingTarget(
            device_id=7,
            name="stg-edge-junos-01",
            host="192.168.4.31",
            platform="junos",
            management_interface="fxp0",
            interface_id=10,
            management_cidr="192.168.4.31/24",
            ip_address_id=10,
            live_homolog_id=2,
            credential_reference="openbao:kv-v2:ncdp/devices/7/ssh",
            openbao_role="ncdp-buildkite-staging-device-7",
        ),
    )
    inventory = ProtectedStaticInventory(targets)
    assert inventory.resolve("stg-core-02").port == 22
    assert inventory.resolve("stg-edge-junos-01").port == 830
    integration = inventory.resolve("stg-core-02", "GigabitEthernet2")
    assert integration.inventory_interface_object_id == (
        "protected:cml.integration:6:GigabitEthernet2"
    )
    with pytest.raises(ProtectedStagingError):
        inventory.resolve("stg-core-02", "GigabitEthernet3")
    with pytest.raises(ProtectedStagingError):
        inventory.resolve("core-02")


def test_complete_lifecycle_cleans_absence_proves_and_retires(tmp_path: Path) -> None:
    directory = run_directory(tmp_path)
    operations = FakeOperations()
    evidence = run_protected_lifecycle(identity(), directory, operations)
    assert evidence.overall_result == "passed"
    assert evidence.cleanup_result == "passed"
    assert evidence.absence_result == "passed"
    assert evidence.state_retirement_result == "passed"
    assert not directory.exists()
    assert operations.calls.count("cleanup") == 1


@pytest.mark.parametrize("count", [1, 5, 10])
def test_create_failure_valid_partial_state_gets_one_exact_cleanup(
    tmp_path: Path, count: int
) -> None:
    directory = run_directory(tmp_path)
    state = set(sorted(EXPECTED_TERRAFORM_ADDRESSES)[:count])
    operations = FakeOperations(state=state, failure="create")
    evidence = run_protected_lifecycle(identity(), directory, operations)
    assert evidence.overall_result == "failed"
    assert evidence.primary_failure == FailureCode.TERRAFORM_CREATE
    assert evidence.cleanup_result == "passed"
    assert evidence.absence_result == "passed"
    assert operations.calls.count("cleanup") == 1
    assert "absent-title" in operations.calls
    assert not directory.exists()


def test_create_failure_with_empty_state_never_destroys(tmp_path: Path) -> None:
    directory = run_directory(tmp_path)
    operations = FakeOperations(state=set(), failure="create")
    evidence = run_protected_lifecycle(identity(), directory, operations)
    assert "cleanup" not in operations.calls
    assert evidence.cleanup_result == "passed"
    assert evidence.absence_result == "passed"
    assert "absent-title" in operations.calls
    assert evidence.state_retirement_result == "passed"
    assert not directory.exists()


def test_create_attempt_without_state_retains_when_title_is_present(
    tmp_path: Path,
) -> None:
    directory = run_directory(tmp_path)
    operations = FakeOperations(state=set(), failure="absent-title")
    operations.failure = "create"
    original = operations.prove_title_absent

    def fail_title(title) -> None:
        original(title)
        raise ProtectedStagingError("sanitized title conflict")

    operations.prove_title_absent = fail_title
    evidence = run_protected_lifecycle(identity(), directory, operations)
    assert evidence.absence_result == "failed"
    assert evidence.cleanup_failure == FailureCode.ABSENCE_FAILED
    assert directory.exists()


def test_admission_failure_retires_empty_run_without_cml_claim(tmp_path: Path) -> None:
    directory = run_directory(tmp_path)
    operations = FakeOperations(state=set(), failure="admit")
    evidence = run_protected_lifecycle(identity(), directory, operations)
    assert "create" not in operations.calls
    assert "cleanup" not in operations.calls
    assert "absent-title" not in operations.calls
    assert evidence.state_retirement_result == "passed"
    assert not directory.exists()


def test_terraform_init_has_distinct_sanitized_failure_code(tmp_path: Path) -> None:
    directory = run_directory(tmp_path)
    operations = FakeOperations(state=set())

    def fail_init() -> None:
        operations.calls.append("admit")
        raise ProtectedOperationError(FailureCode.TERRAFORM_INIT)

    operations.admit = fail_init
    evidence = run_protected_lifecycle(identity(), directory, operations)
    assert evidence.primary_failure == FailureCode.TERRAFORM_INIT
    assert evidence.safe_json().find("TERRAFORM_INIT") >= 0
    assert "absent-title" not in operations.calls


def test_foreign_state_is_retained_without_destroy(tmp_path: Path) -> None:
    directory = run_directory(tmp_path)
    operations = FakeOperations(state={"foreign.resource"}, failure="create")
    evidence = run_protected_lifecycle(identity(), directory, operations)
    assert evidence.cleanup_result == "retained"
    assert evidence.cleanup_failure == FailureCode.CLEANUP_UNAUTHORIZED
    assert "cleanup" not in operations.calls
    assert directory.exists()


@pytest.mark.parametrize("failure", ["cleanup", "absent"])
def test_failures_preserve_independent_cleanup_state(
    tmp_path: Path, failure: str
) -> None:
    directory = run_directory(tmp_path)
    operations = FakeOperations(failure=failure)
    evidence = run_protected_lifecycle(identity(), directory, operations)
    assert evidence.overall_result == "failed"
    assert directory.exists()
    if failure == "cleanup":
        assert evidence.cleanup_failure == FailureCode.CLEANUP_FAILED
    else:
        assert evidence.cleanup_failure == FailureCode.ABSENCE_FAILED


def test_validation_failure_with_proven_cleanup_retires_state(tmp_path: Path) -> None:
    directory = run_directory(tmp_path)
    evidence = run_protected_lifecycle(
        identity(), directory, FakeOperations(failure="validate")
    )
    assert evidence.overall_result == "failed"
    assert evidence.primary_failure == FailureCode.VALIDATION
    assert evidence.cleanup_result == "passed"
    assert not directory.exists()


def test_evidence_rejects_secret_fields_and_never_emits_injected_exception(
    tmp_path: Path,
) -> None:
    directory = run_directory(tmp_path)
    evidence = run_protected_lifecycle(
        identity(), directory, FakeOperations(failure="validate")
    )
    serialized = evidence.safe_json()
    assert "sanitized validate" not in serialized
    assert "password" not in serialized
    payload = json.loads(serialized)
    payload["token"] = "secret"
    with pytest.raises(ValidationError):
        ProtectedRuntimeEvidence.model_validate(payload)


def test_ca_digest_is_exact() -> None:
    pem = b"test-ca"
    accepted = manifest(
        cml=CMLAuthority(
            controller_identity="personal-cml",
            controller_url="https://cml.example",
            ca_pem_sha256=hashlib.sha256(pem).hexdigest(),
        )
    )
    verify_ca_digest(pem, accepted)
    with pytest.raises(ProtectedStagingError):
        verify_ca_digest(b"other", accepted)


class CleanupTerraformRunner:
    def __init__(self, state: set[str], planned: dict[str, str]) -> None:
        self.state = set(state)
        self.planned = planned
        self.calls = []

    def run(self, arguments, *, cwd, environment):
        del cwd, environment
        self.calls.append(tuple(arguments))
        if arguments[:2] == ["state", "list"]:
            return tuple(sorted(self.state))
        if arguments[0] == "plan":
            return tuple(
                json.dumps(
                    {
                        "type": "planned_change",
                        "change": {"resource": {"addr": address}, "action": action},
                    }
                )
                for address, action in self.planned.items()
            )
        if arguments[0] == "apply":
            self.state.clear()
        return ()


def test_executor_start_changes_only_protected_lifecycle_input(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    (bundle / "infrastructure/cml/ephemeral").mkdir(parents=True)
    state_dir = tmp_path / "state"
    state_dir.mkdir(mode=0o700)

    class StartRunner:
        def __init__(self) -> None:
            self.environment = {}

        def run(self, arguments, *, cwd, environment):
            del cwd
            self.environment = dict(environment)
            if arguments[0] == "plan":
                return (
                    json.dumps(
                        {
                            "type": "planned_change",
                            "change": {
                                "resource": {
                                    "addr": (
                                        "module.managed_pair.cml2_lifecycle.managed_pair"
                                    )
                                },
                                "action": "update",
                            },
                        }
                    ),
                )
            return ()

    runner = StartRunner()
    executor = ProtectedTerraformExecutor(
        bundle,
        state_dir,
        runner,
        {"TF_VAR_lifecycle_state": "DEFINED_ON_CORE"},
    )
    executor.set_lifecycle_state("STARTED")
    executor.execute("start")
    assert runner.environment["TF_VAR_lifecycle_state"] == "STARTED"


@pytest.mark.parametrize("count", [1, 5, 10])
def test_executor_partial_cleanup_applies_exact_subset(
    tmp_path: Path, count: int
) -> None:
    bundle = tmp_path / "bundle"
    (bundle / "infrastructure/cml/ephemeral").mkdir(parents=True)
    state_dir = tmp_path / "state"
    state_dir.mkdir(mode=0o700)
    (state_dir / "terraform.tfstate").touch(mode=0o600)
    state = set(sorted(EXPECTED_TERRAFORM_ADDRESSES)[:count])
    runner = CleanupTerraformRunner(state, dict.fromkeys(state, "delete"))
    executor = ProtectedTerraformExecutor(bundle, state_dir, runner, {})
    assert executor.cleanup_retained() is True
    assert not runner.state
    assert runner.calls[-1][0] == "apply"


@pytest.mark.parametrize(
    "state,planned",
    [
        ({"foreign.resource"}, {"foreign.resource": "delete"}),
        ({"cml2_lab.staging"}, {}),
        ({"cml2_lab.staging"}, {"cml2_lab.staging": "update"}),
        (
            {"cml2_lab.staging"},
            {"cml2_lab.staging": "delete", "foreign.resource": "delete"},
        ),
    ],
)
def test_executor_cleanup_rejects_foreign_or_mismatched_plan(
    tmp_path: Path, state, planned
) -> None:
    bundle = tmp_path / "bundle"
    (bundle / "infrastructure/cml/ephemeral").mkdir(parents=True)
    state_dir = tmp_path / "state"
    state_dir.mkdir(mode=0o700)
    (state_dir / "terraform.tfstate").touch(mode=0o600)
    runner = CleanupTerraformRunner(state, planned)
    executor = ProtectedTerraformExecutor(bundle, state_dir, runner, {})
    with pytest.raises(ProtectedStagingError):
        executor.cleanup_retained()
    assert not any(call[0] == "apply" for call in runner.calls)


def test_recovery_uses_exact_metadata_and_never_create_or_start(tmp_path: Path) -> None:
    checkout = tmp_path / "checkout"
    state_root = tmp_path / "state"
    checkout.mkdir()
    state_root.mkdir(mode=0o700)
    run_id, directory = derive_run_directory(state_root, BUILD)
    metadata = ProtectedRecoveryMetadata(
        run_id=run_id,
        build_id=BUILD,
        source_commit=SHA1,
        manifest_digest=manifest().digest,
        bundle_digest=SHA256,
        lab_id=LAB,
        lab_title=f"NCDP Staging {run_id}",
        terraform_addresses=tuple(sorted(EXPECTED_TERRAFORM_ADDRESSES)),
    )
    write_recovery_metadata(directory / "recovery-metadata.json", metadata)
    operations = FakeOperations(state={"cml2_lab.staging"})
    recover_protected_run(BUILD, state_root, checkout, manifest(), operations)
    assert "create" not in operations.calls and "start" not in operations.calls
    assert not directory.exists()


def test_recovery_rejects_wrong_bundle(tmp_path: Path) -> None:
    checkout = tmp_path / "checkout"
    state_root = tmp_path / "state"
    checkout.mkdir()
    state_root.mkdir(mode=0o700)
    run_id, directory = derive_run_directory(state_root, BUILD)
    metadata = ProtectedRecoveryMetadata(
        run_id=run_id,
        build_id=BUILD,
        source_commit=SHA1,
        manifest_digest="c" * 64,
        bundle_digest=SHA256,
        lab_id=LAB,
        lab_title=f"NCDP Staging {run_id}",
        terraform_addresses=tuple(sorted(EXPECTED_TERRAFORM_ADDRESSES)),
    )
    write_recovery_metadata(directory / "recovery-metadata.json", metadata)
    with pytest.raises(ProtectedStagingError, match="version mismatch"):
        recover_protected_run(BUILD, state_root, checkout, manifest(), FakeOperations())
    assert directory.exists()


def test_recovery_accepts_provisional_metadata_without_arbitrary_lab_id(
    tmp_path: Path,
) -> None:
    checkout = tmp_path / "checkout"
    state_root = tmp_path / "state"
    checkout.mkdir()
    state_root.mkdir(mode=0o700)
    run_id, directory = derive_run_directory(state_root, BUILD)
    metadata = ProtectedRecoveryMetadata(
        run_id=run_id,
        build_id=BUILD,
        source_commit=SHA1,
        manifest_digest=manifest().digest,
        bundle_digest=SHA256,
        lab_title=f"NCDP Staging {run_id}",
        terraform_addresses=tuple(sorted(EXPECTED_TERRAFORM_ADDRESSES)),
    )
    write_recovery_metadata(directory / "recovery-metadata.json", metadata)
    operations = FakeOperations(state={"cml2_lab.staging"})
    recover_protected_run(BUILD, state_root, checkout, manifest(), operations)
    assert "absent-title" in operations.calls
    assert "create" not in operations.calls and "start" not in operations.calls
    assert not directory.exists()


@pytest.mark.parametrize("final_metadata", [True, False])
def test_recovery_accepts_empty_post_destroy_state_and_proves_absence(
    tmp_path: Path, final_metadata: bool
) -> None:
    checkout = tmp_path / "checkout"
    state_root = tmp_path / "state"
    checkout.mkdir()
    state_root.mkdir(mode=0o700)
    run_id, directory = derive_run_directory(state_root, BUILD)
    metadata = ProtectedRecoveryMetadata(
        run_id=run_id,
        build_id=BUILD,
        source_commit=SHA1,
        manifest_digest=manifest().digest,
        bundle_digest=SHA256,
        lab_id=LAB if final_metadata else None,
        lab_title=f"NCDP Staging {run_id}",
        terraform_addresses=tuple(sorted(EXPECTED_TERRAFORM_ADDRESSES)),
    )
    write_recovery_metadata(directory / "recovery-metadata.json", metadata)
    operations = FakeOperations(state=set())
    recover_protected_run(BUILD, state_root, checkout, manifest(), operations)
    assert "cleanup" not in operations.calls
    assert ("absent" if final_metadata else "absent-title") in operations.calls
    assert not directory.exists()


def test_recovery_empty_state_retains_when_absence_fails(tmp_path: Path) -> None:
    checkout = tmp_path / "checkout"
    state_root = tmp_path / "state"
    checkout.mkdir()
    state_root.mkdir(mode=0o700)
    run_id, directory = derive_run_directory(state_root, BUILD)
    metadata = ProtectedRecoveryMetadata(
        run_id=run_id,
        build_id=BUILD,
        source_commit=SHA1,
        manifest_digest=manifest().digest,
        bundle_digest=SHA256,
        lab_title=f"NCDP Staging {run_id}",
        terraform_addresses=tuple(sorted(EXPECTED_TERRAFORM_ADDRESSES)),
    )
    write_recovery_metadata(directory / "recovery-metadata.json", metadata)
    operations = FakeOperations(state=set(), failure="absent-title")
    with pytest.raises(ProtectedStagingError):
        recover_protected_run(BUILD, state_root, checkout, manifest(), operations)
    assert "cleanup" not in operations.calls
    assert directory.exists()
