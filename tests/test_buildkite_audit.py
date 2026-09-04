"""Deterministic protected-Buildkite audit correlation tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
from snmp_test_fixtures import snmp_plan
from test_audit_store import plan, snmp_record
from test_promotion import _record as assurance_record

import network_change_delivery.buildkite_audit as audit_module
from network_change_delivery.audit import (
    AuditArtifactKind,
    AuditArtifactReference,
    AuditFinalOutcome,
)
from network_change_delivery.buildkite_audit import (
    FINAL_OUTCOME_MAP,
    SNMP_FINAL_OUTCOME_MAP,
    BuildkiteAuditError,
    normalize_buildkite_repository,
    persist_buildkite_audit,
    validate_change_record,
    validate_staging_correlation,
)
from network_change_delivery.buildkite_policy import BuildkiteDeploymentContext
from network_change_delivery.ephemeral_staging import StagingEvidence
from network_change_delivery.models import ChangeRecord, FinalOutcome, StageResult
from network_change_delivery.snmp_provisioning import SnmpProvisioningOutcome

PIPELINE_ID = "11111111-1111-4111-8111-111111111111"
BUILD_ID = "22222222-2222-4222-8222-222222222222"
JOB_ID = "33333333-3333-4333-8333-333333333333"


def context(**changes: str) -> BuildkiteDeploymentContext:
    values = {
        "commit": "a" * 40,
        "branch": "main",
        "pull_request": "false",
        "pipeline_id": PIPELINE_ID,
        "build_id": BUILD_ID,
        "build_number": "48",
        "job_id": JOB_ID,
        "step_key": "deploy-gate",
        "queue_key": "ncdp-deploy",
    }
    values.update(changes)
    return BuildkiteDeploymentContext(**values)


def staging(**changes: object) -> StagingEvidence:
    values: dict[str, object] = {
        "schema_version": "2",
        "staging_run_id": f"bk-{BUILD_ID}",
        "orchestrator": "buildkite",
        "pipeline_id": PIPELINE_ID,
        "build_id": BUILD_ID,
        "build_commit": "a" * 40,
        "build_branch": "main",
        "step_key": "cml-staging",
        "job_id": "44444444-4444-4444-8444-444444444444",
        "creation_outcome": "passed",
        "readiness_outcome": "passed",
        "ncdp_validation_outcome": "passed",
        "destroy_outcome": "passed",
        "absence_verification_outcome": "passed",
        "state_retirement_outcome": "passed",
        "overall_result": "passed",
    }
    values.update(changes)
    return StagingEvidence(**values)


class FakeStore:
    def __init__(self) -> None:
        self.record = None
        self.kinds = []

    def persist_artifact(self, kind, _artifact):
        self.kinds.append(kind)
        digest = "sha256:" + f"{len(self.kinds):064x}"
        return AuditArtifactReference(
            kind=kind,
            schema_version="1",
            sha256=digest,
            locator=f"artifacts/{kind.value}/{digest[7:]}.json",
            size_bytes=2,
        )

    def persist_record(self, record):
        self.record = record


def write_staging(path: Path, evidence: StagingEvidence) -> None:
    path.write_text(json.dumps(evidence.safe_dict()), encoding="utf-8")


def test_same_build_no_write_produces_deterministic_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    approved = plan()
    manifest = SimpleNamespace()
    assurance = SimpleNamespace()
    monkeypatch.setattr(
        audit_module,
        "load_verified_promotion_artifacts",
        lambda *_args: (manifest, approved, assurance),
    )
    monkeypatch.setattr(
        audit_module,
        "load_live_deployment_request_at_commit",
        lambda *_args, **_kwargs: None,
    )
    evidence_path = tmp_path / "staging.json"
    write_staging(evidence_path, staging())
    store = FakeStore()
    record_id, digest, outcome = persist_buildkite_audit(
        store=store,
        context=context(),
        repository="git@github.com:Atheer-Kareem/network-change-delivery-platform.git",
        promotion=tmp_path,
        staging_evidence_path=evidence_path,
        checkout=tmp_path,
        now=datetime(2026, 8, 27, tzinfo=UTC),
    )
    assert record_id == UUID(JOB_ID)
    assert outcome is AuditFinalOutcome.NO_WRITE
    assert store.record.verify_digest()
    assert store.record.digest == digest
    assert len(store.record.artifacts) == 4
    assert store.record.buildkite.job_id == UUID(JOB_ID)


def test_missing_change_record_cannot_be_called_no_write_when_request_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    approved = plan()
    monkeypatch.setattr(
        audit_module,
        "load_verified_promotion_artifacts",
        lambda *_args: (SimpleNamespace(), approved, SimpleNamespace()),
    )
    monkeypatch.setattr(
        audit_module,
        "load_live_deployment_request_at_commit",
        lambda *_args, **_kwargs: SimpleNamespace(),
    )
    evidence_path = tmp_path / "staging.json"
    write_staging(evidence_path, staging())
    with pytest.raises(BuildkiteAuditError, match="without typed ChangeRecord"):
        persist_buildkite_audit(
            store=FakeStore(),
            context=context(),
            repository="https://github.com/owner/repo.git",
            promotion=tmp_path,
            staging_evidence_path=evidence_path,
            checkout=tmp_path,
        )


@pytest.mark.parametrize(
    ("typed_outcome", "audit_outcome"),
    [
        (SnmpProvisioningOutcome.AMBIGUOUS, AuditFinalOutcome.AMBIGUOUS),
        (SnmpProvisioningOutcome.SUCCEEDED, AuditFinalOutcome.SUCCEEDED),
    ],
)
def test_snmp_attempt_persists_exact_plan_record_and_credential_provenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    typed_outcome: SnmpProvisioningOutcome,
    audit_outcome: AuditFinalOutcome,
) -> None:
    approved = snmp_plan()
    evidence = snmp_record(typed_outcome)
    monkeypatch.setattr(
        audit_module,
        "load_verified_promotion_artifacts",
        lambda *_args: (SimpleNamespace(), approved, SimpleNamespace()),
    )
    monkeypatch.setattr(
        audit_module,
        "load_live_deployment_request_at_commit",
        lambda *_args, **_kwargs: SimpleNamespace(verify_plan=lambda _plan: None),
    )
    staging_path = tmp_path / "staging.json"
    write_staging(staging_path, staging())
    record_path = tmp_path / "snmp-record.json"
    record_path.write_text(evidence.model_dump_json(), encoding="utf-8")
    store = FakeStore()
    _record_id, _digest, outcome = persist_buildkite_audit(
        store=store,
        context=context(),
        repository="https://github.com/owner/repo.git",
        promotion=tmp_path,
        staging_evidence_path=staging_path,
        checkout=tmp_path,
        change_record_path=record_path,
        now=datetime(2026, 8, 29, tzinfo=UTC),
    )
    assert outcome is audit_outcome
    assert SNMP_FINAL_OUTCOME_MAP[typed_outcome] is audit_outcome
    assert store.kinds == [
        AuditArtifactKind.SNMP_PROVISIONING_PLAN,
        AuditArtifactKind.PLAN_ASSURANCE_RECORD,
        AuditArtifactKind.DEPLOYMENT_PROMOTION_MANIFEST,
        AuditArtifactKind.STAGING_EVIDENCE,
        AuditArtifactKind.SNMP_PROVISIONING_RECORD,
    ]
    assert [(target.device, target.interface) for target in store.record.targets] == [
        (approved.inventory_object_id, None)
    ]
    assert [
        (item.device, item.source, item.reference) for item in store.record.credentials
    ] == [
        (
            approved.inventory_object_id,
            "openbao",
            approved.connection_credential_reference,
        ),
        (
            approved.inventory_object_id,
            "openbao_snmp",
            approved.snmp_credential.reference,
        ),
    ]
    serialized = store.record.model_dump_json().casefold()
    for forbidden in ("authentication_secret", "privacy_secret", "password"):
        assert forbidden not in serialized


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("git@github.com:Owner/Repo.git", "github:owner/repo"),
        ("https://github.com/Owner/Repo.git", "github:owner/repo"),
        ("ssh://git@github.com/Owner/Repo.git", "github:owner/repo"),
    ],
)
def test_repository_normalization(value: str, expected: str) -> None:
    assert normalize_buildkite_repository(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "",
        "owner/repo",
        "https://example.com/owner/repo",
        "https://token@github.com/o/r",
    ],
)
def test_repository_normalization_rejects_untrusted_forms(value: str) -> None:
    with pytest.raises(BuildkiteAuditError):
        normalize_buildkite_repository(value)


@pytest.mark.parametrize(
    "changes",
    [{"branch": "feature"}, {"pull_request": "48"}, {"step_key": "other"}],
)
def test_protected_context_requires_main_non_pr_deploy_gate(
    changes: dict[str, str],
) -> None:
    with pytest.raises(ValueError):
        context(**changes)


def test_promotion_digest_or_assurance_subject_mismatch_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    approved = plan()
    assurance = assurance_record()
    (tmp_path / "assurance.json").write_text(
        assurance.model_dump_json(), encoding="utf-8"
    )
    manifest = SimpleNamespace(
        verify_digest=lambda: False,
        plan_digest=approved.digest,
        assurance_record_digest=assurance.digest,
    )
    monkeypatch.setattr(
        audit_module,
        "load_promoted_single_plan",
        lambda *_args: (manifest, approved),
    )
    with pytest.raises(BuildkiteAuditError, match="promotion audit correlation"):
        audit_module.load_verified_promotion_artifacts(tmp_path, context())


@pytest.mark.parametrize(
    "changes",
    [
        {"pipeline_id": str(UUID(int=9))},
        {"build_id": str(UUID(int=9))},
        {"build_commit": "b" * 40},
        {"build_branch": "feature"},
        {"step_key": "deploy-gate"},
        {"staging_run_id": "bk-wrong"},
        {"creation_outcome": "failed"},
        {"readiness_outcome": "failed"},
        {"ncdp_validation_outcome": "failed"},
        {"destroy_outcome": "failed"},
        {"absence_verification_outcome": "failed"},
        {"state_retirement_outcome": "failed"},
    ],
)
def test_staging_mismatch_or_failure_is_rejected(changes: dict[str, object]) -> None:
    with pytest.raises(BuildkiteAuditError):
        validate_staging_correlation(staging(**changes), context())


def change_record(**changes: object) -> ChangeRecord:
    approved = plan()
    stage = StageResult(message="bounded", attempted=False)
    values: dict[str, object] = {
        "generated_at": datetime(2026, 8, 27, tzinfo=UTC),
        "change_id": approved.change_id,
        "plan_digest": approved.digest,
        "target": approved.target,
        "inventory_source": approved.inventory_source,
        "inventory_object_id": approved.inventory_object_id,
        "inventory_interface_object_id": approved.inventory_interface_object_id,
        "credential_source": approved.credential_source,
        "credential_reference": approved.credential_reference,
        "host": approved.host,
        "port": approved.port,
        "expected_hostname": approved.expected_hostname,
        "platform": approved.platform,
        "interface": approved.interface,
        "previous_description": approved.current_description,
        "desired_description": approved.desired_description,
        "approval_digest": approved.digest,
        "preflight": stage,
        "execution": stage,
        "post_validation": stage,
        "recovery": stage,
        "transaction_strategy": approved.transaction_strategy,
        "final_outcome": FinalOutcome.SUCCEEDED,
        "provider": "bounded-test",
    }
    values.update(changes)
    return ChangeRecord(**values)


@pytest.mark.parametrize(
    "changes",
    [
        {"plan_digest": "sha256:" + "0" * 64},
        {"approval_digest": "sha256:" + "0" * 64},
        {"change_id": "other"},
        {"target": "other"},
        {"inventory_object_id": "netbox:dcim.device:2"},
        {"inventory_interface_object_id": "netbox:dcim.interface:8"},
        {"credential_reference": "openbao:kv-v2:ncdp/devices/2/ssh"},
        {"platform": "junos", "port": 830},
        {"interface": "GigabitEthernet3"},
    ],
)
def test_change_record_must_match_promoted_plan(changes: dict[str, object]) -> None:
    with pytest.raises(BuildkiteAuditError):
        validate_change_record(change_record(**changes), plan())


def test_every_final_outcome_has_explicit_reviewed_mapping() -> None:
    assert set(FINAL_OUTCOME_MAP) == set(FinalOutcome)
    for outcome in (
        FinalOutcome.AMBIGUOUS,
        FinalOutcome.RECOVERY_AMBIGUOUS,
        FinalOutcome.CONFIRMATION_AMBIGUOUS,
    ):
        assert FINAL_OUTCOME_MAP[outcome] is AuditFinalOutcome.AMBIGUOUS
