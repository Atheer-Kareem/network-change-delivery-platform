"""Tests for the private append-only audit filesystem store."""

from __future__ import annotations

import errno
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from test_snmp_protected_deployment import snmp_plan

import network_change_delivery.audit_store as audit_store_module
from network_change_delivery.audit import (
    AuditArtifactKind,
    AuditArtifactReference,
    AuditFinalOutcome,
    GitCorrelation,
    StableTargetIdentity,
    audit_record_with_digest,
    canonical_json_bytes,
    sha256_identity,
)
from network_change_delivery.audit_store import (
    MAX_AUDIT_ARTIFACT_BYTES,
    AuditStore,
    AuditStoreError,
)
from network_change_delivery.ephemeral_staging import StagingEvidence
from network_change_delivery.models import (
    ChangeRecord,
    DesiredDescription,
    FinalOutcome,
    InterfaceDescriptionIntent,
    InterfaceState,
    InventoryDevice,
    StageResult,
)
from network_change_delivery.secrets import CredentialReference
from network_change_delivery.snmp_provisioning import (
    SnmpProvisioningOutcome,
    SnmpProvisioningRecord,
    SnmpProvisioningStage,
)
from network_change_delivery.workflow import build_plan

RECORD_ID = UUID("11111111-1111-4111-8111-111111111111")


def make_store(tmp_path: Path) -> AuditStore:
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    root = tmp_path / "audit"
    root.mkdir(mode=0o700)
    return AuditStore(root, checkout=checkout)


def plan():
    intent = InterfaceDescriptionIntent(
        change_id="CHG-10B1",
        kind="interface_description",
        target="core-02",
        interface="GigabitEthernet2",
        desired=DesiredDescription(description="audit-store-test"),
    )
    device = InventoryDevice(
        name="core-02",
        host="192.0.2.14",
        platform="cisco_iosxe",
        expected_hostname="core-02",
        inventory_source="netbox",
        inventory_object_id="netbox:dcim.device:1",
        inventory_interface_object_id="netbox:dcim.interface:7",
    )
    state = InterfaceState(
        observed_hostname="core-02",
        interface="GigabitEthernet2",
        exists=True,
        description="before",
        protected=False,
    )
    return build_plan(
        intent,
        device,
        state,
        credential=CredentialReference("openbao", "openbao:kv-v2:ncdp/devices/1/ssh"),
        created_at=datetime(2026, 8, 27, tzinfo=UTC),
    )


def record(reference: AuditArtifactReference, **changes: object):
    values: dict[str, object] = {
        "record_id": RECORD_ID,
        "generated_at": datetime(2026, 8, 27, 1, tzinfo=UTC),
        "change_id": "CHG-10B1",
        "git": GitCorrelation(
            repository="github:Atheer-Kareem/network-change-delivery-platform",
            commit="a" * 40,
        ),
        "targets": (
            StableTargetIdentity(
                device="netbox:dcim.device:1",
                interface="netbox:dcim.interface:7",
            ),
        ),
        "final_outcome": AuditFinalOutcome.SUCCEEDED,
        "artifacts": (reference,),
    }
    values.update(changes)
    return audit_record_with_digest(**values)


def snmp_record(
    outcome: SnmpProvisioningOutcome = SnmpProvisioningOutcome.SUCCEEDED,
) -> SnmpProvisioningRecord:
    approved = snmp_plan()
    completed = SnmpProvisioningStage(
        attempted=True, succeeded=True, message="bounded test stage"
    )
    skipped = SnmpProvisioningStage(message="not required")
    return SnmpProvisioningRecord(
        generated_at=datetime(2026, 8, 29, tzinfo=UTC),
        change_id=approved.change_id,
        plan_digest=approved.digest,
        approval_digest=approved.digest,
        device=approved.inventory_object_id,
        platform=approved.platform,
        generation=approved.generation,
        username=approved.username,
        credential_reference=approved.snmp_credential.reference,
        view_name=approved.view_name,
        group_name=approved.group_name,
        oid_closure_digest=approved.oid_closure_digest,
        preflight=completed,
        execution=completed,
        post_validation=completed,
        recovery=skipped,
        final_outcome=outcome,
    )


def change_record() -> ChangeRecord:
    approved = plan()
    stage = StageResult(message="bounded", attempted=False)
    return ChangeRecord(
        generated_at=datetime(2026, 8, 27, tzinfo=UTC),
        change_id=approved.change_id,
        plan_digest=approved.digest,
        target=approved.target,
        inventory_source=approved.inventory_source,
        inventory_object_id=approved.inventory_object_id,
        inventory_interface_object_id=approved.inventory_interface_object_id,
        credential_source=approved.credential_source,
        credential_reference=approved.credential_reference,
        host=approved.host,
        port=approved.port,
        expected_hostname=approved.expected_hostname,
        platform=approved.platform,
        interface=approved.interface,
        previous_description=approved.current_description,
        desired_description=approved.desired_description,
        approval_digest=approved.digest,
        preflight=stage,
        execution=stage,
        post_validation=stage,
        recovery=stage,
        transaction_strategy=approved.transaction_strategy,
        final_outcome=FinalOutcome.SUCCEEDED,
        provider="bounded-test",
    )


def test_root_must_be_absolute_private_owned_and_outside_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checkout = tmp_path / "checkout"
    checkout.mkdir(mode=0o700)
    with pytest.raises(AuditStoreError):
        AuditStore(Path("relative-audit"), checkout=checkout)
    with pytest.raises(AuditStoreError, match="outside checkout"):
        AuditStore(checkout, checkout=checkout)
    inside = checkout / "audit"
    inside.mkdir(mode=0o700)
    with pytest.raises(AuditStoreError, match="outside checkout"):
        AuditStore(inside, checkout=checkout)
    wrong_mode = tmp_path / "wrong-mode"
    wrong_mode.mkdir(mode=0o750)
    with pytest.raises(AuditStoreError, match="permissions"):
        AuditStore(wrong_mode, checkout=checkout)
    owned = tmp_path / "wrong-owner"
    owned.mkdir(mode=0o700)
    current_uid = os.getuid()
    monkeypatch.setattr(audit_store_module.os, "getuid", lambda: current_uid + 1)
    with pytest.raises(AuditStoreError, match="owner"):
        AuditStore(owned, checkout=checkout)


def test_root_and_managed_directory_symlinks_are_rejected(tmp_path: Path) -> None:
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    real = tmp_path / "real"
    real.mkdir(mode=0o700)
    link = tmp_path / "root-link"
    link.symlink_to(real, target_is_directory=True)
    with pytest.raises(AuditStoreError):
        AuditStore(link, checkout=checkout)

    root = tmp_path / "audit"
    root.mkdir(mode=0o700)
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "artifacts").symlink_to(outside, target_is_directory=True)
    with pytest.raises(AuditStoreError, match="managed directory"):
        AuditStore(root, checkout=checkout)


def test_managed_directories_and_final_files_are_private(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    reference = store.persist_artifact(AuditArtifactKind.DEPLOYMENT_PLAN, plan())
    destination = store.root / reference.locator
    assert (store.root / "artifacts").stat().st_mode & 0o777 == 0o700
    assert destination.parent.stat().st_mode & 0o777 == 0o700
    assert (store.root / "records").stat().st_mode & 0o777 == 0o700
    assert destination.stat().st_mode & 0o777 == 0o600
    record_path = store.persist_record(record(reference))
    assert record_path.stat().st_mode & 0o777 == 0o600


def test_intrinsic_artifact_identity_agrees_with_model_digest(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    approved = plan()
    reference = store.persist_artifact(AuditArtifactKind.DEPLOYMENT_PLAN, approved)
    assert reference.sha256 == approved.digest
    assert store.read_artifact(reference) == approved


def test_snmp_plan_and_record_round_trip_under_exact_artifact_kinds(
    tmp_path: Path,
) -> None:
    store = make_store(tmp_path)
    approved = snmp_plan()
    plan_reference = store.persist_artifact(
        AuditArtifactKind.SNMP_PROVISIONING_PLAN, approved
    )
    assert plan_reference.sha256 == approved.digest
    assert store.read_artifact(plan_reference) == approved

    evidence = snmp_record()
    record_reference = store.persist_artifact(
        AuditArtifactKind.SNMP_PROVISIONING_RECORD, evidence
    )
    expected = canonical_json_bytes(evidence.model_dump(mode="json"))
    assert record_reference.sha256 == sha256_identity(expected)
    assert store.read_artifact(record_reference) == evidence
    serialized = expected.decode().casefold()
    for forbidden in (
        "authentication_secret",
        "privacy_secret",
        "password",
        "localized",
    ):
        assert forbidden not in serialized


def test_existing_deployment_plan_and_change_record_round_trip_unchanged(
    tmp_path: Path,
) -> None:
    store = make_store(tmp_path)
    approved = plan()
    plan_reference = store.persist_artifact(AuditArtifactKind.DEPLOYMENT_PLAN, approved)
    assert plan_reference.sha256 == approved.digest
    assert store.read_artifact(plan_reference) == approved
    evidence = change_record()
    record_reference = store.persist_artifact(AuditArtifactKind.CHANGE_RECORD, evidence)
    assert store.read_artifact(record_reference) == evidence


def test_snmp_plan_intrinsic_digest_is_enforced(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    tampered = snmp_plan().model_copy(update={"digest": "sha256:" + "0" * 64})
    with pytest.raises(AuditStoreError, match="intrinsic audit artifact digest"):
        store.persist_artifact(AuditArtifactKind.SNMP_PROVISIONING_PLAN, tampered)


def test_nonintrinsic_artifact_hashes_complete_canonical_json(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    evidence = StagingEvidence(schema_version="2", staging_run_id="bk-test")
    reference = store.persist_artifact(AuditArtifactKind.STAGING_EVIDENCE, evidence)
    expected = canonical_json_bytes(evidence.safe_dict())
    assert reference.sha256 == sha256_identity(expected)
    assert store.read_artifact(reference) == evidence


def test_artifact_exact_reuse_does_not_mutate_file(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    approved = plan()
    first = store.persist_artifact(AuditArtifactKind.DEPLOYMENT_PLAN, approved)
    destination = store.root / first.locator
    before = destination.stat()
    second = store.persist_artifact(AuditArtifactKind.DEPLOYMENT_PLAN, approved)
    after = destination.stat()
    assert second == first
    assert (before.st_ino, before.st_mtime_ns) == (after.st_ino, after.st_mtime_ns)


def test_corrupt_existing_artifact_fails_closed_without_overwrite(
    tmp_path: Path,
) -> None:
    store = make_store(tmp_path)
    approved = plan()
    reference = store.persist_artifact(AuditArtifactKind.DEPLOYMENT_PLAN, approved)
    destination = store.root / reference.locator
    destination.write_bytes(b"{}")
    before = destination.read_bytes()
    with pytest.raises(AuditStoreError):
        store.persist_artifact(AuditArtifactKind.DEPLOYMENT_PLAN, approved)
    assert destination.read_bytes() == before


def test_artifact_and_record_final_symlinks_are_rejected(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    approved = plan()
    reference = store.persist_artifact(AuditArtifactKind.DEPLOYMENT_PLAN, approved)
    artifact_path = store.root / reference.locator
    artifact_path.unlink()
    target = store.root / "target"
    target.write_text("{}", encoding="utf-8")
    target.chmod(0o600)
    artifact_path.symlink_to(target)
    with pytest.raises(AuditStoreError):
        store.read_artifact(reference)

    artifact_path.unlink()
    artifact_path.write_bytes(canonical_json_bytes(approved.model_dump(mode="json")))
    artifact_path.chmod(0o600)
    record_path = store.root / "records" / f"{RECORD_ID}.json"
    record_path.symlink_to(target)
    with pytest.raises(AuditStoreError, match="already exists"):
        store.persist_record(record(reference))
    with pytest.raises(AuditStoreError, match="missing or unsafe"):
        store.read_record(RECORD_ID)


def test_changed_managed_directory_permissions_fail_closed(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    artifacts = store.root / "artifacts"
    artifacts.chmod(0o750)
    with pytest.raises(AuditStoreError, match="permissions"):
        store.persist_artifact(AuditArtifactKind.DEPLOYMENT_PLAN, plan())


def test_record_collision_never_overwrites(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    reference = store.persist_artifact(AuditArtifactKind.DEPLOYMENT_PLAN, plan())
    destination = store.persist_record(record(reference))
    before = destination.read_bytes()
    with pytest.raises(AuditStoreError, match="already exists"):
        store.persist_record(record(reference))
    assert destination.read_bytes() == before


def test_missing_or_tampered_reference_blocks_record_publication(
    tmp_path: Path,
) -> None:
    store = make_store(tmp_path)
    missing = AuditArtifactReference(
        kind=AuditArtifactKind.DEPLOYMENT_PLAN,
        schema_version="1",
        sha256="sha256:" + "f" * 64,
        locator="artifacts/deployment_plan/" + "f" * 64 + ".json",
        size_bytes=10,
    )
    with pytest.raises(AuditStoreError):
        store.persist_record(record(missing))
    assert not (store.root / "records" / f"{RECORD_ID}.json").exists()

    reference = store.persist_artifact(AuditArtifactKind.DEPLOYMENT_PLAN, plan())
    artifact_path = store.root / reference.locator
    artifact_path.write_bytes(b"{}")
    with pytest.raises(AuditStoreError):
        store.persist_record(record(reference))
    assert not (store.root / "records" / f"{RECORD_ID}.json").exists()


def test_tampered_or_malformed_record_fails_read(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    reference = store.persist_artifact(AuditArtifactKind.DEPLOYMENT_PLAN, plan())
    destination = store.persist_record(record(reference))
    payload = record(reference).model_dump(mode="json")
    payload["change_id"] = "CHG-TAMPERED"
    destination.write_bytes(canonical_json_bytes(payload))
    with pytest.raises(AuditStoreError, match="integrity"):
        store.read_record(RECORD_ID)
    destination.write_bytes(b"{")
    with pytest.raises(AuditStoreError, match="schema"):
        store.read_record(RECORD_ID)


def test_malformed_artifact_and_unknown_schema_version_fail_closed(
    tmp_path: Path,
) -> None:
    store = make_store(tmp_path)
    evidence = StagingEvidence(schema_version="2", staging_run_id="bk-test")
    reference = store.persist_artifact(AuditArtifactKind.STAGING_EVIDENCE, evidence)
    destination = store.root / reference.locator
    destination.write_bytes(b"{" + b" " * (reference.size_bytes - 1))
    with pytest.raises(AuditStoreError, match="schema"):
        store.read_artifact(reference)

    unsupported = StagingEvidence(schema_version="99", staging_run_id="bk-test")
    with pytest.raises(AuditStoreError, match="unsupported"):
        store.persist_artifact(AuditArtifactKind.STAGING_EVIDENCE, unsupported)


def test_write_failure_leaves_no_final_record_or_temporary_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = make_store(tmp_path)
    reference = store.persist_artifact(AuditArtifactKind.DEPLOYMENT_PLAN, plan())

    def fail_write(_descriptor: int, _value: object) -> int:
        raise OSError(errno.EIO, "injected write failure")

    monkeypatch.setattr(audit_store_module.os, "write", fail_write)
    with pytest.raises(AuditStoreError, match="publication"):
        store.persist_record(record(reference))
    records = store.root / "records"
    assert not (records / f"{RECORD_ID}.json").exists()
    assert not list(records.glob(".audit-tmp-*"))


def test_directory_fsync_failure_removes_new_final_record_when_possible(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = make_store(tmp_path)
    reference = store.persist_artifact(AuditArtifactKind.DEPLOYMENT_PLAN, plan())
    actual_fsync = os.fsync
    calls = 0

    def fail_first_directory_fsync(descriptor: int) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError(errno.EIO, "injected directory fsync failure")
        actual_fsync(descriptor)

    monkeypatch.setattr(audit_store_module.os, "fsync", fail_first_directory_fsync)
    with pytest.raises(AuditStoreError, match="publication"):
        store.persist_record(record(reference))
    records = store.root / "records"
    assert not (records / f"{RECORD_ID}.json").exists()
    assert not list(records.glob(".audit-tmp-*"))


def test_temporary_files_are_not_records(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    temporary = store.root / "records" / ".audit-tmp-interrupted"
    temporary.write_text("{}", encoding="utf-8")
    temporary.chmod(0o600)
    with pytest.raises(AuditStoreError, match="missing or unsafe"):
        store.read_record(RECORD_ID)


def test_over_limit_artifact_and_record_are_rejected_before_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = make_store(tmp_path)
    evidence = StagingEvidence(schema_version="2", staging_run_id="bk-test")
    evidence.node_states["core-02"] = "x" * MAX_AUDIT_ARTIFACT_BYTES
    with pytest.raises(AuditStoreError, match="exceeds bounded"):
        store.persist_artifact(AuditArtifactKind.STAGING_EVIDENCE, evidence)

    reference = store.persist_artifact(AuditArtifactKind.DEPLOYMENT_PLAN, plan())
    approved = record(reference)
    size = len(canonical_json_bytes(approved.model_dump(mode="json")))
    monkeypatch.setattr(audit_store_module, "MAX_AUDIT_RECORD_BYTES", size - 1)
    with pytest.raises(AuditStoreError, match="exceeds bounded"):
        store.persist_record(approved)
    assert not (store.root / "records" / f"{RECORD_ID}.json").exists()


def test_artifact_kind_cannot_be_used_as_a_generic_payload_label(
    tmp_path: Path,
) -> None:
    store = make_store(tmp_path)
    with pytest.raises(AuditStoreError, match="kind and schema"):
        store.persist_artifact(AuditArtifactKind.CHANGE_RECORD, plan())
    with pytest.raises(AuditStoreError, match="kind and schema"):
        store.persist_artifact(AuditArtifactKind.DEPLOYMENT_PLAN, snmp_plan())
    with pytest.raises(AuditStoreError, match="kind and schema"):
        store.persist_artifact(AuditArtifactKind.SNMP_PROVISIONING_PLAN, plan())
    with pytest.raises(AuditStoreError, match="kind and schema"):
        store.persist_artifact(AuditArtifactKind.CHANGE_RECORD, snmp_record())
    with pytest.raises(AuditStoreError, match="unsupported"):
        store.persist_artifact("arbitrary_json", plan())  # type: ignore[arg-type]
