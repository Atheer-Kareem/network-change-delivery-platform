"""Offline contracts for exact four-device profiled PR Batfish assurance."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from network_change_delivery.assurance import (
    AssuranceOutcome,
    ParseFileResult,
    ParseSummary,
)
from network_change_delivery.ospf_triangle import (
    BatfishOspfEdge,
    BatfishOspfInterface,
    BatfishOspfProcess,
    BatfishOspfRoute,
    OspfTriangleBatfishObservation,
    OspfTriangleIntent,
    build_ospf_desired_state,
)
from network_change_delivery.profiled_pr_assurance import (
    ACL_D1_DIGEST,
    OSPF_D1_DIGEST,
    PROFILED_ASSURANCE_FIXTURE_HOSTS,
    PROFILED_COMBINED_CANDIDATE_DIGEST,
    PROFILED_MANAGED_NETWORK_NODES,
    PROFILED_MODELED_NODES,
    ROUTED_UNDERLAY_D1_DIGEST,
    VLAN_D1_DIGEST,
    ProfiledPrAssuranceEvidence,
    ProfiledService,
    assure_profiled_pr_candidate,
    load_profiled_pr_evidence,
    write_profiled_pr_evidence,
)
from network_change_delivery.reference_data_plane import (
    ACCEPTED_REFERENCE_ALLOCATION_DIGEST,
    build_accepted_reference_allocation_evidence,
    reference_allocation_digest,
)
from network_change_delivery.reference_routing_identity import (
    build_accepted_routing_identity_evidence,
)
from network_change_delivery.reference_vlan_service import (
    build_accepted_vlan_service_evidence,
)
from network_change_delivery.routed_underlay import (
    BatfishInterfacePrefix,
    RoutedUnderlayBatfishObservation,
    RoutedUnderlayFlow,
    RoutedUnderlayIntent,
    build_routed_underlay_desired_state,
)
from network_change_delivery.security_policy import (
    ACCEPTED_ACL_CANDIDATE_DIGEST,
    ACL_NAME,
    AclObservation,
    AclSecurityBatfishObservation,
    AclSecurityFlow,
    AclSecurityIntent,
    BatfishAclAttachment,
    BatfishAclLine,
    assure_acl_security_candidate,
    build_acl_desired_state,
    build_acl_proposal_evidence,
)
from network_change_delivery.vlan_service import (
    VlanBatfishObservation,
    VlanFlow,
    VlanServiceIntent,
    VlanTrace,
    build_vlan_desired_state,
)

ROOT = Path(__file__).parents[1]

_SPEC = importlib.util.spec_from_file_location(
    "render_profiled_pr_assurance_annotation",
    ROOT / "scripts/buildkite/render_profiled_pr_assurance_annotation.py",
)
assert _SPEC and _SPEC.loader
_RENDERER = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_RENDERER)


def desired_state():
    allocation = build_accepted_reference_allocation_evidence()
    return build_routed_underlay_desired_state(
        RoutedUnderlayIntent.from_reference_allocation(allocation)
    )


def acl_service_inputs():
    allocation = build_accepted_reference_allocation_evidence()
    routing = build_accepted_routing_identity_evidence()
    vlan = build_accepted_vlan_service_evidence()
    underlay_intent = RoutedUnderlayIntent.from_reference_allocation(allocation)
    underlay_desired = build_routed_underlay_desired_state(underlay_intent)
    ospf_intent = OspfTriangleIntent.from_allocations(allocation, routing)
    ospf_desired = build_ospf_desired_state(ospf_intent)
    vlan_intent = VlanServiceIntent.from_allocations(allocation, vlan)
    vlan_desired = build_vlan_desired_state(vlan_intent)
    acl_intent = AclSecurityIntent.from_allocations(allocation, vlan, vlan_desired)
    acl_desired = build_acl_desired_state(acl_intent)
    return (
        underlay_intent,
        underlay_desired,
        ospf_intent,
        ospf_desired,
        vlan_intent,
        vlan_desired,
        acl_intent,
        acl_desired,
    )


def batfish_observation(
    nodes: tuple[str, ...] = PROFILED_MANAGED_NETWORK_NODES,
) -> OspfTriangleBatfishObservation:
    desired = desired_state()
    node_names = {
        "netbox:dcim.device:1": "core-02",
        "netbox:dcim.device:2": "edge-junos-01",
        "netbox:dcim.device:8": "transit-ios-01",
    }
    underlay = RoutedUnderlayBatfishObservation(
        pybatfish_version="2025.7.7.2423",
        batfish_version="2026.07.20.3565",
        candidate_parse=ParseSummary(
            files=tuple(
                ParseFileResult(relative_path=f"{name}.cfg", status="PASSED")
                for name in PROFILED_MANAGED_NETWORK_NODES
            ),
            nodes=nodes,
            initialization_issue_count=0,
        ),
        interface_prefixes=tuple(
            BatfishInterfacePrefix(
                node=node_names[state.device_identity],
                interface=state.interface.name,
                prefix=state.ipv4_addresses[0],
            )
            for state in desired.interfaces
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
        ospf_process_count=3,
    )
    return OspfTriangleBatfishObservation(
        underlay=underlay,
        processes=(
            BatfishOspfProcess(node="core-02", router_id="10.60.255.1"),
            BatfishOspfProcess(node="edge-junos-01", router_id="10.60.255.2"),
            BatfishOspfProcess(node="transit-ios-01", router_id="10.60.255.3"),
        ),
        interfaces=(
            BatfishOspfInterface(
                node="core-02",
                interface="GigabitEthernet2",
                area="0.0.0.0",
                network_type="point-to-point",
                passive=False,
            ),
            BatfishOspfInterface(
                node="core-02",
                interface="GigabitEthernet4",
                area="0.0.0.0",
                network_type="point-to-point",
                passive=False,
            ),
            BatfishOspfInterface(
                node="edge-junos-01",
                interface="ge-0/0/0",
                area="0.0.0.0",
                network_type="point-to-point",
                passive=False,
            ),
            BatfishOspfInterface(
                node="edge-junos-01",
                interface="ge-0/0/1",
                area="0.0.0.0",
                network_type="point-to-point",
                passive=False,
            ),
            BatfishOspfInterface(
                node="transit-ios-01",
                interface="GigabitEthernet0/1",
                area="0.0.0.0",
                network_type="point-to-point",
                passive=False,
            ),
            BatfishOspfInterface(
                node="transit-ios-01",
                interface="GigabitEthernet0/2",
                area="0.0.0.0",
                network_type="point-to-point",
                passive=False,
            ),
        ),
        edges=(
            BatfishOspfEdge(nodes=("core-02", "edge-junos-01")),
            BatfishOspfEdge(nodes=("core-02", "transit-ios-01")),
            BatfishOspfEdge(nodes=("edge-junos-01", "transit-ios-01")),
        ),
        routes=(
            BatfishOspfRoute(node="core-02", prefix="10.60.0.8/30", protocol="ospf"),
            BatfishOspfRoute(
                node="edge-junos-01", prefix="10.60.0.4/30", protocol="ospf"
            ),
            BatfishOspfRoute(
                node="transit-ios-01", prefix="10.60.0.0/30", protocol="ospf"
            ),
        ),
        remote_flows=(
            RoutedUnderlayFlow(
                source_node="core-02",
                source_ip="10.60.0.1",
                destination_ip="10.60.0.10",
                reachable=True,
            ),
            RoutedUnderlayFlow(
                source_node="edge-junos-01",
                source_ip="10.60.0.2",
                destination_ip="10.60.0.6",
                reachable=True,
            ),
            RoutedUnderlayFlow(
                source_node="transit-ios-01",
                source_ip="10.60.0.6",
                destination_ip="10.60.0.2",
                reachable=True,
            ),
        ),
    )


def vlan_batfish_observation(
    nodes: tuple[str, ...] = PROFILED_MANAGED_NETWORK_NODES,
    *,
    modeled_nodes: tuple[str, ...] = PROFILED_MODELED_NODES,
    reachable: bool = True,
) -> VlanBatfishObservation:
    return VlanBatfishObservation(
        ospf=batfish_observation(nodes),
        modeled_nodes=modeled_nodes,
        layer1_edges=(
            (("access-sw-01", "GigabitEthernet0/1"), ("core-02", "GigabitEthernet3")),
            (("access-sw-01", "GigabitEthernet0/2"), ("assurance-users-probe", "eth0")),
            (
                ("access-sw-01", "GigabitEthernet0/3"),
                ("assurance-servers-probe", "eth0"),
            ),
            (("core-02", "GigabitEthernet2"), ("transit-ios-01", "GigabitEthernet0/1")),
            (("core-02", "GigabitEthernet4"), ("edge-junos-01", "ge-0/0/0")),
            (("edge-junos-01", "ge-0/0/1"), ("transit-ios-01", "GigabitEthernet0/2")),
        ),
        switched_vlans=(
            (10, ("GigabitEthernet0/1", "GigabitEthernet0/2")),
            (20, ("GigabitEthernet0/1", "GigabitEthernet0/3")),
        ),
        switchports=(
            ("access-sw-01", "GigabitEthernet0/1", "trunk", (10, 20), None, 1),
            ("access-sw-01", "GigabitEthernet0/2", "access", (), 10, 1),
            ("access-sw-01", "GigabitEthernet0/3", "access", (), 20, 1),
        ),
        gateways=(
            ("core-02", "GigabitEthernet3.10", "['10.60.10.1/24']"),
            ("core-02", "GigabitEthernet3.20", "['10.60.20.1/24']"),
        ),
        access_l3_interfaces=(),
        connected_routes=("10.60.10.0/24", "10.60.20.0/24"),
        remote_ospf_vlan_routes=(),
        flows=(
            VlanFlow(
                name="users_gateway",
                reported_trace_count=1,
                traces=(
                    VlanTrace(
                        disposition="ACCEPTED" if reachable else "EXITS_NETWORK",
                        nodes=("assurance-users-probe", "core-02"),
                        final_node="core-02",
                    ),
                ),
            ),
            VlanFlow(
                name="servers_gateway",
                reported_trace_count=1,
                traces=(
                    VlanTrace(
                        disposition="ACCEPTED" if reachable else "EXITS_NETWORK",
                        nodes=("assurance-servers-probe", "core-02"),
                        final_node="core-02",
                    ),
                ),
            ),
            VlanFlow(
                name="users_to_servers",
                reported_trace_count=1,
                traces=(
                    VlanTrace(
                        disposition="ACCEPTED" if reachable else "EXITS_NETWORK",
                        nodes=(
                            "assurance-users-probe",
                            "core-02",
                            "assurance-servers-probe",
                        ),
                        final_node="assurance-servers-probe",
                    ),
                ),
            ),
            VlanFlow(
                name="servers_to_users",
                reported_trace_count=1,
                traces=(
                    VlanTrace(
                        disposition="ACCEPTED" if reachable else "EXITS_NETWORK",
                        nodes=(
                            "assurance-servers-probe",
                            "core-02",
                            "assurance-users-probe",
                        ),
                        final_node="assurance-users-probe",
                    ),
                ),
            ),
        ),
    )


class FakeBatfishProvider:
    def __init__(
        self,
        nodes: tuple[str, ...] = PROFILED_MANAGED_NETWORK_NODES,
        observation: AclSecurityBatfishObservation | None = None,
    ) -> None:
        self.nodes = nodes
        self.observation = observation
        self.candidate_contents = ""

    def analyze(
        self, baseline_candidate: Path, secured_candidate: Path
    ) -> AclSecurityBatfishObservation:
        baseline_paths = tuple(sorted((baseline_candidate / "configs").iterdir()))
        paths = tuple(sorted((secured_candidate / "configs").iterdir()))
        assert tuple(path.name for path in paths) == tuple(
            f"{name}.cfg" for name in PROFILED_MANAGED_NETWORK_NODES
        )
        assert ACL_NAME not in "\n".join(path.read_text() for path in baseline_paths)
        self.candidate_contents = "\n".join(path.read_text() for path in paths)
        assert ACL_NAME in self.candidate_contents
        host_paths = tuple(sorted((secured_candidate / "hosts").iterdir()))
        assert tuple(path.name for path in host_paths) == (
            "assurance-servers-probe.json",
            "assurance-users-probe.json",
        )
        return self.observation or acl_batfish_observation(self.nodes)


def security_flows(*, secured: bool) -> tuple[AclSecurityFlow, ...]:
    expected = (
        ("users_https", "ACCEPTED", "assurance-servers-probe"),
        (
            "users_ssh",
            "DENIED_OUT" if secured else "ACCEPTED",
            "core-02" if secured else "assurance-servers-probe",
        ),
        (
            "users_icmp",
            "DENIED_OUT" if secured else "ACCEPTED",
            "core-02" if secured else "assurance-servers-probe",
        ),
        ("servers_to_users", "ACCEPTED", "assurance-users-probe"),
        ("users_gateway", "ACCEPTED", "core-02"),
        ("servers_gateway", "ACCEPTED", "core-02"),
    )
    sources = {
        "users_https": "assurance-users-probe",
        "users_ssh": "assurance-users-probe",
        "users_icmp": "assurance-users-probe",
        "servers_to_users": "assurance-servers-probe",
        "users_gateway": "assurance-users-probe",
        "servers_gateway": "assurance-servers-probe",
    }
    return tuple(
        AclSecurityFlow(
            name=name,
            reported_trace_count=1,
            traces=(
                VlanTrace(
                    disposition=disposition,
                    nodes=(sources[name], "core-02")
                    if final == "core-02"
                    else (sources[name], "core-02", final),
                    final_node=final,
                ),
            ),
        )
        for name, disposition, final in expected
    )


def acl_batfish_observation(
    nodes: tuple[str, ...] = PROFILED_MANAGED_NETWORK_NODES,
) -> AclSecurityBatfishObservation:
    vlan = vlan_batfish_observation(nodes)
    return AclSecurityBatfishObservation(
        baseline_vlan=vlan,
        secured_vlan=vlan,
        baseline_flows=security_flows(secured=False),
        secured_flows=security_flows(secured=True),
        acl_lines=(
            BatfishAclLine(
                filter_name=ACL_NAME,
                line_index=0,
                line=("10 permit tcp 10.60.10.0 0.0.0.255 10.60.20.0 0.0.0.255 eq 443"),
                action="PERMIT",
            ),
            BatfishAclLine(
                filter_name=ACL_NAME,
                line_index=1,
                line="20 deny ip 10.60.10.0 0.0.0.255 10.60.20.0 0.0.0.255",
                action="DENY",
            ),
            BatfishAclLine(
                filter_name=ACL_NAME,
                line_index=2,
                line="30 permit ip any any",
                action="PERMIT",
            ),
        ),
        acl_attachments=(
            BatfishAclAttachment(
                interface="GigabitEthernet3.20", outgoing_filter=ACL_NAME
            ),
        ),
    )


def replace_security_flow(
    observation: AclSecurityBatfishObservation,
    name: str,
    traces: tuple[VlanTrace, ...],
) -> AclSecurityBatfishObservation:
    return observation.model_copy(
        update={
            "secured_flows": tuple(
                AclSecurityFlow(
                    name=flow.name,
                    reported_trace_count=len(traces),
                    traces=traces,
                )
                if flow.name == name
                else flow
                for flow in observation.secured_flows
            )
        }
    )


def invariant(evidence: ProfiledPrAssuranceEvidence, name: str) -> bool:
    return next(item.passed for item in evidence.invariants if item.name == name)


def test_offline_allocation_reconstructs_exact_accepted_b3_5_copy() -> None:
    allocation = build_accepted_reference_allocation_evidence()
    assert reference_allocation_digest(allocation) == (
        ACCEPTED_REFERENCE_ALLOCATION_DIGEST
    )
    assert tuple(str(link.prefix) for link in allocation.routed_links) == (
        "10.60.0.0/30",
        "10.60.0.4/30",
        "10.60.0.8/30",
    )
    assert tuple(
        endpoint.interface.interface
        for link in allocation.routed_links
        for endpoint in link.endpoints
    ) == (
        "netbox:dcim.interface:11",
        "netbox:dcim.interface:12",
        "netbox:dcim.interface:2",
        "netbox:dcim.interface:14",
        "netbox:dcim.interface:4",
        "netbox:dcim.interface:15",
    )


def test_profiled_pr_assurance_is_exact_deterministic_and_d1_only() -> None:
    first_provider = FakeBatfishProvider()
    second_provider = FakeBatfishProvider()
    first = assure_profiled_pr_candidate(first_provider)
    second = assure_profiled_pr_candidate(second_provider)

    assert first == second
    assert first.verify_digest()
    assert first.architecture_identity == "profiled-four-device"
    assert first.active_service_stack == (
        ProfiledService.ROUTED_UNDERLAY,
        ProfiledService.OSPF,
        ProfiledService.VLAN,
        ProfiledService.ACL,
    )
    assert first.accepted_source_allocation_digest == (
        ACCEPTED_REFERENCE_ALLOCATION_DIGEST
    )
    assert tuple(subject.digest for subject in first.service_subjects) == (
        ROUTED_UNDERLAY_D1_DIGEST,
        OSPF_D1_DIGEST,
        VLAN_D1_DIGEST,
        ACL_D1_DIGEST,
    )
    assert first.candidate_snapshot_digest == PROFILED_COMBINED_CANDIDATE_DIGEST
    assert first.managed_network_nodes == PROFILED_MANAGED_NETWORK_NODES
    assert first.assurance_fixture_hosts == PROFILED_ASSURANCE_FIXTURE_HOSTS
    assert first.modeled_nodes == PROFILED_MODELED_NODES
    assert first.outcome is AssuranceOutcome.PASSED
    assert len(first.invariants) == 40
    assert all(item.passed for item in first.invariants)
    for content in (
        first_provider.candidate_contents,
        second_provider.candidate_contents,
    ):
        assert "10.6.12" not in content
        assert "192.168.4" not in content
        assert "router ospf 1" in content
        assert "10.60.255.1" in content
        assert ACL_NAME in content


@pytest.mark.parametrize("disposition", ["ACCEPTED", "EXITS_NETWORK"])
def test_secured_ssh_requires_exact_acl_denial(disposition: str) -> None:
    observation = replace_security_flow(
        acl_batfish_observation(),
        "users_ssh",
        (
            VlanTrace(
                disposition=disposition,
                nodes=("assurance-users-probe", "core-02"),
                final_node="core-02",
            ),
        ),
    )
    evidence = assure_profiled_pr_candidate(
        FakeBatfishProvider(observation=observation)
    )
    assert evidence.outcome is AssuranceOutcome.FAILED
    assert not invariant(evidence, "acl_ssh_blocked")


def test_one_good_and_one_bypass_trace_cannot_hide_failure() -> None:
    observation = replace_security_flow(
        acl_batfish_observation(),
        "users_https",
        (
            VlanTrace(
                disposition="ACCEPTED",
                nodes=("assurance-users-probe", "core-02", "assurance-servers-probe"),
                final_node="assurance-servers-probe",
            ),
            VlanTrace(
                disposition="ACCEPTED",
                nodes=("assurance-users-probe", "assurance-servers-probe"),
                final_node="assurance-servers-probe",
            ),
        ),
    )
    evidence = assure_profiled_pr_candidate(
        FakeBatfishProvider(observation=observation)
    )
    assert not invariant(evidence, "acl_https_preserved")


@pytest.mark.parametrize("unexpected", ["edge-junos-01", "transit-ios-01"])
def test_security_flow_rejects_remote_router_transit(unexpected: str) -> None:
    observation = replace_security_flow(
        acl_batfish_observation(),
        "users_https",
        (
            VlanTrace(
                disposition="ACCEPTED",
                nodes=(
                    "assurance-users-probe",
                    "core-02",
                    unexpected,
                    "assurance-servers-probe",
                ),
                final_node="assurance-servers-probe",
            ),
        ),
    )
    evidence = assure_profiled_pr_candidate(
        FakeBatfishProvider(observation=observation)
    )
    assert not invariant(evidence, "acl_https_preserved")


def test_wrong_final_fixture_does_not_pass_security_contract() -> None:
    observation = replace_security_flow(
        acl_batfish_observation(),
        "users_https",
        (
            VlanTrace(
                disposition="ACCEPTED",
                nodes=("assurance-users-probe", "core-02", "wrong-host"),
                final_node="wrong-host",
            ),
        ),
    )
    evidence = assure_profiled_pr_candidate(
        FakeBatfishProvider(observation=observation)
    )
    assert not invariant(evidence, "acl_https_preserved")


def test_reported_trace_count_cannot_hide_truncation() -> None:
    with pytest.raises(ValueError, match="truncated"):
        VlanFlow(
            name="users_gateway",
            reported_trace_count=2,
            traces=(
                VlanTrace(
                    disposition="ACCEPTED",
                    nodes=("assurance-users-probe", "core-02"),
                    final_node="core-02",
                ),
            ),
        )


def test_failed_combined_assurance_invalidates_acl_proposal() -> None:
    inputs = acl_service_inputs()
    assurance = assure_acl_security_candidate(*inputs, provider=FakeBatfishProvider())
    observation = AclObservation(
        observed_at=assurance.generated_at, policy_present=False
    )
    proposal = build_acl_proposal_evidence(inputs[6], observation, inputs[7], assurance)
    assert proposal.combined_assurance.outcome is AssuranceOutcome.PASSED
    failed_invariants = (
        assurance.invariants[0].model_copy(update={"passed": False}),
        *assurance.invariants[1:],
    )
    failed = assurance.model_copy(
        update={
            "invariants": failed_invariants,
            "outcome": AssuranceOutcome.FAILED,
        }
    )
    with pytest.raises(ValueError, match="proposal evidence"):
        build_acl_proposal_evidence(inputs[6], observation, inputs[7], failed)


@pytest.mark.parametrize(
    "nodes",
    [
        ("core-02", "edge-junos-01"),
        ("access-sw-01", "core-02", "edge-junos-01"),
        ("core-02", "edge-junos-01", "transit-ios-01"),
        (*PROFILED_MANAGED_NETWORK_NODES, "rogue-01"),
    ],
)
def test_non_exact_candidate_population_cannot_pass(
    nodes: tuple[str, ...],
) -> None:
    with pytest.raises(ValueError, match="assurance"):
        assure_profiled_pr_candidate(FakeBatfishProvider(nodes))


def test_evidence_io_and_annotation_are_typed_and_allowlisted(tmp_path: Path) -> None:
    evidence = assure_profiled_pr_candidate(FakeBatfishProvider())
    path = tmp_path / "profiled-pr-assurance.json"
    write_profiled_pr_evidence(evidence, path)
    assert load_profiled_pr_evidence(path) == evidence

    annotation = _RENDERER.render_annotation(evidence)
    for value in (
        "Profiled PR Batfish assurance",
        "profiled-four-device",
        "routed_underlay",
        "vlan",
        "acl",
        "6",
        "40 / 40 passed",
        *PROFILED_MANAGED_NETWORK_NODES,
        *PROFILED_ASSURANCE_FIXTURE_HOSTS,
        ROUTED_UNDERLAY_D1_DIGEST,
        OSPF_D1_DIGEST,
        VLAN_D1_DIGEST,
        ACL_D1_DIGEST,
        ACCEPTED_ACL_CANDIDATE_DIGEST,
        PROFILED_COMBINED_CANDIDATE_DIGEST,
    ):
        assert value in annotation
    assert "2026.07.20.3565" not in annotation
    assert "10.60.0.1" not in annotation

    tampered = evidence.model_copy(update={"digest": "sha256:" + "0" * 64})
    path.write_text(tampered.model_dump_json())
    with pytest.raises(ValueError, match="evidence file is invalid"):
        load_profiled_pr_evidence(path)


def test_profiled_entry_point_has_no_live_authority_imports_or_surfaces() -> None:
    sources = (
        ROOT / "src/network_change_delivery/profiled_pr_assurance.py",
        ROOT / "scripts/assurance/verify_profiled_pr_candidate.py",
    )
    forbidden = (
        "NetBoxReferenceDataPlaneProvider",
        "NetBoxProfileInventoryProvider",
        "OpenBaoSecretProvider",
        "ProfileReadOnlyAdapter",
        "NCDP_NETBOX_TOKEN",
        "NCDP_OPENBAO",
        "known_hosts",
        "paramiko",
        "ncclient",
    )
    for source in sources:
        text = source.read_text()
        assert all(value not in text for value in forbidden)

    public = {
        name for name in dir(ProfiledPrAssuranceEvidence) if not name.startswith("_")
    }
    assert not public.intersection({"execute", "deploy", "write", "apply", "commit"})
