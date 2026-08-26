"""Offline configuration-observation schema and security-boundary tests."""

from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID

import pytest
from pydantic import ValidationError

from network_change_delivery.configuration_observation import (
    ConfigurationObservationRecord,
    ObservationFailureCategory,
    ObservationOverallStatus,
    ObservationRelationship,
    ObservationStatus,
    OxidizedObservation,
    OxidizedRevision,
    ParentAuditReference,
    observation_record_with_digest,
)

PARENT_ID = UUID("11111111-1111-4111-8111-111111111111")
OBSERVATION_ID = UUID("22222222-2222-4222-8222-222222222222")
REQUEST_ID = UUID("33333333-3333-4333-8333-333333333333")
PARENT_DIGEST = "sha256:" + "a" * 64


def revision(
    *,
    commit: str = "b" * 40,
    blob: str = "c" * 40,
    config_path: str = "managed/netbox-device-1",
    collected_at: datetime = datetime(2026, 8, 27, tzinfo=UTC),
) -> OxidizedRevision:
    return OxidizedRevision(
        commit=commit,
        config_path=config_path,
        blob=blob,
        collected_at=collected_at,
    )


def unchanged_observation(
    *, request_id: UUID = REQUEST_ID, hour: int = 1
) -> OxidizedObservation:
    observed = revision(collected_at=datetime(2026, 8, 27, hour, tzinfo=UTC))
    return OxidizedObservation(
        request_id=request_id,
        requested_at=datetime(2026, 8, 27, hour, 1, tzinfo=UTC),
        completed_at=datetime(2026, 8, 27, hour, 2, tzinfo=UTC),
        status=ObservationStatus.UNCHANGED,
        before_revision=observed,
        after_revision=observed,
    )


def observation_record(**changes: object) -> ConfigurationObservationRecord:
    values: dict[str, object] = {
        "observation_record_id": OBSERVATION_ID,
        "generated_at": datetime(2026, 8, 27, 2, tzinfo=UTC),
        "parent_audit": ParentAuditReference(record_id=PARENT_ID, digest=PARENT_DIGEST),
        "repository": "oxidized:ncdp-lab-actual-state",
        "target": "netbox:dcim.device:1",
        "oxidized_node": "netbox-device-1",
        "group": "managed",
        "post_observation": unchanged_observation(),
        "relationship": ObservationRelationship.POST_ONLY,
        "overall_status": ObservationOverallStatus.SUCCEEDED,
    }
    values.update(changes)
    return observation_record_with_digest(**values)


def test_schema_is_frozen_closed_canonical_and_digest_bound() -> None:
    approved = observation_record()
    assert approved.schema_version == "1"
    assert approved.causality == "NOT_PROVEN"
    assert approved.verify_digest()
    assert approved.digest == observation_record().digest
    assert not approved.model_copy(
        update={"repository": "oxidized:other"}
    ).verify_digest()
    with pytest.raises(ValidationError):
        approved.repository = "oxidized:changed"
    payload = approved.model_dump(mode="json")
    payload["schema_version"] = "2"
    with pytest.raises(ValidationError):
        ConfigurationObservationRecord.model_validate(payload)


@pytest.mark.parametrize(
    "field",
    [
        "configuration",
        "config_payload",
        "diff",
        "command_output",
        "device_output",
        "credentials",
        "password",
        "token",
        "secret",
        "error_text",
    ],
)
def test_record_rejects_secret_configuration_and_free_form_payloads(field: str) -> None:
    payload = observation_record().model_dump(mode="json")
    payload[field] = "forbidden-sensitive-payload"
    with pytest.raises(ValidationError):
        ConfigurationObservationRecord.model_validate(payload)


@pytest.mark.parametrize(
    "field",
    ["configuration", "diff", "command_output", "password", "token", "error"],
)
def test_attempt_and_revision_reject_unreviewed_payload_fields(field: str) -> None:
    attempt = unchanged_observation().model_dump(mode="json")
    attempt[field] = "forbidden"
    with pytest.raises(ValidationError):
        OxidizedObservation.model_validate(attempt)
    revision_payload = revision().model_dump(mode="json")
    revision_payload[field] = "forbidden"
    with pytest.raises(ValidationError):
        OxidizedRevision.model_validate(revision_payload)


@pytest.mark.parametrize(
    "repository",
    [
        "local",
        "Oxidized:repo",
        "oxidized:",
        "../repo",
        "oxidized:../repo",
        "oxidized:repo with space",
        "github:owner/repo",
    ],
)
def test_invalid_repository_identity_is_rejected(repository: str) -> None:
    with pytest.raises(ValidationError):
        observation_record(repository=repository)


@pytest.mark.parametrize(
    ("target", "node"),
    [
        ("netbox:dcim.device:0", "netbox-device-0"),
        ("netbox:dcim.device:-1", "netbox-device-1"),
        ("netbox:dcim.device:1/ssh", "netbox-device-1"),
        ("netbox:dcim.device:2", "netbox-device-1"),
        ("netbox:dcim.device:1", "core-02"),
    ],
)
def test_target_and_node_identity_are_exact_and_bound(target: str, node: str) -> None:
    with pytest.raises(ValidationError):
        observation_record(target=target, oxidized_node=node)


@pytest.mark.parametrize(
    "path",
    [
        ".",
        "/",
        "../x",
        "./x",
        "managed/../x",
        "managed//x",
        "/managed/netbox-device-1",
        "../netbox-device-1",
        "managed/../netbox-device-1",
        "managed//netbox-device-1",
        "./netbox-device-1",
        "managed/netbox device-1",
        "managed/netbox\\device-1",
        "managed/.hidden",
        "managed/netbox-device-1\nsecret",
    ],
)
def test_revision_rejects_unsafe_or_noncanonical_paths(path: str) -> None:
    with pytest.raises(ValidationError):
        revision(config_path=path)


@pytest.mark.parametrize(
    "object_id",
    ["a" * 39, "a" * 41, "a" * 63, "a" * 65, "A" * 40, "g" * 40, "sha1:" + "a" * 40],
)
def test_revision_rejects_malformed_object_ids(object_id: str) -> None:
    with pytest.raises(ValidationError):
        revision(commit=object_id)
    with pytest.raises(ValidationError):
        revision(blob=object_id)


def test_revision_accepts_distinct_sha1_and_sha256_sized_object_ids() -> None:
    assert len(revision().commit) == 40
    assert len(revision(commit="d" * 64, blob="e" * 64).commit) == 64
    with pytest.raises(ValidationError):
        revision(commit="d" * 40, blob="e" * 64)


def test_all_timestamps_require_utc_and_ordering() -> None:
    non_utc = datetime(2026, 8, 27, tzinfo=timezone(timedelta(hours=10)))
    with pytest.raises(ValidationError):
        revision(collected_at=non_utc)
    with pytest.raises(ValidationError):
        observation_record(generated_at=non_utc)
    payload = unchanged_observation().model_dump(mode="python")
    payload["requested_at"] = datetime(2026, 8, 27, 2, tzinfo=UTC)
    payload["completed_at"] = datetime(2026, 8, 27, 1, tzinfo=UTC)
    with pytest.raises(ValidationError, match="precedes"):
        OxidizedObservation.model_validate(payload)


@pytest.mark.parametrize(
    "status",
    [
        ObservationStatus.CHANGED,
        ObservationStatus.UNCHANGED,
        ObservationStatus.FAILED,
        ObservationStatus.TIMED_OUT,
        ObservationStatus.AMBIGUOUS,
    ],
)
def test_before_revision_must_predate_request(status: ObservationStatus) -> None:
    payload = unchanged_observation().model_dump(mode="python")
    payload["status"] = status
    payload["before_revision"] = revision(
        collected_at=datetime(2026, 8, 27, 1, 1, 30, tzinfo=UTC)
    )
    if status not in {ObservationStatus.CHANGED, ObservationStatus.UNCHANGED}:
        payload["after_revision"] = None
        payload["failure_category"] = {
            ObservationStatus.FAILED: ObservationFailureCategory.COLLECTION_FAILED,
            ObservationStatus.TIMED_OUT: (
                ObservationFailureCategory.COLLECTION_TIMED_OUT
            ),
            ObservationStatus.AMBIGUOUS: (
                ObservationFailureCategory.INCONSISTENT_EVIDENCE
            ),
        }[status]
    with pytest.raises(ValidationError, match="after the request"):
        OxidizedObservation.model_validate(payload)


def test_changed_and_unchanged_revision_claims_are_consistent() -> None:
    unchanged = unchanged_observation().model_dump(mode="python")
    unchanged["after_revision"] = revision(blob="d" * 40)
    with pytest.raises(ValidationError, match="conflicting"):
        OxidizedObservation.model_validate(unchanged)

    changed = unchanged_observation().model_dump(mode="python")
    changed["status"] = ObservationStatus.CHANGED
    with pytest.raises(ValidationError, match="inconsistent"):
        OxidizedObservation.model_validate(changed)
    changed["after_revision"] = revision(
        commit="d" * 40,
        blob="e" * 40,
        collected_at=datetime(2026, 8, 27, 1, 1, 30, tzinfo=UTC),
    )
    assert (
        OxidizedObservation.model_validate(changed).status is ObservationStatus.CHANGED
    )


def test_changed_after_revision_must_be_observed_during_request_window() -> None:
    changed = unchanged_observation().model_dump(mode="python")
    changed["status"] = ObservationStatus.CHANGED
    changed["after_revision"] = revision(
        commit="d" * 40,
        blob="e" * 40,
        collected_at=datetime(2026, 8, 27, 1, 0, 30, tzinfo=UTC),
    )
    with pytest.raises(ValidationError, match="inconsistent revisions"):
        OxidizedObservation.model_validate(changed)


def test_unchanged_revision_may_predate_request() -> None:
    observed = revision(collected_at=datetime(2026, 8, 26, tzinfo=UTC))
    unchanged = unchanged_observation().model_dump(mode="python")
    unchanged["before_revision"] = observed
    unchanged["after_revision"] = observed
    assert (
        OxidizedObservation.model_validate(unchanged).status
        is ObservationStatus.UNCHANGED
    )


@pytest.mark.parametrize(
    "status", [ObservationStatus.FAILED, ObservationStatus.TIMED_OUT]
)
def test_failure_and_timeout_cannot_fabricate_after_revision(
    status: ObservationStatus,
) -> None:
    with pytest.raises(ValidationError):
        OxidizedObservation(
            request_id=REQUEST_ID,
            requested_at=datetime(2026, 8, 27, 1, tzinfo=UTC),
            completed_at=datetime(2026, 8, 27, 1, 1, tzinfo=UTC),
            status=status,
            before_revision=revision(),
            after_revision=revision(),
            failure_category=(
                ObservationFailureCategory.COLLECTION_TIMED_OUT
                if status is ObservationStatus.TIMED_OUT
                else ObservationFailureCategory.COLLECTION_FAILED
            ),
        )


def test_failure_category_is_closed_and_required() -> None:
    with pytest.raises(ValidationError):
        OxidizedObservation(
            request_id=REQUEST_ID,
            requested_at=datetime(2026, 8, 27, 1, tzinfo=UTC),
            completed_at=datetime(2026, 8, 27, 1, 1, tzinfo=UTC),
            status=ObservationStatus.FAILED,
        )
    payload = {
        "request_id": str(REQUEST_ID),
        "requested_at": "2026-08-27T01:00:00Z",
        "completed_at": "2026-08-27T01:01:00Z",
        "status": "FAILED",
        "failure_category": "raw device error: password=secret",
    }
    with pytest.raises(ValidationError):
        OxidizedObservation.model_validate(payload)


@pytest.mark.parametrize("status", list(ObservationStatus))
@pytest.mark.parametrize("category", list(ObservationFailureCategory))
def test_status_and_failure_category_mapping_is_exact(
    status: ObservationStatus, category: ObservationFailureCategory
) -> None:
    allowed = {
        ObservationStatus.FAILED: {
            ObservationFailureCategory.SOURCE_UNAVAILABLE,
            ObservationFailureCategory.NODE_UNAVAILABLE,
            ObservationFailureCategory.AUTHENTICATION_FAILED,
            ObservationFailureCategory.CONNECTION_FAILED,
            ObservationFailureCategory.COLLECTION_FAILED,
            ObservationFailureCategory.OUTPUT_FAILED,
            ObservationFailureCategory.HISTORY_UNAVAILABLE,
        },
        ObservationStatus.TIMED_OUT: {ObservationFailureCategory.COLLECTION_TIMED_OUT},
        ObservationStatus.AMBIGUOUS: {
            ObservationFailureCategory.CONCURRENT_COLLECTION,
            ObservationFailureCategory.INCONSISTENT_EVIDENCE,
        },
    }
    payload = {
        "request_id": REQUEST_ID,
        "requested_at": datetime(2026, 8, 27, 1, tzinfo=UTC),
        "completed_at": datetime(2026, 8, 27, 1, 1, tzinfo=UTC),
        "status": status,
        "before_revision": revision(),
        "failure_category": category,
    }
    if category in allowed.get(status, set()):
        assert OxidizedObservation.model_validate(payload).status is status
    else:
        with pytest.raises(ValidationError):
            OxidizedObservation.model_validate(payload)


def test_relationship_and_overall_status_are_derived_from_evidence() -> None:
    pre = unchanged_observation(hour=0)
    post = unchanged_observation(request_id=UUID(int=4), hour=1)
    bracketed = observation_record(
        pre_observation=pre,
        post_observation=post,
        relationship=ObservationRelationship.TEMPORALLY_BRACKETED,
    )
    assert bracketed.overall_status is ObservationOverallStatus.SUCCEEDED
    with pytest.raises(ValidationError):
        observation_record(
            pre_observation=pre,
            relationship=ObservationRelationship.POST_ONLY,
        )
    with pytest.raises(ValidationError, match="overall status"):
        observation_record(overall_status=ObservationOverallStatus.FAILED)


def test_schema_one_exposes_no_proven_causality_value() -> None:
    assert set(ObservationRelationship) == {
        ObservationRelationship.TEMPORALLY_BRACKETED,
        ObservationRelationship.POST_ONLY,
        ObservationRelationship.UNCORRELATED,
    }
    payload = observation_record().model_dump(mode="json")
    payload["causality"] = "PROVEN"
    with pytest.raises(ValidationError):
        ConfigurationObservationRecord.model_validate(payload)
