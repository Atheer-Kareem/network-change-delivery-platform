"""Tests for bounded, secret-safe Runner result normalization."""

import os
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

from network_change_delivery.ansible_adapter import (
    ACL_READ_COMMANDS,
    ACL_READ_TASK,
    EXECUTION_TASK,
    IDENTITY_TASK,
    VLAN_READ_COMMANDS,
    VLAN_READ_TASK,
    AclReadScope,
    AnsibleRunnerCiscoAdapter,
    HostTrustError,
    ProviderError,
    VlanReadScope,
    _known_hosts_path,
    effective_ansible_collection_path,
)
from network_change_delivery.models import (
    CiscoConfigArtifact,
    ExecutionDisposition,
    InventoryDevice,
)
from network_change_delivery.secrets import DeviceCredentials


@pytest.mark.parametrize("scope", tuple(VlanReadScope))
def test_vlan_read_scope_forwards_only_immutable_exact_commands(
    monkeypatch: pytest.MonkeyPatch, scope: VlanReadScope
) -> None:
    adapter = AnsibleRunnerCiscoAdapter()
    captured: dict[str, object] = {}

    def fake_run(*args: object, **kwargs: object):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return SimpleNamespace(status="successful", rc=0), {
            VLAN_READ_TASK: {"stdout": ["bounded"] * len(VLAN_READ_COMMANDS[scope])}
        }

    monkeypatch.setattr(adapter, "_run", fake_run)
    result = adapter.collect_vlan_read_only(
        object(),
        DeviceCredentials(username="user", password="secret"),
        scope,
        ssh_type="paramiko",
    )
    assert result == ("bounded",) * len(VLAN_READ_COMMANDS[scope])
    assert captured["args"][2] == "collect_vlan_state.yml"
    assert captured["kwargs"]["extravars"] == {
        "ncdp_vlan_commands": list(VLAN_READ_COMMANDS[scope])
    }


@pytest.mark.parametrize(
    "commands",
    [
        (),
        (*VLAN_READ_COMMANDS[VlanReadScope.CORE], "show version"),
        tuple(reversed(VLAN_READ_COMMANDS[VlanReadScope.CORE])),
        ("reload",),
        VLAN_READ_COMMANDS[VlanReadScope.ACCESS][:-1],
    ],
)
def test_arbitrary_vlan_cli_is_rejected_before_runner(
    monkeypatch: pytest.MonkeyPatch, commands: tuple[str, ...]
) -> None:
    adapter = AnsibleRunnerCiscoAdapter()
    called = False

    def fake_run(*_args: object, **_kwargs: object):
        nonlocal called
        called = True
        raise AssertionError("Runner must not receive unadmitted VLAN commands")

    monkeypatch.setattr(adapter, "_run", fake_run)
    with pytest.raises(ProviderError, match="scope is invalid"):
        adapter.collect_vlan_read_only(
            object(),
            DeviceCredentials(username="user", password="secret"),
            commands,  # type: ignore[arg-type]
            ssh_type="paramiko",
        )
    assert not called


def test_acl_read_scope_forwards_only_immutable_exact_commands(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = AnsibleRunnerCiscoAdapter()
    captured: dict[str, object] = {}

    def fake_run(*args: object, **kwargs: object):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return SimpleNamespace(status="successful", rc=0), {
            ACL_READ_TASK: {
                "stdout": ["bounded"]
                * len(ACL_READ_COMMANDS[AclReadScope.SECURITY_POLICY])
            }
        }

    monkeypatch.setattr(adapter, "_run", fake_run)
    result = adapter.collect_acl_read_only(
        object(),
        DeviceCredentials(username="user", password="secret"),
        AclReadScope.SECURITY_POLICY,
        ssh_type="paramiko",
    )
    assert result == ("bounded",) * len(ACL_READ_COMMANDS[AclReadScope.SECURITY_POLICY])
    assert captured["args"][2] == "collect_acl_state.yml"
    assert captured["kwargs"]["extravars"] == {
        "ncdp_acl_commands": list(ACL_READ_COMMANDS[AclReadScope.SECURITY_POLICY])
    }


@pytest.mark.parametrize(
    "commands",
    [
        (),
        (*ACL_READ_COMMANDS[AclReadScope.SECURITY_POLICY], "show version"),
        tuple(reversed(ACL_READ_COMMANDS[AclReadScope.SECURITY_POLICY])),
        ("configure terminal",),
        ACL_READ_COMMANDS[AclReadScope.SECURITY_POLICY][:-1],
    ],
)
def test_arbitrary_acl_cli_is_rejected_before_runner(
    monkeypatch: pytest.MonkeyPatch, commands: tuple[str, ...]
) -> None:
    adapter = AnsibleRunnerCiscoAdapter()
    called = False

    def fake_run(*_args: object, **_kwargs: object):
        nonlocal called
        called = True
        raise AssertionError("Runner must not receive unadmitted ACL commands")

    monkeypatch.setattr(adapter, "_run", fake_run)
    with pytest.raises(ProviderError, match="scope is invalid"):
        adapter.collect_acl_read_only(
            object(),
            DeviceCredentials(username="user", password="secret"),
            commands,  # type: ignore[arg-type]
            ssh_type="paramiko",
        )
    assert not called


def test_runner_error_normalization_is_bounded_and_secret_safe(monkeypatch) -> None:
    adapter = AnsibleRunnerCiscoAdapter()
    secret = "never-copy-this-password"

    def fake_run(*_args, **_kwargs):
        return SimpleNamespace(status="failed", rc=1), {
            EXECUTION_TASK: {"msg": f"raw provider failure {secret}"}
        }

    monkeypatch.setattr(adapter, "_run", fake_run)
    device = InventoryDevice(
        name="router-1",
        host="192.0.2.10",
        platform="cisco_iosxe",
        expected_hostname="lab-router",
    )
    result = adapter.execute(
        device,
        DeviceCredentials(username="user", password=secret),
        CiscoConfigArtifact(
            parent="interface GigabitEthernet2",
            lines=("description managed",),
        ),
    )
    assert result.disposition is ExecutionDisposition.FAILED
    assert secret not in result.message


def test_failed_write_task_is_treated_as_ambiguous(monkeypatch) -> None:
    adapter = AnsibleRunnerCiscoAdapter()

    def fake_run(*_args, **_kwargs):
        return SimpleNamespace(status="failed", rc=1), {
            EXECUTION_TASK: {"_ncdp_event": "runner_on_failed"}
        }

    monkeypatch.setattr(adapter, "_run", fake_run)
    result = adapter.execute(
        InventoryDevice(
            name="router-1",
            host="192.0.2.10",
            platform="cisco_iosxe",
            expected_hostname="lab-router",
        ),
        DeviceCredentials(username="user", password="secret"),
        CiscoConfigArtifact(
            parent="interface GigabitEthernet2",
            lines=("description managed",),
        ),
    )
    assert result.disposition is ExecutionDisposition.AMBIGUOUS


def test_read_only_connection_failure_has_bounded_classification(monkeypatch) -> None:
    adapter = AnsibleRunnerCiscoAdapter()

    monkeypatch.setattr(
        adapter,
        "_run",
        lambda *_args, **_kwargs: (
            SimpleNamespace(status="failed", rc=4),
            {IDENTITY_TASK: {"_ncdp_event": "runner_on_unreachable"}},
        ),
    )
    with pytest.raises(
        ProviderError, match=r"^trusted Cisco SSH collection was unreachable$"
    ):
        adapter.discover(
            InventoryDevice(
                name="router-1",
                host="192.0.2.10",
                platform="cisco_iosxe",
                expected_hostname="lab-router",
            ),
            DeviceCredentials(username="user", password="secret"),
        )


@pytest.mark.parametrize(
    ("message", "classification"),
    [
        (
            "Connection type ansible.builtin.ssh is not valid for this module",
            "Cisco connection type was rejected",
        ),
        ("command timeout triggered", "Cisco read-only command timed out"),
        ("invalid input detected", "Cisco rejected a read-only CLI command"),
        (
            "unrecognized provider module detail",
            "Cisco read-only task failed",
        ),
    ],
)
def test_read_only_task_failure_message_is_allowlist_classified(
    monkeypatch, message: str, classification: str
) -> None:
    adapter = AnsibleRunnerCiscoAdapter()
    monkeypatch.setattr(
        adapter,
        "_run",
        lambda *_args, **_kwargs: (
            SimpleNamespace(status="failed", rc=2),
            {
                IDENTITY_TASK: {
                    "_ncdp_event": "runner_on_failed",
                    "msg": message,
                }
            },
        ),
    )
    with pytest.raises(ProviderError, match=classification):
        adapter.discover(
            InventoryDevice(
                name="router-1",
                host="192.0.2.10",
                platform="cisco_iosxe",
                expected_hostname="lab-router",
            ),
            DeviceCredentials(username="user", password="secret"),
        )


def test_unknown_task_exception_is_bounded_and_secret_free(monkeypatch) -> None:
    adapter = AnsibleRunnerCiscoAdapter()
    secret = "must-not-escape"
    monkeypatch.setattr(
        adapter,
        "_run",
        lambda *_args, **_kwargs: (
            SimpleNamespace(status="failed", rc=2),
            {
                IDENTITY_TASK: {
                    "_ncdp_event": "runner_on_failed",
                    "msg": "failed",
                    "exception": f"traceback path and {secret}: VendorProtocolError",
                }
            },
        ),
    )
    with pytest.raises(ProviderError, match=r"^Cisco read-only task failed$") as caught:
        adapter.discover(
            InventoryDevice(
                name="router-1",
                host="192.0.2.10",
                platform="cisco_iosxe",
                expected_hostname="lab-router",
            ),
            DeviceCredentials(username="user", password=secret),
        )
    assert secret not in str(caught.value)


def test_known_hosts_path_ignores_custom_environment(
    monkeypatch,
) -> None:
    monkeypatch.setenv("NCDP_KNOWN_HOSTS", "/tmp/not-used")
    assert _known_hosts_path() == Path.home() / ".ssh" / "known_hosts"


def test_runner_uses_the_shared_effective_collection_path(
    tmp_path: Path, monkeypatch
) -> None:
    collection_root = tmp_path / "agent-collections"
    monkeypatch.setenv("ANSIBLE_COLLECTIONS_PATH", str(collection_root))
    monkeypatch.setenv("NCDP_DEVICE_USERNAME", "parent-user")
    monkeypatch.setenv("NCDP_DEVICE_PASSWORD", "parent-password")
    monkeypatch.setattr(
        "network_change_delivery.ansible_adapter.verify_existing_host_trust",
        lambda _device: "safe fingerprint",
    )
    captured = {}

    def fake_run(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(status="successful", rc=0)

    monkeypatch.setattr(
        "network_change_delivery.ansible_adapter.ansible_runner.run", fake_run
    )
    adapter = AnsibleRunnerCiscoAdapter(tmp_path)
    adapter._run(
        InventoryDevice(
            name="router-1",
            host="192.0.2.10",
            platform="cisco_iosxe",
            expected_hostname="lab-router",
        ),
        DeviceCredentials(username="user", password="secret"),
        "collect_interface_state.yml",
    )
    assert captured["envvars"]["ANSIBLE_COLLECTIONS_PATH"] == (
        effective_ansible_collection_path(tmp_path)
    )
    assert captured["envvars"]["NCDP_DEVICE_USERNAME"] == "user"
    assert captured["envvars"]["NCDP_DEVICE_PASSWORD"] == "secret"
    assert captured["envvars"]["ANSIBLE_HOST_KEY_CHECKING"] == "True"
    assert "ANSIBLE_HOST_KEY_AUTO_ADD" not in captured["envvars"]
    assert "ANSIBLE_LIBSSH_HOST_KEY_AUTO_ADD" not in captured["envvars"]
    assert captured["envvars"]["ANSIBLE_PERSISTENT_CONTROL_PATH_DIR"].endswith("/pc")
    assert len(captured["envvars"]["ANSIBLE_PERSISTENT_CONTROL_PATH_DIR"]) < 90
    assert os.environ["NCDP_DEVICE_USERNAME"] == "parent-user"
    assert os.environ["NCDP_DEVICE_PASSWORD"] == "parent-password"


def test_runner_gives_paramiko_the_run_scoped_known_hosts_home(
    tmp_path: Path, monkeypatch
) -> None:
    known_hosts = tmp_path / "dedicated-trust" / "known_hosts"
    known_hosts.parent.mkdir()
    known_hosts.write_text("hashed trusted host key\n", encoding="utf-8")
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "network_change_delivery.ansible_adapter.verify_existing_host_trust",
        lambda _device, _path: "safe fingerprint",
    )

    def fake_run(**kwargs):
        captured["home"] = kwargs["envvars"]["HOME"]
        projected = Path(captured["home"]) / ".ssh" / "known_hosts"
        captured["known_hosts"] = projected.read_text(encoding="utf-8")
        captured["known_hosts_mode"] = stat.S_IMODE(projected.stat().st_mode)
        captured["inventory"] = kwargs["inventory"]
        return SimpleNamespace(status="successful", rc=0)

    monkeypatch.setattr(
        "network_change_delivery.ansible_adapter.ansible_runner.run", fake_run
    )
    adapter = AnsibleRunnerCiscoAdapter(tmp_path, known_hosts=known_hosts)
    adapter._run(
        InventoryDevice(
            name="router-1",
            host="192.0.2.10",
            platform="cisco_iosxe",
            expected_hostname="lab-router",
        ),
        DeviceCredentials(username="user", password="secret"),
        "collect_interface_state.yml",
    )

    assert Path(captured["home"]).name == "home"
    assert captured["known_hosts"] == "hashed trusted host key\n"
    assert captured["known_hosts_mode"] == 0o600
    target = captured["inventory"]["all"]["hosts"]["ncdp_target"]
    assert target["ansible_network_cli_ssh_type"] == "paramiko"
    assert "ansible_user" not in target
    assert "ansible_password" not in target


@pytest.mark.parametrize("invalid_file", [False, True])
def test_runner_rejects_missing_or_invalid_private_host_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, invalid_file: bool
) -> None:
    known_hosts = tmp_path / "private-trust" / "known_hosts"
    if invalid_file:
        known_hosts.parent.mkdir()
        known_hosts.write_text(
            "192.0.2.99 ssh-ed25519 AAAA\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(
            "network_change_delivery.ansible_adapter.subprocess.run",
            lambda *_args, **_kwargs: SimpleNamespace(returncode=1, stdout=""),
        )
    adapter = AnsibleRunnerCiscoAdapter(tmp_path, known_hosts=known_hosts)
    with pytest.raises(HostTrustError):
        adapter._run(
            InventoryDevice(
                name="router-1",
                host="192.0.2.10",
                platform="cisco_iosxe",
                expected_hostname="lab-router",
            ),
            DeviceCredentials(username="user", password="secret"),
            "apply_snmp_provisioning.yml",
        )
