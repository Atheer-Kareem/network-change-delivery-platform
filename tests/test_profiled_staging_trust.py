"""Strict run-scoped profiled staging host-trust contracts."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from network_change_delivery.profiled_staging_trust import (
    KNOWN_HOSTS_NAME,
    ProfiledStagingTrustError,
    establish_profiled_staging_trust,
)


def _scan_result(host: str, port: int) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        ["ssh-keyscan"],
        0,
        stdout=(
            f"[{host}]:{port} ssh-ed25519 "
            "AAAAC3NzaC1lZDI1NTE5AAAAIEeI0mXz1o5B7w+/fZ9mP69SivxpRrPSdzDrM5oYJbkB\n"
        ),
    )


def test_staging_trust_is_private_exact_four_and_profile_port_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from test_profiled_realization import inventory_devices, staging_context

    root = tmp_path / "trust"

    def fake_run(arguments, **_kwargs):
        return _scan_result(arguments[-1], int(arguments[-2]))

    monkeypatch.setattr(
        "network_change_delivery.profiled_staging_trust.subprocess.run", fake_run
    )
    generation = establish_profiled_staging_trust(
        staging_context(), inventory_devices(), root
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


def test_staging_trust_rejects_ambiguous_or_reused_known_hosts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from test_profiled_realization import inventory_devices, staging_context

    root = tmp_path / "trust"
    root.mkdir(mode=0o700)
    (root / KNOWN_HOSTS_NAME).write_text("stale\n", encoding="utf-8")
    (root / KNOWN_HOSTS_NAME).chmod(0o600)
    monkeypatch.setattr(
        "network_change_delivery.profiled_staging_trust.subprocess.run",
        lambda *_args, **_kwargs: _scan_result("192.0.2.1", 22),
    )
    with pytest.raises(ProfiledStagingTrustError):
        establish_profiled_staging_trust(staging_context(), inventory_devices(), root)
