"""Typed protected-Buildkite audit correlation and durable publication."""

from __future__ import annotations

import json
import re
from dataclasses import fields
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import TypeAdapter, ValidationError

from network_change_delivery.audit import (
    AuditArtifactKind,
    AuditFinalOutcome,
    BuildkiteCorrelation,
    CredentialProvenance,
    GitCorrelation,
    ProtectedApprovalBoundary,
    StableTargetIdentity,
    audit_record_with_digest,
)
from network_change_delivery.audit_store import AuditStore
from network_change_delivery.buildkite_deployment import (
    load_live_deployment_request_at_commit,
    load_promoted_single_plan,
)
from network_change_delivery.buildkite_policy import BuildkiteDeploymentContext
from network_change_delivery.ephemeral_staging import StagingEvidence
from network_change_delivery.models import ChangeRecord, DeploymentPlan, FinalOutcome
from network_change_delivery.plan_assurance import AssuranceOutcome, PlanAssuranceRecord
from network_change_delivery.promotion import (
    DeploymentPromotionManifest,
)

MAX_STAGING_EVIDENCE_BYTES = 256 * 1024
MAX_CHANGE_RECORD_BYTES = 256 * 1024
_STAGING_FIELDS = frozenset(item.name for item in fields(StagingEvidence))
_STAGING_ADAPTER = TypeAdapter(StagingEvidence)
_REPOSITORY_PATH = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")


class BuildkiteAuditError(ValueError):
    """Bounded, secret-free protected audit-correlation failure."""


FINAL_OUTCOME_MAP: dict[FinalOutcome, AuditFinalOutcome] = {
    FinalOutcome.COMPLIANT: AuditFinalOutcome.NO_WRITE,
    FinalOutcome.BLOCKED: AuditFinalOutcome.BLOCKED,
    FinalOutcome.STALE_PLAN: AuditFinalOutcome.BLOCKED,
    FinalOutcome.SUCCEEDED: AuditFinalOutcome.SUCCEEDED,
    FinalOutcome.EXECUTION_FAILED: AuditFinalOutcome.FAILED,
    FinalOutcome.AMBIGUOUS: AuditFinalOutcome.AMBIGUOUS,
    FinalOutcome.POST_VALIDATION_FAILED: AuditFinalOutcome.FAILED,
    FinalOutcome.RECOVERED: AuditFinalOutcome.RECOVERED,
    FinalOutcome.RECOVERY_FAILED: AuditFinalOutcome.FAILED,
    FinalOutcome.RECOVERY_AMBIGUOUS: AuditFinalOutcome.AMBIGUOUS,
    FinalOutcome.AUTO_ROLLBACK_PENDING: AuditFinalOutcome.FAILED,
    FinalOutcome.CONFIRMATION_FAILED: AuditFinalOutcome.FAILED,
    FinalOutcome.CONFIRMATION_AMBIGUOUS: AuditFinalOutcome.AMBIGUOUS,
}


def normalize_buildkite_repository(value: str) -> str:
    """Normalize only reviewed GitHub clone URL forms into audit identity."""
    candidate = value.strip()
    path = ""
    if candidate.startswith("git@github.com:"):
        path = candidate.removeprefix("git@github.com:")
    else:
        parsed = urlsplit(candidate)
        if (
            parsed.scheme not in {"https", "ssh"}
            or parsed.hostname != "github.com"
            or parsed.query
            or parsed.fragment
            or parsed.username not in {None, "git"}
            or parsed.password is not None
        ):
            raise BuildkiteAuditError("Buildkite repository identity is rejected")
        path = parsed.path.removeprefix("/")
    path = path.removesuffix(".git")
    if not _REPOSITORY_PATH.fullmatch(path):
        raise BuildkiteAuditError("Buildkite repository identity is rejected")
    return f"github:{path.lower()}"


def load_staging_evidence(path: Path) -> StagingEvidence:
    """Load one bounded, exact staging evidence schema without generic payloads."""
    if path.is_symlink() or not path.is_file():
        raise BuildkiteAuditError("staging evidence file is invalid")
    try:
        data = path.read_bytes()
    except OSError as error:
        raise BuildkiteAuditError("staging evidence file is invalid") from error
    if not data or len(data) > MAX_STAGING_EVIDENCE_BYTES:
        raise BuildkiteAuditError("staging evidence size is invalid")
    try:
        payload = json.loads(data)
        if not isinstance(payload, dict) or set(payload) != _STAGING_FIELDS:
            raise ValueError
        evidence = _STAGING_ADAPTER.validate_python(payload)
    except (UnicodeDecodeError, json.JSONDecodeError, ValidationError, ValueError):
        raise BuildkiteAuditError("staging evidence schema is invalid") from None
    return evidence


def validate_staging_correlation(
    evidence: StagingEvidence, context: BuildkiteDeploymentContext
) -> None:
    """Require successful evidence from this exact build's staging job."""
    try:
        UUID(evidence.job_id or "")
    except ValueError:
        raise BuildkiteAuditError("staging evidence job identity is invalid") from None
    checks = (
        evidence.schema_version == "2",
        evidence.orchestrator == "buildkite",
        evidence.pipeline_id == context.pipeline_id,
        evidence.build_id == context.build_id,
        evidence.build_commit == context.commit,
        evidence.build_branch == "main",
        evidence.step_key == "cml-staging",
        evidence.staging_run_id == f"bk-{context.build_id}",
        evidence.creation_outcome == "passed",
        evidence.readiness_outcome == "passed",
        evidence.ncdp_validation_outcome == "passed",
        evidence.destroy_outcome == "passed",
        evidence.absence_verification_outcome == "passed",
        evidence.state_retirement_outcome == "passed",
        evidence.overall_result == "passed",
        evidence.primary_failure is None,
        evidence.cleanup_failure is None,
    )
    if not all(checks):
        raise BuildkiteAuditError("staging evidence does not match this deployment")


def load_verified_promotion_artifacts(
    promotion: Path, context: BuildkiteDeploymentContext
) -> tuple[DeploymentPromotionManifest, DeploymentPlan, PlanAssuranceRecord]:
    """Reuse promotion verification and return its reviewed durable artifacts."""
    manifest, plan = load_promoted_single_plan(promotion, context.commit)
    try:
        assurance = PlanAssuranceRecord.model_validate_json(
            (promotion / "assurance.json").read_text(encoding="utf-8")
        )
    except (OSError, UnicodeDecodeError, ValidationError) as error:
        raise BuildkiteAuditError("promoted assurance record is invalid") from error
    if (
        not manifest.verify_digest()
        or not plan.verify_digest()
        or not assurance.verify_digest()
        or plan.digest != manifest.plan_digest
        or assurance.digest != manifest.assurance_record_digest
        or assurance.subject.plan_digest != plan.digest
        or assurance.outcome is not AssuranceOutcome.PASSED
    ):
        raise BuildkiteAuditError("promotion audit correlation is invalid")
    return manifest, plan, assurance


def validate_change_record(record: ChangeRecord, plan: DeploymentPlan) -> None:
    """Bind typed execution evidence to every duplicated approved-plan identity."""
    matches = (
        record.change_id == plan.change_id,
        record.plan_digest == plan.digest,
        record.approval_digest == plan.digest,
        record.target == plan.target,
        record.inventory_source == plan.inventory_source,
        record.inventory_object_id == plan.inventory_object_id,
        record.inventory_interface_object_id == plan.inventory_interface_object_id,
        record.credential_source == plan.credential_source,
        record.credential_reference == plan.credential_reference,
        record.host == plan.host,
        record.port == plan.port,
        record.expected_hostname == plan.expected_hostname,
        record.platform == plan.platform,
        record.interface == plan.interface,
        record.previous_description == plan.current_description,
        record.desired_description == plan.desired_description,
        record.transaction_strategy == plan.transaction_strategy,
    )
    if not all(matches):
        raise BuildkiteAuditError("ChangeRecord does not match the promoted plan")


def verify_buildkite_audit_inputs(
    *,
    context: BuildkiteDeploymentContext,
    repository: str,
    promotion: Path,
    staging_evidence_path: Path,
) -> None:
    """Validate all pre-write correlation inputs without publishing evidence."""
    _manifest, plan, _assurance = load_verified_promotion_artifacts(promotion, context)
    _correlation_values(context, repository, plan)
    validate_staging_correlation(load_staging_evidence(staging_evidence_path), context)


def _correlation_values(
    context: BuildkiteDeploymentContext,
    repository: str,
    plan: DeploymentPlan,
) -> tuple[
    GitCorrelation,
    BuildkiteCorrelation,
    StableTargetIdentity,
    CredentialProvenance,
]:
    if plan.inventory_object_id is None or plan.inventory_interface_object_id is None:
        raise BuildkiteAuditError("promoted plan lacks stable NetBox identity")
    try:
        return (
            GitCorrelation(
                repository=normalize_buildkite_repository(repository),
                commit=context.commit,
            ),
            BuildkiteCorrelation(
                pipeline_id=UUID(context.pipeline_id),
                build_id=UUID(context.build_id),
                build_number=int(context.build_number),
                job_id=UUID(context.job_id),
                step_key=context.step_key,
            ),
            StableTargetIdentity(
                device=plan.inventory_object_id,
                interface=plan.inventory_interface_object_id,
            ),
            CredentialProvenance(
                device=plan.inventory_object_id,
                source="openbao",
                reference=plan.credential_reference,
            ),
        )
    except (ValidationError, ValueError):
        raise BuildkiteAuditError(
            "Buildkite audit correlation identity is invalid"
        ) from None


def persist_buildkite_audit(
    *,
    store: AuditStore,
    context: BuildkiteDeploymentContext,
    repository: str,
    promotion: Path,
    staging_evidence_path: Path,
    checkout: Path,
    change_record_path: Path | None = None,
    now: datetime | None = None,
) -> tuple[UUID, str, AuditFinalOutcome]:
    """Validate, correlate, and publish one protected deployment audit attempt."""
    manifest, plan, assurance = load_verified_promotion_artifacts(promotion, context)
    git, buildkite, target, credential = _correlation_values(context, repository, plan)
    staging = load_staging_evidence(staging_evidence_path)
    validate_staging_correlation(staging, context)
    live_request = load_live_deployment_request_at_commit(context.commit, root=checkout)
    record: ChangeRecord | None = None
    if change_record_path is None:
        if live_request is not None:
            raise BuildkiteAuditError(
                "live request exists without typed ChangeRecord evidence"
            )
        final_outcome = AuditFinalOutcome.NO_WRITE
    else:
        if live_request is None:
            raise BuildkiteAuditError("ChangeRecord exists without a live request")
        live_request.verify_plan(plan)
        if change_record_path.is_symlink() or not change_record_path.is_file():
            raise BuildkiteAuditError("ChangeRecord evidence is invalid")
        try:
            content = change_record_path.read_bytes()
        except OSError as error:
            raise BuildkiteAuditError("ChangeRecord evidence is invalid") from error
        if not content or len(content) > MAX_CHANGE_RECORD_BYTES:
            raise BuildkiteAuditError("ChangeRecord evidence size is invalid")
        try:
            record = ChangeRecord.model_validate_json(content)
        except ValidationError as error:
            raise BuildkiteAuditError("ChangeRecord evidence is invalid") from error
        validate_change_record(record, plan)
        try:
            final_outcome = FINAL_OUTCOME_MAP[record.final_outcome]
        except KeyError:
            raise BuildkiteAuditError("ChangeRecord outcome is not reviewed") from None

    references = [
        store.persist_artifact(AuditArtifactKind.DEPLOYMENT_PLAN, plan),
        store.persist_artifact(AuditArtifactKind.PLAN_ASSURANCE_RECORD, assurance),
        store.persist_artifact(
            AuditArtifactKind.DEPLOYMENT_PROMOTION_MANIFEST, manifest
        ),
        store.persist_artifact(AuditArtifactKind.STAGING_EVIDENCE, staging),
    ]
    if record is not None:
        references.append(
            store.persist_artifact(AuditArtifactKind.CHANGE_RECORD, record)
        )
    references.sort(key=lambda item: str(item.kind))
    audit = audit_record_with_digest(
        record_id=UUID(context.job_id),
        generated_at=now or datetime.now(UTC),
        change_id=plan.change_id,
        git=git,
        buildkite=buildkite,
        approval=ProtectedApprovalBoundary(),
        targets=(target,),
        credentials=(credential,),
        final_outcome=final_outcome,
        artifacts=tuple(references),
    )
    store.persist_record(audit)
    return audit.record_id, audit.digest, audit.final_outcome
