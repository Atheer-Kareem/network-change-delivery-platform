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
