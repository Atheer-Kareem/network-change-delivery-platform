"""Offline full coordinator, original child lifecycle and temporary durable stores."""

from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
from profiled_chronology_fixtures import observation
from test_profiled_planning import FakeSecrets
from test_profiled_rollout import NOW
from test_profiled_rollout_admission import fixture

from network_change_delivery import profiled_rollout_execution as run
from network_change_delivery.architecture_contracts import AutomationProfileID
from network_change_delivery.models import ExecutionResult, FinalOutcome
from network_change_delivery.profiled_rollout_audit import (
    ProfiledRolloutAuditRecord,
    ProfiledRolloutChildAuditRecord,
    ProfiledRolloutChronologyRecord,
)
from network_change_delivery.profiled_rollout_audit_store import (
    ProfiledRolloutAuditStore,
)
from network_change_delivery.profiled_rollout_reservation import reserve_rollout_devices
from network_change_delivery.profiled_write_adapter import ProfiledWriteAdapter


@pytest.fixture
def execution(tmp_path, monkeypatch):
    f = fixture()
    root, state, directory = (tmp_path / n for n in ("audit", "state", "private"))
    for p in (root, state, directory):
        p.mkdir(mode=0o700)
    store = ProfiledRolloutAuditStore(root, checkout=Path.cwd())
    calls = []
    originals = []
    originals_execute = run.execute_profiled_plan

    def execute(plan, *args):
        originals.append(plan)
        return originals_execute(plan, *args, now=lambda: NOW + timedelta(seconds=1))

    monkeypatch.setattr(run, "execute_profiled_plan", execute)

    def capture(plan, *, expected_before=None):
        o = observation(expected_before=expected_before)
        if expected_before is None:
            data = o.model_dump()
            for key in ("before_revision", "after_revision"):
                data[key]["config_path"] = (
                    "managed/netbox-device-" + plan.device_identity.rsplit(":", 1)[1]
                )
            o = type(o).model_validate(data)
        return o

    monkeypatch.setattr(run, "capture_profiled_attempt", capture)

    def changed(target):
        calls.append(target.device_identity)
        f.collector.compliant = (*f.collector.compliant, target.name)
        return ExecutionResult(disposition="SUCCEEDED", changed=True, message="offline")

    class Cisco:
        def verify_runtime(self):
            pass

        def execute_profiled(self, target, *_):
            return changed(target)

    class Junos:
        @contextmanager
        def profiled_transaction(self, target, *_):
            class Transaction:
                close_failed = False

                def prepare(self):
                    return SimpleNamespace(diff_sha256="sha256:" + "a" * 64)

                def commit_confirmed(self, _minutes):
                    return changed(target)

            yield Transaction()

        def confirm_profiled(self, *_):
            return ExecutionResult(
                disposition="SUCCEEDED", changed=False, message="confirmed"
            )

    writer = ProfiledWriteAdapter(
        known_hosts=tmp_path / "unused", cisco=Cisco(), junos=Junos()
    )
    args = dict(
        f.args,
        store=store,
        state_root=state,
        directory=directory,
        pipeline_id="00000000-0000-4000-8000-000000000004",
        build_number=466,
        inventory=f.inventory,
        credential_authority=f.authority,
        secrets=FakeSecrets(),
        collector=f.collector,
        writer_factory=lambda: writer,
    )
    return SimpleNamespace(
        f=f, args=args, store=store, calls=calls, originals=originals
    )


def test_four_real_child_lifecycles_original_bytes_durable_chronology(execution):
    e = execution
    result = run.execute_rollout(**e.args)
    assert result.outcome == "SUCCEEDED", result
    assert e.calls == ["netbox:dcim.device:" + str(i) for i in (1, 2, 8, 9)]
    assert len(result.child_records) == len(result.chronology_records) == 4
    assert result.final_validation_status == "PASSED"
    assert e.originals == [c.result() for c in e.f.parent.children]
    for child in e.f.parent.children:
        assert (
            e.store.read_bytes("child", child.artifact_digest) == child.artifact_bytes()
        )
    assert (
        e.store.read_rollout_record(ProfiledRolloutAuditRecord, result.record_id)
        == result
    )
    for ref in result.chronology_records:
        c = e.store.read_rollout_record(ProfiledRolloutChronologyRecord, ref.record_id)
        assert c.causality == "NOT_PROVEN" and c.overall_status == "SUCCEEDED"
    with reserve_rollout_devices(e.args["state_root"], tuple(e.calls)):
        pass


@pytest.mark.parametrize("stop", range(4))
def test_escaping_child_exception_stops_without_retry(execution, monkeypatch, stop):
    e = execution
    original = run.execute_profiled_plan
    count = []

    def fail(plan, *args):
        count.append(plan.device_identity)
        if len(count) == stop + 1:
            raise RuntimeError("unknown after child boundary")
        return original(plan, *args)

    monkeypatch.setattr(run, "execute_profiled_plan", fail)
    result = run.execute_rollout(**e.args)
    assert len(count) == stop + 1 and len(e.calls) == stop
    assert result.outcome == ("STOPPED" if stop == 0 else "PARTIAL")
    assert result.stopping_reason == "CHILD_EXECUTION_UNCERTAIN"
    assert len(result.untouched) == 3 - stop


def test_complete_preflight_failure_zero_children(execution):
    e = execution
    e.f.collector.fail = "access-sw-01"
    result = run.execute_rollout(**e.args)
    assert result.outcome == "STOPPED" and result.stopping_reason == "PREFLIGHT"
    assert not e.calls and not result.attempted and len(result.untouched) == 4


def test_shared_reservation_conflict_before_provider_activity(execution):
    e = execution
    e.f.collector.calls.clear()
    with (
        reserve_rollout_devices(e.args["state_root"], ("netbox:dcim.device:1",)),
        pytest.raises(ValueError),
    ):
        run.execute_rollout(**e.args)
    assert not e.f.collector.calls and not e.calls


@pytest.mark.parametrize("kind", ["child", "chronology", "parent"])
def test_evidence_failure_never_replays_or_exposes_later_child(
    execution, monkeypatch, kind
):
    e = execution
    original = e.store.persist_rollout_record
    model = {
        "child": ProfiledRolloutChildAuditRecord,
        "chronology": ProfiledRolloutChronologyRecord,
        "parent": ProfiledRolloutAuditRecord,
    }[kind]

    def fail(record):
        if isinstance(record, model):
            raise OSError("offline evidence failure")
        return original(record)

    monkeypatch.setattr(e.store, "persist_rollout_record", fail)
    if kind == "parent":
        with pytest.raises(OSError):
            run.execute_rollout(**e.args)
        assert len(e.calls) == 4
    else:
        result = run.execute_rollout(**e.args)
        assert (
            result.outcome == "PARTIAL" and result.stopping_reason == "CHILD_EVIDENCE"
        )
        assert len(e.calls) == 1


def test_audit_readiness_collision_prevents_all_activity(execution):
    e = execution
    e.store.prepare_rollout(UUID(e.args["context"].job_id), e.f.parent)
    path = e.store.root / "rollout-records" / (e.args["context"].job_id + ".json")
    path.write_text("{}")
    e.f.collector.calls.clear()
    with pytest.raises(ValueError):
        run.execute_rollout(**e.args)
    assert not e.calls and not e.f.collector.calls


def test_final_observation_failure_never_rolls_back(execution, monkeypatch):
    e = execution
    original = run.validate_rollout_final_state

    def fail(*args, **kwargs):
        e.f.collector.fail = "access-sw-01"
        return original(*args, **kwargs)

    monkeypatch.setattr(run, "validate_rollout_final_state", fail)
    result = run.execute_rollout(**e.args)
    assert result.outcome == "FINAL_VALIDATION_FAILED"
    assert len(e.calls) == 4 and result.final_validation_status == "FAILED"


def test_jit_stale_after_complete_preflight_stops_without_forward(
    execution, monkeypatch
):
    e = execution
    original = run.execute_profiled_plan

    def stale(plan, *args):
        e.f.collector.compliant = (plan.target,)
        return original(plan, *args)

    monkeypatch.setattr(run, "execute_profiled_plan", stale)
    result = run.execute_rollout(**e.args)
    assert result.outcome == "STOPPED" and not e.calls
    assert result.stopping_outcome in {FinalOutcome.BLOCKED, FinalOutcome.STALE_PLAN}
    assert len(result.attempted) == 1 and len(result.untouched) == 3


@pytest.mark.parametrize("boundary", ["pre", "post"])
def test_chronology_failure_stops_exposure(execution, monkeypatch, boundary):
    e = execution
    original = run.capture_profiled_attempt

    def fail(plan, **kwargs):
        if ("expected_before" in kwargs) == (boundary == "post"):
            raise ValueError("offline chronology unavailable")
        return original(plan, **kwargs)

    monkeypatch.setattr(run, "capture_profiled_attempt", fail)
    result = run.execute_rollout(**e.args)
    assert result.outcome == ("PARTIAL" if boundary == "post" else "STOPPED")
    assert len(e.calls) == (1 if boundary == "post" else 0)


def test_viewer_rollout_metadata_only(execution):
    from network_change_delivery.configuration_observation_store import (
        ConfigurationObservationStore,
    )
    from network_change_delivery.evidence_viewer import EvidenceViewerApplication

    e = execution
    record = run.execute_rollout(**e.args)
    ConfigurationObservationStore(e.store.root, checkout=Path.cwd())
    viewer = EvidenceViewerApplication(
        ConfigurationObservationStore(e.store.root, checkout=Path.cwd(), create=False)
    )
    status, content = viewer.get("/")
    assert status == 200 and b"rollout-records/" in content
    status, content = viewer.get("/rollout-records/" + str(record.record_id))
    assert status == 200 and b"SUCCEEDED" in content and b"NOT_PROVEN" in content
    assert b"netbox:dcim.device:9" in content
    for forbidden in (
        b"test-user",
        b"test-password",
        b"artifact_json",
        b"credential_reference",
        b"openbao:",
    ):
        assert forbidden not in content


def test_original_byte_tampering_rejected_by_store(execution):
    e = execution
    result = run.execute_rollout(**e.args)
    child = e.f.parent.children[0]
    path = (
        e.store.root
        / "rollout-artifact-bytes"
        / "child"
        / (child.artifact_digest[7:] + ".json")
    )
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError):
        e.store.read_rollout_record(ProfiledRolloutAuditRecord, result.record_id)


@pytest.mark.parametrize("stop_index", [0, 2, 3])
@pytest.mark.parametrize("outcome", ["EXECUTION_FAILED", "AMBIGUOUS", "RECOVERED"])
def test_real_child_non_success_never_advances(
    execution, monkeypatch, stop_index, outcome
):
    from test_profiled_execution import Cisco, Collector, writer
    from test_profiled_planning import observed

    from network_change_delivery.profiled_execution import execute_profiled_plan

    e = execution
    original = run.execute_profiled_plan
    stopped = e.f.parent.children[stop_index]
    cisco_calls = []

    def controlled(plan, *args):
        if plan.device_identity != stopped.device.device_identity:
            return original(plan, *args)
        state = observed(stopped.device, stopped.interface, description="previous")
        results = [
            ExecutionResult(
                disposition="SUCCEEDED"
                if outcome == "RECOVERED"
                else "AMBIGUOUS"
                if outcome == "AMBIGUOUS"
                else "FAILED",
                message="offline",
            )
        ]
        if outcome == "RECOVERED":
            results.append(ExecutionResult(disposition="SUCCEEDED", message="inverse"))
        cisco = Cisco(results)
        record = execute_profiled_plan(
            plan,
            plan.digest,
            e.f.inventory,
            e.args["secrets"],
            Collector([state, state, state]),
            writer(cisco),
            now=lambda: NOW + timedelta(seconds=1),
        )
        cisco_calls.extend(cisco.artifacts)
        return record

    monkeypatch.setattr(run, "execute_profiled_plan", controlled)
    record = run.execute_rollout(**e.args)
    assert record.stopping_outcome.value == outcome
    assert record.outcome == ("STOPPED" if stop_index == 0 else "PARTIAL")
    assert len(record.attempted) == stop_index + 1 and len(e.calls) == stop_index
    assert len(cisco_calls) == (2 if outcome == "RECOVERED" else 1)
    if outcome == "RECOVERED":
        assert cisco_calls[1] == stopped.result().recovery_artifact


@pytest.mark.parametrize(
    "confirmation", ["FAILED", "AMBIGUOUS", "AUTO_ROLLBACK_PENDING"]
)
def test_junos_confirmation_non_success_stops_before_waves(
    execution, monkeypatch, confirmation
):
    from test_profiled_execution import Collector, Junos, writer
    from test_profiled_planning import observed

    from network_change_delivery.profiled_execution import execute_profiled_plan

    e = execution
    original = run.execute_profiled_plan
    child = e.f.parent.children[1]
    junos = Junos(
        ExecutionResult(disposition="SUCCEEDED", changed=True, message="commit"),
        ExecutionResult(
            disposition="FAILED"
            if confirmation == "AUTO_ROLLBACK_PENDING"
            else confirmation,
            message="confirm",
        ),
    )

    def controlled(plan, *args):
        if plan.device_identity != child.device.device_identity:
            return original(plan, *args)
        state = observed(child.device, child.interface, description="previous")
        return execute_profiled_plan(
            plan,
            plan.digest,
            e.f.inventory,
            e.args["secrets"],
            Collector(
                [
                    state,
                    state
                    if confirmation == "AUTO_ROLLBACK_PENDING"
                    else state.model_copy(update={"description": "NEW"}),
                ]
            ),
            writer(junos=junos),
            now=lambda: NOW + timedelta(seconds=1),
        )

    monkeypatch.setattr(run, "execute_profiled_plan", controlled)
    record = run.execute_rollout(**e.args)
    assert record.outcome == "PARTIAL" and len(record.attempted) == 2
    assert record.stopping_outcome.value == (
        "AUTO_ROLLBACK_PENDING"
        if confirmation == "AUTO_ROLLBACK_PENDING"
        else "CONFIRMATION_" + confirmation
    )
    assert junos.commits == 1
    assert junos.confirms == (0 if confirmation == "AUTO_ROLLBACK_PENDING" else 1)
    assert record.untouched == ("netbox:dcim.device:8", "netbox:dcim.device:9")


def test_mixed_population_reserves_and_final_validates_compliant_member(execution):
    e = execution
    names = ("core-02",)
    new = fixture(compliant=names)
    e.args.update(new.args)
    e.f.collector.compliant = names
    e.f.parent = new.parent
    record = run.execute_rollout(**e.args)
    assert record.outcome == "SUCCEEDED"
    assert record.compliant == ("netbox:dcim.device:1",)
    assert "netbox:dcim.device:1" not in e.calls
    assert len(e.calls) == len(record.chronology_records) == 3
    final = e.store.find_model("final", record.final_validation_digest)
    assert len(final.observations) == 4


@pytest.mark.parametrize(
    "fault", ["description", "profile", "endpoint", "credential", "hostname"]
)
def test_final_validation_requires_complete_frozen_d1(execution, monkeypatch, fault):
    e = execution
    original = run.validate_rollout_final_state

    def broken(*args, **kwargs):
        if fault == "description":
            e.f.collector.compliant = tuple(
                n for n in e.f.collector.compliant if n != "access-sw-01"
            )
        elif fault == "credential":
            monkeypatch.setattr(
                e.args["secrets"],
                "load",
                lambda *_: (_ for _ in ()).throw(ValueError("unavailable")),
            )
        else:
            device, interface = e.f.inventory.pairs["access-sw-01"]
            field, value = {
                "profile": (
                    "automation_profile_id",
                    AutomationProfileID.CAT8000V_IOSXE,
                ),
                "endpoint": (
                    "management_endpoints",
                    device.management_endpoints.model_copy(
                        update={"logical_device": "netbox:dcim.device:99"}
                    ),
                ),
                "hostname": ("expected_hostname", "wrong"),
            }[fault]
            e.f.inventory.pairs["access-sw-01"] = (
                device.model_copy(update={field: value}),
                interface,
            )
        return original(*args, **kwargs)

    monkeypatch.setattr(run, "validate_rollout_final_state", broken)
    record = run.execute_rollout(**e.args)
    assert record.outcome == "FINAL_VALIDATION_FAILED" and len(e.calls) == 4


@pytest.mark.parametrize(
    "damage",
    ["child-digest", "cohort", "duplicate-chronology", "outcome", "final-digest"],
)
def test_parent_store_rejects_rehashed_detached_evidence(execution, damage):
    from network_change_delivery.profiled_configuration_observation import _signed

    e = execution
    record = run.execute_rollout(**e.args)
    values = record.model_dump(exclude={"digest"})
    if damage == "child-digest":
        values["children"][0]["artifact_digest"] = "sha256:" + "0" * 64
    elif damage == "cohort":
        child = e.store.read_rollout_record(
            ProfiledRolloutChildAuditRecord, record.child_records[0].record_id
        )
        wrong = _signed(
            ProfiledRolloutChildAuditRecord,
            {**child.model_dump(exclude={"digest"}), "execution_order": 1},
        )
        with pytest.raises(ValueError):
            e.store.persist_rollout_record(wrong)
        return
    elif damage == "duplicate-chronology":
        values["chronology_records"] = (values["chronology_records"][0],) * 4
    elif damage == "outcome":
        values["final_validation_status"] = "FAILED"
    else:
        values["final_validation_digest"] = "sha256:" + "0" * 64
    with pytest.raises(ValueError):
        e.store.persist_rollout_record(_signed(ProfiledRolloutAuditRecord, values))


def test_final_module_has_no_writer_import():
    import ast

    from network_change_delivery import profiled_rollout_final_validation

    source = Path(profiled_rollout_final_validation.__file__).read_text()
    tree = ast.parse(source)
    imports = [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
    assert not any(
        "execution" in (n or "") or "write_adapter" in (n or "") for n in imports
    )
    assert "execute_profiled_plan" not in source


def test_execution_uncertainty_survives_later_post_failure(execution, monkeypatch):
    e = execution
    original = run.capture_profiled_attempt

    def fail_post(plan, **kwargs):
        if kwargs:
            raise ValueError("POST unavailable")
        return original(plan)

    def fail_execution(*_args):
        raise RuntimeError("execution escaped")

    monkeypatch.setattr(run, "capture_profiled_attempt", fail_post)
    monkeypatch.setattr(run, "execute_profiled_plan", fail_execution)
    record = run.execute_rollout(**e.args)
    assert record.outcome == "STOPPED"
    assert record.stopping_reason == "CHILD_EXECUTION_UNCERTAIN"
    assert len(record.attempted) == 1 and len(record.untouched) == 3
    assert not e.calls
