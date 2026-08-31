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
        f"| Nodes | `{len(evidence.candidate_nodes)}` |",
        f"| OSPF routers | `{evidence.ospf_router_count}` |",
        f"| OSPF adjacencies | `{evidence.ospf_adjacency_count}` |",
        f"| Invariants | `{passed} / {len(evidence.invariants)} passed` |",
        f"| Candidate | `{_safe(evidence.candidate_snapshot_digest)}` |",
        f"| Evidence | `{_safe(evidence.digest)}` |",
        "",
        "### Candidate nodes",
        "",
        *[f"- `{_safe(node)}`" for node in evidence.candidate_nodes],
        "",
        "### Service subjects",
        "",
        *[
            f"- `{_safe(subject.service.value)}` — `{_safe(subject.digest)}`"
            for subject in evidence.service_subjects
        ],
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
