"""Detour B4-3 VLAN service intent, observation, rendering, and evidence."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from network_change_delivery.ansible_adapter import VlanReadScope
from network_change_delivery.architecture_contracts import (
    AutomationProfileID,
    ManagedField,
    ManagedScopeKind,
)
from network_change_delivery.assurance import AssuranceOutcome, InvariantResult
from network_change_delivery.ospf_triangle import (
    OspfTriangleIntent,
    build_ospf_desired_state,
)
from network_change_delivery.reference_data_plane import (
    build_accepted_reference_allocation_evidence,
)
from network_change_delivery.reference_routing_identity import (
    build_accepted_routing_identity_evidence,
)
from network_change_delivery.reference_vlan_service import (
    ACCEPTED_VLAN_SERVICE_ALLOCATION_DIGEST,
    build_accepted_vlan_service_evidence,
    vlan_service_allocation_digest,
)
from network_change_delivery.routed_underlay import (
    ACCEPTED_ROUTED_UNDERLAY_D1_DIGEST,
    RoutedUnderlayIntent,
    build_routed_underlay_desired_state,
)
from network_change_delivery.secrets import DeviceCredentials
from network_change_delivery.vlan_service import (
    ASSURANCE_FIXTURE_HOSTS,
    INFRASTRUCTURE_LAYER1_EDGES,
    LAYER1_EDGES,
    MANAGED_NETWORK_NODES,
    MODELED_NODES,
    VLAN_COMBINED_INVARIANTS,
    ObservedAccessPort,
    ObservedAccessVlan,
    ObservedCoreVlanInterface,
    ProfileVlanReadOnlyAdapter,
    VlanObservation,
    VlanServiceAssuranceEvidence,
    VlanServiceIntent,
    VlanServiceProposalEvidence,
    build_vlan_candidate_snapshot,
    build_vlan_desired_state,
    build_vlan_ownership_envelope,
    build_vlan_proposal_evidence,
    parse_access_vlan_observation,
    parse_core_vlan_observation,
    render_vlan_changes,
)

VLAN_D1 = "sha256:57fe2decfcf6ecaf595a877fac9d2fa4befa0286ec7a70b8235fd514ca3995b3"
OSPF_D1 = "sha256:55f5718089228eb4e9f3badebca036135461c10b3c4312184462b5468d463182"
CANDIDATE = "sha256:18ba3232b8ec85019b0afcfd7239eb3818e8dc788948482a54ffb2eb430dcda6"


def service_inputs():
    data_plane = build_accepted_reference_allocation_evidence()
    routing = build_accepted_routing_identity_evidence()
    vlan_facts = build_accepted_vlan_service_evidence()
    underlay_intent = RoutedUnderlayIntent.from_reference_allocation(data_plane)
    underlay_desired = build_routed_underlay_desired_state(underlay_intent)
    ospf_intent = OspfTriangleIntent.from_allocations(data_plane, routing)
    ospf_desired = build_ospf_desired_state(ospf_intent)
    vlan_intent = VlanServiceIntent.from_allocations(data_plane, vlan_facts)
    vlan_desired = build_vlan_desired_state(vlan_intent)
    return (
        underlay_intent,
        underlay_desired,
        ospf_intent,
        ospf_desired,
        vlan_intent,
        vlan_desired,
    )


def accepted_observation() -> VlanObservation:
    *_, intent, _desired = service_inputs()
    facts = intent.source_vlan_service
    return VlanObservation(
        observed_at=datetime(2026, 9, 1, tzinfo=UTC),
        core_parent=ObservedCoreVlanInterface(
            interface=facts.core_parent, exists=True, admin_enabled=False
        ),
        core_subinterfaces=tuple(
            ObservedCoreVlanInterface(interface=item.gateway_interface, exists=False)
            for item in facts.gateways
        ),
        access_vlans=(
            ObservedAccessVlan(vid=10, present=False),
            ObservedAccessVlan(vid=20, present=False),
        ),
        access_ports=(
            ObservedAccessPort(
                interface=facts.access_trunk,
                mode="dynamic auto",
                admin_enabled=True,
                access_vlan=1,
                native_vlan=1,
            ),
            ObservedAccessPort(
                interface=facts.access_users_port,
                mode="dynamic auto",
                admin_enabled=True,
                access_vlan=1,
                native_vlan=1,
            ),
            ObservedAccessPort(
                interface=facts.access_servers_port,
                mode="dynamic auto",
                admin_enabled=True,
                access_vlan=1,
                native_vlan=1,
            ),
        ),
    )


def accepted_assurance(outcome: AssuranceOutcome = AssuranceOutcome.PASSED):
    passed = outcome is AssuranceOutcome.PASSED
    return VlanServiceAssuranceEvidence(
        generated_at=datetime(2026, 9, 1, tzinfo=UTC),
        routed_underlay_digest=ACCEPTED_ROUTED_UNDERLAY_D1_DIGEST,
        ospf_digest=OSPF_D1,
        vlan_digest=VLAN_D1,
        candidate_snapshot_digest=CANDIDATE,
        pybatfish_version="2025.7.7.2423",
        batfish_version="2026.07.20.3565",
        managed_network_nodes=MANAGED_NETWORK_NODES,
        assurance_fixture_hosts=ASSURANCE_FIXTURE_HOSTS,
        modeled_nodes=MODELED_NODES,
        ospf_router_count=3,
        ospf_adjacency_count=3,
        vlan_count=2,
        vlan_gateway_count=2,
        infrastructure_layer1_edge_count=4,
        assurance_fixture_edge_count=2,
        total_layer1_edge_count=6,
        invariants=tuple(
            InvariantResult(
                name=name,
                passed=passed or name != "vlan_gateway_flows",
                detail="bounded",
            )
            for name in VLAN_COMBINED_INVARIANTS
        ),
        outcome=outcome,
    )


def test_exact_authority_intent_desired_and_ownership() -> None:
    *_, intent, desired = service_inputs()
    assert vlan_service_allocation_digest(intent.source_vlan_service) == (
        ACCEPTED_VLAN_SERVICE_ALLOCATION_DIGEST
    )
    assert desired.digest == VLAN_D1
    assert tuple(item.vid for item in desired.gateways) == (10, 20)
    assert tuple(str(item.gateway) for item in desired.gateways) == (
        "10.60.10.1/24",
        "10.60.20.1/24",
    )
    envelope = build_vlan_ownership_envelope(intent)
    assert envelope.targets == ("netbox:dcim.device:1", "netbox:dcim.device:9")
    assert set(envelope.normalized_fields) == {
        ManagedField.VLAN_PRESENCE,
        ManagedField.VLAN_PORT_MODE,
        ManagedField.VLAN_ACCESS_VLAN,
        ManagedField.VLAN_ALLOWED_VLANS,
        ManagedField.VLAN_GATEWAY,
        ManagedField.VLAN_INTERFACE_ADMIN_ENABLED,
    }
    assert ManagedField.VLAN_NATIVE_VLAN not in envelope.normalized_fields
    assert (
        len(
            [item for item in envelope.scope if item.kind is ManagedScopeKind.INTERFACE]
        )
        == 6
    )
    assert all("assurance-" not in str(item.identity) for item in envelope.scope)


def test_authority_tamper_and_native_vlan_fail_closed() -> None:
    facts = build_accepted_vlan_service_evidence()
    with pytest.raises(ValidationError):
        type(facts).model_validate(
            facts.model_copy(update={"cable_id": 5}).model_dump(mode="json")
        )
    with pytest.raises(ValidationError, match="unsupported"):
        ObservedAccessPort(
            interface=facts.access_trunk,
            mode="trunk",
            admin_enabled=True,
            native_vlan=10,
        )


def test_real_empty_observation_digest_and_transition_render() -> None:
    *_, intent, desired = service_inputs()
    observation = accepted_observation()
    assert observation.managed_state_digest() == (
        "sha256:04c4183c7d71e2e14e873f4c59bc8b11ea2022aaf302b04f2d5495ca56f4eb63"
    )
    core, access = render_vlan_changes(intent, observation, desired)
    assert "interface GigabitEthernet3.10" in core.payload
    assert "ip address 10.60.10.1 255.255.255.0" in core.payload
    assert "interface GigabitEthernet3.20" in core.payload
    assert "router ospf" not in core.payload
    assert "switchport trunk allowed vlan 10,20" in access.payload
    assert "switchport access vlan 10" in access.payload
    assert "switchport access vlan 20" in access.payload
    assert "native" not in access.payload
    assert "interface Vlan10" not in access.payload


def test_parsers_fail_closed_on_conflicting_managed_state() -> None:
    *_, intent, _desired = service_inputs()
    with pytest.raises(Exception, match="unexpected core VLAN subinterface"):
        parse_core_vlan_observation(
            intent,
            (
                "interface GigabitEthernet3\n shutdown\n",
                "interface GigabitEthernet3.99\n encapsulation dot1Q 99\n",
                "",
            ),
        )
    switchport = """Administrative Mode: static access
Access Mode VLAN: 1
Trunking Native Mode VLAN: 1
Trunking VLANs Enabled: none
Voice VLAN: none
"""
    with pytest.raises(Exception, match="unsupported"):
        parse_access_vlan_observation(
            intent,
            (
                "",
                switchport,
                switchport,
                switchport,
                "interface GigabitEthernet0/1\n channel-group 1\n",
                "interface GigabitEthernet0/2\n",
                "interface GigabitEthernet0/3\n",
                "",
            ),
        )


def test_read_only_adapter_admits_only_exact_core_and_access_profiles() -> None:
    *_, intent, _desired = service_inputs()

    class Collector:
        def collect_vlan_read_only(
            self,
            _target: object,
            _credentials: DeviceCredentials,
            scope: VlanReadScope,
            *,
            ssh_type: str,
        ) -> tuple[str, ...]:
            assert ssh_type == "paramiko"
            if scope is VlanReadScope.CORE:
                return ("interface GigabitEthernet3\n shutdown\n", "", "")
            assert scope is VlanReadScope.ACCESS
            switchport = """Administrative Mode: dynamic auto
Access Mode VLAN: 1
Trunking Native Mode VLAN: 1
Trunking VLANs Enabled: none
Voice VLAN: none
"""
            return ("", switchport, switchport, switchport, "", "", "", "")

    adapter = ProfileVlanReadOnlyAdapter(cisco=Collector())
    credentials = DeviceCredentials(username="bounded", password="secret-value")

    def device(name: str, profile: AutomationProfileID) -> object:
        return SimpleNamespace(
            logical_name=name,
            automation_profile_id=profile,
            live_read_only_target=lambda: object(),
        )

    assert adapter.collect(
        device("core-02", AutomationProfileID.CAT8000V_IOSXE), credentials, intent
    )
    assert adapter.collect(
        device("access-sw-01", AutomationProfileID.IOSVL2_2020), credentials, intent
    )
    for name, profile in (
        ("edge-junos-01", AutomationProfileID.VJUNOS_ROUTER),
        ("transit-ios-01", AutomationProfileID.IOSV_159_3_M12),
    ):
        with pytest.raises(Exception, match="not admitted"):
            adapter.collect(device(name, profile), credentials, intent)
    public = {name for name in dir(adapter) if not name.startswith("_")}
    assert not public.intersection({"write", "apply", "configure", "execute", "commit"})


def test_candidate_contains_only_exact_batfish_fixtures_and_six_edges() -> None:
    inputs = service_inputs()
    with build_vlan_candidate_snapshot(*inputs) as candidate:
        assert candidate.manifest.digest == CANDIDATE
        assert tuple(
            path.name for path in sorted((candidate.root / "configs").iterdir())
        ) == tuple(f"{name}.cfg" for name in MANAGED_NETWORK_NODES)
        hosts = {
            path.stem: json.loads(path.read_text())
            for path in (candidate.root / "hosts").iterdir()
        }
        assert set(hosts) == set(ASSURANCE_FIXTURE_HOSTS)
        assert hosts["assurance-users-probe"]["hostInterfaces"]["eth0"] == {
            "name": "eth0",
            "prefix": "10.60.10.100/24",
            "gateway": "10.60.10.1",
        }
        assert hosts["assurance-servers-probe"]["hostInterfaces"]["eth0"] == {
            "name": "eth0",
            "prefix": "10.60.20.100/24",
            "gateway": "10.60.20.1",
        }
        topology = json.loads(
            (candidate.root / "batfish/layer1_topology.json").read_text()
        )
        assert len(topology["edges"]) == 6
        assert len(INFRASTRUCTURE_LAYER1_EDGES) == 4
        assert len(LAYER1_EDGES) == 6
        assert "10.6.12" not in "".join(
            path.read_text() for path in (candidate.root / "configs").iterdir()
        )


def test_failed_assurance_and_population_tamper_invalidate_proposal() -> None:
    *_, intent, desired = service_inputs()
    observation = accepted_observation()
    with pytest.raises(ValidationError, match="proposal evidence"):
        build_vlan_proposal_evidence(
            intent, observation, desired, accepted_assurance(AssuranceOutcome.FAILED)
        )
    proposal = build_vlan_proposal_evidence(
        intent, observation, desired, accepted_assurance()
    )
    tampered = proposal.combined_assurance.model_copy(
        update={"modeled_nodes": (*MODELED_NODES, "rogue")}
    )
    with pytest.raises(ValidationError, match="assurance outcome"):
        VlanServiceProposalEvidence.model_validate(
            proposal.model_copy(update={"combined_assurance": tampered}).model_dump(
                mode="json"
            )
        )


def test_assurance_fixtures_are_not_authority_or_managed_population() -> None:
    allocation = build_accepted_vlan_service_evidence().model_dump_json()
    assert all(name not in allocation for name in ASSURANCE_FIXTURE_HOSTS)
    assert set(MANAGED_NETWORK_NODES).isdisjoint(ASSURANCE_FIXTURE_HOSTS)
    assert set(MODELED_NODES) == set(MANAGED_NETWORK_NODES) | set(
        ASSURANCE_FIXTURE_HOSTS
    )
