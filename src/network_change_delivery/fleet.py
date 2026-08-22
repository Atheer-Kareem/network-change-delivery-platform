"""Fleet planning and complete read-only preflight domain policy."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from network_change_delivery.inventory import (
    FleetInventoryProvider,
    FleetPreflightInventoryProvider,
)
from network_change_delivery.models import (
    FleetDeploymentPlan,
    FleetInterfaceDescriptionIntent,
    FleetMemberClassification,
    FleetMemberPreflight,
    FleetPreflightResult,
    FrozenFleetMember,
    InterfaceDescriptionIntent,
    InterfaceState,
)
from network_change_delivery.secrets import CredentialReference, SecretProvider
from network_change_delivery.workflow import (
    PreflightError,
    StateCollector,
    _assert_safe_state,
    build_plan,
    collect_preflight_state,
)


class FleetSafetyError(ValueError):
    """Raised when fleet planning cannot establish one safe frozen population."""


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
    except (ValueError, OSError, RuntimeError) as error:
        raise FleetSafetyError("fleet selector resolution failed") from error
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
    except (ValueError, OSError, RuntimeError) as error:
        raise FleetSafetyError("complete fleet planning preflight failed") from error
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
    if not plan.verify_digest():
        return FleetPreflightResult(
            fleet_digest=plan.digest,
            succeeded=False,
            members=(),
            message="fleet plan digest is invalid",
        )
    if approval_digest is not None and approval_digest != plan.digest:
        return FleetPreflightResult(
            fleet_digest=plan.digest,
            succeeded=False,
            members=(),
            message="approval digest does not match fleet plan",
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
