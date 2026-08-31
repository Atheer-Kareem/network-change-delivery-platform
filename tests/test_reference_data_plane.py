"""Exact B3-5 reference data-plane resolver tests."""

from __future__ import annotations

import copy
import inspect
from collections.abc import Callable

import httpx
import pytest

from network_change_delivery.inventory import InventoryError
from network_change_delivery.reference_data_plane import (
    DATA_PLANE_TAG,
    NetBoxReferenceDataPlaneProvider,
    ReferenceDataPlaneAllocation,
    RoutedLinkIdentity,
)

TOKEN = "opaque-reference-data-plane-token"


def page(results: list[object]) -> dict[str, object]:
    return {"count": len(results), "next": None, "results": results}


def tag() -> dict[str, str]:
    return {"slug": DATA_PLANE_TAG}


def status() -> dict[str, str]:
    return {"value": "active"}


def site() -> dict[str, object]:
    return {"id": 1, "name": "lab", "slug": "lab"}


def fixture_payloads() -> dict[str, list[dict[str, object]]]:
    vlans = [
        {
            "id": 1,
            "vid": 10,
            "name": "USERS",
            "status": status(),
            "site": site(),
            "group": None,
            "tags": [tag()],
        },
        {
            "id": 2,
            "vid": 20,
            "name": "SERVERS",
            "status": status(),
            "site": site(),
            "group": None,
            "tags": [tag()],
        },
    ]
    prefix_rows = (
        (2, "10.60.0.0/16", None),
        (3, "10.60.0.0/30", None),
        (4, "10.60.0.4/30", None),
        (5, "10.60.0.8/30", None),
        (6, "10.60.10.0/24", {"id": 1, "vid": 10, "name": "USERS"}),
        (7, "10.60.20.0/24", {"id": 2, "vid": 20, "name": "SERVERS"}),
        (8, "10.60.255.0/24", None),
    )
    prefixes = [
        {
            "id": object_id,
            "prefix": prefix,
            "status": status(),
            "scope_type": "dcim.site",
            "scope_id": 1,
            "scope": site(),
            "vlan": vlan,
            "vrf": None,
            "tags": [tag()],
        }
        for object_id, prefix, vlan in prefix_rows
    ]
    interface_rows = (
        (2, 1, "core-02", "GigabitEthernet2", 2),
        (4, 2, "edge-junos-01", "ge-0/0/1", 3),
        (11, 1, "core-02", "GigabitEthernet4", 1),
        (12, 2, "edge-junos-01", "ge-0/0/0", 1),
        (14, 8, "transit-ios-01", "GigabitEthernet0/1", 2),
        (15, 8, "transit-ios-01", "GigabitEthernet0/2", 3),
    )
    interfaces = [
        {
            "id": interface_id,
            "name": name,
            "device": {"id": device_id, "name": device_name},
            "cable": {"id": cable_id},
            "tags": [tag()],
        }
        for interface_id, device_id, device_name, name, cable_id in interface_rows
    ]
    by_interface = {item[0]: item for item in interface_rows}
    ip_rows = (
        (17, "10.60.0.1/30", 11),
        (18, "10.60.0.2/30", 12),
        (19, "10.60.0.5/30", 2),
        (20, "10.60.0.6/30", 14),
        (21, "10.60.0.9/30", 4),
        (22, "10.60.0.10/30", 15),
    )
    ips = []
    for object_id, address, interface_id in ip_rows:
        _, device_id, device_name, interface_name, cable_id = by_interface[interface_id]
        ips.append(
            {
                "id": object_id,
                "address": address,
                "status": status(),
                "assigned_object_type": "dcim.interface",
                "assigned_object_id": interface_id,
                "assigned_object": {
                    "id": interface_id,
                    "name": interface_name,
                    "device": {"id": device_id, "name": device_name},
                    "cable": {"id": cable_id},
                },
                "tags": [tag()],
            }
        )
    return {"prefixes": prefixes, "vlans": vlans, "interfaces": interfaces, "ips": ips}


def provider(
    payloads: dict[str, list[dict[str, object]]],
    *,
    requests: list[httpx.Request] | None = None,
    handler_override: Callable[[httpx.Request], httpx.Response] | None = None,
) -> NetBoxReferenceDataPlaneProvider:
    paths = {
        "/api/ipam/prefixes/": "prefixes",
        "/api/ipam/vlans/": "vlans",
        "/api/ipam/ip-addresses/": "ips",
        "/api/dcim/interfaces/": "interfaces",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if requests is not None:
            requests.append(request)
        if handler_override is not None:
            return handler_override(request)
        noun = paths.get(request.url.path)
        if noun is None:
            return httpx.Response(404)
        assert request.url.params["tag"] == DATA_PLANE_TAG
        return httpx.Response(200, json=page(payloads[noun]))

    return NetBoxReferenceDataPlaneProvider(
        "https://netbox.example",
        TOKEN,
        transport=httpx.MockTransport(handler),
    )


def test_exact_reference_allocation_resolves_get_only() -> None:
    requests: list[httpx.Request] = []
    resolved = provider(
        fixture_payloads(), requests=requests
    ).resolve_reference_allocation()
    assert str(resolved.parent_prefix) == "10.60.0.0/16"
    assert resolved.parent_prefix_identity == "netbox:ipam.prefix:2"
    assert tuple(item.logical_link for item in resolved.routed_links) == tuple(
        RoutedLinkIdentity
    )
    assert [str(item.prefix) for item in resolved.routed_links] == [
        "10.60.0.0/30",
        "10.60.0.4/30",
        "10.60.0.8/30",
    ]
    assert [item.cable_id for item in resolved.routed_links] == [1, 2, 3]
    assert [item.vid for item in resolved.vlans] == [10, 20]
    assert [item.canonical_name for item in resolved.vlans] == ["USERS", "SERVERS"]
    assert str(resolved.routing_identity_pool) == "10.60.255.0/24"
    assert requests and all(request.method == "GET" for request in requests)
    assert all(TOKEN not in str(request.url) for request in requests)


def test_public_allocation_contract_rejects_non_catalog_identity_or_address() -> None:
    resolved = provider(fixture_payloads()).resolve_reference_allocation()
    wrong_identity = resolved.model_dump(mode="json")
    wrong_identity["parent_prefix_identity"] = "netbox:ipam.prefix:99"
    with pytest.raises(ValueError, match="allocation is not exact"):
        ReferenceDataPlaneAllocation.model_validate(wrong_identity)

    wrong_address = resolved.model_dump(mode="json")
    wrong_address["routed_links"][0]["endpoints"][0]["address"] = "10.60.0.3/30"
    with pytest.raises(ValueError, match="endpoint is not exact"):
        ReferenceDataPlaneAllocation.model_validate(wrong_address)


@pytest.mark.parametrize("noun", ["prefixes", "vlans", "interfaces", "ips"])
def test_missing_or_additional_data_plane_population_fails(noun: str) -> None:
    missing = fixture_payloads()
    missing[noun].pop()
    with pytest.raises(InventoryError, match="population"):
        provider(missing).resolve_reference_allocation()

    additional = fixture_payloads()
    additional[noun].append(copy.deepcopy(additional[noun][0]))
    with pytest.raises(InventoryError, match="population"):
        provider(additional).resolve_reference_allocation()


def test_duplicate_and_wrong_prefix_identity_fail_closed() -> None:
    duplicate = fixture_payloads()
    duplicate["prefixes"][1] = copy.deepcopy(duplicate["prefixes"][0])
    with pytest.raises(InventoryError, match="prefix authority"):
        provider(duplicate).resolve_reference_allocation()

    wrong = fixture_payloads()
    wrong["prefixes"][1]["prefix"] = "10.60.0.12/30"
    with pytest.raises(InventoryError, match="prefix authority"):
        provider(wrong).resolve_reference_allocation()


@pytest.mark.parametrize(
    ("field", "value"),
    [("vid", 30), ("name", "GUESTS"), ("id", 99)],
)
def test_wrong_vlan_identity_fails_closed(field: str, value: object) -> None:
    payloads = fixture_payloads()
    payloads["vlans"][0][field] = value
    with pytest.raises(InventoryError, match="VLAN authority"):
        provider(payloads).resolve_reference_allocation()


def test_wrong_vlan_prefix_association_fails_closed() -> None:
    payloads = fixture_payloads()
    payloads["prefixes"][4]["vlan"] = {"id": 2, "vid": 20, "name": "SERVERS"}
    with pytest.raises(InventoryError, match="VLAN association"):
        provider(payloads).resolve_reference_allocation()


def test_wrong_interface_identity_or_cable_fails_closed() -> None:
    payloads = fixture_payloads()
    payloads["interfaces"][0]["name"] = "GigabitEthernet3"
    with pytest.raises(InventoryError, match="interface authority"):
        provider(payloads).resolve_reference_allocation()

    payloads = fixture_payloads()
    payloads["interfaces"][0]["cable"] = {"id": 99}
    with pytest.raises(InventoryError, match="interface authority"):
        provider(payloads).resolve_reference_allocation()


def test_wrong_or_swapped_ip_assignment_fails_closed() -> None:
    payloads = fixture_payloads()
    first = payloads["ips"][0]
    second = payloads["ips"][1]
    first["assigned_object_id"], second["assigned_object_id"] = (
        second["assigned_object_id"],
        first["assigned_object_id"],
    )
    first["assigned_object"], second["assigned_object"] = (
        second["assigned_object"],
        first["assigned_object"],
    )
    with pytest.raises(InventoryError, match="routed IP authority"):
        provider(payloads).resolve_reference_allocation()

    payloads = fixture_payloads()
    payloads["ips"][0]["address"] = "10.60.0.2/30"
    with pytest.raises(InventoryError, match="routed IP authority"):
        provider(payloads).resolve_reference_allocation()


def test_resolver_has_no_write_or_generic_ipam_surface() -> None:
    public = {
        name
        for name, value in inspect.getmembers(
            NetBoxReferenceDataPlaneProvider, inspect.isfunction
        )
        if not name.startswith("_")
    }
    assert public == {"resolve_reference_allocation"}
