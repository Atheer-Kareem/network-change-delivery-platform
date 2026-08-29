"""Explicit two-platform adapter composition without dynamic plugins."""

from __future__ import annotations

from pathlib import Path

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
from network_change_delivery.snmp_provisioning import (
    SecretRenderedArtifact,
    SnmpOwnedObjectState,
    SnmpPreflightSubject,
    SnmpProvisioningPlan,
)


class MultiVendorAdapter:
    """Dispatch only the two explicitly supported platform implementations."""

    def __init__(self, *, known_hosts: Path | None = None) -> None:
        self._cisco = AnsibleRunnerCiscoAdapter(known_hosts=known_hosts)
        self._junos = JunosPyEZAdapter(known_hosts=known_hosts)

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

    def preflight(
        self,
        device: InventoryDevice,
        credentials: DeviceCredentials,
        plan: SnmpPreflightSubject,
    ) -> SnmpOwnedObjectState:
        if device.platform == "cisco_iosxe":
            return self._cisco.snmp_preflight(device, credentials, plan)
        if device.platform == "junos":
            return self._junos.snmp_preflight(device, credentials, plan)
        raise ProviderError("target platform is unsupported")

    def execute_cisco(
        self,
        device: InventoryDevice,
        credentials: DeviceCredentials,
        artifact: SecretRenderedArtifact,
    ) -> ExecutionResult:
        return self._cisco.execute_snmp(device, credentials, artifact)

    def execute_junos_confirmed(
        self,
        device: InventoryDevice,
        credentials: DeviceCredentials,
        artifact: SecretRenderedArtifact,
        minutes: int,
    ) -> ExecutionResult:
        return self._junos.execute_snmp_confirmed(
            device, credentials, artifact, minutes
        )

    def post_validate(
        self,
        device: InventoryDevice,
        credentials: DeviceCredentials,
        plan: SnmpProvisioningPlan,
    ) -> SnmpOwnedObjectState:
        return self.preflight(device, credentials, plan)

    def recover_cisco(
        self,
        device: InventoryDevice,
        credentials: DeviceCredentials,
        plan: SnmpProvisioningPlan,
        commands: tuple[str, ...],
    ) -> ExecutionResult:
        artifact = SecretRenderedArtifact(
            "cisco_iosxe",
            plan,
            payload=commands,
        )
        return self._cisco.execute_snmp(device, credentials, artifact)

    def confirm_junos(
        self, device: InventoryDevice, credentials: DeviceCredentials
    ) -> ExecutionResult:
        return self._junos.confirm(device, credentials)
