from __future__ import annotations

import importlib.util
import inspect
import stat
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from network_change_delivery.ansible_adapter import (
    ProviderError,
    ProviderReadinessError,
)
from network_change_delivery.models import InventoryDevice

SCRIPT = Path(__file__).parents[1] / "scripts/run_ephemeral_cml_staging.py"
SPEC = importlib.util.spec_from_file_location("run_ephemeral_cml_staging", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
driver = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(driver)


def test_staging_phase_markers_are_complete_and_ordered() -> None:
    assert driver.PHASE_MARKERS == (
        "Admission & authority",
        "Terraform create",
        "CML topology & Day-0 verification",
        "Lab start",
        "Device readiness",
        "Strict host trust",
        "NCDP Cisco staging validation · READ-ONLY",
        "NCDP Junos staging validation · READ-ONLY",
        "Terraform destroy",
        "Independent absence verification",
        "Run-scoped state retirement",
        "Final staging result",
    )
    source = SCRIPT.read_text(encoding="utf-8")
    assert "+++ :cloud:" in source
    assert source.count("emit_phase(") == len(driver.PHASE_MARKERS)


def test_readiness_progress_preserves_checks_timeout_and_low_volume(
    monkeypatch, capsys
) -> None:
    operations = object.__new__(driver.LocalOperations)
    monotonic = iter((0.0, 0.0, 1.0, 31.0, 32.0))
    probes = iter((1, 1, 0, 0))
    ports: list[int] = []
    sleeps: list[int] = []

    monkeypatch.setattr(driver.time, "monotonic", lambda: next(monotonic))
    monkeypatch.setattr(driver.time, "sleep", sleeps.append)
    monkeypatch.setattr(
        driver.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=next(probes)),
    )

    def endpoint_ready(_host: str, port: int) -> bool:
        ports.append(port)
        return True

    operations._endpoint_ready = endpoint_ready
    duration = operations._wait_device("core_02", "core-02", "192.168.4.30")

    output = capsys.readouterr().out
    assert duration == 32.0
    assert sleeps == [10]
    assert ports == [22, 830]
    assert output.count("readiness core_02/core-02") == 3
    assert "ARP=WAITING ICMP=WAITING TCP/22=WAITING TCP/830=WAITING" in output
    assert "ARP=PASS ICMP=PASS TCP/22=PASS TCP/830=PASS duration=32.0s" in output
    assert (
        inspect.signature(driver.LocalOperations._wait_device)
        .parameters["timeout"]
        .default
        == 1200
    )


def device(name: str, device_id: int, host: str, platform: str) -> InventoryDevice:
    return InventoryDevice(
        name=name,
        host=host,
        port=22 if platform == "cisco_iosxe" else 830,
        platform=platform,
        expected_hostname=name,
        inventory_source="netbox",
        inventory_object_id=f"netbox:dcim.device:{device_id}",
        inventory_interface_object_id=(
            "netbox:dcim.interface:1" if device_id == 1 else "netbox:dcim.interface:3"
        ),
    )


def test_exact_two_router_staging_graph_and_addresses() -> None:
    source = SCRIPT.read_text()
    assert {
        "system_bridge",
        "management_switch",
        "core_02",
        "edge_junos_01",
    } == driver.EXPECTED_NODES
    assert {
        "system_bridge_management",
        "management_core_02",
        "management_edge_junos_01",
        "core_02_edge_junos_01",
    } == driver.EXPECTED_LINKS
    assert 'for host in ("192.168.4.30", "192.168.4.40")' in source
    assert '"192.168.4.14",\n                "192.168.4.30/24"' in source
    assert '"192.168.4.20",\n                "192.168.4.40/24"' in source
    assert "ncdp/devices/{1 if role == 'core_02' else 2}/ssh" in source
    assert "_require_lab_stopped(LEGACY_LAB" not in source
    assert 'values.get("lab_id") == LEGACY_LAB' in source


def test_running_persistent_live_lab_does_not_block_staging_admission(
    tmp_path: Path, monkeypatch
) -> None:
    operations = object.__new__(driver.LocalOperations)
    operations.run_directory = tmp_path / "ephemeral" / "bk-test"
    operations.data_directory = operations.run_directory / "terraform-data"
    operations.state_path = operations.run_directory / "terraform.tfstate"
    operations._buildkite_context = None
    stopped_checks: list[tuple[str, str]] = []
    operations._lab_ids = lambda: [driver.LEGACY_LAB]
    operations._lab = lambda _lab_id: {"title": "NCDP Live", "state": "STARTED"}
    operations._require_lab_stopped = lambda lab_id, label: stopped_checks.append(
        (lab_id, label)
    )
    operations._resolve_authority = lambda: None
    operations._run_plain = lambda _command: ""
    monkeypatch.setattr(
        driver.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=1),
    )

    operations.admit()

    assert stopped_checks == [(driver.SCRATCH_LAB, "scratch")]
    assert operations.run_directory.is_dir()


@pytest.mark.parametrize(
    ("cidr", "interface_id"),
    (("192.168.4.30/24", 1), ("192.168.4.40/24", 3)),
)
def test_secondary_address_requires_exact_interface(
    monkeypatch, cidr: str, interface_id: int
) -> None:
    payload = {
        "count": 1,
        "results": [
            {
                "address": cidr,
                "status": {"value": "active"},
                "assigned_object_type": "dcim.interface",
                "assigned_object_id": interface_id,
            }
        ],
    }

    class Client:
        def __init__(self, **_kwargs):
            pass

        def get(self, *_args, **_kwargs):
            return httpx.Response(200, json=payload)

        def close(self):
            pass

    monkeypatch.setattr(driver.httpx, "Client", Client)
    driver.LocalOperations._verify_secondary_address(
        "http://127.0.0.1:8000", "token", cidr, interface_id
    )
    payload["results"][0]["assigned_object_id"] = 99
    with pytest.raises(driver.StagingError, match="authority mismatch"):
        driver.LocalOperations._verify_secondary_address(
            "http://127.0.0.1:8000", "token", cidr, interface_id
        )


def test_staging_inventory_keeps_logical_identity_and_changes_only_endpoint() -> None:
    live = device("core-02", 1, "192.168.4.14", "cisco_iosxe")
    staged = live.model_copy(update={"host": "192.168.4.30"})

    class Inventory:
        def resolve(self, target, interface=None):
            assert target == "core-02"
            assert interface == "GigabitEthernet2"
            return live.model_copy(
                update={"inventory_interface_object_id": "netbox:dcim.interface:2"}
            )

    resolved = driver.StagingInventory(Inventory(), {"core_02": staged}).resolve(
        "core-02", "GigabitEthernet2"
    )
    assert resolved.host == "192.168.4.30"
    assert resolved.inventory_object_id == "netbox:dcim.device:1"
    assert resolved.inventory_interface_object_id == "netbox:dcim.interface:2"


def test_provider_read_retries_bounded_provider_failures(monkeypatch) -> None:
    calls = 0

    def action() -> None:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise ProviderReadinessError("bounded provider read failed")

    monkeypatch.setattr(driver.time, "monotonic", lambda: 0.0)
    monkeypatch.setattr(driver.time, "sleep", lambda _seconds: None)

    assert driver.retry_provider_read(action) == 3


def test_provider_read_does_not_retry_non_provider_failure(monkeypatch) -> None:
    sleeps = []
    monkeypatch.setattr(driver.time, "sleep", sleeps.append)

    with pytest.raises(ValueError, match="policy failed"):
        driver.retry_provider_read(
            lambda: (_ for _ in ()).throw(ValueError("policy failed"))
        )

    assert sleeps == []


def test_provider_read_stops_at_deadline(monkeypatch) -> None:
    monkeypatch.setattr(driver.time, "sleep", lambda _seconds: None)

    with pytest.raises(ProviderReadinessError, match="still unavailable"):
        driver.retry_provider_read(
            lambda: (_ for _ in ()).throw(ProviderReadinessError("still unavailable")),
            timeout=0,
        )


def test_provider_read_does_not_retry_deterministic_provider_error(
    monkeypatch,
) -> None:
    sleeps = []
    monkeypatch.setattr(driver.time, "sleep", sleeps.append)

    with pytest.raises(ProviderError, match="deterministic task failure"):
        driver.retry_provider_read(
            lambda: (_ for _ in ()).throw(ProviderError("deterministic task failure"))
        )

    assert sleeps == []


def test_host_key_acquisition_retries_and_creates_restrictive_trust(
    tmp_path: Path, monkeypatch
) -> None:
    operations = object.__new__(driver.LocalOperations)
    operations._known_hosts = tmp_path / ".ssh" / "known_hosts"
    scans = iter(
        (
            SimpleNamespace(returncode=1, stdout=""),
            SimpleNamespace(returncode=0, stdout="hash-1 ssh-ed25519 AAAA\n"),
            SimpleNamespace(returncode=0, stdout="hash-2 ssh-ed25519 AAAA\n"),
            SimpleNamespace(returncode=0, stdout="hash-3 ssh-ed25519 AAAA\n"),
        )
    )

    def run(command, **_kwargs):
        if command[0] == "ssh-keygen":
            return SimpleNamespace(returncode=0, stdout="")
        return next(scans)

    monkeypatch.setattr(driver.subprocess, "run", run)
    monkeypatch.setattr(driver.time, "monotonic", lambda: 0.0)
    monkeypatch.setattr(driver.time, "sleep", lambda _seconds: None)

    operations._establish_host_trust("192.0.2.10", (22,))

    assert operations._known_hosts.read_text() == "hash-3 ssh-ed25519 AAAA\n"
    assert stat.S_IMODE(operations._known_hosts.stat().st_mode) == 0o600
