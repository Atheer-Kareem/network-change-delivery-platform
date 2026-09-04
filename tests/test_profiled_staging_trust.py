"""Strict run-scoped profiled staging host-trust contracts."""

from __future__ import annotations

from pathlib import Path

import pytest

from network_change_delivery.profiled_realization import (
    RealizationLifecycleState,
    SSHHostKeyType,
)
from network_change_delivery.profiled_staging_trust import (
    KNOWN_HOSTS_NAME,
    ProfiledStagingTrustError,
    establish_profiled_staging_trust,
)

KEY_LINE = (
    "ssh-ed25519",
    "SHA256:mNQp+RgW/Rudeag+8Keh0OAQTMF2bwLhb1MkX9sCwXg",
    "AAAAC3NzaC1lZDI1NTE5AAAAIEeI0mXz1o5B7w+/fZ9mP69SivxpRrPSdzDrM5oYJbkB",
)


def anchors(devices):
    from test_profiled_realization import evidence

    return {
        str(device.logical_name): evidence(f"anchor-{device.logical_name}")
        for device in devices
    }


def preparing_context():
    from test_profiled_realization import staging_context, staging_devices

    devices = tuple(
        item.model_copy(update={"trust_evidence": None}) for item in staging_devices()
    )
    return staging_context(state=RealizationLifecycleState.PREPARING, devices_=devices)


def test_staging_trust_is_private_exact_four_and_profile_port_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from test_profiled_realization import inventory_devices

    root = tmp_path / "trust"

    monkeypatch.setattr(
        "network_change_delivery.profiled_staging_trust._observe_server_key",
        lambda *_args: (SSHHostKeyType(KEY_LINE[0]), KEY_LINE[1], KEY_LINE[2]),
    )
    devices = inventory_devices()
    generation = establish_profiled_staging_trust(
        preparing_context(), devices, root, anchors(devices)
    )
    known_hosts = root / KNOWN_HOSTS_NAME
    assert known_hosts.exists()
    assert known_hosts.stat().st_mode & 0o777 == 0o600
    assert generation.environment.value == "STAGING"
    assert [record.logical_name for record in generation.records] == [
        "core-02",
        "edge-junos-01",
        "transit-ios-01",
        "access-sw-01",
    ]
    assert [record.management_port for record in generation.records] == [
        22,
        830,
        22,
        22,
    ]
    assert "[198.51.100.2]:830 ssh-ed25519" in known_hosts.read_text(encoding="utf-8")


def test_staging_trust_rejects_ambiguous_or_reused_known_hosts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from test_profiled_realization import inventory_devices

    root = tmp_path / "trust"
    root.mkdir(mode=0o700)
    (root / KNOWN_HOSTS_NAME).write_text("stale\n", encoding="utf-8")
    (root / KNOWN_HOSTS_NAME).chmod(0o600)
    monkeypatch.setattr(
        "network_change_delivery.profiled_staging_trust._observe_server_key",
        lambda *_args: (SSHHostKeyType(KEY_LINE[0]), KEY_LINE[1], KEY_LINE[2]),
    )
    devices = inventory_devices()
    with pytest.raises(ProfiledStagingTrustError):
        establish_profiled_staging_trust(
            preparing_context(), devices, root, anchors(devices)
        )


def test_staging_trust_rejects_unstable_key_samples(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from test_profiled_realization import inventory_devices

    calls = 0

    def unstable(*_args):
        nonlocal calls
        calls += 1
        return (
            SSHHostKeyType.SSH_ED25519,
            KEY_LINE[1],
            KEY_LINE[2] + ("A" if calls == 2 else ""),
        )

    monkeypatch.setattr(
        "network_change_delivery.profiled_staging_trust._observe_server_key", unstable
    )
    devices = inventory_devices()
    with pytest.raises(ProfiledStagingTrustError, match="unstable"):
        establish_profiled_staging_trust(
            preparing_context(), devices, tmp_path / "trust", anchors(devices)
        )


def test_staging_trust_cannot_be_established_from_declared_ready_context(
    tmp_path: Path,
) -> None:
    from test_profiled_realization import inventory_devices, staging_context

    devices = inventory_devices()
    with pytest.raises(ProfiledStagingTrustError, match="PREPARING"):
        establish_profiled_staging_trust(
            staging_context(), devices, tmp_path / "trust", anchors(devices)
        )
