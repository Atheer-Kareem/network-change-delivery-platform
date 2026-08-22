"""Explicit two-platform adapter composition without dynamic plugins."""

from __future__ import annotations

from network_change_delivery.ansible_adapter import (
    AnsibleRunnerCiscoAdapter,
    ProviderError,
)
from network_change_delivery.junos_adapter import JunosPyEZAdapter
from network_change_delivery.models import (
    CiscoConfigArtifact,
    ExecutionResult,
    InterfaceState,
    InventoryDevice,
    JunosConfigArtifact,
)
from network_change_delivery.secrets import DeviceCredentials


class MultiVendorAdapter:
    """Dispatch only the two explicitly supported platform implementations."""

    def __init__(self) -> None:
        self._cisco = AnsibleRunnerCiscoAdapter()
        self._junos = JunosPyEZAdapter()

    def collect(
        self,
        device: InventoryDevice,
        credentials: DeviceCredentials,
        interface: str,
    ) -> InterfaceState:
        if device.platform == "cisco_iosxe":
            return self._cisco.collect(device, credentials, interface)
        if device.platform == "junos":
            return self._junos.collect(device, credentials, interface)
        raise ProviderError("target platform is unsupported")

    def execute(
        self,
        device: InventoryDevice,
        credentials: DeviceCredentials,
        artifact: CiscoConfigArtifact,
    ) -> ExecutionResult:
        return self._cisco.execute(device, credentials, artifact)

    def transaction(
        self,
        device: InventoryDevice,
        credentials: DeviceCredentials,
        artifact: JunosConfigArtifact,
    ):
        return self._junos.transaction(device, credentials, artifact)

    def confirm(
        self, device: InventoryDevice, credentials: DeviceCredentials
    ) -> ExecutionResult:
        return self._junos.confirm(device, credentials)
