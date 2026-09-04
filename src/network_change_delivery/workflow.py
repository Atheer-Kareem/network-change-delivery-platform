"""Historical schema-v1 read-only planning for interface descriptions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from network_change_delivery.inventory import InventoryProvider
from network_change_delivery.models import (
    CiscoConfigArtifact,
    DeploymentPlan,
    DesiredDescription,
    FinalOutcome,
    FrozenFleetMember,
    InterfaceDescriptionIntent,
    InterfaceState,
    InventoryDevice,
    JunosConfigArtifact,
    PlanPreconditions,
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
