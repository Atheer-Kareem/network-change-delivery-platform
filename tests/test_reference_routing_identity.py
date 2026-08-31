"""Exact B4-2 routing-identity authority tests."""

from __future__ import annotations

import copy
import inspect

import httpx
import pytest

from network_change_delivery.inventory import InventoryError
from network_change_delivery.reference_routing_identity import (
    ACCEPTED_ROUTING_IDENTITY_ALLOCATION_DIGEST,
    ROUTING_IDENTITY_TAG,
    NetBoxReferenceRoutingIdentityProvider,
    ReferenceRoutingIdentityAllocation,
    build_accepted_routing_identity_evidence,
    routing_identity_allocation_digest,
)

TOKEN = "opaque-routing-identity-token"


def page(results: list[dict[str, object]]) -> dict[str, object]:
    return {"count": len(results), "next": None, "results": results}


def fixture_payloads() -> dict[str, list[dict[str, object]]]:
    return {
        "prefixes": [
            {
                "id": 8,
                "prefix": "10.60.255.0/24",
                "status": {"value": "active"},
            }
        ],
        "ips": [
            {
                "id": ip_id,
                "address": address,
                "status": {"value": "active"},
                "assigned_object_type": None,
                "assigned_object_id": None,
                "assigned_object": None,
                "description": f"NCDP OSPF router ID for {name}",
                "tags": [{"slug": ROUTING_IDENTITY_TAG}],
            }
            for ip_id, address, name in (
                (23, "10.60.255.1/32", "core-02"),
                (24, "10.60.255.2/32", "edge-junos-01"),
                (25, "10.60.255.3/32", "transit-ios-01"),
            )
        ],
        "devices": [
            {"id": device_id, "name": name, "primary_ip4": {"id": primary}}
            for device_id, name, primary in (
                (1, "core-02", 1),
                (2, "edge-junos-01", 2),
                (8, "transit-ios-01", 13),
                (9, "access-sw-01", 15),
            )
        ],
    }


def provider(
    payloads: dict[str, list[dict[str, object]]],
    requests: list[httpx.Request] | None = None,
) -> NetBoxReferenceRoutingIdentityProvider:
    paths = {
        "/api/ipam/prefixes/": "prefixes",
        "/api/ipam/ip-addresses/": "ips",
        "/api/dcim/devices/": "devices",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if requests is not None:
            requests.append(request)
        noun = paths.get(request.url.path)
        if noun is None:
            return httpx.Response(404)
        return httpx.Response(200, json=page(payloads[noun]))

    return NetBoxReferenceRoutingIdentityProvider(
        "https://netbox.example", TOKEN, transport=httpx.MockTransport(handler)
    )


def test_exact_get_only_resolution_and_offline_digest() -> None:
    requests: list[httpx.Request] = []
    resolved = provider(fixture_payloads(), requests).resolve_routing_identities()
    assert resolved == build_accepted_routing_identity_evidence()
    assert routing_identity_allocation_digest(resolved) == (
        ACCEPTED_ROUTING_IDENTITY_ALLOCATION_DIGEST
    )
    assert [str(item.router_id) for item in resolved.routers] == [
        "10.60.255.1",
        "10.60.255.2",
        "10.60.255.3",
    ]
    assert all(request.method == "GET" for request in requests)
    assert all(TOKEN not in str(request.url) for request in requests)


@pytest.mark.parametrize("noun", ["prefixes", "ips", "devices"])
def test_missing_or_extra_population_fails_closed(noun: str) -> None:
    missing = fixture_payloads()
    missing[noun].pop()
    with pytest.raises(InventoryError, match="population"):
        provider(missing).resolve_routing_identities()

    extra = fixture_payloads()
    extra[noun].append(copy.deepcopy(extra[noun][0]))
    with pytest.raises(InventoryError, match="population"):
        provider(extra).resolve_routing_identities()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("id", 99),
        ("address", "10.60.255.4/32"),
        ("assigned_object_type", "dcim.interface"),
        ("assigned_object_id", 11),
        ("assigned_object", {"id": 11}),
        ("description", "arbitrary"),
    ],
)
def test_wrong_assigned_or_identity_fact_fails_closed(
    field: str, value: object
) -> None:
    payloads = fixture_payloads()
    payloads["ips"][0][field] = value
    with pytest.raises(InventoryError, match="router-ID authority"):
        provider(payloads).resolve_routing_identities()


def test_primary_access_or_data_plane_membership_fails_closed() -> None:
    payloads = fixture_payloads()
    payloads["devices"][0]["primary_ip4"] = {"id": 23}
    with pytest.raises(InventoryError):
        provider(payloads).resolve_routing_identities()

    payloads = fixture_payloads()
    payloads["ips"].append(
        payloads["ips"].pop(0) | {"id": 26, "address": "10.60.255.4/32"}
    )
    with pytest.raises(InventoryError):
        provider(payloads).resolve_routing_identities()

    payloads = fixture_payloads()
    payloads["ips"][0]["tags"] = [
        {"slug": ROUTING_IDENTITY_TAG},
        {"slug": "ncdp-data-plane"},
    ]
    with pytest.raises(InventoryError, match="router-ID authority"):
        provider(payloads).resolve_routing_identities()


def test_public_model_and_provider_have_no_generic_or_write_surface() -> None:
    payload = build_accepted_routing_identity_evidence().model_dump(mode="json")
    payload["routers"][0]["device_identity"] = "netbox:dcim.device:9"
    with pytest.raises(ValueError, match="router identity is not exact"):
        ReferenceRoutingIdentityAllocation.model_validate(payload)
    public = {
        name
        for name, value in inspect.getmembers(
            NetBoxReferenceRoutingIdentityProvider, inspect.isfunction
        )
        if not name.startswith("_")
    }
    assert public == {"resolve_routing_identities"}
