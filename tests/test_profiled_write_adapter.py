"""Direct authority fences for the profiled write dispatcher."""

from pathlib import Path

import pytest
from test_profiled_execution import plan

from network_change_delivery.ansible_adapter import ProviderError
from network_change_delivery.architecture_contracts import NetworkOS
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

    def profiled_transaction(self, *_args):
        self.calls += 1
        raise AssertionError

    def confirm_profiled(self, *_args):
        self.calls += 1
        return ExecutionResult(disposition=ExecutionDisposition.SUCCEEDED, message="ok")


@pytest.mark.parametrize(
    "field,value", [("network_os", NetworkOS.JUNOS), ("port", 830)]
)
def test_fabricated_cisco_target_is_rejected_before_writer(field, value):
    value_plan, device, interface, _state = plan()
    target = ProfiledWriteTarget.from_preflight(
        device, interface, value_plan.operation_admission.operation
    )
    object.__setattr__(target, field, value)
    cisco = Cisco()
    adapter = ProfiledWriteAdapter(
        known_hosts=Path("/tmp/k"), cisco=cisco, junos=Junos()
    )
    with pytest.raises(ProviderError):
        adapter.execute_cisco(
            target,
            DeviceCredentials(username="u", password="p"),
            value_plan.execution_artifact,
        )
    assert not cisco.calls


def test_adapter_requires_known_hosts():
    with pytest.raises(ProviderError):
        ProfiledWriteAdapter(known_hosts=None)
