"""Version 1 durable envelopes for current schema-v2 profiled delivery artifacts.

These contracts correlate existing evidence offline. They confer no write authority
and do not publish evidence from the current Buildkite delivery path.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from network_change_delivery.audit import (
    AuditArtifactKind,
    AuditArtifactReference,
    BoundedText,
    BuildkiteCorrelation,
    CredentialProvenance,
    GitCorrelation,
    Sha256,
    StableTargetIdentity,
    canonical_json_bytes,
    sha256_identity,
)
from network_change_delivery.models import FinalOutcome
from network_change_delivery.profiled_execution import (
    ProfiledChangeRecord,
    verify_profiled_record_plan,
)
from network_change_delivery.profiled_planning import (
    ProfiledComplianceRecord,
    ProfiledDeploymentPlan,
)
from network_change_delivery.profiled_promotion import ProfiledPromotion

PROFILED_REPOSITORY = "github:Atheer-Kareem/network-change-delivery-platform"


class ProfiledDeliveryKind(StrEnum):
    EXECUTION = "EXECUTION"
    COMPLIANCE = "COMPLIANCE"


class ProfiledHumanAuthorization(BaseModel):
    """Trusted scheduler provenance, not a looked-up or cryptographic user identity."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    step_key: Literal["profiled-human-authorization"] = "profiled-human-authorization"
    passed: Literal[True] = True
    unblocker_id: UUID
    promotion_digest: Sha256


class ProfiledAssuranceCorrelation(BaseModel):
    """Exact promoted prerequisites, not candidate-specific service/write proof."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    validation_digest: Sha256
    batfish_digest: Sha256
    cml_digest: Sha256


class ProfiledArtifactByteDigests(BaseModel):
    """Original validated JSON byte hashes, distinct from canonical store identities."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    planning: Sha256
    promotion: Sha256 | None = None
    execution: Sha256 | None = None


class ProfiledDeliveryAuditRecord(BaseModel):
    """Immutable current delivery correlation; envelope v1, delivery artifacts v2."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal["1"] = "1"
    record_type: Literal["profiled_delivery_audit_record"] = (
        "profiled_delivery_audit_record"
    )
    record_id: UUID
    generated_at: datetime
    digest: Sha256
    change_id: BoundedText
    git: GitCorrelation
    buildkite: BuildkiteCorrelation
    target: StableTargetIdentity
    credential: CredentialProvenance
    delivery_kind: ProfiledDeliveryKind
    final_outcome: FinalOutcome
    artifacts: tuple[AuditArtifactReference, ...] = Field(min_length=1, max_length=3)
    planning_result_digest: Sha256
    artifact_bytes: ProfiledArtifactByteDigests
    authorization: ProfiledHumanAuthorization | None = None
    assurance: ProfiledAssuranceCorrelation | None = None

    def calculated_digest(self) -> str:
        return sha256_identity(
            canonical_json_bytes(self.model_dump(mode="json", exclude={"digest"}))
        )

    @model_validator(mode="after")
    def consistent_envelope(self) -> ProfiledDeliveryAuditRecord:
        if (
            self.generated_at.tzinfo is None
            or self.generated_at.utcoffset() != timedelta(0)
        ):
            raise ValueError("profiled audit timestamp must be timezone-aware UTC")
        if (
            self.git.repository != PROFILED_REPOSITORY
            or self.buildkite.step_key != "profiled-deploy"
        ):
            raise ValueError("profiled delivery source/step rejected")
        if (
            self.target.interface is None
            or self.credential.device != self.target.device
            or self.credential.source != "openbao"
        ):
            raise ValueError("profiled audit target/credential binding rejected")
        kinds = [ref.kind for ref in self.artifacts]
        expected = (
            {
                AuditArtifactKind.PROFILED_DEPLOYMENT_PLAN,
                AuditArtifactKind.PROFILED_PROMOTION,
                AuditArtifactKind.PROFILED_CHANGE_RECORD,
            }
            if self.delivery_kind is ProfiledDeliveryKind.EXECUTION
            else {AuditArtifactKind.PROFILED_COMPLIANCE_RECORD}
        )
        if set(kinds) != expected or kinds != sorted(expected, key=str):
            raise ValueError("profiled audit artifact family rejected")
        if any(ref.schema_version != "2" for ref in self.artifacts):
            raise ValueError("profiled audit requires schema-v2 artifacts")
        refs = {ref.kind: ref for ref in self.artifacts}
        if self.delivery_kind is ProfiledDeliveryKind.EXECUTION:
            if (
                self.final_outcome is FinalOutcome.COMPLIANT
                or self.authorization is None
                or self.assurance is None
                or self.artifact_bytes.promotion is None
                or self.artifact_bytes.execution is None
                or self.planning_result_digest
                != refs[AuditArtifactKind.PROFILED_DEPLOYMENT_PLAN].sha256
                or self.authorization.promotion_digest
                != refs[AuditArtifactKind.PROFILED_PROMOTION].sha256
            ):
                raise ValueError("profiled execution correlation is incomplete")
        elif (
            self.final_outcome is not FinalOutcome.COMPLIANT
            or self.authorization is not None
            or self.assurance is not None
            or self.artifact_bytes.promotion is not None
            or self.artifact_bytes.execution is not None
            or self.planning_result_digest
            != refs[AuditArtifactKind.PROFILED_COMPLIANCE_RECORD].sha256
        ):
            raise ValueError("profiled compliance cannot carry execution authority")
        if self.digest != self.calculated_digest():
            raise ValueError("profiled audit digest rejected")
        return self

    def byte_digests_by_kind(self) -> dict[AuditArtifactKind, str]:
        if self.delivery_kind is ProfiledDeliveryKind.COMPLIANCE:
            return {
                AuditArtifactKind.PROFILED_COMPLIANCE_RECORD: (
                    self.artifact_bytes.planning
                )
            }
        # The validated execution variant requires all three non-null hashes.
        assert self.artifact_bytes.promotion is not None
        assert self.artifact_bytes.execution is not None
        return {
            AuditArtifactKind.PROFILED_DEPLOYMENT_PLAN: self.artifact_bytes.planning,
            AuditArtifactKind.PROFILED_PROMOTION: self.artifact_bytes.promotion,
            AuditArtifactKind.PROFILED_CHANGE_RECORD: self.artifact_bytes.execution,
        }


def profiled_audit_record_with_digest(**values: object) -> ProfiledDeliveryAuditRecord:
    """Bind the canonical envelope after validating its nested typed inputs."""
    # Construct only to calculate; the final object always passes full validation.
    fields = ProfiledDeliveryAuditRecord.model_fields
    parsed = {
        key: TypeAdapter(fields[key].annotation).validate_python(value)
        for key, value in values.items()
        if key in fields and key != "digest"
    }
    if set(values) - set(fields):
        raise ValueError("unknown profiled audit fields")
    unsigned = ProfiledDeliveryAuditRecord.model_construct(
        **parsed, digest="sha256:" + "0" * 64
    )
    return ProfiledDeliveryAuditRecord.model_validate(
        {**unsigned.model_dump(mode="json"), "digest": unsigned.calculated_digest()}
    )


def verify_profiled_audit_artifacts(
    record: ProfiledDeliveryAuditRecord,
    artifacts: Mapping[AuditArtifactKind, BaseModel],
) -> None:
    """Correlate validated store artifacts without executing a write."""
    if set(artifacts) != {ref.kind for ref in record.artifacts}:
        raise ValueError("profiled durable artifact set rejected")
    planning = artifacts.get(
        AuditArtifactKind.PROFILED_DEPLOYMENT_PLAN
    ) or artifacts.get(AuditArtifactKind.PROFILED_COMPLIANCE_RECORD)
    if not isinstance(planning, (ProfiledDeploymentPlan, ProfiledComplianceRecord)):
        raise ValueError("profiled durable planning result rejected")
    if (
        planning.change_id != record.change_id
        or planning.device_identity != record.target.device
        or planning.interface.interface != record.target.interface
        or planning.credential_source != record.credential.source
        or planning.credential_reference != record.credential.reference
        or planning.digest != record.planning_result_digest
    ):
        raise ValueError("profiled durable planning correlation rejected")
    if record.delivery_kind is ProfiledDeliveryKind.COMPLIANCE:
        if not isinstance(planning, ProfiledComplianceRecord):
            raise ValueError("profiled durable compliance type rejected")
        return
    promotion = artifacts[AuditArtifactKind.PROFILED_PROMOTION]
    execution = artifacts[AuditArtifactKind.PROFILED_CHANGE_RECORD]
    if (
        not isinstance(planning, ProfiledDeploymentPlan)
        or not isinstance(promotion, ProfiledPromotion)
        or not isinstance(execution, ProfiledChangeRecord)
    ):
        raise ValueError("profiled durable execution types rejected")
    verify_profiled_record_plan(execution, planning)
    assert record.assurance is not None and record.authorization is not None
    if (
        promotion.build_id != str(record.buildkite.build_id)
        or promotion.commit != record.git.commit
        or promotion.change_id != record.change_id
        or promotion.target != planning.target
        or promotion.device_identity != record.target.device
        or promotion.plan_digest != planning.digest
        or promotion.plan_artifact_digest != record.artifact_bytes.planning
        or promotion.digest != record.authorization.promotion_digest
        or promotion.validation_digest != record.assurance.validation_digest
        or promotion.batfish_digest != record.assurance.batfish_digest
        or promotion.cml_digest != record.assurance.cml_digest
        or execution.final_outcome is not record.final_outcome
    ):
        raise ValueError("profiled durable execution correlation rejected")
