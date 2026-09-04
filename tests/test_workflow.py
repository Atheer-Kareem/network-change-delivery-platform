"""Deterministic lifecycle and failure-path tests using provider fakes."""

from datetime import UTC, datetime

from network_change_delivery.models import (
    DesiredDescription,
    InterfaceDescriptionIntent,
    InterfaceState,
    InventoryDevice,
)
from network_change_delivery.secrets import (
    ENVIRONMENT_REFERENCE,
    CredentialReference,
    DeviceCredentials,
)
from network_change_delivery.workflow import build_plan, plan_change


class FakeInventory:
    """Resolve one fixed device."""

    def __init__(
        self,
        device: InventoryDevice | None = None,
        error: Exception | None = None,
    ) -> None:
        self.device = device or InventoryDevice(
            name="router-1",
            host="192.0.2.10",
            platform="cisco_iosxe",
            expected_hostname="lab-router",
            protected_interfaces=("GigabitEthernet1",),
        )
        self.error = error

    def resolve(self, target: str, interface: str | None = None) -> InventoryDevice:
        del interface
        if self.error is not None:
            raise self.error
        if target != self.device.name:
            raise ValueError("unknown target")
        return self.device


class FakeSecrets:
    """Return ephemeral test credentials."""

    def __init__(
        self,
        credential: CredentialReference | None = None,
        load_error: Exception | None = None,
        reference_error: Exception | None = None,
    ) -> None:
        self.credential = credential or CredentialReference(
            "environment", ENVIRONMENT_REFERENCE
        )
        self.load_error = load_error
        self.reference_error = reference_error
        self.loads = 0

    def reference(self, _device: InventoryDevice) -> CredentialReference:
        if self.reference_error is not None:
            raise self.reference_error
        return self.credential

    def load(self, _device: InventoryDevice) -> DeviceCredentials:
        self.loads += 1
        if self.load_error is not None:
            raise self.load_error
        return DeviceCredentials(username="test-user", password="test-password")


class FakeCollector:
    """Return fresh states in order."""

    def __init__(self, *states: InterfaceState | Exception) -> None:
        self.states = list(states)
        self.calls = 0

    def collect(
        self, _device: object, _credentials: object, _interface: str
    ) -> InterfaceState:
        self.calls += 1
        next_state = self.states.pop(0)
        if isinstance(next_state, Exception):
            raise next_state
        return next_state


def intent() -> InterfaceDescriptionIntent:
    return InterfaceDescriptionIntent(
        change_id="CHG-001",
        kind="interface_description",
        target="router-1",
        interface="GigabitEthernet2",
        desired=DesiredDescription(description="managed-by-ncdp"),
    )


def state(description: str | None) -> InterfaceState:
    return InterfaceState(
        observed_hostname="lab-router",
        interface="GigabitEthernet2",
        exists=True,
        description=description,
        protected=False,
    )


def plan(previous: str | None = "old"):
    return build_plan(
        intent(),
        FakeInventory().device,
        state(previous),
        credential=CredentialReference("environment", ENVIRONMENT_REFERENCE),
        created_at=datetime(2026, 8, 22, tzinfo=UTC),
    )


def test_noop_planning_produces_no_artifact() -> None:
    credential = CredentialReference("openbao", "openbao:kv-v2:ncdp/devices/1/ssh")
    planned = plan_change(
        intent(),
        FakeInventory(),
        FakeSecrets(credential),
        FakeCollector(state("managed-by-ncdp")),
    )
    assert planned.plan is None
    assert planned.credential == credential
    assert "no deployable artifact" in planned.message
