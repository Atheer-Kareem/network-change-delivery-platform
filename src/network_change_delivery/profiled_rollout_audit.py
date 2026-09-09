"""Distinct append-only rollout correlation models; historical envelopes unchanged."""

from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, model_validator

from network_change_delivery.architecture_contracts import (
    GitCommit,
    NetBoxInterfaceIdentity,
    Sha256Digest,
)
from network_change_delivery.audit import canonical_json_bytes, sha256_identity
from network_change_delivery.configuration_observation import OxidizedObservation
from network_change_delivery.models import FinalOutcome
from network_change_delivery.profiled_configuration_observation import (
    SUCCESS,
    node_for_target,
    overall_status,
)
from network_change_delivery.profiled_rollout import MAX_MEMBERS, DeviceIdentity

ROLLOUT_DURABLE_METADATA = "profiled-rollout-durable-publication"
CHRONOLOGY_NAMESPACE = UUID("9f29f54c-f239-58c9-b28e-d604a3fa86b1")


def child_record_id(parent_id, device):
    return uuid5(UUID(str(parent_id)), device)


def chronology_record_id(child_id):
    return uuid5(UUID(str(child_id)), str(CHRONOLOGY_NAMESPACE))


class SignedRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal["1"] = "1"
    digest: Sha256Digest

    def calculated_digest(self):
        return sha256_identity(
            canonical_json_bytes(self.model_dump(mode="json", exclude={"digest"}))
        )

    @model_validator(mode="after")
    def signed(self):
        if self.digest != self.calculated_digest():
            raise ValueError("rollout evidence digest rejected")
        return self


class RolloutOutcome(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    STOPPED = "STOPPED"
    PARTIAL = "PARTIAL"
    FINAL_VALIDATION_FAILED = "FINAL_VALIDATION_FAILED"


class RecordReference(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    record_id: UUID
    digest: Sha256Digest


class RolloutChildBinding(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    device_identity: DeviceIdentity
    interface_identity: NetBoxInterfaceIdentity
    kind: Literal["DEPLOYABLE", "COMPLIANT"]
    artifact_digest: Sha256Digest
    result_digest: Sha256Digest


class ProfiledRolloutChildAuditRecord(SignedRecord):
    record_type: Literal["profiled_rollout_child_audit_record"] = (
        "profiled_rollout_child_audit_record"
    )
    record_id: UUID
    parent_record_id: UUID
    build_id: UUID
    job_id: UUID
    source_commit: GitCommit
    parent_digest: Sha256Digest
    promotion_digest: Sha256Digest
    authorization_digest: Sha256Digest
    preflight_digest: Sha256Digest
    child: RolloutChildBinding
    cohort_kind: Literal["CANARY", "WAVE"]
    cohort_index: int = Field(ge=0, le=MAX_MEMBERS)
    execution_order: int = Field(ge=0, lt=MAX_MEMBERS)
    execution_attempted: bool
    execution_digest: Sha256Digest | None
    final_outcome: FinalOutcome | None
    pre_status: str | None
    post_status: str | None

    @model_validator(mode="after")
    def correlated(self):
        if (
            self.record_id
            != child_record_id(self.parent_record_id, self.child.device_identity)
            or self.job_id != self.parent_record_id
            or self.child.kind != "DEPLOYABLE"
            or (self.execution_digest is None) != (self.final_outcome is None)
            or (not self.execution_attempted and self.execution_digest is not None)
        ):
            raise ValueError("rollout child correlation rejected")
        return self


class ProfiledRolloutChronologyRecord(SignedRecord):
    record_type: Literal["profiled_rollout_chronology_record"] = (
        "profiled_rollout_chronology_record"
    )
    record_id: UUID
    child_audit: RecordReference
    device_identity: DeviceIdentity
    pre: OxidizedObservation
    post: OxidizedObservation
    relationship: Literal["TEMPORALLY_BRACKETED"] = "TEMPORALLY_BRACKETED"
    causality: Literal["NOT_PROVEN"] = "NOT_PROVEN"
    overall_status: Literal["SUCCEEDED", "PARTIAL", "AMBIGUOUS"]

    @model_validator(mode="after")
    def correlated(self):
        if (
            self.record_id != chronology_record_id(self.child_audit.record_id)
            or self.pre.status not in SUCCESS
            or self.pre.completed_at is None
            or self.pre.after_revision is None
            or self.pre.completed_at > self.post.requested_at
            or (
                self.post.status in SUCCESS
                and self.post.before_revision != self.pre.after_revision
            )
            or self.overall_status != overall_status(self.post.status).value
        ):
            raise ValueError("rollout chronology bracket rejected")
        for attempt in (self.pre, self.post):
            for revision in (attempt.before_revision, attempt.after_revision):
                if (
                    revision is not None
                    and revision.config_path
                    != "managed/" + node_for_target(self.device_identity)
                ):
                    raise ValueError("rollout chronology target rejected")
        return self


class ProfiledRolloutAuditRecord(SignedRecord):
    record_type: Literal["profiled_rollout_audit_record"] = (
        "profiled_rollout_audit_record"
    )
    record_id: UUID
    pipeline_id: UUID
    build_id: UUID
    build_number: int = Field(gt=0)
    job_id: UUID
    source_commit: GitCommit
    generated_at: datetime
    change_id: str = Field(min_length=1, max_length=100)
    parent_digest: Sha256Digest
    parent_artifact_digest: Sha256Digest
    promotion_digest: Sha256Digest
    promotion_artifact_digest: Sha256Digest
    authorization_digest: Sha256Digest
    unblocker_id: UUID
    preflight_digest: Sha256Digest | None
    children: tuple[RolloutChildBinding, ...] = Field(
        min_length=1, max_length=MAX_MEMBERS
    )
    canaries: tuple[DeviceIdentity, ...]
    waves: tuple[tuple[DeviceIdentity, ...], ...]
    child_records: tuple[RecordReference, ...]
    chronology_records: tuple[RecordReference, ...]
    compliant: tuple[DeviceIdentity, ...]
    attempted: tuple[DeviceIdentity, ...]
    successful: tuple[DeviceIdentity, ...]
    untouched: tuple[DeviceIdentity, ...]
    stopping_member: DeviceIdentity | None
    stopping_reason: (
        Literal[
            "PREFLIGHT",
            "PRE_CHRONOLOGY",
            "CHILD_NON_SUCCESS",
            "CHILD_EXECUTION_UNCERTAIN",
            "CHILD_EVIDENCE",
            "FINAL_VALIDATION",
        ]
        | None
    )
    stopping_outcome: FinalOutcome | None
    completed_canaries: tuple[DeviceIdentity, ...]
    completed_waves: tuple[tuple[DeviceIdentity, ...], ...]
    remaining_waves: tuple[tuple[DeviceIdentity, ...], ...]
    final_validation_digest: Sha256Digest | None
    final_validation_status: Literal["PASSED", "FAILED"] | None
    outcome: RolloutOutcome

    @model_validator(mode="after")
    def correlated(self):
        selected = tuple(c.device_identity for c in self.children)
        deployable = tuple(
            c.device_identity for c in self.children if c.kind == "DEPLOYABLE"
        )
        order = self.canaries + tuple(d for w in self.waves for d in w)
        if (
            self.record_id != self.job_id
            or self.generated_at.tzinfo is None
            or len({r.record_id for r in self.child_records}) != len(self.child_records)
            or len({r.record_id for r in self.chronology_records})
            != len(self.chronology_records)
            or len(set(selected)) != len(selected)
            or len(set(order)) != len(order)
            or set(order) != set(deployable)
            or self.compliant
            != tuple(c.device_identity for c in self.children if c.kind == "COMPLIANT")
            or self.attempted != order[: len(self.attempted)]
            or self.successful != self.attempted[: len(self.successful)]
            or self.untouched != tuple(d for d in deployable if d not in self.attempted)
            or self.completed_canaries
            != tuple(d for d in self.canaries if d in self.successful)
            or self.completed_waves
            != tuple(w for w in self.waves if all(d in self.successful for d in w))
            or self.remaining_waves
            != tuple(w for w in self.waves if not all(d in self.successful for d in w))
            or (self.final_validation_digest is None)
            != (self.final_validation_status is None)
            or (self.preflight_digest is None and self.attempted)
            or (
                self.stopping_member is not None
                and self.stopping_member not in deployable
            )
        ):
            raise ValueError("rollout parent population/outcome rejected")
        all_succeeded = len(self.successful) == len(deployable)
        if self.outcome == RolloutOutcome.SUCCEEDED:
            valid = (
                all_succeeded
                and self.final_validation_status == "PASSED"
                and self.stopping_reason is None
            )
        elif self.outcome == RolloutOutcome.FINAL_VALIDATION_FAILED:
            valid = (
                all_succeeded
                and self.final_validation_status == "FAILED"
                and self.stopping_reason == "FINAL_VALIDATION"
            )
        elif self.outcome == RolloutOutcome.PARTIAL:
            valid = bool(self.successful) and self.stopping_reason is not None
        else:
            valid = not self.successful and self.stopping_reason is not None
        if not valid:
            raise ValueError("rollout parent outcome truth rejected")
        return self


class ProfiledRolloutDurablePublicationReceipt(SignedRecord):
    record_type: Literal["profiled_rollout_durable_publication"] = (
        "profiled_rollout_durable_publication"
    )
    record_id: UUID
    record_digest: Sha256Digest
    build_id: UUID
    source_commit: GitCommit
    outcome: RolloutOutcome
