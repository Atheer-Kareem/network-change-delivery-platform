"""Typed, secret-free durable audit correlation contracts."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Sha256 = Annotated[str, StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$")]
SchemaVersion = Annotated[str, StringConstraints(pattern=r"^[1-9][0-9]{0,2}$")]
BoundedText = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=255,
        pattern=r"^[^\x00-\x1f\x7f]+$",
    ),
]
GitCommit = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{40}$")]
RepositoryIdentity = Annotated[
    str,
    StringConstraints(
        min_length=3,
        max_length=255,
        pattern=r"^[a-z][a-z0-9-]{1,31}:[A-Za-z0-9._/-]+$",
    ),
]
NetBoxDeviceIdentity = Annotated[
    str, StringConstraints(pattern=r"^netbox:dcim\.device:[1-9][0-9]*$")
]
NetBoxInterfaceIdentity = Annotated[
    str, StringConstraints(pattern=r"^netbox:dcim\.interface:[1-9][0-9]*$")
]


class AuditArtifactKind(StrEnum):
    """Reviewed artifact kinds eligible for the Baseline-1 audit store."""

    DEPLOYMENT_PLAN = "deployment_plan"
    FLEET_DEPLOYMENT_PLAN = "fleet_deployment_plan"
    PLAN_ASSURANCE_RECORD = "plan_assurance_record"
    DEPLOYMENT_PROMOTION_MANIFEST = "deployment_promotion_manifest"
    STAGING_EVIDENCE = "staging_evidence"
    CHANGE_RECORD = "change_record"
    FLEET_CHANGE_RECORD = "fleet_change_record"


class AuditFinalOutcome(StrEnum):
    """Bounded cross-pipeline outcome without flattening provider evidence."""

    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    AMBIGUOUS = "AMBIGUOUS"
    RECOVERED = "RECOVERED"
    PARTIAL = "PARTIAL"
    NO_WRITE = "NO_WRITE"


class AuditArtifactReference(BaseModel):
    """Integrity-bound locator for one separately persisted audit artifact."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    kind: AuditArtifactKind
    schema_version: SchemaVersion
    sha256: Sha256
    locator: str = Field(min_length=1, max_length=255)
    size_bytes: int = Field(ge=2, le=4 * 1024 * 1024)

    @model_validator(mode="after")
    def locator_matches_identity(self) -> AuditArtifactReference:
        path = PurePosixPath(self.locator)
        expected = f"artifacts/{self.kind.value}/{self.sha256[7:]}.json"
        if (
            path.is_absolute()
            or path.as_posix() != self.locator
            or any(part in {"", ".", ".."} for part in path.parts)
            or self.locator != expected
        ):
            raise ValueError("audit artifact locator is not canonical")
        return self


class GitCorrelation(BaseModel):
    """Stable reviewed-source identity."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    repository: RepositoryIdentity
    commit: GitCommit
    pull_request: int | None = Field(default=None, ge=1)


class BuildkiteCorrelation(BaseModel):
    """Complete immutable Buildkite attempt identity when one exists."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    pipeline_id: UUID
    build_id: UUID
    build_number: int = Field(ge=1)
    job_id: UUID
    step_key: BoundedText


class ProtectedApprovalBoundary(BaseModel):
    """Proof of a passed block without claiming approver identity."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    step_key: Literal["deployment-approval"] = "deployment-approval"
    passed: Literal[True] = True


class StableTargetIdentity(BaseModel):
    """Stable NetBox identities used for bounded audit lookup."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    device: NetBoxDeviceIdentity
    interface: NetBoxInterfaceIdentity


class CredentialProvenance(BaseModel):
    """Allowlisted non-secret credential authority reference."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    device: NetBoxDeviceIdentity
    source: Literal["environment", "openbao"]
    reference: BoundedText

    @model_validator(mode="after")
    def reference_matches_source(self) -> CredentialProvenance:
        if self.source == "openbao":
            expected = self.device.removeprefix("netbox:dcim.device:")
            pattern = rf"openbao:kv-v2:ncdp/devices/{expected}/ssh"
            if self.reference != pattern:
                raise ValueError("OpenBao audit credential reference is invalid")
        elif self.reference != "environment:NCDP_DEVICE_USERNAME/PASSWORD":
            raise ValueError("environment audit credential reference is invalid")
        return self


class ChangeAuditRecord(BaseModel):
    """Top-level immutable correlation envelope for one delivery attempt."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal["1"] = "1"
    record_id: UUID
    generated_at: datetime
    digest: Sha256
    change_id: BoundedText
    git: GitCorrelation
    buildkite: BuildkiteCorrelation | None = None
    approval: ProtectedApprovalBoundary | None = None
    targets: tuple[StableTargetIdentity, ...] = Field(min_length=1, max_length=100)
    credentials: tuple[CredentialProvenance, ...] = Field(default=(), max_length=100)
    final_outcome: AuditFinalOutcome
    artifacts: tuple[AuditArtifactReference, ...] = Field(
        min_length=1, max_length=len(AuditArtifactKind)
    )

    @model_validator(mode="after")
    def validate_correlation(self) -> ChangeAuditRecord:
        if (
            self.generated_at.tzinfo is None
            or self.generated_at.utcoffset() != timedelta(0)
        ):
            raise ValueError("audit timestamp must be timezone-aware UTC")
        target_keys = [(target.device, target.interface) for target in self.targets]
        if len(target_keys) != len(set(target_keys)) or target_keys != sorted(
            target_keys
        ):
            raise ValueError("audit targets must be unique and ordered")
        credential_devices = [item.device for item in self.credentials]
        if len(credential_devices) != len(
            set(credential_devices)
        ) or credential_devices != sorted(credential_devices):
            raise ValueError("audit credential references must be unique and ordered")
        target_devices = {target.device for target in self.targets}
        if any(device not in target_devices for device in credential_devices):
            raise ValueError("audit credential reference targets an unknown device")
        kinds = [artifact.kind for artifact in self.artifacts]
        if len(kinds) != len(set(kinds)) or kinds != sorted(kinds, key=str):
            raise ValueError("audit artifact references must be unique and ordered")
        kind_set = set(kinds)
        single = AuditArtifactKind.DEPLOYMENT_PLAN in kind_set
        fleet = AuditArtifactKind.FLEET_DEPLOYMENT_PLAN in kind_set
        if single == fleet:
            raise ValueError("audit record requires exactly one plan kind")
        if single and len(self.targets) != 1:
            raise ValueError("single-device audit plan requires one target")
        if (
            AuditArtifactKind.CHANGE_RECORD in kind_set
            and AuditArtifactKind.FLEET_CHANGE_RECORD in kind_set
        ):
            raise ValueError("audit execution evidence is ambiguous")
        if fleet and AuditArtifactKind.CHANGE_RECORD in kind_set:
            raise ValueError("fleet audit cannot flatten child ChangeRecords")
        if single and AuditArtifactKind.FLEET_CHANGE_RECORD in kind_set:
            raise ValueError("single-device audit cannot reference fleet evidence")
        if self.approval is not None and self.buildkite is None:
            raise ValueError("audit approval requires Buildkite correlation")
        return self

    def digest_input(self) -> bytes:
        return canonical_json_bytes(self.model_dump(mode="json", exclude={"digest"}))

    def calculated_digest(self) -> str:
        return sha256_identity(self.digest_input())

    def verify_digest(self) -> bool:
        return self.digest == self.calculated_digest()


def canonical_json_bytes(value: object) -> bytes:
    """Return the repository canonical compact JSON representation."""
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_identity(value: bytes) -> str:
    """Return the repository-prefixed SHA-256 identity."""
    return "sha256:" + hashlib.sha256(value).hexdigest()


def audit_record_with_digest(**values: object) -> ChangeAuditRecord:
    """Construct one validated record and bind its complete correlation digest."""
    unsigned = ChangeAuditRecord.model_validate(
        {**values, "digest": "sha256:" + "0" * 64}
    )
    return ChangeAuditRecord.model_validate(
        {**unsigned.model_dump(mode="json"), "digest": unsigned.calculated_digest()}
    )
