"""Offline CLI smoke test for plan and deploy using a provider fake."""

from pathlib import Path

import pytest

from network_change_delivery import cli
from network_change_delivery.models import (
    CiscoConfigArtifact,
    ExecutionDisposition,
    ExecutionResult,
    InterfaceState,
    InventoryDevice,
)
from network_change_delivery.secrets import DeviceCredentials


class StatefulFakeAdapter:
    """Simulate fresh collection and one exact successful write."""

    def __init__(self) -> None:
        self.description: str | None = "old-description"
        self.executed: list[CiscoConfigArtifact] = []

    def collect(
        self,
        _device: InventoryDevice,
        _credentials: DeviceCredentials,
        interface: str,
    ) -> InterfaceState:
        return InterfaceState(
            observed_hostname="lab-router",
            ios_version="17.18.2",
            interface=interface,
            exists=True,
            description=self.description,
            protected=False,
        )

    def execute(
        self,
        _device: InventoryDevice,
        _credentials: DeviceCredentials,
        artifact: CiscoConfigArtifact,
    ) -> ExecutionResult:
        self.executed.append(artifact)
        line = artifact.lines[0]
        self.description = line.removeprefix("description ")
        return ExecutionResult(
            disposition=ExecutionDisposition.SUCCEEDED,
            changed=True,
            message="bounded fake success",
        )


def test_plan_and_deploy_cli_offline_smoke(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inventory = tmp_path / "inventory.yaml"
    inventory.write_text(
        """devices:
  - name: router-1
    host: 192.0.2.10
    platform: cisco_iosxe
    expected_hostname: lab-router
    protected_interfaces: [GigabitEthernet1]
""",
        encoding="utf-8",
    )
    change = tmp_path / "change.yaml"
    change.write_text(
        """change_id: CHG-001
kind: interface_description
target: router-1
interface: GigabitEthernet2
desired:
  description: managed-by-ncdp
""",
        encoding="utf-8",
    )
    adapter = StatefulFakeAdapter()
    monkeypatch.setattr(cli, "AnsibleRunnerCiscoAdapter", lambda: adapter)
    monkeypatch.setenv("NCDP_DEVICE_USERNAME", "test-user")
    monkeypatch.setenv("NCDP_DEVICE_PASSWORD", "test-password")
    plan_path = tmp_path / "plan.json"
    report_path = tmp_path / "report.json"

    assert (
        cli.main(
            [
                "plan",
                "--change",
                str(change),
                "--inventory",
                str(inventory),
                "--output",
                str(plan_path),
            ]
        )
        == 0
    )
    digest = cli.DeploymentPlan.model_validate_json(
        plan_path.read_text(encoding="utf-8")
    ).digest
    assert (
        cli.main(
            [
                "deploy",
                "--plan",
                str(plan_path),
                "--inventory",
                str(inventory),
                "--approve-digest",
                digest,
                "--report-json",
                str(report_path),
            ]
        )
        == 0
    )
    assert report_path.is_file()
    assert len(adapter.executed) == 1
