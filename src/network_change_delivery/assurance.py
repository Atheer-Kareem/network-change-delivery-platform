"""Offline Batfish assurance boundary and platform-owned evidence."""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Annotated, Protocol

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Sha256 = Annotated[str, StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$")]


class AssuranceProviderError(RuntimeError):
    """Bounded provider failure without raw service output."""


class AssuranceOutcome(StrEnum):
    PASSED = "PASSED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"


class SnapshotFile(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    relative_path: str
    sha256: Sha256
    size_bytes: int = Field(ge=0)


class SnapshotManifest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    files: tuple[SnapshotFile, ...]
    digest: Sha256

    def digest_input(self) -> bytes:
        return json.dumps(
            {"files": [item.model_dump(mode="json") for item in self.files]},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()

    def calculated_digest(self) -> str:
        return "sha256:" + hashlib.sha256(self.digest_input()).hexdigest()

    def verify_digest(self) -> bool:
        return self.digest == self.calculated_digest()


class CriticalFlow(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    source_node: str
    source_ip: str
    destination_ip: str


class BatfishAssuranceIntent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    subject_digest: Sha256
    expected_nodes: tuple[str, ...]
    critical_flows: tuple[CriticalFlow, ...]
    require_no_differential_reachability: bool = True


class ParseSummary(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    nodes: tuple[str, ...]
    parse_status: Mapping[str, str]
    initialization_issue_count: int = Field(ge=0)


class FlowResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    source_node: str
    source_ip: str
    destination_ip: str
    baseline_reachable: bool
    candidate_reachable: bool


class AssuranceObservation(BaseModel):
    """Normalized observations returned by an assurance provider."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    pybatfish_version: str
    service_identity: str | None = None
    baseline: ParseSummary
    candidate: ParseSummary
    flows: tuple[FlowResult, ...]
    differential_changed_flow_count: int = Field(ge=0)


class InvariantResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    name: str
    passed: bool
    detail: str


class AssuranceEvidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    generated_at: datetime
    subject_digest: Sha256
    provider: str = "batfish"
    pybatfish_version: str
    service_identity: str | None = None
    baseline_snapshot_digest: Sha256
    candidate_snapshot_digest: Sha256
    expected_nodes: tuple[str, ...]
    baseline_parse: ParseSummary
    candidate_parse: ParseSummary
    baseline_initialization_issue_count: int = Field(ge=0)
    candidate_initialization_issue_count: int = Field(ge=0)
    critical_flows: tuple[FlowResult, ...]
    differential_changed_flow_count: int = Field(ge=0)
    invariants: tuple[InvariantResult, ...]
    outcome: AssuranceOutcome


class NetworkAssuranceProvider(Protocol):
    def analyze(
        self,
        baseline: Path,
        candidate: Path,
        intent: BatfishAssuranceIntent,
    ) -> AssuranceObservation:
        """Analyze snapshots and return normalized, bounded observations."""


MAX_FILES = 128
MAX_BYTES = 4 * 1024 * 1024
_CONFIG_NAME = re.compile(r"^[^/\\]+$")


def build_snapshot_manifest(root: Path) -> SnapshotManifest:
    """Validate a configs-only snapshot and build its deterministic manifest."""
    if not root.is_dir() or root.is_symlink():
        raise ValueError("snapshot root must be a real directory")
    configs = root / "configs"
    if not configs.is_dir() or configs.is_symlink():
        raise ValueError("snapshot configs directory is required")
    entries: list[SnapshotFile] = []
    total = 0
    for path in sorted(configs.rglob("*"), key=lambda item: item.as_posix()):
        if path.is_symlink() or not path.is_file():
            raise ValueError("snapshot contains a symlink or non-regular file")
        relative = PurePosixPath(path.relative_to(configs).as_posix())
        if any(part in {"", ".", ".."} for part in relative.parts):
            raise ValueError("snapshot path is invalid")
        size = path.stat().st_size
        total += size
        if len(entries) >= MAX_FILES or total > MAX_BYTES:
            raise ValueError("snapshot exceeds bounded size limits")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        entries.append(
            SnapshotFile(
                relative_path=relative.as_posix(),
                sha256="sha256:" + digest,
                size_bytes=size,
            )
        )
    if not entries:
        raise ValueError("snapshot config set is empty")
    provisional = SnapshotManifest(files=tuple(entries), digest="sha256:" + "0" * 64)
    return provisional.model_copy(update={"digest": provisional.calculated_digest()})


def evaluate_assurance(
    intent: BatfishAssuranceIntent,
    baseline_manifest: SnapshotManifest,
    candidate_manifest: SnapshotManifest,
    observation: AssuranceObservation,
) -> AssuranceEvidence:
    """Apply assurance policy to normalized provider observations."""
    invariants: list[InvariantResult] = []
    expected = tuple(sorted(intent.expected_nodes))
    for label, summary in (
        ("baseline", observation.baseline),
        ("candidate", observation.candidate),
    ):
        invariants.append(
            InvariantResult(
                name=f"{label}_parse_status",
                passed=all(
                    value == "PASSED" for value in summary.parse_status.values()
                ),
                detail="every configuration parsed successfully",
            )
        )
        invariants.append(
            InvariantResult(
                name=f"{label}_exact_nodes",
                passed=tuple(sorted(summary.nodes)) == expected,
                detail="parsed node set equals expected node set",
            )
        )
        invariants.append(
            InvariantResult(
                name=f"{label}_initialization_issues",
                passed=summary.initialization_issue_count == 0,
                detail="initialization issue count is zero",
            )
        )
    invariants.extend(
        InvariantResult(
            name=f"critical_flow:{flow.source_node}:{flow.destination_ip}",
            passed=flow.baseline_reachable and flow.candidate_reachable,
            detail="critical flow is reachable in both snapshots",
        )
        for flow in observation.flows
    )
    if intent.require_no_differential_reachability:
        invariants.append(
            InvariantResult(
                name="differential_reachability",
                passed=observation.differential_changed_flow_count == 0,
                detail="no differential reachability rows changed",
            )
        )
    outcome = (
        AssuranceOutcome.PASSED
        if all(item.passed for item in invariants)
        else AssuranceOutcome.FAILED
    )
    return AssuranceEvidence(
        generated_at=datetime.now(UTC),
        subject_digest=intent.subject_digest,
        pybatfish_version=observation.pybatfish_version,
        service_identity=observation.service_identity,
        baseline_snapshot_digest=baseline_manifest.digest,
        candidate_snapshot_digest=candidate_manifest.digest,
        expected_nodes=expected,
        baseline_parse=observation.baseline,
        candidate_parse=observation.candidate,
        baseline_initialization_issue_count=observation.baseline.initialization_issue_count,
        candidate_initialization_issue_count=observation.candidate.initialization_issue_count,
        critical_flows=observation.flows,
        differential_changed_flow_count=observation.differential_changed_flow_count,
        invariants=tuple(invariants),
        outcome=outcome,
    )


class BatfishAssuranceAdapter:
    """Thin adapter; raw pybatfish objects never cross the provider boundary."""

    def __init__(self, host: str | None = None) -> None:
        self.host = host or os.environ.get("NCDP_BATFISH_HOST", "127.0.0.1")

    def analyze(
        self, baseline: Path, candidate: Path, intent: BatfishAssuranceIntent
    ) -> AssuranceObservation:
        try:
            from pybatfish.client.session import Session
        except ImportError:
            raise AssuranceProviderError(
                "Batfish provider dependency unavailable"
            ) from None
        try:
            session = Session(host=self.host, port=9996)
            baseline_name = "ncdp-6a-baseline"
            candidate_name = "ncdp-6a-candidate"
            session.init_snapshot(str(baseline), name=baseline_name, overwrite=True)
            session.init_snapshot(str(candidate), name=candidate_name, overwrite=True)

            def summary(snapshot_name: str) -> ParseSummary:
                parse = (
                    session.q.fileParseStatus().answer(snapshot=snapshot_name).frame()
                )
                statuses = {
                    str(row["File_Name"]): str(row["Status"])
                    for _, row in parse.iterrows()
                }
                nodes = frozenset(
                    str(node)
                    for node in session.q.nodeProperties()
                    .answer(snapshot=snapshot_name)
                    .frame()["Node"]
                )
                issues = session.q.initIssues().answer(snapshot=snapshot_name).frame()
                return ParseSummary(
                    parse_status=statuses,
                    nodes=nodes,
                    initialization_issue_count=len(issues),
                )

            def flow_query(question_name: str, snapshot_name: str, **kwargs):
                question = getattr(session.q, question_name)(**kwargs)
                return question.answer(snapshot=snapshot_name).frame()

            baseline_summary = summary(baseline_name)
            candidate_summary = summary(candidate_name)
            flows: list[FlowResult] = []
            for flow in intent.critical_flows:
                kwargs = {
                    "pathConstraints": {
                        "startLocation": flow.source_node,
                    },
                    "headers": {
                        "srcIps": flow.source_ip,
                        "dstIps": flow.destination_ip,
                    },
                }
                baseline_rows = flow_query("reachability", baseline_name, **kwargs)
                candidate_rows = flow_query("reachability", candidate_name, **kwargs)
                flows.append(
                    FlowResult(
                        source_node=flow.source_node,
                        source_ip=flow.source_ip,
                        destination_ip=flow.destination_ip,
                        baseline_reachable=len(baseline_rows) > 0,
                        candidate_reachable=len(candidate_rows) > 0,
                    )
                )

            changed = 0
            for flow in intent.critical_flows:
                kwargs = {
                    "pathConstraints": {
                        "startLocation": flow.source_node,
                    },
                    "headers": {
                        "srcIps": flow.source_ip,
                        "dstIps": flow.destination_ip,
                    },
                }
                differential = session.q.differentialReachability(**kwargs)
                changed += len(
                    differential.answer(
                        snapshot=candidate_name, reference_snapshot=baseline_name
                    ).frame()
                )
            version = str(session._get_bf_version())
            return AssuranceObservation(
                pybatfish_version=version,
                service_identity=f"batfish:{version}",
                baseline=baseline_summary,
                candidate=candidate_summary,
                flows=tuple(flows),
                differential_changed_flow_count=changed,
            )
        except AssuranceProviderError:
            raise
        except Exception:
            raise AssuranceProviderError("Batfish service unavailable") from None
