"""B3-1 exact profiled-population and legacy-separation tests."""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

import network_change_delivery.profile_inventory as profile_inventory_module
from network_change_delivery.inventory import InventoryError, NetBoxInventoryProvider
from network_change_delivery.profile_inventory import (
    PROFILED_INVENTORY_TAG,
    PROFILED_POPULATION_CATALOG,
    NetBoxProfileInventoryProvider,
    ProfiledDeviceName,
)

TOKEN = "opaque-profiled-population-token"

MEMBERS = (
    (
        1,
        "core-02",
        "core",
        "cisco-ios-xe",
        "Cisco IOS XE",
        "c8000v",
        "C8000V",
        "192.0.2.14/24",
    ),
    (
        2,
        "edge-junos-01",
        "edge",
        "juniper-junos",
        "Juniper Junos",
        "vjunos-router-lab",
        "vJunos Router",
        "192.0.2.20/24",
    ),
    (
        31,
        "transit-ios-01",
        "transit",
        "cisco-ios",
        "Cisco IOS",
        "iosv-159-3-m12",
        "IOSv 15.9(3)M12",
        "192.0.2.16/24",
    ),
    (
        42,
        "access-sw-01",
        "access",
        "cisco-ios",
        "Cisco IOS",
        "iosvl2-2020",
        "IOSvL2 2020",
        "192.0.2.17/24",
    ),
)


def page(results: list[object]) -> dict[str, object]:
    return {"count": len(results), "next": None, "results": results}


def tag(slug: str) -> dict[str, str]:
    return {"slug": slug}


def devices() -> list[dict[str, object]]:
    payloads = []
    for index, member in enumerate(MEMBERS):
        (
            device_id,
            name,
            role,
            platform_slug,
            platform_name,
            device_type_slug,
            device_type_model,
            address,
        ) = member
        payloads.append(
            {
                "id": device_id,
                "name": name,
                "status": {"value": "active"},
                "tags": [tag(PROFILED_INVENTORY_TAG)],
                "platform": {
                    "id": 100 + index,
                    "slug": platform_slug,
                    "name": platform_name,
                },
                "device_type": {
                    "id": 200 + index,
                    "slug": device_type_slug,
                    "model": device_type_model,
                },
                "role": {"id": 300 + index, "slug": role, "name": role.title()},
                "primary_ip4": {"id": 400 + index * 2, "address": address},
            }
        )
    return payloads


def interfaces(device: dict[str, object]) -> list[dict[str, object]]:
    device_id = int(device["id"])
    name = str(device["name"])
    interface_id = 500 + device_id
    return [
        {
            "id": interface_id,
            "name": "Gi0/0" if name != "edge-junos-01" else "fxp0",
            "device": {"id": device_id, "name": name},
            "tags": [
                tag("ncdp-management-attachment"),
                tag("ncdp-protected"),
            ],
        }
    ]


def addresses(device: dict[str, object]) -> list[dict[str, object]]:
    device_id = int(device["id"])
    name = str(device["name"])
    primary = device["primary_ip4"]
    assert isinstance(primary, dict)
    primary_id = int(primary["id"])
    live_address = str(primary["address"])
    staging_address = f"198.51.100.{device_id}/24"
    interface = interfaces(device)[0]

    def address(ip_id: int, value: str, purpose: str) -> dict[str, object]:
        return {
            "id": ip_id,
            "address": value,
            "status": {"value": "active"},
            "tags": [tag(purpose)],
            "assigned_object_type": "dcim.interface",
            "assigned_object": {
                "id": interface["id"],
                "name": interface["name"],
                "device": {"id": device_id, "name": name},
            },
        }

    return [
        address(primary_id, live_address, "ncdp-management-live"),
        address(primary_id + 1, staging_address, "ncdp-management-staging"),
    ]


def profiled_provider(
    device_payloads: list[dict[str, object]],
    *,
    requests: list[httpx.Request] | None = None,
) -> NetBoxProfileInventoryProvider:
    by_id = {int(device["id"]): device for device in device_payloads}

    def handler(request: httpx.Request) -> httpx.Response:
        if requests is not None:
            requests.append(request)
        if request.url.path == "/api/dcim/devices/":
            name = request.url.params.get("name")
            selected = (
                [device for device in device_payloads if device.get("name") == name]
                if name
                else device_payloads
            )
            return httpx.Response(200, json=page(selected))
        device_id = int(request.url.params["device_id"])
        device = by_id[device_id]
        if request.url.path == "/api/dcim/interfaces/":
            return httpx.Response(200, json=page(interfaces(device)))
        if request.url.path == "/api/ipam/ip-addresses/":
            return httpx.Response(200, json=page(addresses(device)))
        return httpx.Response(404)

    return NetBoxProfileInventoryProvider(
        "https://netbox.example",
        TOKEN,
        transport=httpx.MockTransport(handler),
    )


def mutate(
    payloads: list[dict[str, object]],
    name: str,
    change: Callable[[dict[str, object]], None],
) -> list[dict[str, object]]:
    for payload in payloads:
        if payload["name"] == name:
            change(payload)
            return payloads
    raise AssertionError("fixture member not found")


def test_exact_four_profiled_population_is_deterministic_and_get_only() -> None:
    requests: list[httpx.Request] = []
    population = profiled_provider(
        list(reversed(devices())), requests=requests
    ).resolve_profiled_population()
    assert population.population_tag == PROFILED_INVENTORY_TAG
    assert tuple(device.logical_name for device in population.devices) == tuple(
        member.logical_name for member in PROFILED_POPULATION_CATALOG
    )
    assert tuple(device.logical_name for device in population.devices) == tuple(
        ProfiledDeviceName
    )
    assert all(request.method == "GET" for request in requests)
    first = requests[0]
    assert first.url.params["tag"] == PROFILED_INVENTORY_TAG
    assert first.url.params["status"] == "active"
    assert first.url.params["ordering"] == "id"


def test_profiled_population_member_model_is_catalog_internal() -> None:
    assert not hasattr(profile_inventory_module, "ProfiledPopulationMember")


@pytest.mark.parametrize("population_size", [3, 5])
def test_profiled_population_requires_exactly_four_members(
    population_size: int,
) -> None:
    payloads = devices()
    if population_size == 3:
        payloads.pop()
    else:
        extra = dict(payloads[-1])
        extra.update(id=99, name="foreign-01")
        payloads.append(extra)
    with pytest.raises(InventoryError, match="exactly four"):
        profiled_provider(payloads).resolve_profiled_population()


def test_profiled_population_rejects_wrong_or_duplicate_names() -> None:
    wrong = mutate(devices(), "access-sw-01", lambda item: item.update(name="other"))
    with pytest.raises(InventoryError, match="names are not exact"):
        profiled_provider(wrong).resolve_profiled_population()

    duplicate = mutate(
        devices(), "access-sw-01", lambda item: item.update(name="transit-ios-01")
    )
    with pytest.raises(InventoryError, match="duplicate logical name"):
        profiled_provider(duplicate).resolve_profiled_population()


def test_profiled_population_rejects_duplicate_stable_identity() -> None:
    duplicate = mutate(devices(), "access-sw-01", lambda item: item.update(id=31))
    with pytest.raises(InventoryError, match="duplicate stable identity"):
        profiled_provider(duplicate).resolve_profiled_population()


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (
            lambda item: item.update(role={"id": 9, "slug": "edge", "name": "Edge"}),
            "Git catalog",
        ),
        (lambda item: item.update(status={"value": "offline"}), "inactive"),
        (lambda item: item.update(tags=[tag("ncdp-managed")]), "missing ncdp-profiled"),
        (
            lambda item: item.update(
                device_type={"id": 9, "slug": "iosv-159-3-m12", "model": "IOSv"}
            ),
            "Git catalog",
        ),
    ],
)
def test_profiled_population_fails_closed_on_wrong_member_facts(
    change: Callable[[dict[str, object]], None], message: str
) -> None:
    payloads = mutate(devices(), "access-sw-01", change)
    with pytest.raises(InventoryError, match=message):
        profiled_provider(payloads).resolve_profiled_population()


def test_per_device_profile_resolution_has_no_legacy_tag_fallback() -> None:
    payloads = mutate(
        devices(), "core-02", lambda item: item.update(tags=[tag("ncdp-managed")])
    )
    with pytest.raises(InventoryError, match="missing ncdp-profiled-inventory"):
        profiled_provider(payloads).resolve("core-02")


def test_v1_population_contract_remains_legacy_and_ios_closed() -> None:
    device = devices()[0]
    device["tags"] = [tag("ncdp-managed")]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/dcim/devices/":
            return httpx.Response(200, json=page([device]))
        if request.url.path == "/api/dcim/interfaces/":
            return httpx.Response(200, json=page([]))
        return httpx.Response(404)

    legacy = NetBoxInventoryProvider(
        "https://netbox.example",
        TOKEN,
        transport=httpx.MockTransport(handler),
    )
    assert legacy.resolve("core-02").platform == "cisco_iosxe"
    assert set(NetBoxInventoryProvider._PLATFORM_MAPPING) == {
        "cisco-ios-xe",
        "juniper-junos",
    }
