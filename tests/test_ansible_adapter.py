"""Tests for bounded, secret-safe Runner result normalization."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from network_change_delivery.ansible_adapter import (
    EXECUTION_TASK,
    IDENTITY_TASK,
    AnsibleRunnerCiscoAdapter,
    ProviderError,
    _known_hosts_path,
    effective_ansible_collection_path,
)
from network_change_delivery.models import (
    CiscoConfigArtifact,
    ExecutionDisposition,
    InventoryDevice,
)
from network_change_delivery.secrets import DeviceCredentials


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
            "signals=module shape=none exception_type=none frames=none "
            "structural_tokens=none exception_kind=NoneType exception_length=0 "
            "exception_lines=0",
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


def test_read_only_task_exception_is_allowlist_classified(monkeypatch) -> None:
    adapter = AnsibleRunnerCiscoAdapter()
    monkeypatch.setattr(
        adapter,
        "_run",
        lambda *_args, **_kwargs: (
            SimpleNamespace(status="failed", rc=2),
            {
                IDENTITY_TASK: {
                    "_ncdp_event": "runner_on_failed",
                    "msg": "failed",
                    "exception": "traceback omitted: AttributeError",
                }
            },
        ),
    )
    with pytest.raises(ProviderError, match="runtime attribute failed"):
        adapter.discover(
            InventoryDevice(
                name="router-1",
                host="192.0.2.10",
                platform="cisco_iosxe",
                expected_hostname="lab-router",
            ),
            DeviceCredentials(username="user", password="secret"),
        )


def test_unknown_task_exception_exposes_only_bounded_class_name(monkeypatch) -> None:
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
    with pytest.raises(ProviderError) as caught:
        adapter.discover(
            InventoryDevice(
                name="router-1",
                host="192.0.2.10",
                platform="cisco_iosxe",
                expected_hostname="lab-router",
            ),
            DeviceCredentials(username="user", password=secret),
        )
    assert "exception_type=VendorProtocolError" in str(caught.value)
    assert secret not in str(caught.value)


def test_unknown_task_exception_exposes_only_bounded_frames(monkeypatch) -> None:
    adapter = AnsibleRunnerCiscoAdapter()
    secret = "must-not-escape"
    exception = (
        f'Traceback: File "/private/{secret}/network.py", line 12, in run\n'
        'File "/private/provider/action.py", line 34, in execute\n'
    )
    monkeypatch.setattr(
        adapter,
        "_run",
        lambda *_args, **_kwargs: (
            SimpleNamespace(status="failed", rc=2),
            {
                IDENTITY_TASK: {
                    "_ncdp_event": "runner_on_failed",
                    "msg": "failed",
                    "exception": exception,
                }
            },
        ),
    )
    with pytest.raises(ProviderError) as caught:
        adapter.discover(
            InventoryDevice(
                name="router-1",
                host="192.0.2.10",
                platform="cisco_iosxe",
                expected_hostname="lab-router",
            ),
            DeviceCredentials(username="user", password=secret),
        )
    assert "frames=network.py:run,action.py:execute" in str(caught.value)
    assert "structural_tokens=Traceback" in str(caught.value)
    assert secret not in str(caught.value)


def test_nonstandard_ansible_failure_class_is_bounded(monkeypatch) -> None:
    adapter = AnsibleRunnerCiscoAdapter()
    monkeypatch.setattr(
        adapter,
        "_run",
        lambda *_args, **_kwargs: (
            SimpleNamespace(status="failed", rc=2),
            {
                IDENTITY_TASK: {
                    "_ncdp_event": "runner_on_failed",
                    "msg": "failed",
                    "exception": "raise ansible.errors.AnsibleActionFail(value)",
                }
            },
        ),
    )
    with pytest.raises(ProviderError, match="exception_type=AnsibleActionFail"):
        adapter.discover(
            InventoryDevice(
                name="router-1",
                host="192.0.2.10",
                platform="cisco_iosxe",
                expected_hostname="lab-router",
            ),
            DeviceCredentials(username="user", password="secret"),
        )


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


def test_runner_gives_libssh_the_run_scoped_known_hosts_file(
    tmp_path: Path, monkeypatch
) -> None:
    known_hosts = tmp_path / ".ssh" / "known_hosts"
    known_hosts.parent.mkdir()
    known_hosts.write_text("hashed trusted host key\n", encoding="utf-8")
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "network_change_delivery.ansible_adapter.verify_existing_host_trust",
        lambda _device, _path: "safe fingerprint",
    )

    def fake_run(**kwargs):
        config = Path(kwargs["envvars"]["ANSIBLE_LIBSSH_CONFIG_FILE"])
        captured["config"] = config.read_text(encoding="utf-8")
        captured["mode"] = config.stat().st_mode & 0o777
        captured["home"] = kwargs["envvars"]["HOME"]
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

    assert captured["config"] == (
        f"Host *\n  StrictHostKeyChecking yes\n  UserKnownHostsFile {known_hosts}\n"
    )
    assert captured["mode"] == 0o600
    assert captured["home"] == str(tmp_path)
