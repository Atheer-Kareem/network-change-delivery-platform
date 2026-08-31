"""Read-only desired-state vertical for the exact Detour B routed underlay.

The vertical resolves factual NetBox allocation, observes only its six LIVE
interfaces, renders a proposed candidate, and evaluates that candidate offline.
It deliberately contains no execution or persistence surface.
"""

from __future__ import annotations

import ipaddress
import os
import re
import uuid
from datetime import UTC, datetime
from enum import StrEnum
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path, PurePosixPath
from typing import Literal, Protocol
from xml.etree import ElementTree

from pydantic import BaseModel, ConfigDict, Field, model_validator

from network_change_delivery.architecture_contracts import (
    AutomationProfileID,
    ManagedField,
    ManagedOwnershipEnvelope,
    ManagedScopeIdentity,
    ManagedScopeKind,
    ManagedVertical,
    NetBoxDeviceIdentity,
    NetBoxIPAddressIdentity,
    NetBoxPrefixIdentity,
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
from network_change_delivery.profile_inventory import (
    PROFILED_POPULATION_CATALOG,
    ProfiledInventoryDevice,
    ProfiledInventoryPopulation,
)
from network_change_delivery.profile_read_only_adapter import ProfileReadOnlyAdapter
from network_change_delivery.reference_data_plane import (
    ReferenceDataPlaneAllocation,
    RoutedLinkAllocation,
    RoutedLinkIdentity,
    reference_allocation_digest,
)
from network_change_delivery.secrets import DeviceCredentials

ACCEPTED_ROUTED_UNDERLAY_D1_DIGEST = (
    "sha256:d25f753ef711677ccdde67bfeb7005f19759800099734a79bca1616bb77baf6b"
)

EXPECTED_PROFILED_NAMES = (
    "core-02",
    "edge-junos-01",
    "transit-ios-01",
    "access-sw-01",
)
UNDERLAY_DEVICE_IDENTITIES = (
    "netbox:dcim.device:1",
    "netbox:dcim.device:2",
    "netbox:dcim.device:8",
)
MANAGEMENT_INTERFACE_IDENTITIES = frozenset(
    {
        "netbox:dcim.interface:1",
        "netbox:dcim.interface:5",
        "netbox:dcim.interface:13",
        "netbox:dcim.interface:17",
    }
)
MANAGEMENT_ADDRESSES = frozenset(
    {
        ipaddress.ip_address(value)
        for value in (
            "192.168.4.14",
            "192.168.4.20",
            "192.168.4.16",
            "192.168.4.17",
            "192.168.4.30",
            "192.168.4.40",
            "192.168.4.31",
            "192.168.4.32",
        )
    }
)


class RoutedUnderlayIntentEndpoint(BaseModel):
    """One desired routed endpoint copied from resolved NetBox authority."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    interface: StableInterfaceIdentity
    ip_address_identity: NetBoxIPAddressIdentity
    address: ipaddress.IPv4Interface
    admin_enabled: Literal[True] = True


class RoutedUnderlayLinkIntent(BaseModel):
    """One exact Git-owned link relationship over resolved NetBox facts."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    logical_link: RoutedLinkIdentity
    prefix_identity: NetBoxPrefixIdentity
    prefix: ipaddress.IPv4Network
    endpoints: tuple[RoutedUnderlayIntentEndpoint, RoutedUnderlayIntentEndpoint]

    @classmethod
    def from_allocation(cls, link: RoutedLinkAllocation) -> RoutedUnderlayLinkIntent:
        return cls(
            logical_link=link.logical_link,
            prefix_identity=link.prefix_identity,
            prefix=link.prefix,
            endpoints=tuple(
                RoutedUnderlayIntentEndpoint(
                    interface=endpoint.interface,
                    ip_address_identity=endpoint.ip_address_identity,
                    address=endpoint.address,
                )
                for endpoint in link.endpoints
            ),
        )


class RoutedUnderlayIntent(BaseModel):
    """Exact three-link intent derived from one accepted B3-5 resolution."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal["1"] = "1"
    source_allocation: ReferenceDataPlaneAllocation
    links: tuple[
        RoutedUnderlayLinkIntent,
        RoutedUnderlayLinkIntent,
        RoutedUnderlayLinkIntent,
    ]

    @classmethod
    def from_reference_allocation(
        cls, allocation: ReferenceDataPlaneAllocation
    ) -> RoutedUnderlayIntent:
        """Bind intent to exact resolved facts instead of duplicating IPAM."""
        return cls(
            source_allocation=allocation,
            links=tuple(  # type: ignore[arg-type]
                RoutedUnderlayLinkIntent.from_allocation(link)
                for link in allocation.routed_links
            ),
        )

    @model_validator(mode="after")
    def exact_source_and_scope(self) -> RoutedUnderlayIntent:
        expected = tuple(
            RoutedUnderlayLinkIntent.from_allocation(link)
            for link in self.source_allocation.routed_links
        )
        endpoints = tuple(
            endpoint for link in self.links for endpoint in link.endpoints
        )
        if self.links != expected:
            raise ValueError(
                "routed-underlay intent is detached from NetBox allocation"
            )
        if (
            tuple(link.logical_link for link in self.links) != tuple(RoutedLinkIdentity)
            or len(endpoints) != 6
            or len({item.interface.interface for item in endpoints}) != 6
            or len({item.ip_address_identity for item in endpoints}) != 6
            or tuple(dict.fromkeys(item.interface.device for item in endpoints))
            != UNDERLAY_DEVICE_IDENTITIES
            or any(
                item.interface.interface in MANAGEMENT_INTERFACE_IDENTITIES
                or item.address.ip in MANAGEMENT_ADDRESSES
                for item in endpoints
            )
        ):
            raise ValueError("routed-underlay intent scope is not exact")
        return self


class DesiredRoutedInterfaceState(BaseModel):
    """Normalized D1 for exactly one interface and managed fields only."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    device_identity: NetBoxDeviceIdentity
    interface: StableInterfaceIdentity
    ip_address_identity: NetBoxIPAddressIdentity
    routed_l3_present: Literal[True] = True
    ipv4_addresses: tuple[ipaddress.IPv4Interface, ...]
    admin_enabled: Literal[True] = True

    @model_validator(mode="after")
    def exact_stable_identity(self) -> DesiredRoutedInterfaceState:
        if (
            self.device_identity != self.interface.device
            or len(self.ipv4_addresses) != 1
            or self.interface.interface in MANAGEMENT_INTERFACE_IDENTITIES
            or self.ipv4_addresses[0].ip in MANAGEMENT_ADDRESSES
        ):
            raise ValueError("desired routed-interface state is not exact")
        return self


class RoutedUnderlayDesiredState(BaseModel):
    """Deterministic proposed D1; this is not an accepted D0 baseline."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal["1"] = "1"
    interfaces: tuple[
        DesiredRoutedInterfaceState,
        DesiredRoutedInterfaceState,
        DesiredRoutedInterfaceState,
        DesiredRoutedInterfaceState,
        DesiredRoutedInterfaceState,
        DesiredRoutedInterfaceState,
    ]
    digest: Sha256Digest

    @model_validator(mode="after")
    def exact_six_interfaces(self) -> RoutedUnderlayDesiredState:
        identities = tuple(item.interface.interface for item in self.interfaces)
        addresses = tuple(str(item.ipv4_addresses[0]) for item in self.interfaces)
        if (
            len(set(identities)) != 6
            or len(set(addresses)) != 6
            or tuple(dict.fromkeys(item.device_identity for item in self.interfaces))
            != UNDERLAY_DEVICE_IDENTITIES
        ):
            raise ValueError("desired routed-underlay population is not exact")
        return self

    def digest_input(self) -> bytes:
        return canonical_json_bytes(self.model_dump(mode="json", exclude={"digest"}))

    def calculated_digest(self) -> str:
        return sha256_identity(self.digest_input())

    def verify_digest(self) -> bool:
        return self.digest == self.calculated_digest()


def build_routed_underlay_desired_state(
    intent: RoutedUnderlayIntent,
) -> RoutedUnderlayDesiredState:
    """Normalize exact resolved intent into vendor-independent proposed D1."""
    interfaces = tuple(
        DesiredRoutedInterfaceState(
            device_identity=endpoint.interface.device,
            interface=endpoint.interface,
            ip_address_identity=endpoint.ip_address_identity,
            ipv4_addresses=(endpoint.address,),
        )
        for link in intent.links
        for endpoint in link.endpoints
    )
    unsigned = RoutedUnderlayDesiredState(
        interfaces=interfaces,  # type: ignore[arg-type]
        digest="sha256:" + "0" * 64,
    )
    return unsigned.model_copy(update={"digest": unsigned.calculated_digest()})


def build_routed_underlay_ownership_envelope(
    intent: RoutedUnderlayIntent,
) -> ManagedOwnershipEnvelope:
    """Own only L3 presence/address/admin state on the six data interfaces."""
    return ManagedOwnershipEnvelope(
        vertical=ManagedVertical.ROUTED_UNDERLAY,
        envelope_version=1,
        targets=UNDERLAY_DEVICE_IDENTITIES,
        scope=tuple(
            [
                ManagedScopeIdentity(
                    kind=ManagedScopeKind.PREFIX,
                    identity=link.prefix_identity,
                )
                for link in intent.links
            ]
            + [
                ManagedScopeIdentity(
                    kind=ManagedScopeKind.INTERFACE,
                    identity=endpoint.interface.interface,
                )
                for link in intent.links
                for endpoint in link.endpoints
            ]
        ),
        normalized_fields=(
            ManagedField.ROUTED_UNDERLAY_L3_PRESENCE,
            ManagedField.ROUTED_UNDERLAY_ADDRESS,
            ManagedField.ROUTED_UNDERLAY_ADMIN_ENABLED,
        ),
    )


class ObservedRoutedInterfaceState(BaseModel):
    """Current observed O for one interface inside the ownership envelope."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    device_identity: NetBoxDeviceIdentity
    interface: StableInterfaceIdentity
    exists: bool
    ipv4_addresses: tuple[ipaddress.IPv4Interface, ...]
    admin_enabled: bool | None
    operational_status: Literal["up", "down"] | None

    @model_validator(mode="after")
    def stable_identity_matches(self) -> ObservedRoutedInterfaceState:
        if (
            self.device_identity != self.interface.device
            or self.interface.interface in MANAGEMENT_INTERFACE_IDENTITIES
            or len(self.ipv4_addresses) != len(set(self.ipv4_addresses))
        ):
            raise ValueError("observed routed-interface identity is invalid")
        return self


class RoutedUnderlayObservation(BaseModel):
    """Fresh exact-six observed state O."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal["1"] = "1"
    observed_at: datetime
    interfaces: tuple[
        ObservedRoutedInterfaceState,
        ObservedRoutedInterfaceState,
        ObservedRoutedInterfaceState,
        ObservedRoutedInterfaceState,
        ObservedRoutedInterfaceState,
        ObservedRoutedInterfaceState,
    ]

    @model_validator(mode="after")
    def exact_observation_population(self) -> RoutedUnderlayObservation:
        identities = tuple(item.interface.interface for item in self.interfaces)
        if len(set(identities)) != 6:
            raise ValueError("routed-underlay observation is not exact-six")
        return self

    def managed_state_digest(self) -> str:
        """Bind only observed fields that can influence the managed change render."""
        managed = {
            "schema_version": self.schema_version,
            "interfaces": [
                state.model_dump(
                    mode="json",
                    exclude={"operational_status"},
                )
                for state in self.interfaces
            ],
        }
        return sha256_identity(canonical_json_bytes(managed))


class RoutedUnderlaySecretProvider(Protocol):
    """Only the ephemeral credential load surface needed by observation."""

    def load(self, device: ProfiledInventoryDevice) -> DeviceCredentials: ...


def _normalized_ipv4_addresses(
    values: tuple[str, ...],
) -> tuple[ipaddress.IPv4Interface, ...]:
    try:
        normalized = tuple(sorted({ipaddress.IPv4Interface(value) for value in values}))
    except ValueError:
        raise ValueError(
            "read-only interface observation contains invalid IPv4"
        ) from None
    return normalized


def collect_routed_underlay_observation(
    intent: RoutedUnderlayIntent,
    population: ProfiledInventoryPopulation,
    secret_provider: RoutedUnderlaySecretProvider,
    adapter: ProfileReadOnlyAdapter,
    *,
    observed_at: datetime | None = None,
) -> RoutedUnderlayObservation:
    """Collect O through exact LIVE targets; no target or adapter can write."""
    by_identity = {device.device_identity: device for device in population.devices}
    if (
        tuple(device.logical_name for device in population.devices)
        != EXPECTED_PROFILED_NAMES
    ):
        raise ValueError("profiled inventory population is not exact")
    observed: list[ObservedRoutedInterfaceState] = []
    for device_identity in UNDERLAY_DEVICE_IDENTITIES:
        device = by_identity.get(device_identity)
        if device is None:
            raise ValueError("routed-underlay target is absent from profiled inventory")
        credentials = secret_provider.load(device)
        target = device.live_read_only_target()
        endpoints = tuple(
            endpoint
            for link in intent.links
            for endpoint in link.endpoints
            if endpoint.interface.device == device_identity
        )
        for endpoint in endpoints:
            state = adapter.collect(target, credentials, endpoint.interface.name)
            if state.observed_hostname != device.expected_hostname:
                raise ValueError("read-only routed-underlay hostname mismatch")
            if state.interface != endpoint.interface.name:
                raise ValueError("read-only routed-underlay interface mismatch")
            observed.append(
                ObservedRoutedInterfaceState(
                    device_identity=device_identity,
                    interface=endpoint.interface,
                    exists=state.exists,
                    ipv4_addresses=_normalized_ipv4_addresses(state.ipv4_addresses),
                    admin_enabled=state.enabled,
                    operational_status=state.operational_status,
                )
            )
    return RoutedUnderlayObservation(
        observed_at=observed_at or datetime.now(UTC),
        interfaces=tuple(observed),  # type: ignore[arg-type]
    )


class RoutedUnderlayRenderFormat(StrEnum):
    IOS_CLI = "ios_cli"
    JUNOS_XML = "junos_xml"


class RoutedUnderlayRenderedTarget(BaseModel):
    """Pure O-to-D1 vendor change artifact; it carries no execution authority."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    device_identity: NetBoxDeviceIdentity
    logical_name: str
    automation_profile_id: AutomationProfileID
    source_managed_observation_digest: Sha256Digest
    proposed_desired_state_digest: Sha256Digest
    format: RoutedUnderlayRenderFormat
    content: str = Field(min_length=1)


def _junos_change_xml(
    changes: tuple[
        tuple[ObservedRoutedInterfaceState, DesiredRoutedInterfaceState], ...
    ],
) -> str:
    root = ElementTree.Element("configuration")
    interfaces = ElementTree.SubElement(root, "interfaces")
    for observed, desired in changes:
        interface = ElementTree.SubElement(interfaces, "interface")
        ElementTree.SubElement(interface, "name").text = desired.interface.name
        disable = ElementTree.SubElement(interface, "disable")
        disable.set("operation", "delete")
        unit = ElementTree.SubElement(interface, "unit")
        ElementTree.SubElement(unit, "name").text = "0"
        family = ElementTree.SubElement(unit, "family")
        inet = ElementTree.SubElement(family, "inet")
        removed = tuple(
            address
            for address in observed.ipv4_addresses
            if address not in desired.ipv4_addresses
        )
        added = tuple(
            address
            for address in desired.ipv4_addresses
            if address not in observed.ipv4_addresses
        )
        for value in removed:
            address = ElementTree.SubElement(inet, "address")
            address.set("operation", "delete")
            ElementTree.SubElement(address, "name").text = str(value)
        for value in added:
            address = ElementTree.SubElement(inet, "address")
            ElementTree.SubElement(address, "name").text = str(value)
    return ElementTree.tostring(root, encoding="unicode", short_empty_elements=True)


_RENDER_BINDINGS = (
    (
        "netbox:dcim.device:1",
        "core-02",
        AutomationProfileID.CAT8000V_IOSXE,
    ),
    (
        "netbox:dcim.device:2",
        "edge-junos-01",
        AutomationProfileID.VJUNOS_ROUTER,
    ),
    (
        "netbox:dcim.device:8",
        "transit-ios-01",
        AutomationProfileID.IOSV_159_3_M12,
    ),
)
_PROFILED_BINDINGS = (
    *_RENDER_BINDINGS,
    (
        "netbox:dcim.device:9",
        "access-sw-01",
        AutomationProfileID.IOSVL2_2020,
    ),
)


def _observation_by_interface(
    observation: RoutedUnderlayObservation,
    desired: RoutedUnderlayDesiredState,
) -> dict[str, ObservedRoutedInterfaceState]:
    observed = {item.interface.interface: item for item in observation.interfaces}
    expected = {item.interface.interface for item in desired.interfaces}
    if set(observed) != expected:
        raise ValueError("routed-underlay observation is not exact for desired state")
    for state in desired.interfaces:
        current = observed[state.interface.interface]
        if (
            current.device_identity != state.device_identity
            or current.interface != state.interface
        ):
            raise ValueError("routed-underlay observation identity is inconsistent")
        if any(
            address.ip in MANAGEMENT_ADDRESSES for address in current.ipv4_addresses
        ):
            raise ValueError(
                "management address cannot enter routed-underlay rendering"
            )
    return observed


def _render_change_exact(
    observation: RoutedUnderlayObservation,
    desired: RoutedUnderlayDesiredState,
) -> tuple[RoutedUnderlayRenderedTarget, ...]:
    if not desired.verify_digest():
        raise ValueError("routed-underlay desired-state digest is invalid")
    observed = _observation_by_interface(observation, desired)
    rendered: list[RoutedUnderlayRenderedTarget] = []
    by_identity = {state.device_identity: [] for state in desired.interfaces}
    for state in desired.interfaces:
        by_identity[state.device_identity].append(state)
    for device_identity, logical_name, profile_id in _RENDER_BINDINGS:
        states = tuple(by_identity.get(device_identity, ()))
        if profile_id in {
            AutomationProfileID.CAT8000V_IOSXE,
            AutomationProfileID.IOSV_159_3_M12,
        }:
            blocks: list[str] = []
            for state in states:
                current = observed[state.interface.interface]
                if len(current.ipv4_addresses) > 1:
                    raise ValueError(
                        "multiple observed Cisco IPv4 addresses are unsupported"
                    )
                blocks.append(f"interface {state.interface.name}")
                blocks.extend(
                    f" no ip address {address.ip} {address.network.netmask}"
                    for address in current.ipv4_addresses
                    if address not in state.ipv4_addresses
                )
                blocks.extend(
                    f" ip address {address.ip} {address.network.netmask}"
                    for address in state.ipv4_addresses
                    if address not in current.ipv4_addresses
                )
                blocks.append(" no shutdown")
            format_ = RoutedUnderlayRenderFormat.IOS_CLI
            content = "\n".join(blocks) + "\n"
        elif profile_id is AutomationProfileID.VJUNOS_ROUTER:
            format_ = RoutedUnderlayRenderFormat.JUNOS_XML
            content = _junos_change_xml(
                tuple((observed[state.interface.interface], state) for state in states)
            )
        else:
            raise ValueError("routed-underlay renderer profile is unsupported")
        rendered.append(
            RoutedUnderlayRenderedTarget(
                device_identity=device_identity,
                logical_name=logical_name,
                automation_profile_id=profile_id,
                source_managed_observation_digest=observation.managed_state_digest(),
                proposed_desired_state_digest=desired.digest,
                format=format_,
                content=content,
            )
        )
    return tuple(rendered)


def render_routed_underlay(
    intent: RoutedUnderlayIntent,
    observation: RoutedUnderlayObservation,
    desired: RoutedUnderlayDesiredState,
    population: ProfiledInventoryPopulation,
) -> tuple[RoutedUnderlayRenderedTarget, ...]:
    """Render exact envelope-scoped IOS XE, IOS, and Junos O-to-D1 changes."""
    if desired != build_routed_underlay_desired_state(intent):
        raise ValueError("routed-underlay desired state is detached from intent")
    facts = tuple(
        (
            device.device_identity,
            device.logical_name,
            device.automation_profile_id,
        )
        for device in population.devices
    )
    if facts != _PROFILED_BINDINGS:
        raise ValueError("routed-underlay rendered population is not exact")
    return _render_change_exact(observation, desired)


def _render_final_state_ios(
    states: tuple[DesiredRoutedInterfaceState, ...],
) -> str:
    blocks: list[str] = []
    for state in states:
        address = state.ipv4_addresses[0]
        blocks.extend(
            (
                f"interface {state.interface.name}",
                f" ip address {address.ip} {address.network.netmask}",
                " no shutdown",
            )
        )
    return "\n".join(blocks) + "\n"


def build_routed_underlay_candidate_snapshot(
    intent: RoutedUnderlayIntent,
    desired: RoutedUnderlayDesiredState,
) -> PreparedSnapshot:
    """Build a synthetic exact-four final-state candidate from normalized D1."""
    if desired != build_routed_underlay_desired_state(intent):
        raise ValueError("routed-underlay desired state is detached from intent")
    candidate_catalog = tuple(
        (member.logical_name.value, member.automation_profile_id)
        for member in PROFILED_POPULATION_CATALOG
    )
    if tuple(name for name, _profile in candidate_catalog) != EXPECTED_PROFILED_NAMES:
        raise ValueError("routed-underlay candidate population is not exact")
    by_identity = {state.device_identity: [] for state in desired.interfaces}
    for state in desired.interfaces:
        by_identity[state.device_identity].append(state)
    identity_by_name = {
        "core-02": "netbox:dcim.device:1",
        "edge-junos-01": "netbox:dcim.device:2",
        "transit-ios-01": "netbox:dcim.device:8",
    }
    files: list[tuple[str, bytes]] = []
    for name, profile_id in candidate_catalog:
        states = tuple(by_identity.get(identity_by_name.get(name, ""), ()))
        if profile_id in {
            AutomationProfileID.CAT8000V_IOSXE,
            AutomationProfileID.IOSV_159_3_M12,
        }:
            content = f"hostname {name}\n{_render_final_state_ios(states)}"
        elif profile_id is AutomationProfileID.VJUNOS_ROUTER:
            lines = [f"set system host-name {name}"]
            lines.extend(
                "set interfaces "
                f"{state.interface.name} unit 0 family inet address "
                f"{state.ipv4_addresses[0]}"
                for state in states
            )
            content = "\n".join(lines) + "\n"
        elif profile_id is AutomationProfileID.IOSVL2_2020:
            if states:
                raise ValueError("access switch cannot join routed underlay")
            content = (
                f"version 15.2\nhostname {name}\n"
                "interface GigabitEthernet0/0\n no switchport\n no shutdown\n"
            )
        else:
            raise ValueError("routed-underlay candidate profile is unsupported")
        files.append((f"{name}.cfg", content.encode()))
    return prepare_snapshot_from_bytes(tuple(sorted(files, key=lambda item: item[0])))


class RoutedUnderlayFlow(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    source_node: str
    source_ip: ipaddress.IPv4Address
    destination_ip: ipaddress.IPv4Address
    reachable: bool


class BatfishInterfacePrefix(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    node: str
    interface: str
    prefix: ipaddress.IPv4Interface


class RoutedUnderlayBatfishObservation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    pybatfish_version: str
    batfish_version: str
    candidate_parse: ParseSummary
    interface_prefixes: tuple[BatfishInterfacePrefix, ...]
    flows: tuple[RoutedUnderlayFlow, ...]
    ospf_process_count: int = Field(ge=0)


class RoutedUnderlayAssuranceEvidence(BaseModel):
    """Secret-free candidate-only Batfish evidence for proposed D1."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    generated_at: datetime
    subject_digest: Sha256Digest
    candidate_snapshot_digest: Sha256Digest
    pybatfish_version: str
    batfish_version: str
    candidate_parse: ParseSummary
    interface_prefixes: tuple[BatfishInterfacePrefix, ...]
    flows: tuple[RoutedUnderlayFlow, ...]
    ospf_process_count: int = Field(ge=0)
    invariants: tuple[InvariantResult, ...]
    outcome: AssuranceOutcome

    @model_validator(mode="after")
    def outcome_matches_invariants(self) -> RoutedUnderlayAssuranceEvidence:
        passed = bool(self.invariants) and all(item.passed for item in self.invariants)
        expected = AssuranceOutcome.PASSED if passed else AssuranceOutcome.FAILED
        if self.outcome is not expected:
            raise ValueError("routed-underlay assurance outcome is inconsistent")
        return self


class RoutedUnderlayAssuranceProvider(Protocol):
    def analyze(self, candidate: Path) -> RoutedUnderlayBatfishObservation: ...


_PREFIX_PATTERN = re.compile(r"(?<![0-9.])(?:[0-9]{1,3}\.){3}[0-9]{1,3}/[0-9]{1,2}")


def _frame_column(frame: object, name: str) -> str:
    columns = tuple(str(column) for column in frame.columns)
    for column in columns:
        if column.casefold() == name.casefold():
            return column
    raise AssuranceProviderError("Batfish answer schema is unsupported")


def _optional_frame_column(frame: object, name: str) -> str | None:
    try:
        return _frame_column(frame, name)
    except AssuranceProviderError:
        return None


def _batfish_interface_identity(
    row: object,
    *,
    node_column: str | None,
    interface_column: str,
) -> tuple[str, str]:
    """Normalize Batfish's Node/Interface columns or compound Interface value."""
    interface_value = str(row[interface_column])
    if node_column is not None:
        node, interface = str(row[node_column]), interface_value
    else:
        match = re.fullmatch(r"([^\[\]]+)\[([^\[\]]+)\]", interface_value)
        if match is None:
            raise AssuranceProviderError("Batfish interface identity is unsupported")
        node, interface = match.groups()
    if node == "edge-junos-01" and interface.endswith(".0"):
        interface = interface.removesuffix(".0")
    return node, interface


class BatfishRoutedUnderlayAdapter:
    """Pinned Batfish read-only candidate analyzer for the routed underlay."""

    def __init__(self, host: str | None = None) -> None:
        self.host = host or os.environ.get("NCDP_BATFISH_HOST", "127.0.0.1")

    def analyze(self, candidate: Path) -> RoutedUnderlayBatfishObservation:
        try:
            from pybatfish.client.session import Session

            pybatfish_version = version("pybatfish")
        except (ImportError, PackageNotFoundError):
            raise AssuranceProviderError(
                "Batfish provider dependency unavailable"
            ) from None
        with prepare_snapshot(candidate) as frozen:
            snapshot = "ncdp-b4-routed-underlay-" + uuid.uuid4().hex
            try:
                session = Session(host=self.host, port=9996)
                session.init_snapshot(str(frozen.root), name=snapshot, overwrite=False)
                parse_rows = (
                    session.q.fileParseStatus().answer(snapshot=snapshot).frame()
                )
                parse_files: list[ParseFileResult] = []
                for _, row in parse_rows.iterrows():
                    file_name = PurePosixPath(
                        str(row["File_Name"]).replace("\\", "/")
                    ).as_posix()
                    parse_files.append(
                        ParseFileResult(
                            relative_path=file_name.removeprefix("configs/"),
                            status=str(row["Status"]),
                        )
                    )
                nodes = tuple(
                    sorted(
                        str(node)
                        for node in session.q.nodeProperties()
                        .answer(snapshot=snapshot)
                        .frame()["Node"]
                    )
                )
                issues = len(session.q.initIssues().answer(snapshot=snapshot).frame())
                parse = ParseSummary(
                    files=tuple(
                        sorted(parse_files, key=lambda item: item.relative_path)
                    ),
                    nodes=nodes,
                    initialization_issue_count=issues,
                )
                interface_rows = (
                    session.q.interfaceProperties(properties="All_Prefixes")
                    .answer(snapshot=snapshot)
                    .frame()
                    .reset_index()
                )
                node_column = _optional_frame_column(interface_rows, "Node")
                interface_column = _frame_column(interface_rows, "Interface")
                prefix_column = _frame_column(interface_rows, "All_Prefixes")
                prefixes: list[BatfishInterfacePrefix] = []
                for _, row in interface_rows.iterrows():
                    node, interface = _batfish_interface_identity(
                        row,
                        node_column=node_column,
                        interface_column=interface_column,
                    )
                    prefixes.extend(
                        BatfishInterfacePrefix(
                            node=node,
                            interface=interface,
                            prefix=value,
                        )
                        for value in _PREFIX_PATTERN.findall(str(row[prefix_column]))
                    )
                flow_specs = (
                    ("core-02", "10.60.0.1", "10.60.0.2"),
                    ("core-02", "10.60.0.5", "10.60.0.6"),
                    ("edge-junos-01", "10.60.0.9", "10.60.0.10"),
                )
                flows: list[RoutedUnderlayFlow] = []
                for source_node, source_ip, destination_ip in flow_specs:
                    rows = (
                        session.q.reachability(
                            pathConstraints={"startLocation": source_node},
                            headers={"srcIps": source_ip, "dstIps": destination_ip},
                        )
                        .answer(snapshot=snapshot)
                        .frame()
                    )
                    flows.append(
                        RoutedUnderlayFlow(
                            source_node=source_node,
                            source_ip=source_ip,
                            destination_ip=destination_ip,
                            reachable=len(rows) > 0,
                        )
                    )
                ospf_process_count = len(
                    session.q.ospfProcessConfiguration()
                    .answer(snapshot=snapshot)
                    .frame()
                )
                return RoutedUnderlayBatfishObservation(
                    pybatfish_version=pybatfish_version,
                    batfish_version=str(session._get_bf_version()),
                    candidate_parse=parse,
                    interface_prefixes=tuple(
                        sorted(prefixes, key=lambda item: (item.node, item.interface))
                    ),
                    flows=tuple(flows),
                    ospf_process_count=ospf_process_count,
                )
            except AssuranceProviderError:
                raise
            except Exception:
                raise AssuranceProviderError("Batfish service unavailable") from None


def evaluate_routed_underlay_assurance(
    desired: RoutedUnderlayDesiredState,
    candidate_snapshot_digest: str,
    observation: RoutedUnderlayBatfishObservation,
) -> RoutedUnderlayAssuranceEvidence:
    """Evaluate the standalone B4-1 candidate including OSPF isolation."""
    common = evaluate_routed_underlay_common_invariants(desired, observation)
    invariants = (
        *common,
        InvariantResult(
            name="ospf_absent",
            passed=observation.ospf_process_count == 0,
            detail="candidate contains no OSPF process",
        ),
    )
    outcome = (
        AssuranceOutcome.PASSED
        if all(item.passed for item in invariants)
        else AssuranceOutcome.FAILED
    )
    return RoutedUnderlayAssuranceEvidence(
        generated_at=datetime.now(UTC),
        subject_digest=desired.digest,
        candidate_snapshot_digest=candidate_snapshot_digest,
        pybatfish_version=observation.pybatfish_version,
        batfish_version=observation.batfish_version,
        candidate_parse=observation.candidate_parse,
        interface_prefixes=observation.interface_prefixes,
        flows=observation.flows,
        ospf_process_count=observation.ospf_process_count,
        invariants=invariants,
        outcome=outcome,
    )


def evaluate_routed_underlay_common_invariants(
    desired: RoutedUnderlayDesiredState,
    observation: RoutedUnderlayBatfishObservation,
) -> tuple[InvariantResult, ...]:
    """Evaluate the nine underlay invariants shared by composed candidates."""
    expected_nodes = tuple(sorted(EXPECTED_PROFILED_NAMES))
    expected_files = {f"{name}.cfg" for name in EXPECTED_PROFILED_NAMES}
    parse_status = observation.candidate_parse.parse_status
    expected_prefixes = {
        (
            {
                "netbox:dcim.device:1": "core-02",
                "netbox:dcim.device:2": "edge-junos-01",
                "netbox:dcim.device:8": "transit-ios-01",
            }[state.device_identity],
            state.interface.name,
            str(state.ipv4_addresses[0]),
        )
        for state in desired.interfaces
    }
    observed_prefixes = {
        (item.node, item.interface, str(item.prefix))
        for item in observation.interface_prefixes
    }
    link_participants = {
        str(state.ipv4_addresses[0].network): 0 for state in desired.interfaces
    }
    for state in desired.interfaces:
        link_participants[str(state.ipv4_addresses[0].network)] += 1
    flow_identities = {
        (flow.source_node, str(flow.source_ip), str(flow.destination_ip))
        for flow in observation.flows
    }
    expected_flows = {
        ("core-02", "10.60.0.1", "10.60.0.2"),
        ("core-02", "10.60.0.5", "10.60.0.6"),
        ("edge-junos-01", "10.60.0.9", "10.60.0.10"),
    }
    return (
        InvariantResult(
            name="candidate_exact_parse_files",
            passed=set(parse_status) == expected_files,
            detail="parse results cover exactly four candidate files",
        ),
        InvariantResult(
            name="candidate_parse_status",
            passed=set(parse_status) == expected_files
            and all(status == "PASSED" for status in parse_status.values()),
            detail="all four candidate configurations parse",
        ),
        InvariantResult(
            name="candidate_exact_nodes",
            passed=observation.candidate_parse.nodes == expected_nodes,
            detail="candidate recognizes the exact four profiled nodes",
        ),
        InvariantResult(
            name="candidate_initialization_issues",
            passed=observation.candidate_parse.initialization_issue_count == 0,
            detail="candidate initialization issue count is zero",
        ),
        InvariantResult(
            name="exact_routed_interface_prefixes",
            passed=observed_prefixes == expected_prefixes,
            detail="Batfish reports exactly the six intended routed interface prefixes",
        ),
        InvariantResult(
            name="exact_two_participants_per_link",
            passed=link_participants
            == {"10.60.0.0/30": 2, "10.60.0.4/30": 2, "10.60.0.8/30": 2},
            detail="each routed /30 has exactly its two intended participants",
        ),
        InvariantResult(
            name="access_switch_excluded",
            passed=not any(
                item.node == "access-sw-01" for item in observation.interface_prefixes
            ),
            detail="access-sw-01 has no routed-underlay participation",
        ),
        InvariantResult(
            name="management_addresses_excluded",
            passed=not any(
                item.prefix.ip in MANAGEMENT_ADDRESSES
                for item in observation.interface_prefixes
            ),
            detail="no management address enters the candidate data-plane envelope",
        ),
        InvariantResult(
            name="exact_direct_neighbor_flows",
            passed=flow_identities == expected_flows
            and all(flow.reachable for flow in observation.flows),
            detail="all three direct-neighbor reachability checks pass",
        ),
    )


def assure_routed_underlay_candidate(
    intent: RoutedUnderlayIntent,
    desired: RoutedUnderlayDesiredState,
    provider: RoutedUnderlayAssuranceProvider | None = None,
) -> RoutedUnderlayAssuranceEvidence:
    """Analyze one frozen candidate and bind the result to the proposed D1 digest."""
    with build_routed_underlay_candidate_snapshot(intent, desired) as candidate:
        observation = (provider or BatfishRoutedUnderlayAdapter()).analyze(
            candidate.root
        )
        return evaluate_routed_underlay_assurance(
            desired, candidate.manifest.digest, observation
        )


class RoutedUnderlayDelta(BaseModel):
    """Managed-envelope delta from current O to proposed D1."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    interface: StableInterfaceIdentity
    observed_addresses: tuple[ipaddress.IPv4Interface, ...]
    desired_addresses: tuple[ipaddress.IPv4Interface, ...]
    observed_admin_enabled: bool | None
    desired_admin_enabled: Literal[True] = True
    addresses_match: bool
    admin_matches: bool


def routed_underlay_delta(
    observation: RoutedUnderlayObservation,
    desired: RoutedUnderlayDesiredState,
) -> tuple[RoutedUnderlayDelta, ...]:
    """Compare only owned fields; operational status is evidence, not desired state."""
    observed = {item.interface.interface: item for item in observation.interfaces}
    deltas: list[RoutedUnderlayDelta] = []
    for state in desired.interfaces:
        current = observed.get(state.interface.interface)
        if current is None:
            raise ValueError("routed-underlay observation does not cover desired state")
        deltas.append(
            RoutedUnderlayDelta(
                interface=state.interface,
                observed_addresses=current.ipv4_addresses,
                desired_addresses=state.ipv4_addresses,
                observed_admin_enabled=current.admin_enabled,
                addresses_match=current.exists
                and current.ipv4_addresses == state.ipv4_addresses,
                admin_matches=current.exists
                and current.admin_enabled is state.admin_enabled,
            )
        )
    return tuple(deltas)


class RoutedUnderlayProposalEvidence(BaseModel):
    """Secret-free B4-1 proposal evidence; it grants no write authority."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal["1"] = "1"
    generated_at: datetime
    intent: RoutedUnderlayIntent
    ownership_envelope: ManagedOwnershipEnvelope
    current_observation: RoutedUnderlayObservation
    proposed_desired_state: RoutedUnderlayDesiredState
    delta: tuple[RoutedUnderlayDelta, ...]
    rendered_targets: tuple[RoutedUnderlayRenderedTarget, ...]
    batfish: RoutedUnderlayAssuranceEvidence

    @model_validator(mode="after")
    def exact_proposal_binding(self) -> RoutedUnderlayProposalEvidence:
        if (
            self.ownership_envelope
            != build_routed_underlay_ownership_envelope(self.intent)
            or self.proposed_desired_state
            != build_routed_underlay_desired_state(self.intent)
            or self.delta
            != routed_underlay_delta(
                self.current_observation, self.proposed_desired_state
            )
            or self.rendered_targets
            != _render_change_exact(
                self.current_observation, self.proposed_desired_state
            )
            or self.batfish.subject_digest != self.proposed_desired_state.digest
            or self.batfish.outcome is not AssuranceOutcome.PASSED
        ):
            raise ValueError("routed-underlay proposal evidence is inconsistent")
        return self


def source_allocation_digest(allocation: ReferenceDataPlaneAllocation) -> str:
    """Return stable evidence identity for one frozen resolved NetBox copy."""
    return reference_allocation_digest(allocation)
