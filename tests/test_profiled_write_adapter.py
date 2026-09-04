"""Direct authority fences for the profiled write dispatcher."""

from contextlib import contextmanager
from pathlib import Path

import pytest
from test_profiled_execution import plan

from network_change_delivery.ansible_adapter import ProviderError
from network_change_delivery.architecture_contracts import (
    AutomationProfileID,
    NetworkOS,
)
from network_change_delivery.models import ExecutionDisposition, ExecutionResult
from network_change_delivery.profiled_write_adapter import (
    ProfiledWriteAdapter,
    ProfiledWriteTarget,
)
from network_change_delivery.secrets import DeviceCredentials


class Cisco:
    def __init__(self):
        self.calls = 0

    def execute_profiled(self, *_args):
        self.calls += 1
        return ExecutionResult(disposition=ExecutionDisposition.SUCCEEDED, message="ok")


class Junos:
    def __init__(self):
        self.calls = 0

    @contextmanager
    def profiled_transaction(self, *_args):
        self.calls += 1
        yield object()

    def confirm_profiled(self, *_args):
        self.calls += 1
        return ExecutionResult(disposition=ExecutionDisposition.SUCCEEDED, message="ok")


@pytest.mark.parametrize(
    ("profile", "field", "value"),
    [
        (AutomationProfileID.CAT8000V_IOSXE, "network_os", NetworkOS.JUNOS),
        (AutomationProfileID.CAT8000V_IOSXE, "port", 830),
        (AutomationProfileID.VJUNOS_ROUTER, "network_os", NetworkOS.IOSXE),
        (AutomationProfileID.VJUNOS_ROUTER, "port", 22),
        (AutomationProfileID.CAT8000V_IOSXE, "interface", "other-device"),
        (AutomationProfileID.CAT8000V_IOSXE, "admission", "wrong-profile"),
    ],
)
def test_fabricated_target_is_rejected_before_underlying_writer(profile, field, value):
    value_plan, device, interface, _state = plan(profile)
    target = ProfiledWriteTarget.from_preflight(
        device, interface, value_plan.operation_admission.operation
    )
    if field == "interface":
        value = interface.model_copy(update={"device": "netbox:dcim.device:999"})
    elif field == "admission":
        other_plan, *_ = plan(AutomationProfileID.VJUNOS_ROUTER)
        value = other_plan.operation_admission
    object.__setattr__(target, field, value)
    cisco = Cisco()
    junos = Junos()
    adapter = ProfiledWriteAdapter(known_hosts=Path("/tmp/k"), cisco=cisco, junos=junos)
    with pytest.raises(ProviderError):
        if profile is AutomationProfileID.CAT8000V_IOSXE:
            adapter.execute_cisco(
                target,
                DeviceCredentials(username="u", password="p"),
                value_plan.execution_artifact,
            )
        else:
            with adapter.junos_transaction(
                target,
                DeviceCredentials(username="u", password="p"),
                value_plan.execution_artifact,
            ):
                pass
    assert (cisco.calls, junos.calls) == (0, 0)


def test_closed_dispatch_delegates_only_matching_valid_profile_once():
    credentials = DeviceCredentials(username="u", password="p")
    cisco, junos = Cisco(), Junos()
    adapter = ProfiledWriteAdapter(known_hosts=Path("/tmp/k"), cisco=cisco, junos=junos)
    cisco_plan, cisco_device, cisco_interface, _ = plan()
    cisco_target = ProfiledWriteTarget.from_preflight(
        cisco_device, cisco_interface, cisco_plan.operation_admission.operation
    )
    adapter.execute_cisco(cisco_target, credentials, cisco_plan.execution_artifact)
    junos_plan, junos_device, junos_interface, _ = plan(
        AutomationProfileID.VJUNOS_ROUTER
    )
    junos_target = ProfiledWriteTarget.from_preflight(
        junos_device, junos_interface, junos_plan.operation_admission.operation
    )
    with adapter.junos_transaction(
        junos_target, credentials, junos_plan.execution_artifact
    ):
        pass
    adapter.confirm_junos(junos_target, credentials)
    assert (cisco.calls, junos.calls) == (1, 2)


def test_adapter_requires_known_hosts():
    with pytest.raises(ProviderError):
        ProfiledWriteAdapter(known_hosts=None)
