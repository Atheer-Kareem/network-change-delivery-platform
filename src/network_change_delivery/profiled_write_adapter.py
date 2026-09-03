"""Closed profile-bound write dispatch with no ambient SSH trust fallback."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Any, Protocol

from network_change_delivery.ansible_adapter import (
    AnsibleRunnerCiscoAdapter,
    ProviderError,
)
from network_change_delivery.architecture_contracts import (
    AutomationProfileID,
    NetworkOS,
)
from network_change_delivery.junos_adapter import JunosPyEZAdapter
from network_change_delivery.models import (
    CiscoConfigArtifact,
    ExecutionResult,
    JunosConfigArtifact,
)
from network_change_delivery.profile_inventory import ProfiledInventoryDevice
from network_change_delivery.profiled_planning import (
    ProfiledOperation,
    admit_profiled_operation,
)
from network_change_delivery.secrets import DeviceCredentials


class ProfiledWriteTarget:
    """Operation-specific, non-secret write authority projected after preflight."""

    def __init__(
        self, device: ProfiledInventoryDevice, operation: ProfiledOperation
    ) -> None:
        admission = admit_profiled_operation(device, operation)
        live = device.live_read_only_target()
        self.name = device.logical_name
        self.host = live.host
        self.port = live.port
        self.expected_hostname = device.expected_hostname
        self.protected_interfaces = live.protected_interfaces
        self.automation_profile_id = device.automation_profile_id
        self.network_os = device.network_os
        self.operation = operation
        self.admission = admission


class CiscoProfiledWriter(Protocol):
    def execute_profiled(
        self, target: Any, credentials: DeviceCredentials, artifact: CiscoConfigArtifact
    ) -> ExecutionResult: ...


class JunosProfiledWriter(Protocol):
    def profiled_transaction(
        self, target: Any, credentials: DeviceCredentials, artifact: JunosConfigArtifact
    ): ...
    def confirm_profiled(
        self, target: Any, credentials: DeviceCredentials
    ) -> ExecutionResult: ...


class ProfiledWriteAdapter:
    """Exact two-profile write surface; unsupported profiles never reach a writer."""

    def __init__(
        self,
        *,
        known_hosts: Path | None,
        cisco: CiscoProfiledWriter | None = None,
        junos: JunosProfiledWriter | None = None,
    ) -> None:
        if known_hosts is None:
            raise ProviderError("profiled writes require explicit known_hosts")
        self._cisco = cisco or AnsibleRunnerCiscoAdapter(known_hosts=known_hosts)
        self._junos = junos or JunosPyEZAdapter(known_hosts=known_hosts)

    def execute_cisco(
        self,
        target: ProfiledWriteTarget,
        credentials: DeviceCredentials,
        artifact: CiscoConfigArtifact,
    ) -> ExecutionResult:
        if (
            target.automation_profile_id is not AutomationProfileID.CAT8000V_IOSXE
            or target.port != 22
        ):
            raise ProviderError("profiled Cisco write operation is unsupported")
        return self._cisco.execute_profiled(target, credentials, artifact)

    @contextmanager
    def junos_transaction(
        self,
        target: ProfiledWriteTarget,
        credentials: DeviceCredentials,
        artifact: JunosConfigArtifact,
    ):
        if (
            target.automation_profile_id is not AutomationProfileID.VJUNOS_ROUTER
            or target.network_os is not NetworkOS.JUNOS
            or target.port != 830
        ):
            raise ProviderError("profiled Junos write operation is unsupported")
        with self._junos.profiled_transaction(
            target, credentials, artifact
        ) as transaction:
            yield transaction

    def confirm_junos(
        self, target: ProfiledWriteTarget, credentials: DeviceCredentials
    ) -> ExecutionResult:
        if target.automation_profile_id is not AutomationProfileID.VJUNOS_ROUTER:
            raise ProviderError("profiled Junos write operation is unsupported")
        return self._junos.confirm_profiled(target, credentials)
