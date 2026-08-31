"""B2 profile-aware GET-only NetBox inventory contract tests."""

from __future__ import annotations

import inspect
from collections.abc import Callable

import httpx
import pytest
from pydantic import ValidationError

import network_change_delivery.inventory as inventory_module
from network_change_delivery.architecture_contracts import (
    AutomationProfileID,
    CmlRealizationProfileID,
    ManagementEndpointPurpose,
    NetworkOS,
    OperationalRole,
)
from network_change_delivery.inventory import InventoryError
from network_change_delivery.profile_inventory import (
    MANAGEMENT_ATTACHMENT_TAG,
    MANAGEMENT_LIVE_TAG,
    MANAGEMENT_STAGING_TAG,
    NCDP_MANAGED_TAG,
    OPERATIONAL_ROLE_BY_SLUG,
    PLATFORM_NETWORK_OS,
    PROFILE_ADMISSION_CATALOG,
    PROTECTED_INTERFACE_TAG,
    NetBoxProfileInventoryProvider,
    ProfiledInventoryDevice,
    admit_profile,
)

TOKEN = "opaque-profile-inventory-token"

PROFILE_CASES = (
    (
        "cisco-ios-xe",
        "Cisco IOS XE",
        "c8000v",
        "C8000V",
        AutomationProfileID.CAT8000V_IOSXE,
        CmlRealizationProfileID.CAT8000V_17_18_02,
        NetworkOS.IOSXE,
        OperationalRole.CORE,
        22,
    ),
    (
        "cisco-ios",
        "Cisco IOS",
        "iosv-159-3-m12",
        "IOSv 15.9(3)M12",
        AutomationProfileID.IOSV_159_3_M12,
        CmlRealizationProfileID.IOSV_159_3_M12,
        NetworkOS.IOS,
        OperationalRole.TRANSIT,
        22,
    ),
    (
        "cisco-ios",
        "Cisco IOS",
        "iosvl2-2020",
        "IOSvL2 2020",
        AutomationProfileID.IOSVL2_2020,
        CmlRealizationProfileID.IOSVL2_2020,
        NetworkOS.IOS,
        OperationalRole.ACCESS,
        22,
    ),
    (
        "juniper-junos",
        "Juniper Junos",
        "vjunos-router-lab",
        "vJunos Router (Synthetic Lab)",
        AutomationProfileID.VJUNOS_ROUTER,
        CmlRealizationProfileID.VJUNOS_ROUTER_23_2R1_15,
        NetworkOS.JUNOS,
        OperationalRole.EDGE,
        830,
    ),
)


def page(results: list[object], *, count: int | None = None, next_: object = None):
    return {
        "count": len(results) if count is None else count,
        "next": next_,
        "results": results,
    }


def tag(slug: str) -> dict[str, str]:
    return {"slug": slug}


def device_payload(
    *,
    platform_slug: str = "cisco-ios-xe",
    platform_name: str = "Cisco IOS XE",
    device_type_slug: str = "c8000v",
    device_type_model: str = "C8000V",
    role_slug: str = "core",
    name: str = "core-02",
    device_id: int = 4,
    **changes: object,
) -> dict[str, object]:
    value: dict[str, object] = {
        "id": device_id,
        "name": name,
        "status": {"value": "active"},
        "tags": [tag(NCDP_MANAGED_TAG)],
        "platform": {"id": 10, "slug": platform_slug, "name": platform_name},
        "device_type": {
            "id": 20,
            "slug": device_type_slug,
            "model": device_type_model,
        },
        "role": {"id": 30, "slug": role_slug, "name": role_slug.title()},
        "primary_ip4": {"id": 40, "address": "192.0.2.14/24"},
    }
    value.update(changes)
    return value


def interface_payload(
    interface_id: int,
    name: str,
    *,
    device_id: int = 4,
    device_name: str = "core-02",
    tags: list[dict[str, str]] | None = None,
) -> dict[str, object]:
    return {
        "id": interface_id,
        "name": name,
        "device": {"id": device_id, "name": device_name},
        "tags": tags or [],
    }


def ip_payload(
    ip_id: int,
    address: str,
    purpose_tag: str,
    *,
    interface_id: int = 50,
    interface_name: str = "Gi0/0",
    device_id: int = 4,
    device_name: str = "core-02",
    status: str = "active",
    extra_tags: tuple[str, ...] = (),
) -> dict[str, object]:
    return {
        "id": ip_id,
        "address": address,
        "status": {"value": status},
        "tags": [tag(purpose_tag), *(tag(item) for item in extra_tags)],
        "assigned_object_type": "dcim.interface",
        "assigned_object": {
            "id": interface_id,
            "name": interface_name,
            "device": {"id": device_id, "name": device_name},
        },
    }


def fixture_payloads(
    *,
    platform_slug: str = "cisco-ios-xe",
    platform_name: str = "Cisco IOS XE",
    device_type_slug: str = "c8000v",
    device_type_model: str = "C8000V",
    role_slug: str = "core",
    device_changes: dict[str, object] | None = None,
    interfaces: list[dict[str, object]] | None = None,
    ips: list[dict[str, object]] | None = None,
) -> tuple[dict[str, object], list[dict[str, object]], list[dict[str, object]]]:
    device = device_payload(
        platform_slug=platform_slug,
        platform_name=platform_name,
        device_type_slug=device_type_slug,
        device_type_model=device_type_model,
        role_slug=role_slug,
        **(device_changes or {}),
    )
    resolved_interfaces = interfaces or [
        interface_payload(
            50,
            "Gi0/0",
            tags=[tag(MANAGEMENT_ATTACHMENT_TAG), tag(PROTECTED_INTERFACE_TAG)],
        ),
        interface_payload(51, "Gi0/1", tags=[tag(PROTECTED_INTERFACE_TAG)]),
    ]
    resolved_ips = ips or [
        ip_payload(40, "192.0.2.14/24", MANAGEMENT_LIVE_TAG),
        ip_payload(41, "192.0.2.114/24", MANAGEMENT_STAGING_TAG),
    ]
    return device, resolved_interfaces, resolved_ips


def provider(
    payloads: tuple[
        dict[str, object], list[dict[str, object]], list[dict[str, object]]
    ],
    *,
    requests: list[httpx.Request] | None = None,
    handler_override: Callable[[httpx.Request], httpx.Response] | None = None,
) -> NetBoxProfileInventoryProvider:
    device, interfaces, ips = payloads

    def handler(request: httpx.Request) -> httpx.Response:
        if requests is not None:
            requests.append(request)
        if handler_override is not None:
            return handler_override(request)
        if request.url.path == "/api/dcim/devices/":
            return httpx.Response(200, json=page([device]))
        if request.url.path == "/api/dcim/interfaces/":
            return httpx.Response(200, json=page(interfaces))
        if request.url.path == "/api/ipam/ip-addresses/":
            return httpx.Response(200, json=page(ips))
        return httpx.Response(404)

    return NetBoxProfileInventoryProvider(
        "https://netbox.example",
        TOKEN,
        transport=httpx.MockTransport(handler),
    )


@pytest.mark.parametrize(
    (
        "platform_slug",
        "platform_name",
        "device_type_slug",
        "device_type_model",
        "profile_id",
        "realization_id",
        "network_os",
        "role",
        "port",
    ),
    PROFILE_CASES,
)
def test_exact_factual_metadata_resolves_all_four_profiles(
    platform_slug: str,
    platform_name: str,
    device_type_slug: str,
    device_type_model: str,
    profile_id: AutomationProfileID,
    realization_id: CmlRealizationProfileID,
    network_os: NetworkOS,
    role: OperationalRole,
    port: int,
) -> None:
    payloads = fixture_payloads(
        platform_slug=platform_slug,
        platform_name=platform_name,
        device_type_slug=device_type_slug,
        device_type_model=device_type_model,
        role_slug=role.value,
    )
    resolved = provider(payloads).resolve("core-02")
    assert resolved.automation_profile_id is profile_id
    assert resolved.cml_realization_profile_id is realization_id
    assert resolved.network_os is network_os
    assert resolved.operational_role is role
    assert resolved.live_read_only_target().port == port


def test_iosv_and_iosvl2_share_ios_without_sharing_profile() -> None:
    iosv = admit_profile("cisco-ios", "iosv-159-3-m12")
    iosvl2 = admit_profile("cisco-ios", "iosvl2-2020")
    assert PLATFORM_NETWORK_OS[iosv.platform_slug] is NetworkOS.IOS
    assert PLATFORM_NETWORK_OS[iosvl2.platform_slug] is NetworkOS.IOS
    assert iosv.automation_profile_id is AutomationProfileID.IOSV_159_3_M12
    assert iosvl2.automation_profile_id is AutomationProfileID.IOSVL2_2020


def test_role_is_independent_and_never_selects_behavior() -> None:
    first = provider(fixture_payloads(role_slug="core")).resolve("core-02")
    second = provider(fixture_payloads(role_slug="access")).resolve("core-02")
    assert first.automation_profile_id is second.automation_profile_id
    assert first.operational_role is OperationalRole.CORE
    assert second.operational_role is OperationalRole.ACCESS
    assert set(OPERATIONAL_ROLE_BY_SLUG) == {role.value for role in OperationalRole}


def test_profile_admission_is_closed_unique_and_has_no_fallback() -> None:
    assert len(PROFILE_ADMISSION_CATALOG) == 4
    assert {
        rule.automation_profile_id for rule in PROFILE_ADMISSION_CATALOG.values()
    } == set(AutomationProfileID)
    with pytest.raises(InventoryError, match="not admitted"):
        admit_profile("cisco-ios", "c8000v")
    with pytest.raises(InventoryError, match="not admitted"):
        admit_profile("unknown-platform", "iosvl2-2020")


@pytest.mark.parametrize(
    ("device_changes", "message"),
    [
        ({"status": {"value": "offline"}}, "inactive"),
        ({"tags": []}, "missing ncdp-managed"),
        ({"role": None}, "role is missing"),
        (
            {"role": {"id": 30, "slug": "lab-router", "name": "Lab Router"}},
            "role slug is not admitted",
        ),
        (
            {"device_type": {"id": 20, "slug": "iosvl2-2020", "model": "L2"}},
            "not admitted",
        ),
    ],
)
def test_ineligible_device_facts_fail_closed(
    device_changes: dict[str, object], message: str
) -> None:
    with pytest.raises(InventoryError, match=message):
        provider(fixture_payloads(device_changes=device_changes)).resolve("core-02")


def test_profiled_model_rejects_platform_nos_mismatch() -> None:
    resolved = provider(fixture_payloads()).resolve("core-02")
    payload = resolved.model_dump(mode="json")
    payload["network_os"] = "ios"
    with pytest.raises((ValidationError, InventoryError), match="NOS mismatch"):
        ProfiledInventoryDevice.model_validate(payload)


@pytest.mark.parametrize(
    ("interfaces", "message"),
    [
        (
            [interface_payload(50, "Gi0/0", tags=[tag(PROTECTED_INTERFACE_TAG)])],
            "one physical",
        ),
        (
            [
                interface_payload(
                    50,
                    "Gi0/0",
                    tags=[tag(MANAGEMENT_ATTACHMENT_TAG), tag(PROTECTED_INTERFACE_TAG)],
                ),
                interface_payload(
                    51,
                    "Gi0/1",
                    tags=[tag(MANAGEMENT_ATTACHMENT_TAG), tag(PROTECTED_INTERFACE_TAG)],
                ),
            ],
            "one physical",
        ),
        (
            [interface_payload(50, "Gi0/0", tags=[tag(MANAGEMENT_ATTACHMENT_TAG)])],
            "attachment is not protected",
        ),
    ],
)
def test_exact_one_protected_physical_attachment_is_required(
    interfaces: list[dict[str, object]], message: str
) -> None:
    with pytest.raises(InventoryError, match=message):
        provider(fixture_payloads(interfaces=interfaces)).resolve("core-02")


@pytest.mark.parametrize(
    ("ips", "message"),
    [
        ([ip_payload(41, "192.0.2.114/24", MANAGEMENT_STAGING_TAG)], "one LIVE"),
        ([ip_payload(40, "192.0.2.14/24", MANAGEMENT_LIVE_TAG)], "one STAGING"),
        (
            [
                ip_payload(40, "192.0.2.14/24", MANAGEMENT_LIVE_TAG),
                ip_payload(42, "192.0.2.15/24", MANAGEMENT_LIVE_TAG),
                ip_payload(41, "192.0.2.114/24", MANAGEMENT_STAGING_TAG),
            ],
            "one LIVE",
        ),
        (
            [
                ip_payload(40, "192.0.2.14/24", MANAGEMENT_LIVE_TAG),
                ip_payload(41, "192.0.2.114/24", MANAGEMENT_STAGING_TAG),
                ip_payload(42, "192.0.2.115/24", MANAGEMENT_STAGING_TAG),
            ],
            "one STAGING",
        ),
    ],
)
def test_exact_one_explicit_live_and_staging_ip_is_required(
    ips: list[dict[str, object]], message: str
) -> None:
    with pytest.raises(InventoryError, match=message):
        provider(fixture_payloads(ips=ips)).resolve("core-02")


@pytest.mark.parametrize(
    ("ips", "device_changes", "message"),
    [
        (
            [
                ip_payload(42, "192.0.2.14/24", MANAGEMENT_LIVE_TAG),
                ip_payload(41, "192.0.2.114/24", MANAGEMENT_STAGING_TAG),
            ],
            {},
            "exactly match primary",
        ),
        (
            [
                ip_payload(40, "192.0.2.15/24", MANAGEMENT_LIVE_TAG),
                ip_payload(41, "192.0.2.114/24", MANAGEMENT_STAGING_TAG),
            ],
            {},
            "exactly match primary",
        ),
        (
            [
                ip_payload(40, "192.0.2.14/24", MANAGEMENT_LIVE_TAG),
                ip_payload(41, "192.0.2.114/24", MANAGEMENT_STAGING_TAG),
            ],
            {"primary_ip4": {"id": 41, "address": "192.0.2.114/24"}},
            "LIVE management IP",
        ),
    ],
)
def test_live_exactly_matches_primary_and_staging_never_does(
    ips: list[dict[str, object]],
    device_changes: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(InventoryError, match=message):
        provider(fixture_payloads(ips=ips, device_changes=device_changes)).resolve(
            "core-02"
        )


def test_endpoint_purpose_is_tag_identity_not_numeric_range() -> None:
    ips = [
        ip_payload(40, "198.51.100.250/24", MANAGEMENT_LIVE_TAG),
        ip_payload(41, "192.0.2.1/24", MANAGEMENT_STAGING_TAG),
    ]
    resolved = provider(
        fixture_payloads(
            ips=ips,
            device_changes={"primary_ip4": {"id": 40, "address": "198.51.100.250/24"}},
        )
    ).resolve("core-02")
    assert resolved.management_endpoints.live.purpose is ManagementEndpointPurpose.LIVE
    assert str(resolved.management_endpoints.live.binding.l3_endpoint.address.ip) == (
        "198.51.100.250"
    )
    assert str(
        resolved.management_endpoints.staging.binding.l3_endpoint.address.ip
    ) == ("192.0.2.1")


def test_split_physical_and_l3_management_remains_representable_and_protected() -> None:
    interfaces = [
        interface_payload(
            50,
            "Ethernet0",
            tags=[tag(MANAGEMENT_ATTACHMENT_TAG), tag(PROTECTED_INTERFACE_TAG)],
        ),
        interface_payload(51, "Loopback0", tags=[tag(PROTECTED_INTERFACE_TAG)]),
    ]
    ips = [
        ip_payload(
            40,
            "192.0.2.14/24",
            MANAGEMENT_LIVE_TAG,
            interface_id=51,
            interface_name="Loopback0",
        ),
        ip_payload(
            41,
            "192.0.2.114/24",
            MANAGEMENT_STAGING_TAG,
            interface_id=51,
            interface_name="Loopback0",
        ),
    ]
    resolved = provider(fixture_payloads(interfaces=interfaces, ips=ips)).resolve(
        "core-02"
    )
    binding = resolved.management_endpoints.live.binding
    assert binding.physical_attachment.interface.name == "Ethernet0"
    assert binding.l3_endpoint.interface.name == "Loopback0"
    assert {item.name for item in resolved.protected_interfaces} == {
        "Ethernet0",
        "Loopback0",
    }


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("other_device", "another device"),
        ("inactive", "management IP is inactive"),
        ("unprotected_l3", "L3 interface is not protected"),
        ("different_l3", "contract is inconsistent"),
    ],
)
def test_management_ip_assignment_and_protection_fail_closed(
    mutation: str, message: str
) -> None:
    interfaces = [
        interface_payload(
            50,
            "Gi0/0",
            tags=[tag(MANAGEMENT_ATTACHMENT_TAG), tag(PROTECTED_INTERFACE_TAG)],
        ),
        interface_payload(
            51,
            "Loopback0",
            tags=[] if mutation == "unprotected_l3" else [tag(PROTECTED_INTERFACE_TAG)],
        ),
    ]
    live = ip_payload(40, "192.0.2.14/24", MANAGEMENT_LIVE_TAG)
    staging = ip_payload(41, "192.0.2.114/24", MANAGEMENT_STAGING_TAG)
    if mutation == "other_device":
        live = ip_payload(
            40,
            "192.0.2.14/24",
            MANAGEMENT_LIVE_TAG,
            device_id=99,
            device_name="foreign",
        )
    elif mutation == "inactive":
        live = ip_payload(40, "192.0.2.14/24", MANAGEMENT_LIVE_TAG, status="reserved")
    elif mutation == "unprotected_l3":
        live = ip_payload(
            40,
            "192.0.2.14/24",
            MANAGEMENT_LIVE_TAG,
            interface_id=51,
            interface_name="Loopback0",
        )
    elif mutation == "different_l3":
        staging = ip_payload(
            41,
            "192.0.2.114/24",
            MANAGEMENT_STAGING_TAG,
            interface_id=51,
            interface_name="Loopback0",
        )
    with pytest.raises(InventoryError, match=message):
        provider(fixture_payloads(interfaces=interfaces, ips=[live, staging])).resolve(
            "core-02"
        )


def test_provider_issues_get_only_with_exact_device_filters_and_no_redirects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[httpx.Request] = []
    options: dict[str, object] = {}
    real_client = inventory_module.httpx.Client

    def client_spy(**kwargs: object):
        options.update(kwargs)
        return real_client(**kwargs)

    monkeypatch.setattr(inventory_module.httpx, "Client", client_spy)
    provider(fixture_payloads(), requests=requests).resolve("core-02")
    assert [request.method for request in requests] == ["GET", "GET", "GET"]
    assert requests[0].url.params["name"] == "core-02"
    assert requests[1].url.params["device_id"] == "4"
    assert requests[2].url.params["device_id"] == "4"
    assert options["follow_redirects"] is False
    assert options["trust_env"] is False
    assert options["verify"] is True


def test_redirect_and_auth_failures_are_bounded_and_token_free() -> None:
    for status in (302, 401):

        def reject(_request: httpx.Request, status: int = status) -> httpx.Response:
            return httpx.Response(status, content=TOKEN.encode())

        with pytest.raises(InventoryError) as caught:
            provider(fixture_payloads(), handler_override=reject).resolve("core-02")
        assert TOKEN not in str(caught.value)
        assert TOKEN not in repr(caught.value)


def test_profile_models_are_secret_free_and_normal_projection_is_live_only() -> None:
    resolved = provider(fixture_payloads()).resolve("core-02")
    target = resolved.live_read_only_target()
    assert target.host == "192.0.2.14"
    assert "credential" not in ProfiledInventoryDevice.model_fields
    assert "password" not in ProfiledInventoryDevice.model_fields
    assert "command" not in ProfiledInventoryDevice.model_fields
    assert "cml_slot" not in ProfiledInventoryDevice.model_fields
    assert (
        "purpose"
        not in inspect.signature(
            ProfiledInventoryDevice.live_read_only_target
        ).parameters
    )
    assert not hasattr(NetBoxProfileInventoryProvider, "resolve_target")
    assert not hasattr(NetBoxProfileInventoryProvider, "resolve_staging")
    assert not hasattr(ProfiledInventoryDevice, "staging_read_only_target")
