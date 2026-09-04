"""Static and fake-only contracts for profiled exact-four disposable staging."""

from __future__ import annotations

import re
from pathlib import Path
from typing import cast

import pytest

from network_change_delivery.architecture_contracts import (
    AutomationProfileID,
    CmlRealizationProfileID,
)
from network_change_delivery.profiled_staging import (
    PROFILED_STAGING_DEVICE_NAMES,
    PROFILED_STAGING_LINK_COUNT,
    PROFILED_STAGING_NODE_COUNT,
    PROFILED_STAGING_RESOURCE_COUNT,
    PROFILED_STAGING_TERRAFORM_ADDRESSES,
    ProfiledStagingError,
    ProfiledStagingEvidence,
    ProfiledStagingLifecycle,
    ProfiledStagingOutcome,
    profiled_staging_topology,
    terraform_profiled_device_variables,
    validate_destroy_only_plan,
    validate_management_only_bootstrap,
    validate_profiled_staging_physical_topology,
)
from network_change_delivery.secrets import DeviceCredentials

ROOT = Path(__file__).parents[1]
TERRAFORM = ROOT / "infrastructure/cml/profiled-staging"


def test_exact_four_profiled_population_and_topology_contract() -> None:
    assert PROFILED_STAGING_DEVICE_NAMES == (
        "core-02",
        "edge-junos-01",
        "transit-ios-01",
        "access-sw-01",
    )
    assert PROFILED_STAGING_NODE_COUNT == 6
    assert PROFILED_STAGING_LINK_COUNT == 9
    assert PROFILED_STAGING_RESOURCE_COUNT == 17
    assert profiled_staging_topology() == {
        "core_edge": ("core-02:GigabitEthernet4", "edge-junos-01:ge-0/0/0"),
        "core_transit": (
            "core-02:GigabitEthernet2",
            "transit-ios-01:GigabitEthernet0/1",
        ),
        "edge_transit": (
            "edge-junos-01:ge-0/0/1",
            "transit-ios-01:GigabitEthernet0/2",
        ),
        "core_access": (
            "core-02:GigabitEthernet3",
            "access-sw-01:GigabitEthernet0/1",
        ),
    }


def test_terraform_graph_is_profiled_management_only_and_exact() -> None:
    source = "\n".join(
        item.read_text(encoding="utf-8") for item in TERRAFORM.glob("*.tf")
    )
    templates = "\n".join(
        item.read_text(encoding="utf-8")
        for item in (TERRAFORM / "bootstrap").glob("*.tftpl")
    )
    assert source.count('resource "cml2_lab"') == 1
    assert source.count('resource "cml2_node"') == 3
    assert source.count('resource "cml2_link"') == 9
    assert source.count('resource "cml2_lifecycle"') == 1
    for value in (
        "cat8000v-17-18-02",
        "vjunos-router-23-2r1-15",
        "iosv-159-3-m12",
        "iosvl2-2020",
    ):
        assert value not in source
    assert "10.6.12." not in templates
    for forbidden in (
        "router ospf",
        "vlan ",
        "switchport trunk",
        "access-list",
        "snmp-server",
        "description ",
    ):
        assert forbidden not in templates.lower()
    assert "netconf { ssh; }" in templates
    assert "no switchport" in templates
    assert "secret 9" in templates
    assert "encrypted-password" in templates


@pytest.mark.parametrize(
    "profile, realization",
    [
        (
            AutomationProfileID.CAT8000V_IOSXE,
            CmlRealizationProfileID.CAT8000V_17_18_02,
        ),
        (
            AutomationProfileID.VJUNOS_ROUTER,
            CmlRealizationProfileID.VJUNOS_ROUTER_23_2R1_15,
        ),
        (AutomationProfileID.IOSV_159_3_M12, CmlRealizationProfileID.IOSV_159_3_M12),
        (AutomationProfileID.IOSVL2_2020, CmlRealizationProfileID.IOSVL2_2020),
    ],
)
def test_profile_mapping_is_closed(profile, realization) -> None:
    from network_change_delivery.architecture_contracts import (
        CML_REALIZATION_PROFILE_CATALOG,
    )

    assert CML_REALIZATION_PROFILE_CATALOG[realization].profile_id is realization
    assert profile.value.split("_")[0] in {"cat8000v", "vjunos", "iosv", "iosvl2"}


def test_management_bootstrap_rejects_legacy_or_b4_content() -> None:
    validate_management_only_bootstrap("hostname core-02\nip ssh version 2\n")
    for invalid in (
        "10.6.12.1/30",
        "router ospf 1",
        "snmp-server community",
        "description x",
    ):
        with pytest.raises(ProfiledStagingError):
            validate_management_only_bootstrap(invalid)


def test_profiled_staging_evidence_is_schema_v2_and_secret_free() -> None:
    evidence = ProfiledStagingEvidence(
        staging_run_id="run-001",
        orchestrator="local",
        lab_title="NCDP Staging run-001",
        primary_failure="bounded failure",
    )
    rendered = evidence.model_dump_json()
    assert '"schema_version":"2"' in rendered
    for secret in ("username", "password", "token", "RoleID", "SecretID"):
        assert secret not in rendered


def test_sensitive_bootstrap_inputs_require_profile_appropriate_verifiers() -> None:
    from test_profiled_realization import inventory_devices

    devices = inventory_devices()
    credentials = {
        str(device.logical_name): DeviceCredentials(
            username="netdevops", password="secret"
        )
        for device in devices
    }
    verifiers = {
        "core-02": "$9$ncdpCoreSalt1$abcdefghijklmnop",
        "edge-junos-01": "$6$ncdpJunosSalt$abcdefghijklmnop",
        "transit-ios-01": "$9$ncdpTransitSalt$abcdefghijklmnop",
        "access-sw-01": "$9$ncdpAccessSalt1$abcdefghijklmnop",
    }
    values = terraform_profiled_device_variables(devices, credentials, verifiers)
    assert set(values) == {"core_02", "edge_junos_01", "transit_ios_01", "access_sw_01"}
    assert all("password" not in set(item) for item in values.values())
    assert values["edge_junos_01"]["management_port"] == 830
    verifiers["edge-junos-01"] = "plaintext"
    with pytest.raises(ProfiledStagingError, match="bootstrap verifier"):
        terraform_profiled_device_variables(devices, credentials, verifiers)


class TopologyInventory:
    def __init__(self) -> None:
        self.interfaces: dict[tuple[str, str], object] = {}
        self.peers: dict[object, object] = {}
        index = 1
        for left, right in profiled_staging_topology().values():
            for endpoint in (left, right):
                device, name = endpoint.split(":", maxsplit=1)
                self.interfaces[(device, name)] = (device, name, index)
                index += 1
            left_key = tuple(left.split(":", maxsplit=1))
            right_key = tuple(right.split(":", maxsplit=1))
            self.peers[self.interfaces[left_key]] = self.interfaces[right_key]
            self.peers[self.interfaces[right_key]] = self.interfaces[left_key]

    def resolve_interface(self, device, interface_name):
        return self.interfaces[(str(device.logical_name), interface_name)]

    def resolve_cabled_peer(self, interface):
        return self.peers[interface]


def test_profiled_staging_physical_topology_is_exact_netbox_cable_authority() -> None:
    from test_profiled_realization import inventory_devices

    inventory = TopologyInventory()
    validate_profiled_staging_physical_topology(
        cast(object, inventory), inventory_devices()
    )
    left = next(iter(inventory.peers))
    inventory.peers[left] = left
    with pytest.raises(ProfiledStagingError, match="physical topology"):
        validate_profiled_staging_physical_topology(
            cast(object, inventory), inventory_devices()
        )


class Operations:
    def __init__(self, *, fail: str | None = None) -> None:
        self.fail = fail
        self.calls: list[str] = []
        self.exists = False

    @property
    def managed_resources_exist(self) -> bool:
        return self.exists

    def admit(self) -> None:
        self.calls.append("admit")

    def create(self):
        self.calls.append("create")
        self.exists = True
        from test_profiled_realization import staging_context

        return staging_context()

    def validate(self, _context):
        self.calls.append("validate")
        if self.fail == "validate":
            raise ProfiledStagingError("validation failed")
        return ()

    def destroy(self, _context):
        self.calls.append("destroy")
        if self.fail == "destroy":
            raise ProfiledStagingError("destroy failed")

    def verify_absent(self, _context):
        self.calls.append("absence")

    def retire_state(self) -> None:
        self.calls.append("retire")
        self.exists = False


def test_lifecycle_cleans_up_after_primary_validation_failure() -> None:
    operations = Operations(fail="validate")
    evidence = ProfiledStagingLifecycle("run-1", "local", operations).run()
    assert evidence.primary_failure == "validation failed"
    assert evidence.destroy_outcome == "succeeded"
    assert evidence.absence_verification == "succeeded"
    assert evidence.state_retirement == "succeeded"
    assert evidence.final_outcome is ProfiledStagingOutcome.FAILED
    assert operations.calls == [
        "admit",
        "create",
        "validate",
        "destroy",
        "absence",
        "retire",
    ]


def test_lifecycle_retains_state_after_cleanup_failure() -> None:
    operations = Operations(fail="destroy")
    evidence = ProfiledStagingLifecycle("run-1", "local", operations).run()
    assert evidence.destroy_outcome == "not_attempted"
    assert evidence.cleanup_failure == "destroy failed"
    assert evidence.final_outcome is ProfiledStagingOutcome.CLEANUP_FAILED
    assert operations.exists is True


def test_guarded_recovery_accepts_only_exact_deletes() -> None:
    state = set(PROFILED_STAGING_TERRAFORM_ADDRESSES)
    validate_destroy_only_plan(state, dict.fromkeys(state, "delete"))
    with pytest.raises(ProfiledStagingError):
        validate_destroy_only_plan(state, dict.fromkeys(state, "update"))
    with pytest.raises(ProfiledStagingError):
        validate_destroy_only_plan(
            set(state) - {next(iter(state))}, dict.fromkeys(state, "delete")
        )


def test_new_runtime_is_profiled_read_only_and_has_no_write_dependencies() -> None:
    source = (ROOT / "src/network_change_delivery/profiled_staging.py").read_text(
        encoding="utf-8"
    )
    assert "NetBoxProfileInventoryProvider" in source
    assert "ProfileReadOnlyAdapter" in source
    for forbidden in (
        "NetBoxInventoryProvider",
        "InventoryDevice",
        "MultiVendorAdapter",
        "plan_change",
        "ProfiledWriteAdapter",
        "execute_profiled_plan",
    ):
        assert re.search(rf"\b{forbidden}\b", source) is None


def test_operator_entry_point_requires_explicit_execution_and_remains_profiled() -> (
    None
):
    source = (ROOT / "scripts/run_profiled_cml_staging.py").read_text(encoding="utf-8")
    assert 'add_argument("--execute", action="store_true")' in source
    assert "ProfiledStagingLifecycle" in source
    assert "ProfileReadOnlyAdapter" in source
    assert "establish_profiled_staging_trust" in source
    for forbidden in (
        "NetBoxInventoryProvider",
        "InventoryDevice",
        "MultiVendorAdapter",
        "ProfiledWriteAdapter",
        "execute_profiled_plan",
    ):
        assert re.search(rf"\b{forbidden}\b", source) is None


def test_recovery_entry_point_is_exact_destroy_only() -> None:
    source = (ROOT / "scripts/recover_profiled_cml_staging.py").read_text(
        encoding="utf-8"
    )
    assert 'add_argument("--execute", action="store_true")' in source
    assert "validate_destroy_only_plan" in source
    assert "_verify_absence" in source
    assert '"-destroy"' in source
    assert '"create"' not in source
    assert '"STARTED"' not in source
