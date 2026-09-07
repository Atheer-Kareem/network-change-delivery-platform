"""Current CLI runtime admission with real manifests and no external providers."""

from types import SimpleNamespace

import pytest
from test_ansible_runtime import PINS, complete_runtime, install_manifest
from test_cli_profiled_deploy import _arguments
from test_profiled_execution import Collector, Inventory, Junos, Secrets, plan

from network_change_delivery import ansible_adapter, cli
from network_change_delivery.architecture_contracts import AutomationProfileID
from network_change_delivery.models import ExecutionDisposition, ExecutionResult
from network_change_delivery.profiled_execution import ProfiledChangeRecord
from network_change_delivery.profiled_write_adapter import ProfiledWriteAdapter


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    root = tmp_path / "project"
    collections = tmp_path / "agent-collections"
    complete_runtime(root, collections)
    monkeypatch.setenv("NCDP_PROJECT_ROOT", str(root))
    monkeypatch.setenv("ANSIBLE_COLLECTIONS_PATH", str(collections))
    monkeypatch.setattr(cli, "DEFAULT_PROFILED_LIVE_TRUST_ROOT", tmp_path / "trust")
    trust = cli.DEFAULT_PROFILED_LIVE_TRUST_ROOT
    trust.mkdir()
    (trust / cli.PROFILED_LIVE_KNOWN_HOSTS_NAME).write_text("fixture trust\n")
    monkeypatch.setattr(cli, "validate_profiled_live_host_trust", lambda: None)
    return root, collections


def compose_cli(
    tmp_path, monkeypatch, events, profile=AutomationProfileID.CAT8000V_IOSXE
):
    value, device, interface, state = plan(profile)
    plan_path, report = tmp_path / "plan.json", tmp_path / "record.json"
    plan_path.write_text(value.model_dump_json())

    class TracedInventory(Inventory):
        def resolve(self, target):
            events.append("inventory")
            return super().resolve(target)

    class TracedSecrets(Secrets):
        def reference(self, target):
            events.append("credential reference")
            return super().reference(target)

        def load(self, target):
            events.append("credential load")
            return super().load(target)

    class TracedCollector(Collector):
        def collect(self, *args):
            events.append("collection")
            return super().collect(*args)

    monkeypatch.setattr(
        cli,
        "NetBoxProfileInventoryProvider",
        lambda: TracedInventory(device, interface),
    )
    monkeypatch.setattr(cli, "OpenBaoSecretProvider", TracedSecrets)
    monkeypatch.setattr(
        cli,
        "ProfileReadOnlyAdapter",
        lambda **_kwargs: TracedCollector(
            [state, state.model_copy(update={"description": "new"})]
        ),
    )
    return _arguments(plan_path, report, value.digest), report


def trace_real_verifier(monkeypatch, events, expected_root):
    verify = ansible_adapter.verify_deployment_ansible_runtime

    def traced(repository_root):
        events.append("runtime")
        assert repository_root == expected_root
        return verify(repository_root)

    monkeypatch.setattr(ansible_adapter, "verify_deployment_ansible_runtime", traced)


@pytest.mark.parametrize("explicit_path", [True, False])
@pytest.mark.parametrize("changed", [True, False, None])
def test_cli_verifies_actual_cisco_runner_path_before_preflight(
    runtime, tmp_path, monkeypatch, explicit_path, changed
):
    root, collections = runtime
    if not explicit_path:
        collections = root / ".ansible" / "collections"
        for name, version in PINS:
            install_manifest(collections, name, version)
        monkeypatch.delenv("ANSIBLE_COLLECTIONS_PATH")
        monkeypatch.setattr(
            ansible_adapter, "SYSTEM_ANSIBLE_COLLECTIONS", tmp_path / "empty-system"
        )
    events = []
    arguments, report = compose_cli(tmp_path, monkeypatch, events)
    trace_real_verifier(monkeypatch, events, root)
    expected_path = ansible_adapter.effective_ansible_collection_path(root)
    monkeypatch.setattr(ansible_adapter, "verify_existing_host_trust", lambda *_a: None)

    def runner(**kwargs):
        events.append("writer")
        assert kwargs["project_dir"] == str(root / "ansible")
        assert kwargs["envvars"]["ANSIBLE_COLLECTIONS_PATH"] == expected_path
        assert str(collections) == expected_path.split(ansible_adapter.os.pathsep)[0]
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
    assert cli.main(arguments) == 0
    assert events == [
        "runtime",
        "inventory",
        "credential reference",
        "credential load",
        "collection",
        "writer",
        "collection",
    ]
    record = ProfiledChangeRecord.model_validate_json(report.read_bytes())
    assert record.final_outcome.value == "SUCCEEDED"
    assert record.execution.attempted and not record.recovery.attempted
    assert record.execution.changed is changed
    assert record.post_validation.changed is True


@pytest.mark.parametrize(
    "failure",
    [
        "missing-netcommon",
        "missing-ios",
        "version",
        "malformed",
        "duplicate",
        "duplicate-path",
        "relative-path",
        "empty-path",
    ],
)
def test_cli_runtime_rejection_is_blocked_before_any_device_boundary(
    runtime, tmp_path, monkeypatch, capsys, failure
):
    root, collections = runtime
    manifest = collections / "ansible_collections/ansible/netcommon/MANIFEST.json"
    if failure.startswith("missing-"):
        if failure == "missing-ios":
            manifest = collections / "ansible_collections/cisco/ios/MANIFEST.json"
        manifest.unlink()
    elif failure == "version":
        install_manifest(collections, "ansible.netcommon", "0.0.1")
    elif failure == "malformed":
        manifest.write_text("private-runtime-sentinel: not-json")
    elif failure == "duplicate":
        other = tmp_path / "duplicate"
        install_manifest(other, *PINS[0])
        monkeypatch.setenv("ANSIBLE_COLLECTIONS_PATH", f"{collections}:{other}")
    elif failure == "duplicate-path":
        monkeypatch.setenv("ANSIBLE_COLLECTIONS_PATH", f"{collections}:{collections}")
    else:
        monkeypatch.setenv(
            "ANSIBLE_COLLECTIONS_PATH",
            "relative/path" if failure == "relative-path" else "",
        )
    events = []
    arguments, report = compose_cli(tmp_path, monkeypatch, events)
    trace_real_verifier(monkeypatch, events, root)
    monkeypatch.setattr(
        ProfiledWriteAdapter,
        "execute_cisco",
        lambda *_a: pytest.fail("writer/recovery"),
    )
    monkeypatch.setattr(
        ansible_adapter.ansible_runner, "run", lambda **_k: pytest.fail("Runner")
    )
    assert cli.main(arguments) == 2
    assert events == ["runtime"]
    record = ProfiledChangeRecord.model_validate_json(report.read_bytes())
    assert record.final_outcome.value == "BLOCKED"
    assert record.preflight.attempted and record.preflight.succeeded is False
    assert (
        record.preflight.message
        == "deployment Ansible runtime prerequisites unavailable"
    )
    assert not record.execution.attempted
    assert not record.post_validation.attempted
    assert not record.recovery.attempted
    assert (
        "private-runtime-sentinel" not in report.read_text() + capsys.readouterr().out
    )


@pytest.mark.usefixtures("runtime")
def test_cli_junos_does_not_require_cisco_runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("ANSIBLE_COLLECTIONS_PATH", "invalid-path")
    monkeypatch.setattr(
        ansible_adapter,
        "verify_deployment_ansible_runtime",
        lambda *_a: pytest.fail("Junos must not verify Cisco collections"),
    )
    events = []
    arguments, report = compose_cli(
        tmp_path, monkeypatch, events, AutomationProfileID.VJUNOS_ROUTER
    )
    success = ExecutionResult(disposition=ExecutionDisposition.SUCCEEDED, message="ok")
    junos = Junos(success, success)
    monkeypatch.setattr(
        cli,
        "ProfiledWriteAdapter",
        lambda **kwargs: ProfiledWriteAdapter(**kwargs, junos=junos),
    )
    assert cli.main(arguments) == 0
    assert junos.commits == 1 and junos.confirms == 1
    assert "runtime" not in events
    assert (
        ProfiledChangeRecord.model_validate_json(
            report.read_bytes()
        ).final_outcome.value
        == "SUCCEEDED"
    )
