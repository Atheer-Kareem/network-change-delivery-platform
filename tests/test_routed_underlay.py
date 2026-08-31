"""Detour B4-1 routed-underlay intent, observation, render, and assurance tests."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from network_change_delivery.architecture_contracts import (
    AutomationProfileID,
    ManagedField,
    ManagedVertical,
    NetworkOS,
    StableInterfaceIdentity,
)
from network_change_delivery.assurance import (
    AssuranceOutcome,
    ParseFileResult,
    ParseSummary,
)
from network_change_delivery.models import InterfaceState
from network_change_delivery.profile_inventory import ProfileReadOnlyTarget
from network_change_delivery.reference_data_plane import (
    ReferenceDataPlaneAllocation,
    RoutedLinkAllocation,
    RoutedLinkEndpoint,
    RoutedLinkIdentity,
    VLANServiceAllocation,
)
from network_change_delivery.routed_underlay import (
    BatfishInterfacePrefix,
    ObservedRoutedInterfaceState,
    RoutedUnderlayBatfishObservation,
    RoutedUnderlayDesiredState,
    RoutedUnderlayFlow,
    RoutedUnderlayIntent,
    RoutedUnderlayObservation,
    RoutedUnderlayProposalEvidence,
    RoutedUnderlayRenderFormat,
    assure_routed_underlay_candidate,
    build_routed_underlay_candidate_snapshot,
    build_routed_underlay_desired_state,
    build_routed_underlay_ownership_envelope,
    collect_routed_underlay_observation,
    evaluate_routed_underlay_assurance,
    render_routed_underlay,
    routed_underlay_delta,
)
from network_change_delivery.secrets import DeviceCredentials


def interface(device: int, object_id: int, name: str) -> StableInterfaceIdentity:
    return StableInterfaceIdentity(
        device=f"netbox:dcim.device:{device}",
        interface=f"netbox:dcim.interface:{object_id}",
        name=name,
    )


def reference_allocation() -> ReferenceDataPlaneAllocation:
    link_rows = (
        (
            RoutedLinkIdentity.CORE_JUNOS,
            3,
            "10.60.0.0/30",
            1,
            (
                (1, 11, "GigabitEthernet4", 17, "10.60.0.1/30"),
                (2, 12, "ge-0/0/0", 18, "10.60.0.2/30"),
            ),
        ),
        (
            RoutedLinkIdentity.CORE_TRANSIT,
            4,
            "10.60.0.4/30",
            2,
            (
                (1, 2, "GigabitEthernet2", 19, "10.60.0.5/30"),
                (8, 14, "GigabitEthernet0/1", 20, "10.60.0.6/30"),
            ),
        ),
        (
            RoutedLinkIdentity.JUNOS_TRANSIT,
            5,
            "10.60.0.8/30",
            3,
            (
                (2, 4, "ge-0/0/1", 21, "10.60.0.9/30"),
                (8, 15, "GigabitEthernet0/2", 22, "10.60.0.10/30"),
            ),
        ),
    )
    links = tuple(
        RoutedLinkAllocation(
            logical_link=logical_link,
            prefix_identity=f"netbox:ipam.prefix:{prefix_id}",
            prefix=prefix,
            cable_id=cable_id,
            endpoints=tuple(
                RoutedLinkEndpoint(
                    interface=interface(device, interface_id, name),
                    ip_address_identity=f"netbox:ipam.ipaddress:{ip_id}",
                    address=address,
                )
                for device, interface_id, name, ip_id, address in endpoints
            ),
        )
        for logical_link, prefix_id, prefix, cable_id, endpoints in link_rows
    )
    return ReferenceDataPlaneAllocation(
        parent_prefix_identity="netbox:ipam.prefix:2",
        parent_prefix="10.60.0.0/16",
        routed_links=links,
        vlans=(
            VLANServiceAllocation(
                vlan_identity="netbox:ipam.vlan:1",
                vid=10,
                canonical_name="USERS",
                prefix_identity="netbox:ipam.prefix:6",
                prefix="10.60.10.0/24",
            ),
            VLANServiceAllocation(
                vlan_identity="netbox:ipam.vlan:2",
                vid=20,
                canonical_name="SERVERS",
                prefix_identity="netbox:ipam.prefix:7",
                prefix="10.60.20.0/24",
            ),
        ),
        routing_identity_pool_identity="netbox:ipam.prefix:8",
        routing_identity_pool="10.60.255.0/24",
    )


def device(
    identity: int,
    name: str,
    profile: AutomationProfileID,
    network_os: NetworkOS,
) -> SimpleNamespace:
    target = ProfileReadOnlyTarget(
        logical_name=name,
        host={
            1: "192.168.4.14",
            2: "192.168.4.20",
            8: "192.168.4.16",
            9: "192.168.4.17",
        }[identity],
        port=830 if identity == 2 else 22,
        expected_hostname=name,
        protected_interfaces=("management",),
        automation_profile_id=profile,
        network_os=network_os,
    )
    return SimpleNamespace(
        device_identity=f"netbox:dcim.device:{identity}",
        logical_name=name,
        expected_hostname=name,
        automation_profile_id=profile,
        live_read_only_target=lambda: target,
    )


def population() -> SimpleNamespace:
    return SimpleNamespace(
        devices=(
            device(1, "core-02", AutomationProfileID.CAT8000V_IOSXE, NetworkOS.IOSXE),
            device(
                2, "edge-junos-01", AutomationProfileID.VJUNOS_ROUTER, NetworkOS.JUNOS
            ),
            device(
                8, "transit-ios-01", AutomationProfileID.IOSV_159_3_M12, NetworkOS.IOS
            ),
            device(9, "access-sw-01", AutomationProfileID.IOSVL2_2020, NetworkOS.IOS),
        )
    )


def desired() -> RoutedUnderlayDesiredState:
    return build_routed_underlay_desired_state(
        RoutedUnderlayIntent.from_reference_allocation(reference_allocation())
    )


def batfish_observation() -> RoutedUnderlayBatfishObservation:
    desired_state = desired()
    node_names = {
        "netbox:dcim.device:1": "core-02",
        "netbox:dcim.device:2": "edge-junos-01",
        "netbox:dcim.device:8": "transit-ios-01",
    }
    return RoutedUnderlayBatfishObservation(
        pybatfish_version="2025.7.7.2423",
        batfish_version="2026.07.20.3565",
        candidate_parse=ParseSummary(
            files=tuple(
                ParseFileResult(relative_path=f"{name}.cfg", status="PASSED")
                for name in sorted(
                    ("core-02", "edge-junos-01", "transit-ios-01", "access-sw-01")
                )
            ),
            nodes=("access-sw-01", "core-02", "edge-junos-01", "transit-ios-01"),
            initialization_issue_count=0,
        ),
        interface_prefixes=tuple(
            BatfishInterfacePrefix(
                node=node_names[state.device_identity],
                interface=state.interface.name,
                prefix=state.ipv4_addresses[0],
            )
            for state in desired_state.interfaces
        ),
        flows=(
            RoutedUnderlayFlow(
                source_node="core-02",
                source_ip="10.60.0.1",
                destination_ip="10.60.0.2",
                reachable=True,
            ),
            RoutedUnderlayFlow(
                source_node="core-02",
                source_ip="10.60.0.5",
                destination_ip="10.60.0.6",
                reachable=True,
            ),
            RoutedUnderlayFlow(
                source_node="edge-junos-01",
                source_ip="10.60.0.9",
                destination_ip="10.60.0.10",
                reachable=True,
            ),
        ),
        ospf_process_count=0,
    )


def observation() -> RoutedUnderlayObservation:
    return RoutedUnderlayObservation(
        observed_at=datetime(2026, 8, 31, tzinfo=UTC),
        interfaces=tuple(
            ObservedRoutedInterfaceState(
                device_identity=state.device_identity,
                interface=state.interface,
                exists=True,
                ipv4_addresses=(),
                admin_enabled=False,
                operational_status="down",
            )
            for state in desired().interfaces
        ),
    )


def test_intent_consumes_exact_reference_allocation_and_owns_narrow_scope() -> None:
    allocation = reference_allocation()
    intent = RoutedUnderlayIntent.from_reference_allocation(allocation)
    assert intent.source_allocation is allocation
    assert tuple(link.logical_link for link in intent.links) == tuple(
        RoutedLinkIdentity
    )
    envelope = build_routed_underlay_ownership_envelope(intent)
    assert envelope.vertical is ManagedVertical.ROUTED_UNDERLAY
    assert envelope.targets == (
        "netbox:dcim.device:1",
        "netbox:dcim.device:2",
        "netbox:dcim.device:8",
    )
    assert envelope.normalized_fields == (
        ManagedField.ROUTED_UNDERLAY_L3_PRESENCE,
        ManagedField.ROUTED_UNDERLAY_ADDRESS,
        ManagedField.ROUTED_UNDERLAY_ADMIN_ENABLED,
    )
    assert len(envelope.scope) == 9
    assert all("192.168.4" not in str(item) for item in intent.links)


def test_intent_rejects_detached_missing_or_swapped_source_facts() -> None:
    intent = RoutedUnderlayIntent.from_reference_allocation(reference_allocation())
    payload = intent.model_dump(mode="python")
    payload["links"] = payload["links"][:2]
    with pytest.raises(ValidationError):
        RoutedUnderlayIntent.model_validate(payload)
    payload = intent.model_dump(mode="python")
    payload["links"][0]["endpoints"] = tuple(reversed(payload["links"][0]["endpoints"]))
    with pytest.raises(ValidationError, match="detached from NetBox allocation"):
        RoutedUnderlayIntent.model_validate(payload)


def test_normalized_d1_is_deterministic_and_not_an_accepted_baseline() -> None:
    first = desired()
    second = desired()
    assert first == second
    assert first.verify_digest()
    assert first.digest == second.digest
    assert len(first.interfaces) == 6
    assert {str(item.ipv4_addresses[0]) for item in first.interfaces} == {
        "10.60.0.1/30",
        "10.60.0.2/30",
        "10.60.0.5/30",
        "10.60.0.6/30",
        "10.60.0.9/30",
        "10.60.0.10/30",
    }
    assert set(RoutedUnderlayDesiredState.model_fields) == {
        "schema_version",
        "interfaces",
        "digest",
    }


def test_vendor_rendering_is_exact_pure_and_excludes_access() -> None:
    intent = RoutedUnderlayIntent.from_reference_allocation(reference_allocation())
    desired_state = build_routed_underlay_desired_state(intent)
    rendered = render_routed_underlay(
        intent,
        desired_state,
        population(),  # type: ignore[arg-type]
    )
    assert tuple(item.logical_name for item in rendered) == (
        "core-02",
        "edge-junos-01",
        "transit-ios-01",
    )
    assert rendered[0].format is RoutedUnderlayRenderFormat.IOS_CLI
    assert rendered[0].content == (
        "interface GigabitEthernet4\n"
        " ip address 10.60.0.1 255.255.255.252\n"
        " no shutdown\n"
        "interface GigabitEthernet2\n"
        " ip address 10.60.0.5 255.255.255.252\n"
        " no shutdown\n"
    )
    assert rendered[2].content == (
        "interface GigabitEthernet0/1\n"
        " ip address 10.60.0.6 255.255.255.252\n"
        " no shutdown\n"
        "interface GigabitEthernet0/2\n"
        " ip address 10.60.0.10 255.255.255.252\n"
        " no shutdown\n"
    )
    assert rendered[1].format is RoutedUnderlayRenderFormat.JUNOS_XML
    assert "ge-0/0/0" in rendered[1].content
    assert "10.60.0.2/30" in rendered[1].content
    assert '<disable operation="delete"' in rendered[1].content
    assert "access-sw-01" not in "".join(item.content for item in rendered)
    payload = desired_state.model_dump(mode="python")
    payload["interfaces"][0]["ipv4_addresses"] = ("10.60.0.13/30",)
    tampered = RoutedUnderlayDesiredState.model_validate(payload)
    tampered = tampered.model_copy(update={"digest": tampered.calculated_digest()})
    with pytest.raises(ValueError, match="detached from intent"):
        render_routed_underlay(
            intent,
            tampered,
            population(),  # type: ignore[arg-type]
        )


class FakeSecretProvider:
    def __init__(self) -> None:
        self.loads: list[str] = []

    def load(self, target: SimpleNamespace) -> DeviceCredentials:
        self.loads.append(target.device_identity)
        return DeviceCredentials(username="test", password="secret")


class FakeReadOnlyAdapter:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def collect(
        self,
        target: ProfileReadOnlyTarget,
        _credentials: DeviceCredentials,
        interface_name: str,
    ) -> InterfaceState:
        self.calls.append((target.logical_name, interface_name))
        return InterfaceState(
            observed_hostname=target.expected_hostname,
            interface=interface_name,
            exists=True,
            protected=False,
            enabled=False,
            operational_status="down",
            ipv4_addresses=(),
        )


def test_real_observation_boundary_uses_live_read_only_exact_six() -> None:
    secrets = FakeSecretProvider()
    adapter = FakeReadOnlyAdapter()
    observed = collect_routed_underlay_observation(
        RoutedUnderlayIntent.from_reference_allocation(reference_allocation()),
        population(),  # type: ignore[arg-type]
        secrets,  # type: ignore[arg-type]
        adapter,  # type: ignore[arg-type]
        observed_at=datetime(2026, 8, 31, tzinfo=UTC),
    )
    assert len(observed.interfaces) == 6
    assert secrets.loads == [
        "netbox:dcim.device:1",
        "netbox:dcim.device:2",
        "netbox:dcim.device:8",
    ]
    assert adapter.calls == [
        ("core-02", "GigabitEthernet4"),
        ("core-02", "GigabitEthernet2"),
        ("edge-junos-01", "ge-0/0/0"),
        ("edge-junos-01", "ge-0/0/1"),
        ("transit-ios-01", "GigabitEthernet0/1"),
        ("transit-ios-01", "GigabitEthernet0/2"),
    ]
    assert all(not item.ipv4_addresses for item in observed.interfaces)
    assert {name for name in dir(FakeReadOnlyAdapter) if not name.startswith("_")} == {
        "collect"
    }


def test_candidate_snapshot_is_exact_four_with_no_management_or_ospf() -> None:
    intent = RoutedUnderlayIntent.from_reference_allocation(reference_allocation())
    with build_routed_underlay_candidate_snapshot(
        intent,
        build_routed_underlay_desired_state(intent),
        population(),  # type: ignore[arg-type]
    ) as candidate:
        assert {item.relative_path for item in candidate.manifest.files} == {
            "access-sw-01.cfg",
            "core-02.cfg",
            "edge-junos-01.cfg",
            "transit-ios-01.cfg",
        }
        config_root = candidate.root / "configs"
        contents = "\n".join(path.read_text() for path in sorted(config_root.iterdir()))
        assert "192.168.4" not in contents
        assert "ospf" not in contents.casefold()
        assert "ip address" not in (config_root / "access-sw-01.cfg").read_text()


def test_batfish_evaluation_proves_exact_candidate_contract() -> None:
    desired_state = desired()
    evidence = evaluate_routed_underlay_assurance(
        desired_state,
        "sha256:" + "1" * 64,
        batfish_observation(),
    )
    assert evidence.outcome is AssuranceOutcome.PASSED
    assert {item.name for item in evidence.invariants} == {
        "candidate_exact_parse_files",
        "candidate_parse_status",
        "candidate_exact_nodes",
        "candidate_initialization_issues",
        "exact_routed_interface_prefixes",
        "exact_two_participants_per_link",
        "access_switch_excluded",
        "management_addresses_excluded",
        "exact_direct_neighbor_flows",
        "ospf_absent",
    }
    failed = batfish_observation().model_copy(update={"ospf_process_count": 1})
    assert (
        evaluate_routed_underlay_assurance(
            desired_state, "sha256:" + "1" * 64, failed
        ).outcome
        is AssuranceOutcome.FAILED
    )


class FakeBatfishProvider:
    def analyze(self, candidate: Path) -> RoutedUnderlayBatfishObservation:
        assert candidate.name
        return batfish_observation()


def test_complete_secret_free_proposal_binds_o_d1_render_and_batfish() -> None:
    intent = RoutedUnderlayIntent.from_reference_allocation(reference_allocation())
    desired_state = build_routed_underlay_desired_state(intent)
    observed = observation()
    rendered = render_routed_underlay(
        intent,
        desired_state,
        population(),  # type: ignore[arg-type]
    )
    batfish = assure_routed_underlay_candidate(
        intent,
        desired_state,
        population(),  # type: ignore[arg-type]
        FakeBatfishProvider(),
    )
    proposal = RoutedUnderlayProposalEvidence(
        generated_at=datetime(2026, 8, 31, tzinfo=UTC),
        intent=intent,
        ownership_envelope=build_routed_underlay_ownership_envelope(intent),
        current_observation=observed,
        proposed_desired_state=desired_state,
        delta=routed_underlay_delta(observed, desired_state),
        rendered_targets=rendered,
        batfish=batfish,
    )
    serialized = proposal.model_dump_json()
    assert "password" not in serialized
    assert "credentials" not in serialized
    assert all(not item.addresses_match for item in proposal.delta)
    assert all(not item.admin_matches for item in proposal.delta)


def test_invalid_desired_digest_and_extra_interface_fail_closed() -> None:
    state = desired()
    assert not state.model_copy(update={"digest": "sha256:" + "f" * 64}).verify_digest()
    payload = state.model_dump(mode="python")
    payload["interfaces"] = (*payload["interfaces"][:-1], payload["interfaces"][0])
    with pytest.raises(ValidationError, match="population is not exact"):
        RoutedUnderlayDesiredState.model_validate(payload)


def test_models_and_adapter_contracts_expose_no_write_surface() -> None:
    for subject in (
        RoutedUnderlayIntent,
        RoutedUnderlayDesiredState,
        RoutedUnderlayObservation,
        RoutedUnderlayProposalEvidence,
    ):
        names = {name for name in dir(subject) if not name.startswith("_")}
        assert not names.intersection({"execute", "deploy", "write", "apply", "commit"})
