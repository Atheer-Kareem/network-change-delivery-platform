"""Synthetic chronology metadata only; no local Oxidized access."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from network_change_delivery.configuration_observation import (
    OxidizedObservation,
    OxidizedRevision,
)


def observation(*, expected_before=None, changed=False):
    now = datetime.now(UTC) - timedelta(seconds=5)
    before = expected_before or OxidizedRevision(
        commit="a" * 40,
        blob="b" * 40,
        config_path="managed/netbox-device-1",
        collected_at=now - timedelta(seconds=10),
    )
    after = (
        OxidizedRevision(
            commit="c" * 40,
            blob="d" * 40,
            config_path=before.config_path,
            collected_at=now,
        )
        if changed
        else before
    )
    return OxidizedObservation(
        request_id=uuid4(),
        requested_at=now,
        completed_at=now,
        status="CHANGED" if changed else "UNCHANGED",
        before_revision=before,
        after_revision=after,
    )


def capture(_plan, *, expected_before=None):
    return observation(expected_before=expected_before)
