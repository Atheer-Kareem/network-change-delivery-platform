"""Policy and lifecycle orchestration for the first Cisco vertical."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from network_change_delivery.inventory import InventoryProvider
from network_change_delivery.models import (
    ChangeRecord,
    CiscoConfigArtifact,
    DeploymentPlan,
    DesiredDescription,
    ExecutionDisposition,
    ExecutionResult,
    FinalOutcome,
    InterfaceDescriptionIntent,
    InterfaceState,
    InventoryDevice,
    PlanPreconditions,
    StageResult,
)
from network_change_delivery.secrets import DeviceCredentials, SecretProvider

MANAGEMENT_INTERFACE_NAMES = frozenset({"gigabitethernet1", "gi1"})


class SafetyError(ValueError):
    """Raised when the supported change cannot proceed safely."""


class StateCollector(Protocol):
    """Boundary for fresh device-state collection."""

    def collect(
        self,
        device: InventoryDevice,
        credentials: DeviceCredentials,
        interface: str,
    ) -> InterfaceState:
        """Collect and normalize fresh state for one interface."""


class ArtifactExecutor(Protocol):
    """Boundary for applying one exact Cisco artifact."""

    def execute(
        self,
        device: InventoryDevice,
        credentials: DeviceCredentials,
        artifact: CiscoConfigArtifact,
    ) -> ExecutionResult:
        """Apply exactly one approved artifact without retry."""


@dataclass(frozen=True)
class PlanningResult:
    """Either a deployable plan or an already-compliant result."""

    plan: DeploymentPlan | None
    state: InterfaceState
    message: str


def _normalized_interface(name: str) -> str:
    return "".join(name.split()).casefold()


def _assert_safe_state(
    intent: InterfaceDescriptionIntent,
    device: InventoryDevice,
    state: InterfaceState,
) -> None:
    expected_hostname = device.expected_hostname
    protected_interfaces = device.protected_interfaces
    platform = device.platform
    if platform != "cisco_iosxe":
        raise SafetyError("target platform is unsupported")
    if state.observed_hostname != expected_hostname:
        raise SafetyError("observed hostname does not match inventory identity")
    if state.interface != intent.interface:
        raise SafetyError("observed interface does not match requested interface")
    if not state.exists:
        raise SafetyError("requested interface does not exist")
    requested = _normalized_interface(intent.interface)
    protected = {_normalized_interface(name) for name in protected_interfaces}
    if state.protected or requested in protected:
        raise SafetyError("requested interface is protected by inventory policy")
    if requested in MANAGEMENT_INTERFACE_NAMES:
        raise SafetyError("GigabitEthernet1 is protected for this lab target")


def build_plan(
    intent: InterfaceDescriptionIntent,
    device: InventoryDevice,
    state: InterfaceState,
    *,
    created_at: datetime | None = None,
) -> DeploymentPlan:
    """Build and digest the exact immutable artifact from fresh safe state."""
    _assert_safe_state(intent, device, state)
    if state.description is not None:
        try:
            DesiredDescription(description=state.description)
        except ValueError as error:
            raise SafetyError(
                "observed description is unsafe for targeted recovery"
            ) from error
    if state.description == intent.desired.description:
        raise SafetyError("interface is already compliant")
    parent = f"interface {intent.interface}"
    execution = CiscoConfigArtifact(
        parent=parent,
        lines=(f"description {intent.desired.description}",),
    )
    recovery_line = (
        f"description {state.description}"
        if state.description is not None
        else "no description"
    )
    recovery = CiscoConfigArtifact(parent=parent, lines=(recovery_line,))
    plan = DeploymentPlan(
        change_id=intent.change_id,
        kind=intent.kind,
        target=intent.target,
        inventory_source=device.inventory_source,
        inventory_object_id=device.inventory_object_id,
        host=device.host,
        port=device.port,
        expected_hostname=device.expected_hostname,
        platform=device.platform,
        interface=intent.interface,
        current_description=state.description,
        desired_description=intent.desired.description,
        execution_artifact=execution,
        recovery_artifact=recovery,
        preconditions=PlanPreconditions(
            observed_hostname=state.observed_hostname,
            interface_exists=state.exists,
            interface_protected=state.protected,
            current_description=state.description,
        ),
        created_at=created_at or datetime.now(UTC),
        digest="sha256:pending",
    )
    return plan.model_copy(update={"digest": plan.calculated_digest()})


def plan_change(
    intent: InterfaceDescriptionIntent,
    inventory: InventoryProvider,
    secrets: SecretProvider,
    collector: StateCollector,
    *,
    created_at: datetime | None = None,
) -> PlanningResult:
    """Resolve, collect, preflight, and plan one explicit target."""
    device = inventory.resolve(intent.target)
    credentials = secrets.load()
    state = collector.collect(device, credentials, intent.interface)
    _assert_safe_state(intent, device, state)
    if state.description == intent.desired.description:
        return PlanningResult(
            plan=None,
            state=state,
            message="interface is already compliant; no deployable artifact produced",
        )
    return PlanningResult(
        plan=build_plan(intent, device, state, created_at=created_at),
        state=state,
        message="deployable immutable plan created",
    )


def _stage(
    message: str,
    *,
    attempted: bool = False,
    succeeded: bool | None = None,
    changed: bool | None = None,
    observed_description: str | None = None,
) -> StageResult:
    return StageResult(
        attempted=attempted,
        succeeded=succeeded,
        changed=changed,
        observed_description=observed_description,
        message=message,
    )


def _record(
    plan: DeploymentPlan,
    approval_digest: str,
    outcome: FinalOutcome,
    *,
    preflight: StageResult,
    execution: StageResult | None = None,
    post_validation: StageResult | None = None,
    recovery: StageResult | None = None,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> ChangeRecord:
    return ChangeRecord(
        generated_at=now(),
        change_id=plan.change_id,
        plan_digest=plan.digest,
        target=plan.target,
        inventory_source=plan.inventory_source,
        inventory_object_id=plan.inventory_object_id,
        host=plan.host,
        port=plan.port,
        expected_hostname=plan.expected_hostname,
        platform=plan.platform,
        interface=plan.interface,
        previous_description=plan.current_description,
        desired_description=plan.desired_description,
        approval_digest=approval_digest,
        preflight=preflight,
        execution=execution or _stage("execution not attempted"),
        post_validation=post_validation or _stage("post-validation not attempted"),
        recovery=recovery or _stage("recovery not attempted"),
        final_outcome=outcome,
        provider="ansible-runner/cisco.ios",
    )


def deploy_plan(
    plan: DeploymentPlan,
    approval_digest: str,
    inventory: InventoryProvider,
    secrets: SecretProvider,
    collector: StateCollector,
    executor: ArtifactExecutor,
    *,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> ChangeRecord:
    """Verify, execute, validate, and recover one approved exact plan."""
    blocked = _stage("pre-write verification blocked", attempted=True, succeeded=False)
    if not plan.verify_digest():
        return _record(
            plan,
            approval_digest,
            FinalOutcome.BLOCKED,
            preflight=blocked.model_copy(update={"message": "plan digest is invalid"}),
            now=now,
        )
    if approval_digest != plan.digest:
        return _record(
            plan,
            approval_digest,
            FinalOutcome.BLOCKED,
            preflight=blocked.model_copy(
                update={"message": "approval digest does not match plan"}
            ),
            now=now,
        )

    try:
        device = inventory.resolve(plan.target)
    except (ValueError, OSError, RuntimeError):
        return _record(
            plan,
            approval_digest,
            FinalOutcome.BLOCKED,
            preflight=blocked,
            now=now,
        )
    if (
        device.inventory_source != plan.inventory_source
        or device.inventory_object_id != plan.inventory_object_id
        or device.name != plan.target
        or device.host != plan.host
        or device.port != plan.port
        or device.platform != plan.platform
        or device.expected_hostname != plan.expected_hostname
    ):
        return _record(
            plan,
            approval_digest,
            FinalOutcome.STALE_PLAN,
            preflight=blocked.model_copy(
                update={"message": "approved inventory endpoint binding has changed"}
            ),
            now=now,
        )

    try:
        credentials = secrets.load()
        state = collector.collect(device, credentials, plan.interface)
        intent = InterfaceDescriptionIntent.model_validate(
            {
                "change_id": plan.change_id,
                "kind": plan.kind,
                "target": plan.target,
                "interface": plan.interface,
                "desired": {"description": plan.desired_description},
            }
        )
        _assert_safe_state(intent, device, state)
    except (ValueError, OSError, RuntimeError):
        return _record(
            plan,
            approval_digest,
            FinalOutcome.BLOCKED,
            preflight=blocked,
            now=now,
        )

    if (
        state.description != plan.current_description
        or state.observed_hostname != plan.preconditions.observed_hostname
        or not state.exists
    ):
        return _record(
            plan,
            approval_digest,
            FinalOutcome.STALE_PLAN,
            preflight=_stage(
                "approved preconditions no longer match live state",
                attempted=True,
                succeeded=False,
                observed_description=state.description,
            ),
            now=now,
        )

    preflight = _stage(
        "fresh identity and interface preconditions verified",
        attempted=True,
        succeeded=True,
        observed_description=state.description,
    )
    result = executor.execute(device, credentials, plan.execution_artifact)
    execution = _stage(
        result.message,
        attempted=True,
        succeeded=result.disposition is ExecutionDisposition.SUCCEEDED,
        changed=result.changed,
    )
    if result.disposition is ExecutionDisposition.AMBIGUOUS:
        try:
            ambiguous_state = collector.collect(device, credentials, plan.interface)
            ambiguous_observation = _stage(
                "read-only observation collected after ambiguous write",
                attempted=True,
                succeeded=True,
                observed_description=ambiguous_state.description,
            )
        except (ValueError, OSError, RuntimeError):
            ambiguous_observation = _stage(
                "read-only observation unavailable after ambiguous write",
                attempted=True,
                succeeded=False,
            )
        return _record(
            plan,
            approval_digest,
            FinalOutcome.AMBIGUOUS,
            preflight=preflight,
            execution=execution,
            post_validation=ambiguous_observation,
            now=now,
        )
    if result.disposition is ExecutionDisposition.FAILED:
        return _record(
            plan,
            approval_digest,
            FinalOutcome.EXECUTION_FAILED,
            preflight=preflight,
            execution=execution,
            now=now,
        )

    try:
        observed = collector.collect(device, credentials, plan.interface)
    except (ValueError, OSError, RuntimeError):
        return _record(
            plan,
            approval_digest,
            FinalOutcome.POST_VALIDATION_FAILED,
            preflight=preflight,
            execution=execution,
            post_validation=_stage(
                "fresh post-write collection failed; operator investigation required",
                attempted=True,
                succeeded=False,
            ),
            now=now,
        )
    post_identity_matches = (
        observed.observed_hostname == plan.expected_hostname
        and observed.interface == plan.interface
        and observed.exists
    )
    if post_identity_matches and observed.description == plan.desired_description:
        return _record(
            plan,
            approval_digest,
            FinalOutcome.SUCCEEDED,
            preflight=preflight,
            execution=execution,
            post_validation=_stage(
                "fresh observed description matches desired state",
                attempted=True,
                succeeded=True,
                observed_description=observed.description,
            ),
            now=now,
        )

    if not post_identity_matches:
        return _record(
            plan,
            approval_digest,
            FinalOutcome.POST_VALIDATION_FAILED,
            preflight=preflight,
            execution=execution,
            post_validation=_stage(
                "post-write identity or interface mismatch; "
                "operator investigation required",
                attempted=True,
                succeeded=False,
                observed_description=observed.description,
            ),
            now=now,
        )

    post_validation = _stage(
        "fresh observed description does not match desired state",
        attempted=True,
        succeeded=False,
        observed_description=observed.description,
    )
    recovery_result = executor.execute(device, credentials, plan.recovery_artifact)
    recovery_stage = _stage(
        recovery_result.message,
        attempted=True,
        succeeded=recovery_result.disposition is ExecutionDisposition.SUCCEEDED,
        changed=recovery_result.changed,
    )
    if recovery_result.disposition is ExecutionDisposition.AMBIGUOUS:
        return _record(
            plan,
            approval_digest,
            FinalOutcome.RECOVERY_AMBIGUOUS,
            preflight=preflight,
            execution=execution,
            post_validation=post_validation,
            recovery=recovery_stage,
            now=now,
        )
    if recovery_result.disposition is ExecutionDisposition.FAILED:
        return _record(
            plan,
            approval_digest,
            FinalOutcome.RECOVERY_FAILED,
            preflight=preflight,
            execution=execution,
            post_validation=post_validation,
            recovery=recovery_stage,
            now=now,
        )

    try:
        recovered = collector.collect(device, credentials, plan.interface)
    except (ValueError, OSError, RuntimeError):
        return _record(
            plan,
            approval_digest,
            FinalOutcome.RECOVERY_FAILED,
            preflight=preflight,
            execution=execution,
            post_validation=post_validation,
            recovery=recovery_stage.model_copy(
                update={
                    "succeeded": False,
                    "message": (
                        "fresh recovery verification collection failed; "
                        "operator investigation required"
                    ),
                }
            ),
            now=now,
        )
    recovery_identity_matches = (
        recovered.observed_hostname == plan.expected_hostname
        and recovered.interface == plan.interface
        and recovered.exists
    )
    if recovery_identity_matches and recovered.description == plan.current_description:
        recovery_stage = recovery_stage.model_copy(
            update={
                "succeeded": True,
                "observed_description": recovered.description,
                "message": "targeted recovery restored the previous description",
            }
        )
        outcome = FinalOutcome.RECOVERED
    else:
        recovery_stage = recovery_stage.model_copy(
            update={
                "succeeded": False,
                "observed_description": recovered.description,
                "message": "targeted recovery did not restore the previous description",
            }
        )
        outcome = FinalOutcome.RECOVERY_FAILED
    return _record(
        plan,
        approval_digest,
        outcome,
        preflight=preflight,
        execution=execution,
        post_validation=post_validation,
        recovery=recovery_stage,
        now=now,
    )
