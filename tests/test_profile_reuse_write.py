"""Explicit operation policy and shared Cisco lifecycle; offline providers only."""

import ast
import inspect
from dataclasses import FrozenInstanceError
from ipaddress import IPv4Interface
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from test_profiled_execution import (
    CISCO_PROFILES,
    Cisco,
    Collector,
    CountingInventory,
    CountingSecrets,
    plan,
    writer,
)
from test_profiled_planning import (
    PROFILE_FACTS,
    FakeCollector,
    FakeInventory,
    FakeSecrets,
    intent,
    observed,
    profiled_device,
)

from network_change_delivery import (
    ansible_adapter,
    profiled_planning,
    profiled_write_adapter,
)
from network_change_delivery.ansible_adapter import ProviderError
from network_change_delivery.architecture_contracts import (
    AutomationProfileID,
    NetworkOS,
)
from network_change_delivery.models import CiscoConfigArtifact, ExecutionResult
from network_change_delivery.openbao_profiled_deploy_config import DEVICE_IDS
from network_change_delivery.profiled_execution import (
    ProfiledExecutionError,
    execute_profiled_plan,
)
from network_change_delivery.profiled_planning import (
    PROFILED_OPERATION_ADMISSIONS,
    ProfiledOperation,
    plan_profiled_change,
)
from network_change_delivery.profiled_write_adapter import ProfiledWriteTarget
from network_change_delivery.secrets import CredentialReference, DeviceCredentials

ROOT = Path(__file__).parents[1]
ALL_PROFILES = tuple(PROFILE_FACTS)


@pytest.mark.parametrize("profile", CISCO_PROFILES)
@pytest.mark.parametrize("previous", ["previous", None])
def test_exact_cisco_plan_and_frozen_inverse_share_one_artifact(profile, previous):
    device, interface = profiled_device(profile)
    requested = intent(device, interface)
    secrets = FakeSecrets()
    result = plan_profiled_change(
        requested,
        FakeInventory(device, interface),
        secrets,
        FakeCollector(observed(device, interface, description=previous)),
    )
    value = result.plan
    assert value and value.schema_version == "2" and value.verify_digest()
    facts = PROFILE_FACTS[profile]
    assert value.device_identity == f"netbox:dcim.device:{facts['device_id']}"
    assert value.target == facts["name"]
    assert (
        value.interface == interface
        and value.interface.interface
        == f"netbox:dcim.interface:{facts['change_interface'][0]}"
    )
    assert value.host == facts["live"].split("/")[0] and value.port == 22
    assert value.network_os is (
        NetworkOS.IOSXE
        if profile is AutomationProfileID.CAT8000V_IOSXE
        else NetworkOS.IOS
    )
    assert value.automation_profile_id is profile
    assert (
        value.credential_reference
        == f"openbao:kv-v2:ncdp/devices/{facts['device_id']}/ssh"
    )
    admission = value.operation_admission
    assert (
        admission
        == PROFILED_OPERATION_ADMISSIONS[
            (profile, ProfiledOperation.INTERFACE_DESCRIPTION)
        ]
    )
    assert admission.transaction_strategy == "cisco_targeted_inverse"
    assert (
        admission.confirmed_timeout_minutes is admission.confirmation_operation is None
    )
    assert value.execution_artifact == CiscoConfigArtifact(
        parent=f"interface {interface.name}",
        lines=(f"description {requested.desired.description}",),
    )
    assert value.recovery_artifact == CiscoConfigArtifact(
        parent=f"interface {interface.name}",
        lines=(
            f"description {previous}" if previous is not None else "no description",
        ),
    )


@pytest.mark.parametrize("profile", ALL_PROFILES)
@pytest.mark.parametrize(
    "fault", ["device", "name", "missing", "hostname", "credential"]
)
def test_planning_identity_and_credential_errors_fail_closed(profile, fault):
    device, interface = profiled_device(profile)
    requested = intent(device, interface)
    state = observed(device, interface)
    secrets = FakeSecrets()

    class Inventory(FakeInventory):
        def resolve_interface(self, *_args):
            if fault == "device":
                return interface.model_copy(update={"device": "netbox:dcim.device:999"})
            if fault == "name":
                return interface.model_copy(update={"name": "wrong"})
            return interface

    if fault == "missing":
        state = state.model_copy(update={"exists": False})
    if fault == "hostname":
        state = state.model_copy(update={"observed_hostname": "wrong"})
    if fault == "credential":
        secrets.reference = lambda _d: CredentialReference(
            "openbao", "openbao:kv-v2:ncdp/devices/999/ssh"
        )
    collector = FakeCollector(state)
    with pytest.raises(ValueError):
        plan_profiled_change(
            requested, Inventory(device, interface), secrets, collector
        )
    if fault in {"device", "name", "credential"}:
        assert secrets.load_calls == collector.calls == 0


@pytest.mark.parametrize("profile", ALL_PROFILES)
@pytest.mark.parametrize(
    "fault",
    [
        "interface-id",
        "interface-name",
        "device",
        "profile",
        "nos",
        "host",
        "port",
        "credential",
        "description",
        "hostname",
        "operation",
    ],
)
def test_fresh_preflight_changes_never_reach_a_writer(profile, fault, monkeypatch):
    value, device, interface, state = plan(profile)
    secrets = CountingSecrets()
    if fault == "interface-id":
        interface = interface.model_copy(
            update={"interface": "netbox:dcim.interface:999"}
        )
    if fault == "interface-name":
        interface = interface.model_copy(update={"name": "wrong"})
    if fault == "device":
        device = device.model_copy(update={"device_identity": "netbox:dcim.device:999"})
    if fault == "profile":
        device = device.model_copy(
            update={
                "automation_profile_id": AutomationProfileID.VJUNOS_ROUTER
                if profile is not AutomationProfileID.VJUNOS_ROUTER
                else AutomationProfileID.CAT8000V_IOSXE
            }
        )
    if fault == "nos":
        device = device.model_copy(
            update={
                "network_os": NetworkOS.JUNOS
                if device.network_os is not NetworkOS.JUNOS
                else NetworkOS.IOS
            }
        )
    if fault in {"host", "port"}:
        # Deliberately inject a malformed provider object so execution must
        # revalidate it; normal endpoint construction already rejects bad ports.
        endpoints = device.management_endpoints
        live = endpoints.live
        binding = live.binding
        endpoint = binding.l3_endpoint.model_copy(
            update={"address": IPv4Interface("192.168.4.99/24")}
            if fault == "host"
            else {"port": 2222}
        )
        device = device.model_copy(
            update={
                "management_endpoints": endpoints.model_copy(
                    update={
                        "live": live.model_copy(
                            update={
                                "binding": binding.model_copy(
                                    update={"l3_endpoint": endpoint}
                                )
                            }
                        )
                    }
                )
            }
        )
    if fault == "credential":
        secrets.reference = lambda _d: CredentialReference(
            "openbao", "openbao:kv-v2:ncdp/devices/999/ssh"
        )
    if fault == "description":
        state = state.model_copy(update={"description": "drift"})
    if fault == "hostname":
        state = state.model_copy(update={"observed_hostname": "wrong"})
    if fault == "operation":
        monkeypatch.setattr(profiled_planning, "PROFILED_OPERATION_ADMISSIONS", {})

    class NoWriter:
        def verify_cisco_runtime(self):
            pass

        def execute_cisco(self, *_a):
            pytest.fail("stale write")

        def junos_transaction(self, *_a):
            pytest.fail("stale Junos write")

    record = execute_profiled_plan(
        value,
        value.digest,
        CountingInventory(device, interface),
        secrets,
        Collector([state]),
        NoWriter(),
    )
    assert record.final_outcome.value in {"BLOCKED", "STALE_PLAN"}
    assert not record.execution.attempted and not record.recovery.attempted


@pytest.mark.parametrize("profile", CISCO_PROFILES)
@pytest.mark.parametrize(
    "post", ["desired", "different", "hostname", "interface", "missing", "unavailable"]
)
def test_post_observation_controls_inverse_eligibility(profile, post):
    value, device, interface, state = plan(profile)
    desired = state.model_copy(update={"description": "new"})
    observed_post = {
        "desired": desired,
        "different": state,
        "hostname": state.model_copy(update={"observed_hostname": "wrong"}),
        "interface": state.model_copy(update={"interface": "wrong"}),
        "missing": state.model_copy(update={"exists": False}),
        "unavailable": OSError("bounded unavailable"),
    }[post]

    class Independent(Collector):
        def collect(self, *args):
            result = super().collect(*args)
            if isinstance(result, Exception):
                raise result
            return result

    collector = Independent([state, observed_post, state])
    success = ExecutionResult(disposition="SUCCEEDED", changed=None, message="ok")
    cisco = Cisco([success, success])
    inventory = CountingInventory(device, interface)
    record = execute_profiled_plan(
        value, value.digest, inventory, CountingSecrets(), collector, writer(cisco)
    )
    assert inventory.resolves == inventory.interfaces == 1
    assert cisco.artifacts[0] == value.execution_artifact
    assert cisco.artifacts.count(value.execution_artifact) == 1
    if post == "different":
        assert cisco.artifacts == [value.execution_artifact, value.recovery_artifact]
        assert collector.calls == 3 and record.final_outcome.value == "RECOVERED"
    else:
        assert len(cisco.artifacts) == 1 and collector.calls == 2
        assert not record.recovery.attempted
        assert record.final_outcome.value == (
            "SUCCEEDED" if post == "desired" else "POST_VALIDATION_FAILED"
        )


@pytest.mark.parametrize("profile", CISCO_PROFILES)
@pytest.mark.parametrize(
    "disposition,outcome",
    [("FAILED", "RECOVERY_FAILED"), ("AMBIGUOUS", "RECOVERY_AMBIGUOUS")],
)
def test_inverse_failure_never_retries(profile, disposition, outcome):
    value, device, interface, state = plan(profile)
    cisco = Cisco(
        [
            ExecutionResult(disposition="SUCCEEDED", message="write"),
            ExecutionResult(disposition=disposition, message="inverse"),
        ]
    )
    collector = Collector([state, state])
    record = execute_profiled_plan(
        value,
        value.digest,
        CountingInventory(device, interface),
        CountingSecrets(),
        collector,
        writer(cisco),
    )
    assert record.final_outcome.value == outcome
    assert cisco.artifacts == [value.execution_artifact, value.recovery_artifact]
    assert collector.calls == 2


@pytest.mark.parametrize("profile", CISCO_PROFILES)
@pytest.mark.parametrize("fault", ["missing-entry", "lifecycle"])
def test_compatible_family_without_exact_operation_authority_cannot_write(
    profile, fault, monkeypatch
):
    value, device, interface, _ = plan(profile)
    target = ProfiledWriteTarget.from_preflight(
        device, interface, ProfiledOperation.INTERFACE_DESCRIPTION
    )
    assert (
        target.device_identity,
        target.interface,
        target.name,
        target.host,
        target.port,
        target.expected_hostname,
        target.protected_interfaces,
        target.automation_profile_id,
        target.network_os,
        target.operation,
        target.admission,
    ) == (
        device.device_identity,
        interface,
        device.logical_name,
        value.host,
        22,
        device.expected_hostname,
        tuple(i.name for i in device.protected_interfaces),
        profile,
        device.network_os,
        ProfiledOperation.INTERFACE_DESCRIPTION,
        value.operation_admission,
    )
    with pytest.raises(FrozenInstanceError):
        target.host = "192.0.2.1"
    if fault == "missing-entry":
        monkeypatch.setattr(profiled_write_adapter, "PROFILED_OPERATION_ADMISSIONS", {})
    else:
        object.__setattr__(
            target,
            "admission",
            target.admission.model_copy(update={"management_port": 2222}),
        )
    cisco = Cisco([])
    with pytest.raises(ProviderError):
        writer(cisco).execute_cisco(
            target,
            DeviceCredentials(username="fake", password="fake"),
            value.execution_artifact,
        )
    assert cisco.artifacts == []


def test_explicit_catalog_and_family_dispatch_are_separate():
    tree = ast.parse(inspect.getsource(profiled_planning))
    node = next(
        n
        for n in tree.body
        if isinstance(n, ast.AnnAssign)
        and isinstance(n.target, ast.Name)
        and n.target.id == "PROFILED_OPERATION_ADMISSIONS"
    )
    assert isinstance(node.value, ast.Call) and isinstance(node.value.args[0], ast.Dict)
    assert {key.elts[0].attr for key in node.value.args[0].keys} == {
        "CAT8000V_IOSXE",
        "VJUNOS_ROUTER",
        "IOSV_159_3_M12",
        "IOSVL2_2020",
    }
    source = inspect.getsource(
        profiled_write_adapter.ProfiledWriteAdapter._validate_cisco_target
    )
    assert "AutomationProfileID" not in source and "automation_profile_id" not in source
    assert "target.__post_init__()" in source
    assert DEVICE_IDS == (1, 2)
    assert list(ProfiledOperation) == [ProfiledOperation.INTERFACE_DESCRIPTION]


@pytest.mark.parametrize("profile", CISCO_PROFILES)
@pytest.mark.parametrize("changed", [True, False, None])
def test_real_ansible_runner_uses_one_shared_playbook_and_exact_artifact(
    tmp_path, monkeypatch, profile, changed
):
    value, device, interface, _ = plan(profile)
    target = ProfiledWriteTarget.from_preflight(
        device, interface, ProfiledOperation.INTERFACE_DESCRIPTION
    )
    known = tmp_path / "known_hosts"
    known.write_text("synthetic known-host fixture\n")
    monkeypatch.setattr(
        ansible_adapter, "verify_existing_host_trust", lambda *_a: "fixture fingerprint"
    )
    calls = []

    def runner(**kwargs):
        calls.append(kwargs)
        host = kwargs["inventory"]["all"]["hosts"]["ncdp_target"]
        assert host["ansible_connection"] == "ansible.netcommon.network_cli"
        assert host["ansible_network_os"] == "cisco.ios.ios"
        assert host["ansible_network_cli_ssh_type"] == "paramiko"
        assert kwargs["playbook"] == "apply_interface_description.yml"
        assert kwargs["extravars"] == {
            "ncdp_artifact": value.execution_artifact.model_dump(mode="json")
        }
        assert kwargs["envvars"]["ANSIBLE_HOST_KEY_CHECKING"] == "True"
        assert kwargs["envvars"]["ANSIBLE_HOST_KEY_AUTO_ADD"] == "False"
        assert (
            Path(kwargs["envvars"]["HOME"]) / ".ssh/known_hosts"
        ).read_bytes() == known.read_bytes()
        kwargs["event_handler"](
            {
                "event": "runner_on_ok",
                "event_data": {
                    "task": ansible_adapter.EXECUTION_TASK,
                    "res": {"changed": changed}
                    if changed is not None
                    else {"censored": "no_log"},
                },
            }
        )
        return SimpleNamespace(status="successful", rc=0)

    monkeypatch.setattr(ansible_adapter.ansible_runner, "run", runner)
    adapter = profiled_write_adapter.ProfiledWriteAdapter(known_hosts=known)
    result = adapter.execute_cisco(
        target,
        DeviceCredentials(username="fake", password="fake"),
        value.execution_artifact,
    )
    assert (
        len(calls) == 1
        and result.disposition.value == "SUCCEEDED"
        and result.changed is changed
    )
    play = yaml.safe_load(
        (ROOT / "ansible/apply_interface_description.yml").read_text()
    )[0]
    assert len(play["tasks"]) == 1
    assert play["tasks"][0]["cisco.ios.ios_config"] == {
        "parents": "{{ ncdp_artifact.parent }}",
        "lines": "{{ ncdp_artifact.lines }}",
        "match": "line",
        "save_when": "never",
    }


@pytest.mark.parametrize("profile", CISCO_PROFILES)
def test_real_runner_uncertain_start_is_one_ambiguous_attempt(
    tmp_path, monkeypatch, profile
):
    value, device, interface, _ = plan(profile)
    target = ProfiledWriteTarget.from_preflight(
        device, interface, ProfiledOperation.INTERFACE_DESCRIPTION
    )
    known = tmp_path / "known_hosts"
    known.write_text("synthetic known-host fixture\n")
    monkeypatch.setattr(
        ansible_adapter, "verify_existing_host_trust", lambda *_a: "fixture fingerprint"
    )
    calls = []

    def runner(**kwargs):
        calls.append(kwargs["playbook"])
        raise RuntimeError("synthetic private provider body")

    monkeypatch.setattr(ansible_adapter.ansible_runner, "run", runner)
    result = profiled_write_adapter.ProfiledWriteAdapter(
        known_hosts=known
    ).execute_cisco(
        target,
        DeviceCredentials(username="fake", password="fake"),
        value.execution_artifact,
    )
    assert calls == ["apply_interface_description.yml"]
    assert result.disposition.value == "AMBIGUOUS"
    assert "synthetic private provider body" not in str(result)


@pytest.mark.parametrize("profile", CISCO_PROFILES)
def test_bad_approval_precedes_even_runtime_verification(profile):
    value, device, interface, state = plan(profile)

    class NoAuthority:
        def verify_cisco_runtime(self):
            pytest.fail("runtime reached before approval")

    inventory = CountingInventory(device, interface)
    secrets = CountingSecrets()
    collector = Collector([state])
    with pytest.raises(ProfiledExecutionError) as error:
        execute_profiled_plan(
            value, "sha256:" + "0" * 64, inventory, secrets, collector, NoAuthority()
        )
    assert error.value.outcome.value == "BLOCKED"
    assert inventory.resolves == inventory.interfaces == 0
    assert secrets.references == secrets.loads == collector.calls == 0
