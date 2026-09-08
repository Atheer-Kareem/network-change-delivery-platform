"""Current profiled delivery chronology: metadata bracketing, never causality."""

from __future__ import annotations

import os
import stat
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4, uuid5

from pydantic import BaseModel, ConfigDict, TypeAdapter, model_validator

from network_change_delivery.audit import (
    GitCommit,
    NetBoxDeviceIdentity,
    Sha256,
    canonical_json_bytes,
    sha256_identity,
)
from network_change_delivery.configuration_observation import (
    ObservationFailureCategory as Failure,
)
from network_change_delivery.configuration_observation import (
    ObservationOverallStatus as Overall,
)
from network_change_delivery.configuration_observation import (
    ObservationRelationship,
    OxidizedNodeName,
    OxidizedObservation,
    OxidizedRevision,
    _is_utc,
)
from network_change_delivery.configuration_observation import (
    ObservationStatus as Status,
)
from network_change_delivery.oxidized_controller import (
    CollectionOutcome,
    OxidizedController,
)
from network_change_delivery.oxidized_history import (
    OXIDIZED_GROUP,
    OXIDIZED_REPOSITORY_IDENTITY,
    OxidizedHistoryError,
    OxidizedHistoryRepository,
)
from network_change_delivery.oxidized_observation import (
    API_URL,
    DEFAULT_TRUST_ROOT,
    STATE_ROOT,
    OxidizedChronologyError,
    OxidizedRevisionUnavailableError,
    bind_collection_result,
    verified_container_id,
)
from network_change_delivery.profiled_audit import (
    ProfiledDeliveryAuditRecord,
    ProfiledDeliveryKind,
)
from network_change_delivery.profiled_planning import ProfiledDeploymentPlan

CHRONOLOGY_METADATA = "profiled-configuration-chronology"
# Stable UUIDv5 namespace reserved for one chronology child per profiled parent.
CHRONOLOGY_NAMESPACE = UUID("e6821f34-c371-518e-911e-413f24b7d572")
MAX_ATTEMPT_BYTES = 64 * 1024
SUCCESS = frozenset({Status.CHANGED, Status.UNCHANGED})


def chronology_id(parent_id: UUID) -> UUID:
    return uuid5(CHRONOLOGY_NAMESPACE, str(UUID(str(parent_id))))


def canonical_oxidized_node(plan: ProfiledDeploymentPlan) -> str:
    plan = ProfiledDeploymentPlan.model_validate(plan.model_dump())
    return node_for_target(plan.device_identity)


def node_for_target(target: str) -> str:
    identity = TypeAdapter(NetBoxDeviceIdentity).validate_python(target)
    return TypeAdapter(OxidizedNodeName).validate_python(
        "netbox-device-" + identity.rsplit(":", 1)[1]
    )


def overall_status(post: Status) -> Overall:
    if post in SUCCESS:
        return Overall.SUCCEEDED
    return Overall.AMBIGUOUS if post is Status.AMBIGUOUS else Overall.PARTIAL


class ProfiledDeliveryAuditReference(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    record_type: Literal["profiled_delivery_audit_record"] = (
        "profiled_delivery_audit_record"
    )
    schema_version: Literal["1"] = "1"
    record_id: UUID
    digest: Sha256


class ProfiledConfigurationObservationRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal["1"] = "1"
    record_type: Literal["profiled_configuration_observation_record"] = (
        "profiled_configuration_observation_record"
    )
    observation_record_id: UUID
    generated_at: datetime
    digest: Sha256
    parent_audit: ProfiledDeliveryAuditReference
    repository: Literal["oxidized:ncdp-lab-actual-state"]
    target: NetBoxDeviceIdentity
    oxidized_node: OxidizedNodeName
    group: Literal["managed"]
    pre_observation: OxidizedObservation
    post_observation: OxidizedObservation
    relationship: Literal[ObservationRelationship.TEMPORALLY_BRACKETED] = (
        ObservationRelationship.TEMPORALLY_BRACKETED
    )
    causality: Literal["NOT_PROVEN"] = "NOT_PROVEN"
    overall_status: Overall

    def calculated_digest(self) -> str:
        return sha256_identity(
            canonical_json_bytes(self.model_dump(mode="json", exclude={"digest"}))
        )

    @model_validator(mode="after")
    def consistent(self):
        pre, post = self.pre_observation, self.post_observation
        if (
            not _is_utc(self.generated_at)
            or self.observation_record_id != chronology_id(self.parent_audit.record_id)
            or self.oxidized_node != node_for_target(self.target)
            or pre.status not in SUCCESS
            or pre.completed_at is None
            or pre.after_revision is None
            or pre.completed_at > post.requested_at
            or self.generated_at < (post.completed_at or post.requested_at)
            or (post.status in SUCCESS and post.before_revision != pre.after_revision)
            or self.overall_status is not overall_status(post.status)
            or self.digest != self.calculated_digest()
        ):
            raise ValueError("profiled chronology correlation rejected")
        expected_path = f"{self.group}/{self.oxidized_node}"
        for attempt in (pre, post):
            for revision in (attempt.before_revision, attempt.after_revision):
                if revision is not None and revision.config_path != expected_path:
                    raise ValueError("profiled chronology revision target rejected")
        return self


def _signed(model, values):
    fields = model.model_fields
    normalized = {
        k: TypeAdapter(fields[k].annotation).validate_python(v)
        for k, v in values.items()
    }
    # Include defaults in the digest, without bypassing final model validation.
    for k, f in fields.items():
        if k not in normalized and k != "digest" and not f.is_required():
            normalized[k] = f.default
    encoded = {
        k: TypeAdapter(fields[k].annotation).dump_python(v, mode="json")
        for k, v in normalized.items()
    }
    return model.model_validate(
        {**encoded, "digest": sha256_identity(canonical_json_bytes(encoded))}
    )


def build_profiled_observation_record(parent, pre, post, *, generated_at):
    parent = ProfiledDeliveryAuditRecord.model_validate(parent.model_dump())
    if parent.delivery_kind is not ProfiledDeliveryKind.EXECUTION:
        raise ValueError("chronology requires current execution parent")
    return _signed(
        ProfiledConfigurationObservationRecord,
        {
            "observation_record_id": chronology_id(parent.record_id),
            "generated_at": generated_at,
            "parent_audit": ProfiledDeliveryAuditReference(
                record_id=parent.record_id, digest=parent.digest
            ),
            "repository": OXIDIZED_REPOSITORY_IDENTITY,
            "target": parent.target.device,
            "oxidized_node": node_for_target(parent.target.device),
            "group": OXIDIZED_GROUP,
            "pre_observation": pre,
            "post_observation": post,
            "overall_status": overall_status(post.status),
        },
    )


class ProfiledChronologyPublicationReceipt(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal["1"] = "1"
    receipt_type: Literal["profiled_chronology_publication"] = (
        "profiled_chronology_publication"
    )
    build_id: UUID
    commit: GitCommit
    job_id: UUID
    parent_record_id: UUID
    parent_digest: Sha256
    chronology_record_id: UUID
    chronology_digest: Sha256
    target: NetBoxDeviceIdentity
    delivery_kind: Literal[ProfiledDeliveryKind.EXECUTION] = (
        ProfiledDeliveryKind.EXECUTION
    )
    relationship: Literal[ObservationRelationship.TEMPORALLY_BRACKETED] = (
        ObservationRelationship.TEMPORALLY_BRACKETED
    )
    causality: Literal["NOT_PROVEN"] = "NOT_PROVEN"
    overall_status: Overall
    pre_status: Status
    post_status: Status
    digest: Sha256

    def calculated_digest(self):
        return sha256_identity(
            canonical_json_bytes(self.model_dump(mode="json", exclude={"digest"}))
        )

    @model_validator(mode="after")
    def consistent(self):
        if (
            self.parent_record_id != self.job_id
            or self.chronology_record_id != chronology_id(self.parent_record_id)
            or self.pre_status not in SUCCESS
            or self.overall_status is not overall_status(self.post_status)
            or self.digest != self.calculated_digest()
        ):
            raise ValueError("profiled chronology receipt rejected")
        return self

    @classmethod
    def from_record(cls, parent, child):
        parent = ProfiledDeliveryAuditRecord.model_validate(parent.model_dump())
        child = ProfiledConfigurationObservationRecord.model_validate(
            child.model_dump()
        )
        if (
            parent.delivery_kind is not ProfiledDeliveryKind.EXECUTION
            or child.parent_audit.record_id != parent.record_id
            or child.parent_audit.digest != parent.digest
            or child.target != parent.target.device
        ):
            raise ValueError("profiled chronology receipt parent rejected")
        return _signed(
            cls,
            {
                "build_id": parent.buildkite.build_id,
                "commit": parent.git.commit,
                "job_id": parent.buildkite.job_id,
                "parent_record_id": parent.record_id,
                "parent_digest": parent.digest,
                "chronology_record_id": child.observation_record_id,
                "chronology_digest": child.digest,
                "target": child.target,
                "overall_status": child.overall_status,
                "pre_status": child.pre_observation.status,
                "post_status": child.post_observation.status,
            },
        )

    def verify_delivery(self, context, parent_receipt, target):
        if (
            str(self.build_id) != context.build_id
            or self.commit != context.commit
            or self.job_id != parent_receipt.job_id
            or self.parent_record_id != parent_receipt.record_id
            or self.parent_digest != parent_receipt.record_digest
            or self.target != target
            or parent_receipt.delivery_kind is not ProfiledDeliveryKind.EXECUTION
        ):
            raise ValueError("profiled chronology receipt delivery rejected")


def _failure(category, *, before=None, request=None, request_id=None):
    status = (
        Status.AMBIGUOUS
        if category in {Failure.CONCURRENT_COLLECTION, Failure.INCONSISTENT_EVIDENCE}
        else Status.TIMED_OUT
        if category is Failure.COLLECTION_TIMED_OUT
        else Status.FAILED
    )
    return OxidizedObservation(
        request_id=request_id or uuid4(),
        requested_at=request or datetime.now(UTC),
        completed_at=datetime.now(UTC),
        status=status,
        before_revision=before,
        failure_category=category,
    )


def capture_attempt(
    controller, history, node, *, expected_before: OxidizedRevision | None = None
):
    """Collect once from an existing baseline, never silently rebase POST."""
    try:
        before = history.latest_revision(node)
    except (OSError, OxidizedHistoryError):
        return _failure(Failure.HISTORY_UNAVAILABLE)
    if before is None:
        return _failure(Failure.HISTORY_UNAVAILABLE)
    if expected_before is not None and before != expected_before:
        return _failure(Failure.INCONSISTENT_EVIDENCE, before=before)
    try:
        collection = controller.collect(node)
    except (OSError, ValueError):
        return _failure(Failure.SOURCE_UNAVAILABLE, before=before)
    if collection.outcome is not CollectionOutcome.SUCCEEDED:
        mapping = {
            CollectionOutcome.COLLECTION_FAILED: Failure.COLLECTION_FAILED,
            CollectionOutcome.COLLECTION_TIMED_OUT: Failure.COLLECTION_TIMED_OUT,
            CollectionOutcome.CONCURRENT_COLLECTION: Failure.CONCURRENT_COLLECTION,
            CollectionOutcome.INCONSISTENT_EVIDENCE: Failure.INCONSISTENT_EVIDENCE,
        }
        category = mapping[collection.outcome]
        attempt = _failure(category, before=before, request=collection.requested_at)
        return OxidizedObservation.model_validate(
            {
                **attempt.model_dump(),
                "request_id": collection.request_id,
                "completed_at": collection.completed_at,
            }
        )
    try:
        bound = bind_collection_result(history, node, before, collection)
    except OxidizedChronologyError:
        return _failure(
            Failure.INCONSISTENT_EVIDENCE,
            before=before,
            request=collection.requested_at,
            request_id=collection.request_id,
        )
    except (OxidizedHistoryError, OxidizedRevisionUnavailableError):
        return _failure(
            Failure.HISTORY_UNAVAILABLE,
            before=before,
            request=collection.requested_at,
            request_id=collection.request_id,
        )
    return OxidizedObservation(
        request_id=collection.request_id,
        requested_at=collection.requested_at,
        completed_at=bound.settled_at,
        status=Status.CHANGED if bound.revision_changed else Status.UNCHANGED,
        before_revision=before,
        after_revision=bound.after,
    )


def capture_profiled_attempt(plan, *, expected_before=None):
    node = canonical_oxidized_node(plan)
    try:
        controller = OxidizedController(
            API_URL,
            STATE_ROOT / "runtime/collection-ready.json",
            STATE_ROOT / "control/locks",
            verified_container_id(),
            trust_root=DEFAULT_TRUST_ROOT,
        )
    except (OSError, ValueError):
        return _failure(Failure.SOURCE_UNAVAILABLE)
    try:
        history = OxidizedHistoryRepository(STATE_ROOT / "config-history.git")
    except (OSError, ValueError):
        return _failure(Failure.HISTORY_UNAVAILABLE)
    return capture_attempt(controller, history, node, expected_before=expected_before)


def validate_pre(
    plan: ProfiledDeploymentPlan, attempt: OxidizedObservation
) -> OxidizedObservation:
    attempt = OxidizedObservation.model_validate(attempt.model_dump())
    path = f"{OXIDIZED_GROUP}/{canonical_oxidized_node(plan)}"
    if (
        attempt.status not in SUCCESS
        or attempt.before_revision is None
        or attempt.after_revision is None
        or attempt.completed_at is None
        or attempt.before_revision.config_path != path
        or attempt.after_revision.config_path != path
    ):
        raise ValueError("successful target-bound PRE required")
    return attempt


def _private_parent(path):
    if not path.is_absolute() or path.resolve() != path:
        raise ValueError("profiled attempt path rejected")
    info = path.lstat()
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) != 0o700
    ):
        raise ValueError("profiled attempt directory rejected")


def persist_attempt_file(path: Path, attempt: OxidizedObservation):
    _private_parent(path.parent)
    attempt = OxidizedObservation.model_validate(attempt.model_dump())
    content = canonical_json_bytes(attempt.model_dump(mode="json"))
    if not 0 < len(content) <= MAX_ATTEMPT_BYTES:
        raise ValueError("profiled attempt size rejected")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def load_attempt_file(path: Path):
    _private_parent(path.parent)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_nlink != 1
            or not 0 < info.st_size <= MAX_ATTEMPT_BYTES
        ):
            raise ValueError("profiled attempt file rejected")
        content = stream.read(MAX_ATTEMPT_BYTES + 1)
    attempt = OxidizedObservation.model_validate_json(content)
    if canonical_json_bytes(attempt.model_dump(mode="json")) != content:
        raise ValueError("profiled attempt canonical bytes rejected")
    return attempt
