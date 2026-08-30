"""Append-only configuration-observation persistence and query tests."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from uuid import UUID

import pytest
from test_audit_store import plan, record
from test_configuration_observation import observation_record

from network_change_delivery.audit_store import AuditStoreError
from network_change_delivery.configuration_observation import (
    ParentAuditReference,
    observation_record_with_digest,
)
from network_change_delivery.configuration_observation_store import (
    ConfigurationObservationStore,
)


def make_store(tmp_path: Path) -> ConfigurationObservationStore:
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    root = tmp_path / "audit"
    root.mkdir(mode=0o700)
    return ConfigurationObservationStore(root, checkout=checkout)


def populated_store(tmp_path: Path) -> tuple[ConfigurationObservationStore, object]:
    store = make_store(tmp_path)
    artifact = store.persist_artifact("deployment_plan", plan())
    parent = record(artifact)
    store.persist_record(parent)
    return store, parent


def linked_record(parent: object, **changes: object):
    values = observation_record().model_dump(mode="python", exclude={"digest"})
    values["parent_audit"] = ParentAuditReference(
        record_id=parent.record_id, digest=parent.digest
    )
    values.update(changes)
    return observation_record_with_digest(**values)


def test_observation_namespace_is_separate_private_and_directly_readable(
    tmp_path: Path,
) -> None:
    store, parent = populated_store(tmp_path)
    parent_path = store.root / "records" / f"{parent.record_id}.json"
    parent_before = parent_path.read_bytes()
    approved = linked_record(parent)

    destination = store.persist_observation_record(approved)

    assert destination == (
        store.root / "observation-records" / f"{approved.observation_record_id}.json"
    )
    assert stat.S_IMODE(destination.stat().st_mode) == 0o600
    assert stat.S_IMODE(destination.parent.stat().st_mode) == 0o700
    assert not destination.is_symlink()
    assert store.read_observation_record(approved.observation_record_id) == approved
    assert parent_path.read_bytes() == parent_before
    assert not list(
        (store.root / "records").glob(f"{approved.observation_record_id}.json")
    )
    assert not list((store.root / "artifacts").glob("**/configuration_observation*"))


def test_create_false_requires_existing_observation_namespace(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    reopened = ConfigurationObservationStore(
        store.root, checkout=tmp_path / "checkout", create=False
    )
    assert reopened.root == store.root

    (store.root / "observation-records").rmdir()
    with pytest.raises(AuditStoreError, match="managed directory"):
        ConfigurationObservationStore(
            store.root, checkout=tmp_path / "checkout", create=False
        )
    assert not (store.root / "observation-records").exists()


def test_parent_digest_mismatch_and_unknown_target_fail_before_publication(
    tmp_path: Path,
) -> None:
    store, parent = populated_store(tmp_path)
    mismatch = linked_record(
        parent,
        parent_audit=ParentAuditReference(
            record_id=parent.record_id, digest="sha256:" + "f" * 64
        ),
    )
    with pytest.raises(AuditStoreError, match="parent digest mismatch"):
        store.persist_observation_record(mismatch)
    wrong_target = observation_record().model_dump(mode="python", exclude={"digest"})
    wrong_target.update(
        {
            "parent_audit": ParentAuditReference(
                record_id=parent.record_id, digest=parent.digest
            ),
            "target": "netbox:dcim.device:2",
            "oxidized_node": "netbox-device-2",
        }
    )
    with pytest.raises(AuditStoreError, match="target is not in parent"):
        store.persist_observation_record(observation_record_with_digest(**wrong_target))
    assert not list((store.root / "observation-records").glob("*.json"))


def test_missing_or_corrupt_parent_fails_closed(tmp_path: Path) -> None:
    store, parent = populated_store(tmp_path)
    missing = linked_record(
        parent,
        parent_audit=ParentAuditReference(record_id=UUID(int=99), digest=parent.digest),
    )
    with pytest.raises(AuditStoreError, match="missing or unsafe"):
        store.persist_observation_record(missing)

    parent_path = store.root / "records" / f"{parent.record_id}.json"
    parent_path.write_text("{}", encoding="utf-8")
    with pytest.raises(AuditStoreError, match="schema is invalid"):
        store.persist_observation_record(linked_record(parent))
    assert not list((store.root / "observation-records").glob("*.json"))


def test_parent_is_revalidated_on_every_observation_read(tmp_path: Path) -> None:
    store, parent = populated_store(tmp_path)
    approved = linked_record(parent)
    store.persist_observation_record(approved)
    parent_path = store.root / "records" / f"{parent.record_id}.json"
    parent_path.write_text("{}", encoding="utf-8")
    with pytest.raises(AuditStoreError, match="schema is invalid"):
        store.read_observation_record(approved.observation_record_id)


def test_uuid_collision_never_overwrites_existing_bytes(tmp_path: Path) -> None:
    store, parent = populated_store(tmp_path)
    approved = linked_record(parent)
    destination = store.persist_observation_record(approved)
    before = destination.read_bytes()
    with pytest.raises(AuditStoreError, match="identity already exists"):
        store.persist_observation_record(approved)
    assert destination.read_bytes() == before


def test_invalid_digest_tampering_and_noncanonical_bytes_fail_closed(
    tmp_path: Path,
) -> None:
    store, parent = populated_store(tmp_path)
    approved = linked_record(parent)
    with pytest.raises(AuditStoreError, match="digest is invalid"):
        store.persist_observation_record(
            approved.model_copy(update={"repository": "oxidized:tampered"})
        )

    destination = store.persist_observation_record(approved)
    payload = json.loads(destination.read_text(encoding="utf-8"))
    destination.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    with pytest.raises(AuditStoreError, match="not canonical"):
        store.read_observation_record(approved.observation_record_id)


def test_schema_corruption_and_unsafe_file_metadata_fail_closed(tmp_path: Path) -> None:
    store, parent = populated_store(tmp_path)
    approved = linked_record(parent)
    destination = store.persist_observation_record(approved)
    destination.write_text("{}", encoding="utf-8")
    with pytest.raises(AuditStoreError, match="schema is invalid"):
        store.read_observation_record(approved.observation_record_id)

    destination.write_bytes(b"{}")
    destination.chmod(0o644)
    with pytest.raises(AuditStoreError, match="metadata is invalid"):
        store.read_observation_record(approved.observation_record_id)


def test_iteration_and_queries_are_deterministic_and_bounded(tmp_path: Path) -> None:
    store, parent = populated_store(tmp_path)
    ids = [UUID(int=2), UUID(int=1)]
    for record_id in ids:
        store.persist_observation_record(
            linked_record(parent, observation_record_id=record_id)
        )

    expected = [UUID(int=1), UUID(int=2)]
    assert [
        item.observation_record_id for item in store.iter_observation_records()
    ] == expected
    assert [
        item.observation_record_id for item in store.find_by_parent(parent.record_id)
    ] == expected
    assert [
        item.observation_record_id
        for item in store.find_by_device("netbox:dcim.device:1")
    ] == expected
    assert store.find_by_device("netbox:dcim.device:999") == ()
    with pytest.raises(AuditStoreError, match="device identity is invalid"):
        store.find_by_device("core-02")
    with pytest.raises(AuditStoreError, match="scan bound exceeded"):
        store.iter_observation_records(max_scan=1)
    with pytest.raises(AuditStoreError, match="result bound exceeded"):
        store.find_by_parent(parent.record_id, max_results=1)
    with pytest.raises(AuditStoreError, match="result bound is invalid"):
        store.find_by_parent(parent.record_id, max_results=101)


def test_unexpected_entries_and_symlinks_fail_but_temporary_files_are_ignored(
    tmp_path: Path,
) -> None:
    store, parent = populated_store(tmp_path)
    approved = linked_record(parent)
    destination = store.persist_observation_record(approved)
    directory = store.root / "observation-records"
    temporary = directory / ".audit-tmp-incomplete"
    temporary.write_text("partial", encoding="utf-8")
    assert store.iter_observation_records() == (approved,)

    link = directory / f"{UUID(int=99)}.json"
    link.symlink_to(destination)
    with pytest.raises(AuditStoreError, match="unexpected entry"):
        store.iter_observation_records()
    link.unlink()
    (directory / "unexpected").write_text("x", encoding="utf-8")
    with pytest.raises(AuditStoreError, match="unexpected entry"):
        store.iter_observation_records()


def test_observation_file_owner_is_current_uid(tmp_path: Path) -> None:
    store, parent = populated_store(tmp_path)
    destination = store.persist_observation_record(linked_record(parent))
    assert destination.stat().st_uid == os.getuid()
