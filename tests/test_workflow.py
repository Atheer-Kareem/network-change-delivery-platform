"""Deterministic lifecycle and failure-path tests using provider fakes."""

from datetime import UTC, datetime

import pytest

from network_change_delivery.models import (
    DesiredDescription,
    ExecutionDisposition,
    ExecutionResult,
    FinalOutcome,
    InterfaceDescriptionIntent,
    InterfaceState,
    InventoryDevice,
)
from network_change_delivery.secrets import (
    ENVIRONMENT_REFERENCE,
    CredentialReference,
    DeviceCredentials,
)
from network_change_delivery.workflow import build_plan, deploy_plan, plan_change


class FakeInventory:
    """Resolve one fixed device."""

    def __init__(self, device: InventoryDevice | None = None) -> None:
        self.device = device or InventoryDevice(
            name="router-1",
            host="192.0.2.10",
            platform="cisco_iosxe",
            expected_hostname="lab-router",
            protected_interfaces=("GigabitEthernet1",),
        )

    def resolve(self, target: str, interface: str | None = None) -> InventoryDevice:
        del interface
        if target != self.device.name:
            raise ValueError("unknown target")
        return self.device


class FakeSecrets:
    """Return ephemeral test credentials."""

    def __init__(
        self,
        credential: CredentialReference | None = None,
        error: Exception | None = None,
    ) -> None:
        self.credential = credential or CredentialReference(
            "environment", ENVIRONMENT_REFERENCE
        )
        self.error = error
        self.loads = 0

    def reference(self, _device: InventoryDevice) -> CredentialReference:
        return self.credential

    def load(self, _device: InventoryDevice) -> DeviceCredentials:
        self.loads += 1
        if self.error is not None:
            raise self.error
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


@pytest.mark.parametrize(
    ("changes", "expected_message"),
    [
        ({"host": "192.0.2.99"}, "endpoint binding"),
        ({"port": 2222}, "endpoint binding"),
        ({"expected_hostname": "other-router"}, "endpoint binding"),
        ({"platform": "unsupported"}, "endpoint binding"),
    ],
)
def test_inventory_binding_drift_is_stale_before_collection(
    changes: dict[str, object], expected_message: str
) -> None:
    approved = plan()
    changed_device = FakeInventory().device.model_copy(update=changes)
    collector = FakeCollector()
    executor = FakeExecutor()
    record = deploy_plan(
        approved,
        approved.digest,
        FakeInventory(changed_device),
        FakeSecrets(),
        collector,
        executor,
    )
    assert record.final_outcome is FinalOutcome.STALE_PLAN
    assert expected_message in record.preflight.message
    assert collector.calls == 0


def test_netbox_object_identity_drift_is_stale_before_device_collection() -> None:
    netbox_device = FakeInventory().device.model_copy(
        update={
            "inventory_source": "netbox",
            "inventory_object_id": "netbox:dcim.device:42",
            "inventory_interface_object_id": "netbox:dcim.interface:100",
        }
    )
    approved = build_plan(intent(), netbox_device, state("old"))
    replacement = netbox_device.model_copy(
        update={"inventory_object_id": "netbox:dcim.device:99"}
    )
    collector = FakeCollector()
    executor = FakeExecutor()
    record = deploy_plan(
        approved,
        approved.digest,
        FakeInventory(replacement),
        FakeSecrets(),
        collector,
        executor,
    )
    assert record.final_outcome is FinalOutcome.STALE_PLAN
    assert collector.calls == 0
    assert executor.artifacts == []
    assert record.inventory_object_id == "netbox:dcim.device:42"


def test_netbox_interface_identity_drift_is_stale_before_device_collection() -> None:
    netbox_device = FakeInventory().device.model_copy(
        update={
            "inventory_source": "netbox",
            "inventory_object_id": "netbox:dcim.device:42",
            "inventory_interface_object_id": "netbox:dcim.interface:100",
        }
    )
    approved = build_plan(intent(), netbox_device, state("old"))
    replacement = netbox_device.model_copy(
        update={"inventory_interface_object_id": "netbox:dcim.interface:101"}
    )
    collector = FakeCollector()
    executor = FakeExecutor()
    record = deploy_plan(
        approved,
        approved.digest,
        FakeInventory(replacement),
        FakeSecrets(),
        collector,
        executor,
    )
    assert record.final_outcome is FinalOutcome.STALE_PLAN
    assert collector.calls == 0
    assert executor.artifacts == []
    assert record.inventory_interface_object_id == "netbox:dcim.interface:100"


def test_credential_provenance_enters_plan_and_change_record() -> None:
    approved_credential = CredentialReference(
        "openbao", "openbao:kv-v2:ncdp/devices/1/ssh"
    )
    netbox_device = FakeInventory().device.model_copy(
        update={
            "inventory_source": "netbox",
            "inventory_object_id": "netbox:dcim.device:1",
            "inventory_interface_object_id": "netbox:dcim.interface:2",
        }
    )
    approved = build_plan(
        intent(),
        netbox_device,
        state("old"),
        credential=approved_credential,
    )
    record = deploy_plan(
        approved,
        approved.digest,
        FakeInventory(netbox_device),
        FakeSecrets(approved_credential),
        FakeCollector(state("old"), state("managed-by-ncdp")),
        FakeExecutor(result(ExecutionDisposition.SUCCEEDED, changed=True)),
    )
    assert approved.credential_source == "openbao"
    assert approved.credential_reference == approved_credential.reference
    assert record.credential_source == "openbao"
    assert record.credential_reference == approved_credential.reference
    serialized = record.model_dump(mode="json")
    assert "username" not in serialized
    assert "password" not in serialized


@pytest.mark.parametrize(
    "credential",
    [
        CredentialReference("openbao", "openbao:kv-v2:ncdp/devices/1/ssh"),
        CredentialReference("environment", "environment:changed-reference"),
    ],
)
def test_credential_binding_drift_is_stale_before_secret_load_or_collection(
    credential: CredentialReference,
) -> None:
    approved = plan()
    secrets = FakeSecrets(credential)
    collector = FakeCollector()
    executor = FakeExecutor()
    record = deploy_plan(
        approved,
        approved.digest,
        FakeInventory(),
        secrets,
        collector,
        executor,
    )
    assert record.final_outcome is FinalOutcome.STALE_PLAN
    assert secrets.loads == 0
    assert collector.calls == 0
    assert executor.artifacts == []


def test_secret_load_failure_blocks_before_device_collection() -> None:
    approved = plan()
    secrets = FakeSecrets(error=RuntimeError("bounded load failure"))
    collector = FakeCollector()
    executor = FakeExecutor()
    record = deploy_plan(
        approved,
        approved.digest,
        FakeInventory(),
        secrets,
        collector,
        executor,
    )
    assert record.final_outcome is FinalOutcome.BLOCKED
    assert secrets.loads == 1
    assert collector.calls == 0
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


def test_post_write_collection_exception_returns_typed_evidence() -> None:
    approved = plan()
    executor = FakeExecutor(result(ExecutionDisposition.SUCCEEDED, changed=True))
    record = deploy_plan(
        approved,
        approved.digest,
        FakeInventory(),
        FakeSecrets(),
        FakeCollector(state("old"), RuntimeError("provider unavailable")),
        executor,
    )
    assert record.final_outcome is FinalOutcome.POST_VALIDATION_FAILED
    assert record.execution.succeeded is True
    assert record.post_validation.attempted is True
    assert record.post_validation.succeeded is False
    assert executor.artifacts == [approved.execution_artifact]


@pytest.mark.parametrize(
    "post_write_state",
    [
        InterfaceState(
            observed_hostname="other-router",
            interface="GigabitEthernet2",
            exists=True,
            description="wrong",
            protected=False,
        ),
        InterfaceState(
            observed_hostname="lab-router",
            interface="GigabitEthernet3",
            exists=True,
            description="wrong",
            protected=False,
        ),
        InterfaceState(
            observed_hostname="lab-router",
            interface="GigabitEthernet2",
            exists=False,
            description=None,
            protected=False,
        ),
    ],
)
def test_post_write_identity_failure_never_recovers(
    post_write_state: InterfaceState,
) -> None:
    approved = plan()
    executor = FakeExecutor(result(ExecutionDisposition.SUCCEEDED, changed=True))
    record = deploy_plan(
        approved,
        approved.digest,
        FakeInventory(),
        FakeSecrets(),
        FakeCollector(state("old"), post_write_state),
        executor,
    )
    assert record.final_outcome is FinalOutcome.POST_VALIDATION_FAILED
    assert record.post_validation.succeeded is False
    assert executor.artifacts == [approved.execution_artifact]


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


def test_recovery_ambiguity_is_distinct_and_not_retried() -> None:
    approved = plan()
    executor = FakeExecutor(
        result(ExecutionDisposition.SUCCEEDED, changed=True),
        result(ExecutionDisposition.AMBIGUOUS),
    )
    record = deploy_plan(
        approved,
        approved.digest,
        FakeInventory(),
        FakeSecrets(),
        FakeCollector(state("old"), state("wrong")),
        executor,
    )
    assert record.final_outcome is FinalOutcome.RECOVERY_AMBIGUOUS
    assert executor.artifacts == [
        approved.execution_artifact,
        approved.recovery_artifact,
    ]


def test_recovery_verification_collection_exception_is_caught() -> None:
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
        FakeCollector(state("old"), state("wrong"), RuntimeError("unavailable")),
        executor,
    )
    assert record.final_outcome is FinalOutcome.RECOVERY_FAILED
    assert record.recovery.succeeded is False
    assert len(executor.artifacts) == 2


@pytest.mark.parametrize(
    "recovered_state",
    [
        InterfaceState(
            observed_hostname="other-router",
            interface="GigabitEthernet2",
            exists=True,
            description="old",
            protected=False,
        ),
        InterfaceState(
            observed_hostname="lab-router",
            interface="GigabitEthernet3",
            exists=True,
            description="old",
            protected=False,
        ),
        InterfaceState(
            observed_hostname="lab-router",
            interface="GigabitEthernet2",
            exists=False,
            description=None,
            protected=False,
        ),
    ],
)
def test_recovery_verification_identity_failure_is_not_retried(
    recovered_state: InterfaceState,
) -> None:
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
        FakeCollector(state("old"), state("wrong"), recovered_state),
        executor,
    )
    assert record.final_outcome is FinalOutcome.RECOVERY_FAILED
    assert record.recovery.succeeded is False
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
