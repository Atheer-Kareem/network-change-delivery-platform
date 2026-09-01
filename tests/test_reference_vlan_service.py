"""Exact GET-only B4-3 VLAN service authority tests."""

from __future__ import annotations

import copy

import httpx
import pytest

from network_change_delivery.inventory import InventoryError
from network_change_delivery.reference_vlan_service import (
    ACCEPTED_VLAN_SERVICE_ALLOCATION_DIGEST,
    NetBoxReferenceVlanServiceProvider,
    vlan_service_allocation_digest,
)

TOKEN = "opaque-vlan-authority-token"


def page(results: list[object]) -> dict[str, object]:
    return {"count": len(results), "next": None, "results": results}


def active() -> dict[str, str]:
    return {"value": "active"}


def fixture_payloads() -> dict[str, list[dict[str, object]]]:
    interfaces = []
    for identity, device_id, device, name, parent, cable in (
        (7, 1, "core-02", "GigabitEthernet3", None, 4),
        (18, 9, "access-sw-01", "GigabitEthernet0/1", None, 4),
        (19, 9, "access-sw-01", "GigabitEthernet0/2", None, None),
        (20, 9, "access-sw-01", "GigabitEthernet0/3", None, None),
        (21, 1, "core-02", "GigabitEthernet3.10", 7, None),
        (22, 1, "core-02", "GigabitEthernet3.20", 7, None),
    ):
        interfaces.append(
            {
                "id": identity,
                "device": {"id": device_id, "name": device},
                "name": name,
                "parent": {"id": parent} if parent else None,
                "cable": {"id": cable} if cable else None,
                "mode": None,
                "untagged_vlan": None,
                "tagged_vlans": [],
                "type": {"value": "virtual" if parent else "1000base-t"},
                "tags": (
                    [{"slug": "ncdp-vlan-gateway"}] if identity in {21, 22} else []
                ),
            }
        )
    return {
        "interfaces": interfaces,
        "ips": [
            {
                "id": 26,
                "address": "10.60.10.1/24",
                "assigned_object_type": "dcim.interface",
                "assigned_object_id": 21,
                "status": active(),
                "tags": [{"slug": "ncdp-vlan-gateway"}],
            },
            {
                "id": 27,
                "address": "10.60.20.1/24",
                "assigned_object_type": "dcim.interface",
                "assigned_object_id": 22,
                "status": active(),
                "tags": [{"slug": "ncdp-vlan-gateway"}],
            },
        ],
        "vlans": [
            {"id": 1, "vid": 10, "name": "USERS", "status": active()},
            {"id": 2, "vid": 20, "name": "SERVERS", "status": active()},
        ],
        "prefixes": [
            {
                "id": 6,
                "prefix": "10.60.10.0/24",
                "vlan": {"id": 1},
                "status": active(),
            },
            {
                "id": 7,
                "prefix": "10.60.20.0/24",
                "vlan": {"id": 2},
                "status": active(),
            },
        ],
        "devices": [
            {"id": 1, "name": "core-02", "primary_ip4": {"id": 1}},
            {"id": 2, "name": "edge-junos-01", "primary_ip4": {"id": 2}},
            {"id": 8, "name": "transit-ios-01", "primary_ip4": {"id": 3}},
            {"id": 9, "name": "access-sw-01", "primary_ip4": {"id": 4}},
        ],
    }


def provider(
    payloads: dict[str, list[dict[str, object]]],
    requests: list[httpx.Request] | None = None,
) -> NetBoxReferenceVlanServiceProvider:
    def handler(request: httpx.Request) -> httpx.Response:
        if requests is not None:
            requests.append(request)
        mapping = {
            "/api/dcim/interfaces/": "interfaces",
            "/api/ipam/ip-addresses/": "ips",
            "/api/ipam/vlans/": "vlans",
            "/api/ipam/prefixes/": "prefixes",
            "/api/dcim/devices/": "devices",
        }
        noun = mapping.get(request.url.path)
        if noun is None:
            return httpx.Response(404)
        rows = payloads[noun]
        if "id" in request.url.params:
            identity = int(request.url.params["id"])
            rows = [item for item in rows if item["id"] == identity]
        elif noun == "interfaces":
            rows = [item for item in rows if item["id"] in {21, 22}]
        return httpx.Response(200, json=page(rows))

    return NetBoxReferenceVlanServiceProvider(
        "https://netbox.example", TOKEN, transport=httpx.MockTransport(handler)
    )


def test_exact_vlan_service_resolves_get_only() -> None:
    requests: list[httpx.Request] = []
    resolved = provider(fixture_payloads(), requests).resolve_vlan_service()
    assert vlan_service_allocation_digest(resolved) == (
        ACCEPTED_VLAN_SERVICE_ALLOCATION_DIGEST
    )
    assert resolved.cable_id == 4
    assert tuple(item.gateway_interface.interface for item in resolved.gateways) == (
        "netbox:dcim.interface:21",
        "netbox:dcim.interface:22",
    )
    assert requests and all(request.method == "GET" for request in requests)
    assert all(TOKEN not in str(request.url) for request in requests)


@pytest.mark.parametrize(
    ("noun", "index", "field", "value", "message"),
    [
        ("interfaces", 4, "parent", {"id": 99}, "interface authority"),
        ("interfaces", 1, "cable", {"id": 99}, "interface authority"),
        ("interfaces", 2, "cable", {"id": 5}, "interface authority"),
        ("ips", 0, "assigned_object_id", 22, "gateway authority"),
        ("ips", 0, "address", "10.60.10.2/24", "gateway authority"),
        ("vlans", 0, "name", "GUESTS", "VLAN authority"),
        ("prefixes", 0, "vlan", {"id": 2}, "prefix authority"),
    ],
)
def test_wrong_factual_relationship_fails_closed(
    noun: str, index: int, field: str, value: object, message: str
) -> None:
    payloads = fixture_payloads()
    payloads[noun][index][field] = value
    with pytest.raises(InventoryError, match=message):
        provider(payloads).resolve_vlan_service()


def test_missing_extra_and_primary_gateway_fail_closed() -> None:
    missing = fixture_payloads()
    missing["ips"].pop()
    with pytest.raises(InventoryError, match="population"):
        provider(missing).resolve_vlan_service()

    extra = fixture_payloads()
    extra["ips"].append(copy.deepcopy(extra["ips"][0]))
    with pytest.raises(InventoryError, match="population"):
        provider(extra).resolve_vlan_service()

    primary = fixture_payloads()
    primary["devices"][0]["primary_ip4"] = {"id": 26}
    with pytest.raises(InventoryError, match="gateway authority"):
        provider(primary).resolve_vlan_service()
