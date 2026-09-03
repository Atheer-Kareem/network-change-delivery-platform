"""Offline schema-v2 execution lifecycle tests; no provider contacts devices."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

import pytest
from test_profiled_planning import profiled_device

from network_change_delivery.architecture_contracts import AutomationProfileID
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


class Collector:
    def __init__(self, states):
        self.states = iter(states)
        self.calls = 0

    def collect(self, _target, _credentials, _interface):
        self.calls += 1
        return next(self.states)


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
        device, interface.interface, value.operation_admission.operation
    )
    assert target.device_identity == value.device_identity
    assert target.interface_identity == value.interface.interface
    with pytest.raises(AttributeError):
        target.host = "192.0.2.1"  # type: ignore[misc]
