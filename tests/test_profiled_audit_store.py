"""Append-only current namespace safety and historical store compatibility."""

import stat
from uuid import UUID

import pytest
from profiled_audit_fixtures import bundle
from test_audit_store import (
    make_store,
    plan,
    store_snapshot,
)
from test_audit_store import (
    record as historical_record,
)
from test_profiled_audit import rehash

from network_change_delivery import audit_store as module
from network_change_delivery.audit import (
    AuditArtifactKind as Kind,
)
from network_change_delivery.audit import (
    canonical_json_bytes,
    sha256_identity,
)
from network_change_delivery.audit_store import AuditStore, AuditStoreError
from network_change_delivery.profiled_audit import ProfiledDeliveryAuditRecord


def test_historical_two_directory_store_readonly_needs_no_migration(tmp_path):
    store = make_store(tmp_path)
    reference = store.persist_artifact(Kind.DEPLOYMENT_PLAN, plan())
    old = historical_record(reference)
    store.persist_record(old)
    assert {p.name for p in store.root.iterdir()} == {"records", "artifacts"}
    before = store_snapshot(store.root)
    readonly = AuditStore(store.root, checkout=tmp_path / "checkout", create=False)
    assert readonly.read_record(old.record_id) == old
    assert readonly.iter_records() == (old,)
    assert readonly.iter_profiled_records() == ()
    assert store_snapshot(store.root) == before
    current, raw, _ = bundle(store)
    store.persist_profiled_record(current, artifact_bytes=raw)
    assert readonly.read_record(old.record_id) == old
    assert readonly.read_artifact(reference) == plan()
    for path in store.root.rglob("*"):
        assert stat.S_IMODE(path.stat().st_mode) == (0o700 if path.is_dir() else 0o600)


@pytest.mark.parametrize("namespace", ["profiled-records", "profiled-artifact-bytes"])
@pytest.mark.parametrize("unsafe", ["mode", "symlink", "file", "owner"])
def test_new_namespaces_fail_closed_without_changing_old_store(
    tmp_path, monkeypatch, namespace, unsafe
):
    store = make_store(tmp_path)
    path = store.root / namespace
    if unsafe == "symlink":
        path.symlink_to(tmp_path / "missing", target_is_directory=True)
    elif unsafe == "file":
        path.write_text("not a directory")
    else:
        path.mkdir(mode=0o755 if unsafe == "mode" else 0o700)
    if unsafe == "owner":
        original = module.Path.stat

        def wrong_owner(self, *a, **kw):
            result = original(self, *a, **kw)
            if self == path:
                from types import SimpleNamespace

                return SimpleNamespace(st_uid=result.st_uid + 1, st_mode=result.st_mode)
            return result

        monkeypatch.setattr(module.Path, "stat", wrong_owner)
    with pytest.raises(AuditStoreError):
        AuditStore(store.root, checkout=tmp_path / "checkout", create=False)


def test_create_only_duplicate_uuid_and_content_reuse(tmp_path):
    store = make_store(tmp_path)
    first, raw, _ = bundle(store)
    path = store.persist_profiled_record(first, artifact_bytes=raw)
    before = store_snapshot(store.root)
    with pytest.raises(AuditStoreError, match="already exists"):
        store.persist_profiled_record(first, artifact_bytes=raw)
    assert store_snapshot(store.root) == before
    second = ProfiledDeliveryAuditRecord.model_validate(
        rehash({**first.model_dump(mode="json"), "record_id": str(UUID(int=2))})
    )
    store.persist_profiled_record(second, artifact_bytes=raw)
    assert path.read_bytes() == canonical_json_bytes(first.model_dump(mode="json"))
    assert [r.record_id for r in store.iter_profiled_records()] == [
        second.record_id,
        first.record_id,
    ]
    with pytest.raises(AuditStoreError, match="scan bound exceeded"):
        store.iter_profiled_records(max_scan=1)
    for bound in (0, module.MAX_AUDIT_RECORD_SCAN + 1):
        with pytest.raises(AuditStoreError):
            store.iter_profiled_records(max_scan=bound)


@pytest.mark.parametrize("part", ["canonical", "original", "envelope"])
def test_symlink_replacement_is_rejected_for_all_profiled_layers(tmp_path, part):
    store = make_store(tmp_path)
    record, raw, _ = bundle(store)
    path = store.persist_profiled_record(record, artifact_bytes=raw)
    if part == "canonical":
        path = store.root / record.artifacts[0].locator
    elif part == "original":
        kind, digest = next(iter(record.byte_digests_by_kind().items()))
        path = (
            store.root / "profiled-artifact-bytes" / kind.value / f"{digest[7:]}.json"
        )
    outside = tmp_path / "outside"
    outside.write_bytes(path.read_bytes())
    outside.chmod(0o600)
    path.unlink()
    path.symlink_to(outside)
    with pytest.raises(AuditStoreError):
        store.read_profiled_record(record.record_id)


@pytest.mark.parametrize("limit", ["record", "artifact"])
def test_bounded_publication_fails_without_final_envelope(tmp_path, monkeypatch, limit):
    store = make_store(tmp_path)
    record, raw, _ = bundle(store)
    monkeypatch.setattr(
        module,
        "MAX_AUDIT_RECORD_BYTES" if limit == "record" else "MAX_AUDIT_ARTIFACT_BYTES",
        16,
    )
    with pytest.raises(AuditStoreError):
        store.persist_profiled_record(record, artifact_bytes=raw)
    assert store.iter_profiled_records() == ()


def test_failed_envelope_publication_keeps_orphan_artifacts_without_fabricating_record(
    tmp_path, monkeypatch
):
    store = make_store(tmp_path)
    record, raw, _ = bundle(store)
    publish = store._publish_new

    def interrupted(directory, name, content):
        if directory.name == "profiled-records":
            raise AuditStoreError("synthetic publication interruption")
        return publish(directory, name, content)

    monkeypatch.setattr(store, "_publish_new", interrupted)
    with pytest.raises(AuditStoreError):
        store.persist_profiled_record(record, artifact_bytes=raw)
    assert store.iter_profiled_records() == ()
    assert len(list((store.root / "profiled-artifact-bytes").rglob("*.json"))) == 3
    assert all((store.root / ref.locator).exists() for ref in record.artifacts)


@pytest.mark.parametrize("entry", ["unexpected", "directory", "symlink"])
def test_profiled_scan_rejects_unexpected_entries(tmp_path, entry):
    store = make_store(tmp_path)
    current, raw, _ = bundle(store)
    store.persist_profiled_record(current, artifact_bytes=raw)
    path = store.root / "profiled-records" / (str(UUID(int=3)) + ".json")
    if entry == "directory":
        path.mkdir()
    elif entry == "symlink":
        path.symlink_to(tmp_path / "missing")
    else:
        (path.parent / "unexpected").write_text("bad")
    with pytest.raises(AuditStoreError):
        store.iter_profiled_records()


def test_original_json_cannot_hide_duplicate_fields(tmp_path):
    store = make_store(tmp_path)
    record, raw, _ = bundle(store, compliant=True)
    kind = Kind.PROFILED_COMPLIANCE_RECORD
    value = raw[kind]
    # Last-key-wins parsing would hide an unrepresented value in retained bytes.
    raw[kind] = b'{"credential_reference":"unrepresented-value",' + value[1:]
    data = record.model_dump(mode="json")
    data["artifact_bytes"]["planning"] = sha256_identity(raw[kind])
    changed = ProfiledDeliveryAuditRecord.model_validate(rehash(data))
    with pytest.raises(AuditStoreError, match="duplicate"):
        store.persist_profiled_record(changed, artifact_bytes=raw)
    assert store.iter_profiled_records() == ()


@pytest.mark.parametrize(
    "kind",
    [
        Kind.PROFILED_DEPLOYMENT_PLAN,
        Kind.PROFILED_PROMOTION,
        Kind.PROFILED_CHANGE_RECORD,
    ],
)
def test_modified_artifact_content_fails_correlation_even_with_valid_outer_hashes(
    tmp_path, kind
):
    store = make_store(tmp_path)
    record, raw, artifacts = bundle(store)
    value = artifacts[kind]
    data = value.model_dump(mode="json")
    if kind is Kind.PROFILED_DEPLOYMENT_PLAN:
        data["change_id"] = "CHG-UNRELATED"
        rehash(data)
    elif kind is Kind.PROFILED_PROMOTION:
        data["plan_digest"] = "sha256:" + "c" * 64
        rehash(data)
    else:
        data["change_id"] = "CHG-UNRELATED"
    updated = type(value).model_validate(data)
    ref = store.persist_artifact(kind, updated)
    raw[kind] = updated.model_dump_json(indent=2).encode() + b"\n"
    envelope = record.model_dump(mode="json")
    envelope["artifacts"] = [
        ref.model_dump(mode="json") if r["kind"] == kind else r
        for r in envelope["artifacts"]
    ]
    if kind is Kind.PROFILED_DEPLOYMENT_PLAN:
        envelope["planning_result_digest"] = updated.digest
        envelope["artifact_bytes"]["planning"] = sha256_identity(raw[kind])
    elif kind is Kind.PROFILED_PROMOTION:
        envelope["authorization"]["promotion_digest"] = updated.digest
        envelope["artifact_bytes"]["promotion"] = sha256_identity(raw[kind])
    else:
        envelope["artifact_bytes"]["execution"] = sha256_identity(raw[kind])
    changed = ProfiledDeliveryAuditRecord.model_validate(rehash(envelope))
    with pytest.raises(AuditStoreError):
        store.persist_profiled_record(changed, artifact_bytes=raw)
    assert not store.iter_profiled_records()


def test_unvalidated_historical_copy_cannot_persist_new_profiled_artifacts(tmp_path):
    store = make_store(tmp_path)
    legacy = historical_record(store.persist_artifact(Kind.DEPLOYMENT_PLAN, plan()))
    current, _, _ = bundle(store, compliant=True)
    forged = legacy.model_copy(
        update={
            "artifacts": tuple(
                sorted(
                    (*legacy.artifacts, *current.artifacts), key=lambda ref: ref.kind
                )
            )
        }
    )
    forged = forged.model_copy(update={"digest": forged.calculated_digest()})
    with pytest.raises(ValueError, match="historical audit"):
        store.persist_record(forged)
    assert store.iter_records() == ()
