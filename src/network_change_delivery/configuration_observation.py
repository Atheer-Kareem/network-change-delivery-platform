"""Typed, secret-free observed-configuration correlation contracts."""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from network_change_delivery.audit import (
    NetBoxDeviceIdentity,
    Sha256,
    canonical_json_bytes,
    sha256_identity,
)

OxidizedObjectId = Annotated[
    str, StringConstraints(pattern=r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
]
OxidizedRepositoryIdentity = Annotated[
    str,
    StringConstraints(
        min_length=12,
        max_length=255,
        pattern=r"^oxidized:[a-z0-9]+(?:[._/-][a-z0-9]+)*$",
    ),
]
OxidizedNodeName = Annotated[
    str,
    StringConstraints(
        min_length=15,
        max_length=64,
        pattern=r"^netbox-device-[1-9][0-9]*$",
    ),
]
OxidizedGroupName = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=64,
        pattern=r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$",
    ),
]


def _is_utc(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() == timedelta(0)


class ObservationStatus(StrEnum):
    """Result of one bounded observed-configuration attempt."""

    CHANGED = "CHANGED"
    UNCHANGED = "UNCHANGED"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"
    AMBIGUOUS = "AMBIGUOUS"


class ObservationFailureCategory(StrEnum):
    """Allowlisted secret-free failure classifications, never raw error text."""

    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
    NODE_UNAVAILABLE = "NODE_UNAVAILABLE"
    AUTHENTICATION_FAILED = "AUTHENTICATION_FAILED"
    CONNECTION_FAILED = "CONNECTION_FAILED"
    COLLECTION_FAILED = "COLLECTION_FAILED"
    COLLECTION_TIMED_OUT = "COLLECTION_TIMED_OUT"
    OUTPUT_FAILED = "OUTPUT_FAILED"
    HISTORY_UNAVAILABLE = "HISTORY_UNAVAILABLE"
    CONCURRENT_COLLECTION = "CONCURRENT_COLLECTION"
    INCONSISTENT_EVIDENCE = "INCONSISTENT_EVIDENCE"


class ObservationRelationship(StrEnum):
    """Temporal relationship between observations and one delivery audit."""

    TEMPORALLY_BRACKETED = "TEMPORALLY_BRACKETED"
    POST_ONLY = "POST_ONLY"
    UNCORRELATED = "UNCORRELATED"


class ObservationOverallStatus(StrEnum):
    """Bounded aggregate status without implying deployment success."""

    SUCCEEDED = "SUCCEEDED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    AMBIGUOUS = "AMBIGUOUS"


class ParentAuditReference(BaseModel):
    """Immutable identity and integrity link to one ChangeAuditRecord."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    record_id: UUID
    digest: Sha256


class OxidizedRevision(BaseModel):
    """Metadata-only identity of one configuration in private Git history."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    commit: OxidizedObjectId
    config_path: str = Field(min_length=1, max_length=255)
    blob: OxidizedObjectId
    collected_at: datetime

    @model_validator(mode="after")
    def validate_revision(self) -> OxidizedRevision:
        path = PurePosixPath(self.config_path)
        if (
            len(self.commit) != len(self.blob)
            or self.config_path == "."
            or path.is_absolute()
            or path.as_posix() != self.config_path
            or any(part in {"", ".", ".."} for part in path.parts)
            or any(part.startswith(".") for part in path.parts)
            or any(
                not character.isascii()
                or not (character.isalnum() or character in "._-/")
                for character in self.config_path
            )
            or not _is_utc(self.collected_at)
        ):
            raise ValueError("Oxidized revision metadata is invalid")
        return self


class OxidizedObservation(BaseModel):
    """One bounded request and its verified metadata-only result."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    request_id: UUID
    requested_at: datetime
    completed_at: datetime | None = None
    status: ObservationStatus
    before_revision: OxidizedRevision | None = None
    after_revision: OxidizedRevision | None = None
    failure_category: ObservationFailureCategory | None = None

    @model_validator(mode="after")
    def validate_attempt(self) -> OxidizedObservation:
        if not _is_utc(self.requested_at) or (
            self.completed_at is not None and not _is_utc(self.completed_at)
        ):
            raise ValueError("observation timestamps must be timezone-aware UTC")
        if self.completed_at is not None and self.completed_at < self.requested_at:
            raise ValueError("observation completion precedes request")
        if (
            self.before_revision is not None
            and self.before_revision.collected_at > self.requested_at
        ):
            raise ValueError("before revision was collected after the request")
        for revision in (self.before_revision, self.after_revision):
            if revision is not None and revision.collected_at > (
                self.completed_at or self.requested_at
            ):
                raise ValueError("observation revision timestamp is inconsistent")

        successful = self.status in {
            ObservationStatus.CHANGED,
            ObservationStatus.UNCHANGED,
        }
        if successful:
            if (
                self.completed_at is None
                or self.before_revision is None
                or self.after_revision is None
                or self.failure_category is not None
            ):
                raise ValueError("successful observation evidence is incomplete")
            before = self.before_revision
            after = self.after_revision
            same_identity = (
                before.commit == after.commit
                and before.config_path == after.config_path
                and before.blob == after.blob
            )
            if self.status is ObservationStatus.UNCHANGED and not same_identity:
                raise ValueError("unchanged observation has conflicting revisions")
            if self.status is ObservationStatus.CHANGED and (
                before.config_path != after.config_path
                or before.blob == after.blob
                or len(before.commit) != len(after.commit)
                or after.collected_at < self.requested_at
            ):
                raise ValueError("changed observation has inconsistent revisions")
            return self

        if self.failure_category is None:
            raise ValueError("unsuccessful observation requires a failure category")
        ambiguous_categories = {
            ObservationFailureCategory.CONCURRENT_COLLECTION,
            ObservationFailureCategory.INCONSISTENT_EVIDENCE,
        }
        if self.status is ObservationStatus.AMBIGUOUS:
            if self.failure_category not in ambiguous_categories:
                raise ValueError("ambiguous observation category is inconsistent")
        elif self.status is ObservationStatus.FAILED and self.failure_category in {
            ObservationFailureCategory.COLLECTION_TIMED_OUT,
            *ambiguous_categories,
        }:
            raise ValueError("failed observation category is inconsistent")
        if self.status in {ObservationStatus.FAILED, ObservationStatus.TIMED_OUT}:
            if self.after_revision is not None:
                raise ValueError("failed observation cannot claim an after revision")
            if self.status is ObservationStatus.FAILED and self.completed_at is None:
                raise ValueError("failed observation requires completion time")
            if (
                self.status is ObservationStatus.TIMED_OUT
                and self.failure_category
                is not ObservationFailureCategory.COLLECTION_TIMED_OUT
            ):
                raise ValueError("timed-out observation category is inconsistent")
        return self


class ConfigurationObservationRecord(BaseModel):
    """Append-only follow-up metadata correlated to one delivery audit."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal["1"] = "1"
    observation_record_id: UUID
    generated_at: datetime
    digest: Sha256
    parent_audit: ParentAuditReference
    repository: OxidizedRepositoryIdentity
    target: NetBoxDeviceIdentity
    oxidized_node: OxidizedNodeName
    group: OxidizedGroupName | None = None
    pre_observation: OxidizedObservation | None = None
    post_observation: OxidizedObservation | None = None
    relationship: ObservationRelationship
    causality: Literal["NOT_PROVEN"] = "NOT_PROVEN"
    overall_status: ObservationOverallStatus

    @model_validator(mode="after")
    def validate_correlation(self) -> ConfigurationObservationRecord:
        if not _is_utc(self.generated_at):
            raise ValueError("observation record timestamp must be timezone-aware UTC")
        if self.pre_observation is None and self.post_observation is None:
            raise ValueError("observation record requires pre or post evidence")
        expected_node = self.target.removeprefix("netbox:dcim.device:")
        if self.oxidized_node != f"netbox-device-{expected_node}":
            raise ValueError("Oxidized node does not match stable NetBox identity")

        if self.relationship is ObservationRelationship.TEMPORALLY_BRACKETED:
            if self.pre_observation is None or self.post_observation is None:
                raise ValueError("temporally bracketed evidence requires pre and post")
            pre_end = self.pre_observation.completed_at
            if pre_end is None or pre_end > self.post_observation.requested_at:
                raise ValueError("temporally bracketed evidence is not ordered")
        elif self.relationship is ObservationRelationship.POST_ONLY:
            if self.pre_observation is not None or self.post_observation is None:
                raise ValueError("post-only relationship is inconsistent")
        elif self.post_observation is not None:
            raise ValueError("uncorrelated schema-1 evidence is pre-only")

        attempts = tuple(
            item
            for item in (self.pre_observation, self.post_observation)
            if item is not None
        )
        latest = max(item.completed_at or item.requested_at for item in attempts)
        if self.generated_at < latest:
            raise ValueError("observation record predates its evidence")
        statuses = {item.status for item in attempts}
        successes = statuses <= {
            ObservationStatus.CHANGED,
            ObservationStatus.UNCHANGED,
        }
        if ObservationStatus.AMBIGUOUS in statuses:
            expected = ObservationOverallStatus.AMBIGUOUS
        elif successes:
            expected = ObservationOverallStatus.SUCCEEDED
        elif statuses.isdisjoint(
            {ObservationStatus.CHANGED, ObservationStatus.UNCHANGED}
        ):
            expected = ObservationOverallStatus.FAILED
        else:
            expected = ObservationOverallStatus.PARTIAL
        if self.overall_status is not expected:
            raise ValueError("observation overall status is inconsistent")
        return self

    def digest_input(self) -> bytes:
        return canonical_json_bytes(self.model_dump(mode="json", exclude={"digest"}))

    def calculated_digest(self) -> str:
        return sha256_identity(self.digest_input())

    def verify_digest(self) -> bool:
        return self.digest == self.calculated_digest()


def observation_record_with_digest(**values: object) -> ConfigurationObservationRecord:
    """Construct and bind one canonical configuration-observation record."""

    unsigned = ConfigurationObservationRecord.model_validate(
        {**values, "digest": "sha256:" + "0" * 64}
    )
    return ConfigurationObservationRecord.model_validate(
        {**unsigned.model_dump(mode="json"), "digest": unsigned.calculated_digest()}
    )
