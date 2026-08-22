"""Fleet planning, complete preflight, and sequential rollout domain policy."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Lock

from network_change_delivery.inventory import (
    FleetInventoryProvider,
    FleetPreflightInventoryProvider,
)
from network_change_delivery.models import (
    ChangeRecord,
    FinalOutcome,
    FleetChangeRecord,
    FleetCohortType,
    FleetDeploymentPlan,
    FleetDesiredStateValidationResult,
    FleetFinalOutcome,
    FleetInterfaceDescriptionIntent,
    FleetMemberClassification,
    FleetMemberExecution,
    FleetMemberPreflight,
    FleetPreflightResult,
    FrozenFleetMember,
    InterfaceDescriptionIntent,
    InterfaceState,
)
from network_change_delivery.secrets import CredentialReference, SecretProvider
from network_change_delivery.workflow import (
    ArtifactExecutor,
    PreflightError,
    StateCollector,
    _assert_safe_state,
    build_plan,
    collect_preflight_state,
    deploy_plan,
)


class FleetSafetyError(ValueError):
    """Raised when fleet planning cannot establish one safe frozen population."""


class ProcessLocalFleetLease:
    """Idempotently releases one atomically acquired in-process device set."""

    def __init__(
        self, controller: ProcessLocalFleetAdmission, identities: frozenset[str]
    ) -> None:
        self._controller = controller
        self._identities = identities
        self._released = False

    def release(self) -> None:
        if not self._released:
            self._controller._release(self._identities)
            self._released = True

    def __enter__(self) -> ProcessLocalFleetLease:
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.release()


class ProcessLocalFleetAdmission:
    """Thread-safe, all-or-nothing admission for stable device identities."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._held: set[str] = set()

    def acquire(
        self, device_identities: tuple[str, ...]
    ) -> ProcessLocalFleetLease | None:
        identities = frozenset(device_identities)
        if not identities or len(identities) != len(device_identities):
            raise ValueError("fleet admission requires unique stable device identities")
        with self._lock:
            if self._held.intersection(identities):
                return None
            self._held.update(identities)
        return ProcessLocalFleetLease(self, identities)

    def _release(self, identities: frozenset[str]) -> None:
        with self._lock:
            self._held.difference_update(identities)


PROCESS_LOCAL_FLEET_ADMISSION = ProcessLocalFleetAdmission()


@dataclass(frozen=True)
class FleetPlanningResult:
    """Fleet plan or complete already-compliant member observations."""

    plan: FleetDeploymentPlan | None
    members: tuple[FrozenFleetMember, ...]
    message: str


def _member_key(member: FrozenFleetMember) -> tuple[str, str, str]:
    return (
        member.inventory_object_id,
        member.target,
        member.inventory_interface_object_id,
    )


def _child_intent(
    intent: FleetInterfaceDescriptionIntent, target: str, interface: str
) -> InterfaceDescriptionIntent:
    return InterfaceDescriptionIntent(
        change_id=intent.change_id,
        kind=intent.kind,
        target=target,
        interface=interface,
        desired=intent.desired,
    )


def _freeze_member(
    intent: FleetInterfaceDescriptionIntent,
    device,
    interface: str,
    state: InterfaceState,
    credential: CredentialReference,
    *,
    created_at: datetime,
) -> FrozenFleetMember:
    child_intent = _child_intent(intent, device.name, interface)
    _assert_safe_state(child_intent, device, state)
    compliant = state.description == intent.desired.description
    child = None
    if not compliant:
        child = build_plan(
            child_intent,
            device,
            state,
            credential=credential,
            created_at=created_at,
        )
    if (
        device.inventory_object_id is None
        or device.inventory_interface_object_id is None
    ):
        raise FleetSafetyError("fleet member stable inventory identity is missing")
    return FrozenFleetMember(
        target=device.name,
        inventory_source="netbox",
        inventory_object_id=device.inventory_object_id,
        inventory_interface_object_id=device.inventory_interface_object_id,
        host=device.host,
        port=device.port,
        expected_hostname=device.expected_hostname,
        platform=device.platform,
        interface=interface,
        credential_source=credential.source,
        credential_reference=credential.reference,
        classification=(
            FleetMemberClassification.COMPLIANT
            if compliant
            else FleetMemberClassification.DEPLOYABLE
        ),
        current_description=state.description,
        desired_description=intent.desired.description,
        child_plan=child,
    )


def plan_fleet(
    intent: FleetInterfaceDescriptionIntent,
    inventory: FleetInventoryProvider,
    secrets: SecretProvider,
    collector: StateCollector,
    *,
    created_at: datetime | None = None,
) -> FleetPlanningResult:
    """Resolve, observe, freeze, and digest one complete exact fleet."""
    created = created_at or datetime.now(UTC)
    try:
        selected = inventory.resolve_fleet(intent.selector)
    except (ValueError, OSError, RuntimeError):
        raise FleetSafetyError("fleet selector resolution failed") from None
    members: list[FrozenFleetMember] = []
    try:
        for device, interface in selected:
            credential = secrets.reference(device)
            credentials = secrets.load(device)
            state = collector.collect(device, credentials, interface)
            members.append(
                _freeze_member(
                    intent,
                    device,
                    interface,
                    state,
                    credential,
                    created_at=created,
                )
            )
    except (ValueError, OSError, RuntimeError):
        raise FleetSafetyError("complete fleet planning preflight failed") from None
    frozen = tuple(sorted(members, key=_member_key))
    deployable = tuple(
        member
        for member in frozen
        if member.classification is FleetMemberClassification.DEPLOYABLE
    )
    if not deployable:
        return FleetPlanningResult(
            plan=None,
            members=frozen,
            message="fleet is already compliant; no deployable artifact produced",
        )
    platforms = sorted({member.platform for member in deployable})
    canaries = tuple(
        min(
            (member for member in deployable if member.platform == platform),
            key=_member_key,
        ).inventory_object_id
        for platform in platforms
    )
    remaining = sorted(
        (
            member
            for member in deployable
            if member.inventory_object_id not in set(canaries)
        ),
        key=_member_key,
    )
    waves = tuple(
        tuple(
            member.inventory_object_id
            for member in remaining[index : index + intent.rollout.wave_size]
        )
        for index in range(0, len(remaining), intent.rollout.wave_size)
    )
    plan = FleetDeploymentPlan(
        change_id=intent.change_id,
        kind=intent.kind,
        selector=intent.selector,
        desired_description=intent.desired.description,
        rollout=intent.rollout,
        members=frozen,
        canaries=canaries,
        waves=waves,
        created_at=created,
        digest="sha256:" + "0" * 64,
    )
    plan = plan.model_copy(update={"digest": plan.calculated_digest()})
    return FleetPlanningResult(
        plan=plan,
        members=frozen,
        message="deployable immutable fleet plan created",
    )


def preflight_fleet(
    plan: FleetDeploymentPlan,
    inventory: FleetPreflightInventoryProvider,
    secrets: SecretProvider,
    collector: StateCollector,
    *,
    approval_digest: str | None = None,
) -> FleetPreflightResult:
    """Re-resolve and freshly verify every member without any execution boundary."""
    approval_error = validate_fleet_approval(plan, approval_digest)
    if approval_error is not None:
        return FleetPreflightResult(
            fleet_digest=plan.digest,
            succeeded=False,
            members=(),
            message=approval_error,
        )
    try:
        selected = inventory.resolve_fleet(plan.selector)
    except (ValueError, OSError, RuntimeError):
        return FleetPreflightResult(
            fleet_digest=plan.digest,
            succeeded=False,
            members=(),
            message="fleet selector re-resolution failed",
        )
    frozen_membership = {
        (member.inventory_object_id, member.inventory_interface_object_id)
        for member in plan.members
    }
    current_membership = {
        (device.inventory_object_id, device.inventory_interface_object_id)
        for device, _interface in selected
    }
    if current_membership != frozen_membership or len(selected) != len(plan.members):
        return FleetPreflightResult(
            fleet_digest=plan.digest,
            succeeded=False,
            members=(),
            message="fleet selector membership has changed",
        )
    results: list[FleetMemberPreflight] = []
    for member in plan.members:
        succeeded = False
        observed_description = None
        message = "fleet member preflight blocked"
        try:
            snapshot = collect_preflight_state(
                member,
                inventory,
                secrets,
                collector,
            )
            observed_description = snapshot.state.description
            if member.classification is FleetMemberClassification.DEPLOYABLE:
                child = member.child_plan
                succeeded = bool(
                    child is not None
                    and child.verify_digest()
                    and snapshot.state.description == child.current_description
                    and snapshot.state.observed_hostname
                    == child.preconditions.observed_hostname
                    and snapshot.state.exists
                    and not snapshot.state.protected
                )
                message = (
                    "approved child preconditions verified"
                    if succeeded
                    else "approved child preconditions have changed"
                )
            else:
                succeeded = snapshot.state.description == plan.desired_description
                message = (
                    "compliant member remains at desired state"
                    if succeeded
                    else "compliant member is no longer compliant"
                )
        except PreflightError as error:
            message = str(error)
        results.append(
            FleetMemberPreflight(
                inventory_object_id=member.inventory_object_id,
                inventory_interface_object_id=member.inventory_interface_object_id,
                target=member.target,
                interface=member.interface,
                classification=member.classification,
                succeeded=succeeded,
                observed_description=observed_description,
                message=message,
            )
        )
    complete = all(result.succeeded for result in results)
    return FleetPreflightResult(
        fleet_digest=plan.digest,
        succeeded=complete,
        members=tuple(results),
        message=(
            "complete fleet read-only preflight succeeded"
            if complete
            else "complete fleet read-only preflight failed"
        ),
    )


def validate_fleet_approval(
    plan: FleetDeploymentPlan, approval_digest: str | None
) -> str | None:
    """Return one bounded pure approval failure without provider contact."""
    if not plan.verify_digest():
        return "fleet plan digest is invalid"
    if approval_digest is not None and approval_digest != plan.digest:
        return "approval digest does not match fleet plan"
    return None


def validate_fleet_desired_state(
    plan: FleetDeploymentPlan,
    inventory: FleetPreflightInventoryProvider,
    secrets: SecretProvider,
    collector: StateCollector,
) -> FleetDesiredStateValidationResult:
    """Freshly verify exact membership and desired state after all child successes."""
    try:
        selected = inventory.resolve_fleet(plan.selector)
    except (ValueError, OSError, RuntimeError):
        return FleetDesiredStateValidationResult(
            attempted=True,
            succeeded=False,
            members=(),
            message="final fleet selector re-resolution failed",
        )
    frozen_membership = {
        (member.inventory_object_id, member.inventory_interface_object_id)
        for member in plan.members
    }
    current_membership = {
        (device.inventory_object_id, device.inventory_interface_object_id)
        for device, _interface in selected
    }
    if current_membership != frozen_membership or len(selected) != len(plan.members):
        return FleetDesiredStateValidationResult(
            attempted=True,
            succeeded=False,
            members=(),
            message="final fleet selector membership has changed",
        )
    results: list[FleetMemberPreflight] = []
    for member in plan.members:
        succeeded = False
        observed_description = None
        message = "final desired-state validation blocked"
        try:
            snapshot = collect_preflight_state(member, inventory, secrets, collector)
            observed_description = snapshot.state.description
            succeeded = snapshot.state.description == plan.desired_description
            message = (
                "fresh member state matches fleet desired description"
                if succeeded
                else "fresh member state does not match fleet desired description"
            )
        except PreflightError:
            pass
        results.append(
            FleetMemberPreflight(
                inventory_object_id=member.inventory_object_id,
                inventory_interface_object_id=member.inventory_interface_object_id,
                target=member.target,
                interface=member.interface,
                classification=member.classification,
                succeeded=succeeded,
                observed_description=observed_description,
                message=message,
            )
        )
    complete = all(result.succeeded for result in results)
    return FleetDesiredStateValidationResult(
        attempted=True,
        succeeded=complete,
        members=tuple(results),
        message=(
            "final whole-fleet desired-state validation succeeded"
            if complete
            else "final whole-fleet desired-state validation failed"
        ),
    )


def _cohort_binding(
    plan: FleetDeploymentPlan, identity: str
) -> tuple[FleetCohortType, int | None]:
    if identity in plan.canaries:
        return FleetCohortType.CANARY, None
    for index, wave in enumerate(plan.waves, start=1):
        if identity in wave:
            return FleetCohortType.WAVE, index
    return FleetCohortType.COMPLIANT, None


def _execution_evidence(
    plan: FleetDeploymentPlan,
    records: dict[str, tuple[int, ChangeRecord]],
    *,
    stopped: bool,
) -> tuple[FleetMemberExecution, ...]:
    evidence: list[FleetMemberExecution] = []
    for member in plan.members:
        cohort, wave_index = _cohort_binding(plan, member.inventory_object_id)
        attempted = member.inventory_object_id in records
        sequence, child_record = records.get(member.inventory_object_id, (None, None))
        child_digest = (
            member.child_plan.digest if member.child_plan is not None else None
        )
        evidence.append(
            FleetMemberExecution(
                inventory_object_id=member.inventory_object_id,
                inventory_interface_object_id=member.inventory_interface_object_id,
                target=member.target,
                interface=member.interface,
                platform=member.platform,
                classification=member.classification,
                cohort=cohort,
                wave_index=wave_index,
                child_plan_digest=child_digest,
                attempt_sequence=sequence,
                attempted=attempted,
                child_record=child_record,
                message=(
                    "compliant no-op; no child deployment required"
                    if member.classification is FleetMemberClassification.COMPLIANT
                    else "child deployment attempted"
                    if attempted
                    else "not attempted because fleet rollout stopped"
                    if stopped
                    else "not attempted because fleet rollout was blocked"
                ),
            )
        )
    return tuple(evidence)


def deploy_fleet(
    plan: FleetDeploymentPlan,
    approval_digest: str,
    inventory: FleetPreflightInventoryProvider,
    secrets: SecretProvider,
    collector: StateCollector,
    executor: ArtifactExecutor,
    *,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    child_deployer: Callable[..., ChangeRecord] = deploy_plan,
    admission: ProcessLocalFleetAdmission = PROCESS_LOCAL_FLEET_ADMISSION,
) -> FleetChangeRecord:
    """Admit the exact device set, then execute the unchanged fleet state machine."""
    approval_error = validate_fleet_approval(plan, approval_digest)
    if approval_error is not None:
        preflight = FleetPreflightResult(
            fleet_digest=plan.digest,
            succeeded=False,
            members=(),
            message=approval_error,
        )
        return _blocked_fleet_record(plan, approval_digest, preflight, now=now)
    identities = tuple(member.inventory_object_id for member in plan.members)
    lease = admission.acquire(identities)
    if lease is None:
        preflight = FleetPreflightResult(
            fleet_digest=plan.digest,
            succeeded=False,
            members=(),
            message="process-local fleet target admission blocked",
        )
        return _blocked_fleet_record(plan, approval_digest, preflight, now=now)
    with lease:
        return _deploy_admitted_fleet(
            plan,
            approval_digest,
            inventory,
            secrets,
            collector,
            executor,
            now=now,
            child_deployer=child_deployer,
        )


def _blocked_fleet_record(
    plan: FleetDeploymentPlan,
    approval_digest: str,
    preflight: FleetPreflightResult,
    *,
    now: Callable[[], datetime],
) -> FleetChangeRecord:
    return FleetChangeRecord(
        generated_at=now(),
        change_id=plan.change_id,
        fleet_plan_digest=plan.digest,
        approval_digest=approval_digest,
        selector=plan.selector,
        rollout=plan.rollout,
        canaries=plan.canaries,
        waves=plan.waves,
        preflight=preflight,
        fleet_plan=plan,
        members=_execution_evidence(plan, {}, stopped=False),
        final_validation=_not_attempted_validation(),
        final_outcome=FleetFinalOutcome.BLOCKED,
    )


def _not_attempted_validation() -> FleetDesiredStateValidationResult:
    return FleetDesiredStateValidationResult(
        attempted=False,
        succeeded=None,
        members=(),
        message="final fleet validation not attempted",
    )


def _deploy_admitted_fleet(
    plan: FleetDeploymentPlan,
    approval_digest: str,
    inventory: FleetPreflightInventoryProvider,
    secrets: SecretProvider,
    collector: StateCollector,
    executor: ArtifactExecutor,
    *,
    now: Callable[[], datetime],
    child_deployer: Callable[..., ChangeRecord],
) -> FleetChangeRecord:
    """Run 5B unchanged while the caller holds the complete device lease."""
    not_attempted_validation = _not_attempted_validation()
    preflight = preflight_fleet(
        plan,
        inventory,
        secrets,
        collector,
        approval_digest=approval_digest,
    )
    if not preflight.succeeded:
        return _blocked_fleet_record(plan, approval_digest, preflight, now=now)

    by_id = {member.inventory_object_id: member for member in plan.members}
    order = [*plan.canaries, *(identity for wave in plan.waves for identity in wave)]
    records: dict[str, tuple[int, ChangeRecord]] = {}
    stop_identity = None
    stop_outcome = None
    for sequence, identity in enumerate(order, start=1):
        member = by_id[identity]
        child = member.child_plan
        if child is None:  # FleetDeploymentPlan validation makes this unreachable.
            break
        record = child_deployer(
            child,
            child.digest,
            inventory,
            secrets,
            collector,
            executor,
            now=now,
        )
        records[identity] = (sequence, record)
        if record.final_outcome is not FinalOutcome.SUCCEEDED:
            stop_identity = identity
            stop_outcome = record.final_outcome
            break
    if stop_identity is not None:
        prior_success = any(
            record.final_outcome is FinalOutcome.SUCCEEDED
            for _sequence, record in records.values()
        )
        return FleetChangeRecord(
            generated_at=now(),
            change_id=plan.change_id,
            fleet_plan_digest=plan.digest,
            approval_digest=approval_digest,
            selector=plan.selector,
            rollout=plan.rollout,
            canaries=plan.canaries,
            waves=plan.waves,
            preflight=preflight,
            fleet_plan=plan,
            members=_execution_evidence(plan, records, stopped=True),
            stop_member_identity=stop_identity,
            stop_child_outcome=stop_outcome,
            final_validation=not_attempted_validation,
            final_outcome=(
                FleetFinalOutcome.PARTIAL
                if prior_success
                else FleetFinalOutcome.STOPPED
            ),
        )

    final_validation = validate_fleet_desired_state(plan, inventory, secrets, collector)
    return FleetChangeRecord(
        generated_at=now(),
        change_id=plan.change_id,
        fleet_plan_digest=plan.digest,
        approval_digest=approval_digest,
        selector=plan.selector,
        rollout=plan.rollout,
        canaries=plan.canaries,
        waves=plan.waves,
        preflight=preflight,
        fleet_plan=plan,
        members=_execution_evidence(plan, records, stopped=False),
        final_validation=final_validation,
        final_outcome=(
            FleetFinalOutcome.SUCCEEDED
            if final_validation.succeeded
            else FleetFinalOutcome.FINAL_VALIDATION_FAILED
        ),
    )
