"""Protected Buildkite configuration-observation correlation boundaries."""

from __future__ import annotations

import os
import stat
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol
from uuid import UUID, uuid4

from pydantic import ValidationError

from network_change_delivery.audit import AuditArtifactKind, canonical_json_bytes
from network_change_delivery.audit_store import AuditStoreError
from network_change_delivery.buildkite_audit import (
    load_verified_promotion_artifacts,
    normalize_buildkite_repository,
)
from network_change_delivery.buildkite_deployment import (
    load_live_deployment_request_at_commit,
)
from network_change_delivery.buildkite_policy import BuildkiteDeploymentContext
from network_change_delivery.configuration_observation import (
    ConfigurationObservationRecord,
    ObservationFailureCategory,
    ObservationOverallStatus,
    ObservationRelationship,
    ObservationStatus,
    OxidizedRevision,
    observation_record_with_digest,
)
from network_change_delivery.configuration_observation import (
    OxidizedObservation as DurableOxidizedObservation,
)
from network_change_delivery.configuration_observation_store import (
    ConfigurationObservationStore,
)
from network_change_delivery.models import DeploymentPlan
from network_change_delivery.oxidized_controller import (
    CollectionOutcome,
    CollectionResult,
    OxidizedController,
)
from network_change_delivery.oxidized_history import (
    OXIDIZED_GROUP,
    OXIDIZED_REPOSITORY_IDENTITY,
    OxidizedHistoryError,
    OxidizedHistoryRepository,
)
from network_change_delivery.oxidized_host_trust import DEFAULT_TRUST_ROOT
from network_change_delivery.oxidized_observation import (
    API_URL,
    STATE_ROOT,
    OxidizedChronologyError,
    OxidizedObservation,
    OxidizedRevisionUnavailableError,
    bind_collection_result,
    verified_container_id,
)

MAX_ATTEMPT_BYTES = 64 * 1024
HISTORY_PATH = STATE_ROOT / "config-history.git"
READINESS_PATH = STATE_ROOT / "runtime" / "collection-ready.json"
LOCK_ROOT = STATE_ROOT / "control" / "locks"
SUPPORTED_TARGETS = {
    "netbox:dcim.device:1": "netbox-device-1",
    "netbox:dcim.device:2": "netbox-device-2",
}
SUCCESS_STATUSES = frozenset({ObservationStatus.CHANGED, ObservationStatus.UNCHANGED})


class BuildkiteConfigurationObservationError(ValueError):
    """Bounded protected-observation failure without raw provider text."""


class _Controller(Protocol):
    def collect(self, node: str) -> CollectionResult: ...


_FAILURE_MAP = {
    CollectionOutcome.COLLECTION_TIMED_OUT: (
        ObservationStatus.TIMED_OUT,
        ObservationFailureCategory.COLLECTION_TIMED_OUT,
    ),
    CollectionOutcome.CONCURRENT_COLLECTION: (
        ObservationStatus.AMBIGUOUS,
        ObservationFailureCategory.CONCURRENT_COLLECTION,
    ),
    CollectionOutcome.INCONSISTENT_EVIDENCE: (
        ObservationStatus.AMBIGUOUS,
        ObservationFailureCategory.INCONSISTENT_EVIDENCE,
    ),
    CollectionOutcome.COLLECTION_FAILED: (
        ObservationStatus.FAILED,
        ObservationFailureCategory.COLLECTION_FAILED,
    ),
}


def canonical_oxidized_node(plan: DeploymentPlan) -> str:
    """Derive the only reviewed node identity from stable promoted identity."""
    identity = plan.inventory_object_id or ""
    try:
        node = SUPPORTED_TARGETS[identity]
    except KeyError:
        raise BuildkiteConfigurationObservationError(
            "protected observation target is unsupported"
        ) from None
    if (
        plan.inventory_source != "netbox"
        or plan.credential_source != "openbao"
        or plan.credential_reference
        != f"openbao:kv-v2:ncdp/devices/{identity.rsplit(':', 1)[-1]}/ssh"
    ):
        raise BuildkiteConfigurationObservationError(
            "protected observation target provenance rejected"
        )
    return node


def verified_observation_plan(
    context: BuildkiteDeploymentContext,
    promotion: Path,
    checkout: Path,
) -> tuple[DeploymentPlan, str]:
    """Bind promoted plan, committed live request, and canonical node."""
    _manifest, plan, _assurance = load_verified_promotion_artifacts(promotion, context)
    request = load_live_deployment_request_at_commit(context.commit, root=checkout)
    if request is None:
        raise BuildkiteConfigurationObservationError(
            "protected observation live request unavailable"
        )
    try:
        request.verify_plan(plan)
    except ValueError:
        raise BuildkiteConfigurationObservationError(
            "protected observation plan/request mismatch"
        ) from None
    return plan, canonical_oxidized_node(plan)


def durable_success(observation: OxidizedObservation) -> DurableOxidizedObservation:
    """Convert one successful transient binding without configuration bytes."""
    if observation.before is None:
        raise BuildkiteConfigurationObservationError(
            "protected observation baseline revision unavailable"
        )
    collection = observation.collection
    return DurableOxidizedObservation(
        request_id=collection.request_id,
        requested_at=collection.requested_at,
        completed_at=collection.completed_at,
        status=(
            ObservationStatus.CHANGED
            if observation.revision_changed
            else ObservationStatus.UNCHANGED
        ),
        before_revision=observation.before,
        after_revision=observation.after,
    )


def durable_failure(
    collection: CollectionResult,
    before_revision: OxidizedRevision | None,
) -> DurableOxidizedObservation:
    """Map only reviewed controller outcomes into closed durable evidence."""
    try:
        status, category = _FAILURE_MAP[collection.outcome]
    except KeyError:
        raise BuildkiteConfigurationObservationError(
            "protected observation outcome is unclassifiable"
        ) from None
    try:
        return DurableOxidizedObservation(
            request_id=collection.request_id,
            requested_at=collection.requested_at,
            completed_at=collection.completed_at,
            status=status,
            before_revision=before_revision,
            failure_category=category,
        )
    except ValidationError:
        raise BuildkiteConfigurationObservationError(
            "protected observation failure evidence is incomplete"
        ) from None


def capture_attempt(
    controller: _Controller,
    history: OxidizedHistoryRepository,
    node: str,
) -> DurableOxidizedObservation:
    """Capture one attempt with an existing baseline required before collection."""
    try:
        before = history.latest_revision(node)
    except OxidizedHistoryError:
        raise BuildkiteConfigurationObservationError(
            "protected observation baseline revision unavailable"
        ) from None
    collection = controller.collect(node)
    if collection.outcome is not CollectionOutcome.SUCCEEDED:
        return durable_failure(collection, before)
    try:
        transient = bind_collection_result(history, node, before, collection)
    except OxidizedChronologyError:
        return DurableOxidizedObservation(
            request_id=collection.request_id,
            requested_at=collection.requested_at,
            completed_at=collection.completed_at,
            status=ObservationStatus.AMBIGUOUS,
            before_revision=before,
            failure_category=ObservationFailureCategory.INCONSISTENT_EVIDENCE,
        )
    except (OxidizedHistoryError, OxidizedRevisionUnavailableError):
        try:
            return DurableOxidizedObservation(
                request_id=collection.request_id,
                requested_at=collection.requested_at,
                completed_at=collection.completed_at,
                status=ObservationStatus.FAILED,
                before_revision=before,
                failure_category=ObservationFailureCategory.HISTORY_UNAVAILABLE,
            )
        except ValidationError:
            raise BuildkiteConfigurationObservationError(
                "protected observation history evidence is incomplete"
            ) from None
    return durable_success(transient)


def _validate_private_parent(path: Path) -> None:
    if not path.is_absolute():
        raise BuildkiteConfigurationObservationError(
            "protected observation output path rejected"
        )
    try:
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        metadata = path.lstat()
    except OSError:
        raise BuildkiteConfigurationObservationError(
            "protected observation output directory rejected"
        ) from None
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or stat.S_IMODE(metadata.st_mode) != 0o700
    ):
        raise BuildkiteConfigurationObservationError(
            "protected observation output directory rejected"
        )


def persist_attempt_file(path: Path, attempt: DurableOxidizedObservation) -> None:
    """Publish one canonical private attempt with exclusive create semantics."""
    _validate_private_parent(path.parent)
    content = canonical_json_bytes(attempt.model_dump(mode="json"))
    if not content or len(content) > MAX_ATTEMPT_BYTES:
        raise BuildkiteConfigurationObservationError(
            "protected observation attempt size rejected"
        )
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except OSError:
        raise BuildkiteConfigurationObservationError(
            "protected observation attempt publication failed"
        ) from None


def load_attempt_file(path: Path) -> DurableOxidizedObservation:
    """Read one exact private canonical attempt within a hard size bound."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
        try:
            metadata = os.fstat(descriptor)
            if metadata.st_size <= 0 or metadata.st_size > MAX_ATTEMPT_BYTES:
                raise OSError
            chunks: list[bytes] = []
            remaining = MAX_ATTEMPT_BYTES + 1
            while remaining:
                chunk = os.read(descriptor, remaining)
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            content = b"".join(chunks)
            if len(content) != metadata.st_size:
                raise OSError
        finally:
            os.close(descriptor)
    except OSError:
        raise BuildkiteConfigurationObservationError(
            "protected observation attempt unavailable"
        ) from None
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or metadata.st_nlink != 1
        or not content
        or len(content) > MAX_ATTEMPT_BYTES
    ):
        raise BuildkiteConfigurationObservationError(
            "protected observation attempt unavailable"
        )
    try:
        attempt = DurableOxidizedObservation.model_validate_json(content)
    except ValidationError:
        raise BuildkiteConfigurationObservationError(
            "protected observation attempt invalid"
        ) from None
    if canonical_json_bytes(attempt.model_dump(mode="json")) != content:
        raise BuildkiteConfigurationObservationError(
            "protected observation attempt is not canonical"
        )
    return attempt


def capture_buildkite_attempt(
    *,
    context: BuildkiteDeploymentContext,
    promotion: Path,
    checkout: Path,
    output: Path,
) -> DurableOxidizedObservation:
    """Validate protected identity, capture, and exclusively publish one attempt."""
    _plan, node = verified_observation_plan(context, promotion, checkout)
    container_id = verified_container_id()
    attempt = capture_attempt(
        OxidizedController(
            API_URL,
            READINESS_PATH,
            LOCK_ROOT,
            container_id,
            trust_root=DEFAULT_TRUST_ROOT,
        ),
        OxidizedHistoryRepository(HISTORY_PATH),
        node,
    )
    persist_attempt_file(output, attempt)
    return attempt


def _overall_status(
    pre: DurableOxidizedObservation, post: DurableOxidizedObservation
) -> ObservationOverallStatus:
    statuses = {pre.status, post.status}
    if ObservationStatus.AMBIGUOUS in statuses:
        return ObservationOverallStatus.AMBIGUOUS
    if statuses <= SUCCESS_STATUSES:
        return ObservationOverallStatus.SUCCEEDED
    if statuses.isdisjoint(SUCCESS_STATUSES):
        return ObservationOverallStatus.FAILED
    return ObservationOverallStatus.PARTIAL


def persist_buildkite_configuration_observation(
    *,
    store: ConfigurationObservationStore,
    context: BuildkiteDeploymentContext,
    repository: str,
    promotion: Path,
    checkout: Path,
    pre_path: Path,
    post_path: Path,
    now: datetime | None = None,
    observation_record_id: UUID | None = None,
) -> ConfigurationObservationRecord:
    """Revalidate the durable parent and publish one append-only child."""
    plan, node = verified_observation_plan(context, promotion, checkout)
    pre = load_attempt_file(pre_path)
    post = load_attempt_file(post_path)
    if pre.status not in SUCCESS_STATUSES or pre.completed_at is None:
        raise BuildkiteConfigurationObservationError(
            "protected pre-observation was not successful"
        )
    if pre.completed_at > post.requested_at:
        raise BuildkiteConfigurationObservationError(
            "protected observations are not temporally bracketed"
        )
    if post.status in SUCCESS_STATUSES and post.before_revision != pre.after_revision:
        raise BuildkiteConfigurationObservationError(
            "protected observation revision chain is inconsistent"
        )

    try:
        job_id = UUID(context.job_id)
        build_number = int(context.build_number)
        parent = store.read_record(job_id)
    except (AuditStoreError, ValueError, ValidationError):
        raise BuildkiteConfigurationObservationError(
            "protected observation parent unavailable"
        ) from None
    expected_repository = normalize_buildkite_repository(repository)
    target = (plan.inventory_object_id, plan.inventory_interface_object_id)
    parent_target = tuple((item.device, item.interface) for item in parent.targets)
    parent_credential = tuple(
        (item.device, item.source, item.reference) for item in parent.credentials
    )
    buildkite = parent.buildkite
    if (
        parent.record_id != job_id
        or not parent.verify_digest()
        or parent.git.repository != expected_repository
        or parent.git.commit != context.commit
        or buildkite is None
        or str(buildkite.pipeline_id) != context.pipeline_id
        or str(buildkite.build_id) != context.build_id
        or buildkite.build_number != build_number
        or str(buildkite.job_id) != context.job_id
        or buildkite.step_key != context.step_key
        or parent.approval is None
        or not parent.approval.passed
        or parent.change_id != plan.change_id
        or parent_target != (target,)
        or parent_credential
        != ((plan.inventory_object_id, "openbao", plan.credential_reference),)
        or AuditArtifactKind.CHANGE_RECORD
        not in {reference.kind for reference in parent.artifacts}
    ):
        raise BuildkiteConfigurationObservationError(
            "protected observation parent correlation rejected"
        )

    record = observation_record_with_digest(
        observation_record_id=observation_record_id or uuid4(),
        generated_at=now or datetime.now(UTC),
        parent_audit={"record_id": parent.record_id, "digest": parent.digest},
        repository=OXIDIZED_REPOSITORY_IDENTITY,
        target=plan.inventory_object_id,
        oxidized_node=node,
        group=OXIDIZED_GROUP,
        pre_observation=pre,
        post_observation=post,
        relationship=ObservationRelationship.TEMPORALLY_BRACKETED,
        causality="NOT_PROVEN",
        overall_status=_overall_status(pre, post),
    )
    store.persist_observation_record(record)
    return record
