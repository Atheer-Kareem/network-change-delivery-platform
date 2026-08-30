#!/usr/bin/env python3
"""Render a bounded Buildkite annotation from typed ephemeral-staging evidence."""

import argparse
import html
import os
import re
import stat
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_EVIDENCE_BYTES = 256 * 1024
EXPECTED_NODE_ROLES = (
    "system_bridge",
    "management_switch",
    "core_02",
    "edge_junos_01",
)
EXPECTED_LINK_ROLES = (
    "system_bridge_management",
    "management_core_02",
    "management_edge_junos_01",
    "core_02_edge_junos_01",
)
ROUTER_PRESENTATION = {
    "core_02": ("core-02", "192.168.4.30"),
    "edge_junos_01": ("edge-junos-01", "192.168.4.40"),
}
CHECKS = ("arp", "icmp", "tcp22", "tcp830")
READINESS_OPERATION_TIMEOUT_SECONDS = 1200
# The loop checks its deadline before its final bounded probes. Allow one polling
# interval for those probes to finish without changing or rewriting their duration.
READINESS_FINAL_PROBE_ALLOWANCE_SECONDS = 10
MAX_READINESS_PRESENTATION_SECONDS = (
    READINESS_OPERATION_TIMEOUT_SECONDS + READINESS_FINAL_PROBE_ALLOWANCE_SECONDS
)
Outcome = Literal["not_attempted", "attempted", "passed", "failed"]


class StagingAnnotationEvidence(BaseModel):
    """Strict presentation input matching the existing StagingEvidence schema."""

    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal["1", "2"]
    staging_run_id: str = Field(min_length=1, max_length=40)
    orchestrator: Literal["local", "buildkite"] = "local"
    pipeline_id: str | None = None
    build_id: str | None = None
    build_commit: str | None = None
    build_branch: str | None = None
    step_key: str | None = None
    job_id: str | None = None
    lab_id: str | None = None
    node_ids: dict[str, str] = Field(default_factory=dict)
    link_ids: dict[str, str] = Field(default_factory=dict)
    creation_outcome: Outcome = "not_attempted"
    readiness_outcome: Outcome = "not_attempted"
    readiness_seconds: dict[str, float] = Field(default_factory=dict)
    readiness_checks: dict[str, dict[str, str]] = Field(default_factory=dict)
    node_states: dict[str, str] = Field(default_factory=dict)
    netbox_device_ids: dict[str, str] = Field(default_factory=dict)
    credential_references: dict[str, str] = Field(default_factory=dict)
    ncdp_validation_outcome: Outcome = "not_attempted"
    ncdp_validation_attempts: dict[str, int] = Field(default_factory=dict)
    primary_failure: str | None = None
    destroy_outcome: Outcome = "not_attempted"
    cleanup_failure: str | None = None
    absence_verification_outcome: Outcome = "not_attempted"
    state_retirement_outcome: Outcome = "not_attempted"
    overall_result: Literal["running", "passed", "failed"] = "running"

    @model_validator(mode="after")
    def validate_presentation_contract(self) -> Self:
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,39}", self.staging_run_id):
            raise ValueError("staging run identity is invalid")
        if self.build_commit is not None and not re.fullmatch(
            r"[0-9a-f]{40}", self.build_commit
        ):
            raise ValueError("build commit is invalid")
        if self.lab_id is not None and not re.fullmatch(
            r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", self.lab_id
        ):
            raise ValueError("lab identity is invalid")
        expected_nodes = set(EXPECTED_NODE_ROLES)
        routers = set(ROUTER_PRESENTATION)
        for mapping in (
            self.node_ids,
            self.node_states,
            self.netbox_device_ids,
            self.credential_references,
        ):
            if not set(mapping).issubset(expected_nodes):
                raise ValueError("staging evidence contains an unknown node role")
        expected_links = set(EXPECTED_LINK_ROLES)
        if not set(self.link_ids).issubset(expected_links):
            raise ValueError("staging evidence contains an unknown link role")
        for mapping in (
            self.readiness_seconds,
            self.readiness_checks,
            self.ncdp_validation_attempts,
        ):
            if not set(mapping).issubset(routers):
                raise ValueError("staging evidence contains an unknown router role")
        for seconds in self.readiness_seconds.values():
            if seconds < 0 or seconds > MAX_READINESS_PRESENTATION_SECONDS:
                raise ValueError("readiness duration is outside the bounded contract")
        for checks in self.readiness_checks.values():
            if set(checks) != set(CHECKS) or any(
                value != "passed" for value in checks.values()
            ):
                raise ValueError("readiness checks are outside the bounded contract")
        if any(
            value < 1 or value > 13 for value in self.ncdp_validation_attempts.values()
        ):
            raise ValueError("validation attempts are outside the bounded contract")
        if self.overall_result == "passed":
            outcomes_complete = all(
                value == "passed"
                for value in (
                    self.creation_outcome,
                    self.readiness_outcome,
                    self.ncdp_validation_outcome,
                    self.destroy_outcome,
                    self.absence_verification_outcome,
                    self.state_retirement_outcome,
                )
            )
            observations_complete = all(
                (
                    set(self.node_ids) == expected_nodes,
                    set(self.link_ids) == expected_links,
                    set(self.readiness_seconds) == routers,
                    set(self.readiness_checks) == routers,
                    set(self.ncdp_validation_attempts) == routers,
                    self.primary_failure is None,
                    self.cleanup_failure is None,
                )
            )
            if not outcomes_complete or not observations_complete:
                raise ValueError("passed staging evidence is incomplete")
        return self


def _safe(value: object) -> str:
    return (
        html.escape(str(value), quote=True)
        .replace("|", "&#124;")
        .replace("`", "&#96;")
        .replace("\r", " ")
        .replace("\n", " ")
    )


def load_evidence(path: Path) -> StagingAnnotationEvidence:
    if path.is_symlink():
        raise ValueError("staging evidence symlink rejected")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError("staging evidence is not a regular file")
        if metadata.st_size > MAX_EVIDENCE_BYTES:
            raise ValueError("staging evidence exceeds the presentation limit")
        with os.fdopen(descriptor, encoding="utf-8") as stream:
            descriptor = -1
            return StagingAnnotationEvidence.model_validate_json(stream.read())
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _result(value: str) -> str:
    return value.replace("_", " ").upper()


def render_annotation(evidence: StagingAnnotationEvidence) -> str:
    core_attempts = evidence.ncdp_validation_attempts.get("core_02", "NOT OBSERVED")
    edge_attempts = evidence.ncdp_validation_attempts.get(
        "edge_junos_01", "NOT OBSERVED"
    )
    lines = [
        "## :cloud: Ephemeral CML staging",
        "",
        f"**Overall result:** `{_safe(_result(evidence.overall_result))}`",
        "",
        "| Bound field | Value |",
        "|---|---|",
        f"| Staging run ID | `{_safe(evidence.staging_run_id)}` |",
        f"| Orchestrator | `{_safe(evidence.orchestrator)}` |",
        f"| Build commit | `{_safe(evidence.build_commit or 'NOT AVAILABLE')}` |",
        f"| Lab ID | `{_safe(evidence.lab_id or 'NOT AVAILABLE')}` |",
        (f"| Expected logical nodes | `{_safe(', '.join(EXPECTED_NODE_ROLES))}` |"),
        "",
        "### Lifecycle",
        "",
        "| Phase | Result | Evidence |",
        "|---|---|---|",
        (
            "| Create + topology/Day-0 | "
            f"**{_safe(_result(evidence.creation_outcome))}** | "
            f"nodes={len(evidence.node_ids)}; links={len(evidence.link_ids)} |"
        ),
        (
            "| Device readiness | "
            f"**{_safe(_result(evidence.readiness_outcome))}** | "
            f"router observations={len(evidence.readiness_seconds)} |"
        ),
        (
            "| NCDP validation · READ-ONLY | "
            f"**{_safe(_result(evidence.ncdp_validation_outcome))}** | "
            f"attempted routers={len(evidence.ncdp_validation_attempts)} |"
        ),
        (
            "| Terraform destroy | "
            f"**{_safe(_result(evidence.destroy_outcome))}** | "
            "exact lifecycle cleanup |"
        ),
        (
            "| Independent absence verification | "
            f"**{_safe(_result(evidence.absence_verification_outcome))}** | "
            "CML identity + title + Terraform state |"
        ),
        (
            "| Run-scoped state retirement | "
            f"**{_safe(_result(evidence.state_retirement_outcome))}** | "
            "private run root |"
        ),
        "",
        "### Router readiness",
        "",
        "| Role / hostname | Endpoint | Seconds | ARP | ICMP | TCP/22 | TCP/830 |",
        "|---|---|---:|---|---|---|---|",
    ]
    for role, (hostname, endpoint) in ROUTER_PRESENTATION.items():
        checks = evidence.readiness_checks.get(role, {})
        seconds = evidence.readiness_seconds.get(role, "NOT OBSERVED")
        lines.append(
            f"| `{_safe(role)} / {_safe(hostname)}` | `{_safe(endpoint)}` | "
            f"`{_safe(seconds)}` | "
            + " | ".join(
                f"**{_safe(_result(checks.get(check, 'not observed')))}**"
                for check in CHECKS
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "### NCDP read-only validation",
            "",
            "| Target | Interface | Attempts | Mode |",
            "|---|---|---:|---|",
            (
                "| `core-02` | `GigabitEthernet2` | "
                f"`{_safe(core_attempts)}` "
                "| **READ-ONLY** |"
            ),
            (
                "| `edge-junos-01` | `ge-0/0/2` | "
                f"`{_safe(edge_attempts)}` "
                "| **READ-ONLY** |"
            ),
            "",
            "### Failure classification",
            "",
            (
                "- PRIMARY FAILURE: "
                f"**{'PRESENT' if evidence.primary_failure else 'NONE'}**"
            ),
            (
                "- CLEANUP FAILURE: "
                f"**{'PRESENT' if evidence.cleanup_failure else 'NONE'}**"
            ),
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", required=True, type=Path)
    arguments = parser.parse_args()
    print(render_annotation(load_evidence(arguments.evidence)), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
