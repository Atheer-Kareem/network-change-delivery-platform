"""Bounded B4-2 NetBox router-ID migration contracts."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts/netbox/migrate_b4_ospf_router_ids.py"


def load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("migrate_b4_ospf", SCRIPT)
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


def test_exact_router_id_catalog_and_no_loopback_or_data_plane_tag() -> None:
    migration = load_migration()
    assert migration.POOL_ID == 8
    assert migration.POOL_PREFIX == "10.60.255.0/24"
    assert migration.ROUTING_IDENTITY_TAG == "ncdp-routing-identity"
    assert [item["device_id"] for item in migration.ROUTER_ID_SPECS] == [1, 2, 8]
    assert [item["address"] for item in migration.ROUTER_ID_SPECS] == [
        "10.60.255.1/32",
        "10.60.255.2/32",
        "10.60.255.3/32",
    ]
    source = SCRIPT.read_text()
    assert "Loopback" not in source
    assert ".delete(" not in source
    assert "assigned_object=" not in source
    assert "primary_ip4 =" not in source
    assert "transaction.atomic()" in source
    assert "EXPECTED_DATA_PLANE_IP_IDS = frozenset({17, 18, 19, 20, 21, 22})" in source


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"project": "other"}, "Compose"),
        ({"service": "other"}, "Compose"),
        ({"host_ip": "0.0.0.0"}, "listener"),
        ({"host_port": "8080"}, "listener"),
        ({"running": False}, "running"),
    ],
)
def test_container_boundary_fails_closed(
    changes: dict[str, object], message: str
) -> None:
    migration = load_migration()
    with pytest.raises(migration.MigrationError, match=message):
        migration.validate_container_identity(container_payload(**changes))


def test_host_wrapper_uses_reviewed_nbshell_and_hides_admin_output(
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
        result = {
            "schema_version": "1",
            "changes": {"created": [], "updated": [], "reused": []},
        }
        return subprocess.CompletedProcess(
            arguments,
            0,
            migration.RESULT_PREFIX + json.dumps(result) + "\n",
            "",
        )

    monkeypatch.setattr(migration.subprocess, "run", run)
    migration.run_operator_migration()
    assert calls[0] == ["docker", "inspect", migration.CONTAINER]
    assert calls[1][:5] == [
        "docker",
        "exec",
        "-i",
        "-e",
        f"{migration.INSIDE_MARKER}=1",
    ]
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


def test_second_run_zero_changes_is_reported_idempotent(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    migration = load_migration()
    result = {
        "changes": {
            "created": [],
            "updated": [],
            "reused": ["tag:ncdp-routing-identity:9", "ip:23", "ip:24", "ip:25"],
        }
    }
    monkeypatch.setattr(migration, "run_operator_migration", lambda: result)
    monkeypatch.setattr(sys, "argv", [str(SCRIPT)])
    assert migration.main() == 0
    assert "created=0 updated=0 reused=4" in capsys.readouterr().out
