"""Exact plan-bound Batfish assurance for Increment 6B."""

from __future__ import annotations

import hashlib
import json
import re
import shlex
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from network_change_delivery.assurance import (
    AssuranceEvidence,
    AssuranceObservation,
    AssuranceOutcome,
    AssuranceProviderError,
    BatfishAssuranceAdapter,
    BatfishAssuranceIntent,
    CriticalFlow,
    PreparedSnapshot,
    Sha256,
    evaluate_assurance,
    prepare_snapshot,
    prepare_snapshot_from_bytes,
)
from network_change_delivery.models import (
    DeploymentPlan,
    FleetDeploymentPlan,
)


class PlanAssuranceError(ValueError):
    """Bounded fail-closed plan or candidate derivation failure."""


class PlanAssuranceSubject(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    plan_type: Literal["deployment_plan", "fleet_deployment_plan"]
    schema_version: Literal["1"]
    change_id: str
    plan_digest: Sha256
    deployable_child_digests: tuple[Sha256, ...] = ()


class BatfishAssurancePolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    expected_nodes: tuple[str, ...] = Field(min_length=1)
    critical_flows: tuple[CriticalFlow, ...] = Field(min_length=1)
    require_no_differential_reachability: bool = True

    @model_validator(mode="after")
    def validate_policy(self) -> BatfishAssurancePolicy:
        if len(set(self.expected_nodes)) != len(self.expected_nodes):
            raise ValueError("policy expected_nodes must be unique")
        identities = set()
        for flow in self.critical_flows:
            identity = (flow.source_node, flow.source_ip, flow.destination_ip)
            if identity in identities:
                raise ValueError("policy critical flows must be unique")
            identities.add(identity)
            if flow.source_node not in self.expected_nodes:
                raise ValueError("policy flow source node is not expected")
            import ipaddress

            if (
                ipaddress.ip_address(flow.source_ip).version != 4
                or ipaddress.ip_address(flow.destination_ip).version != 4
            ):
                raise ValueError("policy flow addresses must be IPv4")
        return self

    def digest_input(self) -> bytes:
        return json.dumps(
            self.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        ).encode()

    def calculated_digest(self) -> str:
        return "sha256:" + hashlib.sha256(self.digest_input()).hexdigest()


class PlanSnapshotMutation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    target: str
    platform: str
    interface: str
    config_relative_path: str
    classification: str
    current_description: str | None
    desired_description: str
    child_plan_digest: Sha256 | None = None
    changed: bool


class BaselineConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    hostname: str
    platform: Literal["cisco_iosxe", "junos"]
    relative_path: str
    text: str


class PlanAssuranceRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal["1"] = "1"
    generated_at: datetime
    subject: PlanAssuranceSubject
    policy: BatfishAssurancePolicy
    policy_digest: Sha256
    baseline_snapshot_digest: Sha256 | None = None
    candidate_snapshot_digest: Sha256 | None = None
    candidate_derivation: tuple[PlanSnapshotMutation, ...] = ()
    assurance: AssuranceEvidence | None = None
    failure_reason: str | None = None
    outcome: AssuranceOutcome
    digest: Sha256

    @model_validator(mode="after")
    def validate_record(self) -> PlanAssuranceRecord:
        if self.policy_digest != self.policy.calculated_digest():
            raise ValueError("policy digest mismatch")
        if self.outcome is AssuranceOutcome.BLOCKED:
            if not self.failure_reason or self.assurance is not None:
                raise ValueError("blocked record requires failure reason")
            return self
        if (
            self.failure_reason
            or self.assurance is None
            or not self.baseline_snapshot_digest
            or not self.candidate_snapshot_digest
            or not self.candidate_derivation
        ):
            raise ValueError("completed record is incomplete")
        if self.assurance.outcome is not self.outcome:
            raise ValueError("outer and inner outcomes differ")
        if self.assurance.subject_digest != self.subject.plan_digest:
            raise ValueError("inner subject differs from plan")
        if (
            self.assurance.baseline_snapshot_digest != self.baseline_snapshot_digest
            or self.assurance.candidate_snapshot_digest
            != self.candidate_snapshot_digest
        ):
            raise ValueError("inner snapshot digest differs")
        if tuple(self.assurance.expected_nodes) != tuple(
            sorted(self.policy.expected_nodes)
        ):
            raise ValueError("inner policy nodes differ")
        if self.outcome is AssuranceOutcome.PASSED and not all(
            i.passed for i in self.assurance.invariants
        ):
            raise ValueError("passed record contains failed invariant")
        if self.outcome is AssuranceOutcome.FAILED and not any(
            not i.passed for i in self.assurance.invariants
        ):
            raise ValueError("failed record has no failed invariant")
        return self

    def digest_input(self) -> bytes:
        return json.dumps(
            self.model_dump(mode="json", exclude={"digest"}),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()

    def calculated_digest(self) -> str:
        return "sha256:" + hashlib.sha256(self.digest_input()).hexdigest()

    def verify_digest(self) -> bool:
        return self.digest == self.calculated_digest()


def load_plan(path: Path) -> DeploymentPlan | FleetDeploymentPlan:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise PlanAssuranceError("plan must be a JSON object")
    try:
        plan = (
            FleetDeploymentPlan.model_validate(payload)
            if "members" in payload
            else DeploymentPlan.model_validate(payload)
        )
    except Exception as exc:
        raise PlanAssuranceError("invalid assurance plan") from exc
    if not plan.verify_digest():
        raise PlanAssuranceError("assurance plan digest verification failed")
    return plan


def subject_from_plan(
    plan: DeploymentPlan | FleetDeploymentPlan,
) -> PlanAssuranceSubject:
    if isinstance(plan, FleetDeploymentPlan):
        return PlanAssuranceSubject(
            plan_type="fleet_deployment_plan",
            schema_version=plan.schema_version,
            change_id=plan.change_id,
            plan_digest=plan.digest,
            deployable_child_digests=tuple(
                member.child_plan.digest
                for member in plan.members
                if member.child_plan is not None
            ),
        )
    return PlanAssuranceSubject(
        plan_type="deployment_plan",
        schema_version=plan.schema_version,
        change_id=plan.change_id,
        plan_digest=plan.digest,
    )


def policy_to_intent(
    policy: BatfishAssurancePolicy, subject: PlanAssuranceSubject
) -> BatfishAssuranceIntent:
    return BatfishAssuranceIntent(
        subject_digest=subject.plan_digest,
        expected_nodes=tuple(sorted(policy.expected_nodes)),
        critical_flows=policy.critical_flows,
        require_no_differential_reachability=policy.require_no_differential_reachability,
    )


def _hostname_index(root: Path) -> dict[str, BaselineConfig]:
    result: dict[str, BaselineConfig] = {}
    for path in sorted((root / "configs").rglob("*"), key=lambda p: p.as_posix()):
        if not path.is_file() or path.is_symlink():
            continue
        text = path.read_text(encoding="utf-8")
        cisco = re.findall(r"^hostname\s+(\S+)\s*$", text, re.MULTILINE)
        junos = re.findall(r"^set system host-name\s+(\S+)\s*$", text, re.MULTILINE)
        if (len(cisco) == 1 and junos) or (len(cisco) != 1 and len(junos) != 1):
            raise PlanAssuranceError("baseline hostname identity is ambiguous")
        hostname, platform = (
            (cisco[0], "cisco_iosxe") if len(cisco) == 1 else (junos[0], "junos")
        )
        if hostname in result:
            raise PlanAssuranceError("duplicate baseline hostname")
        result[hostname] = BaselineConfig(
            hostname=hostname,
            platform=platform,
            relative_path=path.relative_to(root / "configs").as_posix(),
            text=text,
        )
    return result


def _transform_cisco(
    text: str, interface: str, current: str | None, desired: str
) -> tuple[str, bool]:
    lines = text.splitlines(keepends=True)
    starts = [
        i for i, line in enumerate(lines) if line.strip() == f"interface {interface}"
    ]
    if len(starts) != 1:
        raise PlanAssuranceError("Cisco target interface is missing or ambiguous")
    start = starts[0]
    end = next(
        (
            i
            for i in range(start + 1, len(lines))
            if lines[i] and not lines[i][0].isspace()
        ),
        len(lines),
    )
    desc = [
        i for i in range(start + 1, end) if lines[i].strip().startswith("description ")
    ]
    if (
        len(desc) > 1
        or (current is None and desc)
        or (
            current is not None
            and (not desc or lines[desc[0]].strip() != f"description {current}")
        )
    ):
        raise PlanAssuranceError("Cisco baseline description mismatch or ambiguous")
    newline = " description " + desired + "\n"
    if desc:
        lines[desc[0]] = newline
    else:
        insert = end
        lines.insert(insert, newline)
    return "".join(lines), True


def _transform_junos(
    text: str, interface: str, current: str | None, desired: str
) -> tuple[str, bool]:
    lines = text.splitlines(keepends=True)
    prefix = f"set interfaces {interface} description "
    interface_lines = [
        line
        for line in lines
        if line.startswith(f"set interfaces {interface} ")
        or line.strip() == f"set interfaces {interface}"
    ]
    if not interface_lines:
        raise PlanAssuranceError("Junos target interface is absent")
    indexes: list[int] = []
    parsed_descriptions: list[str] = []
    for i, line in enumerate(lines):
        if not line.startswith(prefix):
            continue
        try:
            tokens = shlex.split(line.strip())
        except ValueError as exc:
            raise PlanAssuranceError(
                "Junos description encoding is unsupported"
            ) from exc
        if len(tokens) < 5 or tokens[:4] != [
            "set",
            "interfaces",
            interface,
            "description",
        ]:
            continue
        indexes.append(i)
        parsed_descriptions.append(" ".join(tokens[4:]))
    if len(indexes) > 1:
        raise PlanAssuranceError("Junos description is ambiguous")
    if current is None and indexes:
        raise PlanAssuranceError("Junos baseline description mismatch")
    if current is not None and (not indexes or parsed_descriptions[0] != current):
        raise PlanAssuranceError("Junos baseline description mismatch")
    value = (
        desired if re.fullmatch(r"[A-Za-z0-9_.:/-]+", desired) else json.dumps(desired)
    )
    line = prefix + value + "\n"
    if indexes:
        lines[indexes[0]] = line
    else:
        lines.append(line)
    return "".join(lines), True


def materialize_candidate(
    prepared: PreparedSnapshot, plan: DeploymentPlan | FleetDeploymentPlan
) -> tuple[PreparedSnapshot, tuple[PlanSnapshotMutation, ...]]:
    index = _hostname_index(prepared.root)
    members = (
        (plan,)
        if isinstance(plan, DeploymentPlan)
        else tuple(member.child_plan or member for member in plan.members)
    )
    records: list[PlanSnapshotMutation] = []
    replacements = {
        item.relative_path: (
            prepared.root / "configs" / item.relative_path
        ).read_bytes()
        for item in prepared.manifest.files
    }
    for item in members:
        if isinstance(item, DeploymentPlan):
            child, classification = item, "DEPLOYABLE"
        else:
            child, classification = item.child_plan, item.classification.value
            if child is None:
                if item.expected_hostname not in index:
                    raise PlanAssuranceError(
                        "compliant hostname is absent from baseline"
                    )
                config = index[item.expected_hostname]
                if config.platform != item.platform:
                    raise PlanAssuranceError(
                        "compliant platform does not match baseline grammar"
                    )
                if item.platform == "cisco_iosxe":
                    _transform_cisco(
                        config.text,
                        item.interface,
                        item.desired_description,
                        item.desired_description,
                    )
                else:
                    _transform_junos(
                        config.text,
                        item.interface,
                        item.desired_description,
                        item.desired_description,
                    )
                records.append(
                    PlanSnapshotMutation(
                        target=item.target,
                        platform=item.platform,
                        interface=item.interface,
                        config_relative_path=config.relative_path,
                        classification=classification,
                        current_description=item.current_description,
                        desired_description=item.desired_description,
                        changed=False,
                    )
                )
                continue
        if child.expected_hostname not in index:
            raise PlanAssuranceError("plan hostname is absent from baseline")
        config = index[child.expected_hostname]
        if config.platform != child.platform:
            raise PlanAssuranceError("plan platform does not match baseline grammar")
        text = config.text
        if child.platform == "cisco_iosxe":
            transformed, changed = _transform_cisco(
                text,
                child.interface,
                child.current_description,
                child.desired_description,
            )
        elif child.platform == "junos":
            transformed, changed = _transform_junos(
                text,
                child.interface,
                child.current_description,
                child.desired_description,
            )
        else:
            raise PlanAssuranceError("unsupported plan platform")
        transformed_bytes = transformed.encode()
        if changed and transformed_bytes == replacements[config.relative_path]:
            raise PlanAssuranceError("deployable transformation made no byte change")
        replacements[config.relative_path] = transformed_bytes
        records.append(
            PlanSnapshotMutation(
                target=child.target,
                platform=child.platform,
                interface=child.interface,
                config_relative_path=config.relative_path,
                classification=classification,
                current_description=child.current_description,
                desired_description=child.desired_description,
                child_plan_digest=child.digest
                if isinstance(plan, FleetDeploymentPlan)
                else None,
                changed=changed,
            )
        )
    return prepare_snapshot_from_bytes(tuple(sorted(replacements.items()))), tuple(
        records
    )


def _finalize_record(record: PlanAssuranceRecord) -> PlanAssuranceRecord:
    return record.model_copy(update={"digest": record.calculated_digest()})


def assure_plan(
    plan: DeploymentPlan | FleetDeploymentPlan,
    policy: BatfishAssurancePolicy,
    baseline: Path,
    provider: BatfishAssuranceAdapter | None = None,
) -> PlanAssuranceRecord:
    if not plan.verify_digest():
        raise PlanAssuranceError("assurance plan digest verification failed")
    subject = subject_from_plan(plan)
    policy_digest = policy.calculated_digest()
    with prepare_snapshot(baseline) as frozen:
        try:
            candidate, derivation = materialize_candidate(frozen, plan)
        except PlanAssuranceError as exc:
            return _finalize_record(
                PlanAssuranceRecord(
                    generated_at=datetime.now(UTC),
                    subject=subject,
                    policy=policy,
                    policy_digest=policy_digest,
                    baseline_snapshot_digest=frozen.manifest.digest,
                    failure_reason=str(exc),
                    outcome=AssuranceOutcome.BLOCKED,
                    digest="sha256:" + "0" * 64,
                )
            )
        with candidate:
            try:
                observation = (provider or BatfishAssuranceAdapter()).analyze(
                    frozen.root, candidate.root, policy_to_intent(policy, subject)
                )
                evidence = evaluate_assurance(
                    policy_to_intent(policy, subject),
                    frozen.manifest,
                    candidate.manifest,
                    observation,
                )
                record = PlanAssuranceRecord(
                    generated_at=datetime.now(UTC),
                    subject=subject,
                    policy=policy,
                    policy_digest=policy_digest,
                    baseline_snapshot_digest=frozen.manifest.digest,
                    candidate_snapshot_digest=candidate.manifest.digest,
                    candidate_derivation=derivation,
                    assurance=evidence,
                    outcome=evidence.outcome,
                    digest="sha256:" + "0" * 64,
                )
            except AssuranceProviderError as exc:
                record = PlanAssuranceRecord(
                    generated_at=datetime.now(UTC),
                    subject=subject,
                    policy=policy,
                    policy_digest=policy_digest,
                    baseline_snapshot_digest=frozen.manifest.digest,
                    candidate_snapshot_digest=candidate.manifest.digest,
                    candidate_derivation=derivation,
                    failure_reason=str(exc),
                    outcome=AssuranceOutcome.BLOCKED,
                    digest="sha256:" + "0" * 64,
                )
            return _finalize_record(record)


def verify_plan_assurance(
    plan: DeploymentPlan | FleetDeploymentPlan,
    policy: BatfishAssurancePolicy,
    baseline: Path,
    record: PlanAssuranceRecord,
) -> bool:
    if (
        not plan.verify_digest()
        or not record.verify_digest()
        or record.outcome is not AssuranceOutcome.PASSED
    ):
        return False
    subject = subject_from_plan(plan)
    if (
        record.subject != subject
        or record.policy != policy
        or record.policy_digest != policy.calculated_digest()
        or record.assurance is None
    ):
        return False
    with prepare_snapshot(baseline) as frozen:
        try:
            candidate, derivation = materialize_candidate(frozen, plan)
        except PlanAssuranceError:
            return False
        with candidate:
            if (
                frozen.manifest.digest != record.baseline_snapshot_digest
                or candidate.manifest.digest != record.candidate_snapshot_digest
                or derivation != record.candidate_derivation
            ):
                return False
            inner = record.assurance
            if (
                inner.subject_digest != subject.plan_digest
                or inner.baseline_snapshot_digest != frozen.manifest.digest
                or inner.candidate_snapshot_digest != candidate.manifest.digest
            ):
                return False
            observation = AssuranceObservation(
                pybatfish_version=inner.pybatfish_version or "",
                batfish_version=inner.batfish_version or "",
                service_identity=inner.service_identity,
                baseline=inner.baseline_parse,
                candidate=inner.candidate_parse,
                flows=inner.critical_flows,
                differential_changed_flow_count=inner.differential_changed_flow_count,
            )
            recomputed = evaluate_assurance(
                policy_to_intent(policy, subject),
                frozen.manifest,
                candidate.manifest,
                observation,
            )
            return (
                recomputed.outcome is AssuranceOutcome.PASSED
                and recomputed.model_dump(mode="json", exclude={"generated_at"})
                == inner.model_dump(mode="json", exclude={"generated_at"})
            )


class _NoContactProvider:
    def analyze(self, *_: object) -> AssuranceEvidence:
        raise AssuranceProviderError("provider contact forbidden during verification")
