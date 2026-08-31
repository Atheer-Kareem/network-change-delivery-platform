"""Exact GET-only NetBox authority for the Detour B reference data plane.

This additive resolver does not feed legacy planning or device execution. Git
owns the expected logical link/service relationships below; NetBox remains the
factual authority for each admitted stable object identity and value.
"""

from __future__ import annotations

import ipaddress
from enum import StrEnum
from types import MappingProxyType
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator

from network_change_delivery.architecture_contracts import (
    NetBoxIPAddressIdentity,
    NetBoxPrefixIdentity,
    NetBoxVLANIdentity,
    StableInterfaceIdentity,
)
from network_change_delivery.inventory import InventoryError, NetBoxReadOnlyAPI

DATA_PLANE_TAG = "ncdp-data-plane"
LAB_SITE_ID = 1
LAB_SITE_SLUG = "lab"


class RoutedLinkIdentity(StrEnum):
    """Closed logical routed-link identities for the reference topology."""

    CORE_JUNOS = "core-junos-link"
    CORE_TRANSIT = "core-transit-link"
    JUNOS_TRANSIT = "junos-transit-link"


class RoutedLinkEndpoint(BaseModel):
    """One NetBox-owned routed interface/address relationship."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    interface: StableInterfaceIdentity
    ip_address_identity: NetBoxIPAddressIdentity
    address: ipaddress.IPv4Interface


class RoutedLinkAllocation(BaseModel):
    """One Git-owned routed-link relationship resolved from exact NetBox facts."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    logical_link: RoutedLinkIdentity
    prefix_identity: NetBoxPrefixIdentity
    prefix: ipaddress.IPv4Network
    cable_id: int = Field(ge=1)
    endpoints: tuple[RoutedLinkEndpoint, RoutedLinkEndpoint]

    @model_validator(mode="after")
    def exact_endpoint_network(self) -> RoutedLinkAllocation:
        if (
            len({item.interface.device for item in self.endpoints}) != 2
            or len({item.interface.interface for item in self.endpoints}) != 2
            or len({item.ip_address_identity for item in self.endpoints}) != 2
            or any(item.address.network != self.prefix for item in self.endpoints)
        ):
            raise ValueError("routed link endpoints are not exact")
        return self


class VLANServiceAllocation(BaseModel):
    """NetBox-owned VLAN identity and its exact associated service prefix."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    vlan_identity: NetBoxVLANIdentity
    vid: Literal[10, 20]
    canonical_name: Literal["USERS", "SERVERS"]
    prefix_identity: NetBoxPrefixIdentity
    prefix: ipaddress.IPv4Network

    @model_validator(mode="after")
    def identity_matches_service(self) -> VLANServiceAllocation:
        expected = {10: ("USERS", "10.60.10.0/24"), 20: ("SERVERS", "10.60.20.0/24")}
        name, prefix = expected[self.vid]
        if self.canonical_name != name or str(self.prefix) != prefix:
            raise ValueError("VLAN service allocation is inconsistent")
        return self


class ReferenceDataPlaneAllocation(BaseModel):
    """Immutable exact B3-5 NetBox/IPAM resolution."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal["1"] = "1"
    population_tag: Literal["ncdp-data-plane"] = DATA_PLANE_TAG
    parent_prefix_identity: NetBoxPrefixIdentity
    parent_prefix: ipaddress.IPv4Network
    routed_links: tuple[
        RoutedLinkAllocation, RoutedLinkAllocation, RoutedLinkAllocation
    ]
    vlans: tuple[VLANServiceAllocation, VLANServiceAllocation]
    routing_identity_pool_identity: NetBoxPrefixIdentity
    routing_identity_pool: ipaddress.IPv4Network

    @model_validator(mode="after")
    def exact_reference_shape(self) -> ReferenceDataPlaneAllocation:
        if (
            self.parent_prefix_identity != "netbox:ipam.prefix:2"
            or str(self.parent_prefix) != "10.60.0.0/16"
            or tuple(item.logical_link for item in self.routed_links)
            != tuple(RoutedLinkIdentity)
            or tuple(item.vid for item in self.vlans) != (10, 20)
            or self.routing_identity_pool_identity != "netbox:ipam.prefix:8"
            or str(self.routing_identity_pool) != "10.60.255.0/24"
        ):
            raise ValueError("reference data-plane allocation is not exact")
        for allocation, expected in zip(self.routed_links, _LINK_CATALOG, strict=True):
            logical_link, prefix, addresses, cable_id = expected
            if (
                allocation.logical_link != logical_link
                or allocation.prefix_identity
                != f"netbox:ipam.prefix:{_PREFIX_IDENTITIES[prefix]}"
                or str(allocation.prefix) != prefix
                or allocation.cable_id != cable_id
            ):
                raise ValueError("reference routed-link allocation is not exact")
            for endpoint, address in zip(allocation.endpoints, addresses, strict=True):
                ip_id, interface_id = _ROUTED_IP_IDENTITIES[address]
                device_id, _device_name, interface_name, interface_cable = (
                    _INTERFACE_IDENTITIES[interface_id]
                )
                if (
                    endpoint.interface.device != f"netbox:dcim.device:{device_id}"
                    or endpoint.interface.interface
                    != f"netbox:dcim.interface:{interface_id}"
                    or endpoint.interface.name != interface_name
                    or endpoint.ip_address_identity != f"netbox:ipam.ipaddress:{ip_id}"
                    or str(endpoint.address) != address
                    or interface_cable != cable_id
                ):
                    raise ValueError("reference routed endpoint is not exact")
        for allocation, (vid, prefix) in zip(
            self.vlans,
            ((10, "10.60.10.0/24"), (20, "10.60.20.0/24")),
            strict=True,
        ):
            vlan_id, name = _VLAN_IDENTITIES[vid]
            if (
                allocation.vlan_identity != f"netbox:ipam.vlan:{vlan_id}"
                or allocation.vid != vid
                or allocation.canonical_name != name
                or allocation.prefix_identity
                != f"netbox:ipam.prefix:{_PREFIX_IDENTITIES[prefix]}"
                or str(allocation.prefix) != prefix
            ):
                raise ValueError("reference VLAN allocation is not exact")
        return self


# These are accepted copies of NetBox-owned stable identities. They constrain
# admission without transferring authority for the underlying values to Git.
_PREFIX_IDENTITIES = MappingProxyType(
    {
        "10.60.0.0/16": 2,
        "10.60.0.0/30": 3,
        "10.60.0.4/30": 4,
        "10.60.0.8/30": 5,
        "10.60.10.0/24": 6,
        "10.60.20.0/24": 7,
        "10.60.255.0/24": 8,
    }
)
_VLAN_IDENTITIES = MappingProxyType({10: (1, "USERS"), 20: (2, "SERVERS")})
_INTERFACE_IDENTITIES = MappingProxyType(
    {
        11: (1, "core-02", "GigabitEthernet4", 1),
        12: (2, "edge-junos-01", "ge-0/0/0", 1),
        2: (1, "core-02", "GigabitEthernet2", 2),
        14: (8, "transit-ios-01", "GigabitEthernet0/1", 2),
        4: (2, "edge-junos-01", "ge-0/0/1", 3),
        15: (8, "transit-ios-01", "GigabitEthernet0/2", 3),
    }
)
_ROUTED_IP_IDENTITIES = MappingProxyType(
    {
        "10.60.0.1/30": (17, 11),
        "10.60.0.2/30": (18, 12),
        "10.60.0.5/30": (19, 2),
        "10.60.0.6/30": (20, 14),
        "10.60.0.9/30": (21, 4),
        "10.60.0.10/30": (22, 15),
    }
)
_LINK_CATALOG = (
    (
        RoutedLinkIdentity.CORE_JUNOS,
        "10.60.0.0/30",
        ("10.60.0.1/30", "10.60.0.2/30"),
        1,
    ),
    (
        RoutedLinkIdentity.CORE_TRANSIT,
        "10.60.0.4/30",
        ("10.60.0.5/30", "10.60.0.6/30"),
        2,
    ),
    (
        RoutedLinkIdentity.JUNOS_TRANSIT,
        "10.60.0.8/30",
        ("10.60.0.9/30", "10.60.0.10/30"),
        3,
    ),
)


def _positive_id(value: object, noun: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise InventoryError(f"NetBox {noun} identity is invalid")
    return value


def _required_string(value: object, noun: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InventoryError(f"NetBox {noun} is invalid")
    return value.strip()


def _active(value: object) -> bool:
    return isinstance(value, dict) and value.get("value") == "active"


class NetBoxReferenceDataPlaneProvider(NetBoxReadOnlyAPI):
    """Resolve only the exact accepted reference allocation through GET."""

    _PREFIX_PATH = "/api/ipam/prefixes/"
    _VLAN_PATH = "/api/ipam/vlans/"
    _IP_PATH = "/api/ipam/ip-addresses/"
    _INTERFACE_PATH = "/api/dcim/interfaces/"

    def __init__(
        self,
        url: str | None = None,
        token: str | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        super().__init__(url, token, transport=transport)

    def resolve_reference_allocation(self) -> ReferenceDataPlaneAllocation:
        """Resolve exact prefix/VLAN/interface/IP populations or fail closed."""
        prefix_payloads = self._get_all(
            self._PREFIX_PATH,
            params={"tag": DATA_PLANE_TAG, "ordering": "id"},
        )
        vlan_payloads = self._get_all(
            self._VLAN_PATH,
            params={"tag": DATA_PLANE_TAG, "ordering": "id"},
        )
        interface_payloads = self._get_all(
            self._INTERFACE_PATH,
            params={"tag": DATA_PLANE_TAG, "ordering": "id"},
        )
        ip_payloads = self._get_all(
            self._IP_PATH,
            params={"tag": DATA_PLANE_TAG, "ordering": "id"},
        )
        if (
            len(prefix_payloads) != len(_PREFIX_IDENTITIES)
            or len(vlan_payloads) != len(_VLAN_IDENTITIES)
            or len(interface_payloads) != len(_INTERFACE_IDENTITIES)
            or len(ip_payloads) != len(_ROUTED_IP_IDENTITIES)
        ):
            raise InventoryError("NetBox data-plane population is not exact")

        prefixes = self._prefixes(prefix_payloads)
        vlans = self._vlans(vlan_payloads)
        interfaces = self._interfaces(interface_payloads)
        ips = self._ips(ip_payloads, interfaces)
        routed_links = tuple(
            RoutedLinkAllocation(
                logical_link=logical_link,
                prefix_identity=f"netbox:ipam.prefix:{_PREFIX_IDENTITIES[prefix]}",
                prefix=prefix,
                cable_id=cable_id,
                endpoints=tuple(ips[address] for address in addresses),  # type: ignore[arg-type]
            )
            for logical_link, prefix, addresses, cable_id in _LINK_CATALOG
        )
        vlan_allocations = tuple(
            VLANServiceAllocation(
                vlan_identity=f"netbox:ipam.vlan:{_VLAN_IDENTITIES[vid][0]}",
                vid=vid,
                canonical_name=name,
                prefix_identity=f"netbox:ipam.prefix:{_PREFIX_IDENTITIES[prefix]}",
                prefix=prefix,
            )
            for vid, prefix in ((10, "10.60.10.0/24"), (20, "10.60.20.0/24"))
            for _vlan_id, name in (_VLAN_IDENTITIES[vid],)
        )
        # Force evaluation of all factual maps before constructing the result.
        if set(prefixes) != set(_PREFIX_IDENTITIES) or set(vlans) != set(
            _VLAN_IDENTITIES
        ):
            raise InventoryError("NetBox data-plane authority is incomplete")
        return ReferenceDataPlaneAllocation(
            parent_prefix_identity="netbox:ipam.prefix:2",
            parent_prefix="10.60.0.0/16",
            routed_links=routed_links,  # type: ignore[arg-type]
            vlans=vlan_allocations,  # type: ignore[arg-type]
            routing_identity_pool_identity="netbox:ipam.prefix:8",
            routing_identity_pool="10.60.255.0/24",
        )

    def _prefixes(
        self, payloads: list[dict[str, object]]
    ) -> dict[str, dict[str, object]]:
        resolved: dict[str, dict[str, object]] = {}
        expected_vlan_by_prefix = {
            "10.60.10.0/24": (10, *_VLAN_IDENTITIES[10]),
            "10.60.20.0/24": (20, *_VLAN_IDENTITIES[20]),
        }
        for payload in payloads:
            prefix = _required_string(payload.get("prefix"), "prefix")
            prefix_id = _positive_id(payload.get("id"), "prefix")
            expected_id = _PREFIX_IDENTITIES.get(prefix)
            scope = payload.get("scope")
            if (
                expected_id != prefix_id
                or prefix in resolved
                or not _active(payload.get("status"))
                or payload.get("scope_type") != "dcim.site"
                or payload.get("scope_id") != LAB_SITE_ID
                or not isinstance(scope, dict)
                or scope.get("id") != LAB_SITE_ID
                or scope.get("slug") != LAB_SITE_SLUG
                or DATA_PLANE_TAG not in self._tag_slugs(payload.get("tags"))
                or payload.get("vrf") is not None
            ):
                raise InventoryError("NetBox prefix authority conflicts")
            vlan = payload.get("vlan")
            expected_vlan = expected_vlan_by_prefix.get(prefix)
            if expected_vlan is None:
                if vlan is not None:
                    raise InventoryError("NetBox prefix VLAN association conflicts")
            elif (
                not isinstance(vlan, dict)
                or vlan.get("vid") != expected_vlan[0]
                or vlan.get("id") != expected_vlan[1]
                or vlan.get("name") != expected_vlan[2]
            ):
                raise InventoryError("NetBox prefix VLAN association conflicts")
            resolved[prefix] = payload
        return resolved

    def _vlans(self, payloads: list[dict[str, object]]) -> dict[int, dict[str, object]]:
        resolved: dict[int, dict[str, object]] = {}
        for payload in payloads:
            vid = payload.get("vid")
            if not isinstance(vid, int) or isinstance(vid, bool):
                raise InventoryError("NetBox VLAN VID is invalid")
            expected = _VLAN_IDENTITIES.get(vid)
            site = payload.get("site")
            if (
                expected is None
                or payload.get("id") != expected[0]
                or payload.get("name") != expected[1]
                or vid in resolved
                or not _active(payload.get("status"))
                or payload.get("group") is not None
                or not isinstance(site, dict)
                or site.get("id") != LAB_SITE_ID
                or site.get("slug") != LAB_SITE_SLUG
                or DATA_PLANE_TAG not in self._tag_slugs(payload.get("tags"))
            ):
                raise InventoryError("NetBox VLAN authority conflicts")
            resolved[vid] = payload
        return resolved

    def _interfaces(
        self, payloads: list[dict[str, object]]
    ) -> dict[int, StableInterfaceIdentity]:
        resolved: dict[int, StableInterfaceIdentity] = {}
        for payload in payloads:
            interface_id = _positive_id(payload.get("id"), "interface")
            expected = _INTERFACE_IDENTITIES.get(interface_id)
            device = payload.get("device")
            cable = payload.get("cable")
            if (
                expected is None
                or interface_id in resolved
                or not isinstance(device, dict)
                or device.get("id") != expected[0]
                or device.get("name") != expected[1]
                or payload.get("name") != expected[2]
                or not isinstance(cable, dict)
                or cable.get("id") != expected[3]
                or DATA_PLANE_TAG not in self._tag_slugs(payload.get("tags"))
            ):
                raise InventoryError("NetBox routed interface authority conflicts")
            resolved[interface_id] = StableInterfaceIdentity(
                device=f"netbox:dcim.device:{expected[0]}",
                interface=f"netbox:dcim.interface:{interface_id}",
                name=expected[2],
            )
        return resolved

    def _ips(
        self,
        payloads: list[dict[str, object]],
        interfaces: dict[int, StableInterfaceIdentity],
    ) -> dict[str, RoutedLinkEndpoint]:
        resolved: dict[str, RoutedLinkEndpoint] = {}
        for payload in payloads:
            address = _required_string(payload.get("address"), "IP address")
            expected = _ROUTED_IP_IDENTITIES.get(address)
            ip_id = _positive_id(payload.get("id"), "IP address")
            assigned_id = payload.get("assigned_object_id")
            assigned = payload.get("assigned_object")
            if expected is None or not isinstance(assigned, dict):
                raise InventoryError("NetBox routed IP authority conflicts")
            interface = interfaces.get(expected[1])
            interface_expected = _INTERFACE_IDENTITIES[expected[1]]
            assigned_device = assigned.get("device")
            if (
                ip_id != expected[0]
                or address in resolved
                or not _active(payload.get("status"))
                or payload.get("assigned_object_type") != "dcim.interface"
                or assigned_id != expected[1]
                or assigned.get("id") != expected[1]
                or assigned.get("name") != interface_expected[2]
                or not isinstance(assigned_device, dict)
                or assigned_device.get("id") != interface_expected[0]
                or assigned_device.get("name") != interface_expected[1]
                or interface is None
                or DATA_PLANE_TAG not in self._tag_slugs(payload.get("tags"))
            ):
                raise InventoryError("NetBox routed IP authority conflicts")
            resolved[address] = RoutedLinkEndpoint(
                interface=interface,
                ip_address_identity=f"netbox:ipam.ipaddress:{ip_id}",
                address=address,
            )
        return resolved
