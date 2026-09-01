"""Read-only desired-state vertical for the exact B4-3 VLAN service."""

from __future__ import annotations

import ipaddress
import json
import os
import re
import uuid
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from network_change_delivery.ansible_adapter import (
    AnsibleRunnerCiscoAdapter,
    ProviderError,
    VlanReadScope,
)
from network_change_delivery.architecture_contracts import (
    AutomationProfileID,
    ManagedField,
    ManagedOwnershipEnvelope,
    ManagedScopeIdentity,
    ManagedScopeKind,
    ManagedVertical,
    Sha256Digest,
    StableInterfaceIdentity,
)
from network_change_delivery.assurance import (
    AssuranceOutcome,
    AssuranceProviderError,
    InvariantResult,
    PreparedSnapshot,
    prepare_snapshot_with_layer1,
    prepare_snapshot_with_layer1_from_bytes,
)
from network_change_delivery.audit import canonical_json_bytes, sha256_identity
from network_change_delivery.ospf_triangle import (
    BatfishOspfTriangleAdapter,
    OspfDesiredState,
    OspfTriangleBatfishObservation,
    OspfTriangleIntent,
    build_ospf_triangle_candidate_snapshot,
    evaluate_ospf_triangle_assurance,
)
from network_change_delivery.profile_inventory import (
    ProfiledInventoryDevice,
    ProfiledInventoryPopulation,
)
from network_change_delivery.reference_data_plane import (
    ACCEPTED_REFERENCE_ALLOCATION_DIGEST,
    ReferenceDataPlaneAllocation,
    reference_allocation_digest,
)
from network_change_delivery.reference_vlan_service import (
    ACCEPTED_VLAN_SERVICE_ALLOCATION_DIGEST,
    ReferenceVlanServiceAllocation,
    vlan_service_allocation_digest,
)
from network_change_delivery.routed_underlay import (
    ACCEPTED_ROUTED_UNDERLAY_D1_DIGEST,
    RoutedUnderlayDesiredState,
    RoutedUnderlayIntent,
)
from network_change_delivery.secrets import DeviceCredentials

VLAN_POLICY_IDENTITY = "git:policy:vlan-access-service"
VLAN_DEVICE_IDENTITIES = ("netbox:dcim.device:1", "netbox:dcim.device:9")
VLAN_NAMES = ("core-02", "access-sw-01")
MANAGED_NETWORK_NODES = (
    "access-sw-01",
    "core-02",
    "edge-junos-01",
    "transit-ios-01",
)
ASSURANCE_FIXTURE_HOSTS = (
    "assurance-servers-probe",
    "assurance-users-probe",
)
MODELED_NODES = tuple(sorted((*MANAGED_NETWORK_NODES, *ASSURANCE_FIXTURE_HOSTS)))
INFRASTRUCTURE_LAYER1_EDGES = (
    (("core-02", "GigabitEthernet4"), ("edge-junos-01", "ge-0/0/0")),
    (("core-02", "GigabitEthernet2"), ("transit-ios-01", "GigabitEthernet0/1")),
    (("edge-junos-01", "ge-0/0/1"), ("transit-ios-01", "GigabitEthernet0/2")),
    (("core-02", "GigabitEthernet3"), ("access-sw-01", "GigabitEthernet0/1")),
)
ASSURANCE_FIXTURE_EDGES = (
    (("access-sw-01", "GigabitEthernet0/2"), ("assurance-users-probe", "eth0")),
    (("access-sw-01", "GigabitEthernet0/3"), ("assurance-servers-probe", "eth0")),
)
LAYER1_EDGES = (*INFRASTRUCTURE_LAYER1_EDGES, *ASSURANCE_FIXTURE_EDGES)
ACCEPTED_VLAN_D1_DIGEST = (
    "sha256:57fe2decfcf6ecaf595a877fac9d2fa4befa0286ec7a70b8235fd514ca3995b3"
)
ACCEPTED_VLAN_CANDIDATE_DIGEST = (
    "sha256:18ba3232b8ec85019b0afcfd7239eb3818e8dc788948482a54ffb2eb430dcda6"
)
VLAN_COMBINED_INVARIANTS = (
    "candidate_exact_parse_files",
    "candidate_parse_status",
    "candidate_exact_nodes",
    "candidate_initialization_issues",
    "exact_routed_interface_prefixes",
    "exact_two_participants_per_link",
    "access_switch_excluded",
    "management_addresses_excluded",
    "exact_direct_neighbor_flows",
    "ospf_exact_routers",
    "ospf_access_excluded",
    "ospf_exact_interfaces",
    "ospf_management_excluded",
    "ospf_exact_adjacencies",
    "ospf_remote_routes",
    "ospf_remote_reachability",
    "vlan_exact_modeled_population",
    "vlan_exact_layer1_edges",
    "vlan_exact_switched_membership",
    "vlan_exact_switchports",
    "vlan_service_not_native",
    "vlan_exact_gateways",
    "vlan_access_has_no_gateway",
    "vlan_connected_routes",
    "vlan_not_advertised_ospf",
    "vlan_gateway_flows",
    "vlan_intervlan_open",
    "vlan_intervlan_traverses_core",
    "vlan_intervlan_excludes_remote_routers",
)


class VlanGatewayIntent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    vid: Literal[10, 20]
    name: Literal["USERS", "SERVERS"]
    vlan_identity: str
    prefix_identity: str
    prefix: ipaddress.IPv4Network
    parent_interface: StableInterfaceIdentity
    subinterface: StableInterfaceIdentity
    gateway_ip_identity: str
    gateway: ipaddress.IPv4Interface
    encapsulation_vlan: Literal[10, 20]
    admin_enabled: Literal[True] = True


class VlanTrunkIntent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    interface: StableInterfaceIdentity
    allowed_vlans: tuple[Literal[10], Literal[20]] = (10, 20)
    admin_enabled: Literal[True] = True


class VlanAccessPortIntent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    interface: StableInterfaceIdentity
    access_vlan: Literal[10, 20]
    admin_enabled: Literal[True] = True


class VlanServiceIntent(BaseModel):
    """Git-owned service behavior over exact NetBox factual allocations."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal["1"] = "1"
    source_data_plane: ReferenceDataPlaneAllocation
    source_vlan_service: ReferenceVlanServiceAllocation
    gateways: tuple[VlanGatewayIntent, VlanGatewayIntent]
    trunk: VlanTrunkIntent
    access_ports: tuple[VlanAccessPortIntent, VlanAccessPortIntent]

    @classmethod
    def from_allocations(
        cls,
        data_plane: ReferenceDataPlaneAllocation,
        vlan: ReferenceVlanServiceAllocation,
    ) -> VlanServiceIntent:
        gateways = tuple(
            VlanGatewayIntent(
                vid=item.vid,
                name=item.canonical_name,
                vlan_identity=item.vlan_identity,
                prefix_identity=item.prefix_identity,
                prefix=item.prefix,
                parent_interface=item.parent_interface,
                subinterface=item.gateway_interface,
                gateway_ip_identity=item.gateway_ip_identity,
                gateway=item.gateway,
                encapsulation_vlan=item.vid,
            )
            for item in vlan.gateways
        )
        return cls(
            source_data_plane=data_plane,
            source_vlan_service=vlan,
            gateways=gateways,  # type: ignore[arg-type]
            trunk=VlanTrunkIntent(interface=vlan.access_trunk),
            access_ports=(
                VlanAccessPortIntent(interface=vlan.access_users_port, access_vlan=10),
                VlanAccessPortIntent(
                    interface=vlan.access_servers_port, access_vlan=20
                ),
            ),
        )

    @model_validator(mode="after")
    def exact_service(self) -> VlanServiceIntent:
        if (
            reference_allocation_digest(self.source_data_plane)
            != ACCEPTED_REFERENCE_ALLOCATION_DIGEST
            or vlan_service_allocation_digest(self.source_vlan_service)
            != ACCEPTED_VLAN_SERVICE_ALLOCATION_DIGEST
            or tuple(item.vid for item in self.gateways) != (10, 20)
            or tuple(item.encapsulation_vlan for item in self.gateways) != (10, 20)
            or tuple(item.access_vlan for item in self.access_ports) != (10, 20)
            or self.trunk.allowed_vlans != (10, 20)
        ):
            raise ValueError("VLAN intent is detached from source authority")
        for gateway, factual in zip(
            self.gateways, self.source_vlan_service.gateways, strict=True
        ):
            if (
                gateway.vlan_identity != factual.vlan_identity
                or gateway.prefix_identity != factual.prefix_identity
                or gateway.parent_interface != factual.parent_interface
                or gateway.subinterface != factual.gateway_interface
                or gateway.gateway_ip_identity != factual.gateway_ip_identity
                or gateway.gateway != factual.gateway
            ):
                raise ValueError("VLAN intent is detached from source authority")
        if (
            self.trunk.interface != self.source_vlan_service.access_trunk
            or self.access_ports[0].interface
            != self.source_vlan_service.access_users_port
            or self.access_ports[1].interface
            != self.source_vlan_service.access_servers_port
        ):
            raise ValueError("VLAN intent is detached from source authority")
        return self


class DesiredVlanGatewayState(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    vid: int
    name: str
    subinterface: StableInterfaceIdentity
    gateway: ipaddress.IPv4Interface
    gateway_ip_identity: str
    admin_enabled: bool


class DesiredVlanPortState(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    interface: StableInterfaceIdentity
    mode: Literal["trunk", "access"]
    allowed_vlans: tuple[int, ...] = ()
    access_vlan: int | None = None
    admin_enabled: bool


class VlanDesiredState(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal["1"] = "1"
    core_parent: StableInterfaceIdentity
    gateways: tuple[DesiredVlanGatewayState, DesiredVlanGatewayState]
    access_ports: tuple[
        DesiredVlanPortState, DesiredVlanPortState, DesiredVlanPortState
    ]
    digest: Sha256Digest

    def calculated_digest(self) -> str:
        return sha256_identity(
            canonical_json_bytes(self.model_dump(mode="json", exclude={"digest"}))
        )

    def verify_digest(self) -> bool:
        return self.digest == self.calculated_digest()

    @model_validator(mode="after")
    def exact_desired(self) -> VlanDesiredState:
        if (
            tuple(item.vid for item in self.gateways) != (10, 20)
            or tuple(item.mode for item in self.access_ports)
            != ("trunk", "access", "access")
            or self.access_ports[0].allowed_vlans != (10, 20)
            or tuple(item.access_vlan for item in self.access_ports[1:]) != (10, 20)
            or not self.verify_digest()
        ):
            raise ValueError("VLAN desired state is not exact")
        return self


def build_vlan_desired_state(intent: VlanServiceIntent) -> VlanDesiredState:
    unsigned = VlanDesiredState.model_construct(
        schema_version="1",
        core_parent=intent.source_vlan_service.core_parent,
        gateways=tuple(
            DesiredVlanGatewayState(
                vid=item.vid,
                name=item.name,
                subinterface=item.subinterface,
                gateway=item.gateway,
                gateway_ip_identity=item.gateway_ip_identity,
                admin_enabled=True,
            )
            for item in intent.gateways
        ),
        access_ports=(
            DesiredVlanPortState(
                interface=intent.trunk.interface,
                mode="trunk",
                allowed_vlans=(10, 20),
                admin_enabled=True,
            ),
            DesiredVlanPortState(
                interface=intent.access_ports[0].interface,
                mode="access",
                access_vlan=10,
                admin_enabled=True,
            ),
            DesiredVlanPortState(
                interface=intent.access_ports[1].interface,
                mode="access",
                access_vlan=20,
                admin_enabled=True,
            ),
        ),
        digest="sha256:" + "0" * 64,
    )
    return VlanDesiredState.model_validate(
        unsigned.model_copy(update={"digest": unsigned.calculated_digest()})
    )


def build_vlan_ownership_envelope(
    intent: VlanServiceIntent,
) -> ManagedOwnershipEnvelope:
    interfaces = (
        intent.source_vlan_service.core_parent,
        *(item.subinterface for item in intent.gateways),
        intent.trunk.interface,
        *(item.interface for item in intent.access_ports),
    )
    return ManagedOwnershipEnvelope(
        vertical=ManagedVertical.VLAN,
        envelope_version=1,
        targets=VLAN_DEVICE_IDENTITIES,
        scope=tuple(
            [
                ManagedScopeIdentity(kind=ManagedScopeKind.DEVICE, identity=item)
                for item in VLAN_DEVICE_IDENTITIES
            ]
            + [
                ManagedScopeIdentity(
                    kind=ManagedScopeKind.VLAN, identity=item.vlan_identity
                )
                for item in intent.gateways
            ]
            + [
                ManagedScopeIdentity(
                    kind=ManagedScopeKind.PREFIX, identity=item.prefix_identity
                )
                for item in intent.gateways
            ]
            + [
                ManagedScopeIdentity(
                    kind=ManagedScopeKind.INTERFACE, identity=item.interface
                )
                for item in interfaces
            ]
            + [
                ManagedScopeIdentity(
                    kind=ManagedScopeKind.IP_ADDRESS, identity=item.gateway_ip_identity
                )
                for item in intent.gateways
            ]
            + [
                ManagedScopeIdentity(
                    kind=ManagedScopeKind.POLICY, identity=VLAN_POLICY_IDENTITY
                )
            ]
        ),
        normalized_fields=(
            ManagedField.VLAN_PRESENCE,
            ManagedField.VLAN_PORT_MODE,
            ManagedField.VLAN_ACCESS_VLAN,
            ManagedField.VLAN_ALLOWED_VLANS,
            ManagedField.VLAN_GATEWAY,
            ManagedField.VLAN_INTERFACE_ADMIN_ENABLED,
        ),
    )


class ObservedCoreVlanInterface(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    interface: StableInterfaceIdentity
    exists: bool
    admin_enabled: bool | None = None
    encapsulation_vlan: int | None = None
    ipv4_addresses: tuple[ipaddress.IPv4Interface, ...] = ()
    ospf_participating: bool = False

    @model_validator(mode="after")
    def bounded(self) -> ObservedCoreVlanInterface:
        if not self.exists and (
            self.admin_enabled is not None
            or self.encapsulation_vlan is not None
            or self.ipv4_addresses
            or self.ospf_participating
        ):
            raise ValueError("absent core VLAN interface has observed state")
        if len(self.ipv4_addresses) > 1 or self.ospf_participating:
            raise ValueError("core VLAN interface state is unsupported")
        return self


class ObservedAccessVlan(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    vid: Literal[10, 20]
    present: bool
    name: str | None = None
    member_interfaces: tuple[str, ...] = ()


class ObservedAccessPort(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    interface: StableInterfaceIdentity
    mode: str
    admin_enabled: bool
    allowed_vlans: tuple[int, ...] = ()
    access_vlan: int | None = None
    native_vlan: int | None = None
    voice_vlan: int | None = None

    @model_validator(mode="after")
    def supported(self) -> ObservedAccessPort:
        if (
            self.native_vlan in {10, 20}
            or self.voice_vlan is not None
            or self.mode
            not in {"access", "trunk", "dynamic auto", "dynamic desirable", "none"}
        ):
            raise ValueError("access switchport state is unsupported")
        return self


class VlanObservation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal["1"] = "1"
    observed_at: datetime
    core_parent: ObservedCoreVlanInterface
    core_subinterfaces: tuple[ObservedCoreVlanInterface, ObservedCoreVlanInterface]
    access_vlans: tuple[ObservedAccessVlan, ObservedAccessVlan]
    access_ports: tuple[ObservedAccessPort, ObservedAccessPort, ObservedAccessPort]
    access_gateway_svis: tuple[str, ...] = ()

    @model_validator(mode="after")
    def exact_observation(self) -> VlanObservation:
        if (
            self.core_parent.interface.interface != "netbox:dcim.interface:7"
            or self.core_parent.ipv4_addresses
            or tuple(item.interface.interface for item in self.core_subinterfaces)
            != ("netbox:dcim.interface:21", "netbox:dcim.interface:22")
            or tuple(item.vid for item in self.access_vlans) != (10, 20)
            or tuple(item.interface.interface for item in self.access_ports)
            != (
                "netbox:dcim.interface:18",
                "netbox:dcim.interface:19",
                "netbox:dcim.interface:20",
            )
            or self.access_gateway_svis
        ):
            raise ValueError("VLAN observation conflicts with managed envelope")
        expected_members = {
            "GigabitEthernet0/1",
            "GigabitEthernet0/2",
            "GigabitEthernet0/3",
        }
        if any(
            set(item.member_interfaces) - expected_members for item in self.access_vlans
        ):
            raise ValueError("service VLAN is attached to an unexpected port")
        return self

    def managed_state_digest(self) -> str:
        return sha256_identity(
            canonical_json_bytes(self.model_dump(mode="json", exclude={"observed_at"}))
        )


def _ip_interfaces(raw: str) -> tuple[ipaddress.IPv4Interface, ...]:
    values = []
    for address, mask in re.findall(r"^\s*ip address (\S+) (\S+)", raw, re.MULTILINE):
        if address == "dhcp":
            raise ProviderError("dynamic address is unsupported in VLAN envelope")
        values.append(ipaddress.ip_interface(f"{address}/{mask}"))
    return tuple(values)


def parse_core_vlan_observation(
    intent: VlanServiceIntent, raw: tuple[str, ...]
) -> tuple[
    ObservedCoreVlanInterface,
    tuple[ObservedCoreVlanInterface, ObservedCoreVlanInterface],
]:
    if len(raw) != 3:
        raise ProviderError("core VLAN read-only result was incomplete")
    parent_raw, subinterface_raw, ospf_raw = raw
    unexpected = {
        line.strip().removeprefix("interface ")
        for line in subinterface_raw.splitlines()
        if line.strip().startswith("interface GigabitEthernet3.")
    } - {"GigabitEthernet3.10", "GigabitEthernet3.20"}
    if unexpected:
        raise ProviderError("unexpected core VLAN subinterface exists")
    if any(token in parent_raw for token in ("encapsulation dot1Q", "ip ospf")):
        raise ProviderError("core VLAN parent configuration is unsupported")
    parent = ObservedCoreVlanInterface(
        interface=intent.source_vlan_service.core_parent,
        exists=True,
        admin_enabled="shutdown" not in parent_raw,
        ipv4_addresses=_ip_interfaces(parent_raw),
    )
    states = []
    sections = re.split(r"(?=^interface )", subinterface_raw, flags=re.MULTILINE)
    for gateway in intent.gateways:
        config = next(
            (
                section
                for section in sections
                if section.startswith(f"interface {gateway.subinterface.name}\n")
            ),
            "",
        )
        exists = (
            f"interface {gateway.subinterface.name}" in config
            and "Invalid input" not in config
        )
        encapsulations = re.findall(
            r"^\s*encapsulation dot1Q (\d+)(?:\s|$)", config, re.MULTILINE
        )
        if exists and (
            len(encapsulations) > 1
            or re.search(r"encapsulation dot1Q \d+\s+native", config)
        ):
            raise ProviderError("core VLAN encapsulation is unsupported")
        states.append(
            ObservedCoreVlanInterface(
                interface=gateway.subinterface,
                exists=exists,
                admin_enabled=("shutdown" not in config) if exists else None,
                encapsulation_vlan=int(encapsulations[0]) if encapsulations else None,
                ipv4_addresses=_ip_interfaces(config) if exists else (),
                ospf_participating=exists
                and bool(re.search(r"^\s*ip ospf\b", config, re.MULTILINE)),
            )
        )
    if any(name in ospf_raw for name in ("GigabitEthernet3.10", "GigabitEthernet3.20")):
        raise ProviderError("core gateway subinterface participates in OSPF")
    return parent, tuple(states)  # type: ignore[return-value]


def _switchport_value(raw: str, label: str) -> str | None:
    match = re.search(
        rf"^{re.escape(label)}:\s*(.+?)\s*$", raw, re.MULTILINE | re.IGNORECASE
    )
    return match.group(1).strip() if match else None


def _vlan_set(value: str | None) -> tuple[int, ...]:
    if not value or value.casefold() in {"none", "all"}:
        return () if not value or value.casefold() == "none" else tuple(range(1, 4095))
    result: set[int] = set()
    for part in value.split(","):
        part = part.strip()
        if "-" in part:
            start, end = map(int, part.split("-", 1))
            result.update(range(start, end + 1))
        elif part.isdigit():
            result.add(int(part))
    return tuple(sorted(result))


def parse_access_vlan_observation(
    intent: VlanServiceIntent, raw: tuple[str, ...]
) -> tuple[
    tuple[ObservedAccessVlan, ObservedAccessVlan],
    tuple[ObservedAccessPort, ObservedAccessPort, ObservedAccessPort],
    tuple[str, ...],
]:
    if len(raw) != 8:
        raise ProviderError("access VLAN read-only result was incomplete")
    vlan_raw, *port_raw, svi_raw = raw
    vlans = []
    for vid, _name in ((10, "USERS"), (20, "SERVERS")):
        match = re.search(
            rf"^\s*{vid}\s+(\S+)\s+\S+\s*(.*?)\s*$", vlan_raw, re.MULTILINE
        )
        members = (
            tuple(re.findall(r"Gi\d+/\d+|GigabitEthernet\d+/\d+", match.group(2)))
            if match
            else ()
        )
        members = tuple(
            "GigabitEthernet" + item.removeprefix("Gi")
            if item.startswith("Gi")
            else item
            for item in members
        )
        vlans.append(
            ObservedAccessVlan(
                vid=vid,
                present=match is not None,
                name=match.group(1) if match else None,
                member_interfaces=members,
            )
        )
    ports = []
    for intended, switchport, config in zip(
        (intent.trunk, *intent.access_ports), port_raw[:3], port_raw[3:6], strict=True
    ):
        admin_mode = (
            _switchport_value(switchport, "Administrative Mode") or "none"
        ).casefold()
        if any(
            value in config.casefold()
            for value in (
                "switchport voice vlan",
                "switchport mode dot1q-tunnel",
                "private-vlan",
                "channel-group",
            )
        ):
            raise ProviderError("access switchport feature is unsupported")
        access_value = _switchport_value(switchport, "Access Mode VLAN")
        native_value = _switchport_value(switchport, "Trunking Native Mode VLAN")
        allowed = _switchport_value(switchport, "Trunking VLANs Enabled")

        def first_int(value: str | None) -> int | None:
            match = re.search(r"\d+", value or "")
            return int(match.group()) if match else None

        ports.append(
            ObservedAccessPort(
                interface=intended.interface,
                mode=admin_mode,
                admin_enabled="shutdown" not in config,
                allowed_vlans=_vlan_set(allowed) if "trunk" in admin_mode else (),
                access_vlan=first_int(access_value),
                native_vlan=first_int(native_value),
                voice_vlan=None
                if (_switchport_value(switchport, "Voice VLAN") or "none").casefold()
                == "none"
                else first_int(_switchport_value(switchport, "Voice VLAN")),
            )
        )
    svis = tuple(
        name for name in ("Vlan10", "Vlan20") if f"interface {name}" in svi_raw
    )
    return tuple(vlans), tuple(ports), svis  # type: ignore[return-value]


class VlanCiscoReadOnlyCollector(Protocol):
    def collect_vlan_read_only(
        self,
        target: object,
        credentials: DeviceCredentials,
        scope: VlanReadScope,
        *,
        ssh_type: Literal["paramiko"],
    ) -> tuple[str, ...]: ...


class ProfileVlanReadOnlyAdapter:
    """Exact profile-bound read-only VLAN collector; no write surface."""

    def __init__(
        self,
        *,
        known_hosts: Path | None = None,
        cisco: VlanCiscoReadOnlyCollector | None = None,
    ) -> None:
        self._cisco = cisco or AnsibleRunnerCiscoAdapter(known_hosts=known_hosts)

    def collect(
        self,
        device: ProfiledInventoryDevice,
        credentials: DeviceCredentials,
        intent: VlanServiceIntent,
    ) -> object:
        target = device.live_read_only_target()
        if (
            device.logical_name == "core-02"
            and device.automation_profile_id is AutomationProfileID.CAT8000V_IOSXE
        ):
            raw = self._cisco.collect_vlan_read_only(
                target,
                credentials,
                VlanReadScope.CORE,
                ssh_type="paramiko",
            )
            return parse_core_vlan_observation(intent, raw)
        if (
            device.logical_name == "access-sw-01"
            and device.automation_profile_id is AutomationProfileID.IOSVL2_2020
        ):
            raw = self._cisco.collect_vlan_read_only(
                target,
                credentials,
                VlanReadScope.ACCESS,
                ssh_type="paramiko",
            )
            return parse_access_vlan_observation(intent, raw)
        raise ProviderError("profile is not admitted for VLAN observation")


class VlanSecretProvider(Protocol):
    def load(self, device: ProfiledInventoryDevice) -> DeviceCredentials: ...


def collect_vlan_observation(
    intent: VlanServiceIntent,
    devices: ProfiledInventoryPopulation,
    secrets: VlanSecretProvider,
    adapter: ProfileVlanReadOnlyAdapter | None = None,
) -> VlanObservation:
    all_devices = {item.logical_name: item for item in devices.devices}
    if set(all_devices) != {
        "core-02",
        "edge-junos-01",
        "transit-ios-01",
        "access-sw-01",
    }:
        raise ProviderError("profiled VLAN inventory population is not exact")
    by_name = {name: all_devices[name] for name in VLAN_NAMES}
    reader = adapter or ProfileVlanReadOnlyAdapter()
    core = reader.collect(by_name["core-02"], secrets.load(by_name["core-02"]), intent)
    access = reader.collect(
        by_name["access-sw-01"],
        secrets.load(by_name["access-sw-01"]),
        intent,
    )
    parent, subinterfaces = core
    vlans, ports, svis = access
    return VlanObservation(
        observed_at=datetime.now(UTC),
        core_parent=parent,
        core_subinterfaces=subinterfaces,
        access_vlans=vlans,
        access_ports=ports,
        access_gateway_svis=svis,
    )


class VlanRenderFormat(StrEnum):
    IOS_CLI = "ios_cli"


class VlanRenderedTarget(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    device_identity: str
    logical_name: Literal["core-02", "access-sw-01"]
    automation_profile_id: AutomationProfileID
    observed_managed_state_digest: Sha256Digest
    proposed_vlan_digest: Sha256Digest
    format: Literal[VlanRenderFormat.IOS_CLI] = VlanRenderFormat.IOS_CLI
    payload: str


def render_vlan_changes(
    intent: VlanServiceIntent, observation: VlanObservation, desired: VlanDesiredState
) -> tuple[VlanRenderedTarget, VlanRenderedTarget]:
    if desired != build_vlan_desired_state(intent):
        raise ValueError("VLAN desired state is detached from intent")
    core_lines = ["interface GigabitEthernet3"]
    core_lines.extend(
        f" no ip address {address.ip} {address.network.netmask}"
        for address in observation.core_parent.ipv4_addresses
    )
    core_lines.extend((" no ip address", " no shutdown"))
    for wanted, observed in zip(
        desired.gateways, observation.core_subinterfaces, strict=True
    ):
        core_lines.append(f"interface {wanted.subinterface.name}")
        if (
            observed.encapsulation_vlan is not None
            and observed.encapsulation_vlan != wanted.vid
        ):
            core_lines.append(f" no encapsulation dot1Q {observed.encapsulation_vlan}")
        core_lines.extend(
            f" no ip address {address.ip} {address.network.netmask}"
            for address in observed.ipv4_addresses
            if address != wanted.gateway
        )
        core_lines.extend(
            (
                f" encapsulation dot1Q {wanted.vid}",
                f" ip address {wanted.gateway.ip} {wanted.gateway.network.netmask}",
                " no shutdown",
            )
        )
    access_lines = []
    for gateway in desired.gateways:
        access_lines.extend((f"vlan {gateway.vid}", f" name {gateway.name}"))
    for port in desired.access_ports:
        access_lines.extend((f"interface {port.interface.name}", " switchport"))
        if port.mode == "trunk":
            access_lines.extend(
                (" switchport mode trunk", " switchport trunk allowed vlan 10,20")
            )
        else:
            access_lines.extend(
                (
                    " switchport mode access",
                    f" switchport access vlan {port.access_vlan}",
                )
            )
        access_lines.append(" no shutdown")
    digest = observation.managed_state_digest()
    return (
        VlanRenderedTarget(
            device_identity="netbox:dcim.device:1",
            logical_name="core-02",
            automation_profile_id=AutomationProfileID.CAT8000V_IOSXE,
            observed_managed_state_digest=digest,
            proposed_vlan_digest=desired.digest,
            payload="\n".join(core_lines) + "\n",
        ),
        VlanRenderedTarget(
            device_identity="netbox:dcim.device:9",
            logical_name="access-sw-01",
            automation_profile_id=AutomationProfileID.IOSVL2_2020,
            observed_managed_state_digest=digest,
            proposed_vlan_digest=desired.digest,
            payload="\n".join(access_lines) + "\n",
        ),
    )


def _layer1_bytes() -> bytes:
    payload = {
        "edges": [
            {
                "node1": {"hostname": a[0], "interfaceName": a[1]},
                "node2": {"hostname": b[0], "interfaceName": b[1]},
            }
            for a, b in LAYER1_EDGES
        ]
    }
    return (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _host_bytes(hostname: str, prefix: str, gateway: str) -> bytes:
    """Render the exact pinned Batfish supplemental-host schema."""
    payload = {
        "hostname": hostname,
        "hostInterfaces": {
            "eth0": {"name": "eth0", "prefix": prefix, "gateway": gateway}
        },
    }
    return (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()


def build_vlan_candidate_snapshot(
    underlay_intent: RoutedUnderlayIntent,
    underlay_desired: RoutedUnderlayDesiredState,
    ospf_intent: OspfTriangleIntent,
    ospf_desired: OspfDesiredState,
    vlan_intent: VlanServiceIntent,
    vlan_desired: VlanDesiredState,
) -> PreparedSnapshot:
    if vlan_desired != build_vlan_desired_state(vlan_intent):
        raise ValueError("VLAN candidate is detached from intent")
    with build_ospf_triangle_candidate_snapshot(
        underlay_intent, underlay_desired, ospf_intent, ospf_desired
    ) as base:
        files = {
            path.name: path.read_bytes() for path in (base.root / "configs").iterdir()
        }
    core = files["core-02.cfg"].decode().rstrip("\n")
    core += "\ninterface GigabitEthernet3\n no ip address\n no shutdown\n"
    for gateway in vlan_desired.gateways:
        core += (
            f"interface {gateway.subinterface.name}\n"
            f" encapsulation dot1Q {gateway.vid}\n"
            f" ip address {gateway.gateway.ip} {gateway.gateway.network.netmask}\n"
            " no shutdown\n"
        )
    access = files["access-sw-01.cfg"].decode().rstrip("\n") + "\n"
    for gateway in vlan_desired.gateways:
        access += f"vlan {gateway.vid}\n name {gateway.name}\n"
    access += (
        "interface GigabitEthernet0/1\n switchport\n switchport mode trunk\n"
        " switchport trunk allowed vlan 10,20\n no shutdown\n"
        "interface GigabitEthernet0/2\n switchport\n switchport mode access\n"
        " switchport access vlan 10\n no shutdown\n"
        "interface GigabitEthernet0/3\n switchport\n switchport mode access\n"
        " switchport access vlan 20\n no shutdown\n"
    )
    files["core-02.cfg"] = core.encode()
    files["access-sw-01.cfg"] = access.encode()
    source = [(f"configs/{name}", content) for name, content in files.items()]
    source.append(("batfish/layer1_topology.json", _layer1_bytes()))
    source.extend(
        (
            (
                "hosts/assurance-users-probe.json",
                _host_bytes("assurance-users-probe", "10.60.10.100/24", "10.60.10.1"),
            ),
            (
                "hosts/assurance-servers-probe.json",
                _host_bytes(
                    "assurance-servers-probe",
                    "10.60.20.100/24",
                    "10.60.20.1",
                ),
            ),
        )
    )
    return prepare_snapshot_with_layer1_from_bytes(source)


class VlanTrace(BaseModel):
    """One bounded Batfish path for an exact assurance-only fixture flow."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    disposition: str = Field(min_length=1, max_length=64, pattern=r"^[A-Z_]+$")
    nodes: tuple[str, ...] = Field(min_length=1, max_length=16)
    final_node: str = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def final_node_is_last_hop(self) -> VlanTrace:
        if self.final_node != self.nodes[-1]:
            raise ValueError("VLAN trace final node is inconsistent")
        return self


class VlanFlow(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    name: Literal[
        "users_gateway",
        "servers_gateway",
        "users_to_servers",
        "servers_to_users",
    ]
    reported_trace_count: int = Field(ge=0, le=32)
    traces: tuple[VlanTrace, ...] = Field(max_length=32)

    @model_validator(mode="after")
    def complete_trace_population(self) -> VlanFlow:
        if self.reported_trace_count != len(self.traces):
            raise ValueError("Batfish VLAN trace collection was truncated")
        return self


class VlanBatfishObservation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    ospf: OspfTriangleBatfishObservation
    modeled_nodes: tuple[str, ...]
    layer1_edges: tuple[tuple[tuple[str, str], tuple[str, str]], ...]
    switched_vlans: tuple[tuple[int, tuple[str, ...]], ...]
    switchports: tuple[
        tuple[str, str, str, tuple[int, ...], int | None, int | None], ...
    ]
    gateways: tuple[tuple[str, str, str], ...]
    access_l3_interfaces: tuple[str, ...]
    connected_routes: tuple[str, ...]
    remote_ospf_vlan_routes: tuple[str, ...]
    flows: tuple[VlanFlow, ...]


class VlanServiceAssuranceEvidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    generated_at: datetime
    routed_underlay_digest: Sha256Digest
    ospf_digest: Sha256Digest
    vlan_digest: Sha256Digest
    candidate_snapshot_digest: Sha256Digest
    pybatfish_version: str
    batfish_version: str
    managed_network_nodes: tuple[str, ...]
    assurance_fixture_hosts: tuple[str, ...]
    modeled_nodes: tuple[str, ...]
    ospf_router_count: int
    ospf_adjacency_count: int
    vlan_count: int
    vlan_gateway_count: int
    infrastructure_layer1_edge_count: int
    assurance_fixture_edge_count: int
    total_layer1_edge_count: int
    invariants: tuple[InvariantResult, ...]
    outcome: AssuranceOutcome

    @model_validator(mode="after")
    def consistent(self) -> VlanServiceAssuranceEvidence:
        expected = (
            AssuranceOutcome.PASSED
            if self.invariants and all(item.passed for item in self.invariants)
            else AssuranceOutcome.FAILED
        )
        if (
            self.routed_underlay_digest != ACCEPTED_ROUTED_UNDERLAY_D1_DIGEST
            or self.ospf_digest
            != "sha256:55f5718089228eb4e9f3badebca036135461c10b3c4312184462b5468d463182"
            or self.vlan_digest != ACCEPTED_VLAN_D1_DIGEST
            or self.candidate_snapshot_digest != ACCEPTED_VLAN_CANDIDATE_DIGEST
            or self.managed_network_nodes != MANAGED_NETWORK_NODES
            or self.assurance_fixture_hosts != ASSURANCE_FIXTURE_HOSTS
            or self.modeled_nodes != MODELED_NODES
            or self.ospf_router_count != 3
            or self.ospf_adjacency_count != 3
            or self.vlan_count != 2
            or self.vlan_gateway_count != 2
            or self.infrastructure_layer1_edge_count != 4
            or self.assurance_fixture_edge_count != 2
            or self.total_layer1_edge_count != 6
            or tuple(item.name for item in self.invariants) != VLAN_COMBINED_INVARIANTS
            or self.outcome is not expected
        ):
            raise ValueError("VLAN assurance outcome is inconsistent")
        return self


class VlanAssuranceProvider(Protocol):
    def analyze(self, candidate: Path) -> VlanBatfishObservation: ...


class BatfishVlanAdapter:
    """Pinned Batfish semantic analyzer for exact router-on-a-stick candidate."""

    def __init__(self, host: str | None = None) -> None:
        self.host = host or os.environ.get("NCDP_BATFISH_HOST", "127.0.0.1")

    def analyze(self, candidate: Path) -> VlanBatfishObservation:
        try:
            from pybatfish.client.session import Session

        except ImportError:
            raise AssuranceProviderError(
                "Batfish provider dependency unavailable"
            ) from None
        # Existing semantic adapter preserves all B4-2 questions/invariants.
        ospf = BatfishOspfTriangleAdapter(self.host).analyze(candidate)
        with prepare_snapshot_with_layer1(candidate) as frozen:
            snapshot = "ncdp-b4-vlan-" + uuid.uuid4().hex
            try:
                session = Session(host=self.host, port=9996)
                session.init_snapshot(str(frozen.root), name=snapshot, overwrite=False)
                node_rows = (
                    session.q.nodeProperties()
                    .answer(snapshot=snapshot)
                    .frame()
                    .reset_index()
                )
                node_column = next(
                    column
                    for column in node_rows.columns
                    if str(column).casefold() == "node"
                )
                modeled_nodes = tuple(
                    sorted(str(value) for value in node_rows[node_column].tolist())
                )
                layer_rows = (
                    session.q.userProvidedLayer1Edges()
                    .answer(snapshot=snapshot)
                    .frame()
                )
                layer_edges = []
                for _, row in layer_rows.iterrows():
                    values = [str(value) for value in row.values if "[" in str(value)]
                    if len(values) < 2:
                        continue

                    def split(value: str) -> tuple[str, str]:
                        match = re.fullmatch(r"([^\[]+)\[([^\]]+)\]", value)
                        if match is None:
                            raise AssuranceProviderError(
                                "Batfish layer-1 schema is unsupported"
                            )
                        return match.group(1), match.group(2)

                    layer_edges.append(
                        tuple(sorted((split(values[0]), split(values[1]))))
                    )
                props = (
                    session.q.interfaceProperties()
                    .answer(snapshot=snapshot)
                    .frame()
                    .reset_index()
                )
                switchports = []
                gateways = []
                access_l3_interfaces = []
                for _, row in props.iterrows():
                    interface_value = str(
                        row[
                            next(
                                c
                                for c in props.columns
                                if str(c).casefold() == "interface"
                            )
                        ]
                    )
                    match = re.fullmatch(r"([^\[]+)\[([^\]]+)\]", interface_value)
                    if not match:
                        continue
                    node, interface = match.groups()
                    rowmap = {str(k).casefold(): v for k, v in row.items()}
                    if node == "access-sw-01" and interface in {
                        "GigabitEthernet0/1",
                        "GigabitEthernet0/2",
                        "GigabitEthernet0/3",
                    }:
                        allowed = tuple(
                            sorted(
                                int(v)
                                for v in re.findall(
                                    r"\d+", str(rowmap.get("allowed_vlans", ""))
                                )
                                if int(v) in {10, 20}
                            )
                        )

                        def number(
                            key: str, values: dict[str, object] = rowmap
                        ) -> int | None:
                            found = re.search(r"\d+", str(values.get(key, "")))
                            return int(found.group()) if found else None

                        switchports.append(
                            (
                                node,
                                interface,
                                str(
                                    rowmap.get(
                                        "switchport_mode", rowmap.get("switchport", "")
                                    )
                                ).casefold(),
                                allowed,
                                number("access_vlan"),
                                number("native_vlan"),
                            )
                        )
                    if node == "access-sw-01" and (
                        interface in {"Vlan10", "Vlan20"}
                        or "10.60.10." in str(rowmap.get("all_prefixes", ""))
                        or "10.60.20." in str(rowmap.get("all_prefixes", ""))
                    ):
                        access_l3_interfaces.append(interface)
                    if node == "core-02" and interface in {
                        "GigabitEthernet3.10",
                        "GigabitEthernet3.20",
                    }:
                        gateways.append(
                            (node, interface, str(rowmap.get("all_prefixes", "")))
                        )
                switched_rows = (
                    session.q.switchedVlanProperties().answer(snapshot=snapshot).frame()
                )
                switched_vlans = []
                for _, row in switched_rows.iterrows():
                    rowmap = {str(key).casefold(): value for key, value in row.items()}
                    if str(rowmap.get("node")) != "access-sw-01":
                        continue
                    vlan_match = re.search(r"\d+", str(rowmap.get("vlan_id", "")))
                    if vlan_match is None or int(vlan_match.group()) not in {10, 20}:
                        continue
                    interfaces = tuple(
                        sorted(
                            match.group(1)
                            for match in re.finditer(
                                r"access-sw-01\[([^\]]+)\]",
                                str(rowmap.get("interfaces", "")),
                            )
                        )
                    )
                    switched_vlans.append((int(vlan_match.group()), interfaces))
                routes = session.q.routes().answer(snapshot=snapshot).frame()
                connected = []
                remote = []
                for _, row in routes.iterrows():
                    mapping = {str(k).casefold(): str(v) for k, v in row.items()}
                    network = mapping.get("network", "")
                    if network in {"10.60.10.0/24", "10.60.20.0/24"}:
                        if (
                            mapping.get("node") == "core-02"
                            and mapping.get("protocol", "").casefold() == "connected"
                        ):
                            connected.append(network)
                        if (
                            mapping.get("node") in {"edge-junos-01", "transit-ios-01"}
                            and "ospf" in mapping.get("protocol", "").casefold()
                        ):
                            remote.append(f"{mapping.get('node')}:{network}")
                flows = []
                for name, start, src, dst in (
                    (
                        "users_gateway",
                        "assurance-users-probe",
                        "10.60.10.100",
                        "10.60.10.1",
                    ),
                    (
                        "servers_gateway",
                        "assurance-servers-probe",
                        "10.60.20.100",
                        "10.60.20.1",
                    ),
                    (
                        "users_to_servers",
                        "assurance-users-probe",
                        "10.60.10.100",
                        "10.60.20.100",
                    ),
                    (
                        "servers_to_users",
                        "assurance-servers-probe",
                        "10.60.20.100",
                        "10.60.10.100",
                    ),
                ):
                    rows = (
                        session.q.traceroute(
                            startLocation=start,
                            headers={"srcIps": src, "dstIps": dst},
                            maxTraces=32,
                        )
                        .answer(snapshot=snapshot)
                        .frame()
                    )
                    traces = []
                    reported_trace_count = 0
                    for _, row in rows.iterrows():
                        count = row.get("TraceCount")
                        if isinstance(count, bool):
                            raise AssuranceProviderError(
                                "Batfish VLAN trace count is invalid"
                            )
                        try:
                            reported_trace_count += int(count)
                        except (TypeError, ValueError, OverflowError):
                            raise AssuranceProviderError(
                                "Batfish VLAN trace count is invalid"
                            ) from None
                        for trace in row.get("Traces", ()):
                            nodes = tuple(str(hop.node) for hop in trace.hops)
                            if not nodes:
                                raise AssuranceProviderError(
                                    "Batfish VLAN trace has no modeled path"
                                )
                            traces.append(
                                VlanTrace(
                                    disposition=str(trace.disposition).upper(),
                                    nodes=nodes,
                                    final_node=nodes[-1],
                                )
                            )
                    flows.append(
                        VlanFlow(
                            name=name,
                            reported_trace_count=reported_trace_count,
                            traces=tuple(traces),
                        )
                    )
                return VlanBatfishObservation(
                    ospf=ospf,
                    modeled_nodes=modeled_nodes,
                    layer1_edges=tuple(sorted(layer_edges)),
                    switched_vlans=tuple(sorted(switched_vlans)),
                    switchports=tuple(sorted(switchports)),
                    gateways=tuple(sorted(gateways)),
                    access_l3_interfaces=tuple(sorted(set(access_l3_interfaces))),
                    connected_routes=tuple(sorted(set(connected))),
                    remote_ospf_vlan_routes=tuple(sorted(set(remote))),
                    flows=tuple(flows),
                )
            except AssuranceProviderError:
                raise
            except Exception as error:
                raise AssuranceProviderError(
                    "Batfish VLAN service analysis failed"
                ) from error


def evaluate_vlan_assurance(
    underlay: RoutedUnderlayDesiredState,
    ospf: OspfDesiredState,
    vlan: VlanDesiredState,
    snapshot_digest: str,
    observation: VlanBatfishObservation,
) -> VlanServiceAssuranceEvidence:
    # Compose the historical routed-underlay/OSPF checks over their exact
    # ownership envelope. VLAN gateways and assurance-host coordinates are
    # deliberately evaluated by the VLAN invariants below.
    underlay_prefixes = tuple(
        item
        for item in observation.ospf.underlay.interface_prefixes
        if str(ipaddress.ip_interface(item.prefix).network)
        in {"10.60.0.0/30", "10.60.0.4/30", "10.60.0.8/30"}
    )
    ospf_observation = observation.ospf.model_copy(
        update={
            "underlay": observation.ospf.underlay.model_copy(
                update={"interface_prefixes": underlay_prefixes}
            )
        }
    )
    base = evaluate_ospf_triangle_assurance(
        underlay, ospf, snapshot_digest, ospf_observation
    )
    expected_edges = {tuple(sorted(edge)) for edge in LAYER1_EDGES}
    expected_switchports = {
        ("access-sw-01", "GigabitEthernet0/1", "trunk", (10, 20), None),
        ("access-sw-01", "GigabitEthernet0/2", "access", (), 10),
        ("access-sw-01", "GigabitEthernet0/3", "access", (), 20),
    }
    observed_switchports = {
        (n, i, "trunk" if "trunk" in m else "access", a, v)
        for n, i, m, a, v, native in observation.switchports
        if native not in {10, 20}
    }
    flow_map = {item.name: item for item in observation.flows}

    def exact_flow(name: str, final_node: str) -> bool:
        flow = flow_map.get(name)
        return bool(
            flow
            and flow.traces
            and all(
                trace.disposition == "ACCEPTED" and trace.final_node == final_node
                for trace in flow.traces
            )
        )

    def every_path_has(name: str, node: str) -> bool:
        flow = flow_map.get(name)
        return bool(
            flow and flow.traces and all(node in trace.nodes for trace in flow.traces)
        )

    def every_path_excludes(name: str, nodes: set[str]) -> bool:
        flow = flow_map.get(name)
        return bool(
            flow
            and flow.traces
            and all(not nodes.intersection(trace.nodes) for trace in flow.traces)
        )

    vlan_invariants = (
        InvariantResult(
            name="vlan_exact_modeled_population",
            passed=observation.modeled_nodes == MODELED_NODES,
            detail="four managed network nodes and two assurance hosts are modeled",
        ),
        InvariantResult(
            name="vlan_exact_layer1_edges",
            passed=set(observation.layer1_edges) == expected_edges,
            detail="exact four infrastructure and two assurance edges are modeled",
        ),
        InvariantResult(
            name="vlan_exact_switched_membership",
            passed=set(observation.switched_vlans)
            == {
                (10, ("GigabitEthernet0/1", "GigabitEthernet0/2")),
                (20, ("GigabitEthernet0/1", "GigabitEthernet0/3")),
            },
            detail="service VLAN membership is exact on the access switch",
        ),
        InvariantResult(
            name="vlan_exact_switchports",
            passed=observed_switchports == expected_switchports,
            detail="trunk and access switchport semantics are exact",
        ),
        InvariantResult(
            name="vlan_service_not_native",
            passed=all(item[5] not in {10, 20} for item in observation.switchports),
            detail="service VLANs are not native",
        ),
        InvariantResult(
            name="vlan_exact_gateways",
            passed={
                (i, "10.60.10.1/24" in p, "10.60.20.1/24" in p)
                for _, i, p in observation.gateways
            }
            == {
                ("GigabitEthernet3.10", True, False),
                ("GigabitEthernet3.20", False, True),
            },
            detail="core owns exact router-on-a-stick gateways",
        ),
        InvariantResult(
            name="vlan_access_has_no_gateway",
            passed=not observation.access_l3_interfaces,
            detail="access switch owns no VLAN 10/20 L3 interface",
        ),
        InvariantResult(
            name="vlan_connected_routes",
            passed=set(observation.connected_routes)
            == {"10.60.10.0/24", "10.60.20.0/24"},
            detail="core has both connected VLAN routes",
        ),
        InvariantResult(
            name="vlan_not_advertised_ospf",
            passed=not observation.remote_ospf_vlan_routes,
            detail="remote routers learn no VLAN prefix through OSPF",
        ),
        InvariantResult(
            name="vlan_gateway_flows",
            passed=exact_flow("users_gateway", "core-02")
            and exact_flow("servers_gateway", "core-02"),
            detail="all gateway traces terminate ACCEPTED at core-02",
        ),
        InvariantResult(
            name="vlan_intervlan_open",
            passed=exact_flow("users_to_servers", "assurance-servers-probe")
            and exact_flow("servers_to_users", "assurance-users-probe"),
            detail="all inter-VLAN traces terminate ACCEPTED at the exact fixture",
        ),
        InvariantResult(
            name="vlan_intervlan_traverses_core",
            passed=every_path_has("users_to_servers", "core-02")
            and every_path_has("servers_to_users", "core-02"),
            detail="every inter-VLAN trace traverses core-02",
        ),
        InvariantResult(
            name="vlan_intervlan_excludes_remote_routers",
            passed=every_path_excludes(
                "users_to_servers", {"edge-junos-01", "transit-ios-01"}
            )
            and every_path_excludes(
                "servers_to_users", {"edge-junos-01", "transit-ios-01"}
            ),
            detail="no inter-VLAN trace transits a remote router",
        ),
    )
    invariants = base.invariants + vlan_invariants
    outcome = (
        AssuranceOutcome.PASSED
        if all(item.passed for item in invariants)
        else AssuranceOutcome.FAILED
    )
    return VlanServiceAssuranceEvidence(
        generated_at=datetime.now(UTC),
        routed_underlay_digest=underlay.digest,
        ospf_digest=ospf.digest,
        vlan_digest=vlan.digest,
        candidate_snapshot_digest=snapshot_digest,
        pybatfish_version=observation.ospf.underlay.pybatfish_version,
        batfish_version=observation.ospf.underlay.batfish_version,
        managed_network_nodes=observation.ospf.underlay.candidate_parse.nodes,
        assurance_fixture_hosts=ASSURANCE_FIXTURE_HOSTS,
        modeled_nodes=observation.modeled_nodes,
        ospf_router_count=len(observation.ospf.processes),
        ospf_adjacency_count=len(observation.ospf.edges),
        vlan_count=2,
        vlan_gateway_count=2,
        infrastructure_layer1_edge_count=len(INFRASTRUCTURE_LAYER1_EDGES),
        assurance_fixture_edge_count=len(ASSURANCE_FIXTURE_EDGES),
        total_layer1_edge_count=len(observation.layer1_edges),
        invariants=invariants,
        outcome=outcome,
    )


def assure_vlan_candidate(
    underlay_intent: RoutedUnderlayIntent,
    underlay_desired: RoutedUnderlayDesiredState,
    ospf_intent: OspfTriangleIntent,
    ospf_desired: OspfDesiredState,
    vlan_intent: VlanServiceIntent,
    vlan_desired: VlanDesiredState,
    provider: VlanAssuranceProvider | None = None,
) -> VlanServiceAssuranceEvidence:
    with build_vlan_candidate_snapshot(
        underlay_intent,
        underlay_desired,
        ospf_intent,
        ospf_desired,
        vlan_intent,
        vlan_desired,
    ) as candidate:
        observed = (provider or BatfishVlanAdapter()).analyze(candidate.root)
        return evaluate_vlan_assurance(
            underlay_desired,
            ospf_desired,
            vlan_desired,
            candidate.manifest.digest,
            observed,
        )


class VlanServiceProposalEvidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal["1"] = "1"
    source_data_plane_digest: Sha256Digest
    source_vlan_service_digest: Sha256Digest
    intent: VlanServiceIntent
    ownership_envelope: ManagedOwnershipEnvelope
    current_observation: VlanObservation
    current_managed_digest: Sha256Digest
    proposed_desired_state: VlanDesiredState
    rendered_targets: tuple[VlanRenderedTarget, VlanRenderedTarget]
    combined_assurance: VlanServiceAssuranceEvidence
    device_writes: Literal[0] = 0

    @model_validator(mode="after")
    def bound(self) -> VlanServiceProposalEvidence:
        if (
            self.source_data_plane_digest != ACCEPTED_REFERENCE_ALLOCATION_DIGEST
            or self.source_vlan_service_digest
            != ACCEPTED_VLAN_SERVICE_ALLOCATION_DIGEST
            or self.ownership_envelope != build_vlan_ownership_envelope(self.intent)
            or self.current_managed_digest
            != self.current_observation.managed_state_digest()
            or self.proposed_desired_state != build_vlan_desired_state(self.intent)
            or self.rendered_targets
            != render_vlan_changes(
                self.intent, self.current_observation, self.proposed_desired_state
            )
            or self.combined_assurance.outcome is not AssuranceOutcome.PASSED
            or self.combined_assurance.routed_underlay_digest
            != ACCEPTED_ROUTED_UNDERLAY_D1_DIGEST
            or self.combined_assurance.ospf_digest
            != "sha256:55f5718089228eb4e9f3badebca036135461c10b3c4312184462b5468d463182"
            or self.combined_assurance.vlan_digest != self.proposed_desired_state.digest
            or self.combined_assurance.managed_network_nodes
            != ("access-sw-01", "core-02", "edge-junos-01", "transit-ios-01")
            or self.combined_assurance.assurance_fixture_hosts
            != ASSURANCE_FIXTURE_HOSTS
            or self.combined_assurance.modeled_nodes != MODELED_NODES
            or self.combined_assurance.infrastructure_layer1_edge_count != 4
            or self.combined_assurance.assurance_fixture_edge_count != 2
            or self.combined_assurance.total_layer1_edge_count != 6
            or self.combined_assurance.vlan_count != 2
            or self.combined_assurance.vlan_gateway_count != 2
            or self.combined_assurance.ospf_router_count != 3
            or self.combined_assurance.ospf_adjacency_count != 3
        ):
            raise ValueError("VLAN proposal evidence is inconsistent")
        return self


def build_vlan_proposal_evidence(
    intent: VlanServiceIntent,
    observation: VlanObservation,
    desired: VlanDesiredState,
    assurance: VlanServiceAssuranceEvidence,
) -> VlanServiceProposalEvidence:
    return VlanServiceProposalEvidence(
        source_data_plane_digest=reference_allocation_digest(intent.source_data_plane),
        source_vlan_service_digest=vlan_service_allocation_digest(
            intent.source_vlan_service
        ),
        intent=intent,
        ownership_envelope=build_vlan_ownership_envelope(intent),
        current_observation=observation,
        current_managed_digest=observation.managed_state_digest(),
        proposed_desired_state=desired,
        rendered_targets=render_vlan_changes(intent, observation, desired),
        combined_assurance=assurance,
    )
