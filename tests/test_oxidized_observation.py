"""Transient collection-to-path-revision binding tests."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from network_change_delivery.configuration_observation import OxidizedRevision
from network_change_delivery.oxidized_controller import (
    CollectionOutcome,
    CollectionResult,
)
from network_change_delivery.oxidized_observation import (
    OxidizedObservationError,
    observe_configuration,
)

NOW = datetime(2026, 8, 27, 1, 0, tzinfo=UTC)


def revision(commit: str = "a", *, when: datetime = NOW) -> OxidizedRevision:
    return OxidizedRevision(
        commit=commit * 40,
        config_path="managed/netbox-device-1",
        blob=("b" if commit == "a" else "c") * 40,
        collected_at=when,
    )


def collection(outcome: CollectionOutcome = CollectionOutcome.SUCCEEDED):
    return CollectionResult(
        request_id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
        requested_at=NOW,
        completed_at=NOW + timedelta(seconds=2),
        node="netbox-device-1",
        outcome=outcome,
        upstream_status="success" if outcome is CollectionOutcome.SUCCEEDED else "fail",
        upstream_started_at=NOW + timedelta(seconds=1),
        upstream_ended_at=NOW + timedelta(seconds=2),
    )


class Controller:
    def __init__(self, result: CollectionResult) -> None:
        self.result = result

    def collect(self, _node: str) -> CollectionResult:
        return self.result


class History:
    def __init__(self, values):
        self.values = iter(values)

    def latest_revision_or_none(self, _node: str):
        return next(self.values)


def test_first_collection_binds_new_revision() -> None:
    result = observe_configuration(
        Controller(collection()), History([None, revision()]), "netbox-device-1"
    )
    assert result.before is None
    assert result.after.commit == "a" * 40
    assert result.revision_changed is True


def test_unchanged_collection_reuses_path_revision() -> None:
    existing = revision()
    result = observe_configuration(
        Controller(collection()), History([existing, existing]), "netbox-device-1"
    )
    assert result.before == result.after
    assert result.revision_changed is False


def test_unrelated_newer_head_does_not_change_target_revision() -> None:
    node1 = revision()
    result = observe_configuration(
        Controller(collection()), History([node1, node1]), "netbox-device-1"
    )
    assert result.after.commit == node1.commit
    assert result.revision_changed is False


def test_success_without_revision_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "network_change_delivery.oxidized_observation.time.monotonic",
        iter([0.0, 11.0]).__next__,
    )
    with pytest.raises(OxidizedObservationError, match="revision unavailable"):
        observe_configuration(
            Controller(collection()), History([None, None]), "netbox-device-1"
        )


def test_new_revision_outside_job_window_fails_closed() -> None:
    late = revision(when=NOW + timedelta(minutes=1))
    with pytest.raises(OxidizedObservationError, match="chronology rejected"):
        observe_configuration(
            Controller(collection()), History([None, late]), "netbox-device-1"
        )


def test_failed_collection_never_returns_revision_success() -> None:
    with pytest.raises(OxidizedObservationError, match="collection failed"):
        observe_configuration(
            Controller(collection(CollectionOutcome.COLLECTION_FAILED)),
            History([None]),
            "netbox-device-1",
        )


def test_binding_source_is_metadata_only_and_has_no_record_persistence() -> None:
    source = (
        Path(__file__).parents[1]
        / "src/network_change_delivery/oxidized_observation.py"
    ).read_text()
    for forbidden in (
        "cat-file",
        "git show",
        "git diff",
        "ConfigurationObservationRecord",
        "ChangeAuditRecord",
        "AuditStore",
    ):
        assert forbidden not in source
