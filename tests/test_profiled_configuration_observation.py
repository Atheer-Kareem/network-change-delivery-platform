"""Current chronology contracts/capture/store; exclusively synthetic local fixtures."""

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pytest
from profiled_audit_fixtures import bundle, planning_result
from profiled_chronology_fixtures import observation
from test_profiled_audit import rehash

from network_change_delivery import profiled_configuration_observation as module
from network_change_delivery.configuration_observation import (
    ConfigurationObservationRecord,
    ParentAuditReference,
)
from network_change_delivery.configuration_observation import (
    ObservationFailureCategory as Failure,
)
from network_change_delivery.configuration_observation import (
    ObservationStatus as Status,
)
from network_change_delivery.profiled_configuration_observation import (
    ProfiledConfigurationObservationRecord as Record,
)
from network_change_delivery.profiled_configuration_observation import (
    ProfiledDeliveryAuditReference,
    build_profiled_observation_record,
    canonical_oxidized_node,
    capture_attempt,
    capture_profiled_attempt,
    chronology_id,
    load_attempt_file,
    persist_attempt_file,
)
from network_change_delivery.profiled_configuration_observation_store import (
    ProfiledConfigurationObservationStore as Store,
)


@pytest.fixture
def stored(tmp_path):
    root = tmp_path / "audit"
    root.mkdir(mode=0o700)
    (tmp_path / "checkout").mkdir()
    store = Store(root, checkout=tmp_path / "checkout")
    parent, raw, _artifacts = bundle(store)
    store.persist_profiled_record(parent, artifact_bytes=raw)
    pre = observation()
    post = observation(expected_before=pre.after_revision)
    child = build_profiled_observation_record(
        parent, pre, post, generated_at=datetime.now(UTC)
    )
    return store, parent, child


@pytest.mark.parametrize("pre_changed", [False, True])
@pytest.mark.parametrize("post_changed", [False, True])
def test_valid_revision_chain_roundtrip(stored, pre_changed, post_changed):
    store, parent, _ = stored
    pre = observation(changed=pre_changed)
    # Use a distinct new revision for a POST change after a changed PRE.
    post = observation(
        expected_before=pre.after_revision, changed=post_changed and not pre_changed
    )
    if post_changed and pre_changed:
        d = post.model_dump()
        d["status"] = "CHANGED"
        d["after_revision"] = {
            **post.after_revision.model_dump(),
            "commit": "e" * 40,
            "blob": "f" * 40,
            "collected_at": post.requested_at,
        }
        post = module.OxidizedObservation.model_validate(d)
    child = build_profiled_observation_record(
        parent, pre, post, generated_at=datetime.now(UTC)
    )
    path = store.persist_profiled_observation_record(child)
    assert path.parent.name == "profiled-observation-records"
    assert path.stat().st_mode & 0o777 == 0o600
    assert store.read_profiled_observation_record(child.observation_record_id) == child
    assert store.find_by_profiled_parent(parent.record_id) == (child,)
    assert store.iter_profiled_observation_records() == (child,)
    assert child.causality == "NOT_PROVEN" and child.overall_status.value == "SUCCEEDED"
    assert post.before_revision == pre.after_revision
    with pytest.raises(ValueError):
        store.persist_profiled_observation_record(child)


@pytest.mark.parametrize(
    "field,value",
    [
        ("observation_record_id", str(UUID(int=1))),
        ("digest", "sha256:" + "0" * 64),
        ("target", "netbox:dcim.device:2"),
        ("oxidized_node", "netbox-device-2"),
        ("relationship", "POST_ONLY"),
        ("causality", "PROVEN"),
        ("overall_status", "FAILED"),
        ("generated_at", "2000-01-01T00:00:00Z"),
        ("group", "other"),
    ],
)
def test_model_contradictions_rejected(stored, field, value):
    _, _, child = stored
    d = child.model_dump(mode="json")
    d[field] = value
    if field != "digest":
        d = rehash(d)
    with pytest.raises(ValueError):
        Record.model_validate(d)


def test_success_requires_exact_pre_after_and_utc_order(stored):
    _, _, child = stored
    for damage in ["baseline", "time", "pre_failed"]:
        d = child.model_dump(mode="json")
        if damage == "baseline":
            for key in ["before_revision", "after_revision"]:
                d["post_observation"][key]["commit"] = "f" * 40
        elif damage == "time":
            d["post_observation"]["requested_at"] = "2000-01-01T00:00:00Z"
        else:
            d["pre_observation"].update(
                status="FAILED",
                after_revision=None,
                failure_category="COLLECTION_FAILED",
            )
        with pytest.raises(ValueError):
            Record.model_validate(rehash(d))


@pytest.mark.parametrize(
    "status,category,overall",
    [
        ("FAILED", "COLLECTION_FAILED", "PARTIAL"),
        ("TIMED_OUT", "COLLECTION_TIMED_OUT", "PARTIAL"),
        ("AMBIGUOUS", "INCONSISTENT_EVIDENCE", "AMBIGUOUS"),
    ],
)
def test_typed_unsuccessful_post_preserved(stored, status, category, overall):
    store, parent, child = stored
    d = child.post_observation.model_dump()
    d.update(status=status, failure_category=category, after_revision=None)
    post = module.OxidizedObservation.model_validate(d)
    child = build_profiled_observation_record(
        parent, child.pre_observation, post, generated_at=datetime.now(UTC)
    )
    store.persist_profiled_observation_record(child)
    assert (
        store.read_profiled_observation_record(
            child.observation_record_id
        ).overall_status.value
        == overall
    )


@pytest.mark.parametrize(
    "damage", ["parent_uuid", "parent_digest", "target", "compliance", "artifact"]
)
def test_parent_revalidation_on_publish_and_read(stored, damage):
    store, parent, child = stored
    d = child.model_dump(mode="json")
    if damage == "parent_uuid":
        d["parent_audit"]["record_id"] = str(UUID(int=99))
        d["observation_record_id"] = str(chronology_id(UUID(int=99)))
    elif damage == "parent_digest":
        d["parent_audit"]["digest"] = "sha256:" + "e" * 64
    elif damage == "target":
        d["target"] = "netbox:dcim.device:2"
        d["oxidized_node"] = "netbox-device-2"
        for a in ["pre_observation", "post_observation"]:
            for r in ["before_revision", "after_revision"]:
                d[a][r]["config_path"] = "managed/netbox-device-2"
    elif damage == "compliance":
        compliant, raw, _ = bundle(store, compliant=True, record_id=UUID(int=55))
        store.persist_profiled_record(compliant, artifact_bytes=raw)
        d["parent_audit"].update(
            record_id=str(compliant.record_id), digest=compliant.digest
        )
        d["observation_record_id"] = str(chronology_id(compliant.record_id))
    else:
        store.persist_profiled_observation_record(child)
        (store.root / parent.artifacts[0].locator).write_bytes(b"{}")
        with pytest.raises(ValueError):
            store.read_profiled_observation_record(child.observation_record_id)
    candidate = Record.model_validate(rehash(d))
    with pytest.raises((ValueError, OSError)):
        store.persist_profiled_observation_record(candidate)


def test_historical_schema_fences_and_optional_namespace(stored):
    store, parent, child = stored
    assert not (store.root / "profiled-observation-records").exists()
    old = {
        str(p.relative_to(store.root)): p.read_bytes()
        for p in store.root.rglob("*")
        if p.is_file()
    }
    readonly = Store(store.root, checkout=store.root.parent / "checkout", create=False)
    assert readonly.iter_profiled_observation_records() == ()
    assert readonly.find_by_profiled_parent(parent.record_id) == ()
    with pytest.raises(ValueError):
        readonly.prepare_profiled_observation_publication(parent.record_id)
    with pytest.raises(ValueError):
        ConfigurationObservationRecord.model_validate(child.model_dump())
    with pytest.raises(ValueError):
        ProfiledDeliveryAuditReference.model_validate(
            ParentAuditReference(record_id=parent.record_id, digest=parent.digest)
        )
    assert old == {
        str(p.relative_to(store.root)): p.read_bytes()
        for p in store.root.rglob("*")
        if p.is_file()
    }


@pytest.mark.parametrize(
    "damage", ["mode", "symlink", "malformed", "identity", "digest", "scan"]
)
def test_store_safety(stored, tmp_path, damage):
    store, _parent, child = stored
    path = store.persist_profiled_observation_record(child)
    if damage == "mode":
        path.parent.chmod(0o755)
    elif damage == "symlink":
        path.unlink()
        path.symlink_to(tmp_path / "missing")
    elif damage == "malformed":
        path.write_bytes(b"{}")
    elif damage == "identity":
        path.rename(path.parent / f"{UUID(int=87)}.json")
    elif damage == "digest":
        path.write_bytes(
            path.read_bytes().replace(
                child.digest.encode(), ("sha256:" + "0" * 64).encode()
            )
        )
    else:
        with pytest.raises(ValueError):
            store.iter_profiled_observation_records(max_scan=0)
        return
    with pytest.raises((ValueError, OSError)):
        store.iter_profiled_observation_records()


def test_capture_node_derivation_does_not_add_admission():
    from network_change_delivery.architecture_contracts import AutomationProfileID

    for profile in [
        AutomationProfileID.CAT8000V_IOSXE,
        AutomationProfileID.VJUNOS_ROUTER,
    ]:
        plan, *_ = planning_result(profile)
        assert (
            canonical_oxidized_node(plan.plan)
            == "netbox-device-" + plan.plan.device_identity.rsplit(":", 1)[1]
        )
    assert module.node_for_target("netbox:dcim.device:99") == "netbox-device-99"
    with pytest.raises(ValueError):
        module.node_for_target("other:99")


@pytest.mark.parametrize(
    "outcome",
    [
        "COLLECTION_FAILED",
        "COLLECTION_TIMED_OUT",
        "CONCURRENT_COLLECTION",
        "INCONSISTENT_EVIDENCE",
    ],
)
def test_capture_closed_controller_failure(outcome):
    from network_change_delivery.oxidized_controller import CollectionOutcome

    before = observation().before_revision
    result = SimpleNamespace(
        outcome=CollectionOutcome(outcome),
        request_id=UUID(int=9),
        requested_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
    )
    controller = SimpleNamespace(collect=lambda _node: result)
    history = SimpleNamespace(latest_revision=lambda _node: before)
    attempt = capture_attempt(controller, history, "netbox-device-1")
    assert attempt.failure_category.value == outcome and attempt.after_revision is None
    assert "secret" not in attempt.model_dump_json()


def test_intervening_history_is_not_silently_rebased():
    pre = observation()
    newer = observation(changed=True).after_revision
    calls = []
    result = capture_attempt(
        SimpleNamespace(collect=lambda _: calls.append("collect")),
        SimpleNamespace(latest_revision=lambda _: newer),
        "netbox-device-1",
        expected_before=pre.after_revision,
    )
    assert result.status is Status.AMBIGUOUS and not calls
    assert result.failure_category is Failure.INCONSISTENT_EVIDENCE


@pytest.mark.parametrize("failure", ["service", "history", "baseline"])
def test_capture_unavailable_plane_is_typed(monkeypatch, failure):
    plan, *_ = planning_result()

    def fail(*_a, **_k):
        raise ValueError("secret-error")

    monkeypatch.setattr(
        module,
        "verified_container_id",
        fail if failure == "service" else lambda: "f" * 64,
    )
    monkeypatch.setattr(
        module, "OxidizedController", lambda *_a, **_k: SimpleNamespace(collect=fail)
    )
    monkeypatch.setattr(
        module,
        "OxidizedHistoryRepository",
        fail
        if failure == "history"
        else lambda *_a: SimpleNamespace(latest_revision=lambda _: None),
    )
    result = capture_profiled_attempt(plan.plan)
    assert (
        result.status is Status.FAILED
        and "secret-error" not in result.model_dump_json()
    )


@pytest.mark.parametrize(
    "damage", ["symlink", "mode", "malformed", "noncanonical", "duplicate"]
)
def test_private_attempt_file_boundaries(tmp_path, damage):
    tmp_path.chmod(0o700)
    p = tmp_path / "pre.json"
    a = observation()
    persist_attempt_file(p, a)
    assert load_attempt_file(p) == a
    if damage == "symlink":
        p.unlink()
        p.symlink_to(tmp_path / "missing")
    elif damage == "mode":
        p.chmod(0o644)
    elif damage == "malformed":
        p.write_text("{}")
    elif damage == "noncanonical":
        p.write_text(a.model_dump_json(indent=2))
    else:
        with pytest.raises(OSError):
            persist_attempt_file(p, a)
        return
    with pytest.raises((OSError, ValueError)):
        load_attempt_file(p)


@pytest.mark.parametrize("changed", [False, True])
def test_capture_success_uses_retained_binding(monkeypatch, changed):
    from network_change_delivery.oxidized_controller import CollectionOutcome

    before = observation().before_revision
    result = SimpleNamespace(
        outcome=CollectionOutcome.SUCCEEDED,
        request_id=UUID(int=80),
        requested_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
    )
    after = (
        module.OxidizedRevision(
            commit="c" * 40,
            blob="d" * 40,
            config_path=before.config_path,
            collected_at=result.requested_at,
        )
        if changed
        else before
    )
    calls = []

    def bind(_history, node, baseline, collection):
        assert baseline == before and collection is result
        calls.append(node)
        return SimpleNamespace(
            settled_at=datetime.now(UTC), revision_changed=changed, after=after
        )

    monkeypatch.setattr(module, "bind_collection_result", bind)
    attempt = capture_attempt(
        SimpleNamespace(collect=lambda _: result),
        SimpleNamespace(latest_revision=lambda _: before),
        "netbox-device-1",
    )
    assert attempt.status.value == ("CHANGED" if changed else "UNCHANGED")
    assert (
        calls == ["netbox-device-1"]
        and attempt.before_revision == before
        and attempt.after_revision == after
    )


def test_capture_binding_inconsistency_remains_ambiguous(monkeypatch):
    from network_change_delivery.oxidized_controller import CollectionOutcome

    before = observation().before_revision
    result = SimpleNamespace(
        outcome=CollectionOutcome.SUCCEEDED,
        request_id=UUID(int=80),
        requested_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
    )

    def bind(*_a):
        raise module.OxidizedChronologyError("private-body")

    monkeypatch.setattr(module, "bind_collection_result", bind)
    attempt = capture_attempt(
        SimpleNamespace(collect=lambda _: result),
        SimpleNamespace(latest_revision=lambda _: before),
        "netbox-device-1",
    )
    assert (
        attempt.status is Status.AMBIGUOUS
        and attempt.failure_category is Failure.INCONSISTENT_EVIDENCE
    )
