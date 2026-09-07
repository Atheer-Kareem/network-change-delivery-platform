"""Offline trusted delivery publication: real current models, temporary stores only."""

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
from profiled_audit_fixtures import execution_artifacts, raw_bytes
from test_profiled_buildkite_delivery import context as context_fixture
from test_profiled_buildkite_delivery import driver as driver_fixture
from test_profiled_compliance_delivery import offline as offline_fixture
from test_profiled_compliance_delivery import planning

from network_change_delivery.audit import AuditArtifactKind as Kind
from network_change_delivery.audit_store import AuditStore, AuditStoreError
from network_change_delivery.models import FinalOutcome
from network_change_delivery.profiled_audit import (
    DURABLE_PUBLICATION_METADATA,
    ProfiledDurablePublicationReceipt,
)
from network_change_delivery.profiled_execution import ProfiledChangeRecord
from network_change_delivery.profiled_promotion import (
    VALIDATION_KEYS,
    validation_receipt,
)

context = context_fixture
driver = driver_fixture
offline = offline_fixture


def fail(*_a, **_k):
    raise ValueError("private-failure-path-secret")


@pytest.fixture
def delivery(driver, context, offline, monkeypatch, tmp_path):
    artifacts, metadata, annotations = offline
    values = execution_artifacts()
    plan = values[Kind.PROFILED_DEPLOYMENT_PLAN]
    promotion = values[Kind.PROFILED_PROMOTION]
    raw = {kind: raw_bytes(model) for kind, model in values.items()}
    for step, kind, name in (
        ("profiled-live-plan", Kind.PROFILED_DEPLOYMENT_PLAN, "plan"),
        ("profiled-promotion", Kind.PROFILED_PROMOTION, "promotion"),
    ):
        artifacts[(context.build_id, step, driver.artifact_name(context, name))] = raw[
            kind
        ]
    metadata[(context.build_id, driver.PLANNING_METADATA)] = (
        driver.ProfiledPlanningPublication(
            build_id=context.build_id,
            commit=context.commit,
            artifact_kind="plan",
            artifact_digest=driver.digest_bytes(raw[Kind.PROFILED_DEPLOYMENT_PLAN]),
            result_digest=plan.digest,
        ).model_dump_json()
    )
    metadata[(context.build_id, driver.PROMOTION_METADATA)] = promotion.digest
    for key in VALIDATION_KEYS:
        metadata[(context.build_id, "profiled-validation-" + key)] = validation_receipt(
            context.build_id, context.commit, key
        )
    metadata[(context.build_id, driver.BATFISH_METADATA)] = promotion.batfish_digest
    metadata[(context.build_id, driver.CML_METADATA)] = promotion.cml_digest
    monkeypatch.setenv("BUILDKITE_UNBLOCKER_ID", context.job_id)
    events, commands = [], []

    class TracedStore(AuditStore):
        def prepare_profiled_publication(self, *args):
            events.append("prepare")
            return super().prepare_profiled_publication(*args)

        def persist_artifact(self, kind, value):
            events.append(kind.value)
            return super().persist_artifact(kind, value)

        def persist_profiled_record(self, *args, **kwargs):
            events.append("envelope")
            return super().persist_profiled_record(*args, **kwargs)

        def read_profiled_record(self, *args):
            events.append("readback")
            return super().read_profiled_record(*args)

    monkeypatch.setattr(driver, "AuditStore", TracedStore)
    publisher = driver.publish_metadata

    def publish(ctx, key, value):
        if key == DURABLE_PUBLICATION_METADATA:
            events.append("receipt")
        publisher(ctx, key, value)

    monkeypatch.setattr(driver, "publish_metadata", publish)
    attempt = SimpleNamespace(returncode=0)

    def command(args, **kwargs):
        assert kwargs == {"device_authority": True}
        assert events[:3] == [
            "prepare",
            "profiled_deployment_plan",
            "profiled_promotion",
        ]
        events.append("command")
        commands.append(args)
        Path(args[args.index("--report-json") + 1]).write_bytes(
            raw[Kind.PROFILED_CHANGE_RECORD]
        )
        return attempt

    monkeypatch.setattr(driver, "command", command)
    directory = tmp_path / "deploy"
    directory.mkdir(mode=0o700)
    return SimpleNamespace(
        values=values,
        raw=raw,
        events=events,
        commands=commands,
        directory=directory,
        attempt=attempt,
        store_type=TracedStore,
        root=Path(driver.os.environ["NCDP_AUDIT_STORE_ROOT"]),
        artifacts=artifacts,
        metadata=metadata,
        annotations=annotations,
    )


def final(driver, context, tmp_path):
    directory = tmp_path / "final"
    directory.mkdir(mode=0o700)
    return driver.evidence_step(
        replace(
            context,
            step="profiled-deployment-evidence",
            job_id="77777777-7777-4777-8777-777777777777",
        ),
        directory,
    )


@pytest.mark.parametrize("changed", [True, False, None])
def test_execution_durable_order_exact_bytes_and_final_pointer(
    driver,
    context,
    delivery,
    tmp_path,
    changed,
    monkeypatch,
):
    data = delivery.values[Kind.PROFILED_CHANGE_RECORD].model_dump(mode="json")
    data["execution"]["changed"] = changed
    delivery.raw[Kind.PROFILED_CHANGE_RECORD] = raw_bytes(
        ProfiledChangeRecord.model_validate(data)
    )
    assert driver.deploy_step(context, delivery.directory) == 0
    assert delivery.events == [
        "prepare",
        "profiled_deployment_plan",
        "profiled_promotion",
        "command",
        "profiled_change_record",
        "envelope",
        "readback",
        "receipt",
        "readback",
    ]
    assert len(delivery.commands) == 1
    store = AuditStore(delivery.root, checkout=driver.ROOT, create=False)
    record = store.read_profiled_record(UUID(context.job_id))
    assert record.record_id == record.buildkite.job_id == UUID(context.job_id)
    assert record.authorization.unblocker_id == UUID(context.job_id)
    for kind, digest in record.byte_digests_by_kind().items():
        assert (
            delivery.root
            / "profiled-artifact-bytes"
            / kind.value
            / f"{digest[7:]}.json"
        ).read_bytes() == delivery.raw[kind]
    # Validation queue must not receive or open AuditStore.
    monkeypatch.delenv("NCDP_AUDIT_STORE_ROOT")
    monkeypatch.setattr(driver, "AuditStore", fail)
    assert final(driver, context, tmp_path) == 0
    message = delivery.annotations[-1][1]
    assert str(record.record_id) in message and record.digest in message
    assert "Write attempted: True" in message and "Outcome: SUCCEEDED" in message
    assert str(delivery.root) not in message and "openbao:" not in message


@pytest.mark.parametrize(
    "damage",
    [
        "missing",
        "invalid",
        "inside",
        "mode",
        "symlink",
        "namespace",
        "initialization",
        "prepare",
        "plan",
        "promotion",
        "duplicate",
        "correlation",
    ],
)
def test_durable_admission_failure_prevents_device_command(
    driver,
    context,
    delivery,
    monkeypatch,
    damage,
):
    if damage == "missing":
        monkeypatch.delenv("NCDP_AUDIT_STORE_ROOT")
    elif damage == "invalid":
        monkeypatch.setenv("NCDP_AUDIT_STORE_ROOT", "relative")
    elif damage == "inside":
        monkeypatch.setattr(driver, "ROOT", delivery.root)
        monkeypatch.setattr(driver, "verify_human_dependency", lambda: None)
    elif damage == "mode":
        delivery.root.chmod(0o755)
    elif damage == "symlink":
        link = delivery.root.parent / "linked"
        link.symlink_to(delivery.root)
        monkeypatch.setenv("NCDP_AUDIT_STORE_ROOT", str(link))
    elif damage == "namespace":
        (delivery.root / "profiled-records").symlink_to(delivery.root)
    elif damage == "initialization":
        monkeypatch.setattr(driver, "AuditStore", fail)
    elif damage == "prepare":
        monkeypatch.setattr(delivery.store_type, "prepare_profiled_publication", fail)
    elif damage in {"plan", "promotion"}:
        original = delivery.store_type.persist_artifact

        def persist(store, kind, value):
            if kind == (
                Kind.PROFILED_DEPLOYMENT_PLAN
                if damage == "plan"
                else Kind.PROFILED_PROMOTION
            ):
                fail()
            return original(store, kind, value)

        monkeypatch.setattr(delivery.store_type, "persist_artifact", persist)
    elif damage == "duplicate":
        destination = delivery.root / "profiled-records"
        destination.mkdir(mode=0o700)
        (destination / f"{context.job_id}.json").write_bytes(b"existing")
    elif damage == "correlation":
        monkeypatch.setenv("BUILDKITE_BUILD_NUMBER", "invalid")
    assert driver.deploy_step(context, delivery.directory) == 2
    assert not delivery.commands
    assert "NO WRITE" in delivery.annotations[-1][1]
    assert "private-failure" not in repr(delivery.annotations)


@pytest.mark.parametrize(
    "fault",
    [
        "upload",
        "execution",
        "source_bytes",
        "envelope",
        "readback",
        "receipt_upload",
        "receipt",
        "annotation",
    ],
)
@pytest.mark.parametrize("returncode", [0, 17])
def test_post_command_failures_never_replay_or_hide_primary_exit(
    driver,
    context,
    delivery,
    monkeypatch,
    fault,
    returncode,
):
    delivery.attempt.returncode = returncode
    if fault in {"upload", "receipt_upload"}:
        original = driver.upload

        def upload(c, d, name):
            if name.endswith(
                "-record.json" if fault == "upload" else "-durable-publication.json"
            ):
                fail()
            original(c, d, name)

        monkeypatch.setattr(driver, "upload", upload)
    elif fault == "execution":
        original = delivery.store_type.persist_artifact

        def persist(store, kind, value):
            if kind == Kind.PROFILED_CHANGE_RECORD:
                fail()
            return original(store, kind, value)

        monkeypatch.setattr(delivery.store_type, "persist_artifact", persist)
    elif fault in {"source_bytes", "envelope"}:
        original = AuditStore._publish_new

        def publish(directory, name, content):
            if (fault == "envelope" and directory.name == "profiled-records") or (
                fault == "source_bytes"
                and directory.parent.name == "profiled-artifact-bytes"
            ):
                fail()
            return original(directory, name, content)

        monkeypatch.setattr(delivery.store_type, "_publish_new", staticmethod(publish))
    elif fault == "readback":
        monkeypatch.setattr(delivery.store_type, "read_profiled_record", fail)
    elif fault == "receipt":
        monkeypatch.setattr(driver, "publish_metadata", fail)
    elif fault == "annotation":
        monkeypatch.setattr(driver, "annotate", fail)
    assert driver.deploy_step(context, delivery.directory) == (returncode or 3)
    assert len(delivery.commands) == 1
    assert (delivery.directory / driver.artifact_name(context, "record")).exists()
    store = AuditStore(delivery.root, checkout=driver.ROOT, create=False)
    records = store.iter_profiled_records()
    committed = fault in {
        "upload",
        "readback",
        "receipt_upload",
        "receipt",
        "annotation",
    }
    assert bool(records) == committed
    if committed:
        assert records[0].final_outcome is FinalOutcome.SUCCEEDED
    if fault not in {"upload", "annotation"}:
        assert (context.build_id, DURABLE_PUBLICATION_METADATA) not in delivery.metadata


@pytest.mark.parametrize(
    "outcome", ["EXECUTION_FAILED", "AMBIGUOUS", "RECOVERED", "RECOVERY_FAILED"]
)
def test_non_success_typed_execution_is_persisted_without_changing_exit(
    driver,
    context,
    delivery,
    outcome,
):
    from profiled_audit_fixtures import NOW, planning_result
    from test_profiled_execution import Cisco, Collector, Inventory, Secrets, writer

    from network_change_delivery.models import ExecutionResult
    from network_change_delivery.profiled_execution import execute_profiled_plan

    result, device, interface, state = planning_result()
    success = ExecutionResult(disposition="SUCCEEDED", message="ok")
    execution = (
        success
        if outcome in {"RECOVERED", "RECOVERY_FAILED"}
        else ExecutionResult(
            disposition="AMBIGUOUS" if outcome == "AMBIGUOUS" else "FAILED",
            message="bounded",
        )
    )
    states = (
        [state, state, state]
        if outcome in {"RECOVERED", "RECOVERY_FAILED"}
        else [state, state]
    )
    record = execute_profiled_plan(
        result.plan,
        result.plan.digest,
        Inventory(device, interface),
        Secrets(),
        Collector(states),
        writer(
            Cisco(
                [
                    execution,
                    ExecutionResult(disposition="FAILED", message="bounded recovery")
                    if outcome == "RECOVERY_FAILED"
                    else success,
                ]
            )
        ),
        now=lambda: NOW,
    )
    assert record.final_outcome.value == outcome
    delivery.raw[Kind.PROFILED_CHANGE_RECORD] = raw_bytes(record)
    delivery.attempt.returncode = 2
    assert driver.deploy_step(context, delivery.directory) == 2
    store = AuditStore(delivery.root, checkout=driver.ROOT, create=False)
    assert (
        store.read_profiled_record(UUID(context.job_id)).final_outcome.value == outcome
    )
    assert len(delivery.commands) == 1
    assert (delivery.directory / "configuration-pre.json").exists()
    assert (delivery.directory / "configuration-post.json").exists()


@pytest.mark.parametrize("damage", ["missing", "invalid", "binding"])
def test_unavailable_record_never_fabricates_envelope(
    driver, context, delivery, monkeypatch, damage
):
    if damage == "invalid":
        delivery.raw[Kind.PROFILED_CHANGE_RECORD] = b"{}"
    elif damage == "binding":
        data = delivery.values[Kind.PROFILED_CHANGE_RECORD].model_dump(mode="json")
        data["change_id"] = "CHG-OTHER"
        delivery.raw[Kind.PROFILED_CHANGE_RECORD] = json.dumps(data).encode()
    else:
        original = driver.command

        def command(*args, **kwargs):
            result = original(*args, **kwargs)
            (delivery.directory / driver.artifact_name(context, "record")).unlink()
            return result

        monkeypatch.setattr(driver, "command", command)
    assert driver.deploy_step(context, delivery.directory) == 3
    assert len(delivery.commands) == 1
    assert (
        AuditStore(
            delivery.root, checkout=driver.ROOT, create=False
        ).iter_profiled_records()
        == ()
    )
    assert "Artifact absence is not proof" in delivery.annotations[-1][1]


@pytest.mark.parametrize(
    "field",
    [
        "missing",
        "build_id",
        "commit",
        "job_id",
        "record_id",
        "record_digest",
        "delivery_kind",
        "final_outcome",
        "digest",
    ],
)
def test_final_rejects_receipt_tampering(driver, context, delivery, tmp_path, field):
    assert driver.deploy_step(context, delivery.directory) == 0
    key = (
        context.build_id,
        "profiled-deploy",
        driver.artifact_name(context, "durable-publication"),
    )
    if field == "missing":
        delivery.metadata.pop((context.build_id, DURABLE_PUBLICATION_METADATA))
    else:
        data = json.loads(delivery.artifacts[key])
        data[field] = {
            "build_id": "99999999-9999-4999-8999-999999999999",
            "commit": "f" * 40,
            "job_id": "99999999-9999-4999-8999-999999999999",
            "record_id": "99999999-9999-4999-8999-999999999999",
            "record_digest": "sha256:" + "f" * 64,
            "delivery_kind": "COMPLIANCE",
            "final_outcome": "AMBIGUOUS",
            "digest": "sha256:" + "f" * 64,
        }[field]
        delivery.artifacts[key] = json.dumps(data).encode()
    assert final(driver, context, tmp_path) == 3
    message = delivery.annotations[-1][1]
    assert "Outcome: SUCCEEDED" in message and "NOT ESTABLISHED" in message


@pytest.mark.parametrize(
    "fault", [None, "missing", "prepare", "canonical", "envelope", "receipt"]
)
def test_compliance_publication_without_any_device_authority(
    driver,
    context,
    offline,
    tmp_path,
    monkeypatch,
    fault,
):
    planning(driver, context, tmp_path)
    for name in (
        "prerequisites",
        "promote",
        "authorize",
        "validate_profiled_live_host_trust",
        "OpenBaoSecretProvider",
        "NetBoxProfileInventoryProvider",
        "ProfileReadOnlyAdapter",
    ):
        monkeypatch.setattr(
            driver, name, lambda *_a, **_k: pytest.fail("authority forbidden")
        )
    monkeypatch.setenv("BUILDKITE_UNBLOCKER_ID", "not-even-a-valid-uuid")
    root = Path(driver.os.environ["NCDP_AUDIT_STORE_ROOT"])
    if fault == "missing":
        monkeypatch.delenv("NCDP_AUDIT_STORE_ROOT")
    elif fault in {"prepare", "canonical", "envelope"}:
        method = {
            "prepare": "prepare_profiled_publication",
            "canonical": "persist_artifact",
            "envelope": "persist_profiled_record",
        }[fault]
        monkeypatch.setattr(AuditStore, method, fail)
    elif fault == "receipt":
        monkeypatch.setattr(driver, "publish_metadata", fail)
    directory = tmp_path / "deploy"
    directory.mkdir(mode=0o700)
    assert driver.deploy_step(context, directory) == (3 if fault else 0)
    assert "Outcome: COMPLIANT" in offline[2][-1][1]
    if fault:
        assert "NOT ESTABLISHED" in offline[2][-1][1]
    else:
        record = AuditStore(
            root, checkout=driver.ROOT, create=False
        ).read_profiled_record(UUID(context.job_id))
        assert record.authorization is record.assurance is None
        assert {r.kind for r in record.artifacts} == {Kind.PROFILED_COMPLIANCE_RECORD}
        assert final(driver, context, tmp_path) == 0
        assert "Durable evidence:" in offline[2][-1][1]
        assert "planning observation at" in offline[2][-1][1]


def test_prepare_historical_store_is_non_migrating_and_read_only_is_denied(tmp_path):
    from test_audit_store import make_store

    store = make_store(tmp_path)
    sentinel = store.root / "records" / "historical-private"
    sentinel.write_bytes(b"unchanged historical bytes")
    store.prepare_profiled_publication(
        UUID(int=7), frozenset({Kind.PROFILED_COMPLIANCE_RECORD})
    )
    assert sentinel.read_bytes() == b"unchanged historical bytes"
    assert store.iter_profiled_records() == ()
    readonly = AuditStore(store.root, checkout=tmp_path / "checkout", create=False)
    with pytest.raises(AuditStoreError):
        readonly.prepare_profiled_publication(
            UUID(int=7), frozenset({Kind.PROFILED_COMPLIANCE_RECORD})
        )


@pytest.mark.parametrize("result", ["AUTO_ROLLBACK_PENDING", "CONFIRMATION_AMBIGUOUS"])
def test_junos_outcome_artifact_durability_preserves_promotion_boundary(
    tmp_path, result
):
    from profiled_audit_fixtures import NOW, planning_result
    from test_audit_store import make_store
    from test_profiled_execution import Collector, Inventory, Junos, Secrets, writer

    from network_change_delivery.architecture_contracts import AutomationProfileID
    from network_change_delivery.models import ExecutionResult
    from network_change_delivery.profiled_execution import (
        execute_profiled_plan,
        verify_profiled_record_plan,
    )

    planned, device, interface, state = planning_result(
        AutomationProfileID.VJUNOS_ROUTER
    )
    success = ExecutionResult(disposition="SUCCEEDED", message="commit confirmed")
    junos = Junos(
        success,
        ExecutionResult(disposition="AMBIGUOUS", message="unknown confirmation"),
    )
    observed = (
        state
        if result == "AUTO_ROLLBACK_PENDING"
        else state.model_copy(update={"description": planned.plan.desired_description})
    )
    record = execute_profiled_plan(
        planned.plan,
        planned.plan.digest,
        Inventory(device, interface),
        Secrets(),
        Collector([state, observed]),
        writer(junos=junos),
        now=lambda: NOW,
    )
    assert record.final_outcome.value == result
    store = make_store(tmp_path)
    plan_ref = store.persist_artifact(Kind.PROFILED_DEPLOYMENT_PLAN, planned.plan)
    record_ref = store.persist_artifact(Kind.PROFILED_CHANGE_RECORD, record)
    verify_profiled_record_plan(
        store.read_artifact(record_ref), store.read_artifact(plan_ref)
    )
    assert store.read_artifact(record_ref) == record
    assert store.iter_profiled_records() == ()  # No currently admitted Junos promotion.


def test_receipt_contract_self_digest_and_job_identity(driver, context, delivery):
    from network_change_delivery.audit import canonical_json_bytes, sha256_identity

    assert driver.deploy_step(context, delivery.directory) == 0
    key = (
        context.build_id,
        "profiled-deploy",
        driver.artifact_name(context, "durable-publication"),
    )
    data = json.loads(delivery.artifacts[key])
    parsed = ProfiledDurablePublicationReceipt.model_validate(data)
    assert parsed.record_id == parsed.job_id
    assert not any(
        word in data for word in ("path", "credential", "unblocker", "environment")
    )
    data["record_digest"] = "sha256:" + "f" * 64
    with pytest.raises(ValueError, match="receipt rejected"):
        ProfiledDurablePublicationReceipt.model_validate(data)
    data["record_id"] = str(UUID(int=9))
    data["digest"] = sha256_identity(
        canonical_json_bytes({k: v for k, v in data.items() if k != "digest"})
    )
    with pytest.raises(ValueError, match="receipt rejected"):
        ProfiledDurablePublicationReceipt.model_validate(data)
