"""Typed contracts for the Cisco interface-description vertical."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

NonEmptyString = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class DesiredDescription(BaseModel):
    """Desired interface-description properties."""

    model_config = ConfigDict(frozen=True)
    description: str = Field(min_length=1, max_length=240)

    @model_validator(mode="after")
    def reject_unsafe_characters(self) -> DesiredDescription:
        """Reject whitespace-only, multiline, and control-bearing descriptions."""
        if not self.description.strip():
            raise ValueError("description must contain a non-whitespace character")
        if any(
            ord(character) < 32 or ord(character) == 127
            for character in self.description
        ):
            raise ValueError("description must not contain control characters")
        return self


class InterfaceDescriptionIntent(BaseModel):
    """The only supported change intent in Increment 2."""

    model_config = ConfigDict(frozen=True)
    change_id: NonEmptyString
    kind: Literal["interface_description"]
    target: NonEmptyString
    interface: NonEmptyString
    desired: DesiredDescription


class InventoryDevice(BaseModel):
    """Temporary local inventory entry without credentials."""

    model_config = ConfigDict(frozen=True)
    name: NonEmptyString
    host: NonEmptyString
    port: int = Field(default=22, ge=1, le=65535)
    platform: Literal["cisco_iosxe"]
    expected_hostname: NonEmptyString
    protected_interfaces: tuple[str, ...] = ()


class InventoryDocument(BaseModel):
    """Temporary local inventory document."""

    model_config = ConfigDict(frozen=True)
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

    model_config = ConfigDict(frozen=True)
    observed_hostname: str
    ios_version: str | None = None
    interface: str
    exists: bool
    description: str | None = None
    protected: bool
    enabled: bool | None = None
    ipv4_addresses: tuple[str, ...] = ()


class CiscoConfigArtifact(BaseModel):
    """Exact immutable IOS configuration section."""

    model_config = ConfigDict(frozen=True)
    parent: str
    lines: tuple[str, ...]

    def cli_preview(self) -> str:
        """Render the human preview from the machine artifact itself."""
        return "\n".join((self.parent, *(f" {line}" for line in self.lines)))


class PlanPreconditions(BaseModel):
    """Relevant state that must still hold immediately before writing."""

    model_config = ConfigDict(frozen=True)
    observed_hostname: str
    interface_exists: bool
    interface_protected: bool
    current_description: str | None


class DeploymentPlan(BaseModel):
    """Digest-bound immutable machine execution plan."""

    model_config = ConfigDict(frozen=True)
    schema_version: Literal["1"] = "1"
    change_id: NonEmptyString
    kind: Literal["interface_description"]
    target: NonEmptyString
    expected_hostname: NonEmptyString
    platform: Literal["cisco_iosxe"]
    interface: NonEmptyString
    current_description: str | None
    desired_description: str
    execution_artifact: CiscoConfigArtifact
    recovery_artifact: CiscoConfigArtifact
    preconditions: PlanPreconditions
    created_at: datetime
    digest: str

    @model_validator(mode="after")
    def artifact_matches_supported_operation(self) -> DeploymentPlan:
        """Prevent a valid digest from approving a broader or divergent command."""
        DesiredDescription(description=self.desired_description)
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


class ExecutionDisposition(StrEnum):
    """Bounded execution-adapter result classification."""

    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    AMBIGUOUS = "AMBIGUOUS"


class ExecutionResult(BaseModel):
    """Secret-safe normalized result of one exact artifact application."""

    model_config = ConfigDict(frozen=True)
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


class StageResult(BaseModel):
    """Bounded status for a lifecycle stage."""

    model_config = ConfigDict(frozen=True)
    attempted: bool = False
    succeeded: bool | None = None
    changed: bool | None = None
    observed_description: str | None = None
    message: str


class ChangeRecord(BaseModel):
    """Minimal typed, secret-free evidence for this vertical."""

    model_config = ConfigDict(frozen=True)
    schema_version: Literal["1"] = "1"
    generated_at: datetime
    change_id: str
    plan_digest: str
    target: str
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
    final_outcome: FinalOutcome
    provider: str
