from __future__ import annotations

import importlib.util
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

from network_change_delivery.ansible_adapter import (
    ProviderError,
    ProviderReadinessError,
)

SCRIPT = Path(__file__).parents[1] / "scripts/run_ephemeral_cml_staging.py"
SPEC = importlib.util.spec_from_file_location("run_ephemeral_cml_staging", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
driver = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(driver)


def test_provider_read_retries_bounded_provider_failures(monkeypatch) -> None:
    calls = 0

    def action() -> None:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise ProviderReadinessError("bounded provider read failed")

    monkeypatch.setattr(driver.time, "monotonic", lambda: 0.0)
    monkeypatch.setattr(driver.time, "sleep", lambda _seconds: None)

    assert driver.retry_provider_read(action) == 3


def test_provider_read_does_not_retry_non_provider_failure(monkeypatch) -> None:
    sleeps = []
    monkeypatch.setattr(driver.time, "sleep", sleeps.append)

    with pytest.raises(ValueError, match="policy failed"):
        driver.retry_provider_read(
            lambda: (_ for _ in ()).throw(ValueError("policy failed"))
        )

    assert sleeps == []


def test_provider_read_stops_at_deadline(monkeypatch) -> None:
    monkeypatch.setattr(driver.time, "sleep", lambda _seconds: None)

    with pytest.raises(ProviderReadinessError, match="still unavailable"):
        driver.retry_provider_read(
            lambda: (_ for _ in ()).throw(ProviderReadinessError("still unavailable")),
            timeout=0,
        )


def test_provider_read_does_not_retry_deterministic_provider_error(
    monkeypatch,
) -> None:
    sleeps = []
    monkeypatch.setattr(driver.time, "sleep", sleeps.append)

    with pytest.raises(ProviderError, match="deterministic task failure"):
        driver.retry_provider_read(
            lambda: (_ for _ in ()).throw(ProviderError("deterministic task failure"))
        )

    assert sleeps == []


def test_host_key_acquisition_retries_and_creates_restrictive_trust(
    tmp_path: Path, monkeypatch
) -> None:
    operations = object.__new__(driver.LocalOperations)
    operations._known_hosts = tmp_path / ".ssh" / "known_hosts"
    scans = iter(
        (
            SimpleNamespace(returncode=1, stdout=""),
            SimpleNamespace(returncode=0, stdout="hash-1 ssh-ed25519 AAAA\n"),
            SimpleNamespace(returncode=0, stdout="hash-2 ssh-ed25519 AAAA\n"),
            SimpleNamespace(returncode=0, stdout="hash-3 ssh-ed25519 AAAA\n"),
        )
    )

    def run(command, **_kwargs):
        if command[0] == "ssh-keygen":
            return SimpleNamespace(returncode=0, stdout="")
        return next(scans)

    monkeypatch.setattr(driver.subprocess, "run", run)
    monkeypatch.setattr(driver.time, "monotonic", lambda: 0.0)
    monkeypatch.setattr(driver.time, "sleep", lambda _seconds: None)

    operations._establish_host_trust("192.0.2.10", (22,))

    assert operations._known_hosts.read_text() == "hash-3 ssh-ed25519 AAAA\n"
    assert stat.S_IMODE(operations._known_hosts.stat().st_mode) == 0o600
