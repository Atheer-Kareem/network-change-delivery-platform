"""Single-attempt SNMP provisioning workflow and late-secret timing tests."""

from __future__ import annotations

from datetime import UTC, datetime

from network_change_delivery.models import (
    ExecutionDisposition,
    ExecutionResult,
    InventoryDevice,
)
from network_change_delivery.secrets import DeviceCredentials
from network_change_delivery.snmp_credentials import (
    SnmpProvisioningCredentials,
    snmp_username,
)
from network_change_delivery.snmp_provisioning import (
    SecretRenderedArtifact,
    SnmpOwnedObjectState,
    SnmpOwnedStateDisposition,
    SnmpProvisioningOutcome,
    SnmpV3InterfaceTelemetryIntent,
    build_snmp_provisioning_plan,
)
from network_change_delivery.snmp_provisioning_workflow import (
    deploy_snmp_provisioning_plan,
)
from network_change_delivery.snmp_telemetry import SnmpCredentialReference


def absent(device_id: int = 1) -> SnmpOwnedObjectState:
    return SnmpOwnedObjectState(
        observed_hostname="core-02" if device_id == 1 else "edge-junos-01",
        local_engine_id_present=True,
        view="ABSENT",
        group="ABSENT",
        user="ABSENT",
    )


def device(platform: str = "cisco_iosxe", device_id: int = 1) -> InventoryDevice:
    return InventoryDevice(
        name="core-02" if device_id == 1 else "edge-junos-01",
        host="192.0.2.10",
        port=22 if platform == "cisco_iosxe" else 830,
        platform=platform,
        expected_hostname="core-02" if device_id == 1 else "edge-junos-01",
        inventory_source="netbox",
        inventory_object_id=f"netbox:dcim.device:{device_id}",
    )


def plan(platform: str = "cisco_iosxe", device_id: int = 1):
    identity = f"netbox:dcim.device:{device_id}"
    generation = "v1"
    intent = SnmpV3InterfaceTelemetryIntent(
        change_id=f"CHG-SNMP-{device_id}",
        target="core-02" if device_id == 1 else "edge-junos-01",
        device=identity,
        platform=platform,
        generation=generation,
        username=snmp_username(device_id),
        credential=SnmpCredentialReference(
            device=identity,
            reference=f"snmpv3:{identity}:generation:{generation}",
            auth_selector=f"device_{device_id}_{generation}",
        ),
    )
    return build_snmp_provisioning_plan(
        intent,
        device(platform, device_id),
        absent(device_id),
        created_at=datetime(2026, 8, 29, tzinfo=UTC),
    )


class Source:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.calls = 0

    def load(self) -> SnmpProvisioningCredentials:
        self.calls += 1
        self.events.append("snmp-secret")
        return SnmpProvisioningCredentials(
            snmp_username(1),
            "auth-secret-sentinel-" + "A" * 27,
            "privacy-secret-sentinel-" + "B" * 24,
        )


class Adapter:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.state = absent()
        self.artifact_repr = ""
        self.recovery_commands: tuple[str, ...] = ()

    def preflight(self, _device, _credentials, _plan):
        self.events.append("preflight")
        return self.state

    def execute_cisco(
        self, _device, _credentials, artifact: SecretRenderedArtifact
    ) -> ExecutionResult:
        self.events.append("write")
        self.artifact_repr = repr(artifact)
        self.state = self.state.model_copy(
            update={
                "view": SnmpOwnedStateDisposition.EXACT_NCDP_STATE,
                "group": SnmpOwnedStateDisposition.EXACT_NCDP_STATE,
                "user": SnmpOwnedStateDisposition.EXACT_NCDP_STATE,
            }
        )
        return ExecutionResult(
            disposition=ExecutionDisposition.SUCCEEDED,
            changed=True,
            message="one Cisco write succeeded",
        )

    def execute_junos_confirmed(self, *_args):
        self.events.append("commit-confirmed")
        self.state = self.state.model_copy(
            update={
                "view": SnmpOwnedStateDisposition.EXACT_NCDP_STATE,
                "group": SnmpOwnedStateDisposition.EXACT_NCDP_STATE,
                "user": SnmpOwnedStateDisposition.EXACT_NCDP_STATE,
            }
        )
        return ExecutionResult(
            disposition=ExecutionDisposition.SUCCEEDED,
            changed=True,
            message="temporary commit confirmed 5 active",
        )

    def post_validate(self, _device, _credentials, _plan):
        self.events.append("post")
        return self.state

    def recover_cisco(self, _device, _credentials, _plan, commands):
        self.events.append("recover")
        self.recovery_commands = commands
        self.state = absent()
        return ExecutionResult(
            disposition=ExecutionDisposition.SUCCEEDED,
            changed=True,
            message="targeted inverse succeeded",
        )

    def confirm_junos(self, _device, _credentials):
        self.events.append("confirm")
        return ExecutionResult(
            disposition=ExecutionDisposition.SUCCEEDED,
            changed=True,
            message="confirmed",
        )


def execute(adapter: Adapter, source: Source, events: list[str], *, value=None):
    value = value or plan()
    return deploy_snmp_provisioning_plan(
        value,
        value.digest,
        device(value.platform, 1 if value.platform == "cisco_iosxe" else 2),
        DeviceCredentials("ssh-user", "ssh-secret"),
        source,
        adapter,
        lambda: events.append("audit-gate"),
        now=lambda: datetime(2026, 8, 29, tzinfo=UTC),
    )


def test_secret_is_loaded_only_after_fresh_preflight_and_prewrite_gate() -> None:
    events: list[str] = []
    source = Source(events)
    adapter = Adapter(events)
    record = execute(adapter, source, events)
    assert events == ["preflight", "audit-gate", "snmp-secret", "write", "post"]
    assert record.final_outcome is SnmpProvisioningOutcome.SUCCEEDED
    assert source.calls == 1
    assert "auth-secret-sentinel" not in adapter.artifact_repr
    serialized = record.model_dump_json()
    assert "auth-secret-sentinel" not in serialized
    assert "privacy-secret-sentinel" not in serialized


def test_preflight_conflict_stops_before_gate_secret_or_write() -> None:
    events: list[str] = []
    source = Source(events)
    adapter = Adapter(events)
    adapter.state = absent().model_copy(update={"view": "CONFLICT"})
    record = execute(adapter, source, events)
    assert events == ["preflight"]
    assert source.calls == 0
    assert record.final_outcome is SnmpProvisioningOutcome.BLOCKED


def test_cisco_post_failure_runs_exact_inverse_once_and_verifies_absence() -> None:
    events: list[str] = []
    source = Source(events)
    adapter = Adapter(events)
    original = adapter.execute_cisco

    def execute_without_valid_state(*args):
        result = original(*args)
        adapter.state = absent().model_copy(update={"view": "CONFLICT"})
        return result

    adapter.execute_cisco = execute_without_valid_state  # type: ignore[method-assign]
    record = execute(adapter, source, events)
    assert events.count("write") == 1
    assert events.count("recover") == 1
    assert events.count("post") == 2
    assert record.final_outcome is SnmpProvisioningOutcome.RECOVERED
    assert adapter.recovery_commands[0].startswith("no snmp-server user")


def test_junos_uses_one_confirmed_commit_then_independent_validation_and_confirm() -> (
    None
):
    events: list[str] = []
    source = Source(events)
    adapter = Adapter(events)
    value = plan("junos", 2)

    class JunosSource(Source):
        def load(self):
            self.calls += 1
            self.events.append("snmp-secret")
            return SnmpProvisioningCredentials(
                snmp_username(2),
                "auth-secret-sentinel-" + "A" * 27,
                "privacy-secret-sentinel-" + "B" * 24,
            )

    source = JunosSource(events)
    adapter.state = absent(2)
    record = execute(adapter, source, events, value=value)
    assert events == [
        "preflight",
        "audit-gate",
        "snmp-secret",
        "commit-confirmed",
        "post",
        "confirm",
    ]
    assert record.final_outcome is SnmpProvisioningOutcome.SUCCEEDED
