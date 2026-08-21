"""Deterministic lifecycle and failure-path tests using provider fakes."""

from datetime import UTC, datetime

from network_change_delivery.models import (
    DesiredDescription,
    ExecutionDisposition,
    ExecutionResult,
    FinalOutcome,
    InterfaceDescriptionIntent,
    InterfaceState,
    InventoryDevice,
)
from network_change_delivery.secrets import DeviceCredentials
from network_change_delivery.workflow import build_plan, deploy_plan, plan_change


class FakeInventory:
    """Resolve one fixed device."""

    def __init__(self) -> None:
        self.device = InventoryDevice(
            name="router-1",
            host="192.0.2.10",
            platform="cisco_iosxe",
            expected_hostname="lab-router",
            protected_interfaces=("GigabitEthernet1",),
        )

    def resolve(self, target: str) -> InventoryDevice:
        if target != self.device.name:
            raise ValueError("unknown target")
        return self.device


class FakeSecrets:
    """Return ephemeral test credentials."""

    def load(self) -> DeviceCredentials:
        return DeviceCredentials(username="test-user", password="test-password")


class FakeCollector:
    """Return fresh states in order."""

    def __init__(self, *states: InterfaceState) -> None:
        self.states = list(states)
        self.calls = 0

    def collect(
        self, _device: object, _credentials: object, _interface: str
    ) -> InterfaceState:
        self.calls += 1
        return self.states.pop(0)


class FakeExecutor:
    """Record exact artifacts and return bounded results in order."""

    def __init__(self, *results: ExecutionResult) -> None:
        self.results = list(results)
        self.artifacts = []

    def execute(
        self, _device: object, _credentials: object, artifact: object
    ) -> ExecutionResult:
        self.artifacts.append(artifact)
        return self.results.pop(0)


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
        created_at=datetime(2026, 8, 22, tzinfo=UTC),
    )


def result(disposition: ExecutionDisposition, changed: bool = False) -> ExecutionResult:
    return ExecutionResult(
        disposition=disposition,
        changed=changed,
        message=f"bounded {disposition.value.lower()}",
    )


def test_noop_planning_produces_no_artifact() -> None:
    planned = plan_change(
        intent(),
        FakeInventory(),
        FakeSecrets(),
        FakeCollector(state("managed-by-ncdp")),
    )
    assert planned.plan is None
    assert "no deployable artifact" in planned.message


def test_approval_digest_mismatch_blocks_without_execution() -> None:
    approved = plan()
    executor = FakeExecutor()
    record = deploy_plan(
        approved,
        "sha256:wrong",
        FakeInventory(),
        FakeSecrets(),
        FakeCollector(),
        executor,
    )
    assert record.final_outcome is FinalOutcome.BLOCKED
    assert executor.artifacts == []


def test_stale_description_before_deploy_fails_closed() -> None:
    approved = plan()
    executor = FakeExecutor()
    record = deploy_plan(
        approved,
        approved.digest,
        FakeInventory(),
        FakeSecrets(),
        FakeCollector(state("changed-after-approval")),
        executor,
    )
    assert record.final_outcome is FinalOutcome.STALE_PLAN
    assert executor.artifacts == []


def test_exact_artifact_is_executed_and_fresh_state_validated() -> None:
    approved = plan()
    executor = FakeExecutor(result(ExecutionDisposition.SUCCEEDED, changed=True))
    record = deploy_plan(
        approved,
        approved.digest,
        FakeInventory(),
        FakeSecrets(),
        FakeCollector(state("old"), state("managed-by-ncdp")),
        executor,
    )
    assert executor.artifacts == [approved.execution_artifact]
    assert record.final_outcome is FinalOutcome.SUCCEEDED
    assert record.post_validation.observed_description == "managed-by-ncdp"


def test_execution_failure_does_not_retry_or_recover() -> None:
    approved = plan()
    executor = FakeExecutor(result(ExecutionDisposition.FAILED))
    record = deploy_plan(
        approved,
        approved.digest,
        FakeInventory(),
        FakeSecrets(),
        FakeCollector(state("old")),
        executor,
    )
    assert record.final_outcome is FinalOutcome.EXECUTION_FAILED
    assert executor.artifacts == [approved.execution_artifact]


def test_ambiguous_execution_does_not_retry_or_recover() -> None:
    approved = plan()
    executor = FakeExecutor(result(ExecutionDisposition.AMBIGUOUS))
    collector = FakeCollector(state("old"), state("unknown-after-write"))
    record = deploy_plan(
        approved,
        approved.digest,
        FakeInventory(),
        FakeSecrets(),
        collector,
        executor,
    )
    assert record.final_outcome is FinalOutcome.AMBIGUOUS
    assert collector.calls == 2
    assert executor.artifacts == [approved.execution_artifact]


def test_post_validation_failure_recovers_previous_description() -> None:
    approved = plan()
    executor = FakeExecutor(
        result(ExecutionDisposition.SUCCEEDED, changed=True),
        result(ExecutionDisposition.SUCCEEDED, changed=True),
    )
    record = deploy_plan(
        approved,
        approved.digest,
        FakeInventory(),
        FakeSecrets(),
        FakeCollector(state("old"), state("wrong"), state("old")),
        executor,
    )
    assert executor.artifacts == [
        approved.execution_artifact,
        approved.recovery_artifact,
    ]
    assert record.final_outcome is FinalOutcome.RECOVERED


def test_absent_description_recovers_with_no_description() -> None:
    approved = plan(previous=None)
    executor = FakeExecutor(
        result(ExecutionDisposition.SUCCEEDED, changed=True),
        result(ExecutionDisposition.SUCCEEDED, changed=True),
    )
    record = deploy_plan(
        approved,
        approved.digest,
        FakeInventory(),
        FakeSecrets(),
        FakeCollector(state(None), state("wrong"), state(None)),
        executor,
    )
    assert approved.recovery_artifact.lines == ("no description",)
    assert record.final_outcome is FinalOutcome.RECOVERED


def test_recovery_failure_is_reported_without_retry() -> None:
    approved = plan()
    executor = FakeExecutor(
        result(ExecutionDisposition.SUCCEEDED, changed=True),
        result(ExecutionDisposition.FAILED),
    )
    record = deploy_plan(
        approved,
        approved.digest,
        FakeInventory(),
        FakeSecrets(),
        FakeCollector(state("old"), state("wrong")),
        executor,
    )
    assert record.final_outcome is FinalOutcome.RECOVERY_FAILED
    assert len(executor.artifacts) == 2


def test_evidence_excludes_credentials() -> None:
    approved = plan()
    record = deploy_plan(
        approved,
        approved.digest,
        FakeInventory(),
        FakeSecrets(),
        FakeCollector(state("old"), state("managed-by-ncdp")),
        FakeExecutor(result(ExecutionDisposition.SUCCEEDED, changed=True)),
    )
    serialized = record.model_dump_json()
    assert "test-user" not in serialized
    assert "test-password" not in serialized
