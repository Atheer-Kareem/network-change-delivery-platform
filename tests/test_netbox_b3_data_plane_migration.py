"""Bounded B3-5 local NetBox migration operator tests."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts/netbox/migrate_b3_data_plane.py"


def load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("migrate_b3_data_plane", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def container_payload(
    *,
    project: str = "netbox-docker",
    service: str = "netbox",
    host_ip: str = "127.0.0.1",
    host_port: str = "8000",
    running: bool = True,
) -> str:
    return json.dumps(
        [
            {
                "Config": {
                    "Labels": {
                        "com.docker.compose.project": project,
                        "com.docker.compose.service": service,
                    }
                },
                "NetworkSettings": {
                    "Ports": {"8080/tcp": [{"HostIp": host_ip, "HostPort": host_port}]}
                },
                "State": {"Running": running},
            }
        ]
    )


def test_exact_migration_catalog_has_no_service_allocations() -> None:
    migration = load_migration()
    assert [item["prefix"] for item in migration.PREFIX_SPECS] == [
        "10.60.0.0/16",
        "10.60.0.0/30",
        "10.60.0.4/30",
        "10.60.0.8/30",
        "10.60.10.0/24",
        "10.60.20.0/24",
        "10.60.255.0/24",
    ]
    assert migration.VLAN_SPECS == {
        10: {"name": "USERS", "description": "NCDP USERS service identity"},
        20: {"name": "SERVERS", "description": "NCDP SERVERS service identity"},
    }
    assert [item["address"] for item in migration.ROUTED_IP_SPECS] == [
        "10.60.0.1/30",
        "10.60.0.2/30",
        "10.60.0.5/30",
        "10.60.0.6/30",
        "10.60.0.9/30",
        "10.60.0.10/30",
    ]
    assert [item["interface_id"] for item in migration.ROUTED_IP_SPECS] == [
        11,
        12,
        2,
        14,
        4,
        15,
    ]
    assert {item["prefix"]: item["vlan_vid"] for item in migration.PREFIX_SPECS} == {
        "10.60.0.0/16": None,
        "10.60.0.0/30": None,
        "10.60.0.4/30": None,
        "10.60.0.8/30": None,
        "10.60.10.0/24": 10,
        "10.60.20.0/24": 20,
        "10.60.255.0/24": None,
    }
    source = SCRIPT.read_text()
    for deferred in (
        "10.60.10.1",
        "10.60.20.1",
        'GigabitEthernet3"',
        'access-sw-01",\n        "interface_id',
    ):
        assert deferred not in source


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


def test_host_wrapper_is_secret_free_and_uses_reviewed_admin_shell(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration = load_migration()
    calls: list[tuple[list[str], dict[str, object]]] = []
    result = {
        "schema_version": "1",
        "changes": {"created": [], "updated": [], "reused": ["prefix:2"]},
    }

    def run(arguments: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append((arguments, kwargs))
        if len(calls) == 1:
            return subprocess.CompletedProcess(arguments, 0, container_payload(), "")
        return subprocess.CompletedProcess(
            arguments,
            0,
            f"framework noise\n{migration.RESULT_PREFIX}{json.dumps(result)}\n",
            "",
        )

    monkeypatch.setattr(migration.subprocess, "run", run)
    assert migration.run_operator_migration() == result
    assert calls[0][0] == ["docker", "inspect", migration.CONTAINER]
    arguments, options = calls[1]
    assert arguments[:5] == [
        "docker",
        "exec",
        "-i",
        "-e",
        f"{migration.INSIDE_MARKER}=1",
    ]
    assert migration.MANAGE_PY in arguments
    assert options["shell"] is False
    assert str(options["input"]).endswith("migration_main()\n")
    assert "netbox-token" not in str(options["input"])


def test_no_effective_change_result_is_reported_as_idempotent(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    migration = load_migration()
    result = {
        "changes": {
            "created": [],
            "updated": [],
            "reused": [f"object:{number}" for number in range(17)],
        },
        "prefixes": [],
        "vlans": [],
        "routed_ips": [],
    }
    monkeypatch.setattr(migration, "run_operator_migration", lambda: result)
    monkeypatch.setattr(sys, "argv", [str(SCRIPT)])
    assert migration.main() == 0
    assert "created=0 updated=0 reused=17" in capsys.readouterr().out


def test_permission_and_non_mutation_contract_is_narrow() -> None:
    source = SCRIPT.read_text()
    assert 'READ_PERMISSION_NAME = "NCDP data-plane read-only"' in source
    assert 'actions=["view"]' in source
    assert 'username="ncdp-netbox-reader"' in source
    assert "ContentType.objects.get_for_model(Prefix)" in source
    assert "ContentType.objects.get_for_model(VLAN)" in source
    assert 'filter(name=spec["name"]).exclude(vid=vid)' in source
    assert "write_enabled" not in source
    assert ".delete(" not in source
    assert "primary_ip4 =" not in source
    assert "management_snapshot() != before_management" in source
    assert '"management_unchanged": True' in source
    assert "transaction.atomic()" in source


def test_admin_failure_is_bounded_and_hides_output(
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
        return subprocess.CompletedProcess(arguments, 1, "", "sensitive-admin-output")

    monkeypatch.setattr(migration.subprocess, "run", run)
    with pytest.raises(migration.MigrationError) as caught:
        migration.run_operator_migration()
    assert "sensitive-admin-output" not in str(caught.value)
