"""Offline-testable schema-v2 execution lifecycle; intentionally no CLI surface."""

from __future__ import annotations

import re
from collections.abc import Callable
from contextlib import suppress
from datetime import UTC, datetime
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict

from network_change_delivery.architecture_contracts import (
    AutomationProfileID,
    NetworkOS,
    Sha256Digest,
    StableInterfaceIdentity,
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
    if not plan.verify_digest() or approval_digest != plan.digest:
        message = (
            "plan digest is invalid"
            if not plan.verify_digest()
            else "approval digest does not match plan"
        )
        return _record(
            plan,
            approval_digest,
            FinalOutcome.BLOCKED,
            preflight=blocked.model_copy(update={"message": message}),
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
                    post = _stage(
                        "reconciliation observation collected",
                        attempted=True,
                        succeeded=True,
                        observed_description=collector.collect(
                            device.live_read_only_target(),
                            credentials,
                            plan.interface.name,
                        ).description,
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
    try:
        transaction_context = writer.junos_transaction(target, credentials, artifact)
        transaction = transaction_context.__enter__()
        prepared = transaction.prepare()
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
        ),
        confirmation=confirmation,
        now=now,
    )
