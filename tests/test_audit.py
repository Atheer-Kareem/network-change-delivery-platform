"""Tests for durable audit correlation model boundaries."""

from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID

import pytest
from pydantic import ValidationError

from network_change_delivery.audit import (
    AuditArtifactKind,
    AuditArtifactReference,
    AuditFinalOutcome,
    BuildkiteCorrelation,
    ChangeAuditRecord,
    CredentialProvenance,
    GitCorrelation,
    ProtectedApprovalBoundary,
    StableTargetIdentity,
    audit_record_with_digest,
)

RECORD_ID = UUID("11111111-1111-4111-8111-111111111111")
PIPELINE_ID = UUID("22222222-2222-4222-8222-222222222222")
BUILD_ID = UUID("33333333-3333-4333-8333-333333333333")
JOB_ID = UUID("44444444-4444-4444-8444-444444444444")
DIGEST = "sha256:" + "a" * 64


def artifact(
    kind: AuditArtifactKind = AuditArtifactKind.DEPLOYMENT_PLAN,
    *,
    digest: str = DIGEST,
) -> AuditArtifactReference:
    return AuditArtifactReference(
        kind=kind,
        schema_version="1",
        sha256=digest,
        locator=f"artifacts/{kind.value}/{digest[7:]}.json",
        size_bytes=100,
    )


def record(**changes: object) -> ChangeAuditRecord:
    values: dict[str, object] = {
        "schema_version": "1",
        "record_id": RECORD_ID,
        "generated_at": datetime(2026, 8, 27, 1, 2, 3, tzinfo=UTC),
        "change_id": "CHG-10B1",
        "git": GitCorrelation(
            repository="github:Atheer-Kareem/network-change-delivery-platform",
            commit="a" * 40,
            pull_request=48,
        ),
        "targets": (
            StableTargetIdentity(
                device="netbox:dcim.device:1",
                interface="netbox:dcim.interface:7",
            ),
        ),
        "credentials": (
            CredentialProvenance(
                device="netbox:dcim.device:1",
                source="openbao",
                reference="openbao:kv-v2:ncdp/devices/1/ssh",
            ),
        ),
        "final_outcome": AuditFinalOutcome.SUCCEEDED,
        "artifacts": (artifact(),),
    }
    values.update(changes)
    return audit_record_with_digest(**values)


def test_record_is_frozen_and_rejects_extra_fields() -> None:
    approved = record()
    with pytest.raises(ValidationError):
        approved.change_id = "changed"
    payload = approved.model_dump(mode="json")
    payload["password"] = "not-allowed"
    with pytest.raises(ValidationError):
        ChangeAuditRecord.model_validate(payload)
    payload.pop("password")
    payload["schema_version"] = "2"
    with pytest.raises(ValidationError):
        ChangeAuditRecord.model_validate(payload)


@pytest.mark.parametrize("digest", ["a" * 64, "sha256:ABC", "sha256:" + "g" * 64])
def test_artifact_reference_rejects_malformed_sha256(digest: str) -> None:
    with pytest.raises(ValidationError):
        artifact(digest=digest)


@pytest.mark.parametrize(
    "locator",
    [
        "/artifacts/deployment_plan/x.json",
        "../artifacts/deployment_plan/x.json",
        "artifacts/../deployment_plan/x.json",
        "artifacts//deployment_plan/x.json",
        "artifacts/change_record/" + "a" * 64 + ".json",
    ],
)
def test_artifact_reference_rejects_noncanonical_locator(locator: str) -> None:
    payload = artifact().model_dump(mode="json")
    payload["locator"] = locator
    with pytest.raises(ValidationError):
        AuditArtifactReference.model_validate(payload)


def test_record_uuid_and_serialization_are_stable_and_canonical() -> None:
    first = record()
    second = record()
    assert first.record_id == RECORD_ID
    assert first.model_dump(mode="json")["record_id"] == str(RECORD_ID)
    assert first.digest_input() == second.digest_input()
    assert first.digest == second.digest


def test_record_rejects_non_utc_aware_timestamp() -> None:
    with pytest.raises(ValidationError):
        record(generated_at=datetime(2026, 8, 27))
    with pytest.raises(ValidationError):
        record(generated_at=datetime(2026, 8, 27, tzinfo=timezone(timedelta(hours=10))))


def test_digest_verifies_and_covers_every_material_group() -> None:
    approved = record()
    assert approved.verify_digest()
    assert not approved.model_copy(update={"change_id": "CHG-TAMPERED"}).verify_digest()
    assert not approved.model_copy(
        update={"artifacts": (artifact(digest="sha256:" + "b" * 64),)}
    ).verify_digest()
    assert not approved.model_copy(
        update={"git": approved.git.model_copy(update={"commit": "b" * 40})}
    ).verify_digest()


def test_duplicate_or_unsorted_artifacts_are_rejected() -> None:
    with pytest.raises(ValidationError, match="unique and ordered"):
        record(artifacts=(artifact(), artifact()))
    staging = artifact(AuditArtifactKind.STAGING_EVIDENCE)
    with pytest.raises(ValidationError, match="unique and ordered"):
        record(artifacts=(staging, artifact()))


def test_buildkite_and_approval_correlations_are_atomic() -> None:
    with pytest.raises(ValidationError, match="requires Buildkite"):
        record(approval=ProtectedApprovalBoundary())
    approved = record(
        buildkite=BuildkiteCorrelation(
            pipeline_id=PIPELINE_ID,
            build_id=BUILD_ID,
            build_number=121,
            job_id=JOB_ID,
            step_key="deploy-gate",
        ),
        approval=ProtectedApprovalBoundary(),
    )
    assert approved.approval is not None and approved.approval.passed

    payload = approved.model_dump(mode="json")
    payload["buildkite"] = {"pipeline_id": str(PIPELINE_ID)}
    with pytest.raises(ValidationError):
        ChangeAuditRecord.model_validate(payload)
    payload = approved.model_dump(mode="json")
    payload["git"] = {"repository": approved.git.repository}
    with pytest.raises(ValidationError):
        ChangeAuditRecord.model_validate(payload)


def test_target_and_credential_groups_reject_ambiguity() -> None:
    target = record().targets[0]
    with pytest.raises(ValidationError, match="unique and ordered"):
        record(targets=(target, target))
    unknown = CredentialProvenance(
        device="netbox:dcim.device:2",
        source="openbao",
        reference="openbao:kv-v2:ncdp/devices/2/ssh",
    )
    with pytest.raises(ValidationError, match="unknown device"):
        record(credentials=(unknown,))


def test_single_and_fleet_evidence_cannot_be_mixed_or_flattened() -> None:
    fleet_record = artifact(AuditArtifactKind.FLEET_CHANGE_RECORD)
    with pytest.raises(ValidationError, match="single-device"):
        record(artifacts=(artifact(), fleet_record))
    fleet_plan = artifact(AuditArtifactKind.FLEET_DEPLOYMENT_PLAN)
    child = artifact(AuditArtifactKind.CHANGE_RECORD)
    with pytest.raises(ValidationError, match="flatten"):
        record(artifacts=(child, fleet_plan))


def test_envelope_schema_has_no_raw_secret_or_configuration_fields() -> None:
    forbidden = {
        "password",
        "username",
        "token",
        "jwt",
        "configuration",
        "terraform_state",
        "runner_events",
        "provider_output",
    }
    assert forbidden.isdisjoint(ChangeAuditRecord.model_fields)
