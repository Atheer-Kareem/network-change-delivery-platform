"""B4-2 exact OSPF triangle intent, observation, rendering, and candidate tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from network_change_delivery.ansible_adapter import ProviderError
from network_change_delivery.architecture_contracts import (
    AutomationProfileID,
    ManagedField,
    ManagedScopeKind,
)
from network_change_delivery.ospf_triangle import (
    ObservedOspfInterfaceState,
    ObservedOspfRouterState,
    OspfObservation,
    OspfTriangleIntent,
    ProfileOspfReadOnlyAdapter,
    _parse_cisco_ospf,
    _parse_junos_ospf,
    build_ospf_desired_state,
    build_ospf_ownership_envelope,
    build_ospf_triangle_candidate_snapshot,
    render_ospf_changes,
)
from network_change_delivery.profile_inventory import ProfiledInventoryDevice
from network_change_delivery.profiled_pr_assurance import ROUTED_UNDERLAY_D1_DIGEST
from network_change_delivery.reference_data_plane import (
    build_accepted_reference_allocation_evidence,
)
from network_change_delivery.reference_routing_identity import (
    ACCEPTED_ROUTING_IDENTITY_ALLOCATION_DIGEST,
    build_accepted_routing_identity_evidence,
    routing_identity_allocation_digest,
)
from network_change_delivery.routed_underlay import (
    RoutedUnderlayIntent,
    build_routed_underlay_desired_state,
)


def service():
    underlay = build_accepted_reference_allocation_evidence()
    routing = build_accepted_routing_identity_evidence()
    intent = OspfTriangleIntent.from_allocations(underlay, routing)
    desired = build_ospf_desired_state(intent)
    return underlay, routing, intent, desired


def absent_observation(intent: OspfTriangleIntent) -> OspfObservation:
    return OspfObservation(
        observed_at=datetime(2026, 8, 31, tzinfo=UTC),
        routers=tuple(
            ObservedOspfRouterState(
                device_identity=router.device_identity,
                logical_name=router.logical_name,
                automation_profile_id=router.automation_profile_id,
                process_present=False,
                interfaces=tuple(
                    ObservedOspfInterfaceState(
                        interface=item.interface, participating=False
                    )
                    for item in router.interfaces
                ),
            )
            for router in intent.routers
        ),
    )


def device(router) -> ProfiledInventoryDevice:
    return ProfiledInventoryDevice.model_construct(
        device_identity=router.device_identity,
        logical_name=router.logical_name,
        automation_profile_id=router.automation_profile_id,
    )


def test_exact_intent_desired_digest_and_ownership_envelope() -> None:
    underlay, routing, intent, desired = service()
    assert routing_identity_allocation_digest(routing) == (
        ACCEPTED_ROUTING_IDENTITY_ALLOCATION_DIGEST
    )
    assert tuple(str(router.router_id) for router in intent.routers) == (
        "10.60.255.1",
        "10.60.255.2",
        "10.60.255.3",
    )
    assert (
        len(tuple(item for router in intent.routers for item in router.interfaces)) == 6
    )
    assert desired.digest == (
        "sha256:55f5718089228eb4e9f3badebca036135461c10b3c4312184462b5468d463182"
    )
    assert desired.verify_digest()
    assert (
        build_routed_underlay_desired_state(
            RoutedUnderlayIntent.from_reference_allocation(underlay)
        ).digest
        == ROUTED_UNDERLAY_D1_DIGEST
    )
    envelope = build_ospf_ownership_envelope(intent)
    assert envelope.normalized_fields == (
        ManagedField.OSPF_PROCESS,
        ManagedField.OSPF_ROUTER_ID,
        ManagedField.OSPF_INTERFACE_PARTICIPATION,
        ManagedField.OSPF_AREA,
        ManagedField.OSPF_NETWORK_TYPE,
        ManagedField.OSPF_PASSIVE,
    )
    assert sum(item.kind is ManagedScopeKind.IP_ADDRESS for item in envelope.scope) == 3
    assert all("GigabitEthernet0/0" not in item.identity for item in envelope.scope)


def test_source_authority_tamper_fails_closed() -> None:
    _underlay, _routing, intent, _desired = service()
    bad = intent.model_dump(mode="python")
    bad["routers"][0]["router_id"] = "10.60.255.99"
    with pytest.raises(ValidationError, match="detached from source authority"):
        OspfTriangleIntent.model_validate(bad)


def test_absent_state_renders_exact_iosxe_ios_and_junos_changes() -> None:
    _underlay, _routing, intent, desired = service()
    rendered = render_ospf_changes(intent, absent_observation(intent), desired)
    core, junos, transit = rendered
    assert core.logical_name == "core-02"
    assert "router ospf 1\n router-id 10.60.255.1" in core.payload
    assert "ip ospf 1 area 0" in core.payload
    assert "ip ospf network point-to-point" in core.payload
    assert junos.logical_name == "edge-junos-01"
    assert "<router-id>10.60.255.2</router-id>" in junos.payload
    assert "<name>ge-0/0/0.0</name>" in junos.payload
    assert "<interface-type>p2p</interface-type>" in junos.payload
    assert transit.logical_name == "transit-ios-01"
    assert "router-id 10.60.255.3" in transit.payload
    assert all("GigabitEthernet0/0" not in item.payload for item in rendered)


def test_observed_state_changes_render_and_junos_deletes_exact_leaves() -> None:
    _underlay, _routing, intent, desired = service()
    absent = absent_observation(intent)
    junos_router = absent.routers[1].model_copy(
        update={
            "process_present": True,
            "process_identity": "ospf",
            "router_id": "192.0.2.2",
            "interfaces": (
                ObservedOspfInterfaceState(
                    interface=intent.routers[1].interfaces[0].interface,
                    participating=True,
                    area="0.0.0.1",
                    network_type="broadcast",
                    passive=True,
                ),
                absent.routers[1].interfaces[1],
            ),
        }
    )
    changed = absent.model_copy(
        update={"routers": (absent.routers[0], junos_router, absent.routers[2])}
    )
    first = render_ospf_changes(intent, absent, desired)
    second = render_ospf_changes(intent, changed, desired)
    assert first != second
    payload = second[1].payload
    assert '<interface operation="delete"><name>ge-0/0/0.0</name>' in payload
    assert '<passive operation="delete"' in payload
    assert "<name>0.0.0.1</name>" in payload


def test_cisco_and_junos_ambiguous_observation_fails_closed() -> None:
    _underlay, _routing, intent, _desired = service()
    core = intent.routers[0]
    with pytest.raises(ProviderError, match="multiple-process"):
        _parse_cisco_ospf(
            device(core),
            tuple(item.interface for item in core.interfaces),
            ("router ospf 1\nrouter ospf 2\n", "", ""),
        )
    with pytest.raises(ProviderError, match="broad network"):
        _parse_cisco_ospf(
            device(core),
            tuple(item.interface for item in core.interfaces),
            ("router ospf 1\n network 0.0.0.0 255.255.255.255 area 0\n", "", ""),
        )
    junos = intent.routers[1]
    raw = """<configuration><protocols><ospf>
      <area><name>0.0.0.0</name><interface><name>ge-0/0/0.0</name></interface></area>
      <area><name>0.0.0.1</name><interface><name>ge-0/0/0.0</name></interface></area>
    </ospf></protocols></configuration>"""
    with pytest.raises(ProviderError, match="ambiguous area"):
        _parse_junos_ospf(
            device(junos), tuple(item.interface for item in junos.interfaces), raw
        )


def test_final_candidate_excludes_legacy_management_and_access_ospf() -> None:
    underlay, _routing, ospf_intent, ospf_desired = service()
    underlay_intent = RoutedUnderlayIntent.from_reference_allocation(underlay)
    underlay_desired = build_routed_underlay_desired_state(underlay_intent)
    with build_ospf_triangle_candidate_snapshot(
        underlay_intent, underlay_desired, ospf_intent, ospf_desired
    ) as candidate:
        assert candidate.manifest.digest == (
            "sha256:7e7f67500084682194be69d81d94f58d8ae0f6c8722e5de3b3a6c25521e5c269"
        )
        configs = {
            path.name: path.read_text()
            for path in (candidate.root / "configs").iterdir()
        }
    combined = "\n".join(configs.values())
    assert "10.6.12" not in combined
    assert "192.168.4" not in combined
    assert "router ospf 1" in configs["core-02.cfg"]
    assert "router ospf 1" in configs["transit-ios-01.cfg"]
    assert "protocols ospf" in configs["edge-junos-01.cfg"]
    assert "ospf" not in configs["access-sw-01.cfg"].casefold()


def test_ospf_adapter_has_no_write_surface_and_rejects_access_profile() -> None:
    _underlay, _routing, intent, _desired = service()
    adapter = ProfileOspfReadOnlyAdapter(cisco=object(), junos=object())
    public = {name for name in dir(adapter) if not name.startswith("_")}
    assert public == {"collect"}
    access = ProfiledInventoryDevice.model_construct(
        device_identity="netbox:dcim.device:9",
        logical_name="access-sw-01",
        automation_profile_id=AutomationProfileID.IOSVL2_2020,
    )
    with pytest.raises(ProviderError, match="unsupported"):
        adapter.collect(
            access,
            object(),
            tuple(
                item.interface.model_copy(update={"device": "netbox:dcim.device:9"})
                for item in intent.routers[0].interfaces
            ),
        )
