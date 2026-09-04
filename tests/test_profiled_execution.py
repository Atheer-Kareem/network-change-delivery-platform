"""Offline schema-v2 execution lifecycle tests; no provider contacts devices."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

import pytest
from test_profiled_planning import profiled_device

from network_change_delivery.architecture_contracts import AutomationProfileID
from network_change_delivery.cli import build_parser
from network_change_delivery.models import (
    ExecutionDisposition,
    ExecutionResult,
    InterfaceDescriptionIntent,
    InterfaceState,
)
from network_change_delivery.profiled_execution import execute_profiled_plan
from network_change_delivery.profiled_planning import (
    build_profiled_plan,
)
from network_change_delivery.profiled_write_adapter import (
    ProfiledWriteAdapter,
    ProfiledWriteTarget,
)
from network_change_delivery.secrets import CredentialReference, DeviceCredentials


def plan(profile: AutomationProfileID = AutomationProfileID.CAT8000V_IOSXE):
    device, interface = profiled_device(profile)
    intent = InterfaceDescriptionIntent.model_validate(
        {
            "change_id": "CHG-EXEC",
            "kind": "interface_description",
            "target": device.logical_name,
            "interface": interface.name,
            "desired": {"description": "new"},
        }
    )
    state = InterfaceState(
        observed_hostname=device.expected_hostname,
        interface=interface.name,
        exists=True,
        protected=False,
        description="old",
    )
    reference = (
        "openbao:kv-v2:ncdp/devices/"
        + device.device_identity.rsplit(":", 1)[1]
        + "/ssh"
    )
    return (
        build_profiled_plan(
            intent,
            device,
            interface,
            state,
            credential=CredentialReference(
                "openbao",
                reference,
            ),
        ),
        device,
        interface,
        state,
    )


class Inventory:
    def __init__(self, device, interface):
        self.device, self.interface = device, interface

    def resolve(self, _target):
        return self.device

    def resolve_interface(self, _device, _name):
        return self.interface


class CountingInventory(Inventory):
    def __init__(self, device, interface):
        super().__init__(device, interface)
        self.resolves = self.interfaces = 0

    def resolve(self, target):
        self.resolves += 1
        return super().resolve(target)

    def resolve_interface(self, device, name):
        self.interfaces += 1
        return super().resolve_interface(device, name)


class Secrets:
    def reference(self, device):
        reference = (
            "openbao:kv-v2:ncdp/devices/"
            + device.device_identity.rsplit(":", 1)[1]
            + "/ssh"
        )
        return CredentialReference(
            "openbao",
            reference,
        )

    def load(self, _device):
        return DeviceCredentials(username="secret-user", password="secret-password")


class CountingSecrets(Secrets):
    def __init__(self):
        self.references = self.loads = 0

    def reference(self, device):
        self.references += 1
        return super().reference(device)

    def load(self, device):
        self.loads += 1
        return super().load(device)


class Collector:
    def __init__(self, states):
        self.states = iter(states)
        self.calls = 0

    def collect(self, _target, _credentials, _interface):
        self.calls += 1
        return next(self.states)


class CountingCollector(Collector):
    pass


class Cisco:
    def __init__(self, results):
        self.results, self.artifacts = iter(results), []

    def execute_profiled(self, _target, _credentials, artifact):
        self.artifacts.append(artifact)
        return next(self.results)


class Junos:
    def __init__(self, result, confirm):
        self.result, self.confirmation, self.commits, self.confirms = (
            result,
            confirm,
            0,
            0,
        )

    @contextmanager
    def profiled_transaction(self, *_args):
        outer = self

        class Transaction:
            close_failed = False

            def prepare(self):
                class Prepared:
                    diff_sha256 = "sha256:" + "a" * 64

                return Prepared()

            def commit_confirmed(self, _minutes):
                outer.commits += 1
                return outer.result

        yield Transaction()

    def confirm_profiled(self, *_args):
        self.confirms += 1
        return self.confirmation


def writer(cisco=None, junos=None):
    return ProfiledWriteAdapter(
        known_hosts=Path("/tmp/profiled-known-hosts"),
        cisco=cisco or Cisco([]),
        junos=junos or Junos(None, None),
    )


def test_cisco_success_is_one_attempt_and_secret_free():
    value, device, interface, state = plan()
    cisco = Cisco(
        [
            ExecutionResult(
                disposition=ExecutionDisposition.SUCCEEDED, changed=True, message="ok"
            )
        ]
    )
    record = execute_profiled_plan(
        value,
        value.digest,
        Inventory(device, interface),
        Secrets(),
        Collector([state, state.model_copy(update={"description": "new"})]),
        writer(cisco),
    )
    assert record.final_outcome.value == "SUCCEEDED" and len(cisco.artifacts) == 1
    assert (
        "secret" not in record.model_dump_json()
        and record.managed_state_acceptance_attempted is False
    )


def test_cisco_ambiguous_never_retries_or_recovers():
    value, device, interface, state = plan()
    cisco = Cisco(
        [
            ExecutionResult(
                disposition=ExecutionDisposition.AMBIGUOUS, message="uncertain"
            )
        ]
    )
    record = execute_profiled_plan(
        value,
        value.digest,
        Inventory(device, interface),
        Secrets(),
        Collector([state, state]),
        writer(cisco),
    )
    assert (
        record.final_outcome.value == "AMBIGUOUS"
        and len(cisco.artifacts) == 1
        and not record.recovery.attempted
    )


def test_cisco_frozen_targeted_recovery_only_after_known_success():
    value, device, interface, state = plan()
    cisco = Cisco(
        [
            ExecutionResult(disposition=ExecutionDisposition.SUCCEEDED, message="ok"),
            ExecutionResult(
                disposition=ExecutionDisposition.SUCCEEDED, message="recovered"
            ),
        ]
    )
    record = execute_profiled_plan(
        value,
        value.digest,
        Inventory(device, interface),
        Secrets(),
        Collector([state, state, state]),
        writer(cisco),
    )
    assert (
        record.final_outcome.value == "RECOVERED"
        and cisco.artifacts[1] == value.recovery_artifact
    )


def test_junos_success_confirms_once():
    value, device, interface, state = plan(AutomationProfileID.VJUNOS_ROUTER)
    junos = Junos(
        ExecutionResult(
            disposition=ExecutionDisposition.SUCCEEDED,
            changed=True,
            message="committed",
        ),
        ExecutionResult(
            disposition=ExecutionDisposition.SUCCEEDED,
            changed=True,
            message="confirmed",
        ),
    )
    record = execute_profiled_plan(
        value,
        value.digest,
        Inventory(device, interface),
        Secrets(),
        Collector([state, state.model_copy(update={"description": "new"})]),
        writer(junos=junos),
    )
    assert (
        record.final_outcome.value == "SUCCEEDED"
        and junos.commits == 1
        and junos.confirms == 1
    )


def test_invalid_approval_blocks_before_writer():
    value, device, interface, state = plan()
    cisco = Cisco([])
    record = execute_profiled_plan(
        value,
        "sha256:" + "b" * 64,
        Inventory(device, interface),
        Secrets(),
        Collector([state]),
        writer(cisco),
    )
    assert record.final_outcome.value == "BLOCKED" and not cisco.artifacts


def test_profiled_write_target_is_immutable_and_binds_stable_identity():
    value, device, interface, _state = plan()
    target = ProfiledWriteTarget.from_preflight(
        device, interface, value.operation_admission.operation
    )
    assert target.device_identity == value.device_identity
    assert target.interface == value.interface
    with pytest.raises(AttributeError):
        target.host = "192.0.2.1"  # type: ignore[misc]


@pytest.mark.parametrize(
    "field,value",
    [
        ("logical_name", "other"),
        ("device_identity", "netbox:dcim.device:2"),
        ("expected_hostname", "other"),
        ("network_os", "junos"),
        ("automation_profile_id", "vjunos_router"),
    ],
)
def test_stale_device_bindings_never_reach_writer(field, value):
    plan_value, device, interface, state = plan()
    if field in {"network_os", "automation_profile_id"}:
        pytest.skip("Pydantic rejects inconsistent profiled inventory before execution")
    changed = device.model_copy(update={field: value})
    cisco = Cisco([])
    inventory = CountingInventory(changed, interface)
    secrets = CountingSecrets()
    record = execute_profiled_plan(
        plan_value,
        plan_value.digest,
        inventory,
        secrets,
        Collector([state]),
        writer(cisco),
    )
    assert record.final_outcome.value in {"STALE_PLAN", "BLOCKED"}
    assert not cisco.artifacts


@pytest.mark.parametrize(
    "mutation", ["interface", "host", "port", "description", "protected"]
)
def test_stale_interface_or_endpoint_preflight_never_reaches_writer(mutation):
    value, device, interface, state = plan()
    cisco = Cisco([])
    resolved_interface = (
        interface.model_copy(update={"interface": "netbox:dcim.interface:99"})
        if mutation == "interface"
        else interface
    )
    changed_device = device
    if mutation in {"host", "port"}:
        changed_device = device.model_copy(
            update={"expected_hostname": device.expected_hostname}
        )
        # Endpoint changes are represented by the plan binding here.
        value = value.model_copy(
            update={mutation: "192.0.2.99" if mutation == "host" else 2222}
        )
    changed_state = (
        state.model_copy(
            update={mutation: "new" if mutation == "description" else True}
        )
        if mutation in {"description", "protected"}
        else state
    )
    record = execute_profiled_plan(
        value,
        value.digest,
        CountingInventory(changed_device, resolved_interface),
        CountingSecrets(),
        Collector([changed_state]),
        writer(cisco),
    )
    assert (
        record.final_outcome.value in {"STALE_PLAN", "BLOCKED"} and not cisco.artifacts
    )


@pytest.mark.parametrize(
    "result,outcome",
    [
        (ExecutionDisposition.FAILED, "EXECUTION_FAILED"),
        (ExecutionDisposition.AMBIGUOUS, "AMBIGUOUS"),
    ],
)
def test_cisco_known_failure_and_ambiguity_have_no_recovery(result, outcome):
    value, device, interface, state = plan()
    cisco = Cisco([ExecutionResult(disposition=result, message="result")])
    states = (
        [state, state.model_copy(update={"description": "new"})]
        if result is ExecutionDisposition.AMBIGUOUS
        else [state]
    )
    record = execute_profiled_plan(
        value,
        value.digest,
        Inventory(device, interface),
        Secrets(),
        Collector(states),
        writer(cisco),
    )
    assert (
        record.final_outcome.value == outcome
        and len(cisco.artifacts) == 1
        and not record.recovery.attempted
    )


@pytest.mark.parametrize("restored", ["hostname", "interface", "description"])
def test_cisco_wrong_recovery_identity_or_description_fails(restored):
    value, device, interface, state = plan()
    cisco = Cisco(
        [
            ExecutionResult(
                disposition=ExecutionDisposition.SUCCEEDED, message="write"
            ),
            ExecutionResult(
                disposition=ExecutionDisposition.SUCCEEDED, message="recover"
            ),
        ]
    )
    recovered = state
    if restored == "hostname":
        recovered = state.model_copy(update={"observed_hostname": "wrong"})
    elif restored == "interface":
        recovered = state.model_copy(update={"interface": "wrong"})
    else:
        recovered = state.model_copy(update={"description": "wrong"})
    record = execute_profiled_plan(
        value,
        value.digest,
        Inventory(device, interface),
        Secrets(),
        Collector([state, state, recovered]),
        writer(cisco),
    )
    assert (
        record.final_outcome.value == "RECOVERY_FAILED"
        and record.post_validation.attempted
    )


def test_evidence_and_cli_isolation():
    value, device, interface, state = plan()
    cisco = Cisco(
        [ExecutionResult(disposition=ExecutionDisposition.SUCCEEDED, message="ok")]
    )
    record = execute_profiled_plan(
        value,
        value.digest,
        Inventory(device, interface),
        Secrets(),
        Collector([state, state.model_copy(update={"description": "new"})]),
        writer(cisco),
    )
    rendered = record.model_dump_json()
    for present in (
        value.device_identity,
        value.interface.interface,
        value.expected_hostname,
        value.credential_reference,
        value.digest,
    ):
        assert present in rendered
    for absent in ("secret-user", "secret-password", "RoleID", "SecretID"):
        assert absent not in rendered
    parser = build_parser()
    assert (
        parser.parse_args(
            ["profiled-plan", "--change", "x", "--output", "y", "--netbox", "--openbao"]
        ).command
        == "profiled-plan"
    )
    with pytest.raises(SystemExit):
        parser.parse_args(["profiled-deploy"])


class FailingJunos(Junos):
    def __init__(self, *, commit_raises: bool = False, cleanup_raises: bool = False):
        super().__init__(None, None)
        self.exits = 0
        self.commit_raises = commit_raises
        self.cleanup_raises = cleanup_raises

    @contextmanager
    def profiled_transaction(self, *_args):
        outer = self

        class Transaction:
            close_failed = False

            def prepare(self):
                raise RuntimeError("candidate failed")

            def commit_confirmed(self, _minutes):
                outer.commits += 1
                if outer.commit_raises:
                    raise RuntimeError("commit uncertain")

        try:
            yield Transaction()
        finally:
            outer.exits += 1
            if outer.cleanup_raises:
                raise RuntimeError("unlock failed")


def test_junos_prepare_failure_closes_context_once_without_commit_or_confirm():
    value, device, interface, state = plan(AutomationProfileID.VJUNOS_ROUTER)
    junos = FailingJunos()
    record = execute_profiled_plan(
        value,
        value.digest,
        Inventory(device, interface),
        Secrets(),
        Collector([state]),
        writer(junos=junos),
    )
    assert record.final_outcome.value == "BLOCKED"
    assert (junos.exits, junos.commits, junos.confirms) == (1, 0, 0)


def test_malformed_approval_fails_before_external_boundaries():
    value, device, interface, state = plan()
    with pytest.raises(ValueError, match="approval digest"):
        execute_profiled_plan(
            value,
            "not-a-digest",
            Inventory(device, interface),
            Secrets(),
            Collector([state]),
            writer(Cisco([])),
        )
