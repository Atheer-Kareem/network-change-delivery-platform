"""Transient collection-to-path-revision binding tests."""

from __future__ import annotations

import uuid
from contextlib import suppress
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
        self.last = None

    def latest_revision_or_none(self, _node: str):
        with suppress(StopIteration):
            self.last = next(self.values)
        return self.last


def settlement_clock(monkeypatch: pytest.MonkeyPatch, values: list[float]) -> None:
    monkeypatch.setattr(
        "network_change_delivery.oxidized_observation.time.monotonic",
        iter(values).__next__,
    )
    monkeypatch.setattr(
        "network_change_delivery.oxidized_observation.time.sleep", lambda _value: None
    )


def test_first_collection_binds_new_revision() -> None:
    result = observe_configuration(
        Controller(collection()), History([None, revision()]), "netbox-device-1"
    )
    assert result.before is None
    assert result.after.commit == "a" * 40
    assert result.revision_changed is True


def test_existing_path_delayed_changed_revision_wins_race(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    existing = revision()
    changed = revision("c", when=NOW + timedelta(seconds=2))
    settlement_clock(monkeypatch, [0.0, 1.0, 2.0])
    result = observe_configuration(
        Controller(collection()),
        History([existing, existing, existing, changed]),
        "netbox-device-1",
    )
    assert result.before == existing
    assert result.after == changed
    assert result.revision_changed is True


def test_unchanged_collection_reuses_path_revision_after_settlement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    existing = revision()
    settlement_clock(monkeypatch, [0.0, 11.0])
    result = observe_configuration(
        Controller(collection()), History([existing, existing]), "netbox-device-1"
    )
    assert result.before == result.after
    assert result.revision_changed is False


def test_unrelated_newer_head_does_not_change_target_revision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    node1 = revision()
    settlement_clock(monkeypatch, [0.0, 11.0])
    result = observe_configuration(
        Controller(collection()), History([node1, node1]), "netbox-device-1"
    )
    assert result.after.commit == node1.commit
    assert result.revision_changed is False


def test_initial_revision_appears_during_settlement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settlement_clock(monkeypatch, [0.0, 1.0])
    result = observe_configuration(
        Controller(collection()), History([None, None, revision()]), "netbox-device-1"
    )
    assert result.before is None
    assert result.after == revision()
    assert result.revision_changed is True


def test_success_without_revision_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    settlement_clock(monkeypatch, [0.0, 11.0])
    with pytest.raises(OxidizedObservationError, match="revision unavailable"):
        observe_configuration(
            Controller(collection()), History([None, None]), "netbox-device-1"
        )


def test_delayed_new_revision_outside_job_window_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    existing = revision()
    late = revision("c", when=NOW + timedelta(minutes=1))
    settlement_clock(monkeypatch, [0.0, 1.0])
    with pytest.raises(OxidizedObservationError, match="chronology rejected"):
        observe_configuration(
            Controller(collection()),
            History([existing, existing, late]),
            "netbox-device-1",
        )


def test_existing_path_disappearance_fails_closed() -> None:
    existing = revision()
    with pytest.raises(OxidizedObservationError, match="revision unavailable"):
        observe_configuration(
            Controller(collection()), History([existing, None]), "netbox-device-1"
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
