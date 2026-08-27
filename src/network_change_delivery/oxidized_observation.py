"""Bind one bounded Oxidized collection to path-scoped Git metadata."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pydantic import BaseModel, ConfigDict, model_validator

from network_change_delivery.configuration_observation import OxidizedRevision
from network_change_delivery.oxidized_controller import (
    CollectionOutcome,
    CollectionResult,
    OxidizedController,
)
from network_change_delivery.oxidized_history import OxidizedHistoryRepository
from network_change_delivery.oxidized_host_trust import DEFAULT_TRUST_ROOT
from network_change_delivery.oxidized_private_paths import validate_private_file
from network_change_delivery.oxidized_service import (
    API_URL,
    CONTAINER_NAME,
    verify_container_definition,
)

REVISION_WAIT_SECONDS = 10.0
REVISION_POLL_SECONDS = 0.25
REVISION_CLOCK_TOLERANCE = timedelta(seconds=5)
STATE_ROOT = Path("/Users/netdevops/.local/state/ncdp/oxidized")
CONFIG_ROOT = Path("/Users/netdevops/.config/ncdp/oxidized")
DOCKER = "/usr/local/bin/docker"


class OxidizedObservationError(ValueError):
    """A collection could not be coherently bound to private Git metadata."""


class OxidizedRevisionUnavailableError(OxidizedObservationError):
    """Path-scoped Git metadata was unavailable or disappeared."""


class OxidizedChronologyError(OxidizedObservationError):
    """Path-scoped Git metadata contradicted the collection window."""


class OxidizedObservation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    collection: CollectionResult
    before: OxidizedRevision | None
    after: OxidizedRevision
    revision_changed: bool
    settled_at: datetime

    @model_validator(mode="after")
    def validate_settlement(self) -> OxidizedObservation:
        completed = self.collection.completed_at
        if (
            self.settled_at.utcoffset() != timedelta(0)
            or completed is None
            or self.settled_at < completed
            or self.settled_at < self.after.collected_at
        ):
            raise ValueError("Oxidized observation settlement is inconsistent")
        return self


def _settlement_completed_at(
    collection: CollectionResult, after: OxidizedRevision
) -> datetime:
    """Capture the metadata-settlement boundary after accepted Git storage."""
    completed = collection.completed_at
    if completed is None:
        raise OxidizedObservationError("Oxidized observation completion unavailable")
    evidence_completed = max(completed, after.collected_at)
    settled = datetime.now(UTC)
    if evidence_completed > settled:
        delay = (evidence_completed - settled).total_seconds()
        if delay > REVISION_CLOCK_TOLERANCE.total_seconds():
            raise OxidizedChronologyError("Oxidized observation chronology rejected")
        time.sleep(delay)
        settled = datetime.now(UTC)
        if settled < evidence_completed:
            raise OxidizedChronologyError("Oxidized observation chronology rejected")
    return settled


def observe_configuration(
    controller: OxidizedController,
    history: OxidizedHistoryRepository,
    node: str,
) -> OxidizedObservation:
    """Collect once and return metadata only; never read a configuration blob."""
    before = history.latest_revision_or_none(node)
    collection = controller.collect(node)
    if collection.outcome is not CollectionOutcome.SUCCEEDED:
        raise OxidizedObservationError("Oxidized observation collection failed")
    return bind_collection_result(history, node, before, collection)


def bind_collection_result(
    history: OxidizedHistoryRepository,
    node: str,
    before: OxidizedRevision | None,
    collection: CollectionResult,
) -> OxidizedObservation:
    """Settle one completed successful job against target-path metadata only."""
    if collection.outcome is not CollectionOutcome.SUCCEEDED:
        raise OxidizedObservationError("Oxidized observation collection failed")
    deadline = time.monotonic() + REVISION_WAIT_SECONDS
    while True:
        after = history.latest_revision_or_none(node)
        if after is None:
            if before is not None:
                raise OxidizedRevisionUnavailableError(
                    "Oxidized observation revision unavailable"
                )
        else:
            changed = (
                before is None
                or after.commit != before.commit
                or after.blob != before.blob
            )
            if changed:
                if (
                    collection.upstream_started_at is None
                    or collection.upstream_ended_at is None
                    or after.collected_at
                    < collection.requested_at - REVISION_CLOCK_TOLERANCE
                    or after.collected_at
                    > collection.upstream_ended_at + REVISION_CLOCK_TOLERANCE
                ):
                    raise OxidizedChronologyError(
                        "Oxidized observation chronology rejected"
                    )
                return OxidizedObservation(
                    collection=collection,
                    before=before,
                    after=after,
                    revision_changed=True,
                    settled_at=_settlement_completed_at(collection, after),
                )
        # Oxidized 0.37.0 publishes terminal node.last before its synchronous
        # output.store call. An existing identical path must therefore settle
        # for the complete bounded window before it can mean unchanged.
        if time.monotonic() >= deadline:
            if after is None:
                raise OxidizedRevisionUnavailableError(
                    "Oxidized observation revision unavailable"
                )
            return OxidizedObservation(
                collection=collection,
                before=before,
                after=after,
                revision_changed=False,
                settled_at=_settlement_completed_at(collection, after),
            )
        time.sleep(REVISION_POLL_SECONDS)


def _private_text(path: Path) -> str:
    validate_private_file(path)
    value = path.read_text().strip()
    if not value:
        raise OxidizedObservationError("Oxidized observation input unavailable")
    return value


def verified_container_id() -> str:
    try:
        result = subprocess.run(
            [DOCKER, "container", "inspect", CONTAINER_NAME],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=True,
            text=True,
            timeout=10,
            env={"HOME": str(Path.home()), "PATH": "/usr/local/bin:/usr/bin:/bin"},
        )
        values = json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, ValueError):
        raise OxidizedObservationError("Oxidized service unavailable") from None
    if not isinstance(values, list) or len(values) != 1:
        raise OxidizedObservationError("Oxidized service unavailable")
    return verify_container_definition(
        values[0],
        _private_text(CONFIG_ROOT / "image-id"),
        config_path=CONFIG_ROOT / "config",
        source_path=STATE_ROOT / "runtime" / "router.json",
        history_path=STATE_ROOT / "config-history.git",
        trust_path=DEFAULT_TRUST_ROOT,
    )


def main() -> int:
    if len(sys.argv) != 2:
        print("Oxidized observation arguments rejected", file=sys.stderr)
        return 2
    try:
        result = observe_configuration(
            OxidizedController(
                API_URL,
                STATE_ROOT / "runtime" / "collection-ready.json",
                STATE_ROOT / "control" / "locks",
                verified_container_id(),
                trust_root=DEFAULT_TRUST_ROOT,
            ),
            OxidizedHistoryRepository(STATE_ROOT / "config-history.git"),
            sys.argv[1],
        )
    except (OSError, ValueError):
        print("Oxidized observation failed", file=sys.stderr)
        return 2
    print(result.model_dump_json())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
