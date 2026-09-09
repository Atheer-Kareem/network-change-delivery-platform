"""Unmerged rollout evidence truth; every provider/store is a double/temp store."""

from pathlib import Path

import pytest
from test_profiled_rollout_execution import execution as execution_fixture

from network_change_delivery import profiled_rollout_execution as run
from network_change_delivery.configuration_observation import ObservationStatus
from network_change_delivery.configuration_observation_store import (
    ConfigurationObservationStore,
)
from network_change_delivery.evidence_viewer import EvidenceViewerApplication
from network_change_delivery.profiled_configuration_observation import _signed
from network_change_delivery.profiled_rollout_audit import (
    ProfiledRolloutAuditRecord,
    ProfiledRolloutChildAuditRecord,
    child_record_id,
)


@pytest.fixture
def execution(tmp_path, monkeypatch):
    return execution_fixture.__wrapped__(tmp_path, monkeypatch)


def stopped(e, monkeypatch, failure, index=2):
    original = run.execute_profiled_plan
    capture = run.capture_profiled_attempt
    target = e.f.parent.children[index].device.device_identity

    def execute(plan, *args):
        if plan.device_identity == target:
            if failure == "uncertain":
                raise RuntimeError("unknown child call")
            if failure == "jit":
                e.f.collector.compliant = (*e.f.collector.compliant, plan.target)
        return original(plan, *args)

    def observe(plan, **kwargs):
        if plan.device_identity == target and (
            (failure == "pre" and not kwargs) or (failure == "post" and kwargs)
        ):
            raise ValueError("chronology unavailable")
        return capture(plan, **kwargs)

    monkeypatch.setattr(run, "execute_profiled_plan", execute)
    monkeypatch.setattr(run, "capture_profiled_attempt", observe)
    return run.execute_rollout(**e.args)


@pytest.mark.parametrize(
    "kind,expected", [("success", True), ("jit", False), ("uncertain", None)]
)
def test_write_truth_and_independent_store_verification(
    execution, monkeypatch, kind, expected
):
    e = execution
    record = stopped(e, monkeypatch, kind, index=0)
    child = e.store.read_rollout_record(
        ProfiledRolloutChildAuditRecord, record.child_records[0].record_id
    )
    assert child.child_lifecycle_entered is True
    assert child.write_attempted is expected
    assert isinstance(child.pre_status, ObservationStatus)
    assert isinstance(child.post_status, ObservationStatus)
    assert "execution_attempted" not in child.model_dump()
    values = child.model_dump(exclude={"digest"})
    for wrong in (True, False, None):
        if wrong is expected:
            continue
        message = (
            "rollout execution outcome mismatch"
            if wrong is not None and expected is not None
            else "rollout child correlation rejected"
        )
        with pytest.raises(ValueError, match=message):
            e.store.persist_rollout_record(
                _signed(
                    ProfiledRolloutChildAuditRecord,
                    {**values, "write_attempted": wrong},
                )
            )
    if expected is None:
        assert child.execution_digest is child.final_outcome is None
    elif expected is False:
        assert child.final_outcome.value in {"STALE_PLAN", "BLOCKED"}
        assert not e.calls


@pytest.mark.parametrize("failure", ["pre", "jit", "uncertain"])
@pytest.mark.parametrize(
    "damage",
    [
        "earlier-child",
        "earlier-chronology",
        "child-order",
        "chronology-order",
        "unattempted",
        "stopping-child",
        "stopping-chronology",
    ],
)
def test_rehashed_partial_prefix_gaps_rejected(execution, monkeypatch, failure, damage):
    e = execution
    record = stopped(e, monkeypatch, failure)
    assert record.outcome == "PARTIAL" and record.child_evidence_complete
    assert record.evidence_failed is False
    values = record.model_dump(exclude={"digest"})
    if damage == "earlier-child":
        values["child_records"] = values["child_records"][1:]
    elif damage == "earlier-chronology":
        values["chronology_records"] = values["chronology_records"][1:]
    elif damage == "child-order":
        values["child_records"] = values["child_records"][::-1]
    elif damage == "chronology-order":
        values["chronology_records"] = values["chronology_records"][::-1]
    elif damage == "unattempted":
        values["child_records"][-1]["record_id"] = child_record_id(
            record.record_id, "netbox:dcim.device:9"
        )
    elif damage == "stopping-child":
        values["child_records"] = values["child_records"][:-1]
        values["chronology_records"] = values["chronology_records"][:-1]
    else:
        values["chronology_records"] = values["chronology_records"][:-1]
    # Rehashing and even claiming incompleteness cannot excuse unexplained gaps.
    values["child_evidence_complete"] = damage in {
        "child-order",
        "chronology-order",
        "unattempted",
    }
    with pytest.raises(ValueError):
        e.store.persist_rollout_record(_signed(ProfiledRolloutAuditRecord, values))


@pytest.mark.parametrize("failure", ["jit", "uncertain"])
def test_rehashed_stopped_parent_cannot_omit_stopping_evidence(
    execution, monkeypatch, failure
):
    e = execution
    record = stopped(e, monkeypatch, failure, index=0)
    assert record.outcome == "STOPPED"
    for field in ("child_records", "chronology_records"):
        values = record.model_dump(exclude={"digest"})
        values[field] = ()
        values["child_evidence_complete"] = False
        with pytest.raises(ValueError):
            e.store.persist_rollout_record(_signed(ProfiledRolloutAuditRecord, values))


@pytest.mark.parametrize("fault", ["child", "chronology", "final-model"])
def test_all_child_success_evidence_failure_is_not_partial(
    execution, monkeypatch, fault
):
    e = execution
    persist = e.store.persist_rollout_record
    put = e.store.put_model

    def fail_record(record):
        if len(e.calls) == 4 and (
            (
                fault == "child"
                and record.record_type == "profiled_rollout_child_audit_record"
            )
            or (
                fault == "chronology"
                and record.record_type == "profiled_rollout_chronology_record"
            )
        ):
            raise OSError("final child evidence failed")
        return persist(record)

    def fail_model(kind, value):
        if fault == "final-model" and kind == "final":
            raise OSError("final validation storage failed")
        return put(kind, value)

    monkeypatch.setattr(e.store, "persist_rollout_record", fail_record)
    monkeypatch.setattr(e.store, "put_model", fail_model)
    record = run.execute_rollout(**e.args)
    assert record.outcome == "EVIDENCE_FAILED"
    assert record.evidence_failed is True
    assert record.child_evidence_complete is (fault == "final-model")
    assert len(record.successful) == len(e.calls) == len(set(e.calls)) == 4
    assert not record.untouched
    assert (
        e.store.read_rollout_record(ProfiledRolloutAuditRecord, record.record_id)
        == record
    )
    for wrong in ("SUCCEEDED", "PARTIAL", "FINAL_VALIDATION_FAILED"):
        with pytest.raises(ValueError):
            _signed(
                ProfiledRolloutAuditRecord,
                {**record.model_dump(exclude={"digest"}), "outcome": wrong},
            )


def test_uncertainty_and_later_publication_failure_both_preserved(
    execution, monkeypatch
):
    e = execution
    persist = e.store.persist_rollout_record

    def fail_last(record):
        if (
            isinstance(record, ProfiledRolloutChildAuditRecord)
            and record.execution_order == 2
        ):
            raise OSError("uncertain child evidence could not publish")
        return persist(record)

    monkeypatch.setattr(e.store, "persist_rollout_record", fail_last)
    record = stopped(e, monkeypatch, "uncertain")
    assert record.stopping_reason == "CHILD_EXECUTION_UNCERTAIN"
    assert record.evidence_failed and not record.child_evidence_complete
    assert len(record.child_records) == len(record.chronology_records) == 2
    assert len(record.attempted) == 3 and len(e.calls) == 2
    # Even a recorded evidence failure cannot excuse an earlier missing reference.
    values = record.model_dump(exclude={"digest"})
    values["child_records"] = values["child_records"][1:]
    with pytest.raises(ValueError):
        e.store.persist_rollout_record(_signed(ProfiledRolloutAuditRecord, values))


def test_viewer_provenance_and_distinct_digest_labels(execution):
    e = execution
    record = run.execute_rollout(**e.args)
    ConfigurationObservationStore(e.store.root, checkout=Path.cwd())
    viewer = EvidenceViewerApplication(
        ConfigurationObservationStore(e.store.root, checkout=Path.cwd(), create=False)
    )
    status, index = viewer.get("/")
    assert status == 200
    assert b"<dt>Provenance</dt><dd>Current profiled rollout delivery</dd>" in index
    assert b"Historical protected delivery" not in index
    status, detail = viewer.get("/rollout-records/" + str(record.record_id))
    assert status == 200 and record.parent_digest != record.digest
    assert f"<dt>Parent digest</dt><dd>{record.parent_digest}</dd>".encode() in detail
    assert f"<dt>Rollout record digest</dt><dd>{record.digest}</dd>".encode() in detail
    assert b"Child lifecycles entered (not a write count)" in detail
    for secret in (
        b"test-user",
        b"test-password",
        b"artifact_json",
        b"credential_reference",
        b"openbao:",
    ):
        assert secret not in detail + index


@pytest.mark.parametrize(
    "field,value",
    [
        ("pre_status", "arbitrary"),
        ("post_status", "arbitrary"),
        ("child_lifecycle_entered", False),
        ("execution_attempted", True),
    ],
)
def test_child_statuses_and_lifecycle_are_closed(execution, field, value):
    e = execution
    record = run.execute_rollout(**e.args)
    child = e.store.read_rollout_record(
        ProfiledRolloutChildAuditRecord, record.child_records[0].record_id
    )
    with pytest.raises(ValueError):
        ProfiledRolloutChildAuditRecord.model_validate(
            {**child.model_dump(), field: value}
        )
