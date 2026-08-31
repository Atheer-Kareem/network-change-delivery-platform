"""Detour B3-2 explicit local NetBox migration tests."""

from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/netbox/migrate_b3_inventory.py"


def load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("netbox_b3_migration", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def container_payload(*, host_ip: str = "127.0.0.1") -> str:
    return json.dumps(
        [
            {
                "Config": {
                    "Labels": {
                        "com.docker.compose.project": "netbox-docker",
                        "com.docker.compose.service": "netbox",
                    }
                },
                "State": {"Running": True},
                "NetworkSettings": {
                    "Ports": {"8080/tcp": [{"HostIp": host_ip, "HostPort": "8000"}]}
                },
            }
        ]
    )


def test_exact_b3_device_interface_address_and_cable_contract_is_frozen() -> None:
    migration = load_migration()
    assert migration.NEW_DEVICE_SPECS == {
        "transit-ios-01": {
            "device_type_slug": "iosv-159-3-m12",
            "role_slug": "transit",
            "interfaces": (
                "GigabitEthernet0/0",
                "GigabitEthernet0/1",
                "GigabitEthernet0/2",
                "GigabitEthernet0/3",
            ),
            "management_interface": "GigabitEthernet0/0",
            "live": "192.168.4.16/24",
            "staging": "192.168.4.31/24",
        },
        "access-sw-01": {
            "device_type_slug": "iosvl2-2020",
            "role_slug": "access",
            "interfaces": (
                "GigabitEthernet0/0",
                "GigabitEthernet0/1",
                "GigabitEthernet0/2",
                "GigabitEthernet0/3",
            ),
            "management_interface": "GigabitEthernet0/0",
            "live": "192.168.4.17/24",
            "staging": "192.168.4.32/24",
        },
    }
    assert migration.CABLE_SPECS == (
        (("core-02", "GigabitEthernet4"), ("edge-junos-01", "ge-0/0/0")),
        (
            ("core-02", "GigabitEthernet2"),
            ("transit-ios-01", "GigabitEthernet0/1"),
        ),
        (
            ("edge-junos-01", "ge-0/0/1"),
            ("transit-ios-01", "GigabitEthernet0/2"),
        ),
        (
            ("core-02", "GigabitEthernet3"),
            ("access-sw-01", "GigabitEthernet0/1"),
        ),
    )


def test_population_and_metadata_contract_does_not_grant_legacy_authority() -> None:
    migration = load_migration()
    assert set(migration.ROLE_SPECS) == {"core", "edge", "transit", "access"}
    assert set(migration.TAG_SPECS) == {
        "ncdp-profiled-inventory",
        "ncdp-management-attachment",
        "ncdp-management-live",
        "ncdp-management-staging",
    }
    assert "ncdp-managed" not in migration.TAG_SPECS


def test_migration_has_no_delete_or_normal_token_path() -> None:
    source = SCRIPT.read_text()
    assert ".delete(" not in source
    assert "requests.delete" not in source
    assert "client.delete" not in source
    assert "netbox-token" not in source
    assert "Authorization" not in source
    assert "OpenBao" not in source


def test_container_identity_requires_exact_loopback_listener() -> None:
    migration = load_migration()
    migration.validate_container_identity(container_payload())
    with pytest.raises(migration.MigrationError, match="listener boundary"):
        migration.validate_container_identity(container_payload(host_ip="0.0.0.0"))


def test_operator_executes_reviewed_source_in_exact_admin_shell(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration = load_migration()
    calls: list[tuple[list[str], dict[str, object]]] = []
    result = {"schema_version": "1", "devices": [], "cables": []}

    def run(arguments: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append((arguments, kwargs))
        if arguments[:2] == ["docker", "inspect"]:
            return subprocess.CompletedProcess(arguments, 0, container_payload(), "")
        return subprocess.CompletedProcess(
            arguments,
            0,
            f"noise\n{migration.RESULT_PREFIX}{json.dumps(result)}\n",
            "",
        )

    monkeypatch.setattr(migration.subprocess, "run", run)
    assert migration.run_operator_migration() == result
    assert len(calls) == 2
    inspect_arguments, inspect_options = calls[0]
    assert inspect_arguments == ["docker", "inspect", migration.CONTAINER]
    assert inspect_options["shell"] is False
    command_arguments, command_options = calls[1]
    assert command_arguments[:5] == [
        "docker",
        "exec",
        "-i",
        "-e",
        f"{migration.INSIDE_MARKER}=1",
    ]
    assert migration.MANAGE_PY in command_arguments
    assert command_arguments[-2] == "-c"
    assert command_options["shell"] is False
    assert command_options["input"].endswith("migration_main()\n")
    assert "netbox-token" not in str(command_options["input"])


def test_admin_failure_is_bounded_and_does_not_echo_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration = load_migration()
    calls = 0

    def run(
        arguments: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        if calls == 1:
            return subprocess.CompletedProcess(arguments, 0, container_payload(), "")
        return subprocess.CompletedProcess(arguments, 1, "", "sensitive-local-output")

    monkeypatch.setattr(migration.subprocess, "run", run)
    with pytest.raises(migration.MigrationError) as caught:
        migration.run_operator_migration()
    assert "sensitive-local-output" not in str(caught.value)
