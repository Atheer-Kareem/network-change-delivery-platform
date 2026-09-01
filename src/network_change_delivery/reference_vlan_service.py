"""Exact GET-only NetBox authority for the Detour B4-3 VLAN service."""

from __future__ import annotations

import ipaddress
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator

from network_change_delivery.architecture_contracts import (
    NetBoxIPAddressIdentity,
    NetBoxPrefixIdentity,
    NetBoxVLANIdentity,
    StableInterfaceIdentity,
)
from network_change_delivery.audit import canonical_json_bytes, sha256_identity
from network_change_delivery.inventory import InventoryError, NetBoxReadOnlyAPI
from network_change_delivery.reference_data_plane import (
    ACCEPTED_REFERENCE_ALLOCATION_DIGEST,
    build_accepted_reference_allocation_evidence,
    reference_allocation_digest,
)

VLAN_GATEWAY_TAG = "ncdp-vlan-gateway"
DATA_PLANE_TAG = "ncdp-data-plane"
ACCEPTED_VLAN_SERVICE_ALLOCATION_DIGEST = (
    "sha256:3068c48d95639a5f46cffefd53b0f778399b06a58b1a0704cd02e2a9dd338a1b"
)


class VlanGatewayAllocation(BaseModel):
    """One exact NetBox VLAN/prefix/subinterface/gateway relationship."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    vlan_identity: NetBoxVLANIdentity
    vid: Literal[10, 20]
    canonical_name: Literal["USERS", "SERVERS"]
    prefix_identity: NetBoxPrefixIdentity
    prefix: ipaddress.IPv4Network
    parent_interface: StableInterfaceIdentity
    gateway_interface: StableInterfaceIdentity
    gateway_ip_identity: NetBoxIPAddressIdentity
    gateway: ipaddress.IPv4Interface


class ReferenceVlanServiceAllocation(BaseModel):
    """Immutable exact B4-3 NetBox VLAN gateway and attachment resolution."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal["1"] = "1"
    source_data_plane_digest: Literal[ACCEPTED_REFERENCE_ALLOCATION_DIGEST]
    population_tag: Literal["ncdp-vlan-gateway"] = VLAN_GATEWAY_TAG
    cable_id: int = Field(ge=1)
    core_parent: StableInterfaceIdentity
    access_trunk: StableInterfaceIdentity
    access_users_port: StableInterfaceIdentity
    access_servers_port: StableInterfaceIdentity
    gateways: tuple[VlanGatewayAllocation, VlanGatewayAllocation]

    @model_validator(mode="after")
    def exact_reference_shape(self) -> ReferenceVlanServiceAllocation:
        if (
            self.source_data_plane_digest != ACCEPTED_REFERENCE_ALLOCATION_DIGEST
            or self.cable_id != 4
            or self.core_parent != _interface(1, 7, "GigabitEthernet3")
            or self.access_trunk != _interface(9, 18, "GigabitEthernet0/1")
            or self.access_users_port != _interface(9, 19, "GigabitEthernet0/2")
            or self.access_servers_port != _interface(9, 20, "GigabitEthernet0/3")
        ):
            raise ValueError("reference VLAN attachment authority is not exact")
        expected = (
            (1, 10, "USERS", 6, "10.60.10.0/24", 21, 26, "10.60.10.1/24"),
            (2, 20, "SERVERS", 7, "10.60.20.0/24", 22, 27, "10.60.20.1/24"),
        )
        for item, values in zip(self.gateways, expected, strict=True):
            vlan_id, vid, name, prefix_id, prefix, interface_id, ip_id, gateway = values
            if (
                item.vlan_identity != f"netbox:ipam.vlan:{vlan_id}"
                or item.vid != vid
                or item.canonical_name != name
                or item.prefix_identity != f"netbox:ipam.prefix:{prefix_id}"
                or str(item.prefix) != prefix
                or item.parent_interface != self.core_parent
                or item.gateway_interface
                != _interface(1, interface_id, f"GigabitEthernet3.{vid}")
                or item.gateway_ip_identity != f"netbox:ipam.ipaddress:{ip_id}"
                or str(item.gateway) != gateway
            ):
                raise ValueError("reference VLAN gateway authority is not exact")
        return self


def _interface(device_id: int, interface_id: int, name: str) -> StableInterfaceIdentity:
    return StableInterfaceIdentity(
        device=f"netbox:dcim.device:{device_id}",
        interface=f"netbox:dcim.interface:{interface_id}",
        name=name,
    )


def _build_reference_vlan_service() -> ReferenceVlanServiceAllocation:
    underlay = build_accepted_reference_allocation_evidence()
    return ReferenceVlanServiceAllocation(
        source_data_plane_digest=reference_allocation_digest(underlay),
        cable_id=4,
        core_parent=_interface(1, 7, "GigabitEthernet3"),
        access_trunk=_interface(9, 18, "GigabitEthernet0/1"),
        access_users_port=_interface(9, 19, "GigabitEthernet0/2"),
        access_servers_port=_interface(9, 20, "GigabitEthernet0/3"),
        gateways=(
            VlanGatewayAllocation(
                vlan_identity="netbox:ipam.vlan:1",
                vid=10,
                canonical_name="USERS",
                prefix_identity="netbox:ipam.prefix:6",
                prefix="10.60.10.0/24",
                parent_interface=_interface(1, 7, "GigabitEthernet3"),
                gateway_interface=_interface(1, 21, "GigabitEthernet3.10"),
                gateway_ip_identity="netbox:ipam.ipaddress:26",
                gateway="10.60.10.1/24",
            ),
            VlanGatewayAllocation(
                vlan_identity="netbox:ipam.vlan:2",
                vid=20,
                canonical_name="SERVERS",
                prefix_identity="netbox:ipam.prefix:7",
                prefix="10.60.20.0/24",
                parent_interface=_interface(1, 7, "GigabitEthernet3"),
                gateway_interface=_interface(1, 22, "GigabitEthernet3.20"),
                gateway_ip_identity="netbox:ipam.ipaddress:27",
                gateway="10.60.20.1/24",
            ),
        ),
    )


def vlan_service_allocation_digest(allocation: ReferenceVlanServiceAllocation) -> str:
    return sha256_identity(canonical_json_bytes(allocation.model_dump(mode="json")))


def build_accepted_vlan_service_evidence() -> ReferenceVlanServiceAllocation:
    """Reconstruct the accepted NetBox copy for offline assurance only."""
    allocation = _build_reference_vlan_service()
    if (
        vlan_service_allocation_digest(allocation)
        != ACCEPTED_VLAN_SERVICE_ALLOCATION_DIGEST
    ):
        raise RuntimeError("accepted VLAN service evidence digest changed")
    return allocation


def _positive(value: object, noun: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise InventoryError(f"NetBox {noun} identity is invalid")
    return value


def _active(value: object) -> bool:
    return isinstance(value, dict) and value.get("value") == "active"


class NetBoxReferenceVlanServiceProvider(NetBoxReadOnlyAPI):
    """Resolve the exact B4-3 facts through GET only."""

    def __init__(
        self,
        url: str | None = None,
        token: str | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        super().__init__(url, token, transport=transport)

    def resolve_vlan_service(self) -> ReferenceVlanServiceAllocation:
        physical_interfaces = [
            item
            for identity in (7, 18, 19, 20)
            for item in self._get_all(
                "/api/dcim/interfaces/", params={"id": identity, "ordering": "id"}
            )
        ]
        tagged_interfaces = self._get_all(
            "/api/dcim/interfaces/",
            params={"tag": VLAN_GATEWAY_TAG, "ordering": "id"},
        )
        interfaces = physical_interfaces + tagged_interfaces
        gateways = self._get_all(
            "/api/ipam/ip-addresses/",
            params={"tag": VLAN_GATEWAY_TAG, "ordering": "id"},
        )
        vlans = [
            item
            for identity in (1, 2)
            for item in self._get_all(
                "/api/ipam/vlans/", params={"id": identity, "ordering": "id"}
            )
        ]
        prefixes = [
            item
            for identity in (6, 7)
            for item in self._get_all(
                "/api/ipam/prefixes/", params={"id": identity, "ordering": "id"}
            )
        ]
        devices = self._get_all(
            "/api/dcim/devices/",
            params={"tag": "ncdp-profiled-inventory", "ordering": "id"},
        )
        if tuple(map(len, (interfaces, gateways, vlans, prefixes, devices))) != (
            6,
            2,
            2,
            2,
            4,
        ):
            raise InventoryError("NetBox VLAN service population is not exact")

        expected_interfaces = {
            7: (1, "core-02", "GigabitEthernet3", None, 4),
            18: (9, "access-sw-01", "GigabitEthernet0/1", None, 4),
            19: (9, "access-sw-01", "GigabitEthernet0/2", None, None),
            20: (9, "access-sw-01", "GigabitEthernet0/3", None, None),
            21: (1, "core-02", "GigabitEthernet3.10", 7, None),
            22: (1, "core-02", "GigabitEthernet3.20", 7, None),
        }
        for payload in interfaces:
            identity = _positive(payload.get("id"), "interface")
            expected = expected_interfaces.get(identity)
            device = payload.get("device")
            parent = payload.get("parent")
            cable = payload.get("cable")
            tags = self._tag_slugs(payload.get("tags"))
            if (
                expected is None
                or not isinstance(device, dict)
                or (device.get("id"), device.get("name"), payload.get("name"))
                != expected[:3]
                or (
                    (parent.get("id") if isinstance(parent, dict) else None)
                    != expected[3]
                )
                or (
                    (cable.get("id") if isinstance(cable, dict) else None)
                    != expected[4]
                )
                or payload.get("mode") is not None
                or payload.get("untagged_vlan") is not None
                or payload.get("tagged_vlans") not in ([], None)
                or (
                    identity in {21, 22}
                    and (
                        VLAN_GATEWAY_TAG not in tags
                        or DATA_PLANE_TAG in tags
                        or payload.get("type", {}).get("value") != "virtual"
                    )
                )
                or (identity in {7, 18, 19, 20} and VLAN_GATEWAY_TAG in tags)
            ):
                raise InventoryError("NetBox VLAN interface authority conflicts")

        expected_vlans = {1: (10, "USERS"), 2: (20, "SERVERS")}
        for payload in vlans:
            identity = _positive(payload.get("id"), "VLAN")
            if expected_vlans.get(identity) != (
                payload.get("vid"),
                payload.get("name"),
            ) or not _active(payload.get("status")):
                raise InventoryError("NetBox VLAN authority conflicts")
        expected_prefixes = {6: ("10.60.10.0/24", 1), 7: ("10.60.20.0/24", 2)}
        for payload in prefixes:
            identity = _positive(payload.get("id"), "prefix")
            vlan = payload.get("vlan")
            if expected_prefixes.get(identity) != (
                payload.get("prefix"),
                vlan.get("id") if isinstance(vlan, dict) else None,
            ) or not _active(payload.get("status")):
                raise InventoryError("NetBox VLAN prefix authority conflicts")

        expected_ips = {26: ("10.60.10.1/24", 21), 27: ("10.60.20.1/24", 22)}
        primary_ids = {
            item.get("primary_ip4", {}).get("id")
            for item in devices
            if isinstance(item.get("primary_ip4"), dict)
        }
        for payload in gateways:
            identity = _positive(payload.get("id"), "gateway IP")
            tags = self._tag_slugs(payload.get("tags"))
            if (
                expected_ips.get(identity)
                != (payload.get("address"), payload.get("assigned_object_id"))
                or payload.get("assigned_object_type") != "dcim.interface"
                or not _active(payload.get("status"))
                or identity in primary_ids
                or VLAN_GATEWAY_TAG not in tags
                or DATA_PLANE_TAG in tags
            ):
                raise InventoryError("NetBox VLAN gateway authority conflicts")
        return _build_reference_vlan_service()
