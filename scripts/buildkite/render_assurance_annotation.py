#!/usr/bin/env python3
"""Render a strictly allowlisted Buildkite summary from typed assurance evidence."""

from __future__ import annotations

import argparse
import html
import os
import stat
from pathlib import Path

from network_change_delivery.plan_assurance import PlanAssuranceRecord


def _safe(value: object) -> str:
    return (
        html.escape(str(value), quote=True)
        .replace("|", "&#124;")
        .replace("`", "&#96;")
        .replace("\r", " ")
        .replace("\n", " ")
    )


def load_record(path: Path) -> PlanAssuranceRecord:
    if path.is_symlink():
        raise ValueError("assurance evidence symlink rejected")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError("assurance evidence is not a regular file")
        with os.fdopen(descriptor, encoding="utf-8") as stream:
            descriptor = -1
            record = PlanAssuranceRecord.model_validate_json(stream.read())
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if not record.verify_digest():
        raise ValueError("assurance record digest verification failed")
    return record


def render_annotation(record: PlanAssuranceRecord) -> str:
    observation = record.assurance
    observed_flows = (
        {flow.identity: flow for flow in observation.critical_flows}
        if observation
        else {}
    )
    lines = [
        "## :fish: Batfish plan assurance",
        "",
        f"**Outcome:** `{_safe(record.outcome.value)}`",
        "",
        "| Bound field | Value |",
        "|---|---|",
        f"| Change ID | `{_safe(record.subject.change_id)}` |",
        f"| Plan digest | `{_safe(record.subject.plan_digest)}` |",
        f"| Policy digest | `{_safe(record.policy_digest)}` |",
        f"| Assurance record digest | `{_safe(record.digest)}` |",
        (
            "| Baseline snapshot digest | "
            f"`{_safe(record.baseline_snapshot_digest or 'NOT AVAILABLE')}` |"
        ),
        (
            "| Candidate snapshot digest | "
            f"`{_safe(record.candidate_snapshot_digest or 'NOT AVAILABLE')}` |"
        ),
        "",
        "### Expected nodes",
        "",
        *[f"- `{_safe(node)}`" for node in record.policy.expected_nodes],
        "",
        "### Critical flows",
        "",
        "| Source node | Source IP | Destination IP | Baseline | Candidate |",
        "|---|---|---|---|---|",
    ]
    for flow in record.policy.critical_flows:
        identity = (flow.source_node, flow.source_ip, flow.destination_ip)
        observed = observed_flows.get(identity)
        baseline = (
            ("PASS" if observed.baseline_reachable else "FAIL")
            if observed
            else "NOT OBSERVED"
        )
        candidate = (
            ("PASS" if observed.candidate_reachable else "FAIL")
            if observed
            else "NOT OBSERVED"
        )
        lines.append(
            "| "
            f"`{_safe(flow.source_node)}` | `{_safe(flow.source_ip)}` | "
            f"`{_safe(flow.destination_ip)}` | **{baseline}** | **{candidate}** |"
        )
    changed = (
        observation.differential_changed_flow_count
        if observation and observation.differential_changed_flow_count is not None
        else "NOT OBSERVED"
    )
    lines.extend(
        [
            "",
            f"**Differential changed-flow count:** `{_safe(changed)}`",
            "",
            "### Invariants",
            "",
        ]
    )
    if observation:
        lines.extend(
            f"- **{'PASS' if invariant.passed else 'FAIL'}** — "
            f"`{_safe(invariant.name)}`"
            for invariant in observation.invariants
        )
    else:
        lines.append("- No analyzed invariant results were available.")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", required=True, type=Path)
    arguments = parser.parse_args()
    print(render_annotation(load_record(arguments.evidence)), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
