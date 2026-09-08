"""Offline current coordinator: ordering, no replay, receipts and COMPLIANCE."""

import json
from uuid import UUID

import pytest
from profiled_chronology_fixtures import observation
from test_profiled_compliance_delivery import planning
from test_profiled_durable_publication import context as context_fixture
from test_profiled_durable_publication import delivery as delivery_fixture
from test_profiled_durable_publication import driver as driver_fixture
from test_profiled_durable_publication import (
    fail,
    final,
)
from test_profiled_durable_publication import offline as offline_fixture

from network_change_delivery.audit import canonical_json_bytes, sha256_identity
from network_change_delivery.audit_store import AuditStore
from network_change_delivery.profiled_configuration_observation import (
    CHRONOLOGY_METADATA,
    OxidizedObservation,
)
from network_change_delivery.profiled_configuration_observation_store import (
    ProfiledConfigurationObservationStore as Store,
)

context, driver, offline, delivery = (
    context_fixture,
    driver_fixture,
    offline_fixture,
    delivery_fixture,
)


def status_attempt(pre=None, status="UNCHANGED", category=None):
    value = observation(expected_before=pre)
    if category:
        d = value.model_dump()
        d.update(status=status, failure_category=category, after_revision=None)
        value = OxidizedObservation.model_validate(d)
    return value


@pytest.mark.parametrize(
    "fault",
    [
        "namespace",
        "service",
        "readiness",
        "history",
        "baseline",
        "collection",
        "timeout",
        "concurrent",
        "inconsistent",
        "file",
        "malformed",
    ],
)
def test_pre_failure_means_zero_commands(driver, context, delivery, monkeypatch, fault):
    if fault == "namespace":
        (delivery.root / "profiled-observation-records").symlink_to(delivery.root)
    elif fault == "file":
        monkeypatch.setattr(driver, "persist_attempt_file", fail)
    elif fault == "malformed":
        monkeypatch.setattr(
            driver,
            "capture_profiled_attempt",
            lambda *_a, **_k: observation().model_copy(update={"after_revision": None}),
        )
    else:
        status, category = {
            "service": ("FAILED", "SOURCE_UNAVAILABLE"),
            "readiness": ("FAILED", "SOURCE_UNAVAILABLE"),
            "history": ("FAILED", "HISTORY_UNAVAILABLE"),
            "baseline": ("FAILED", "HISTORY_UNAVAILABLE"),
            "collection": ("FAILED", "COLLECTION_FAILED"),
            "timeout": ("TIMED_OUT", "COLLECTION_TIMED_OUT"),
            "concurrent": ("AMBIGUOUS", "CONCURRENT_COLLECTION"),
            "inconsistent": ("AMBIGUOUS", "INCONSISTENT_EVIDENCE"),
        }[fault]
        monkeypatch.setattr(
            driver,
            "capture_profiled_attempt",
            lambda *_a, **_k: status_attempt(status=status, category=category),
        )
    assert driver.deploy_step(context, delivery.directory) == 2
    assert delivery.commands == []
    store = Store(delivery.root, checkout=driver.ROOT, create=False)
    assert not store.iter_profiled_records()
    if fault == "namespace":
        with pytest.raises(ValueError):
            store.iter_profiled_observation_records()
    else:
        assert not store.iter_profiled_observation_records()
    assert "NO WRITE" in delivery.annotations[-1][1]
    assert "private-failure-path-secret" not in repr(delivery.annotations)


def test_order_and_parent_receipt_precedes_child(
    driver, context, delivery, monkeypatch, tmp_path
):
    trace = []
    for name, label in [
        ("authorize", "authorize"),
        ("persist_input", "input"),
        ("command", "command"),
        ("capture_profiled_attempt", "capture"),
        ("read_artifact", "report"),
        ("publish_durable", "parent_receipt"),
        ("annotate", "annotation"),
    ]:
        old = getattr(driver, name)

        def wrapper(*a, _old=old, _label=label, **k):
            trace.append(_label)
            return _old(*a, **k)

        monkeypatch.setattr(driver, name, wrapper)
    for name, label in [
        ("prepare_profiled_observation_publication", "chronology_ready"),
        ("persist_profiled_observation_record", "child"),
        ("read_profiled_observation_record", "child_readback"),
    ]:
        old = getattr(Store, name)

        def wrapper(*a, _old=old, _label=label, **k):
            trace.append(_label)
            return _old(*a, **k)

        monkeypatch.setattr(Store, name, wrapper)
    original = driver.publish_metadata

    def publish(c, k, v):
        if k == CHRONOLOGY_METADATA:
            trace.append("chronology_receipt")
        original(c, k, v)

    monkeypatch.setattr(driver, "publish_metadata", publish)
    assert driver.deploy_step(context, delivery.directory) == 0
    assert trace[:7] == [
        "authorize",
        "input",
        "input",
        "chronology_ready",
        "capture",
        "command",
        "capture",
    ]
    assert trace.index("report") > trace.index("command") + 1
    assert (
        trace.index("parent_receipt")
        < trace.index("child")
        < trace.index("child_readback")
        < trace.index("chronology_receipt")
        < trace.index("annotation")
    )
    assert len(delivery.commands) == 1
    assert final(driver, context, tmp_path) == 0
    message = delivery.annotations[-1][1]
    assert (
        "Configuration chronology: SUCCEEDED" in message
        and "Causality: NOT_PROVEN" in message
    )


@pytest.mark.parametrize(
    "fault",
    [
        "collection",
        "timeout",
        "concurrent",
        "inconsistent",
        "history",
        "file",
        "child",
        "readback",
        "upload",
        "metadata",
        "annotation",
    ],
)
@pytest.mark.parametrize("code", [0, 17])
def test_post_failures_preserve_parent_and_primary_exit(
    driver, context, delivery, monkeypatch, fault, code
):
    delivery.attempt.returncode = code
    attempts = []
    original_capture = driver.capture_profiled_attempt

    def capture(*a, **k):
        attempts.append("POST" if k else "PRE")
        if k and fault in [
            "collection",
            "timeout",
            "concurrent",
            "inconsistent",
            "history",
        ]:
            status, category = {
                "collection": ("FAILED", "COLLECTION_FAILED"),
                "timeout": ("TIMED_OUT", "COLLECTION_TIMED_OUT"),
                "concurrent": ("AMBIGUOUS", "CONCURRENT_COLLECTION"),
                "inconsistent": ("AMBIGUOUS", "INCONSISTENT_EVIDENCE"),
                "history": ("FAILED", "HISTORY_UNAVAILABLE"),
            }[fault]
            return status_attempt(k["expected_before"], status, category)
        return original_capture(*a, **k)

    monkeypatch.setattr(driver, "capture_profiled_attempt", capture)
    if fault == "file":
        old = driver.persist_attempt_file

        def persist(path, value):
            if path.name == "configuration-post.json":
                fail()
            old(path, value)

        monkeypatch.setattr(driver, "persist_attempt_file", persist)
    elif fault in ["child", "readback"]:
        monkeypatch.setattr(
            Store,
            "persist_profiled_observation_record"
            if fault == "child"
            else "read_profiled_observation_record",
            fail,
        )
    elif fault == "upload":
        old = driver.upload

        def upload(c, d, n):
            if n.endswith("-chronology.json"):
                fail()
            old(c, d, n)

        monkeypatch.setattr(driver, "upload", upload)
    elif fault == "metadata":
        old = driver.publish_metadata

        def publish(c, k, v):
            if k == CHRONOLOGY_METADATA:
                fail()
            old(c, k, v)

        monkeypatch.setattr(driver, "publish_metadata", publish)
    elif fault == "annotation":
        monkeypatch.setattr(driver, "annotate", fail)
    assert driver.deploy_step(context, delivery.directory) == (code or 3)
    assert attempts == ["PRE", "POST"] and len(delivery.commands) == 1
    parent = AuditStore(
        delivery.root, checkout=driver.ROOT, create=False
    ).read_profiled_record(UUID(context.job_id))
    assert parent.final_outcome.value == "SUCCEEDED"
    assert (context.build_id, driver.DURABLE_PUBLICATION_METADATA) in delivery.metadata
    assert (delivery.directory / "configuration-pre.json").exists()


def test_uncertain_child_start_attempts_post_without_fabrication(
    driver, context, delivery, monkeypatch
):
    calls = []
    captures = []
    old = driver.capture_profiled_attempt

    def command(*a, **_k):
        calls.append(a)
        raise OSError("private-unknown-start")

    def capture(*a, **k):
        captures.append(k)
        return old(*a, **k)

    monkeypatch.setattr(driver, "command", command)
    monkeypatch.setattr(driver, "capture_profiled_attempt", capture)
    assert driver.deploy_step(context, delivery.directory) == 3
    assert len(calls) == 1 and len(captures) == 2
    store = Store(delivery.root, checkout=driver.ROOT, create=False)
    assert (
        store.iter_profiled_records() == store.iter_profiled_observation_records() == ()
    )
    assert (delivery.directory / "configuration-post.json").exists()
    assert "Artifact absence is not proof" in delivery.annotations[-1][1]
    assert "private-unknown-start" not in delivery.annotations[-1][1]


@pytest.mark.parametrize(
    "field",
    [
        "build_id",
        "commit",
        "job_id",
        "parent_record_id",
        "parent_digest",
        "chronology_record_id",
        "chronology_digest",
        "target",
        "relationship",
        "causality",
        "overall_status",
        "pre_status",
        "post_status",
        "digest",
        "bytes",
        "missing",
    ],
)
def test_receipt_tampering_rejected(driver, context, delivery, tmp_path, field):
    assert driver.deploy_step(context, delivery.directory) == 0
    key = (
        context.build_id,
        "profiled-deploy",
        driver.artifact_name(context, "chronology"),
    )
    data = json.loads(delivery.artifacts[key])
    if field == "missing":
        delivery.metadata.pop((context.build_id, CHRONOLOGY_METADATA))
    else:
        changes = {
            "build_id": str(UUID(int=9)),
            "commit": "f" * 40,
            "job_id": str(UUID(int=9)),
            "parent_record_id": str(UUID(int=9)),
            "parent_digest": "sha256:" + "f" * 64,
            "chronology_record_id": str(UUID(int=9)),
            "chronology_digest": "sha256:" + "f" * 64,
            "target": "netbox:dcim.device:2",
            "relationship": "POST_ONLY",
            "causality": "PROVEN",
            "overall_status": "PARTIAL",
            "pre_status": "FAILED",
            "post_status": "FAILED",
            "digest": "sha256:" + "f" * 64,
        }
        if field != "bytes":
            data[field] = changes[field]
        # Rehash external correlation fields to exercise binding separately.
        if field in {"build_id", "commit", "target", "parent_digest"}:
            data["digest"] = sha256_identity(
                canonical_json_bytes({k: v for k, v in data.items() if k != "digest"})
            )
        raw = json.dumps(data).encode()
        delivery.artifacts[key] = raw
        if field != "bytes":
            delivery.metadata[(context.build_id, CHRONOLOGY_METADATA)] = (
                sha256_identity(raw)
            )
    assert final(driver, context, tmp_path) == 3
    assert "Outcome: SUCCEEDED" in delivery.annotations[-1][1]
    assert "Configuration chronology: NOT ESTABLISHED" in delivery.annotations[-1][1]
    assert len(delivery.commands) == 1


def test_compliance_never_opens_chronology_plane(
    driver, context, offline, tmp_path, monkeypatch
):
    planning(driver, context, tmp_path)
    for name in [
        "capture_profiled_attempt",
        "persist_attempt_file",
        "load_attempt_file",
        "ProfiledConfigurationObservationStore",
        "chronology_receipt",
    ]:
        monkeypatch.setattr(
            driver,
            name,
            lambda *_a, **_k: pytest.fail("chronology forbidden for compliance"),
        )
    directory = tmp_path / "deploy"
    directory.mkdir(mode=0o700)
    assert driver.deploy_step(context, directory) == 0
    assert final(driver, context, tmp_path) == 0
    assert (context.build_id, CHRONOLOGY_METADATA) not in offline[1]
    assert "Configuration chronology: NOT REQUIRED — COMPLIANT" in offline[2][-1][1]


def test_intervening_history_keeps_parent_and_ambiguous_child(
    driver, context, delivery, monkeypatch
):
    from types import SimpleNamespace

    from network_change_delivery.profiled_configuration_observation import (
        capture_attempt,
    )

    original = driver.capture_profiled_attempt

    def capture(plan, **kwargs):
        if not kwargs:
            return original(plan)
        unrelated = observation(changed=True).after_revision
        return capture_attempt(
            SimpleNamespace(collect=lambda _: pytest.fail("do not rebase collection")),
            SimpleNamespace(latest_revision=lambda _: unrelated),
            "netbox-device-1",
            expected_before=kwargs["expected_before"],
        )

    monkeypatch.setattr(driver, "capture_profiled_attempt", capture)
    assert driver.deploy_step(context, delivery.directory) == 3
    assert len(delivery.commands) == 1
    store = Store(delivery.root, checkout=driver.ROOT, create=False)
    parent = store.read_profiled_record(UUID(context.job_id))
    child = store.find_by_profiled_parent(parent.record_id)[0]
    assert parent.final_outcome.value == "SUCCEEDED"
    assert child.overall_status.value == "AMBIGUOUS" and child.causality == "NOT_PROVEN"
