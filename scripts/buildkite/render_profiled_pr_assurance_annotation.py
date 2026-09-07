#!/usr/bin/env python3
"""Render a strict human summary for profiled PR Batfish evidence."""

from __future__ import annotations

import argparse
import html
import sys
from pathlib import Path

from network_change_delivery.profiled_pr_assurance import (
    PROFILED_COMBINED_INVARIANTS,
    ProfiledPrAssuranceEvidence,
    load_profiled_pr_evidence,
)

# Closed presentation vocabulary, not assurance policy. New machine invariants
# require an explicit human label; do not infer labels from identifier spelling.
INVARIANT_DISPLAY = {
    "candidate_exact_parse_files": ("Model integrity", "Expected configuration files"),
    "candidate_parse_status": ("Model integrity", "Configuration parsing"),
    "candidate_exact_nodes": ("Model integrity", "Expected modeled nodes"),
    "candidate_initialization_issues": (
        "Model integrity",
        "Clean model initialization",
    ),
    "exact_routed_interface_prefixes": (
        "Routed underlay",
        "Expected routed interfaces and prefixes",
    ),
    "exact_two_participants_per_link": (
        "Routed underlay",
        "Two endpoints per routed link",
    ),
    "access_switch_excluded": (
        "Routed underlay",
        "Access switch excluded from routed links",
    ),
    "management_addresses_excluded": (
        "Routed underlay",
        "Management addresses excluded from underlay",
    ),
    "exact_direct_neighbor_flows": ("Routed underlay", "Direct neighbor reachability"),
    "ospf_exact_routers": ("OSPF", "Expected participating routers"),
    "ospf_access_excluded": ("OSPF", "Access switch excluded from OSPF"),
    "ospf_exact_interfaces": ("OSPF", "Expected OSPF interfaces"),
    "ospf_management_excluded": ("OSPF", "Management interfaces excluded from OSPF"),
    "ospf_exact_adjacencies": ("OSPF", "Expected adjacency topology"),
    "ospf_remote_routes": ("OSPF", "Remote subnet routes"),
    "ospf_remote_reachability": ("OSPF", "Remote subnet reachability"),
    "vlan_exact_modeled_population": ("VLAN", "Expected VLAN participants"),
    "vlan_exact_layer1_edges": ("VLAN", "Expected physical connections"),
    "vlan_exact_switched_membership": ("VLAN", "Expected VLAN membership"),
    "vlan_exact_switchports": ("VLAN", "Access and trunk port settings"),
    "vlan_service_not_native": ("VLAN", "Service VLANs remain tagged"),
    "vlan_exact_gateways": ("VLAN", "Expected VLAN gateways"),
    "vlan_access_has_no_gateway": ("VLAN", "Gateways remain on the core router"),
    "vlan_connected_routes": ("VLAN", "Connected VLAN subnet routes"),
    "vlan_not_advertised_ospf": ("VLAN", "VLAN subnets excluded from OSPF"),
    "vlan_gateway_flows": ("VLAN", "VLAN gateway reachability"),
    "acl_accepted_b4_3_baseline": ("ACL/security", "Reviewed VLAN baseline retained"),
    "acl_exact_policy": ("ACL/security", "Expected ACL policy"),
    "acl_exact_attachment": ("ACL/security", "Expected ACL location and direction"),
    "acl_exact_rule_order": ("ACL/security", "Expected ACL rule order"),
    "acl_default_permit": ("ACL/security", "Unmatched traffic remains permitted"),
    "acl_management_excluded": ("ACL/security", "Management path excluded from ACL"),
    "acl_baseline_https_open": ("ACL/security", "HTTPS reachable before ACL"),
    "acl_https_preserved": ("ACL/security", "USERS → SERVERS HTTPS is allowed"),
    "acl_baseline_ssh_open": ("ACL/security", "SSH reachable before ACL"),
    "acl_ssh_blocked": ("ACL/security", "USERS → SERVERS SSH is blocked"),
    "acl_baseline_icmp_open": ("ACL/security", "ICMP reachable before ACL"),
    "acl_icmp_blocked": ("ACL/security", "USERS → SERVERS ICMP is blocked"),
    "acl_reverse_direction_preserved": (
        "ACL/security",
        "SERVERS → USERS remains allowed",
    ),
    "acl_gateways_preserved": ("ACL/security", "VLAN gateway reachability preserved"),
}


def _safe(value: object) -> str:
    return (
        html.escape(str(value), quote=True)
        .replace("|", "&#124;")
        .replace("`", "&#96;")
        .replace("\r", " ")
        .replace("\n", " ")
    )


def render_annotation(evidence: ProfiledPrAssuranceEvidence) -> str:
    if tuple(INVARIANT_DISPLAY) != PROFILED_COMBINED_INVARIANTS:
        raise ValueError("human invariant display map is incomplete")
    passed = sum(item.passed for item in evidence.invariants)
    secured = {item.name: item for item in evidence.secured_flows}

    def disposition(name: str) -> str:
        flow = secured[name]
        values = tuple(dict.fromkeys(item.disposition for item in flow.traces))
        if values == ("ACCEPTED",):
            return "ALLOWED"
        if values and all(value in {"DENIED_IN", "DENIED_OUT"} for value in values):
            return "BLOCKED"
        # A routing failure or mixed paths must not masquerade as ACL blocking.
        return "UNEXPECTED (" + ", ".join(values) + ")"

    lines = [
        "## :batfish: Profiled PR Batfish assurance",
        "",
        f"**Outcome:** `{_safe(evidence.outcome.value)}`",
        "",
        "### Topology",
        "",
        f"- {len(evidence.managed_network_nodes)} managed devices · "
        f"{len(evidence.modeled_nodes)} modeled nodes · "
        f"{evidence.total_layer1_edge_count} Layer-1 edges",
        "- Active services: routed underlay, OSPF, VLAN, ACL",
        "",
        "### Network state",
        "",
        f"- OSPF: {evidence.ospf_router_count} routers / "
        f"{evidence.ospf_adjacency_count} adjacencies",
        f"- VLAN: {evidence.vlan_count} VLANs / {evidence.vlan_gateway_count} gateways",
        f"- Security: {evidence.acl_policy_count} ACL / "
        f"{evidence.acl_rule_count} rules / "
        f"{evidence.acl_attachment_count} attachment",
        "",
        "### Security behavior",
        "",
        f"- USERS → SERVERS HTTPS — `{_safe(disposition('users_https'))}`",
        f"- USERS → SERVERS SSH — `{_safe(disposition('users_ssh'))}`",
        f"- USERS → SERVERS ICMP — `{_safe(disposition('users_icmp'))}`",
        f"- SERVERS → USERS — `{_safe(disposition('servers_to_users'))}`",
        "",
        "### Invariant summary",
        "",
    ]
    domains = tuple(
        dict.fromkeys(category for category, _ in INVARIANT_DISPLAY.values())
    )
    for domain in domains:
        checks = [
            item
            for item in evidence.invariants
            if INVARIANT_DISPLAY[item.name][0] == domain
        ]
        lines.append(f"- {domain}: {sum(item.passed for item in checks)}/{len(checks)}")
    lines.append(f"- Total: {passed}/{len(evidence.invariants)} passed")
    for domain in domains:
        failed = [
            item
            for item in evidence.invariants
            if not item.passed and INVARIANT_DISPLAY[item.name][0] == domain
        ]
        if failed:
            lines.extend(("", f"### Failed — {domain}", ""))
            lines.extend(
                f"- **{_safe(INVARIANT_DISPLAY[item.name][1])}** — `{_safe(item.name)}`"
                for item in failed
            )
    lines.extend(("", f"Evidence: `{_safe(evidence.digest)}`"))
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", required=True, type=Path)
    arguments = parser.parse_args()
    try:
        evidence = load_profiled_pr_evidence(arguments.evidence)
    except ValueError as error:
        print(f"profiled PR assurance annotation failed: {error}", file=sys.stderr)
        return 2
    print(render_annotation(evidence), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
