#!/usr/bin/env python3
"""Render a strict human summary for profiled PR Batfish evidence."""

from __future__ import annotations

import argparse
import html
import sys
from pathlib import Path

from network_change_delivery.profiled_pr_assurance import (
    ProfiledPrAssuranceEvidence,
    load_profiled_pr_evidence,
)


def _safe(value: object) -> str:
    return (
        html.escape(str(value), quote=True)
        .replace("|", "&#124;")
        .replace("`", "&#96;")
        .replace("\r", " ")
        .replace("\n", " ")
    )


def render_annotation(evidence: ProfiledPrAssuranceEvidence) -> str:
    passed = sum(item.passed for item in evidence.invariants)
    secured = {item.name: item for item in evidence.secured_flows}

    def disposition(name: str) -> str:
        flow = secured[name]
        values = tuple(dict.fromkeys(item.disposition for item in flow.traces))
        return ", ".join(values)

    lines = [
        "## :fish: Profiled PR Batfish assurance",
        "",
        f"**Outcome:** `{_safe(evidence.outcome.value)}`",
        "",
        "| Bound field | Value |",
        "|---|---|",
        f"| Architecture | `{_safe(evidence.architecture_identity)}` |",
        (
            "| Service stack | `"
            + ", ".join(_safe(item.value) for item in evidence.active_service_stack)
            + "` |"
        ),
        f"| Managed network nodes | `{len(evidence.managed_network_nodes)}` |",
        f"| Assurance fixture hosts | `{len(evidence.assurance_fixture_hosts)}` |",
        f"| Modeled nodes | `{len(evidence.modeled_nodes)}` |",
        f"| OSPF routers | `{evidence.ospf_router_count}` |",
        f"| OSPF adjacencies | `{evidence.ospf_adjacency_count}` |",
        f"| VLANs | `{evidence.vlan_count}` |",
        f"| Gateways | `{evidence.vlan_gateway_count}` |",
        f"| ACL policies | `{evidence.acl_policy_count}` |",
        f"| ACL rules | `{evidence.acl_rule_count}` |",
        f"| ACL attachments | `{evidence.acl_attachment_count}` |",
        "| ACL attachment | `core-02/GigabitEthernet3.20 out` |",
        (
            "| Layer-1 edges | `"
            f"{evidence.infrastructure_layer1_edge_count} infrastructure + "
            f"{evidence.assurance_fixture_edge_count} assurance = "
            f"{evidence.total_layer1_edge_count}` |"
        ),
        f"| Invariants | `{passed} / {len(evidence.invariants)} passed` |",
        (
            "| Behavioral baseline | `"
            f"{_safe(evidence.behavioral_baseline_candidate_digest)}` |"
        ),
        f"| Secured candidate | `{_safe(evidence.secured_candidate_digest)}` |",
        f"| Evidence | `{_safe(evidence.digest)}` |",
        "",
        "### Managed network nodes",
        "",
        *[f"- `{_safe(node)}`" for node in evidence.managed_network_nodes],
        "",
        "### Batfish-only assurance hosts",
        "",
        *[f"- `{_safe(node)}`" for node in evidence.assurance_fixture_hosts],
        "",
        "### Service subjects",
        "",
        *[
            f"- `{_safe(subject.service.value)}` — `{_safe(subject.digest)}`"
            for subject in evidence.service_subjects
        ],
        "",
        "### Security behavior",
        "",
        f"- USERS → SERVERS HTTPS — `{_safe(disposition('users_https'))}`",
        f"- USERS → SERVERS SSH — `{_safe(disposition('users_ssh'))}`",
        f"- USERS → SERVERS ICMP — `{_safe(disposition('users_icmp'))}`",
        f"- SERVERS → USERS — `{_safe(disposition('servers_to_users'))}`",
        "",
        "### Invariants",
        "",
        *[
            f"- **{'PASS' if invariant.passed else 'FAIL'}** — "
            f"`{_safe(invariant.name)}`"
            for invariant in evidence.invariants
        ],
    ]
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
