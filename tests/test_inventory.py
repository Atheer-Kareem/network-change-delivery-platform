"""Tests for temporary local inventory and secret boundaries."""

from pathlib import Path

import pytest

from network_change_delivery.inventory import InventoryError, LocalYamlInventoryProvider
from network_change_delivery.secrets import EnvironmentSecretProvider, SecretError


def test_inventory_target_resolution(tmp_path: Path) -> None:
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
    resolved = LocalYamlInventoryProvider(inventory).resolve("router-1")
    assert resolved.host == "192.0.2.10"
    assert resolved.protected_interfaces == ("GigabitEthernet1",)


def test_unknown_inventory_target_fails_closed(tmp_path: Path) -> None:
    inventory = tmp_path / "inventory.yaml"
    inventory.write_text("devices: []\n", encoding="utf-8")
    with pytest.raises(InventoryError, match="does not resolve exactly once"):
        LocalYamlInventoryProvider(inventory).resolve("missing")


@pytest.mark.parametrize("field", ["username", "password"])
def test_inventory_rejects_credential_fields(tmp_path: Path, field: str) -> None:
    inventory = tmp_path / "inventory.yaml"
    inventory.write_text(
        f"""devices:
  - name: router-1
    host: 192.0.2.10
    platform: cisco_iosxe
    expected_hostname: lab-router
    {field}: forbidden
""",
        encoding="utf-8",
    )
    with pytest.raises(InventoryError):
        LocalYamlInventoryProvider(inventory).resolve("router-1")


def test_missing_secret_error_lists_names_only() -> None:
    with pytest.raises(SecretError) as error:
        EnvironmentSecretProvider({}).load()
    assert str(error.value) == (
        "missing required environment variables: "
        "NCDP_DEVICE_USERNAME, NCDP_DEVICE_PASSWORD"
    )
