"""Policy and vendor-native lifecycle orchestration for interface descriptions."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
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
    FrozenFleetMember,
    InterfaceDescriptionIntent,
    InterfaceState,
    InventoryDevice,
    JunosConfigArtifact,
    PlanPreconditions,
    StageResult,
)
from network_change_delivery.secrets import (
    CredentialReference,
    DeviceCredentials,
    SecretProvider,
)

MANAGEMENT_INTERFACE_NAMES = frozenset({"gigabitethernet1", "gi1"})
JUNOS_MANAGEMENT_INTERFACE_NAMES = frozenset({"fxp0", "em0"})


class SafetyError(ValueError):
    """Raised when the supported change cannot proceed safely."""


class PreflightError(SafetyError):
    """Typed internal failure from the shared read-only prewrite boundary."""

    def __init__(
        self,
        outcome: FinalOutcome,
        message: str,
        state: InterfaceState | None = None,
    ) -> None:
        super().__init__(message)
        self.outcome = outcome
        self.state = state


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


class JunosTransactionHandle(Protocol):
    close_failed: bool

    def prepare(self) -> object: ...

    def commit_confirmed(self, minutes: int) -> ExecutionResult: ...


class JunosTransactionExecutor(Protocol):
    """Boundary for the explicit Junos confirmed-commit phases."""

    def transaction(
        self,
        device: InventoryDevice,
        credentials: DeviceCredentials,
        artifact: JunosConfigArtifact,
    ) -> AbstractContextManager[JunosTransactionHandle]: ...

    def confirm(
        self, device: InventoryDevice, credentials: DeviceCredentials
    ) -> ExecutionResult: ...


@dataclass(frozen=True)
class PlanningResult:
    """Either a deployable plan or an already-compliant result."""

    plan: DeploymentPlan | None
    state: InterfaceState
    credential: CredentialReference
    message: str


@dataclass(frozen=True)
class PreflightSnapshot:
    """Ephemeral verified state and credential material, never evidence."""

    device: InventoryDevice
    credentials: DeviceCredentials
    state: InterfaceState


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
    if platform not in {"cisco_iosxe", "junos"}:
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
    if platform == "cisco_iosxe" and requested in MANAGEMENT_INTERFACE_NAMES:
        raise SafetyError("GigabitEthernet1 is protected for this lab target")
    if platform == "junos" and requested in JUNOS_MANAGEMENT_INTERFACE_NAMES:
        raise SafetyError(f"{intent.interface} is protected as Junos management")


def collect_preflight_state(
    binding: DeploymentPlan | FrozenFleetMember,
    inventory: InventoryProvider,
    secrets: SecretProvider,
    collector: StateCollector,
) -> PreflightSnapshot:
    """Apply the shared identity, credential, and live safety policy read-only."""
    try:
        device = inventory.resolve(binding.target, binding.interface)
    except (ValueError, OSError, RuntimeError):
        raise PreflightError(
            FinalOutcome.BLOCKED, "inventory resolution blocked"
        ) from None
    if (
        device.inventory_source != binding.inventory_source
        or device.inventory_object_id != binding.inventory_object_id
        or device.inventory_interface_object_id != binding.inventory_interface_object_id
        or device.name != binding.target
        or device.host != binding.host
        or device.port != binding.port
        or device.platform != binding.platform
        or device.expected_hostname != binding.expected_hostname
    ):
        raise PreflightError(
            FinalOutcome.STALE_PLAN,
            "approved inventory endpoint binding has changed",
        )
    try:
        current_credential = secrets.reference(device)
    except (ValueError, OSError, RuntimeError):
        raise PreflightError(
            FinalOutcome.BLOCKED, "credential reference resolution blocked"
        ) from None
    if (
        current_credential.source != binding.credential_source
        or current_credential.reference != binding.credential_reference
    ):
        raise PreflightError(
            FinalOutcome.STALE_PLAN, "approved credential binding has changed"
        )
    try:
        credentials = secrets.load(device)
    except (ValueError, OSError, RuntimeError):
        raise PreflightError(
            FinalOutcome.BLOCKED, "credential retrieval blocked"
        ) from None
    try:
        state = collector.collect(device, credentials, binding.interface)
    except (ValueError, OSError, RuntimeError):
        raise PreflightError(
            FinalOutcome.BLOCKED, "device state collection blocked"
        ) from None
    try:
        intent = InterfaceDescriptionIntent.model_validate(
            {
                "change_id": getattr(binding, "change_id", "fleet-preflight"),
                "kind": "interface_description",
                "target": binding.target,
                "interface": binding.interface,
                "desired": {"description": binding.desired_description},
            }
        )
        _assert_safe_state(intent, device, state)
    except (ValueError, OSError, RuntimeError):
        raise PreflightError(
            FinalOutcome.BLOCKED, "live safety validation blocked"
        ) from None
    return PreflightSnapshot(device=device, credentials=credentials, state=state)


def build_plan(
    intent: InterfaceDescriptionIntent,
    device: InventoryDevice,
    state: InterfaceState,
    *,
    credential: CredentialReference,
    created_at: datetime | None = None,
) -> DeploymentPlan:
    """Build and digest the exact immutable artifact from fresh safe state."""
    _assert_safe_state(intent, device, state)
    if (
        device.inventory_source == "netbox"
        and device.inventory_interface_object_id is None
    ):
        raise SafetyError("NetBox requested interface identity is missing")
    if state.description is not None:
        try:
            DesiredDescription(description=state.description)
        except ValueError as error:
            raise SafetyError(
                "observed description is unsafe for targeted recovery"
            ) from error
    if state.description == intent.desired.description:
        raise SafetyError("interface is already compliant")
    if device.platform == "junos":
        from network_change_delivery.models import render_junos_interface_description

        execution: CiscoConfigArtifact | JunosConfigArtifact = JunosConfigArtifact(
            interface=intent.interface,
            description=intent.desired.description,
            xml=render_junos_interface_description(
                intent.interface, intent.desired.description
            ),
        )
        recovery = None
        strategy = "junos_commit_confirmed"
        confirmed_timeout = 5
        confirmation = "confirm_previous_commit"
    else:
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
        strategy = "cisco_targeted_inverse"
        confirmed_timeout = None
        confirmation = None
    plan = DeploymentPlan(
        change_id=intent.change_id,
        kind=intent.kind,
        target=intent.target,
        inventory_source=device.inventory_source,
        inventory_object_id=device.inventory_object_id,
        inventory_interface_object_id=device.inventory_interface_object_id,
        credential_source=credential.source,
        credential_reference=credential.reference,
        host=device.host,
        port=device.port,
        expected_hostname=device.expected_hostname,
        platform=device.platform,
        interface=intent.interface,
        current_description=state.description,
        desired_description=intent.desired.description,
        transaction_strategy=strategy,
        confirmed_timeout_minutes=confirmed_timeout,
        confirmation_operation=confirmation,
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
    device = inventory.resolve(intent.target, intent.interface)
    if (
        device.inventory_source == "netbox"
        and device.inventory_interface_object_id is None
    ):
        raise SafetyError("NetBox requested interface identity is missing")
    credential = secrets.reference(device)
    credentials = secrets.load(device)
    state = collector.collect(device, credentials, intent.interface)
    _assert_safe_state(intent, device, state)
    if state.description == intent.desired.description:
        return PlanningResult(
            plan=None,
            state=state,
            credential=credential,
            message="interface is already compliant; no deployable artifact produced",
        )
    return PlanningResult(
        plan=build_plan(
            intent,
            device,
            state,
            created_at=created_at,
            credential=credential,
        ),
        state=state,
        credential=credential,
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
    candidate_validation: StageResult | None = None,
    candidate_diff_digest: str | None = None,
    confirmation: StageResult | None = None,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> ChangeRecord:
    return ChangeRecord(
        generated_at=now(),
        change_id=plan.change_id,
        plan_digest=plan.digest,
        target=plan.target,
        inventory_source=plan.inventory_source,
        inventory_object_id=plan.inventory_object_id,
        inventory_interface_object_id=plan.inventory_interface_object_id,
        credential_source=plan.credential_source,
        credential_reference=plan.credential_reference,
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
        transaction_strategy=plan.transaction_strategy,
        candidate_validation=candidate_validation,
        candidate_diff_digest=candidate_diff_digest,
        confirmation=confirmation,
        final_outcome=outcome,
        provider=(
            "pyez/netconf-exclusive"
            if plan.platform == "junos"
            else "ansible-runner/cisco.ios"
        ),
    )


def _deploy_junos(
    plan: DeploymentPlan,
    approval_digest: str,
    device: InventoryDevice,
    credentials: DeviceCredentials,
    collector: StateCollector,
    executor: JunosTransactionExecutor,
    preflight: StageResult,
    *,
    now: Callable[[], datetime],
) -> ChangeRecord:
    """Execute the bounded Junos confirmed-commit lifecycle without retries."""
    artifact = plan.execution_artifact
    if not isinstance(artifact, JunosConfigArtifact):
        return _record(
            plan, approval_digest, FinalOutcome.BLOCKED, preflight=preflight, now=now
        )
    transaction = None
    prepared = None
    committed = None
    try:
        with executor.transaction(device, credentials, artifact) as transaction:
            prepared = transaction.prepare()
            candidate = _stage(
                "candidate initially clean; commit check and semantic validation "
                "passed",
                attempted=True,
                succeeded=True,
                changed=True,
            )
            committed = transaction.commit_confirmed(
                plan.confirmed_timeout_minutes or 0
            )
    except (ValueError, OSError, RuntimeError):
        candidate = _stage(
            "candidate preparation blocked before active configuration change",
            attempted=True,
            succeeded=False,
        )
        return _record(
            plan,
            approval_digest,
            FinalOutcome.BLOCKED,
            preflight=preflight,
            candidate_validation=candidate,
            now=now,
        )
    candidate_diff_digest = getattr(prepared, "diff_sha256", None)
    if committed is None:
        return _record(
            plan,
            approval_digest,
            FinalOutcome.BLOCKED,
            preflight=preflight,
            candidate_validation=candidate,
            candidate_diff_digest=candidate_diff_digest,
            now=now,
        )
    execution = _stage(
        committed.message,
        attempted=True,
        succeeded=committed.disposition is ExecutionDisposition.SUCCEEDED,
        changed=committed.changed,
    )
    if committed.disposition is not ExecutionDisposition.SUCCEEDED:
        outcome = (
            FinalOutcome.AMBIGUOUS
            if committed.disposition is ExecutionDisposition.AMBIGUOUS
            else FinalOutcome.EXECUTION_FAILED
        )
        return _record(
            plan,
            approval_digest,
            outcome,
            preflight=preflight,
            candidate_validation=candidate,
            candidate_diff_digest=candidate_diff_digest,
            execution=execution,
            now=now,
        )
    if transaction is not None and getattr(transaction, "close_failed", False):
        return _record(
            plan,
            approval_digest,
            FinalOutcome.AUTO_ROLLBACK_PENDING,
            preflight=preflight,
            candidate_validation=candidate,
            candidate_diff_digest=candidate_diff_digest,
            execution=execution,
            post_validation=_stage(
                "temporary commit deliberately left unconfirmed after session "
                "close failure; automatic rollback expected",
                succeeded=False,
            ),
            now=now,
        )
    try:
        observed = collector.collect(device, credentials, plan.interface)
        valid = (
            observed.observed_hostname == plan.expected_hostname
            and observed.interface == plan.interface
            and observed.exists
            and observed.description == plan.desired_description
        )
    except (ValueError, OSError, RuntimeError):
        observed = None
        valid = False
    if not valid:
        post = _stage(
            "temporary commit deliberately left unconfirmed; "
            "automatic rollback expected",
            attempted=True,
            succeeded=False,
            observed_description=(observed.description if observed else None),
        )
        return _record(
            plan,
            approval_digest,
            FinalOutcome.AUTO_ROLLBACK_PENDING,
            preflight=preflight,
            candidate_validation=candidate,
            candidate_diff_digest=candidate_diff_digest,
            execution=execution,
            post_validation=post,
            now=now,
        )
    post = _stage(
        "fresh independent state matches desired configuration",
        attempted=True,
        succeeded=True,
        observed_description=observed.description,
    )
    confirmed = executor.confirm(device, credentials)
    confirmation = _stage(
        confirmed.message,
        attempted=True,
        succeeded=confirmed.disposition is ExecutionDisposition.SUCCEEDED,
        changed=confirmed.changed,
    )
    if confirmed.disposition is ExecutionDisposition.AMBIGUOUS:
        outcome = FinalOutcome.CONFIRMATION_AMBIGUOUS
    elif confirmed.disposition is ExecutionDisposition.FAILED:
        outcome = FinalOutcome.CONFIRMATION_FAILED
    else:
        outcome = FinalOutcome.SUCCEEDED
    return _record(
        plan,
        approval_digest,
        outcome,
        preflight=preflight,
        candidate_validation=candidate,
        candidate_diff_digest=candidate_diff_digest,
        execution=execution,
        post_validation=post,
        confirmation=confirmation,
        now=now,
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
        snapshot = collect_preflight_state(plan, inventory, secrets, collector)
    except PreflightError as error:
        return _record(
            plan,
            approval_digest,
            error.outcome,
            preflight=blocked.model_copy(update={"message": str(error)}),
            now=now,
        )
    device = snapshot.device
    credentials = snapshot.credentials
    state = snapshot.state

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
    if plan.platform == "junos":
        return _deploy_junos(
            plan,
            approval_digest,
            device,
            credentials,
            collector,
            executor,  # type: ignore[arg-type]
            preflight,
            now=now,
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
