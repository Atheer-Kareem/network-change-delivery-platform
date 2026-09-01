"""Bounded B4-3 NetBox VLAN gateway migration contracts."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts/netbox/migrate_b4_vlan_gateways.py"


def load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("migrate_b4_vlan", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def container_payload(**changes: object) -> str:
    values = {
        "project": "netbox-docker",
        "service": "netbox",
        "host_ip": "127.0.0.1",
        "host_port": "8000",
        "running": True,
        **changes,
    }
    return json.dumps(
        [
            {
                "Config": {
                    "Labels": {
                        "com.docker.compose.project": values["project"],
                        "com.docker.compose.service": values["service"],
                    }
                },
                "NetworkSettings": {
                    "Ports": {
                        "8080/tcp": [
                            {
                                "HostIp": values["host_ip"],
                                "HostPort": values["host_port"],
                            }
                        ]
                    }
                },
                "State": {"Running": values["running"]},
            }
        ]
    )


def test_exact_gateway_catalog_and_no_l2_or_delete_authority() -> None:
    migration = load_migration()
    assert migration.GATEWAY_TAG == "ncdp-vlan-gateway"
    assert [item["name"] for item in migration.SUBINTERFACE_SPECS] == [
        "GigabitEthernet3.10",
        "GigabitEthernet3.20",
    ]
    assert [item["address"] for item in migration.SUBINTERFACE_SPECS] == [
        "10.60.10.1/24",
        "10.60.20.1/24",
    ]
    source = SCRIPT.read_text()
    assert ".delete(" not in source
    assert "transaction.atomic()" in source
    assert "EXPECTED_DATA_PLANE_IP_IDS = frozenset({17, 18, 19, 20, 21, 22})" in source
    assert "EXPECTED_ROUTING_IDENTITY_IP_IDS = frozenset({23, 24, 25})" in source
    assert "primary_ip4 =" not in source
    assert "tagged_vlans.add" not in source
    assert "untagged_vlan =" not in source


@pytest.mark.parametrize(
    "changes",
    [
        {"project": "other"},
        {"service": "other"},
        {"host_ip": "0.0.0.0"},
        {"host_port": "8080"},
        {"running": False},
    ],
)
def test_container_boundary_fails_closed(changes: dict[str, object]) -> None:
    migration = load_migration()
    with pytest.raises(migration.MigrationError):
        migration.validate_container_identity(container_payload(**changes))


def test_wrapper_uses_nbshell_and_hides_admin_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration = load_migration()
    calls: list[list[str]] = []

    def run(
        arguments: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        calls.append(arguments)
        if len(calls) == 1:
            return subprocess.CompletedProcess(arguments, 0, container_payload(), "")
        result = {"changes": {"created": [], "updated": [], "reused": []}}
        return subprocess.CompletedProcess(
            arguments, 0, migration.RESULT_PREFIX + json.dumps(result) + "\n", ""
        )

    monkeypatch.setattr(migration.subprocess, "run", run)
    migration.run_operator_migration()
    assert calls[0] == ["docker", "inspect", migration.CONTAINER]
    assert "nbshell" in calls[1]

    def fail(
        arguments: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        if arguments[1] == "inspect":
            return subprocess.CompletedProcess(arguments, 0, container_payload(), "")
        return subprocess.CompletedProcess(arguments, 1, "", "sensitive-admin-output")

    monkeypatch.setattr(migration.subprocess, "run", fail)
    with pytest.raises(migration.MigrationError) as caught:
        migration.run_operator_migration()
    assert "sensitive-admin-output" not in str(caught.value)


def test_second_run_zero_changes_is_idempotent(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    migration = load_migration()
    result = {
        "changes": {
            "created": [],
            "updated": [],
            "reused": ["tag:11", "interface:21", "interface:22", "ip:26", "ip:27"],
        }
    }
    monkeypatch.setattr(migration, "run_operator_migration", lambda: result)
    monkeypatch.setattr(sys, "argv", [str(SCRIPT)])
    assert migration.main() == 0
    assert "created=0 updated=0 reused=5" in capsys.readouterr().out
