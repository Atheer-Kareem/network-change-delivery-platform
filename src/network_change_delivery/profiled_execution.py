"""Schema-v2 profiled execution lifecycle consumed by the explicit CLI boundary."""

from __future__ import annotations

import re
from collections.abc import Callable
from contextlib import suppress
from datetime import UTC, datetime
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, model_validator

from network_change_delivery.ansible_adapter import DeploymentRuntimeError
from network_change_delivery.architecture_contracts import (
    AutomationProfileID,
    NetworkOS,
    Sha256Digest,
    StableInterfaceIdentity,
    TransportFamily,
)
from network_change_delivery.models import (
    CiscoConfigArtifact,
    ExecutionDisposition,
    FinalOutcome,
    InterfaceState,
    JunosConfigArtifact,
    StageResult,
)
from network_change_delivery.profile_inventory import (
    ProfiledInventoryDevice,
    admit_profiled_subject,
)
from network_change_delivery.profiled_planning import (
    PROFILED_OPERATION_ADMISSIONS,
    ProfiledDeploymentPlan,
    ProfiledOperation,
    admit_profiled_operation,
)
from network_change_delivery.profiled_write_adapter import (
    ProfiledWriteAdapter,
    ProfiledWriteTarget,
)
from network_change_delivery.secrets import CredentialReference, DeviceCredentials


class ProfiledExecutionError(ValueError):
    """Secret-free preflight failure with an honest outcome classification."""

    def __init__(self, outcome: FinalOutcome, message: str) -> None:
        super().__init__(message)
        self.outcome = outcome


class ProfiledChangeRecord(BaseModel):
    """Immutable secret-free schema-v2 execution evidence, separate from v1."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal["2"] = "2"
    record_type: Literal["profiled_change_record"] = "profiled_change_record"
    generated_at: datetime
    change_id: str
    plan_digest: Sha256Digest
    approval_digest: Sha256Digest
    target: str
    device_identity: str
    interface: StableInterfaceIdentity
    platform_slug: str
    network_os: NetworkOS
    automation_profile_id: AutomationProfileID
    operation: ProfiledOperation
    host: str
    port: int
    expected_hostname: str
    previous_description: str | None
    desired_description: str
    credential_source: Literal["openbao"] = "openbao"
    credential_reference: str
    transaction_strategy: Literal["cisco_targeted_inverse", "junos_commit_confirmed"]
    preflight: StageResult
    execution: StageResult
    post_validation: StageResult
    recovery: StageResult
    candidate_validation: StageResult | None = None
    candidate_diff_digest: Sha256Digest | None = None
    confirmation: StageResult | None = None
    managed_state_acceptance_attempted: Literal[False] = False
    final_outcome: FinalOutcome

    @model_validator(mode="after")
    def consistent_outcome(self) -> ProfiledChangeRecord:
        """Validate representable stage facts without treating metadata as authority."""
        if self.approval_digest != self.plan_digest:
            raise ValueError("record approval and plan digests differ")
        admission = PROFILED_OPERATION_ADMISSIONS.get(
            (self.automation_profile_id, self.operation)
        )
        if (
            admission is None
            or self.network_os is not admission.network_os
            or self.transaction_strategy != admission.transaction_strategy
        ):
            raise ValueError("record operation/profile strategy rejected")
        for stage in (
            self.preflight,
            self.execution,
            self.post_validation,
            self.recovery,
            self.candidate_validation,
            self.confirmation,
        ):
            if (
                stage is not None
                and not stage.attempted
                and (
                    stage.succeeded is not None
                    or stage.changed is not None
                    or stage.observed_description is not None
                )
            ):
                raise ValueError("unattempted stage carries result facts")
            if stage is not None and stage.attempted and stage.succeeded is None:
                raise ValueError("attempted stage lacks a classified result")
        pre, execution, post, recovery = (
            self.preflight,
            self.execution,
            self.post_validation,
            self.recovery,
        )
        outcome = self.final_outcome
        junos = self.transaction_strategy == "junos_commit_confirmed"
        if not pre.attempted:
            raise ValueError("record requires attempted preflight")
        if (
            pre.succeeded is True
            and pre.observed_description != self.previous_description
        ):
            raise ValueError("successful preflight differs from reviewed state")
        if execution.attempted and pre.succeeded is not True:
            raise ValueError("execution without successful preflight")
        if post.attempted and not execution.attempted:
            raise ValueError("post-validation without execution")
        if post.changed is not None and post.changed != (
            post.observed_description != self.previous_description
        ):
            raise ValueError("observed transition contradicts observed description")
        if (
            post.succeeded is True
            and outcome is not FinalOutcome.AMBIGUOUS
            and (post.observed_description != self.desired_description)
        ):
            raise ValueError("successful post-validation did not observe desired state")
        recovery_outcomes = {
            FinalOutcome.RECOVERED,
            FinalOutcome.RECOVERY_FAILED,
            FinalOutcome.RECOVERY_AMBIGUOUS,
        }
        if recovery.attempted != (outcome in recovery_outcomes):
            raise ValueError("recovery outcome/attempt mismatch")
        if recovery.attempted and (
            junos
            or execution.succeeded is not True
            or not post.attempted
            or post.succeeded is not False
            or post.observed_description == self.desired_description
        ):
            raise ValueError("recovery is ineligible")
        if outcome is FinalOutcome.RECOVERED and (
            recovery.succeeded is not True
            or recovery.observed_description != self.previous_description
        ):
            raise ValueError("recovery lacks verified restoration")
        if (
            outcome is FinalOutcome.RECOVERY_AMBIGUOUS
            and recovery.succeeded is not False
        ):
            raise ValueError("ambiguous recovery cannot claim success")
        if not junos and any(
            value is not None
            for value in (
                self.candidate_validation,
                self.candidate_diff_digest,
                self.confirmation,
            )
        ):
            raise ValueError("Cisco record carries Junos transaction evidence")
        if junos:
            candidate, confirmation = self.candidate_validation, self.confirmation
            if (
                candidate is not None
                and candidate.attempted
                and pre.succeeded is not True
            ):
                raise ValueError("candidate without successful preflight")
            candidate_ok = candidate is not None and candidate.succeeded is True
            if candidate_ok != (self.candidate_diff_digest is not None):
                raise ValueError("candidate validation/diff mismatch")
            if execution.attempted != candidate_ok:
                raise ValueError("Junos execution/candidate mismatch")
            confirmation_outcomes = {
                FinalOutcome.SUCCEEDED,
                FinalOutcome.CONFIRMATION_FAILED,
                FinalOutcome.CONFIRMATION_AMBIGUOUS,
            }
            if (confirmation is not None and confirmation.attempted) != (
                outcome in confirmation_outcomes
            ):
                raise ValueError("Junos confirmation/outcome mismatch")
            if (
                confirmation is not None
                and confirmation.attempted
                and (
                    execution.succeeded is not True
                    or post.succeeded is not True
                    or confirmation.succeeded is not (outcome is FinalOutcome.SUCCEEDED)
                )
            ):
                raise ValueError("Junos confirmation lifecycle inconsistent")
        if outcome in {FinalOutcome.BLOCKED, FinalOutcome.STALE_PLAN}:
            if execution.attempted or post.attempted or recovery.attempted:
                raise ValueError("blocked/stale record attempted execution")
            if pre.succeeded is True and not (
                junos
                and outcome is FinalOutcome.BLOCKED
                and self.candidate_validation is not None
                and self.candidate_validation.attempted
                and self.candidate_validation.succeeded is False
            ):
                raise ValueError("blocked/stale record lacks failed prerequisite")
        elif outcome is FinalOutcome.SUCCEEDED:
            if execution.succeeded is not True or post.succeeded is not True:
                raise ValueError(
                    "success lacks execution and independent post-validation"
                )
        elif outcome in {FinalOutcome.EXECUTION_FAILED, FinalOutcome.AMBIGUOUS}:
            if not execution.attempted or execution.succeeded is not False:
                raise ValueError("failed/ambiguous execution facts inconsistent")
            if post.attempted and (junos or outcome is FinalOutcome.EXECUTION_FAILED):
                raise ValueError("post observation on unsupported failure path")
        elif outcome in recovery_outcomes:
            pass  # Eligibility and restoration are checked above.
        elif outcome is FinalOutcome.POST_VALIDATION_FAILED:
            if (
                junos
                or execution.succeeded is not True
                or not post.attempted
                or post.succeeded is not False
            ):
                raise ValueError("post-validation failure facts inconsistent")
        elif outcome is FinalOutcome.AUTO_ROLLBACK_PENDING:
            if not junos or execution.succeeded is not True or post.succeeded is True:
                raise ValueError("auto-rollback-pending facts inconsistent")
        elif outcome in {
            FinalOutcome.CONFIRMATION_FAILED,
            FinalOutcome.CONFIRMATION_AMBIGUOUS,
        }:
            if not junos:
                raise ValueError("confirmation outcome requires Junos")
        else:
            raise ValueError("unsupported profiled execution outcome")
        return self


def verify_profiled_record_plan(
    record: ProfiledChangeRecord, plan: ProfiledDeploymentPlan
) -> None:
    """Verify all duplicated approval bindings; never execute or reinterpret a write."""
    # Revalidate even model_copy/model_construct inputs at the consumer boundary.
    record = ProfiledChangeRecord.model_validate(record.model_dump(warnings=False))
    plan = ProfiledDeploymentPlan.model_validate(plan.model_dump(warnings=False))
    fields = (
        "change_id",
        "target",
        "device_identity",
        "interface",
        "platform_slug",
        "network_os",
        "automation_profile_id",
        "host",
        "port",
        "expected_hostname",
        "desired_description",
        "credential_source",
        "credential_reference",
    )
    if any(getattr(record, field) != getattr(plan, field) for field in fields) or (
        record.plan_digest != plan.digest
        or record.approval_digest != plan.digest
        or record.previous_description != plan.current_description
        or record.operation is not plan.operation_admission.operation
        or record.transaction_strategy != plan.operation_admission.transaction_strategy
    ):
        raise ValueError("profiled execution record/plan binding rejected")


def _observed_transition(plan, observed):
    if (
        observed is None
        or not observed.exists
        or observed.observed_hostname != plan.expected_hostname
        or observed.interface != plan.interface.name
    ):
        return None
    return observed.description != plan.current_description


class ProfiledInventory(Protocol):
    def resolve(self, target: str) -> ProfiledInventoryDevice: ...
    def resolve_interface(
        self, device: ProfiledInventoryDevice, interface_name: str
    ) -> StableInterfaceIdentity: ...


class ProfiledSecrets(Protocol):
    def reference(self, device: ProfiledInventoryDevice) -> CredentialReference: ...
    def load(self, device: ProfiledInventoryDevice) -> DeviceCredentials: ...


class ProfiledCollector(Protocol):
    def collect(
        self, target: object, credentials: DeviceCredentials, interface: str
    ) -> InterfaceState: ...


def _stage(message: str, **values: object) -> StageResult:
    return StageResult(message=message, **values)


def _record(
    plan: ProfiledDeploymentPlan,
    approval: str,
    outcome: FinalOutcome,
    *,
    preflight: StageResult,
    execution: StageResult | None = None,
    post: StageResult | None = None,
    recovery: StageResult | None = None,
    candidate: StageResult | None = None,
    diff: str | None = None,
    confirmation: StageResult | None = None,
    now: Callable[[], datetime],
) -> ProfiledChangeRecord:
    return ProfiledChangeRecord(
        generated_at=now(),
        change_id=plan.change_id,
        plan_digest=plan.digest,
        approval_digest=approval,
        target=plan.target,
        device_identity=plan.device_identity,
        interface=plan.interface,
        platform_slug=plan.platform_slug,
        network_os=plan.network_os,
        automation_profile_id=plan.automation_profile_id,
        operation=ProfiledOperation.INTERFACE_DESCRIPTION,
        host=plan.host,
        port=plan.port,
        expected_hostname=plan.expected_hostname,
        previous_description=plan.current_description,
        desired_description=plan.desired_description,
        credential_reference=plan.credential_reference,
        transaction_strategy=plan.operation_admission.transaction_strategy,
        preflight=preflight,
        execution=execution or _stage("not attempted"),
        post_validation=post or _stage("not attempted"),
        recovery=recovery or _stage("not attempted"),
        candidate_validation=candidate,
        candidate_diff_digest=diff,
        confirmation=confirmation,
        final_outcome=outcome,
    )


def _preflight(
    plan: ProfiledDeploymentPlan,
    inventory: ProfiledInventory,
    secrets: ProfiledSecrets,
    collector: ProfiledCollector,
) -> tuple[
    ProfiledInventoryDevice, StableInterfaceIdentity, DeviceCredentials, InterfaceState
]:
    try:
        device = inventory.resolve(plan.target)
        admit_profiled_subject(
            device_identity=device.device_identity,
            logical_name=device.logical_name,
            platform_slug=device.platform.slug,
            network_os=device.network_os,
            automation_profile_id=device.automation_profile_id,
        )
        interface = inventory.resolve_interface(device, plan.interface.name)
        admission = admit_profiled_operation(
            device, ProfiledOperation.INTERFACE_DESCRIPTION
        )
        live = device.live_read_only_target()
    except (ValueError, OSError, RuntimeError) as error:
        raise ProfiledExecutionError(
            FinalOutcome.BLOCKED, "profiled inventory or admission blocked"
        ) from error
    if (
        device.logical_name,
        device.device_identity,
        interface,
        device.platform.slug,
        device.network_os,
        device.automation_profile_id,
        device.expected_hostname,
        live.host,
        live.port,
        admission,
    ) != (
        plan.target,
        plan.device_identity,
        plan.interface,
        plan.platform_slug,
        plan.network_os,
        plan.automation_profile_id,
        plan.expected_hostname,
        plan.host,
        plan.port,
        plan.operation_admission,
    ):
        raise ProfiledExecutionError(
            FinalOutcome.STALE_PLAN, "profiled plan binding changed"
        )
    try:
        reference = secrets.reference(device)
    except (ValueError, OSError, RuntimeError) as error:
        raise ProfiledExecutionError(
            FinalOutcome.BLOCKED, "credential reference resolution blocked"
        ) from error
    if (
        reference.source != "openbao"
        or reference.reference != plan.credential_reference
    ):
        raise ProfiledExecutionError(
            FinalOutcome.STALE_PLAN, "profiled credential binding changed"
        )
    try:
        credentials = secrets.load(device)
        state = collector.collect(live, credentials, plan.interface.name)
    except (ValueError, OSError, RuntimeError) as error:
        raise ProfiledExecutionError(
            FinalOutcome.BLOCKED, "credential or read-only collection blocked"
        ) from error
    if (
        state.observed_hostname != plan.expected_hostname
        or state.interface != plan.interface.name
        or not state.exists
        or state.protected
        or state.description != plan.current_description
    ):
        raise ProfiledExecutionError(
            FinalOutcome.STALE_PLAN, "profiled preconditions changed"
        )
    return device, interface, credentials, state


def execute_profiled_plan(
    plan: ProfiledDeploymentPlan,
    approval_digest: str,
    inventory: ProfiledInventory,
    secrets: ProfiledSecrets,
    collector: ProfiledCollector,
    writer: ProfiledWriteAdapter,
    *,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> ProfiledChangeRecord:
    """Execute one plan; callers, not this module, grant runtime authority."""
    blocked = _stage("pre-write verification blocked", attempted=True, succeeded=False)
    if re.fullmatch(r"sha256:[0-9a-f]{64}", approval_digest) is None:
        raise ValueError("approval digest is invalid")
    if approval_digest != plan.digest:
        raise ProfiledExecutionError(
            FinalOutcome.BLOCKED, "approval digest does not match plan"
        )
    if not plan.verify_digest():
        message = "plan digest is invalid"
        return _record(
            plan,
            approval_digest,
            FinalOutcome.BLOCKED,
            preflight=blocked.model_copy(update={"message": message}),
            now=now,
        )
    try:
        if (
            plan.operation_admission.transport_family
            is TransportFamily.ANSIBLE_NETWORK_CLI
        ):
            writer.verify_cisco_runtime()
    except DeploymentRuntimeError:
        return _record(
            plan,
            approval_digest,
            FinalOutcome.BLOCKED,
            preflight=blocked.model_copy(
                update={
                    "message": "deployment Ansible runtime prerequisites unavailable"
                }
            ),
            now=now,
        )
    try:
        device, _interface, credentials, state = _preflight(
            plan, inventory, secrets, collector
        )
        target = ProfiledWriteTarget.from_preflight(
            device, plan.interface, ProfiledOperation.INTERFACE_DESCRIPTION
        )
    except ProfiledExecutionError as error:
        return _record(
            plan,
            approval_digest,
            error.outcome,
            preflight=blocked.model_copy(update={"message": str(error)}),
            now=now,
        )
    preflight = _stage(
        "fresh profiled identity and preconditions verified",
        attempted=True,
        succeeded=True,
        observed_description=state.description,
    )
    if isinstance(plan.execution_artifact, CiscoConfigArtifact):
        result = writer.execute_cisco(target, credentials, plan.execution_artifact)
        execution = _stage(
            result.message,
            attempted=True,
            succeeded=result.disposition is ExecutionDisposition.SUCCEEDED,
            changed=result.changed,
        )
        if result.disposition is not ExecutionDisposition.SUCCEEDED:
            if result.disposition is ExecutionDisposition.AMBIGUOUS:
                try:
                    reconciled = collector.collect(
                        device.live_read_only_target(), credentials, plan.interface.name
                    )
                    post = _stage(
                        "reconciliation observation collected",
                        attempted=True,
                        succeeded=True,
                        observed_description=reconciled.description,
                        changed=_observed_transition(plan, reconciled),
                    )
                except (ValueError, OSError, RuntimeError):
                    post = _stage(
                        "reconciliation observation unavailable",
                        attempted=True,
                        succeeded=False,
                    )
                return _record(
                    plan,
                    approval_digest,
                    FinalOutcome.AMBIGUOUS,
                    preflight=preflight,
                    execution=execution,
                    post=post,
                    now=now,
                )
            return _record(
                plan,
                approval_digest,
                FinalOutcome.EXECUTION_FAILED,
                preflight=preflight,
                execution=execution,
                now=now,
            )
        try:
            observed = collector.collect(
                device.live_read_only_target(), credentials, plan.interface.name
            )
        except (ValueError, OSError, RuntimeError):
            return _record(
                plan,
                approval_digest,
                FinalOutcome.POST_VALIDATION_FAILED,
                preflight=preflight,
                execution=execution,
                post=_stage("post collection failed", attempted=True, succeeded=False),
                now=now,
            )
        identity = (
            observed.observed_hostname == plan.expected_hostname
            and observed.interface == plan.interface.name
            and observed.exists
        )
        if identity and observed.description == plan.desired_description:
            return _record(
                plan,
                approval_digest,
                FinalOutcome.SUCCEEDED,
                preflight=preflight,
                execution=execution,
                post=_stage(
                    "desired state observed",
                    attempted=True,
                    succeeded=True,
                    observed_description=observed.description,
                    changed=_observed_transition(plan, observed),
                ),
                now=now,
            )
        if not identity:
            return _record(
                plan,
                approval_digest,
                FinalOutcome.POST_VALIDATION_FAILED,
                preflight=preflight,
                execution=execution,
                post=_stage(
                    "post identity mismatch",
                    attempted=True,
                    succeeded=False,
                    observed_description=observed.description,
                    changed=_observed_transition(plan, observed),
                ),
                now=now,
            )
        recovery_result = writer.execute_cisco(
            target, credentials, plan.recovery_artifact
        )
        recovery = _stage(
            recovery_result.message,
            attempted=True,
            succeeded=recovery_result.disposition is ExecutionDisposition.SUCCEEDED,
            changed=recovery_result.changed,
        )
        post_failed = _stage(
            "desired state not observed",
            attempted=True,
            succeeded=False,
            observed_description=observed.description,
            changed=_observed_transition(plan, observed),
        )
        if recovery_result.disposition is ExecutionDisposition.AMBIGUOUS:
            return _record(
                plan,
                approval_digest,
                FinalOutcome.RECOVERY_AMBIGUOUS,
                preflight=preflight,
                execution=execution,
                post=post_failed,
                recovery=recovery,
                now=now,
            )
        if recovery_result.disposition is ExecutionDisposition.FAILED:
            return _record(
                plan,
                approval_digest,
                FinalOutcome.RECOVERY_FAILED,
                preflight=preflight,
                execution=execution,
                post=post_failed,
                recovery=recovery,
                now=now,
            )
        try:
            restored = collector.collect(
                device.live_read_only_target(), credentials, plan.interface.name
            )
        except (ValueError, OSError, RuntimeError):
            return _record(
                plan,
                approval_digest,
                FinalOutcome.RECOVERY_FAILED,
                preflight=preflight,
                execution=execution,
                post=post_failed,
                recovery=recovery,
                now=now,
            )
        outcome = (
            FinalOutcome.RECOVERED
            if restored.description == plan.current_description
            and restored.observed_hostname == plan.expected_hostname
            and restored.interface == plan.interface.name
            and restored.exists
            else FinalOutcome.RECOVERY_FAILED
        )
        return _record(
            plan,
            approval_digest,
            outcome,
            preflight=preflight,
            execution=execution,
            post=post_failed,
            recovery=recovery.model_copy(
                update={
                    "succeeded": outcome is FinalOutcome.RECOVERED,
                    "observed_description": restored.description,
                }
            ),
            now=now,
        )
    artifact = plan.execution_artifact
    if not isinstance(artifact, JunosConfigArtifact):
        return _record(
            plan, approval_digest, FinalOutcome.BLOCKED, preflight=blocked, now=now
        )
    transaction_context = writer.junos_transaction(target, credentials, artifact)
    entered = False
    try:
        transaction = transaction_context.__enter__()
        entered = True
    except (ValueError, OSError, RuntimeError):
        return _record(
            plan,
            approval_digest,
            FinalOutcome.BLOCKED,
            preflight=preflight,
            candidate=_stage(
                "candidate preparation blocked", attempted=True, succeeded=False
            ),
            now=now,
        )
    if not entered:
        raise RuntimeError("profiled transaction entry invariant failed")
    try:
        prepared = transaction.prepare()
    except (ValueError, OSError, RuntimeError):
        cleanup_message = "candidate preparation blocked"
        try:
            transaction_context.__exit__(None, None, None)
        except Exception:
            cleanup_message = "candidate preparation blocked; cleanup or unlock failed"
        return _record(
            plan,
            approval_digest,
            FinalOutcome.BLOCKED,
            preflight=preflight,
            candidate=_stage(cleanup_message, attempted=True, succeeded=False),
            now=now,
        )
    candidate = _stage(
        "candidate validated", attempted=True, succeeded=True, changed=True
    )
    try:
        committed = transaction.commit_confirmed(5)
    except Exception:
        with suppress(Exception):
            transaction_context.__exit__(None, None, None)
        return _record(
            plan,
            approval_digest,
            FinalOutcome.AMBIGUOUS,
            preflight=preflight,
            candidate=candidate,
            diff=prepared.diff_sha256,
            execution=_stage(
                "commit-confirmed outcome is ambiguous", attempted=True, succeeded=False
            ),
            now=now,
        )
    try:
        transaction_context.__exit__(None, None, None)
    except Exception:
        transaction.close_failed = True
    execution = _stage(
        committed.message,
        attempted=True,
        succeeded=committed.disposition is ExecutionDisposition.SUCCEEDED,
        changed=committed.changed,
    )
    if committed.disposition is ExecutionDisposition.AMBIGUOUS:
        return _record(
            plan,
            approval_digest,
            FinalOutcome.AMBIGUOUS,
            preflight=preflight,
            candidate=candidate,
            diff=prepared.diff_sha256,
            execution=execution,
            now=now,
        )
    if committed.disposition is ExecutionDisposition.FAILED:
        return _record(
            plan,
            approval_digest,
            FinalOutcome.EXECUTION_FAILED,
            preflight=preflight,
            candidate=candidate,
            diff=prepared.diff_sha256,
            execution=execution,
            now=now,
        )
    if getattr(transaction, "close_failed", False):
        return _record(
            plan,
            approval_digest,
            FinalOutcome.AUTO_ROLLBACK_PENDING,
            preflight=preflight,
            candidate=candidate,
            diff=prepared.diff_sha256,
            execution=execution,
            now=now,
        )
    try:
        observed = collector.collect(
            device.live_read_only_target(), credentials, plan.interface.name
        )
    except (ValueError, OSError, RuntimeError):
        observed = None
    if (
        observed is None
        or observed.observed_hostname != plan.expected_hostname
        or not observed.exists
        or observed.interface != plan.interface.name
        or observed.description != plan.desired_description
    ):
        return _record(
            plan,
            approval_digest,
            FinalOutcome.AUTO_ROLLBACK_PENDING,
            preflight=preflight,
            candidate=candidate,
            diff=prepared.diff_sha256,
            execution=execution,
            post=_stage(
                "temporary commit left unconfirmed",
                attempted=True,
                succeeded=False,
                observed_description=observed.description if observed else None,
                changed=_observed_transition(plan, observed),
            ),
            now=now,
        )
    confirmation_result = writer.confirm_junos(target, credentials)
    confirmation = _stage(
        confirmation_result.message,
        attempted=True,
        succeeded=confirmation_result.disposition is ExecutionDisposition.SUCCEEDED,
        changed=confirmation_result.changed,
    )
    outcome = (
        FinalOutcome.SUCCEEDED
        if confirmation_result.disposition is ExecutionDisposition.SUCCEEDED
        else (
            FinalOutcome.CONFIRMATION_AMBIGUOUS
            if confirmation_result.disposition is ExecutionDisposition.AMBIGUOUS
            else FinalOutcome.CONFIRMATION_FAILED
        )
    )
    return _record(
        plan,
        approval_digest,
        outcome,
        preflight=preflight,
        candidate=candidate,
        diff=prepared.diff_sha256,
        execution=execution,
        post=_stage(
            "desired state observed",
            attempted=True,
            succeeded=True,
            observed_description=observed.description,
            changed=_observed_transition(plan, observed),
        ),
        confirmation=confirmation,
        now=now,
    )
