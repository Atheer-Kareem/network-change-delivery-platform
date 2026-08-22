"""Offline Batfish assurance boundary and bounded platform evidence."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import shutil
import stat
import tempfile
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime
from enum import StrEnum
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Sha256 = Annotated[str, StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$")]
MAX_FILES = 128
MAX_BYTES = 4 * 1024 * 1024


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
            {"files": [f.model_dump(mode="json") for f in self.files]},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()

    def calculated_digest(self) -> str:
        return "sha256:" + hashlib.sha256(self.digest_input()).hexdigest()

    def verify_digest(self) -> bool:
        return self.digest == self.calculated_digest()


class PreparedSnapshot:
    """Private frozen bytes and their manifest, submitted as one unit."""

    def __init__(self, root: Path, manifest: SnapshotManifest):
        self.root, self.manifest = root, manifest

    def __enter__(self) -> PreparedSnapshot:
        return self

    def __exit__(self, *_: object) -> None:
        shutil.rmtree(self.root, ignore_errors=True)


def _read_regular(path: Path) -> bytes:
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        size = os.fstat(fd).st_size
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError("snapshot contains a non-regular file")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(fd, min(65536, max(1, size - total)))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > MAX_BYTES:
                raise ValueError("snapshot exceeds bounded size limits")
        if total != size:
            raise ValueError("snapshot file changed during read")
        return b"".join(chunks)
    finally:
        os.close(fd)


def _manifest_from_bytes(files: Iterable[tuple[str, bytes]]) -> SnapshotManifest:
    entries = tuple(
        SnapshotFile(
            relative_path=p,
            sha256="sha256:" + hashlib.sha256(b).hexdigest(),
            size_bytes=len(b),
        )
        for p, b in files
    )
    if not entries:
        raise ValueError("snapshot config set is empty")
    provisional = SnapshotManifest(files=entries, digest="sha256:" + "0" * 64)
    return provisional.model_copy(update={"digest": provisional.calculated_digest()})


def prepare_snapshot(root: Path) -> PreparedSnapshot:
    """Read once, hash once, and stage exactly those bytes for Batfish."""
    if root.is_symlink() or not root.is_dir():
        raise ValueError("snapshot root must be a real directory")
    configs = root / "configs"
    if configs.is_symlink() or not configs.is_dir():
        raise ValueError("snapshot configs directory is required")
    source: list[tuple[str, bytes]] = []
    total = 0
    for path in sorted(configs.rglob("*"), key=lambda p: p.as_posix()):
        if path.is_symlink() or not path.is_file():
            raise ValueError("snapshot contains a symlink or non-regular file")
        relative = PurePosixPath(path.relative_to(configs).as_posix()).as_posix()
        content = _read_regular(path)
        source.append((relative, content))
        total += len(content)
        if len(source) > MAX_FILES or total > MAX_BYTES:
            raise ValueError("snapshot exceeds bounded size limits")
    return prepare_snapshot_from_bytes(source)


def prepare_snapshot_from_bytes(
    source: Iterable[tuple[str, bytes]],
) -> PreparedSnapshot:
    """Stage an already-frozen byte representation exactly once."""
    source = tuple(source)
    manifest = _manifest_from_bytes(source)
    staging = Path(tempfile.mkdtemp(prefix="ncdp-batfish-"))
    staging.chmod(0o700)
    (staging / "configs").mkdir(mode=0o700)
    for relative, content in source:
        target = staging / "configs" / relative
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(
            target,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        try:
            os.write(fd, content)
            os.fsync(fd)
        finally:
            os.close(fd)
    return PreparedSnapshot(staging, manifest)


def build_snapshot_manifest(root: Path) -> SnapshotManifest:
    with prepare_snapshot(root) as prepared:
        return prepared.manifest


class CriticalFlow(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    source_node: str
    source_ip: str
    destination_ip: str


class BatfishAssuranceIntent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    subject_digest: Sha256
    expected_nodes: tuple[str, ...] = Field(min_length=1)
    critical_flows: tuple[CriticalFlow, ...] = Field(min_length=1)
    require_no_differential_reachability: bool = True

    @model_validator(mode="after")
    def validate_contract(self) -> BatfishAssuranceIntent:
        if len(set(self.expected_nodes)) != len(self.expected_nodes):
            raise ValueError("expected_nodes must be unique")
        identities = {
            (f.source_node, f.source_ip, f.destination_ip) for f in self.critical_flows
        }
        if len(identities) != len(self.critical_flows):
            raise ValueError("critical_flows must be unique")
        if any(f.source_node not in self.expected_nodes for f in self.critical_flows):
            raise ValueError("critical flow source_node must be expected")
        for flow in self.critical_flows:
            try:
                src, dst = (
                    ipaddress.ip_address(flow.source_ip),
                    ipaddress.ip_address(flow.destination_ip),
                )
            except ValueError as exc:
                raise ValueError("critical flow addresses must be IPv4") from exc
            if src.version != 4 or dst.version != 4:
                raise ValueError("critical flow addresses must be IPv4")
        return self


class ParseFileResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    relative_path: str
    status: str


class ParseSummary(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    files: tuple[ParseFileResult, ...]
    nodes: tuple[str, ...]
    initialization_issue_count: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_unique_identities(self) -> ParseSummary:
        paths = [item.relative_path for item in self.files]
        if len(paths) != len(set(paths)):
            raise ValueError("parse file identities must be unique")
        if len(self.nodes) != len(set(self.nodes)):
            raise ValueError("node identities must be unique")
        return self

    @property
    def parse_status(self) -> dict[str, str]:
        return {f.relative_path: f.status for f in self.files}


class FlowResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    source_node: str
    source_ip: str
    destination_ip: str
    baseline_reachable: bool
    candidate_reachable: bool

    @property
    def identity(self) -> tuple[str, str, str]:
        return self.source_node, self.source_ip, self.destination_ip


class AssuranceObservation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    pybatfish_version: str
    batfish_version: str
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
    provider: Literal["batfish"] = "batfish"
    pybatfish_version: str | None = None
    batfish_version: str | None = None
    service_identity: str | None = None
    baseline_snapshot_digest: Sha256 | None = None
    candidate_snapshot_digest: Sha256 | None = None
    expected_nodes: tuple[str, ...]
    baseline_parse: ParseSummary | None = None
    candidate_parse: ParseSummary | None = None
    critical_flows: tuple[FlowResult, ...] = ()
    differential_changed_flow_count: int | None = Field(default=None, ge=0)
    invariants: tuple[InvariantResult, ...]
    failure_reason: str | None = None
    outcome: AssuranceOutcome

    @model_validator(mode="after")
    def validate_semantics(self) -> AssuranceEvidence:
        if self.outcome is AssuranceOutcome.BLOCKED:
            if not self.failure_reason or not any(
                not item.passed for item in self.invariants
            ):
                raise ValueError("BLOCKED evidence requires a bounded failure reason")
            return self
        required = (
            self.baseline_snapshot_digest,
            self.candidate_snapshot_digest,
            self.pybatfish_version,
            self.batfish_version,
            self.baseline_parse,
            self.candidate_parse,
            self.differential_changed_flow_count,
        )
        if any(value is None or value == "unknown" for value in required):
            raise ValueError("analyzed evidence is missing required observations")
        if self.failure_reason is not None or not self.invariants:
            raise ValueError("analyzed evidence has invalid failure semantics")
        if self.outcome is AssuranceOutcome.PASSED:
            if not self.critical_flows or not all(
                item.passed for item in self.invariants
            ):
                raise ValueError("PASSED evidence requires all invariants and flows")
        elif not any(not item.passed for item in self.invariants):
            raise ValueError("FAILED evidence requires a failed invariant")
        return self


class NetworkAssuranceProvider(Protocol):
    def analyze(
        self, baseline: Path, candidate: Path, intent: BatfishAssuranceIntent
    ) -> AssuranceObservation: ...


def _normalize_parse(rows: object, nodes: tuple[str, ...], issues: int) -> ParseSummary:
    seen: dict[str, str] = {}
    for _, row in rows.iterrows():
        name = PurePosixPath(str(row["File_Name"]).replace("\\", "/")).as_posix()
        if name.startswith("configs/"):
            name = name.removeprefix("configs/")
        if name in seen:
            raise AssuranceProviderError("duplicate Batfish parse result")
        seen[name] = str(row["Status"])
    return ParseSummary(
        files=tuple(
            ParseFileResult(relative_path=n, status=seen[n]) for n in sorted(seen)
        ),
        nodes=tuple(sorted(nodes)),
        initialization_issue_count=issues,
    )


def evaluate_assurance(
    intent: BatfishAssuranceIntent,
    baseline_manifest: SnapshotManifest,
    candidate_manifest: SnapshotManifest,
    observation: AssuranceObservation,
) -> AssuranceEvidence:
    expected = tuple(sorted(intent.expected_nodes))
    invariants: list[InvariantResult] = []
    for label, summary, manifest in (
        ("baseline", observation.baseline, baseline_manifest),
        ("candidate", observation.candidate, candidate_manifest),
    ):
        actual = set(summary.parse_status)
        expected_files = {f.relative_path for f in manifest.files}
        exact = actual == expected_files
        invariants.extend(
            (
                InvariantResult(
                    name=f"{label}_exact_parse_files",
                    passed=exact,
                    detail="parse results cover exactly manifest files",
                ),
                InvariantResult(
                    name=f"{label}_parse_status",
                    passed=exact
                    and all(s == "PASSED" for s in summary.parse_status.values()),
                    detail="every configuration parsed successfully",
                ),
                InvariantResult(
                    name=f"{label}_exact_nodes",
                    passed=tuple(sorted(summary.nodes)) == expected,
                    detail="parsed node set equals expected node set",
                ),
                InvariantResult(
                    name=f"{label}_initialization_issues",
                    passed=summary.initialization_issue_count == 0,
                    detail="initialization issue count is zero",
                ),
            )
        )
    requested = {
        (f.source_node, f.source_ip, f.destination_ip) for f in intent.critical_flows
    }
    observed = {f.identity for f in observation.flows}
    exact_flows = observed == requested and len(observed) == len(observation.flows)
    invariants.append(
        InvariantResult(
            name="exact_flow_observations",
            passed=exact_flows,
            detail="observations cover exactly requested critical flows",
        )
    )
    for flow in intent.critical_flows:
        result = next(
            (
                r
                for r in observation.flows
                if r.identity == (flow.source_node, flow.source_ip, flow.destination_ip)
            ),
            None,
        )
        invariants.append(
            InvariantResult(
                name=f"critical_flow:{flow.source_node}:{flow.destination_ip}",
                passed=result is not None
                and result.baseline_reachable
                and result.candidate_reachable,
                detail="critical flow is reachable in both snapshots",
            )
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
        if all(i.passed for i in invariants)
        else AssuranceOutcome.FAILED
    )
    return AssuranceEvidence(
        generated_at=datetime.now(UTC),
        subject_digest=intent.subject_digest,
        pybatfish_version=observation.pybatfish_version,
        batfish_version=observation.batfish_version,
        service_identity=observation.service_identity,
        baseline_snapshot_digest=baseline_manifest.digest,
        candidate_snapshot_digest=candidate_manifest.digest,
        expected_nodes=expected,
        baseline_parse=observation.baseline,
        candidate_parse=observation.candidate,
        critical_flows=observation.flows,
        differential_changed_flow_count=observation.differential_changed_flow_count,
        invariants=tuple(invariants),
        outcome=outcome,
    )


class BatfishAssuranceAdapter:
    def __init__(self, host: str | None = None) -> None:
        self.host = host or os.environ.get("NCDP_BATFISH_HOST", "127.0.0.1")

    def analyze(
        self, baseline: Path, candidate: Path, intent: BatfishAssuranceIntent
    ) -> AssuranceObservation:
        try:
            from pybatfish.client.session import Session

            pybatfish_version = version("pybatfish")
        except (ImportError, PackageNotFoundError):
            raise AssuranceProviderError(
                "Batfish provider dependency unavailable"
            ) from None
        with (
            prepare_snapshot(baseline) as frozen_baseline,
            prepare_snapshot(candidate) as frozen_candidate,
        ):
            namespace = "ncdp-6a-" + uuid.uuid4().hex
            baseline_name, candidate_name = (
                namespace + "-baseline",
                namespace + "-candidate",
            )
            try:
                session = Session(host=self.host, port=9996)
                session.init_snapshot(
                    str(frozen_baseline.root), name=baseline_name, overwrite=False
                )
                session.init_snapshot(
                    str(frozen_candidate.root), name=candidate_name, overwrite=False
                )

                def summary(name: str) -> ParseSummary:
                    parse = session.q.fileParseStatus().answer(snapshot=name).frame()
                    nodes = (
                        session.q.nodeProperties().answer(snapshot=name).frame()["Node"]
                    )
                    issues = session.q.initIssues().answer(snapshot=name).frame()
                    return _normalize_parse(
                        parse, tuple(str(n) for n in nodes), len(issues)
                    )

                baseline_summary, candidate_summary = (
                    summary(baseline_name),
                    summary(candidate_name),
                )
                flows: list[FlowResult] = []
                for flow in intent.critical_flows:
                    kwargs = {
                        "pathConstraints": {"startLocation": flow.source_node},
                        "headers": {
                            "srcIps": flow.source_ip,
                            "dstIps": flow.destination_ip,
                        },
                    }
                    b = (
                        session.q.reachability(**kwargs)
                        .answer(snapshot=baseline_name)
                        .frame()
                    )
                    c = (
                        session.q.reachability(**kwargs)
                        .answer(snapshot=candidate_name)
                        .frame()
                    )
                    flows.append(
                        FlowResult(
                            source_node=flow.source_node,
                            source_ip=flow.source_ip,
                            destination_ip=flow.destination_ip,
                            baseline_reachable=len(b) > 0,
                            candidate_reachable=len(c) > 0,
                        )
                    )
                changed = 0
                for flow in intent.critical_flows:
                    kwargs = {
                        "pathConstraints": {"startLocation": flow.source_node},
                        "headers": {
                            "srcIps": flow.source_ip,
                            "dstIps": flow.destination_ip,
                        },
                    }
                    changed += len(
                        session.q.differentialReachability(**kwargs)
                        .answer(
                            snapshot=candidate_name, reference_snapshot=baseline_name
                        )
                        .frame()
                    )
                server_version = str(session._get_bf_version())
                return AssuranceObservation(
                    pybatfish_version=pybatfish_version,
                    batfish_version=server_version,
                    service_identity=f"batfish:{server_version}",
                    baseline=baseline_summary,
                    candidate=candidate_summary,
                    flows=tuple(flows),
                    differential_changed_flow_count=changed,
                )
            except AssuranceProviderError:
                raise
            except Exception:
                raise AssuranceProviderError("Batfish service unavailable") from None
