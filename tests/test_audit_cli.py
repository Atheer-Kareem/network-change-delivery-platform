"""Bounded CLI read/query tests for the durable audit store."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

import pytest
from test_audit_store import make_store, plan, record
from test_configuration_observation_store import linked_record

import network_change_delivery.cli as cli_module
from network_change_delivery.audit import AuditFinalOutcome, BuildkiteCorrelation
from network_change_delivery.audit_store import AuditStore, AuditStoreError
from network_change_delivery.configuration_observation_store import (
    ConfigurationObservationStore,
)


def populated_store(tmp_path: Path, count: int = 2) -> tuple[AuditStore, list[UUID]]:
    store = make_store(tmp_path)
    reference = store.persist_artifact("deployment_plan", plan())
    ids: list[UUID] = []
    for value in range(1, count + 1):
        record_id = UUID(int=value)
        audit = record(
            reference,
            record_id=record_id,
            change_id=f"CHG-{value}",
            final_outcome=AuditFinalOutcome.NO_WRITE,
            buildkite=(
                BuildkiteCorrelation(
                    pipeline_id=UUID(int=20),
                    build_id=UUID("22222222-2222-4222-8222-222222222222"),
                    build_number=48,
                    job_id=UUID(int=21),
                    step_key="deploy-gate",
                )
                if value == 1
                else None
            ),
        )
        store.persist_record(audit)
        ids.append(record_id)
    return store, ids


def cli_root(monkeypatch: pytest.MonkeyPatch, store: AuditStore) -> None:
    checkout = store.root.parent / "checkout"
    monkeypatch.setattr(cli_module, "_checkout_root", lambda: checkout)


def test_audit_show_outputs_only_verified_envelope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    store, ids = populated_store(tmp_path, 1)
    cli_root(monkeypatch, store)
    assert (
        cli_module.main(["audit", "show", str(ids[0]), "--store-root", str(store.root)])
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["record_id"] == str(ids[0])
    assert "execution_artifact" not in payload


def test_audit_show_rejects_tampered_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, ids = populated_store(tmp_path, 1)
    cli_root(monkeypatch, store)
    destination = store.root / "records" / f"{ids[0]}.json"
    payload = json.loads(destination.read_text(encoding="utf-8"))
    payload["change_id"] = "tampered"
    destination.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")), encoding="utf-8"
    )
    with pytest.raises(SystemExit):
        cli_module.main(["audit", "show", str(ids[0]), "--store-root", str(store.root)])


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        (["--change-id", "CHG-1"], 1),
        (["--commit", "a" * 40], 2),
        (["--device-id", "netbox:dcim.device:1"], 2),
    ],
)
def test_audit_find_filters_and_orders_deterministically(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys,
    arguments: list[str],
    expected: int,
) -> None:
    store, ids = populated_store(tmp_path)
    cli_root(monkeypatch, store)
    assert (
        cli_module.main(["audit", "find", "--store-root", str(store.root), *arguments])
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert len(payload) == expected
    assert [item["record_id"] for item in payload] == [
        str(item) for item in ids[:expected]
    ]
    assert all("artifacts" not in item for item in payload)


def test_audit_find_by_build_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    store, _ids = populated_store(tmp_path, 1)
    cli_root(monkeypatch, store)
    build_id = "22222222-2222-4222-8222-222222222222"
    assert (
        cli_module.main(
            ["audit", "find", "--store-root", str(store.root), "--build-id", build_id]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert len(payload) == 1
    assert payload[0]["build_id"] == build_id


def test_find_result_and_scan_bounds_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, _ids = populated_store(tmp_path, 2)
    cli_root(monkeypatch, store)
    with pytest.raises(SystemExit):
        cli_module.main(
            [
                "audit",
                "find",
                "--store-root",
                str(store.root),
                "--commit",
                "a" * 40,
                "--max-results",
                "1",
            ]
        )
    with pytest.raises(AuditStoreError, match="scan bound"):
        store.iter_records(max_scan=1)


def test_corrupt_record_and_unexpected_entries_fail_query(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, ids = populated_store(tmp_path, 1)
    cli_root(monkeypatch, store)
    destination = store.root / "records" / f"{ids[0]}.json"
    destination.write_text("{}", encoding="utf-8")
    with pytest.raises(SystemExit):
        cli_module.main(
            ["audit", "find", "--store-root", str(store.root), "--commit", "a" * 40]
        )
    destination.unlink()
    (store.root / "records" / "unexpected").write_text("x", encoding="utf-8")
    with pytest.raises(AuditStoreError, match="unexpected"):
        store.iter_records()


def test_temporary_entries_are_ignored_but_symlinks_fail_closed(tmp_path: Path) -> None:
    store, ids = populated_store(tmp_path, 1)
    (store.root / "records" / ".audit-tmp-incomplete").write_text("partial")
    assert [item.record_id for item in store.iter_records()] == ids
    target = store.root / "records" / f"{ids[0]}.json"
    link = store.root / "records" / f"{UUID(int=99)}.json"
    link.symlink_to(target)
    with pytest.raises(AuditStoreError, match="unexpected"):
        store.iter_records()


def test_find_observations_is_parent_scoped_bounded_and_metadata_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    audit_store, ids = populated_store(tmp_path, 1)
    cli_root(monkeypatch, audit_store)
    store = ConfigurationObservationStore(
        audit_store.root, checkout=audit_store.root.parent / "checkout"
    )
    parent = store.read_record(ids[0])
    child = linked_record(parent)
    store.persist_observation_record(child)

    assert (
        cli_module.main(
            [
                "audit",
                "find-observations",
                "--store-root",
                str(store.root),
                "--parent-record-id",
                str(parent.record_id),
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert len(payload) == 1
    assert payload[0]["parent_record_id"] == str(parent.record_id)
    assert payload[0]["observation_record_id"] == str(child.observation_record_id)
    assert payload[0]["pre_revision"] is None
    assert payload[0]["post_revision"]["commit"] == "b" * 40
    forbidden = {"configuration", "diff", "error", "credentials"}
    assert forbidden.isdisjoint(payload[0])
