"""B2 exact profile-bound collection-only adapter tests."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from network_change_delivery.ansible_adapter import (
    AnsibleRunnerCiscoAdapter,
    ProviderError,
)
from network_change_delivery.architecture_contracts import (
    AdapterFamily,
    AutomationProfileID,
    NetworkOS,
)
from network_change_delivery.models import InterfaceState, InventoryDevice
from network_change_delivery.profile_inventory import ProfileReadOnlyTarget
from network_change_delivery.profile_read_only_adapter import (
    PROFILE_READ_ONLY_TRANSPORTS,
    CiscoSSHBackend,
    ProfileReadOnlyAdapter,
)
from network_change_delivery.secrets import DeviceCredentials

ROOT = Path(__file__).parents[1]
CREDENTIALS = DeviceCredentials(username="test-user", password="test-password")


def target(profile_id: AutomationProfileID) -> ProfileReadOnlyTarget:
    network_os, port = {
        AutomationProfileID.CAT8000V_IOSXE: (NetworkOS.IOSXE, 22),
        AutomationProfileID.IOSV_159_3_M12: (NetworkOS.IOS, 22),
        AutomationProfileID.IOSVL2_2020: (NetworkOS.IOS, 22),
        AutomationProfileID.VJUNOS_ROUTER: (NetworkOS.JUNOS, 830),
    }[profile_id]
    return ProfileReadOnlyTarget(
        logical_name="test-node",
        host="192.0.2.10",
        port=port,
        expected_hostname="test-node",
        protected_interfaces=("Gi0/0",),
        automation_profile_id=profile_id,
        network_os=network_os,
    )


def state(interface: str = "Gi0/1") -> InterfaceState:
    return InterfaceState(
        observed_hostname="test-node",
        software_version="bounded-version",
        interface=interface,
        exists=True,
        protected=False,
    )


class FakeCiscoCollector:
    def __init__(self) -> None:
        self.calls: list[tuple[str, AutomationProfileID, str | None]] = []

    def discover_read_only(
        self,
        target: ProfileReadOnlyTarget,
        _credentials: DeviceCredentials,
        *,
        ssh_type: str,
    ) -> tuple[InterfaceState, ...]:
        self.calls.append(("discover", target.automation_profile_id, ssh_type))
        return (state(),)

    def collect_read_only(
        self,
        target: ProfileReadOnlyTarget,
        _credentials: DeviceCredentials,
        interface: str,
        *,
        ssh_type: str,
    ) -> InterfaceState:
        self.calls.append(("collect", target.automation_profile_id, ssh_type))
        return state(interface)


class FakeJunosCollector:
    def __init__(self) -> None:
        self.calls: list[tuple[str, AutomationProfileID, None]] = []

    def discover_read_only(
        self,
        target: ProfileReadOnlyTarget,
        _credentials: DeviceCredentials,
    ) -> tuple[InterfaceState, ...]:
        self.calls.append(("discover", target.automation_profile_id, None))
        return (state("ge-0/0/0"),)

    def collect_read_only(
        self,
        target: ProfileReadOnlyTarget,
        _credentials: DeviceCredentials,
        interface: str,
    ) -> InterfaceState:
        self.calls.append(("collect", target.automation_profile_id, None))
        return state(interface)


@pytest.mark.parametrize(
    ("profile_id", "backend"),
    [
        (AutomationProfileID.CAT8000V_IOSXE, CiscoSSHBackend.PARAMIKO),
        (AutomationProfileID.IOSV_159_3_M12, CiscoSSHBackend.PARAMIKO),
        (AutomationProfileID.IOSVL2_2020, CiscoSSHBackend.PARAMIKO),
    ],
)
def test_all_three_cisco_profiles_dispatch_exact_backend(
    profile_id: AutomationProfileID, backend: CiscoSSHBackend
) -> None:
    cisco = FakeCiscoCollector()
    junos = FakeJunosCollector()
    adapter = ProfileReadOnlyAdapter(cisco=cisco, junos=junos)
    observed = adapter.collect(target(profile_id), CREDENTIALS, "Gi0/1")
    assert observed.interface == "Gi0/1"
    assert cisco.calls == [("collect", profile_id, backend.value)]
    assert junos.calls == []


def test_junos_profile_dispatches_only_to_pyez_collection() -> None:
    cisco = FakeCiscoCollector()
    junos = FakeJunosCollector()
    adapter = ProfileReadOnlyAdapter(cisco=cisco, junos=junos)
    observed = adapter.discover(target(AutomationProfileID.VJUNOS_ROUTER), CREDENTIALS)
    assert observed[0].interface == "ge-0/0/0"
    assert cisco.calls == []
    assert junos.calls == [("discover", AutomationProfileID.VJUNOS_ROUTER, None)]


def test_unknown_or_mismatched_profile_fails_closed_before_collection() -> None:
    cisco = FakeCiscoCollector()
    junos = FakeJunosCollector()
    adapter = ProfileReadOnlyAdapter(cisco=cisco, junos=junos)
    unknown = SimpleNamespace(
        automation_profile_id="unknown",
        network_os=NetworkOS.IOS,
    )
    with pytest.raises(ProviderError, match="profile is unsupported"):
        adapter.discover(unknown, CREDENTIALS)  # type: ignore[arg-type]
    mismatched = SimpleNamespace(
        automation_profile_id=AutomationProfileID.CAT8000V_IOSXE,
        network_os=NetworkOS.IOS,
    )
    with pytest.raises(ProviderError, match="profile and NOS mismatch"):
        adapter.discover(mismatched, CREDENTIALS)  # type: ignore[arg-type]
    assert cisco.calls == []
    assert junos.calls == []


def test_read_only_target_rejects_profile_nos_and_port_mismatch() -> None:
    payload = target(AutomationProfileID.CAT8000V_IOSXE).model_dump(mode="json")
    payload["network_os"] = "ios"
    with pytest.raises(ValidationError, match="profile and NOS mismatch"):
        ProfileReadOnlyTarget.model_validate(payload)
    payload = target(AutomationProfileID.VJUNOS_ROUTER).model_dump(mode="json")
    payload["port"] = 22
    with pytest.raises(ValidationError, match="port is not admitted"):
        ProfileReadOnlyTarget.model_validate(payload)


def test_profile_adapter_exposes_no_write_transaction_or_recovery_surface() -> None:
    public_names = {
        name for name in dir(ProfileReadOnlyAdapter) if not name.startswith("_")
    }
    assert public_names == {"collect", "discover"}
    for prohibited in (
        "execute",
        "deploy",
        "transaction",
        "confirm",
        "recover",
        "execute_snmp",
        "snmp_preflight",
    ):
        assert not hasattr(ProfileReadOnlyAdapter, prohibited)


def test_transport_catalog_is_closed_strict_and_profile_local() -> None:
    assert set(PROFILE_READ_ONLY_TRANSPORTS) == set(AutomationProfileID)
    assert set(CiscoSSHBackend) == {CiscoSSHBackend.PARAMIKO}
    assert all(
        item.strict_host_key_verification and not item.host_key_auto_add
        for item in PROFILE_READ_ONLY_TRANSPORTS.values()
    )
    for cisco_profile in (
        AutomationProfileID.CAT8000V_IOSXE,
        AutomationProfileID.IOSV_159_3_M12,
        AutomationProfileID.IOSVL2_2020,
    ):
        transport = PROFILE_READ_ONLY_TRANSPORTS[cisco_profile]
        assert transport.adapter_family is AdapterFamily.CISCO_IOS
        assert transport.cisco_ssh_backend is CiscoSSHBackend.PARAMIKO
    junos = PROFILE_READ_ONLY_TRANSPORTS[AutomationProfileID.VJUNOS_ROUTER]
    assert junos.adapter_family is AdapterFamily.JUNOS_PYEZ
    assert junos.cisco_ssh_backend is None


def test_profiled_cisco_runner_uses_run_scoped_strict_backend_policy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    known_hosts = tmp_path / "trust" / "known_hosts"
    known_hosts.parent.mkdir()
    known_hosts.write_text("trusted key material\n", encoding="utf-8")
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        "network_change_delivery.ansible_adapter.verify_existing_host_trust",
        lambda _target, _path: "trusted",
    )

    def fake_run(**kwargs: object) -> SimpleNamespace:
        captured.update(kwargs)
        return SimpleNamespace(status="successful", rc=0)

    monkeypatch.setattr(
        "network_change_delivery.ansible_adapter.ansible_runner.run", fake_run
    )
    adapter = AnsibleRunnerCiscoAdapter(tmp_path, known_hosts=known_hosts)
    adapter._run(
        target(AutomationProfileID.CAT8000V_IOSXE),
        CREDENTIALS,
        "collect_interface_state.yml",
        ssh_type="paramiko",
        profile_bound=True,
    )
    inventory = captured["inventory"]  # type: ignore[assignment]
    host = inventory["all"]["hosts"]["ncdp_target"]  # type: ignore[index]
    envvars = captured["envvars"]  # type: ignore[assignment]
    assert host["ansible_network_cli_ssh_type"] == "paramiko"  # type: ignore[index]
    assert envvars["ANSIBLE_HOST_KEY_CHECKING"] == "True"  # type: ignore[index]
    assert envvars["ANSIBLE_HOST_KEY_AUTO_ADD"] == "False"  # type: ignore[index]
    assert "ANSIBLE_LIBSSH_HOST_KEY_AUTO_ADD" not in envvars  # type: ignore[operator]


def test_b2_has_no_libssh_or_automatic_backend_selection() -> None:
    source = (
        ROOT / "src/network_change_delivery/profile_read_only_adapter.py"
    ).read_text(encoding="utf-8")
    lowered = source.casefold()
    assert "libssh" not in lowered
    assert '"auto"' not in lowered


def test_current_v1_cisco_inventory_still_forces_paramiko_without_b2_policy() -> None:
    legacy = InventoryDevice(
        name="core-02",
        host="192.0.2.14",
        platform="cisco_iosxe",
        expected_hostname="core-02",
    )
    inventory = AnsibleRunnerCiscoAdapter._inventory(legacy)
    target_vars = inventory["all"]["hosts"]["ncdp_target"]
    assert target_vars["ansible_network_cli_ssh_type"] == "paramiko"
    assert "automation_profile_id" not in target_vars


def test_no_global_ssh_algorithm_relaxation_is_present() -> None:
    ansible_config = (ROOT / "ansible.cfg").read_text(encoding="utf-8")
    lowered = ansible_config.casefold()
    assert "diffie-hellman-group14-sha1" not in lowered
    assert "ssh-rsa" not in lowered
    assert "strict_hostkeychecking=no" not in lowered.replace(" ", "")
    assert "host_key_checking = true" in lowered
    assert "host_key_auto_add = false" in lowered
