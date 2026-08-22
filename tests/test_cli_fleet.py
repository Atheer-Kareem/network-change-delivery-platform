"""Offline fleet-plan CLI tests; no fleet execution command exists."""

import stat
from pathlib import Path

import pytest

from network_change_delivery import cli
from network_change_delivery.models import (
    FleetDeploymentPlan,
    InterfaceState,
    InventoryDevice,
)
from network_change_delivery.secrets import CredentialReference, DeviceCredentials


def inventory_device(object_id: int, platform: str) -> tuple[InventoryDevice, str]:
    interface = "GigabitEthernet2" if platform == "cisco_iosxe" else "ge-0/0/1"
    return (
        InventoryDevice(
            name=f"router-{object_id}",
            host=f"192.0.2.{object_id}",
            port=22 if platform == "cisco_iosxe" else 830,
            platform=platform,
            expected_hostname=f"router-{object_id}",
            inventory_source="netbox",
            inventory_object_id=f"netbox:dcim.device:{object_id}",
            inventory_interface_object_id=f"netbox:dcim.interface:{object_id + 100}",
        ),
        interface,
    )


class CliFleetInventory:
    def resolve_fleet(self, _selector):
        return (
            inventory_device(10, "cisco_iosxe"),
            inventory_device(11, "junos"),
        )


class CliFleetSecrets:
    def reference(self, device: InventoryDevice) -> CredentialReference:
        return CredentialReference("openbao", f"openbao:kv-v2:ncdp/{device.name}/ssh")

    def load(self, _device: InventoryDevice) -> DeviceCredentials:
        return DeviceCredentials(
            username="not-printed-user", password="not-printed-pass"
        )


class CliFleetCollector:
    def __init__(self, description: str | None = "old") -> None:
        self.description = description

    def collect(
        self,
        device: InventoryDevice,
        _credentials: DeviceCredentials,
        interface: str,
    ) -> InterfaceState:
        return InterfaceState(
            observed_hostname=device.expected_hostname,
            interface=interface,
            exists=True,
            description=self.description,
            protected=False,
        )


def write_change(path: Path) -> None:
    path.write_text(
        """change_id: CHG-FLEET-CLI
kind: interface_description
selector:
  device_tag: fleet-edge
  interface_tag: fleet-uplink
desired:
  description: managed-by-network-change-delivery-platform
rollout:
  wave_size: 2
""",
        encoding="utf-8",
    )


def test_fleet_plan_cli_writes_reviewable_plan_without_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    change = tmp_path / "fleet.yaml"
    output = tmp_path / "fleet-plan.json"
    write_change(change)
    monkeypatch.setattr(cli, "NetBoxInventoryProvider", CliFleetInventory)
    monkeypatch.setattr(cli, "OpenBaoSecretProvider", CliFleetSecrets)
    monkeypatch.setattr(cli, "MultiVendorAdapter", CliFleetCollector)
    assert (
        cli.main(
            [
                "fleet-plan",
                "--change",
                str(change),
                "--plan-out",
                str(output),
                "--netbox",
                "--openbao",
            ]
        )
        == 0
    )
    plan = FleetDeploymentPlan.model_validate_json(output.read_text(encoding="utf-8"))
    assert plan.verify_digest()
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    rendered = capsys.readouterr().out
    assert "Selected members: 2" in rendered
    assert "Deployable members: 2" in rendered
    assert "Canaries:" in rendered
    assert "Child plan router-10:" in rendered
    assert "not-printed" not in rendered


def test_all_compliant_fleet_cli_writes_no_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    change = tmp_path / "fleet.yaml"
    output = tmp_path / "fleet-plan.json"
    write_change(change)
    monkeypatch.setattr(cli, "NetBoxInventoryProvider", CliFleetInventory)
    monkeypatch.setattr(cli, "OpenBaoSecretProvider", CliFleetSecrets)
    monkeypatch.setattr(
        cli,
        "MultiVendorAdapter",
        lambda: CliFleetCollector("managed-by-network-change-delivery-platform"),
    )
    assert (
        cli.main(
            [
                "fleet-plan",
                "--change",
                str(change),
                "--plan-out",
                str(output),
                "--netbox",
                "--openbao",
            ]
        )
        == 0
    )
    assert not output.exists()
    assert "fleet is already compliant" in capsys.readouterr().out


def test_fleet_deploy_command_does_not_exist() -> None:
    with pytest.raises(SystemExit) as caught:
        cli.main(["fleet-deploy"])
    assert caught.value.code == 2


@pytest.mark.parametrize("existing_kind", ["file", "symlink"])
def test_existing_fleet_plan_path_blocks_before_provider_contact(
    existing_kind: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    change = tmp_path / "fleet.yaml"
    output = tmp_path / "fleet-plan.json"
    sentinel = tmp_path / "sentinel.json"
    write_change(change)
    sentinel.write_text("sentinel-content", encoding="utf-8")
    if existing_kind == "file":
        output.write_text("sentinel-content", encoding="utf-8")
    else:
        output.symlink_to(sentinel)
    contacts = 0

    def contacted_provider():
        nonlocal contacts
        contacts += 1
        raise AssertionError("provider must not be constructed")

    monkeypatch.setattr(cli, "NetBoxInventoryProvider", contacted_provider)
    with pytest.raises(SystemExit) as caught:
        cli.main(
            [
                "fleet-plan",
                "--change",
                str(change),
                "--plan-out",
                str(output),
                "--netbox",
                "--openbao",
            ]
        )
    assert caught.value.code == 2
    assert contacts == 0
    assert sentinel.read_text(encoding="utf-8") == "sentinel-content"
    if existing_kind == "file":
        assert output.read_text(encoding="utf-8") == "sentinel-content"
    else:
        assert output.is_symlink()


def test_fleet_plan_exclusive_create_loses_race_without_overwrite(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    change = tmp_path / "fleet.yaml"
    output = tmp_path / "fleet-plan.json"
    write_change(change)
    monkeypatch.setattr(cli, "NetBoxInventoryProvider", CliFleetInventory)
    monkeypatch.setattr(cli, "OpenBaoSecretProvider", CliFleetSecrets)
    monkeypatch.setattr(cli, "MultiVendorAdapter", CliFleetCollector)
    original_plan_fleet = cli.plan_fleet

    def raced_plan_fleet(*args, **kwargs):
        result = original_plan_fleet(*args, **kwargs)
        output.write_text("racing-sentinel", encoding="utf-8")
        return result

    monkeypatch.setattr(cli, "plan_fleet", raced_plan_fleet)
    with pytest.raises(SystemExit) as caught:
        cli.main(
            [
                "fleet-plan",
                "--change",
                str(change),
                "--plan-out",
                str(output),
                "--netbox",
                "--openbao",
            ]
        )
    assert caught.value.code == 2
    assert output.read_text(encoding="utf-8") == "racing-sentinel"
