"""Current durable correlation and historical schema fencing, with offline fixtures."""

import json
from datetime import timedelta
from uuid import UUID

import pytest
from profiled_audit_fixtures import ASSURANCE, NOW, bundle, planning_result
from pydantic import ValidationError
from test_audit import artifact as legacy_reference
from test_audit import record as legacy_record
from test_audit_store import make_store, store_snapshot

from network_change_delivery.architecture_contracts import AutomationProfileID
from network_change_delivery.audit import (
    HISTORICAL_ARTIFACT_KINDS,
    ChangeAuditRecord,
    canonical_json_bytes,
    sha256_identity,
)
from network_change_delivery.audit import (
    AuditArtifactKind as Kind,
)
from network_change_delivery.audit_store import AuditStore, AuditStoreError
from network_change_delivery.profiled_audit import ProfiledDeliveryAuditRecord
from network_change_delivery.profiled_planning import ProfiledComplianceRecord


def rehash(data):
    data["digest"] = sha256_identity(
        canonical_json_bytes({k: v for k, v in data.items() if k != "digest"})
    )
    return data


def mutate(data, path, value):
    keys = path.split(".")
    for key in keys[:-1]:
        data = data[int(key)] if isinstance(data, list) else data[key]
    if isinstance(data, list):
        data[int(keys[-1])] = value
    else:
        data[keys[-1]] = value


@pytest.mark.parametrize(
    "profile",
    [
        AutomationProfileID.CAT8000V_IOSXE,
        AutomationProfileID.VJUNOS_ROUTER,
        AutomationProfileID.IOSV_159_3_M12,
        AutomationProfileID.IOSVL2_2020,
    ],
)
@pytest.mark.parametrize("compliant", [False, True])
def test_current_envelope_canonical_and_original_bytes_round_trip(
    tmp_path, compliant, profile
):
    store = make_store(tmp_path)
    record, raw, artifacts = bundle(store, compliant=compliant, profile=profile)
    assert not (store.root / "profiled-records").exists()
    assert store.iter_profiled_records() == ()  # artifacts alone are never an envelope
    path = store.persist_profiled_record(record, artifact_bytes=raw)
    assert path.parent.name == "profiled-records"
    assert path.read_bytes() == canonical_json_bytes(record.model_dump(mode="json"))
    assert store.read_profiled_record(record.record_id) == record
    assert store.iter_profiled_records() == (record,)
    assert store.iter_records() == ()
    for ref in record.artifacts:
        assert store.read_artifact(ref) == artifacts[ref.kind]
        assert store.persist_artifact(ref.kind, artifacts[ref.kind]) == ref
        assert (store.root / ref.locator).read_bytes() != raw[ref.kind]
        exact = (
            store.root
            / "profiled-artifact-bytes"
            / ref.kind.value
            / f"{record.byte_digests_by_kind()[ref.kind][7:]}.json"
        )
        assert exact.read_bytes() == raw[ref.kind]
    before = store_snapshot(store.root)
    readonly = AuditStore(store.root, checkout=tmp_path / "checkout", create=False)
    assert readonly.read_profiled_record(record.record_id) == record
    with pytest.raises(AuditStoreError):
        readonly.persist_profiled_record(record, artifact_bytes=raw)
    assert store_snapshot(store.root) == before


@pytest.mark.parametrize(
    "profile",
    [
        AutomationProfileID.CAT8000V_IOSXE,
        AutomationProfileID.VJUNOS_ROUTER,
        AutomationProfileID.IOSV_159_3_M12,
        AutomationProfileID.IOSVL2_2020,
    ],
)
def test_compliance_is_actual_successful_planning_without_deployment_claims(
    tmp_path, profile
):
    store = make_store(tmp_path)
    record, raw, artifacts = bundle(store, compliant=True, profile=profile)
    assert set(artifacts) == {Kind.PROFILED_COMPLIANCE_RECORD}
    compliance = artifacts[Kind.PROFILED_COMPLIANCE_RECORD]
    assert isinstance(compliance, ProfiledComplianceRecord)
    assert compliance.observed_at == NOW
    assert compliance.observed_description == compliance.desired_description
    assert compliance.plan is None
    assert not compliance.execution_attempted and not compliance.recovery_attempted
    assert not compliance.promotion_minted
    assert record.authorization is None and record.assurance is None
    assert (
        record.artifact_bytes.execution is None
        and record.artifact_bytes.promotion is None
    )
    assert record.final_outcome.value == "COMPLIANT"
    store.persist_profiled_record(record, artifact_bytes=raw)
    assert store.read_profiled_record(record.record_id) == record


EXECUTION_MUTATIONS = [
    ("digest", ASSURANCE),
    ("record_type", "change_audit_record"),
    ("schema_version", "2"),
    ("git.repository", "github:other/repository"),
    ("git.commit", "b" * 40),
    ("buildkite.build_id", str(UUID(int=99))),
    ("buildkite.step_key", "deploy-gate"),
    ("change_id", "CHG-DIFFERENT"),
    ("target.device", "netbox:dcim.device:2"),
    ("target.interface", "netbox:dcim.interface:99"),
    ("credential.reference", "openbao:kv-v2:ncdp/devices/2/ssh"),
    ("credential.source", "environment"),
    ("planning_result_digest", ASSURANCE),
    ("artifact_bytes.planning", ASSURANCE),
    ("artifact_bytes.promotion", ASSURANCE),
    ("artifact_bytes.execution", ASSURANCE),
    ("assurance.validation_digest", "sha256:" + "c" * 64),
    ("assurance.batfish_digest", "sha256:" + "c" * 64),
    ("assurance.cml_digest", "sha256:" + "c" * 64),
    ("authorization.promotion_digest", ASSURANCE),
    ("authorization.passed", False),
    ("authorization.step_key", "deployment-approval"),
    ("authorization.unblocker_id", "not-an-uuid"),
    ("authorization", None),
    ("assurance", None),
    ("final_outcome", "AMBIGUOUS"),
    ("artifacts.0.kind", "change_record"),
    ("artifacts.0.sha256", ASSURANCE),
    ("artifacts.0.schema_version", "1"),
    ("artifacts.0.size_bytes", 2),
    ("generated_at", "2026-09-09T12:00:00"),
    ("generated_at", "2026-09-09T12:00:00+01:00"),
]


@pytest.mark.parametrize("field,value", EXECUTION_MUTATIONS)
def test_execution_mismatch_rejected_even_when_outer_digest_is_recomputed(
    tmp_path, field, value
):
    store = make_store(tmp_path)
    record, raw, _ = bundle(store)
    data = record.model_dump(mode="json")
    mutate(data, field, value)
    if field != "digest":
        rehash(data)
    with pytest.raises(ValueError):
        altered = ProfiledDeliveryAuditRecord.model_validate(data)
        store.persist_profiled_record(altered, artifact_bytes=raw)
    assert store.iter_profiled_records() == ()


@pytest.mark.parametrize(
    "field",
    [
        "git.commit",
        "buildkite.pipeline_id",
        "buildkite.build_number",
        "buildkite.job_id",
        "authorization.unblocker_id",
    ],
)
def test_envelope_digest_binds_trusted_correlation_not_duplicated_in_artifacts(
    tmp_path, field
):
    store = make_store(tmp_path)
    record, _, _ = bundle(store)
    data = record.model_dump(mode="json")
    value = (
        99
        if field.endswith("number")
        else ("b" * 40 if field.endswith("commit") else str(UUID(int=99)))
    )
    mutate(data, field, value)
    with pytest.raises(ValueError, match="digest"):
        ProfiledDeliveryAuditRecord.model_validate(data)


@pytest.mark.parametrize(
    "field,value",
    [
        ("final_outcome", "SUCCEEDED"),
        ("delivery_kind", "EXECUTION"),
        (
            "authorization",
            {"unblocker_id": str(UUID(int=77)), "promotion_digest": ASSURANCE},
        ),
        (
            "assurance",
            {
                "validation_digest": ASSURANCE,
                "batfish_digest": ASSURANCE,
                "cml_digest": ASSURANCE,
            },
        ),
        ("artifact_bytes.promotion", ASSURANCE),
        ("artifact_bytes.execution", ASSURANCE),
        ("artifact_bytes.planning", ASSURANCE),
        ("planning_result_digest", ASSURANCE),
        ("target.interface", "netbox:dcim.interface:99"),
        ("credential.source", "environment"),
        ("target.device", "netbox:dcim.device:2"),
        ("artifacts", []),
    ],
)
def test_compliance_cannot_gain_authority_or_lose_binding(tmp_path, field, value):
    store = make_store(tmp_path)
    record, raw, _ = bundle(store, compliant=True)
    data = record.model_dump(mode="json")
    mutate(data, field, value)
    with pytest.raises(ValueError):
        altered = ProfiledDeliveryAuditRecord.model_validate(rehash(data))
        store.persist_profiled_record(altered, artifact_bytes=raw)
    assert not store.iter_profiled_records()


@pytest.mark.parametrize("kind", sorted(set(Kind) - HISTORICAL_ARTIFACT_KINDS, key=str))
def test_historical_envelope_explicitly_fences_every_profiled_kind(kind):
    historical = legacy_record()
    unchanged = historical.model_dump_json()
    assert (
        ChangeAuditRecord.model_validate_json(unchanged).model_dump_json() == unchanged
    )
    forged = legacy_reference(kind)
    with pytest.raises(ValueError, match="historical audit"):
        legacy_record(
            artifacts=tuple(
                sorted((*historical.artifacts, forged), key=lambda r: r.kind)
            )
        )


def test_missing_compliance_artifact_cannot_become_durable_compliance(tmp_path):
    store = make_store(tmp_path)
    record, raw, _ = bundle(store, compliant=True)
    (store.root / record.artifacts[0].locator).unlink()
    with pytest.raises(AuditStoreError):
        store.persist_profiled_record(record, artifact_bytes=raw)
    assert store.iter_profiled_records() == ()


@pytest.mark.parametrize("compliant", [False, True])
@pytest.mark.parametrize("location", ["envelope", "canonical", "original"])
def test_durable_reads_revalidate_every_layer(tmp_path, compliant, location):
    store = make_store(tmp_path)
    record, raw, _ = bundle(store, compliant=compliant)
    path = store.persist_profiled_record(record, artifact_bytes=raw)
    if location == "canonical":
        path = store.root / record.artifacts[0].locator
    elif location == "original":
        kind, digest = next(iter(record.byte_digests_by_kind().items()))
        path = (
            store.root / "profiled-artifact-bytes" / kind.value / f"{digest[7:]}.json"
        )
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(AuditStoreError):
        store.read_profiled_record(record.record_id)


def test_compliance_intrinsic_digest_rejects_modified_state():
    result, *_ = planning_result(compliant=True)
    data = json.loads(result.compliance.model_dump_json())
    data["observed_description"] = "different"
    with pytest.raises(ValueError):
        ProfiledComplianceRecord.model_validate(data)


def test_new_envelope_is_frozen_and_extra_forbid(tmp_path):
    record, _, _ = bundle(make_store(tmp_path))
    with pytest.raises(ValueError):
        record.generated_at = NOW + timedelta(seconds=1)
    with pytest.raises(ValueError):
        ProfiledDeliveryAuditRecord.model_validate(
            {**record.model_dump(), "environment": {}}
        )


def test_junos_artifact_durability_still_rejects_wrong_population_pairing(
    tmp_path,
):
    from profiled_audit_fixtures import BUILD, COMMIT, execution_pair, raw_bytes

    from network_change_delivery.profiled_execution import verify_profiled_record_plan
    from network_change_delivery.profiled_promotion import ProfiledPromotion

    store = make_store(tmp_path)
    plan, execution = execution_pair(AutomationProfileID.VJUNOS_ROUTER)
    assert execution.final_outcome.value == "SUCCEEDED"
    assert execution.candidate_validation.succeeded and execution.confirmation.succeeded
    plan_ref = store.persist_artifact(Kind.PROFILED_DEPLOYMENT_PLAN, plan)
    record_ref = store.persist_artifact(Kind.PROFILED_CHANGE_RECORD, execution)
    assert store.read_artifact(plan_ref) == plan
    assert store.read_artifact(record_ref) == execution
    verify_profiled_record_plan(
        store.read_artifact(record_ref), store.read_artifact(plan_ref)
    )
    rejected_payload = {
        "schema_version": "2",
        "promotion_type": "profiled_buildkite_promotion",
        "build_id": str(BUILD),
        "commit": COMMIT,
        "change_id": plan.change_id,
        "target": plan.target,
        "device_identity": "netbox:dcim.device:1",
        "plan_digest": plan.digest,
        "plan_artifact_digest": sha256_identity(raw_bytes(plan)),
        "validation_digest": ASSURANCE,
        "batfish_digest": ASSURANCE,
        "cml_digest": ASSURANCE,
    }
    # Intent-selected Junos is admitted; a Junos/core stable-ID pairing is not.
    with pytest.raises(ValidationError, match="population pairing"):
        ProfiledPromotion.model_validate(rehash(rejected_payload))
    assert store.iter_profiled_records() == ()
