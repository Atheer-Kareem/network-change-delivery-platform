"""Protected Buildkite configuration-observation adapter tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from test_audit_store import plan
from test_buildkite_audit import context
from test_configuration_observation import revision

import network_change_delivery.buildkite_configuration_observation as adapter
from network_change_delivery.audit import (
    AuditArtifactKind,
    AuditArtifactReference,
    AuditFinalOutcome,
    BuildkiteCorrelation,
    CredentialProvenance,
    GitCorrelation,
    ProtectedApprovalBoundary,
    StableTargetIdentity,
    audit_record_with_digest,
)
from network_change_delivery.buildkite_configuration_observation import (
    BuildkiteConfigurationObservationError,
    canonical_oxidized_node,
    capture_attempt,
    durable_failure,
    durable_success,
    load_attempt_file,
    persist_attempt_file,
    persist_buildkite_configuration_observation,
    verified_observation_plan,
)
from network_change_delivery.buildkite_deployment import LiveDeploymentRequest
from network_change_delivery.configuration_observation import (
    ObservationFailureCategory,
    ObservationStatus,
)
from network_change_delivery.oxidized_controller import (
    CollectionOutcome,
    CollectionResult,
)
from network_change_delivery.oxidized_observation import OxidizedObservation

NOW = datetime(2026, 8, 27, 1, tzinfo=UTC)
REQUEST_ID = UUID("33333333-3333-4333-8333-333333333333")


def collection(outcome: CollectionOutcome) -> CollectionResult:
    return CollectionResult(
        request_id=REQUEST_ID,
        requested_at=NOW,
        completed_at=NOW + timedelta(seconds=2),
        node="netbox-device-1",
        outcome=outcome,
        upstream_status="success" if outcome is CollectionOutcome.SUCCEEDED else None,
        upstream_started_at=NOW,
        upstream_ended_at=NOW + timedelta(seconds=1),
    )


@pytest.mark.parametrize(
    ("changed", "expected"),
    [(True, ObservationStatus.CHANGED), (False, ObservationStatus.UNCHANGED)],
)
def test_success_conversion_preserves_validated_metadata(
    changed: bool, expected: ObservationStatus
) -> None:
    before = revision(collected_at=NOW - timedelta(hours=1))
    after = revision(
        commit="d" * 40 if changed else before.commit,
        blob="e" * 40 if changed else before.blob,
        collected_at=NOW + timedelta(seconds=1) if changed else before.collected_at,
    )
    transient = OxidizedObservation(
        collection=collection(CollectionOutcome.SUCCEEDED),
        before=before,
        after=after,
        revision_changed=changed,
    )
    durable = durable_success(transient)
    assert durable.status is expected
    assert durable.request_id == transient.collection.request_id
    assert durable.requested_at == transient.collection.requested_at
    assert durable.completed_at == transient.collection.completed_at
    assert durable.before_revision == before
    assert durable.after_revision == after


def test_success_requires_existing_baseline() -> None:
    transient = OxidizedObservation(
        collection=collection(CollectionOutcome.SUCCEEDED),
        before=None,
        after=revision(collected_at=NOW),
        revision_changed=True,
    )
    with pytest.raises(BuildkiteConfigurationObservationError, match="baseline"):
        durable_success(transient)


@pytest.mark.parametrize(
    ("outcome", "status", "category"),
    [
        (
            CollectionOutcome.COLLECTION_TIMED_OUT,
            ObservationStatus.TIMED_OUT,
            ObservationFailureCategory.COLLECTION_TIMED_OUT,
        ),
        (
            CollectionOutcome.CONCURRENT_COLLECTION,
            ObservationStatus.AMBIGUOUS,
            ObservationFailureCategory.CONCURRENT_COLLECTION,
        ),
        (
            CollectionOutcome.INCONSISTENT_EVIDENCE,
            ObservationStatus.AMBIGUOUS,
            ObservationFailureCategory.INCONSISTENT_EVIDENCE,
        ),
        (
            CollectionOutcome.COLLECTION_FAILED,
            ObservationStatus.FAILED,
            ObservationFailureCategory.COLLECTION_FAILED,
        ),
    ],
)
def test_closed_failure_mapping_has_no_raw_exception_text(
    outcome: CollectionOutcome,
    status: ObservationStatus,
    category: ObservationFailureCategory,
) -> None:
    durable = durable_failure(collection(outcome), revision())
    assert durable.status is status
    assert durable.failure_category is category
    assert "error" not in durable.model_dump(mode="json")


def test_canonical_target_mapping_and_arbitrary_target_rejection() -> None:
    approved = plan()
    assert canonical_oxidized_node(approved) == "netbox-device-1"
    assert (
        canonical_oxidized_node(
            approved.model_copy(
                update={
                    "inventory_object_id": "netbox:dcim.device:2",
                    "credential_reference": "openbao:kv-v2:ncdp/devices/2/ssh",
                }
            )
        )
        == "netbox-device-2"
    )
    with pytest.raises(BuildkiteConfigurationObservationError, match="unsupported"):
        canonical_oxidized_node(
            approved.model_copy(update={"inventory_object_id": "netbox:dcim.device:3"})
        )
    with pytest.raises(BuildkiteConfigurationObservationError, match="provenance"):
        canonical_oxidized_node(
            approved.model_copy(update={"credential_reference": "environment:x"})
        )


def test_promoted_plan_and_commit_bound_request_must_match(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    approved = plan()
    monkeypatch.setattr(
        adapter,
        "load_verified_promotion_artifacts",
        lambda *_args: (object(), approved, object()),
    )
    monkeypatch.setattr(
        adapter,
        "load_live_deployment_request_at_commit",
        lambda *_args, **_kwargs: LiveDeploymentRequest(
            schema_version="1",
            action="deploy",
            change_id="CHG-MISMATCH",
            plan_digest=approved.digest,
            inventory_object_id=approved.inventory_object_id,
        ),
    )
    with pytest.raises(BuildkiteConfigurationObservationError, match="mismatch"):
        verified_observation_plan(context(), tmp_path, tmp_path)


class _Controller:
    def __init__(self, result: CollectionResult) -> None:
        self.result = result

    def collect(self, node: str) -> CollectionResult:
        assert node == "netbox-device-1"
        return self.result


class _History:
    def __init__(self, observed) -> None:
        self.observed = observed

    def latest_revision(self, node: str):
        assert node == "netbox-device-1"
        return self.observed


def test_failed_collection_never_returns_revision_success() -> None:
    attempt = capture_attempt(
        _Controller(collection(CollectionOutcome.COLLECTION_FAILED)),
        _History(revision()),
        "netbox-device-1",
    )
    assert attempt.status is ObservationStatus.FAILED
    assert attempt.after_revision is None


def test_private_attempt_file_is_canonical_exclusive_and_private(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "observation"
    path = directory / "pre.json"
    attempt = durable_failure(
        collection(CollectionOutcome.COLLECTION_TIMED_OUT), revision()
    )
    persist_attempt_file(path, attempt)
    assert directory.stat().st_mode & 0o777 == 0o700
    assert path.stat().st_mode & 0o777 == 0o600
    assert load_attempt_file(path) == attempt
    with pytest.raises(BuildkiteConfigurationObservationError, match="publication"):
        persist_attempt_file(path, attempt)


def test_attempt_reader_rejects_symlink(tmp_path: Path) -> None:
    directory = tmp_path / "observation"
    target = directory / "pre.json"
    link = directory / "post.json"
    persist_attempt_file(
        target,
        durable_failure(collection(CollectionOutcome.COLLECTION_FAILED), revision()),
    )
    link.symlink_to(target)
    with pytest.raises(BuildkiteConfigurationObservationError, match="unavailable"):
        load_attempt_file(link)


def _artifact(kind: AuditArtifactKind, character: str) -> AuditArtifactReference:
    digest = "sha256:" + character * 64
    return AuditArtifactReference(
        kind=kind,
        schema_version="1",
        sha256=digest,
        locator=f"artifacts/{kind.value}/{digest[7:]}.json",
        size_bytes=2,
    )


def _parent():
    approved = plan()
    return audit_record_with_digest(
        record_id=UUID(context().job_id),
        generated_at=NOW + timedelta(minutes=2),
        change_id=approved.change_id,
        git=GitCorrelation(repository="github:owner/repo", commit=context().commit),
        buildkite=BuildkiteCorrelation(
            pipeline_id=UUID(context().pipeline_id),
            build_id=UUID(context().build_id),
            build_number=int(context().build_number),
            job_id=UUID(context().job_id),
            step_key=context().step_key,
        ),
        approval=ProtectedApprovalBoundary(),
        targets=(
            StableTargetIdentity(
                device=approved.inventory_object_id,
                interface=approved.inventory_interface_object_id,
            ),
        ),
        credentials=(
            CredentialProvenance(
                device=approved.inventory_object_id,
                source="openbao",
                reference=approved.credential_reference,
            ),
        ),
        final_outcome=AuditFinalOutcome.SUCCEEDED,
        artifacts=(
            _artifact(AuditArtifactKind.CHANGE_RECORD, "b"),
            _artifact(AuditArtifactKind.DEPLOYMENT_PLAN, "a"),
        ),
    )


class _Store:
    def __init__(self, parent) -> None:
        self.parent = parent
        self.persisted = None

    def read_record(self, record_id: UUID):
        assert record_id == self.parent.record_id
        return self.parent

    def persist_observation_record(self, record) -> None:
        self.persisted = record


def test_child_revalidates_parent_and_preserves_temporal_revision_chain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    approved = plan()
    monkeypatch.setattr(
        adapter,
        "verified_observation_plan",
        lambda *_args: (approved, "netbox-device-1"),
    )
    before = revision(collected_at=NOW - timedelta(hours=1))
    after = revision(commit="d" * 40, blob="e" * 40, collected_at=NOW)
    pre = durable_success(
        OxidizedObservation(
            collection=collection(CollectionOutcome.SUCCEEDED),
            before=before,
            after=after,
            revision_changed=True,
        )
    )
    post_collection = collection(CollectionOutcome.SUCCEEDED).model_copy(
        update={
            "request_id": UUID(int=44),
            "requested_at": NOW + timedelta(seconds=3),
            "completed_at": NOW + timedelta(seconds=5),
            "upstream_started_at": NOW + timedelta(seconds=3),
            "upstream_ended_at": NOW + timedelta(seconds=4),
        }
    )
    post_after = revision(
        commit="f" * 40,
        blob="1" * 40,
        collected_at=NOW + timedelta(seconds=4),
    )
    post = durable_success(
        OxidizedObservation(
            collection=post_collection,
            before=after,
            after=post_after,
            revision_changed=True,
        )
    )
    pre_path = tmp_path / "observation" / "pre.json"
    post_path = tmp_path / "observation" / "post.json"
    persist_attempt_file(pre_path, pre)
    persist_attempt_file(post_path, post)
    parent = _parent()
    parent_bytes = parent.model_dump_json()
    store = _Store(parent)

    child = persist_buildkite_configuration_observation(
        store=store,
        context=context(),
        repository="https://github.com/owner/repo.git",
        promotion=tmp_path,
        checkout=tmp_path,
        pre_path=pre_path,
        post_path=post_path,
        now=NOW + timedelta(minutes=3),
    )

    assert store.persisted == child
    assert child.parent_audit.record_id == parent.record_id
    assert child.parent_audit.digest == parent.digest
    assert child.relationship == "TEMPORALLY_BRACKETED"
    assert child.causality == "NOT_PROVEN"
    assert parent.model_dump_json() == parent_bytes


@pytest.mark.parametrize("failure", ["order", "chain"])
def test_invalid_bracket_or_revision_chain_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    approved = plan()
    monkeypatch.setattr(
        adapter,
        "verified_observation_plan",
        lambda *_args: (approved, "netbox-device-1"),
    )
    observed = revision(collected_at=NOW - timedelta(hours=1))
    pre_collection = collection(CollectionOutcome.SUCCEEDED)
    pre = durable_success(
        OxidizedObservation(
            collection=pre_collection,
            before=observed,
            after=observed,
            revision_changed=False,
        )
    )
    post_request = (
        NOW - timedelta(seconds=1) if failure == "order" else NOW + timedelta(seconds=3)
    )
    post_collection = pre_collection.model_copy(
        update={
            "request_id": UUID(int=45),
            "requested_at": post_request,
            "completed_at": NOW + timedelta(seconds=5),
        }
    )
    post_before = revision(commit="d" * 40) if failure == "chain" else observed
    post = durable_success(
        OxidizedObservation(
            collection=post_collection,
            before=post_before,
            after=post_before,
            revision_changed=False,
        )
    )
    pre_path = tmp_path / "observation" / "pre.json"
    post_path = tmp_path / "observation" / "post.json"
    persist_attempt_file(pre_path, pre)
    persist_attempt_file(post_path, post)
    with pytest.raises(BuildkiteConfigurationObservationError):
        persist_buildkite_configuration_observation(
            store=_Store(_parent()),
            context=context(),
            repository="https://github.com/owner/repo.git",
            promotion=tmp_path,
            checkout=tmp_path,
            pre_path=pre_path,
            post_path=post_path,
        )
