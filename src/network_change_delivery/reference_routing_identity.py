"""Exact GET-only NetBox authority for the B4-2 OSPF router identities."""

from __future__ import annotations

import ipaddress
from types import MappingProxyType
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict, model_validator

from network_change_delivery.architecture_contracts import (
    NetBoxDeviceIdentity,
    NetBoxIPAddressIdentity,
    NetBoxPrefixIdentity,
)
from network_change_delivery.audit import canonical_json_bytes, sha256_identity
from network_change_delivery.inventory import InventoryError, NetBoxReadOnlyAPI

ROUTING_IDENTITY_TAG = "ncdp-routing-identity"
DATA_PLANE_TAG = "ncdp-data-plane"
ACCEPTED_ROUTING_IDENTITY_ALLOCATION_DIGEST = (
    "sha256:7e57aaa1dd066fecadb2e43d1f1f82a32cf2250648ddd656d7f0068194d4b7ca"
)

# Accepted copies of NetBox-owned identity allocated by the B4-2 migration.
_ROUTER_IDENTITIES = MappingProxyType(
    {
        "core-02": (1, 23, "10.60.255.1/32"),
        "edge-junos-01": (2, 24, "10.60.255.2/32"),
        "transit-ios-01": (8, 25, "10.60.255.3/32"),
    }
)


class OspfRouterIdentity(BaseModel):
    """One unassigned NetBox IP identity admitted as an OSPF router ID."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    device_identity: NetBoxDeviceIdentity
    logical_name: Literal["core-02", "edge-junos-01", "transit-ios-01"]
    ip_address_identity: NetBoxIPAddressIdentity
    router_id: ipaddress.IPv4Address

    @model_validator(mode="after")
    def exact_identity_mapping(self) -> OspfRouterIdentity:
        device_id, ip_id, address = _ROUTER_IDENTITIES[self.logical_name]
        if (
            self.device_identity != f"netbox:dcim.device:{device_id}"
            or self.ip_address_identity != f"netbox:ipam.ipaddress:{ip_id}"
            or str(self.router_id) != address.removesuffix("/32")
        ):
            raise ValueError("OSPF router identity is not exact")
        return self


class ReferenceRoutingIdentityAllocation(BaseModel):
    """Immutable exact B4-2 routing-identity allocation."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal["1"] = "1"
    population_tag: Literal["ncdp-routing-identity"] = ROUTING_IDENTITY_TAG
    pool_identity: NetBoxPrefixIdentity
    pool_prefix: ipaddress.IPv4Network
    routers: tuple[OspfRouterIdentity, OspfRouterIdentity, OspfRouterIdentity]

    @model_validator(mode="after")
    def exact_population(self) -> ReferenceRoutingIdentityAllocation:
        if (
            self.pool_identity != "netbox:ipam.prefix:8"
            or str(self.pool_prefix) != "10.60.255.0/24"
            or tuple(item.logical_name for item in self.routers)
            != tuple(_ROUTER_IDENTITIES)
            or len({item.device_identity for item in self.routers}) != 3
            or len({item.ip_address_identity for item in self.routers}) != 3
            or len({item.router_id for item in self.routers}) != 3
            or any(item.router_id not in self.pool_prefix for item in self.routers)
        ):
            raise ValueError("routing-identity allocation is not exact")
        return self


def routing_identity_allocation_digest(
    allocation: ReferenceRoutingIdentityAllocation,
) -> str:
    """Return the canonical digest for one resolved routing-identity copy."""
    return sha256_identity(canonical_json_bytes(allocation.model_dump(mode="json")))


def _build_routing_identity_allocation() -> ReferenceRoutingIdentityAllocation:
    return ReferenceRoutingIdentityAllocation(
        pool_identity="netbox:ipam.prefix:8",
        pool_prefix="10.60.255.0/24",
        routers=tuple(  # type: ignore[arg-type]
            OspfRouterIdentity(
                device_identity=f"netbox:dcim.device:{device_id}",
                logical_name=name,
                ip_address_identity=f"netbox:ipam.ipaddress:{ip_id}",
                router_id=address.removesuffix("/32"),
            )
            for name, (device_id, ip_id, address) in _ROUTER_IDENTITIES.items()
        ),
    )


def build_accepted_routing_identity_evidence() -> ReferenceRoutingIdentityAllocation:
    """Reconstruct the accepted NetBox copy for offline PR assurance only."""
    allocation = _build_routing_identity_allocation()
    if (
        routing_identity_allocation_digest(allocation)
        != ACCEPTED_ROUTING_IDENTITY_ALLOCATION_DIGEST
    ):
        raise RuntimeError("accepted routing-identity evidence digest changed")
    return allocation


def _positive_id(value: object, noun: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise InventoryError(f"NetBox {noun} identity is invalid")
    return value


def _required_string(value: object, noun: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InventoryError(f"NetBox {noun} is invalid")
    return value.strip()


class NetBoxReferenceRoutingIdentityProvider(NetBoxReadOnlyAPI):
    """Resolve exactly three unassigned router IDs using GET only."""

    _IP_PATH = "/api/ipam/ip-addresses/"
    _PREFIX_PATH = "/api/ipam/prefixes/"
    _DEVICE_PATH = "/api/dcim/devices/"

    def __init__(
        self,
        url: str | None = None,
        token: str | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        super().__init__(url, token, transport=transport)

    def resolve_routing_identities(self) -> ReferenceRoutingIdentityAllocation:
        """Resolve the exact B4-2 facts or fail closed."""
        prefixes = self._get_all(self._PREFIX_PATH, params={"id": 8, "ordering": "id"})
        ips = self._get_all(
            self._IP_PATH, params={"tag": ROUTING_IDENTITY_TAG, "ordering": "id"}
        )
        devices = self._get_all(
            self._DEVICE_PATH,
            params={"tag": "ncdp-profiled-inventory", "ordering": "id"},
        )
        if len(prefixes) != 1 or len(ips) != 3 or len(devices) != 4:
            raise InventoryError("NetBox routing-identity population is not exact")
        prefix = prefixes[0]
        if (
            _positive_id(prefix.get("id"), "prefix") != 8
            or _required_string(prefix.get("prefix"), "prefix") != "10.60.255.0/24"
            or not isinstance(prefix.get("status"), dict)
            or prefix["status"].get("value") != "active"
        ):
            raise InventoryError("NetBox routing-identity pool conflicts")

        expected_primary = {1: 1, 2: 2, 8: 13, 9: 15}
        device_facts: dict[int, tuple[str, int]] = {}
        for device in devices:
            device_id = _positive_id(device.get("id"), "device")
            name = _required_string(device.get("name"), "device name")
            primary = device.get("primary_ip4")
            primary_id = (
                _positive_id(primary.get("id"), "primary IP")
                if isinstance(primary, dict)
                else 0
            )
            if device_id in device_facts:
                raise InventoryError("NetBox routing-identity device is duplicated")
            device_facts[device_id] = (name, primary_id)
        if device_facts != {
            1: ("core-02", 1),
            2: ("edge-junos-01", 2),
            8: ("transit-ios-01", 13),
            9: ("access-sw-01", 15),
        } or {value[1] for value in device_facts.values()} != set(
            expected_primary.values()
        ):
            raise InventoryError("NetBox routing-identity device authority conflicts")

        seen: dict[str, dict[str, object]] = {}
        expected_by_address = {
            address: (name, device_id, ip_id)
            for name, (device_id, ip_id, address) in _ROUTER_IDENTITIES.items()
        }
        for payload in ips:
            address = _required_string(payload.get("address"), "router ID")
            expected = expected_by_address.get(address)
            if expected is None or address in seen:
                raise InventoryError("NetBox router-ID authority conflicts")
            name, _device_id, expected_id = expected
            tags = self._tag_slugs(payload.get("tags"))
            status = payload.get("status")
            if (
                _positive_id(payload.get("id"), "router ID") != expected_id
                or not isinstance(status, dict)
                or status.get("value") != "active"
                or payload.get("assigned_object_type") is not None
                or payload.get("assigned_object_id") is not None
                or payload.get("assigned_object") is not None
                or _required_string(payload.get("description"), "description")
                != f"NCDP OSPF router ID for {name}"
                or ROUTING_IDENTITY_TAG not in tags
                or DATA_PLANE_TAG in tags
                or expected_id in {primary for _name, primary in device_facts.values()}
            ):
                raise InventoryError("NetBox router-ID authority conflicts")
            seen[address] = payload
        if set(seen) != set(expected_by_address):
            raise InventoryError("NetBox router-ID authority is incomplete")
        return _build_routing_identity_allocation()
