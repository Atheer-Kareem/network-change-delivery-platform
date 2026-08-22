"""Typed contracts for the multi-vendor interface-description vertical."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal
from xml.etree import ElementTree

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

NonEmptyString = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
CliBoundString = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=1, pattern=r"^[^\x00-\x1f\x7f]+$"
    ),
]
Sha256Digest = Annotated[str, StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$")]
NetBoxTagSlug = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=100,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
    ),
]


def validate_ios_description(value: str, *, require_nonempty: bool = True) -> str:
    """Validate bounded IOS description data before it can enter CLI syntax."""
    if len(value) > 240:
        raise ValueError("description must contain at most 240 characters")
    if require_nonempty and not value.strip():
        raise ValueError("description must contain a non-whitespace character")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValueError("description must not contain control characters")
    return value


class DesiredDescription(BaseModel):
    """Desired interface-description properties."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    description: str = Field(min_length=1, max_length=240)

    @model_validator(mode="after")
    def reject_unsafe_characters(self) -> DesiredDescription:
        """Reject whitespace-only, multiline, and control-bearing descriptions."""
        validate_ios_description(self.description)
        return self


class InterfaceDescriptionIntent(BaseModel):
    """The only supported change intent in Increment 2."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    change_id: CliBoundString
    kind: Literal["interface_description"]
    target: CliBoundString
    interface: CliBoundString
    desired: DesiredDescription


class NetBoxFleetSelector(BaseModel):
    """Intentionally narrow device/interface tag selector."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    device_tag: NetBoxTagSlug
    interface_tag: NetBoxTagSlug


class FleetRolloutPolicy(BaseModel):
    """Increment 5 v1 deterministic sequential cohort policy."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    canaries_per_platform: Literal[1] = 1
    wave_size: int = Field(ge=1, le=100)


class FleetInterfaceDescriptionIntent(BaseModel):
    """One desired description applied to a frozen NetBox-selected fleet."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    change_id: CliBoundString
    kind: Literal["interface_description"]
    selector: NetBoxFleetSelector
    desired: DesiredDescription
    rollout: FleetRolloutPolicy


class InventoryDevice(BaseModel):
    """Resolved inventory identity and endpoint without credentials."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    name: CliBoundString
    host: NonEmptyString
    port: int = Field(default=22, ge=1, le=65535)
    platform: Literal["cisco_iosxe", "junos"]
    expected_hostname: NonEmptyString
    protected_interfaces: tuple[str, ...] = ()
    inventory_source: Literal["local_yaml", "netbox"] = "local_yaml"
    inventory_object_id: str | None = None
    inventory_interface_object_id: str | None = None


class InventoryDocument(BaseModel):
    """Temporary local inventory document."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    devices: tuple[InventoryDevice, ...]

    @model_validator(mode="after")
    def device_names_are_unique(self) -> InventoryDocument:
        """Prevent ambiguous target resolution."""
        names = [device.name for device in self.devices]
        if len(names) != len(set(names)):
            raise ValueError("inventory device names must be unique")
        return self


class InterfaceState(BaseModel):
    """Normalized state required by this vertical."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    observed_hostname: str
    software_version: str | None = None
    interface: str
    exists: bool
    description: str | None = None
    protected: bool
    enabled: bool | None = None
    operational_status: Literal["up", "down"] | None = None
    ipv4_addresses: tuple[str, ...] = ()


class CiscoConfigArtifact(BaseModel):
    """Exact immutable IOS configuration section."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    parent: str
    lines: tuple[str, ...]

    def cli_preview(self) -> str:
        """Render the human preview from the machine artifact itself."""
        return "\n".join((self.parent, *(f" {line}" for line in self.lines)))


def render_junos_interface_description(interface: str, description: str) -> str:
    """Render the one supported Junos XML merge artifact deterministically."""
    root = ElementTree.Element("configuration")
    interfaces = ElementTree.SubElement(root, "interfaces")
    item = ElementTree.SubElement(interfaces, "interface")
    ElementTree.SubElement(item, "name").text = interface
    ElementTree.SubElement(item, "description").text = description
    return ElementTree.tostring(root, encoding="unicode", short_empty_elements=True)


class JunosConfigArtifact(BaseModel):
    """Exact immutable Junos XML merge and confirmed-commit contract."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    interface: CliBoundString
    description: str
    format: Literal["xml"] = "xml"
    load_action: Literal["merge"] = "merge"
    config_mode: Literal["exclusive"] = "exclusive"
    xml: NonEmptyString

    @model_validator(mode="after")
    def exact_supported_xml(self) -> JunosConfigArtifact:
        DesiredDescription(description=self.description)
        expected = render_junos_interface_description(self.interface, self.description)
        if self.xml != expected:
            raise ValueError("Junos artifact does not match supported intent")
        return self

    def cli_preview(self) -> str:
        """Return the safe machine artifact as its human preview."""
        return self.xml


class PlanPreconditions(BaseModel):
    """Relevant state that must still hold immediately before writing."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    observed_hostname: str
    interface_exists: bool
    interface_protected: bool
    current_description: str | None


class DeploymentPlan(BaseModel):
    """Digest-bound immutable machine execution plan."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal["1"] = "1"
    change_id: CliBoundString
    kind: Literal["interface_description"]
    target: CliBoundString
    inventory_source: Literal["local_yaml", "netbox"] = "local_yaml"
    inventory_object_id: str | None = None
    inventory_interface_object_id: str | None = None
    credential_source: Literal["environment", "openbao"]
    credential_reference: NonEmptyString
    host: NonEmptyString
    port: int = Field(ge=1, le=65535)
    expected_hostname: NonEmptyString
    platform: Literal["cisco_iosxe", "junos"]
    interface: CliBoundString
    current_description: str | None
    desired_description: str
    transaction_strategy: Literal[
        "cisco_targeted_inverse", "junos_commit_confirmed"
    ] = "cisco_targeted_inverse"
    confirmed_timeout_minutes: Literal[5] | None = None
    confirmation_operation: Literal["confirm_previous_commit"] | None = None
    execution_artifact: CiscoConfigArtifact | JunosConfigArtifact
    recovery_artifact: CiscoConfigArtifact | None
    preconditions: PlanPreconditions
    created_at: datetime
    digest: str

    @model_validator(mode="after")
    def artifact_matches_supported_operation(self) -> DeploymentPlan:
        """Prevent a valid digest from approving a broader or divergent command."""
        if self.inventory_source == "netbox" and (
            self.inventory_object_id is None
            or self.inventory_interface_object_id is None
        ):
            raise ValueError("NetBox plan inventory identity is incomplete")
        DesiredDescription(description=self.desired_description)
        if self.current_description is not None:
            validate_ios_description(self.current_description)
        if self.platform == "junos":
            if self.port != 830:
                raise ValueError("Junos plans require NETCONF port 830")
            expected = JunosConfigArtifact(
                interface=self.interface,
                description=self.desired_description,
                xml=render_junos_interface_description(
                    self.interface, self.desired_description
                ),
            )
            if (
                self.transaction_strategy != "junos_commit_confirmed"
                or self.confirmed_timeout_minutes != 5
                or self.confirmation_operation != "confirm_previous_commit"
                or self.execution_artifact != expected
                or self.recovery_artifact is not None
            ):
                raise ValueError("Junos plan transaction contract is invalid")
            return self._validate_preconditions()
        if (
            self.transaction_strategy != "cisco_targeted_inverse"
            or self.confirmed_timeout_minutes is not None
            or self.confirmation_operation is not None
            or not isinstance(self.execution_artifact, CiscoConfigArtifact)
            or not isinstance(self.recovery_artifact, CiscoConfigArtifact)
        ):
            raise ValueError("Cisco plan transaction contract is invalid")
        parent = f"interface {self.interface}"
        expected_execution = (f"description {self.desired_description}",)
        recovery_line = (
            f"description {self.current_description}"
            if self.current_description is not None
            else "no description"
        )
        expected_recovery = (recovery_line,)
        if self.execution_artifact != CiscoConfigArtifact(
            parent=parent,
            lines=expected_execution,
        ):
            raise ValueError("execution artifact does not match supported intent")
        if self.recovery_artifact != CiscoConfigArtifact(
            parent=parent,
            lines=expected_recovery,
        ):
            raise ValueError("recovery artifact does not match observed state")
        return self._validate_preconditions()

    def _validate_preconditions(self) -> DeploymentPlan:
        if (
            self.preconditions.observed_hostname != self.expected_hostname
            or not self.preconditions.interface_exists
            or self.preconditions.interface_protected
            or self.preconditions.current_description != self.current_description
        ):
            raise ValueError("plan preconditions are internally inconsistent")
        return self

    def digest_input(self) -> bytes:
        """Return canonical UTF-8 JSON excluding the digest field."""
        value = self.model_dump(mode="json", exclude={"digest"})
        return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()

    def calculated_digest(self) -> str:
        """Calculate the canonical SHA-256 digest."""
        return f"sha256:{hashlib.sha256(self.digest_input()).hexdigest()}"

    def verify_digest(self) -> bool:
        """Verify that the stored digest matches the canonical plan content."""
        return self.digest == self.calculated_digest()


class FleetMemberClassification(StrEnum):
    """Planning disposition for every frozen selected fleet member."""

    DEPLOYABLE = "DEPLOYABLE"
    COMPLIANT = "COMPLIANT"


class FrozenFleetMember(BaseModel):
    """Exact immutable inventory, credential, and child-plan binding."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    target: CliBoundString
    inventory_source: Literal["netbox"] = "netbox"
    inventory_object_id: NonEmptyString
    inventory_interface_object_id: NonEmptyString
    host: NonEmptyString
    port: int = Field(ge=1, le=65535)
    expected_hostname: NonEmptyString
    platform: Literal["cisco_iosxe", "junos"]
    interface: CliBoundString
    credential_source: Literal["environment", "openbao"]
    credential_reference: NonEmptyString
    classification: FleetMemberClassification
    current_description: str | None
    desired_description: str
    child_plan: DeploymentPlan | None = None

    @model_validator(mode="after")
    def child_plan_matches_frozen_binding(self) -> FrozenFleetMember:
        """Reject divergent duplicated fields and invalid no-op claims."""
        if self.classification is FleetMemberClassification.COMPLIANT:
            if self.child_plan is not None:
                raise ValueError("compliant fleet member cannot contain a child plan")
            return self
        plan = self.child_plan
        if plan is None or not plan.verify_digest():
            raise ValueError("deployable fleet member requires a valid child plan")
        expected = (
            self.target,
            self.inventory_source,
            self.inventory_object_id,
            self.inventory_interface_object_id,
            self.host,
            self.port,
            self.expected_hostname,
            self.platform,
            self.interface,
            self.credential_source,
            self.credential_reference,
            self.current_description,
            self.desired_description,
        )
        actual = (
            plan.target,
            plan.inventory_source,
            plan.inventory_object_id,
            plan.inventory_interface_object_id,
            plan.host,
            plan.port,
            plan.expected_hostname,
            plan.platform,
            plan.interface,
            plan.credential_source,
            plan.credential_reference,
            plan.current_description,
            plan.desired_description,
        )
        if actual != expected:
            raise ValueError("child plan disagrees with frozen fleet member")
        return self


class FleetDeploymentPlan(BaseModel):
    """Digest-bound exact fleet membership and deterministic rollout cohorts."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal["1"] = "1"
    change_id: CliBoundString
    kind: Literal["interface_description"]
    selector: NetBoxFleetSelector
    desired_description: str
    rollout: FleetRolloutPolicy
    members: tuple[FrozenFleetMember, ...]
    canaries: tuple[NonEmptyString, ...]
    waves: tuple[tuple[NonEmptyString, ...], ...]
    created_at: datetime
    digest: Sha256Digest

    @model_validator(mode="after")
    def exact_membership_and_cohorts(self) -> FleetDeploymentPlan:
        DesiredDescription(description=self.desired_description)
        targets = [member.target for member in self.members]
        devices = [member.inventory_object_id for member in self.members]
        interfaces = [member.inventory_interface_object_id for member in self.members]
        if not self.members:
            raise ValueError("fleet plan requires members")
        if len(targets) != len(set(targets)):
            raise ValueError("fleet member targets must be unique")
        if len(devices) != len(set(devices)):
            raise ValueError("fleet device identities must be unique")
        if len(interfaces) != len(set(interfaces)):
            raise ValueError("fleet interface identities must be unique")
        member_order = sorted(
            self.members,
            key=lambda member: (
                member.inventory_object_id,
                member.target,
                member.inventory_interface_object_id,
            ),
        )
        if list(self.members) != member_order:
            raise ValueError("fleet member order is invalid")
        by_id = {member.inventory_object_id: member for member in self.members}
        for member in self.members:
            if member.classification is FleetMemberClassification.COMPLIANT:
                if (
                    member.current_description != self.desired_description
                    or member.desired_description != self.desired_description
                ):
                    raise ValueError(
                        "compliant fleet member does not prove desired state"
                    )
            elif (
                member.child_plan is None
                or member.child_plan.desired_description != self.desired_description
                or member.child_plan.change_id != self.change_id
                or member.desired_description != self.desired_description
            ):
                raise ValueError("fleet child plan disagrees with fleet intent")
        cohort_ids = [*self.canaries, *(item for wave in self.waves for item in wave)]
        if len(cohort_ids) != len(set(cohort_ids)):
            raise ValueError("fleet member appears in multiple cohorts")
        if any(identity not in by_id for identity in cohort_ids):
            raise ValueError("fleet cohort references an unknown member")
        deployable = {
            member.inventory_object_id
            for member in self.members
            if member.classification is FleetMemberClassification.DEPLOYABLE
        }
        if not deployable:
            raise ValueError("fleet plan requires at least one deployable member")
        compliant = set(by_id) - deployable
        if set(cohort_ids) != deployable:
            raise ValueError("fleet cohorts must cover every deployable member once")
        if compliant.intersection(cohort_ids):
            raise ValueError("compliant member cannot appear in a fleet cohort")
        if deployable and not self.canaries:
            raise ValueError("deployable fleet requires representative canaries")
        represented = {by_id[identity].platform for identity in deployable}
        canary_platforms = [by_id[identity].platform for identity in self.canaries]
        if set(canary_platforms) != represented or len(canary_platforms) != len(
            represented
        ):
            raise ValueError("fleet requires exactly one canary per platform")
        if any(not wave or len(wave) > self.rollout.wave_size for wave in self.waves):
            raise ValueError("fleet wave size is invalid")

        def stable_key(identity: str) -> tuple[str, str, str]:
            member = by_id[identity]
            return (
                member.inventory_object_id,
                member.target,
                member.inventory_interface_object_id,
            )

        expected_canaries = tuple(
            min(
                (identity for identity in deployable if by_id[identity].platform == p),
                key=stable_key,
            )
            for p in sorted(represented)
        )
        if self.canaries != expected_canaries:
            raise ValueError("fleet canary order or assignment is invalid")
        remaining = sorted(deployable - set(self.canaries), key=stable_key)
        expected_waves = tuple(
            tuple(remaining[index : index + self.rollout.wave_size])
            for index in range(0, len(remaining), self.rollout.wave_size)
        )
        if self.waves != expected_waves:
            raise ValueError("fleet wave order or assignment is invalid")
        return self

    def digest_input(self) -> bytes:
        value = self.model_dump(mode="json", exclude={"digest"})
        return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()

    def calculated_digest(self) -> str:
        return f"sha256:{hashlib.sha256(self.digest_input()).hexdigest()}"

    def verify_digest(self) -> bool:
        return self.digest == self.calculated_digest()


class FleetMemberPreflight(BaseModel):
    """Bounded secret-free read-only result for one frozen member."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    inventory_object_id: NonEmptyString
    inventory_interface_object_id: NonEmptyString
    target: CliBoundString
    interface: CliBoundString
    classification: FleetMemberClassification
    succeeded: bool
    observed_description: str | None
    message: NonEmptyString


class FleetPreflightResult(BaseModel):
    """Whole-fleet read-only preflight evidence; never authorizes execution."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    fleet_digest: Sha256Digest
    succeeded: bool
    members: tuple[FleetMemberPreflight, ...]
    message: NonEmptyString

    @model_validator(mode="after")
    def outcome_matches_member_results(self) -> FleetPreflightResult:
        """Prevent contradictory whole-fleet safety evidence."""
        every_member_succeeded = bool(self.members) and all(
            member.succeeded for member in self.members
        )
        if self.succeeded != every_member_succeeded:
            raise ValueError("fleet preflight outcome contradicts member results")
        return self


class FleetFinalOutcome(StrEnum):
    """Honest whole-fleet outcomes without an atomicity claim."""

    BLOCKED = "BLOCKED"
    SUCCEEDED = "SUCCEEDED"
    STOPPED = "STOPPED"
    PARTIAL = "PARTIAL"
    FINAL_VALIDATION_FAILED = "FINAL_VALIDATION_FAILED"


class FleetCohortType(StrEnum):
    """Frozen execution placement for one fleet member."""

    COMPLIANT = "COMPLIANT"
    CANARY = "CANARY"
    WAVE = "WAVE"


class ExecutionDisposition(StrEnum):
    """Bounded execution-adapter result classification."""

    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    AMBIGUOUS = "AMBIGUOUS"


class ExecutionResult(BaseModel):
    """Secret-safe normalized result of one exact artifact application."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    disposition: ExecutionDisposition
    changed: bool = False
    message: str
    provider: str = "ansible-runner/cisco.ios.ios_config"


class FinalOutcome(StrEnum):
    """Outcomes supported by the initial ChangeRecord."""

    COMPLIANT = "COMPLIANT"
    BLOCKED = "BLOCKED"
    STALE_PLAN = "STALE_PLAN"
    SUCCEEDED = "SUCCEEDED"
    EXECUTION_FAILED = "EXECUTION_FAILED"
    AMBIGUOUS = "AMBIGUOUS"
    POST_VALIDATION_FAILED = "POST_VALIDATION_FAILED"
    RECOVERED = "RECOVERED"
    RECOVERY_FAILED = "RECOVERY_FAILED"
    RECOVERY_AMBIGUOUS = "RECOVERY_AMBIGUOUS"
    AUTO_ROLLBACK_PENDING = "AUTO_ROLLBACK_PENDING"
    CONFIRMATION_FAILED = "CONFIRMATION_FAILED"
    CONFIRMATION_AMBIGUOUS = "CONFIRMATION_AMBIGUOUS"


class StageResult(BaseModel):
    """Bounded status for a lifecycle stage."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    attempted: bool = False
    succeeded: bool | None = None
    changed: bool | None = None
    observed_description: str | None = None
    message: str


class ChangeRecord(BaseModel):
    """Minimal typed, secret-free evidence for this vertical."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal["1"] = "1"
    generated_at: datetime
    change_id: str
    plan_digest: str
    target: str
    inventory_source: Literal["local_yaml", "netbox"] = "local_yaml"
    inventory_object_id: str | None = None
    inventory_interface_object_id: str | None = None
    credential_source: Literal["environment", "openbao"]
    credential_reference: NonEmptyString
    host: str
    port: int
    expected_hostname: str
    platform: str
    interface: str
    previous_description: str | None
    desired_description: str
    approval_digest: str
    preflight: StageResult
    execution: StageResult
    post_validation: StageResult
    recovery: StageResult
    transaction_strategy: Literal[
        "cisco_targeted_inverse", "junos_commit_confirmed"
    ] = "cisco_targeted_inverse"
    candidate_validation: StageResult | None = None
    candidate_diff_digest: Sha256Digest | None = None
    confirmation: StageResult | None = None
    final_outcome: FinalOutcome
    provider: str


class FleetMemberExecution(BaseModel):
    """Secret-free execution evidence for every frozen fleet member."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    inventory_object_id: NonEmptyString
    inventory_interface_object_id: NonEmptyString
    target: CliBoundString
    interface: CliBoundString
    platform: Literal["cisco_iosxe", "junos"]
    classification: FleetMemberClassification
    cohort: FleetCohortType
    wave_index: int | None = Field(default=None, ge=1)
    child_plan_digest: Sha256Digest | None = None
    attempt_sequence: int | None = Field(default=None, ge=1)
    attempted: bool
    child_record: ChangeRecord | None = None
    message: NonEmptyString

    @model_validator(mode="after")
    def evidence_is_internally_consistent(self) -> FleetMemberExecution:
        if self.classification is FleetMemberClassification.COMPLIANT:
            if (
                self.cohort is not FleetCohortType.COMPLIANT
                or self.wave_index is not None
                or self.child_plan_digest is not None
                or self.attempted
                or self.attempt_sequence is not None
                or self.child_record is not None
            ):
                raise ValueError("compliant member execution evidence is invalid")
            return self
        if self.cohort is FleetCohortType.COMPLIANT:
            raise ValueError("deployable member requires an execution cohort")
        if (self.cohort is FleetCohortType.WAVE) != (self.wave_index is not None):
            raise ValueError("fleet wave index is inconsistent with cohort")
        if self.child_plan_digest is None:
            raise ValueError("deployable member requires child plan digest")
        if self.attempted:
            if self.attempt_sequence is None or self.child_record is None:
                raise ValueError("attempted member requires sequence and child record")
            record = self.child_record
            if (
                record.target != self.target
                or record.interface != self.interface
                or record.inventory_object_id != self.inventory_object_id
                or record.inventory_interface_object_id
                != self.inventory_interface_object_id
                or record.platform != self.platform
                or record.plan_digest != self.child_plan_digest
                or record.approval_digest != self.child_plan_digest
            ):
                raise ValueError("child ChangeRecord disagrees with fleet member")
        elif self.attempt_sequence is not None or self.child_record is not None:
            raise ValueError(
                "unattempted member cannot contain child execution evidence"
            )
        return self


class FleetDesiredStateValidationResult(BaseModel):
    """Complete fresh read-only desired-state evidence after rollout."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    attempted: bool
    succeeded: bool | None
    members: tuple[FleetMemberPreflight, ...]
    message: NonEmptyString

    @model_validator(mode="after")
    def outcome_matches_member_results(self) -> FleetDesiredStateValidationResult:
        if not self.attempted:
            if self.succeeded is not None or self.members:
                raise ValueError("unattempted fleet validation cannot contain results")
            return self
        every_member_succeeded = bool(self.members) and all(
            member.succeeded for member in self.members
        )
        if self.succeeded != every_member_succeeded:
            raise ValueError("fleet validation outcome contradicts member results")
        return self


class FleetChangeRecord(BaseModel):
    """Immutable secret-free evidence for one approved fleet rollout attempt."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal["1"] = "1"
    generated_at: datetime
    change_id: CliBoundString
    fleet_plan_digest: Sha256Digest
    approval_digest: str
    selector: NetBoxFleetSelector
    rollout: FleetRolloutPolicy
    canaries: tuple[NonEmptyString, ...]
    waves: tuple[tuple[NonEmptyString, ...], ...]
    preflight: FleetPreflightResult
    fleet_plan: FleetDeploymentPlan
    members: tuple[FleetMemberExecution, ...]
    stop_member_identity: NonEmptyString | None = None
    stop_child_outcome: FinalOutcome | None = None
    final_validation: FleetDesiredStateValidationResult
    final_outcome: FleetFinalOutcome

    def _require_exact_frozen_results(
        self,
        results: tuple[FleetMemberPreflight, ...],
        *,
        boundary: str,
    ) -> None:
        """Bind member-level read-only evidence to this exact frozen population."""
        if len(results) != len(self.fleet_plan.members):
            raise ValueError(f"{boundary} evidence does not cover frozen fleet")
        identities = [result.inventory_object_id for result in results]
        if len(identities) != len(set(identities)):
            raise ValueError(f"{boundary} evidence contains duplicate members")
        for result, frozen in zip(results, self.fleet_plan.members, strict=True):
            if (
                result.inventory_object_id != frozen.inventory_object_id
                or result.inventory_interface_object_id
                != frozen.inventory_interface_object_id
                or result.target != frozen.target
                or result.interface != frozen.interface
                or result.classification is not frozen.classification
            ):
                raise ValueError(f"{boundary} evidence disagrees with frozen member")

    @model_validator(mode="after")
    def evidence_matches_rollout_state_machine(self) -> FleetChangeRecord:
        if (
            self.fleet_plan.digest != self.fleet_plan_digest
            or self.fleet_plan.change_id != self.change_id
            or self.fleet_plan.selector != self.selector
            or self.fleet_plan.rollout != self.rollout
            or self.fleet_plan.canaries != self.canaries
            or self.fleet_plan.waves != self.waves
        ):
            raise ValueError("fleet execution record disagrees with frozen plan")
        if (
            self.final_outcome is not FleetFinalOutcome.BLOCKED
            and not self.fleet_plan.verify_digest()
        ):
            raise ValueError("executed fleet record contains an invalid fleet plan")
        if self.preflight.fleet_digest != self.fleet_plan_digest:
            raise ValueError("fleet preflight digest disagrees with execution record")
        if self.preflight.members:
            self._require_exact_frozen_results(
                self.preflight.members, boundary="fleet preflight"
            )
        elif self.preflight.succeeded:
            raise ValueError("successful fleet preflight requires complete evidence")
        if self.final_validation.attempted:
            if self.final_validation.members:
                self._require_exact_frozen_results(
                    self.final_validation.members, boundary="final fleet validation"
                )
            elif self.final_validation.succeeded:
                raise ValueError(
                    "successful final validation requires complete evidence"
                )
        identities = [member.inventory_object_id for member in self.members]
        if len(identities) != len(set(identities)):
            raise ValueError("fleet execution member identities must be unique")
        by_id = {member.inventory_object_id: member for member in self.members}
        frozen_by_id = {
            member.inventory_object_id: member for member in self.fleet_plan.members
        }
        if set(by_id) != set(frozen_by_id) or len(frozen_by_id) != len(
            self.fleet_plan.members
        ):
            raise ValueError("fleet execution evidence differs from frozen membership")
        for identity, member in by_id.items():
            frozen = frozen_by_id[identity]
            expected_digest = (
                frozen.child_plan.digest if frozen.child_plan is not None else None
            )
            if (
                member.inventory_interface_object_id
                != frozen.inventory_interface_object_id
                or member.target != frozen.target
                or member.interface != frozen.interface
                or member.platform != frozen.platform
                or member.classification is not frozen.classification
                or member.child_plan_digest != expected_digest
            ):
                raise ValueError("fleet member execution disagrees with frozen member")
            if member.attempted:
                child = frozen.child_plan
                record = member.child_record
                if child is None or record is None:
                    raise ValueError("attempted fleet member lacks child authorization")
                expected_child_binding = (
                    child.change_id,
                    child.digest,
                    child.digest,
                    child.target,
                    child.inventory_source,
                    child.inventory_object_id,
                    child.inventory_interface_object_id,
                    child.credential_source,
                    child.credential_reference,
                    child.host,
                    child.port,
                    child.expected_hostname,
                    child.platform,
                    child.interface,
                    child.current_description,
                    child.desired_description,
                    child.transaction_strategy,
                )
                actual_child_binding = (
                    record.change_id,
                    record.plan_digest,
                    record.approval_digest,
                    record.target,
                    record.inventory_source,
                    record.inventory_object_id,
                    record.inventory_interface_object_id,
                    record.credential_source,
                    record.credential_reference,
                    record.host,
                    record.port,
                    record.expected_hostname,
                    record.platform,
                    record.interface,
                    record.previous_description,
                    record.desired_description,
                    record.transaction_strategy,
                )
                if actual_child_binding != expected_child_binding:
                    raise ValueError(
                        "child ChangeRecord disagrees with embedded child plan"
                    )
        planned = [*self.canaries, *(item for wave in self.waves for item in wave)]
        if len(planned) != len(set(planned)) or any(
            item not in by_id for item in planned
        ):
            raise ValueError("fleet execution cohorts are invalid")
        deployable = [
            member
            for member in self.members
            if member.classification is FleetMemberClassification.DEPLOYABLE
        ]
        if set(planned) != {member.inventory_object_id for member in deployable}:
            raise ValueError("fleet execution cohorts do not cover deployable members")
        wave_by_id = {
            identity: index
            for index, wave in enumerate(self.waves, start=1)
            for identity in wave
        }
        for identity in self.canaries:
            if by_id[identity].cohort is not FleetCohortType.CANARY:
                raise ValueError("fleet canary evidence is inconsistent")
        for identity, wave_index in wave_by_id.items():
            member = by_id[identity]
            if (
                member.cohort is not FleetCohortType.WAVE
                or member.wave_index != wave_index
            ):
                raise ValueError("fleet wave evidence is inconsistent")
        attempted = [member for member in self.members if member.attempted]
        attempted.sort(key=lambda member: member.attempt_sequence or 0)
        sequences = [member.attempt_sequence for member in attempted]
        if sequences != list(range(1, len(attempted) + 1)):
            raise ValueError("fleet attempt sequence must be unique and contiguous")
        expected_attempted = planned[: len(attempted)]
        if [member.inventory_object_id for member in attempted] != expected_attempted:
            raise ValueError("fleet attempt sequence differs from planned cohort order")
        successful = [
            member
            for member in attempted
            if member.child_record is not None
            and member.child_record.final_outcome is FinalOutcome.SUCCEEDED
        ]
        failed = [
            member
            for member in attempted
            if member.child_record is not None
            and member.child_record.final_outcome is not FinalOutcome.SUCCEEDED
        ]
        if len(failed) > 1 or (failed and attempted[-1] is not failed[0]):
            raise ValueError("fleet execution continued after a child stop outcome")
        if self.final_outcome is FleetFinalOutcome.BLOCKED:
            if attempted or self.preflight.succeeded or self.final_validation.attempted:
                raise ValueError("blocked fleet record cannot contain child attempts")
        elif not self.preflight.succeeded:
            raise ValueError("attempted fleet rollout requires successful preflight")
        if self.final_outcome is not FleetFinalOutcome.BLOCKED and (
            self.approval_digest != self.fleet_plan_digest
        ):
            raise ValueError("executed fleet approval digest does not match plan")
        if self.final_outcome is FleetFinalOutcome.STOPPED:
            if len(failed) != 1 or successful:
                raise ValueError("stopped fleet outcome evidence is invalid")
        elif self.final_outcome is FleetFinalOutcome.PARTIAL:
            if len(failed) != 1 or not successful:
                raise ValueError(
                    "partial fleet outcome requires prior success and stop"
                )
        elif self.final_outcome in {
            FleetFinalOutcome.SUCCEEDED,
            FleetFinalOutcome.FINAL_VALIDATION_FAILED,
        }:
            if failed or len(attempted) != len(deployable):
                raise ValueError("completed fleet outcome requires all child successes")
            expected_validation = self.final_outcome is FleetFinalOutcome.SUCCEEDED
            if (
                not self.final_validation.attempted
                or self.final_validation.succeeded is not expected_validation
            ):
                raise ValueError("fleet final outcome contradicts final validation")
        if self.final_outcome in {FleetFinalOutcome.STOPPED, FleetFinalOutcome.PARTIAL}:
            failed_member = failed[0]
            if (
                self.stop_member_identity != failed_member.inventory_object_id
                or self.stop_child_outcome
                is not failed_member.child_record.final_outcome  # type: ignore[union-attr]
                or self.final_validation.attempted
            ):
                raise ValueError("fleet stop evidence is inconsistent")
        elif (
            self.stop_member_identity is not None or self.stop_child_outcome is not None
        ):
            raise ValueError("non-stopped fleet record cannot contain stop evidence")
        return self
