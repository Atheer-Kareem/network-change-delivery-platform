"""Tests for bounded, secret-safe Runner result normalization."""

from pathlib import Path
from types import SimpleNamespace

from network_change_delivery.ansible_adapter import (
    EXECUTION_TASK,
    AnsibleRunnerCiscoAdapter,
    _known_hosts_path,
)
from network_change_delivery.models import (
    CiscoConfigArtifact,
    ExecutionDisposition,
    InventoryDevice,
)
from network_change_delivery.secrets import DeviceCredentials


def test_runner_error_normalization_is_bounded_and_secret_safe(monkeypatch) -> None:
    adapter = AnsibleRunnerCiscoAdapter()
    secret = "never-copy-this-password"

    def fake_run(*_args, **_kwargs):
        return SimpleNamespace(status="failed", rc=1), {
            EXECUTION_TASK: {"msg": f"raw provider failure {secret}"}
        }

    monkeypatch.setattr(adapter, "_run", fake_run)
    device = InventoryDevice(
        name="router-1",
        host="192.0.2.10",
        platform="cisco_iosxe",
        expected_hostname="lab-router",
    )
    result = adapter.execute(
        device,
        DeviceCredentials(username="user", password=secret),
        CiscoConfigArtifact(
            parent="interface GigabitEthernet2",
            lines=("description managed",),
        ),
    )
    assert result.disposition is ExecutionDisposition.FAILED
    assert secret not in result.message


def test_failed_write_task_is_treated_as_ambiguous(monkeypatch) -> None:
    adapter = AnsibleRunnerCiscoAdapter()

    def fake_run(*_args, **_kwargs):
        return SimpleNamespace(status="failed", rc=1), {
            EXECUTION_TASK: {"_ncdp_event": "runner_on_failed"}
        }

    monkeypatch.setattr(adapter, "_run", fake_run)
    result = adapter.execute(
        InventoryDevice(
            name="router-1",
            host="192.0.2.10",
            platform="cisco_iosxe",
            expected_hostname="lab-router",
        ),
        DeviceCredentials(username="user", password="secret"),
        CiscoConfigArtifact(
            parent="interface GigabitEthernet2",
            lines=("description managed",),
        ),
    )
    assert result.disposition is ExecutionDisposition.AMBIGUOUS


def test_known_hosts_path_ignores_custom_environment(
    monkeypatch,
) -> None:
    monkeypatch.setenv("NCDP_KNOWN_HOSTS", "/tmp/not-used")
    assert _known_hosts_path() == Path.home() / ".ssh" / "known_hosts"
