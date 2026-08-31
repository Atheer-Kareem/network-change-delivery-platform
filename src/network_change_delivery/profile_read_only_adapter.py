"""Exact profile-bound B2 adapter composition with no write surface."""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict

from network_change_delivery.ansible_adapter import (
    AnsibleRunnerCiscoAdapter,
    ProviderError,
)
from network_change_delivery.architecture_contracts import (
    AdapterFamily,
    AutomationProfileID,
    NetworkOS,
    get_automation_profile,
)
from network_change_delivery.junos_adapter import JunosPyEZAdapter
from network_change_delivery.models import InterfaceState
from network_change_delivery.profile_inventory import ProfileReadOnlyTarget
from network_change_delivery.secrets import DeviceCredentials


class CiscoSSHBackend(StrEnum):
    """Closed network_cli backends admitted by exact Cisco profile."""

    LIBSSH = "libssh"
    PARAMIKO = "paramiko"


class ProfileReadOnlyTransport(BaseModel):
    """One exact profile-to-read-only-adapter transport admission."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    profile_id: AutomationProfileID
    adapter_family: AdapterFamily
    network_os: NetworkOS
    cisco_ssh_backend: CiscoSSHBackend | None = None
    strict_host_key_verification: Literal[True]
    host_key_auto_add: Literal[False]


PROFILE_READ_ONLY_TRANSPORTS: Mapping[AutomationProfileID, ProfileReadOnlyTransport] = (
    MappingProxyType(
        {
            AutomationProfileID.CAT8000V_IOSXE: ProfileReadOnlyTransport(
                profile_id=AutomationProfileID.CAT8000V_IOSXE,
                adapter_family=AdapterFamily.CISCO_IOS,
                network_os=NetworkOS.IOSXE,
                cisco_ssh_backend=CiscoSSHBackend.LIBSSH,
                strict_host_key_verification=True,
                host_key_auto_add=False,
            ),
            AutomationProfileID.IOSV_159_3_M12: ProfileReadOnlyTransport(
                profile_id=AutomationProfileID.IOSV_159_3_M12,
                adapter_family=AdapterFamily.CISCO_IOS,
                network_os=NetworkOS.IOS,
                cisco_ssh_backend=CiscoSSHBackend.PARAMIKO,
                strict_host_key_verification=True,
                host_key_auto_add=False,
            ),
            AutomationProfileID.IOSVL2_2020: ProfileReadOnlyTransport(
                profile_id=AutomationProfileID.IOSVL2_2020,
                adapter_family=AdapterFamily.CISCO_IOS,
                network_os=NetworkOS.IOS,
                cisco_ssh_backend=CiscoSSHBackend.LIBSSH,
                strict_host_key_verification=True,
                host_key_auto_add=False,
            ),
            AutomationProfileID.VJUNOS_ROUTER: ProfileReadOnlyTransport(
                profile_id=AutomationProfileID.VJUNOS_ROUTER,
                adapter_family=AdapterFamily.JUNOS_PYEZ,
                network_os=NetworkOS.JUNOS,
                strict_host_key_verification=True,
                host_key_auto_add=False,
            ),
        }
    )
)


def _validate_transport_catalog() -> None:
    if set(PROFILE_READ_ONLY_TRANSPORTS) != set(AutomationProfileID):
        raise RuntimeError("profile read-only transport catalog is incomplete")
    for profile_id, transport in PROFILE_READ_ONLY_TRANSPORTS.items():
        profile = get_automation_profile(profile_id)
        if (
            transport.profile_id is not profile_id
            or transport.adapter_family is not profile.adapter_family
            or transport.network_os is not profile.network_os
            or not transport.strict_host_key_verification
            or transport.host_key_auto_add
        ):
            raise RuntimeError("profile read-only transport catalog is inconsistent")
        if transport.adapter_family is AdapterFamily.CISCO_IOS:
            if transport.cisco_ssh_backend is None:
                raise RuntimeError("Cisco profile lacks an exact SSH backend")
        elif transport.cisco_ssh_backend is not None:
            raise RuntimeError("non-Cisco profile cannot select a Cisco SSH backend")
    if (
        PROFILE_READ_ONLY_TRANSPORTS[
            AutomationProfileID.IOSV_159_3_M12
        ].cisco_ssh_backend
        is not CiscoSSHBackend.PARAMIKO
    ):
        raise RuntimeError("exact IOSv profile must retain its compatibility backend")
    for strict_profile in (
        AutomationProfileID.CAT8000V_IOSXE,
        AutomationProfileID.IOSVL2_2020,
    ):
        if (
            PROFILE_READ_ONLY_TRANSPORTS[strict_profile].cisco_ssh_backend
            is not CiscoSSHBackend.LIBSSH
        ):
            raise RuntimeError("strict Cisco profile inherited IOSv compatibility")


_validate_transport_catalog()


class CiscoReadOnlyCollector(Protocol):
    """Only the Cisco collection surface B2 may consume."""

    def discover_read_only(
        self,
        target: ProfileReadOnlyTarget,
        credentials: DeviceCredentials,
        *,
        ssh_type: str,
    ) -> tuple[InterfaceState, ...]: ...

    def collect_read_only(
        self,
        target: ProfileReadOnlyTarget,
        credentials: DeviceCredentials,
        interface: str,
        *,
        ssh_type: str,
    ) -> InterfaceState: ...


class JunosReadOnlyCollector(Protocol):
    """Only the Junos collection surface B2 may consume."""

    def discover_read_only(
        self,
        target: ProfileReadOnlyTarget,
        credentials: DeviceCredentials,
    ) -> tuple[InterfaceState, ...]: ...

    def collect_read_only(
        self,
        target: ProfileReadOnlyTarget,
        credentials: DeviceCredentials,
        interface: str,
    ) -> InterfaceState: ...


class ProfileReadOnlyAdapter:
    """Dispatch exact admitted profiles to collection-only provider surfaces."""

    def __init__(
        self,
        *,
        known_hosts: Path | None = None,
        cisco: CiscoReadOnlyCollector | None = None,
        junos: JunosReadOnlyCollector | None = None,
    ) -> None:
        self._cisco = cisco or AnsibleRunnerCiscoAdapter(known_hosts=known_hosts)
        self._junos = junos or JunosPyEZAdapter(known_hosts=known_hosts)

    @staticmethod
    def _admit(target: ProfileReadOnlyTarget) -> ProfileReadOnlyTransport:
        try:
            profile_id = AutomationProfileID(target.automation_profile_id)
        except ValueError:
            raise ProviderError("read-only automation profile is unsupported") from None
        transport = PROFILE_READ_ONLY_TRANSPORTS.get(profile_id)
        if transport is None:
            raise ProviderError("read-only automation profile is unsupported")
        if transport.network_os is not target.network_os:
            raise ProviderError("read-only target profile and NOS mismatch")
        profile = get_automation_profile(profile_id)
        if (
            profile.adapter_family is not transport.adapter_family
            or not transport.strict_host_key_verification
            or transport.host_key_auto_add
        ):
            raise ProviderError("read-only profile transport policy is inconsistent")
        return transport

    def discover(
        self,
        target: ProfileReadOnlyTarget,
        credentials: DeviceCredentials,
    ) -> tuple[InterfaceState, ...]:
        """Discover normalized state through the exact admitted profile."""
        transport = self._admit(target)
        if transport.adapter_family is AdapterFamily.CISCO_IOS:
            backend = transport.cisco_ssh_backend
            if backend is None:
                raise ProviderError("Cisco read-only SSH backend is missing")
            return self._cisco.discover_read_only(
                target,
                credentials,
                ssh_type=backend.value,
            )
        if transport.adapter_family is AdapterFamily.JUNOS_PYEZ:
            return self._junos.discover_read_only(target, credentials)
        raise ProviderError("read-only adapter family is unsupported")

    def collect(
        self,
        target: ProfileReadOnlyTarget,
        credentials: DeviceCredentials,
        interface: str,
    ) -> InterfaceState:
        """Collect one exact normalized interface through the admitted profile."""
        transport = self._admit(target)
        if transport.adapter_family is AdapterFamily.CISCO_IOS:
            backend = transport.cisco_ssh_backend
            if backend is None:
                raise ProviderError("Cisco read-only SSH backend is missing")
            return self._cisco.collect_read_only(
                target,
                credentials,
                interface,
                ssh_type=backend.value,
            )
        if transport.adapter_family is AdapterFamily.JUNOS_PYEZ:
            return self._junos.collect_read_only(target, credentials, interface)
        raise ProviderError("read-only adapter family is unsupported")
