"""Read-only desired-state vertical for the exact three-router OSPF triangle."""

from __future__ import annotations

import ipaddress
import os
import re
import uuid
from datetime import UTC, datetime
from enum import StrEnum
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path, PurePosixPath
from typing import Any, Literal, Protocol
from xml.etree import ElementTree

from pydantic import BaseModel, ConfigDict, Field, model_validator

from network_change_delivery.ansible_adapter import (
    AnsibleRunnerCiscoAdapter,
    ProviderError,
)
from network_change_delivery.architecture_contracts import (
    AutomationProfileID,
    ManagedField,
    ManagedOwnershipEnvelope,
    ManagedScopeIdentity,
    ManagedScopeKind,
    ManagedVertical,
    NetBoxDeviceIdentity,
    NetBoxIPAddressIdentity,
    Sha256Digest,
    StableInterfaceIdentity,
)
from network_change_delivery.assurance import (
    AssuranceOutcome,
    AssuranceProviderError,
    InvariantResult,
    ParseFileResult,
    ParseSummary,
    PreparedSnapshot,
    prepare_snapshot,
    prepare_snapshot_from_bytes,
)
from network_change_delivery.audit import canonical_json_bytes, sha256_identity
from network_change_delivery.junos_adapter import JunosPyEZAdapter
from network_change_delivery.profile_inventory import (
    PROFILED_POPULATION_CATALOG,
    ProfiledInventoryDevice,
    ProfiledInventoryPopulation,
    ProfileReadOnlyTarget,
)
from network_change_delivery.reference_data_plane import (
    ACCEPTED_REFERENCE_ALLOCATION_DIGEST,
    ReferenceDataPlaneAllocation,
    reference_allocation_digest,
)
from network_change_delivery.reference_routing_identity import (
    ACCEPTED_ROUTING_IDENTITY_ALLOCATION_DIGEST,
    ReferenceRoutingIdentityAllocation,
    routing_identity_allocation_digest,
)
from network_change_delivery.routed_underlay import (
    ACCEPTED_ROUTED_UNDERLAY_D1_DIGEST,
    EXPECTED_PROFILED_NAMES,
    MANAGEMENT_INTERFACE_IDENTITIES,
    BatfishInterfacePrefix,
    RoutedUnderlayBatfishObservation,
    RoutedUnderlayDesiredState,
    RoutedUnderlayFlow,
    RoutedUnderlayIntent,
    build_routed_underlay_desired_state,
    evaluate_routed_underlay_common_invariants,
)
from network_change_delivery.secrets import DeviceCredentials

OSPF_POLICY_IDENTITY = "git:policy:ospf-underlay"
OSPF_AREA = "0.0.0.0"
CISCO_OSPF_PROCESS_ID = 1
OSPF_DEVICE_IDENTITIES = (
    "netbox:dcim.device:1",
    "netbox:dcim.device:2",
    "netbox:dcim.device:8",
)
OSPF_NAMES = ("core-02", "edge-junos-01", "transit-ios-01")
_PREFIX_PATTERN = re.compile(r"(?<![0-9.])(?:[0-9]{1,3}\.){3}[0-9]{1,3}/[0-9]{1,2}")


class OspfNetworkType(StrEnum):
    """Only network type admitted by the B4-2 service."""

    POINT_TO_POINT = "point-to-point"


class OspfInterfaceIntent(BaseModel):
    """Git-owned participation over one exact routed-underlay interface."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    interface: StableInterfaceIdentity
    area: Literal["0.0.0.0"] = OSPF_AREA
    network_type: Literal[OspfNetworkType.POINT_TO_POINT] = (
        OspfNetworkType.POINT_TO_POINT
    )
    passive: Literal[False] = False


class OspfRouterIntent(BaseModel):
    """One exact router and its two OSPF interface intentions."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    device_identity: NetBoxDeviceIdentity
    logical_name: Literal["core-02", "edge-junos-01", "transit-ios-01"]
    automation_profile_id: AutomationProfileID
    router_id_identity: NetBoxIPAddressIdentity
    router_id: ipaddress.IPv4Address
    interfaces: tuple[OspfInterfaceIntent, OspfInterfaceIntent]


def _ospf_routers_from_allocations(
    underlay: ReferenceDataPlaneAllocation,
    routing: ReferenceRoutingIdentityAllocation,
) -> tuple[OspfRouterIntent, OspfRouterIntent, OspfRouterIntent]:
    endpoints: dict[str, list[StableInterfaceIdentity]] = {
        identity: [] for identity in OSPF_DEVICE_IDENTITIES
    }
    for link in underlay.routed_links:
        for endpoint in link.endpoints:
            endpoints[endpoint.interface.device].append(endpoint.interface)
    profiles = {
        "core-02": AutomationProfileID.CAT8000V_IOSXE,
        "edge-junos-01": AutomationProfileID.VJUNOS_ROUTER,
        "transit-ios-01": AutomationProfileID.IOSV_159_3_M12,
    }
    return tuple(  # type: ignore[return-value]
        OspfRouterIntent(
            device_identity=identity.device_identity,
            logical_name=identity.logical_name,
            automation_profile_id=profiles[identity.logical_name],
            router_id_identity=identity.ip_address_identity,
            router_id=identity.router_id,
            interfaces=tuple(  # type: ignore[arg-type]
                OspfInterfaceIntent(interface=interface)
                for interface in endpoints[identity.device_identity]
            ),
        )
        for identity in routing.routers
    )


class OspfTriangleIntent(BaseModel):
    """Exact Git-owned area-0 triangle over resolved NetBox factual authority."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal["1"] = "1"
    policy_identity: Literal["git:policy:ospf-underlay"] = OSPF_POLICY_IDENTITY
    source_underlay: ReferenceDataPlaneAllocation
    source_routing_identities: ReferenceRoutingIdentityAllocation
    routers: tuple[OspfRouterIntent, OspfRouterIntent, OspfRouterIntent]

    @classmethod
    def from_allocations(
        cls,
        underlay: ReferenceDataPlaneAllocation,
        routing: ReferenceRoutingIdentityAllocation,
    ) -> OspfTriangleIntent:
        routers = _ospf_routers_from_allocations(underlay, routing)
        return cls(
            source_underlay=underlay,
            source_routing_identities=routing,
            routers=routers,  # type: ignore[arg-type]
        )

    @model_validator(mode="after")
    def exact_authority_and_triangle(self) -> OspfTriangleIntent:
        expected = _ospf_routers_from_allocations(
            self.source_underlay, self.source_routing_identities
        )
        interfaces = tuple(
            interface for router in self.routers for interface in router.interfaces
        )
        if (
            self.routers != expected
            or tuple(router.device_identity for router in self.routers)
            != OSPF_DEVICE_IDENTITIES
            or tuple(router.logical_name for router in self.routers) != OSPF_NAMES
            or len({item.interface.interface for item in interfaces}) != 6
            or any(
                item.interface.interface in MANAGEMENT_INTERFACE_IDENTITIES
                for item in interfaces
            )
        ):
            raise ValueError("OSPF triangle intent is detached from source authority")
        return self


class DesiredOspfInterfaceState(BaseModel):
    """Vendor-independent desired OSPF state for one exact interface."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    interface: StableInterfaceIdentity
    participating: Literal[True] = True
    area: Literal["0.0.0.0"] = OSPF_AREA
    network_type: Literal[OspfNetworkType.POINT_TO_POINT] = (
        OspfNetworkType.POINT_TO_POINT
    )
    passive: Literal[False] = False


class DesiredOspfRouterState(BaseModel):
    """Vendor-independent desired OSPF process state for one router."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    device_identity: NetBoxDeviceIdentity
    logical_name: Literal["core-02", "edge-junos-01", "transit-ios-01"]
    automation_profile_id: AutomationProfileID
    process_present: Literal[True] = True
    router_id_identity: NetBoxIPAddressIdentity
    router_id: ipaddress.IPv4Address
    interfaces: tuple[DesiredOspfInterfaceState, DesiredOspfInterfaceState]


class OspfDesiredState(BaseModel):
    """Deterministic proposed OSPF D1, independent from routed-underlay D1."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal["1"] = "1"
    routers: tuple[
        DesiredOspfRouterState, DesiredOspfRouterState, DesiredOspfRouterState
    ]
    digest: Sha256Digest

    @model_validator(mode="after")
    def exact_desired_population(self) -> OspfDesiredState:
        interfaces = tuple(
            interface for router in self.routers for interface in router.interfaces
        )
        if (
            tuple(router.device_identity for router in self.routers)
            != OSPF_DEVICE_IDENTITIES
            or tuple(router.logical_name for router in self.routers) != OSPF_NAMES
            or len({item.interface.interface for item in interfaces}) != 6
            or any(
                item.interface.interface in MANAGEMENT_INTERFACE_IDENTITIES
                for item in interfaces
            )
        ):
            raise ValueError("OSPF desired state is not exact")
        return self

    def digest_input(self) -> bytes:
        return canonical_json_bytes(self.model_dump(mode="json", exclude={"digest"}))

    def calculated_digest(self) -> str:
        return sha256_identity(self.digest_input())

    def verify_digest(self) -> bool:
        return self.digest == self.calculated_digest()


def build_ospf_desired_state(intent: OspfTriangleIntent) -> OspfDesiredState:
    """Normalize exact OSPF intent into proposed D1."""
    routers = tuple(
        DesiredOspfRouterState(
            device_identity=router.device_identity,
            logical_name=router.logical_name,
            automation_profile_id=router.automation_profile_id,
            router_id_identity=router.router_id_identity,
            router_id=router.router_id,
            interfaces=tuple(  # type: ignore[arg-type]
                DesiredOspfInterfaceState(interface=item.interface)
                for item in router.interfaces
            ),
        )
        for router in intent.routers
    )
    unsigned = OspfDesiredState(
        routers=routers,  # type: ignore[arg-type]
        digest="sha256:" + "0" * 64,
    )
    return unsigned.model_copy(update={"digest": unsigned.calculated_digest()})


def build_ospf_ownership_envelope(
    intent: OspfTriangleIntent,
) -> ManagedOwnershipEnvelope:
    """Own only the exact OSPF process/router/interface fields in B4-2."""
    return ManagedOwnershipEnvelope(
        vertical=ManagedVertical.OSPF,
        envelope_version=1,
        targets=OSPF_DEVICE_IDENTITIES,
        scope=tuple(
            [
                ManagedScopeIdentity(
                    kind=ManagedScopeKind.DEVICE, identity=router.device_identity
                )
                for router in intent.routers
            ]
            + [
                ManagedScopeIdentity(
                    kind=ManagedScopeKind.INTERFACE,
                    identity=interface.interface.interface,
                )
                for router in intent.routers
                for interface in router.interfaces
            ]
            + [
                ManagedScopeIdentity(
                    kind=ManagedScopeKind.IP_ADDRESS,
                    identity=router.router_id_identity,
                )
                for router in intent.routers
            ]
            + [
                ManagedScopeIdentity(
                    kind=ManagedScopeKind.POLICY,
                    identity=OSPF_POLICY_IDENTITY,
                )
            ]
        ),
        normalized_fields=(
            ManagedField.OSPF_PROCESS,
            ManagedField.OSPF_ROUTER_ID,
            ManagedField.OSPF_INTERFACE_PARTICIPATION,
            ManagedField.OSPF_AREA,
            ManagedField.OSPF_NETWORK_TYPE,
            ManagedField.OSPF_PASSIVE,
        ),
    )


class ObservedOspfInterfaceState(BaseModel):
    """Observed managed OSPF fields for one exact interface."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    interface: StableInterfaceIdentity
    participating: bool
    area: str | None = None
    network_type: str | None = None
    passive: bool | None = None

    @model_validator(mode="after")
    def consistent_observation(self) -> ObservedOspfInterfaceState:
        if self.interface.interface in MANAGEMENT_INTERFACE_IDENTITIES:
            raise ValueError("management interface cannot enter OSPF observation")
        if not self.participating and any(
            value is not None for value in (self.area, self.network_type, self.passive)
        ):
            raise ValueError("nonparticipating OSPF interface has managed facts")
        return self


class ObservedOspfRouterState(BaseModel):
    """Observed managed OSPF process state for one router."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    device_identity: NetBoxDeviceIdentity
    logical_name: Literal["core-02", "edge-junos-01", "transit-ios-01"]
    automation_profile_id: AutomationProfileID
    process_present: bool
    process_identity: str | None = None
    router_id: ipaddress.IPv4Address | None = None
    interfaces: tuple[ObservedOspfInterfaceState, ObservedOspfInterfaceState]

    @model_validator(mode="after")
    def process_consistency(self) -> ObservedOspfRouterState:
        if not self.process_present and (
            self.process_identity is not None
            or any(item.participating for item in self.interfaces)
        ):
            raise ValueError("absent OSPF process has observed managed facts")
        return self


class OspfObservation(BaseModel):
    """Fresh exact-three OSPF observed state O."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal["1"] = "1"
    observed_at: datetime
    routers: tuple[
        ObservedOspfRouterState, ObservedOspfRouterState, ObservedOspfRouterState
    ]

    @model_validator(mode="after")
    def exact_observation(self) -> OspfObservation:
        if (
            tuple(item.device_identity for item in self.routers)
            != OSPF_DEVICE_IDENTITIES
        ):
            raise ValueError("OSPF observation population is not exact")
        return self

    def managed_state_digest(self) -> str:
        return sha256_identity(
            canonical_json_bytes(self.model_dump(mode="json", exclude={"observed_at"}))
        )


class CiscoOspfReadOnlyCollector(Protocol):
    def collect_ospf_read_only(
        self,
        target: ProfileReadOnlyTarget,
        credentials: DeviceCredentials,
        interfaces: tuple[str, str],
        *,
        ssh_type: Literal["paramiko"],
    ) -> tuple[str, str, str]: ...


class JunosOspfReadOnlyCollector(Protocol):
    def collect_ospf_read_only(
        self, target: ProfileReadOnlyTarget, credentials: DeviceCredentials
    ) -> str: ...


_UNSUPPORTED_CISCO_OSPF = re.compile(
    r"^\s*ip ospf (?:cost|authentication|message-digest-key|hello-interval|"
    r"dead-interval|retransmit-interval|transmit-delay)\b",
    re.MULTILINE,
)


def _parse_cisco_ospf(
    device: ProfiledInventoryDevice,
    interfaces: tuple[StableInterfaceIdentity, StableInterfaceIdentity],
    raw: tuple[str, str, str],
) -> ObservedOspfRouterState:
    process_text, *interface_texts = raw
    process_lines = re.findall(r"^router ospf\s+(\d+)\s*$", process_text, re.MULTILINE)
    if len(process_lines) > 1:
        raise ProviderError("Cisco OSPF multiple-process state is unsupported")
    if re.search(r"^\s*network\s+", process_text, re.MULTILINE):
        raise ProviderError("Cisco OSPF broad network statement is unsupported")
    process_id = process_lines[0] if process_lines else None
    if process_id is not None and process_id != str(CISCO_OSPF_PROCESS_ID):
        raise ProviderError("Cisco OSPF process identity is unsupported")
    router_match = re.search(
        r"^\s*router-id\s+([0-9.]+)\s*$", process_text, re.MULTILINE
    )
    router_id = router_match.group(1) if router_match else None
    passive_default = bool(
        re.search(r"^\s*passive-interface default\s*$", process_text, re.MULTILINE)
    )
    observed: list[ObservedOspfInterfaceState] = []
    for interface, text in zip(interfaces, interface_texts, strict=True):
        if _UNSUPPORTED_CISCO_OSPF.search(text):
            raise ProviderError("Cisco OSPF managed interface state is unsupported")
        participation = re.findall(
            r"^\s*ip ospf\s+(\d+)\s+area\s+(\S+)\s*$", text, re.MULTILINE
        )
        if len(participation) > 1:
            raise ProviderError("Cisco OSPF interface participation is ambiguous")
        if not participation:
            observed.append(
                ObservedOspfInterfaceState(interface=interface, participating=False)
            )
            continue
        observed_process, area = participation[0]
        if observed_process != str(CISCO_OSPF_PROCESS_ID):
            raise ProviderError("Cisco OSPF process identity is unsupported")
        network = re.findall(r"^\s*ip ospf network\s+(.+?)\s*$", text, re.MULTILINE)
        if len(network) > 1:
            raise ProviderError("Cisco OSPF network type is ambiguous")
        explicitly_passive = bool(
            re.search(
                rf"^\s*passive-interface\s+{re.escape(interface.name)}\s*$",
                process_text,
                re.MULTILINE,
            )
        )
        explicitly_active = bool(
            re.search(
                rf"^\s*no passive-interface\s+{re.escape(interface.name)}\s*$",
                process_text,
                re.MULTILINE,
            )
        )
        passive = explicitly_passive or (passive_default and not explicitly_active)
        observed.append(
            ObservedOspfInterfaceState(
                interface=interface,
                participating=True,
                area="0.0.0.0" if area == "0" else area,
                network_type=network[0].strip() if network else "broadcast",
                passive=passive,
            )
        )
    return ObservedOspfRouterState(
        device_identity=device.device_identity,
        logical_name=device.logical_name,
        automation_profile_id=device.automation_profile_id,
        process_present=process_id is not None,
        process_identity=process_id,
        router_id=router_id,
        interfaces=tuple(observed),  # type: ignore[arg-type]
    )


def _local_name(tag: object) -> str:
    return str(tag).rsplit("}", 1)[-1]


def _child_text(element: Any, name: str) -> str | None:
    for child in element:
        if _local_name(child.tag) == name and isinstance(child.text, str):
            value = child.text.strip()
            return value or None
    return None


def _parse_junos_ospf(
    device: ProfiledInventoryDevice,
    interfaces: tuple[StableInterfaceIdentity, StableInterfaceIdentity],
    raw: str,
) -> ObservedOspfRouterState:
    try:
        root = ElementTree.fromstring(raw)
    except ElementTree.ParseError:
        raise ProviderError("Junos OSPF read-only result was invalid") from None
    router_ids = [
        element.text.strip()
        for element in root.iter()
        if _local_name(element.tag) == "router-id"
        and isinstance(element.text, str)
        and element.text.strip()
    ]
    if len(router_ids) > 1:
        raise ProviderError("Junos router-ID state is ambiguous")
    ospf_elements = [
        element for element in root.iter() if _local_name(element.tag) == "ospf"
    ]
    if len(ospf_elements) > 1:
        raise ProviderError("Junos OSPF process state is ambiguous")
    memberships: dict[str, list[tuple[str, Any]]] = {
        f"{item.name}.0": [] for item in interfaces
    }
    unsupported = {
        "metric",
        "authentication",
        "authentication-key",
        "hello-interval",
        "dead-interval",
        "retransmit-interval",
        "transit-delay",
    }
    if ospf_elements:
        for area in ospf_elements[0]:
            if _local_name(area.tag) != "area":
                continue
            area_name = _child_text(area, "name")
            if area_name is None:
                continue
            for item in area:
                if _local_name(item.tag) != "interface":
                    continue
                interface_name = _child_text(item, "name")
                if interface_name not in memberships:
                    continue
                if any(
                    _local_name(element.tag) in unsupported for element in item.iter()
                ):
                    raise ProviderError(
                        "Junos OSPF managed interface state is unsupported"
                    )
                memberships[interface_name].append((area_name, item))
    observed: list[ObservedOspfInterfaceState] = []
    for interface in interfaces:
        matches = memberships[f"{interface.name}.0"]
        if len(matches) > 1:
            raise ProviderError("Junos OSPF interface has ambiguous area membership")
        if not matches:
            observed.append(
                ObservedOspfInterfaceState(interface=interface, participating=False)
            )
            continue
        area, item = matches[0]
        interface_type = _child_text(item, "interface-type") or "broadcast"
        passive = any(_local_name(element.tag) == "passive" for element in item)
        observed.append(
            ObservedOspfInterfaceState(
                interface=interface,
                participating=True,
                area=area,
                network_type=(
                    OspfNetworkType.POINT_TO_POINT
                    if interface_type == "p2p"
                    else interface_type
                ),
                passive=passive,
            )
        )
    return ObservedOspfRouterState(
        device_identity=device.device_identity,
        logical_name=device.logical_name,
        automation_profile_id=device.automation_profile_id,
        process_present=bool(ospf_elements),
        process_identity="ospf" if ospf_elements else None,
        router_id=router_ids[0] if router_ids else None,
        interfaces=tuple(observed),  # type: ignore[arg-type]
    )


class ProfileOspfReadOnlyAdapter:
    """Exact profile-dispatched OSPF collection facade with no write surface."""

    def __init__(
        self,
        *,
        known_hosts: Path | None = None,
        cisco: CiscoOspfReadOnlyCollector | None = None,
        junos: JunosOspfReadOnlyCollector | None = None,
    ) -> None:
        self._cisco = cisco or AnsibleRunnerCiscoAdapter(known_hosts=known_hosts)
        self._junos = junos or JunosPyEZAdapter(known_hosts=known_hosts)

    def collect(
        self,
        device: ProfiledInventoryDevice,
        credentials: DeviceCredentials,
        interfaces: tuple[StableInterfaceIdentity, StableInterfaceIdentity],
    ) -> ObservedOspfRouterState:
        """Collect one router through its exact admitted read-only profile."""
        if any(item.device != device.device_identity for item in interfaces):
            raise ProviderError("OSPF collection interface identity mismatch")
        if device.automation_profile_id in {
            AutomationProfileID.CAT8000V_IOSXE,
            AutomationProfileID.IOSV_159_3_M12,
        }:
            target = device.live_read_only_target()
            raw = self._cisco.collect_ospf_read_only(
                target,
                credentials,
                tuple(item.name for item in interfaces),  # type: ignore[arg-type]
                ssh_type="paramiko",
            )
            return _parse_cisco_ospf(device, interfaces, raw)
        if device.automation_profile_id is AutomationProfileID.VJUNOS_ROUTER:
            target = device.live_read_only_target()
            return _parse_junos_ospf(
                device,
                interfaces,
                self._junos.collect_ospf_read_only(target, credentials),
            )
        raise ProviderError("OSPF read-only profile is unsupported")


class OspfSecretProvider(Protocol):
    def load(self, device: ProfiledInventoryDevice) -> DeviceCredentials: ...


def collect_ospf_observation(
    intent: OspfTriangleIntent,
    population: ProfiledInventoryPopulation,
    secrets: OspfSecretProvider,
    adapter: ProfileOspfReadOnlyAdapter,
    *,
    observed_at: datetime | None = None,
) -> OspfObservation:
    """Collect a fresh exact-three managed OSPF observation with no writes."""
    devices = {device.device_identity: device for device in population.devices}
    if set(devices) != {
        "netbox:dcim.device:1",
        "netbox:dcim.device:2",
        "netbox:dcim.device:8",
        "netbox:dcim.device:9",
    }:
        raise ProviderError("profiled OSPF inventory population is not exact")
    observations: list[ObservedOspfRouterState] = []
    for router in intent.routers:
        device = devices[router.device_identity]
        if (
            device.logical_name != router.logical_name
            or device.automation_profile_id is not router.automation_profile_id
        ):
            raise ProviderError("profiled OSPF inventory binding is inconsistent")
        observations.append(
            adapter.collect(
                device,
                secrets.load(device),
                tuple(item.interface for item in router.interfaces),  # type: ignore[arg-type]
            )
        )
    return OspfObservation(
        observed_at=observed_at or datetime.now(UTC),
        routers=tuple(observations),  # type: ignore[arg-type]
    )


class OspfRenderFormat(StrEnum):
    IOS_CLI = "ios_cli"
    JUNOS_XML = "junos_xml"


class OspfRenderedTarget(BaseModel):
    """Deterministic O-to-D1 change artifact with no execution authority."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    device_identity: NetBoxDeviceIdentity
    logical_name: str
    automation_profile_id: AutomationProfileID
    observed_managed_state_digest: Sha256Digest
    proposed_ospf_digest: Sha256Digest
    format: OspfRenderFormat
    payload: str


def _render_cisco_change(
    observed: ObservedOspfRouterState, desired: DesiredOspfRouterState
) -> str:
    lines = [
        f"router ospf {CISCO_OSPF_PROCESS_ID}",
        f" router-id {desired.router_id}",
    ]
    lines.extend(
        f" no passive-interface {interface.interface.name}"
        for interface in desired.interfaces
    )
    current = {item.interface.interface: item for item in observed.interfaces}
    for interface in desired.interfaces:
        state = current[interface.interface.interface]
        lines.append(f"interface {interface.interface.name}")
        if state.participating and state.area != OSPF_AREA:
            old_area = "0" if state.area == OSPF_AREA else state.area
            lines.append(f" no ip ospf {CISCO_OSPF_PROCESS_ID} area {old_area}")
        lines.append(f" ip ospf {CISCO_OSPF_PROCESS_ID} area 0")
        lines.append(" ip ospf network point-to-point")
    return "\n".join(lines) + "\n"


def _junos_change_xml(
    observed: ObservedOspfRouterState, desired: DesiredOspfRouterState
) -> str:
    root = ElementTree.Element("configuration")
    routing_options = ElementTree.SubElement(root, "routing-options")
    ElementTree.SubElement(routing_options, "router-id").text = str(desired.router_id)
    protocols = ElementTree.SubElement(root, "protocols")
    ospf = ElementTree.SubElement(protocols, "ospf")
    current = {item.interface.interface: item for item in observed.interfaces}
    for desired_interface in desired.interfaces:
        state = current[desired_interface.interface.interface]
        logical_name = f"{desired_interface.interface.name}.0"
        if state.participating and state.area != OSPF_AREA:
            old_area = ElementTree.SubElement(ospf, "area")
            ElementTree.SubElement(old_area, "name").text = state.area
            old_interface = ElementTree.SubElement(
                old_area, "interface", {"operation": "delete"}
            )
            ElementTree.SubElement(old_interface, "name").text = logical_name
        area = ElementTree.SubElement(ospf, "area")
        ElementTree.SubElement(area, "name").text = OSPF_AREA
        interface = ElementTree.SubElement(area, "interface")
        ElementTree.SubElement(interface, "name").text = logical_name
        ElementTree.SubElement(interface, "interface-type").text = "p2p"
        if state.participating and state.passive:
            ElementTree.SubElement(interface, "passive", {"operation": "delete"})
    return ElementTree.tostring(root, encoding="unicode")


def _render_ospf_exact(
    observation: OspfObservation,
    desired: OspfDesiredState,
) -> tuple[OspfRenderedTarget, OspfRenderedTarget, OspfRenderedTarget]:
    observed = {item.device_identity: item for item in observation.routers}
    rendered: list[OspfRenderedTarget] = []
    for router in desired.routers:
        current = observed[router.device_identity]
        if router.automation_profile_id in {
            AutomationProfileID.CAT8000V_IOSXE,
            AutomationProfileID.IOSV_159_3_M12,
        }:
            format_ = OspfRenderFormat.IOS_CLI
            payload = _render_cisco_change(current, router)
        elif router.automation_profile_id is AutomationProfileID.VJUNOS_ROUTER:
            format_ = OspfRenderFormat.JUNOS_XML
            payload = _junos_change_xml(current, router)
        else:
            raise ValueError("OSPF renderer profile is unsupported")
        rendered.append(
            OspfRenderedTarget(
                device_identity=router.device_identity,
                logical_name=router.logical_name,
                automation_profile_id=router.automation_profile_id,
                observed_managed_state_digest=observation.managed_state_digest(),
                proposed_ospf_digest=desired.digest,
                format=format_,
                payload=payload,
            )
        )
    return tuple(rendered)  # type: ignore[return-value]


def render_ospf_changes(
    intent: OspfTriangleIntent,
    observation: OspfObservation,
    desired: OspfDesiredState,
) -> tuple[OspfRenderedTarget, OspfRenderedTarget, OspfRenderedTarget]:
    """Render exact O-to-D1 managed changes; never an execution request."""
    if desired != build_ospf_desired_state(intent):
        raise ValueError("OSPF desired state is detached from intent")
    if tuple(item.device_identity for item in observation.routers) != tuple(
        item.device_identity for item in desired.routers
    ):
        raise ValueError("OSPF observation is detached from desired state")
    return _render_ospf_exact(observation, desired)


def build_ospf_triangle_candidate_snapshot(
    underlay_intent: RoutedUnderlayIntent,
    underlay_desired: RoutedUnderlayDesiredState,
    ospf_intent: OspfTriangleIntent,
    ospf_desired: OspfDesiredState,
) -> PreparedSnapshot:
    """Build the clean combined underlay+OSPF final-state candidate."""
    if underlay_desired != build_routed_underlay_desired_state(underlay_intent):
        raise ValueError("combined candidate underlay is detached from intent")
    if ospf_desired != build_ospf_desired_state(ospf_intent):
        raise ValueError("combined candidate OSPF state is detached from intent")
    if underlay_intent.source_allocation != ospf_intent.source_underlay:
        raise ValueError("combined candidate source authority is inconsistent")
    catalog = tuple(
        (item.logical_name.value, item.automation_profile_id)
        for item in PROFILED_POPULATION_CATALOG
    )
    if tuple(name for name, _profile in catalog) != EXPECTED_PROFILED_NAMES:
        raise ValueError("combined candidate population is not exact")
    underlay_by_device: dict[str, list[Any]] = {}
    for state in underlay_desired.interfaces:
        underlay_by_device.setdefault(state.device_identity, []).append(state)
    ospf_by_device = {item.device_identity: item for item in ospf_desired.routers}
    identity_by_name = {
        "core-02": "netbox:dcim.device:1",
        "edge-junos-01": "netbox:dcim.device:2",
        "transit-ios-01": "netbox:dcim.device:8",
    }
    files: list[tuple[str, bytes]] = []
    for name, profile in catalog:
        identity = identity_by_name.get(name)
        routed = tuple(underlay_by_device.get(identity or "", ()))
        ospf = ospf_by_device.get(identity or "")
        lines = [f"hostname {name}"]
        if profile in {
            AutomationProfileID.CAT8000V_IOSXE,
            AutomationProfileID.IOSV_159_3_M12,
        }:
            if ospf is None:
                raise ValueError("combined Cisco candidate lacks OSPF state")
            for state in routed:
                address = state.ipv4_addresses[0]
                lines.extend(
                    (
                        f"interface {state.interface.name}",
                        f" ip address {address.ip} {address.network.netmask}",
                        " ip ospf network point-to-point",
                        f" ip ospf {CISCO_OSPF_PROCESS_ID} area 0",
                        " no shutdown",
                    )
                )
            lines.extend(
                (
                    f"router ospf {CISCO_OSPF_PROCESS_ID}",
                    f" router-id {ospf.router_id}",
                    " passive-interface default",
                    *(
                        f" no passive-interface {item.interface.name}"
                        for item in ospf.interfaces
                    ),
                )
            )
        elif profile is AutomationProfileID.VJUNOS_ROUTER:
            if ospf is None:
                raise ValueError("combined Junos candidate lacks OSPF state")
            lines = [f"set system host-name {name}"]
            lines.extend(
                "set interfaces "
                f"{state.interface.name} unit 0 family inet address "
                f"{state.ipv4_addresses[0]}"
                for state in routed
            )
            lines.append(f"set routing-options router-id {ospf.router_id}")
            lines.extend(
                "set protocols ospf area 0.0.0.0 interface "
                f"{item.interface.name}.0 interface-type p2p"
                for item in ospf.interfaces
            )
        elif profile is AutomationProfileID.IOSVL2_2020:
            if routed or ospf is not None:
                raise ValueError("access switch cannot join OSPF candidate")
            lines.extend(
                (
                    "version 15.2",
                    "interface GigabitEthernet0/0",
                    " no switchport",
                    " no shutdown",
                )
            )
        else:
            raise ValueError("combined candidate profile is unsupported")
        files.append((f"{name}.cfg", ("\n".join(lines) + "\n").encode()))
    return prepare_snapshot_from_bytes(tuple(sorted(files, key=lambda item: item[0])))


class BatfishOspfProcess(BaseModel):
    """Normalized final-state OSPF process fact."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    node: str
    router_id: ipaddress.IPv4Address


class BatfishOspfInterface(BaseModel):
    """Normalized final-state OSPF interface fact."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    node: str
    interface: str
    area: str
    network_type: str
    passive: bool


class BatfishOspfEdge(BaseModel):
    """One normalized unordered OSPF adjacency pair."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    nodes: tuple[str, str]

    @model_validator(mode="after")
    def ordered_distinct_nodes(self) -> BatfishOspfEdge:
        if self.nodes != tuple(sorted(self.nodes)) or self.nodes[0] == self.nodes[1]:
            raise ValueError("OSPF edge must be one ordered distinct node pair")
        return self


class BatfishOspfRoute(BaseModel):
    """One required remote OSPF route fact."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    node: str
    prefix: ipaddress.IPv4Network
    protocol: str


class OspfTriangleBatfishObservation(BaseModel):
    """Bounded Batfish facts for the combined underlay and OSPF candidate."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    underlay: RoutedUnderlayBatfishObservation
    processes: tuple[BatfishOspfProcess, ...]
    interfaces: tuple[BatfishOspfInterface, ...]
    edges: tuple[BatfishOspfEdge, ...]
    routes: tuple[BatfishOspfRoute, ...]
    remote_flows: tuple[RoutedUnderlayFlow, ...]


class OspfTriangleAssuranceEvidence(BaseModel):
    """Secret-free combined candidate assurance result."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    generated_at: datetime
    routed_underlay_digest: Sha256Digest
    ospf_digest: Sha256Digest
    candidate_snapshot_digest: Sha256Digest
    pybatfish_version: str
    batfish_version: str
    candidate_nodes: tuple[str, ...]
    ospf_router_count: int = Field(ge=0)
    ospf_adjacency_count: int = Field(ge=0)
    invariants: tuple[InvariantResult, ...]
    outcome: AssuranceOutcome

    @model_validator(mode="after")
    def outcome_matches_invariants(self) -> OspfTriangleAssuranceEvidence:
        expected = (
            AssuranceOutcome.PASSED
            if self.invariants and all(item.passed for item in self.invariants)
            else AssuranceOutcome.FAILED
        )
        if self.outcome is not expected:
            raise ValueError("OSPF assurance outcome is inconsistent")
        return self


class OspfTriangleAssuranceProvider(Protocol):
    def analyze(self, candidate: Path) -> OspfTriangleBatfishObservation: ...


def _column(frame: object, name: str) -> str:
    for column in frame.columns:
        if str(column).casefold() == name.casefold():
            return str(column)
    raise AssuranceProviderError("Batfish OSPF answer schema is unsupported")


def _compound_interface(value: object) -> tuple[str, str]:
    match = re.fullmatch(r"([^\[\]]+)\[([^\[\]]+)\]", str(value))
    if match is None:
        raise AssuranceProviderError("Batfish OSPF interface identity is unsupported")
    node, interface = match.groups()
    if node == "edge-junos-01" and interface.endswith(".0"):
        interface = interface.removesuffix(".0")
    return node, interface


class BatfishOspfTriangleAdapter:
    """Pinned Batfish analyzer for the exact combined final-state candidate."""

    def __init__(self, host: str | None = None) -> None:
        self.host = host or os.environ.get("NCDP_BATFISH_HOST", "127.0.0.1")

    def analyze(self, candidate: Path) -> OspfTriangleBatfishObservation:
        try:
            from pybatfish.client.session import Session

            pybatfish_version = version("pybatfish")
        except (ImportError, PackageNotFoundError):
            raise AssuranceProviderError(
                "Batfish provider dependency unavailable"
            ) from None
        with prepare_snapshot(candidate) as frozen:
            snapshot = "ncdp-b4-ospf-triangle-" + uuid.uuid4().hex
            try:
                session = Session(host=self.host, port=9996)
                session.init_snapshot(str(frozen.root), name=snapshot, overwrite=False)
                parse_rows = (
                    session.q.fileParseStatus().answer(snapshot=snapshot).frame()
                )
                parse = ParseSummary(
                    files=tuple(
                        sorted(
                            (
                                ParseFileResult(
                                    relative_path=PurePosixPath(
                                        str(row["File_Name"]).replace("\\", "/")
                                    )
                                    .as_posix()
                                    .removeprefix("configs/"),
                                    status=str(row["Status"]),
                                )
                                for _, row in parse_rows.iterrows()
                            ),
                            key=lambda item: item.relative_path,
                        )
                    ),
                    nodes=tuple(
                        sorted(
                            str(node)
                            for node in session.q.nodeProperties()
                            .answer(snapshot=snapshot)
                            .frame()["Node"]
                        )
                    ),
                    initialization_issue_count=len(
                        session.q.initIssues().answer(snapshot=snapshot).frame()
                    ),
                )
                prefix_rows = (
                    session.q.interfaceProperties(properties="All_Prefixes")
                    .answer(snapshot=snapshot)
                    .frame()
                    .reset_index()
                )
                prefixes: list[BatfishInterfacePrefix] = []
                for _, row in prefix_rows.iterrows():
                    node, interface = _compound_interface(
                        row[_column(prefix_rows, "Interface")]
                    )
                    prefixes.extend(
                        BatfishInterfacePrefix(
                            node=node, interface=interface, prefix=value
                        )
                        for value in _PREFIX_PATTERN.findall(
                            str(row[_column(prefix_rows, "All_Prefixes")])
                        )
                    )
                direct_specs = (
                    ("core-02", "10.60.0.1", "10.60.0.2"),
                    ("core-02", "10.60.0.5", "10.60.0.6"),
                    ("edge-junos-01", "10.60.0.9", "10.60.0.10"),
                )
                remote_specs = (
                    ("core-02", "10.60.0.1", "10.60.0.10"),
                    ("edge-junos-01", "10.60.0.2", "10.60.0.6"),
                    ("transit-ios-01", "10.60.0.6", "10.60.0.2"),
                )

                def flows(
                    specs: tuple[tuple[str, str, str], ...],
                ) -> tuple[RoutedUnderlayFlow, ...]:
                    result = []
                    for source_node, source_ip, destination_ip in specs:
                        rows = (
                            session.q.reachability(
                                pathConstraints={"startLocation": source_node},
                                headers={"srcIps": source_ip, "dstIps": destination_ip},
                            )
                            .answer(snapshot=snapshot)
                            .frame()
                        )
                        result.append(
                            RoutedUnderlayFlow(
                                source_node=source_node,
                                source_ip=source_ip,
                                destination_ip=destination_ip,
                                reachable=len(rows) > 0,
                            )
                        )
                    return tuple(result)

                process_rows = (
                    session.q.ospfProcessConfiguration()
                    .answer(snapshot=snapshot)
                    .frame()
                )
                processes = tuple(
                    sorted(
                        (
                            BatfishOspfProcess(
                                node=str(row[_column(process_rows, "Node")]),
                                router_id=str(row[_column(process_rows, "Router_ID")]),
                            )
                            for _, row in process_rows.iterrows()
                        ),
                        key=lambda item: item.node,
                    )
                )
                interface_rows = (
                    session.q.ospfInterfaceConfiguration()
                    .answer(snapshot=snapshot)
                    .frame()
                )
                interfaces = []
                for _, row in interface_rows.iterrows():
                    node, interface = _compound_interface(
                        row[_column(interface_rows, "Interface")]
                    )
                    interfaces.append(
                        BatfishOspfInterface(
                            node=node,
                            interface=interface,
                            area="0.0.0.0"
                            if str(row[_column(interface_rows, "OSPF_Area_Name")])
                            == "0"
                            else str(row[_column(interface_rows, "OSPF_Area_Name")]),
                            network_type=str(
                                row[_column(interface_rows, "OSPF_Network_Type")]
                            )
                            .casefold()
                            .replace("_", "-"),
                            passive=bool(row[_column(interface_rows, "OSPF_Passive")]),
                        )
                    )
                edge_rows = session.q.ospfEdges().answer(snapshot=snapshot).frame()
                edge_pairs = {
                    tuple(
                        sorted(
                            (
                                _compound_interface(
                                    row[_column(edge_rows, "Interface")]
                                )[0],
                                _compound_interface(
                                    row[_column(edge_rows, "Remote_Interface")]
                                )[0],
                            )
                        )
                    )
                    for _, row in edge_rows.iterrows()
                }
                route_rows = session.q.routes().answer(snapshot=snapshot).frame()
                required_routes = {
                    ("core-02", "10.60.0.8/30"),
                    ("edge-junos-01", "10.60.0.4/30"),
                    ("transit-ios-01", "10.60.0.0/30"),
                }
                routes = tuple(
                    sorted(
                        (
                            BatfishOspfRoute(
                                node=str(row[_column(route_rows, "Node")]),
                                prefix=str(row[_column(route_rows, "Network")]),
                                protocol=str(
                                    row[_column(route_rows, "Protocol")]
                                ).casefold(),
                            )
                            for _, row in route_rows.iterrows()
                            if (
                                str(row[_column(route_rows, "Node")]),
                                str(row[_column(route_rows, "Network")]),
                            )
                            in required_routes
                        ),
                        key=lambda item: (item.node, str(item.prefix)),
                    )
                )
                return OspfTriangleBatfishObservation(
                    underlay=RoutedUnderlayBatfishObservation(
                        pybatfish_version=pybatfish_version,
                        batfish_version=str(session._get_bf_version()),
                        candidate_parse=parse,
                        interface_prefixes=tuple(
                            sorted(
                                prefixes, key=lambda item: (item.node, item.interface)
                            )
                        ),
                        flows=flows(direct_specs),
                        ospf_process_count=len(processes),
                    ),
                    processes=processes,
                    interfaces=tuple(
                        sorted(interfaces, key=lambda item: (item.node, item.interface))
                    ),
                    edges=tuple(
                        BatfishOspfEdge(nodes=pair) for pair in sorted(edge_pairs)
                    ),
                    routes=routes,
                    remote_flows=flows(remote_specs),
                )
            except AssuranceProviderError:
                raise
            except Exception:
                raise AssuranceProviderError("Batfish service unavailable") from None


def evaluate_ospf_triangle_invariants(
    underlay: RoutedUnderlayDesiredState,
    ospf: OspfDesiredState,
    observation: OspfTriangleBatfishObservation,
) -> tuple[InvariantResult, ...]:
    """Evaluate the 16 underlay/OSPF invariants without evidence identity."""
    expected_processes = {
        (router.logical_name, str(router.router_id)) for router in ospf.routers
    }
    expected_interfaces = {
        (
            router.logical_name,
            interface.interface.name,
            OSPF_AREA,
            "point-to-point",
            False,
        )
        for router in ospf.routers
        for interface in router.interfaces
    }
    expected_edges = {
        ("core-02", "edge-junos-01"),
        ("core-02", "transit-ios-01"),
        ("edge-junos-01", "transit-ios-01"),
    }
    expected_routes = {
        ("core-02", "10.60.0.8/30", "ospf"),
        ("edge-junos-01", "10.60.0.4/30", "ospf"),
        ("transit-ios-01", "10.60.0.0/30", "ospf"),
    }
    expected_remote_flows = {
        ("core-02", "10.60.0.1", "10.60.0.10"),
        ("edge-junos-01", "10.60.0.2", "10.60.0.6"),
        ("transit-ios-01", "10.60.0.6", "10.60.0.2"),
    }
    ospf_invariants = (
        InvariantResult(
            name="ospf_exact_routers",
            passed={(item.node, str(item.router_id)) for item in observation.processes}
            == expected_processes,
            detail="OSPF exists on exactly three routers with exact router IDs",
        ),
        InvariantResult(
            name="ospf_access_excluded",
            passed=all(item.node != "access-sw-01" for item in observation.processes),
            detail="access-sw-01 has no OSPF process",
        ),
        InvariantResult(
            name="ospf_exact_interfaces",
            passed={
                (item.node, item.interface, item.area, item.network_type, item.passive)
                for item in observation.interfaces
            }
            == expected_interfaces,
            detail="exact six area-0 point-to-point non-passive interfaces participate",
        ),
        InvariantResult(
            name="ospf_management_excluded",
            passed=all(
                item.interface not in {"GigabitEthernet1", "fxp0", "GigabitEthernet0/0"}
                for item in observation.interfaces
            ),
            detail="management interfaces do not participate in OSPF",
        ),
        InvariantResult(
            name="ospf_exact_adjacencies",
            passed={item.nodes for item in observation.edges} == expected_edges,
            detail="exact three unordered OSPF adjacency pairs exist",
        ),
        InvariantResult(
            name="ospf_remote_routes",
            passed={
                (item.node, str(item.prefix), item.protocol)
                for item in observation.routes
            }
            == expected_routes,
            detail="each router learns its remote /30 through OSPF",
        ),
        InvariantResult(
            name="ospf_remote_reachability",
            passed={
                (item.source_node, str(item.source_ip), str(item.destination_ip))
                for item in observation.remote_flows
            }
            == expected_remote_flows
            and all(item.reachable for item in observation.remote_flows),
            detail="representative remote-link reachability succeeds",
        ),
    )
    return (
        evaluate_routed_underlay_common_invariants(underlay, observation.underlay)
        + ospf_invariants
    )


def evaluate_ospf_triangle_assurance(
    underlay: RoutedUnderlayDesiredState,
    ospf: OspfDesiredState,
    candidate_snapshot_digest: str,
    observation: OspfTriangleBatfishObservation,
) -> OspfTriangleAssuranceEvidence:
    """Evaluate exact underlay and OSPF final-state evidence."""
    invariants = evaluate_ospf_triangle_invariants(underlay, ospf, observation)
    outcome = (
        AssuranceOutcome.PASSED
        if all(item.passed for item in invariants)
        else AssuranceOutcome.FAILED
    )
    return OspfTriangleAssuranceEvidence(
        generated_at=datetime.now(UTC),
        routed_underlay_digest=underlay.digest,
        ospf_digest=ospf.digest,
        candidate_snapshot_digest=candidate_snapshot_digest,
        pybatfish_version=observation.underlay.pybatfish_version,
        batfish_version=observation.underlay.batfish_version,
        candidate_nodes=observation.underlay.candidate_parse.nodes,
        ospf_router_count=len(observation.processes),
        ospf_adjacency_count=len(observation.edges),
        invariants=invariants,
        outcome=outcome,
    )


def assure_ospf_triangle_candidate(
    underlay_intent: RoutedUnderlayIntent,
    underlay_desired: RoutedUnderlayDesiredState,
    ospf_intent: OspfTriangleIntent,
    ospf_desired: OspfDesiredState,
    provider: OspfTriangleAssuranceProvider | None = None,
) -> OspfTriangleAssuranceEvidence:
    """Analyze the deterministic combined final-state candidate."""
    with build_ospf_triangle_candidate_snapshot(
        underlay_intent, underlay_desired, ospf_intent, ospf_desired
    ) as candidate:
        observation = (provider or BatfishOspfTriangleAdapter()).analyze(candidate.root)
        return evaluate_ospf_triangle_assurance(
            underlay_desired, ospf_desired, candidate.manifest.digest, observation
        )


class OspfTriangleProposalEvidence(BaseModel):
    """Proposed O-to-D1 evidence; it carries no execution authority."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal["2"] = "2"
    source_underlay_allocation_digest: Sha256Digest
    source_routing_identity_digest: Sha256Digest
    intent: OspfTriangleIntent
    ownership_envelope: ManagedOwnershipEnvelope
    current_observation: OspfObservation
    current_managed_digest: Sha256Digest
    proposed_desired_state: OspfDesiredState
    rendered_targets: tuple[OspfRenderedTarget, OspfRenderedTarget, OspfRenderedTarget]
    combined_assurance: OspfTriangleAssuranceEvidence
    device_writes: Literal[0] = 0

    @model_validator(mode="after")
    def evidence_is_internally_bound(self) -> OspfTriangleProposalEvidence:
        exact_nodes = tuple(sorted(EXPECTED_PROFILED_NAMES))
        if (
            self.source_underlay_allocation_digest
            != ACCEPTED_REFERENCE_ALLOCATION_DIGEST
            or self.source_routing_identity_digest
            != ACCEPTED_ROUTING_IDENTITY_ALLOCATION_DIGEST
            or self.source_underlay_allocation_digest
            != reference_allocation_digest(self.intent.source_underlay)
            or self.source_routing_identity_digest
            != routing_identity_allocation_digest(self.intent.source_routing_identities)
            or self.ownership_envelope != build_ospf_ownership_envelope(self.intent)
            or self.proposed_desired_state != build_ospf_desired_state(self.intent)
            or self.current_managed_digest
            != self.current_observation.managed_state_digest()
            or not self.proposed_desired_state.verify_digest()
            or self.rendered_targets
            != _render_ospf_exact(self.current_observation, self.proposed_desired_state)
            or self.combined_assurance.ospf_digest != self.proposed_desired_state.digest
            or self.combined_assurance.routed_underlay_digest
            != ACCEPTED_ROUTED_UNDERLAY_D1_DIGEST
            or self.combined_assurance.candidate_nodes != exact_nodes
            or self.combined_assurance.ospf_router_count != 3
            or self.combined_assurance.ospf_adjacency_count != 3
            or self.combined_assurance.outcome is not AssuranceOutcome.PASSED
        ):
            raise ValueError("OSPF proposal evidence is inconsistent")
        return self


def build_ospf_proposal_evidence(
    intent: OspfTriangleIntent,
    observation: OspfObservation,
    desired: OspfDesiredState,
    assurance: OspfTriangleAssuranceEvidence,
) -> OspfTriangleProposalEvidence:
    """Bind exact source authority, O, D1, transition render, and assurance."""
    return OspfTriangleProposalEvidence(
        source_underlay_allocation_digest=reference_allocation_digest(
            intent.source_underlay
        ),
        source_routing_identity_digest=routing_identity_allocation_digest(
            intent.source_routing_identities
        ),
        intent=intent,
        ownership_envelope=build_ospf_ownership_envelope(intent),
        current_observation=observation,
        current_managed_digest=observation.managed_state_digest(),
        proposed_desired_state=desired,
        rendered_targets=render_ospf_changes(intent, observation, desired),
        combined_assurance=assurance,
    )
