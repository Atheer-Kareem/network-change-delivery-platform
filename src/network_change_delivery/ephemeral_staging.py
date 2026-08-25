"""Fail-closed orchestration contract for one ephemeral CML staging run."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Protocol


class StagingError(RuntimeError):
    """A sanitized ephemeral-staging lifecycle failure."""


@dataclass
class StagingEvidence:
    """Bounded, non-secret evidence retained for one staging run."""

    schema_version: str
    staging_run_id: str
    lab_id: str | None = None
    node_ids: dict[str, str] = field(default_factory=dict)
    link_ids: dict[str, str] = field(default_factory=dict)
    creation_outcome: str = "not_attempted"
    readiness_outcome: str = "not_attempted"
    readiness_seconds: dict[str, float] = field(default_factory=dict)
    readiness_checks: dict[str, dict[str, str]] = field(default_factory=dict)
    netbox_device_ids: dict[str, str] = field(default_factory=dict)
    credential_references: dict[str, str] = field(default_factory=dict)
    ncdp_validation_outcome: str = "not_attempted"
    primary_failure: str | None = None
    destroy_outcome: str = "not_attempted"
    cleanup_failure: str | None = None
    absence_verification_outcome: str = "not_attempted"
    state_retirement_outcome: str = "not_attempted"
    overall_result: str = "running"

    def safe_dict(self) -> dict[str, object]:
        """Return the explicitly allowlisted evidence schema."""
        return asdict(self)


class StagingOperations(Protocol):
    """Side-effect boundary implemented by the local operator driver."""

    @property
    def managed_resources_exist(self) -> bool: ...

    def admit(self) -> None: ...

    def create(self, evidence: StagingEvidence) -> None: ...

    def start(self, evidence: StagingEvidence) -> None: ...

    def validate(self, evidence: StagingEvidence) -> None: ...

    def destroy(self, evidence: StagingEvidence) -> None: ...

    def verify_absent(self, evidence: StagingEvidence) -> None: ...

    def retire_state(self, evidence: StagingEvidence) -> None: ...


def validate_run_directory(run_id: str, run_directory: Path) -> None:
    """Reject reused or structurally unsafe run directories."""
    if not run_id or len(run_id) > 40:
        raise StagingError("staging run identity is invalid")
    if not run_id[0].isalnum() or any(
        character not in "abcdefghijklmnopqrstuvwxyz0123456789-" for character in run_id
    ):
        raise StagingError("staging run identity is invalid")
    if run_directory.exists() and any(run_directory.iterdir()):
        raise StagingError("run-scoped state already exists; recovery is required")


def run_staging_lifecycle(
    run_id: str,
    run_directory: Path,
    operations: StagingOperations,
) -> StagingEvidence:
    """Run create/start/validate and always attempt eligible cleanup once."""
    evidence = StagingEvidence(schema_version="1", staging_run_id=run_id)
    primary: Exception | None = None
    cleanup: Exception | None = None
    try:
        validate_run_directory(run_id, run_directory)
        operations.admit()
        evidence.creation_outcome = "attempted"
        operations.create(evidence)
        evidence.creation_outcome = "passed"
        operations.start(evidence)
        operations.validate(evidence)
        evidence.readiness_outcome = "passed"
        evidence.ncdp_validation_outcome = "passed"
    except Exception as error:  # the driver exposes only sanitized exceptions
        primary = error
        evidence.primary_failure = str(error)
    finally:
        if operations.managed_resources_exist:
            try:
                operations.destroy(evidence)
                evidence.destroy_outcome = "passed"
                operations.verify_absent(evidence)
                evidence.absence_verification_outcome = "passed"
                operations.retire_state(evidence)
                evidence.state_retirement_outcome = "passed"
            except Exception as error:  # preserve primary and cleanup independently
                cleanup = error
                evidence.cleanup_failure = str(error)

    evidence.overall_result = (
        "passed" if primary is None and cleanup is None else "failed"
    )
    return evidence
