from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from network_change_delivery.ansible_adapter import ProviderError

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
            raise ProviderError("bounded provider read failed")

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

    with pytest.raises(ProviderError, match="still unavailable"):
        driver.retry_provider_read(
            lambda: (_ for _ in ()).throw(ProviderError("still unavailable")),
            timeout=0,
        )
