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
from network_change_delivery.models import InterfaceState
from network_change_delivery.profiled_realization import EvidenceReference
from network_change_delivery.profiled_staging import (
    PROFILED_STAGING_DEVICE_NAMES,
    PROFILED_STAGING_LINK_COUNT,
    PROFILED_STAGING_NODE_COUNT,
    PROFILED_STAGING_RESOURCE_COUNT,
    PROFILED_STAGING_TERRAFORM_ADDRESSES,
    ProfiledStagingAmbiguousError,
    ProfiledStagingError,
    ProfiledStagingEvidence,
    ProfiledStagingLifecycle,
    ProfiledStagingOutcome,
    ProfiledStagingReadinessEvidence,
    ProfiledStagingReadinessOutcome,
    load_recovery_inputs,
    profiled_staging_topology,
    terraform_profiled_device_variables,
    validate_destroy_only_plan,
    validate_management_only_bootstrap,
    validate_profiled_staging_physical_topology,
    validate_read_only_collection,
    validate_start_only_plan,
    write_recovery_inputs,
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
    assert "netconf" in templates
    assert "no switchport" in templates
    assert "secret 9" in templates
    assert "encrypted-password" in templates


@pytest.mark.parametrize(
    "template,management_marker",
    [
        ("cat8000v_minimal.tftpl", "interface GigabitEthernet1"),
        ("iosv_minimal.tftpl", "interface GigabitEthernet0/0"),
        ("iosvl2_routed_management.tftpl", "interface GigabitEthernet0/0"),
    ],
)
def test_cisco_bootstrap_has_complete_management_only_ssh_server(
    template: str, management_marker: str
) -> None:
    rendered = (TERRAFORM / "bootstrap" / template).read_text(encoding="utf-8")
    for required in (
        "ip domain name ncdp.local",
        "crypto key generate rsa modulus 2048",
        "line vty 0 4",
        " login local",
        " transport input ssh",
        "ip ssh version 2",
        management_marker,
        " no shutdown",
        "secret 9",
    ):
        assert required in rendered
    validate_management_only_bootstrap(rendered)
    for forbidden in (
        "10.6.12.",
        "router ospf",
        "vlan ",
        "switchport trunk",
        "access-list",
        "snmp-server",
        "description ",
        "netconf",
    ):
        assert forbidden not in rendered.casefold()
    assert rendered.count("interface ") == 1
    assert '${split("/", management_cidr)[0]}' in rendered
    if template == "iosvl2_routed_management.tftpl":
        assert " no switchport" in rendered


def test_vjunos_bootstrap_restores_accepted_first_boot_guard_only() -> None:
    rendered = (TERRAFORM / "bootstrap" / "vjunos_router_minimal.tftpl").read_text(
        encoding="utf-8"
    )
    assert "root-authentication" in rendered
    assert (
        'ssh-ed25519 "ssh-ed25519 '
        "AAAAC3NzaC1lZDI1NTE5AAAAIPwW8OCx1ZqSb9kBOTcmWF5csn28A+Z+5wkAaslzmXau "
        'ncdp-personal-lab-root-commit-guard";'
    ) in rendered
    for required in (
        "root-login deny",
        "encrypted-password",
        "services",
        "ssh",
        "netconf",
        "fxp0",
        "${management_cidr}",
    ):
        assert required in rendered
    validate_management_only_bootstrap(rendered)
    assert "ge-0/0/" not in rendered


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
    readiness = ProfiledStagingReadinessEvidence(
        device_identity="netbox:dcim.device:1",
        logical_name="core-02",
        automation_profile_id=AutomationProfileID.CAT8000V_IOSXE,
        cml_realization_profile_id=CmlRealizationProfileID.CAT8000V_17_18_02,
        cml_node_id="node-core",
        management_address="192.168.4.30",
        readiness_service="ssh",
        readiness_port=22,
        outcome=ProfiledStagingReadinessOutcome.TIMED_OUT,
        elapsed_seconds=180,
        cml_node_state="BOOTED",
    )
    evidence = ProfiledStagingEvidence(
        staging_run_id="run-001",
        orchestrator="local",
        lab_title="NCDP Staging run-001",
        readiness=(readiness,),
        primary_failure="bounded failure",
    )
    rendered = evidence.model_dump_json()
    assert '"schema_version":"2"' in rendered
    assert '"readiness_deadline_seconds":180' in rendered
    assert '"outcome":"TIMED_OUT"' in rendered
    assert '"elapsed_seconds":180.0' in rendered
    assert (
        ProfiledStagingEvidence(
            staging_run_id="run-extended",
            orchestrator="local",
            lab_title="NCDP Staging run-extended",
            readiness_deadline_seconds=300,
        ).readiness_deadline_seconds
        == 300
    )
    with pytest.raises(ValueError):
        ProfiledStagingEvidence(
            staging_run_id="run-invalid",
            orchestrator="local",
            lab_title="NCDP Staging run-invalid",
            readiness_deadline_seconds=301,
        )
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
        self.readiness_deadline_seconds = 180
        self.readiness_evidence: tuple[ProfiledStagingReadinessEvidence, ...] = ()

    @property
    def managed_resources_exist(self) -> bool:
        return self.exists

    def admit(self) -> None:
        self.calls.append("admit")

    def create(self):
        self.calls.append("create")
        self.exists = True
        if self.fail == "create_after_owned":
            raise ProfiledStagingError("create failed after ownership")
        from test_profiled_realization import (
            evidence,
            inventory_devices,
            staging_context,
        )

        self.readiness_evidence = tuple(
            ProfiledStagingReadinessEvidence(
                device_identity=device.device_identity,
                logical_name=device.logical_name,
                automation_profile_id=device.automation_profile_id,
                cml_realization_profile_id=device.cml_realization_profile_id,
                cml_node_id=f"node-{device.logical_name}",
                management_address=str(
                    device.management_endpoints.staging.binding.l3_endpoint.address.ip
                ),
                readiness_service=(
                    "netconf" if str(device.logical_name) == "edge-junos-01" else "ssh"
                ),
                readiness_port=(
                    device.management_endpoints.staging.binding.l3_endpoint.port
                ),
                outcome=(
                    ProfiledStagingReadinessOutcome.TIMED_OUT
                    if self.fail == "readiness" and index > 0
                    else ProfiledStagingReadinessOutcome.READY
                ),
                elapsed_seconds=1.25,
                readiness_evidence=(
                    None
                    if self.fail == "readiness" and index > 0
                    else evidence(f"ready-{device.logical_name}", "7")
                ),
                cml_node_state=(
                    "BOOTED" if self.fail == "readiness" and index > 0 else None
                ),
            )
            for index, device in enumerate(inventory_devices())
        )
        if self.fail == "readiness":
            raise ProfiledStagingError("profiled staging readiness timed out")

        return staging_context()

    def validate(self, _context):
        self.calls.append("validate")
        if self.fail == "validate":
            raise ProfiledStagingError("validation failed")
        return ()

    def destroy_owned(self, *, require_complete):
        self.calls.append("destroy")
        self.calls.append(f"complete={require_complete}")
        if self.fail == "destroy":
            raise ProfiledStagingError("destroy failed")

    def verify_absent(self):
        self.calls.append("absence")
        if self.fail == "absence_malformed":
            raise ProfiledStagingAmbiguousError(
                "profiled staging Terraform ownership cannot be proven"
            )

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
        "complete=True",
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


def test_lifecycle_cleans_partial_owned_state_when_create_does_not_return_context() -> (
    None
):
    operations = Operations(fail="create_after_owned")
    evidence = ProfiledStagingLifecycle("run-1", "local", operations).run()
    assert evidence.primary_failure == "create failed after ownership"
    assert evidence.destroy_outcome == "succeeded"
    assert evidence.absence_verification == "succeeded"
    assert evidence.state_retirement == "succeeded"
    assert evidence.final_outcome is ProfiledStagingOutcome.FAILED
    assert operations.calls == [
        "admit",
        "create",
        "destroy",
        "complete=False",
        "absence",
        "retire",
    ]


def test_lifecycle_preserves_exact_partial_readiness_after_timeout() -> None:
    operations = Operations(fail="readiness")
    evidence = ProfiledStagingLifecycle("run-1", "local", operations).run()
    assert evidence.final_outcome is ProfiledStagingOutcome.FAILED
    assert evidence.primary_failure == "profiled staging readiness timed out"
    assert evidence.readiness_deadline_seconds == 180
    assert tuple(item.logical_name for item in evidence.readiness) == (
        "core-02",
        "edge-junos-01",
        "transit-ios-01",
        "access-sw-01",
    )
    assert evidence.readiness[0].outcome is ProfiledStagingReadinessOutcome.READY
    assert evidence.readiness[0].readiness_evidence is not None
    assert all(
        item.outcome is ProfiledStagingReadinessOutcome.TIMED_OUT
        and item.readiness_evidence is None
        and item.cml_node_state == "BOOTED"
        for item in evidence.readiness[1:]
    )
    assert evidence.destroy_outcome == "succeeded"
    assert evidence.absence_verification == "succeeded"
    assert evidence.state_retirement == "succeeded"


def test_lifecycle_preserves_extended_deadline_and_cleanup_after_timeout() -> None:
    operations = Operations(fail="readiness")
    operations.readiness_deadline_seconds = 300
    evidence = ProfiledStagingLifecycle("run-1", "local", operations).run()
    assert evidence.final_outcome is ProfiledStagingOutcome.FAILED
    assert evidence.readiness_deadline_seconds == 300
    assert evidence.destroy_outcome == "succeeded"
    assert evidence.absence_verification == "succeeded"
    assert evidence.state_retirement == "succeeded"


def test_lifecycle_malformed_post_destroy_state_is_ambiguous() -> None:
    operations = Operations(fail="absence_malformed")
    evidence = ProfiledStagingLifecycle("run-1", "local", operations).run()
    assert evidence.destroy_outcome == "succeeded"
    assert evidence.absence_verification == "not_attempted"
    assert evidence.state_retirement == "not_attempted"
    assert evidence.cleanup_failure == (
        "profiled staging Terraform ownership cannot be proven"
    )
    assert evidence.final_outcome is ProfiledStagingOutcome.AMBIGUOUS


def test_lifecycle_retains_ambiguous_terraform_outcome() -> None:
    operations = Operations()

    def ambiguous_create():
        operations.calls.append("create")
        raise ProfiledStagingAmbiguousError("create ownership cannot be proven")

    operations.create = ambiguous_create
    evidence = ProfiledStagingLifecycle("run-1", "local", operations).run()
    assert evidence.final_outcome is ProfiledStagingOutcome.AMBIGUOUS
    assert evidence.primary_failure == "create ownership cannot be proven"
    assert operations.calls == ["admit", "create"]


def test_successful_lifecycle_evidence_binds_context_topology_and_trust() -> None:
    operations = Operations()
    evidence = ProfiledStagingLifecycle("run-1", "local", operations).run()
    assert evidence.final_outcome is ProfiledStagingOutcome.SUCCEEDED
    assert evidence.lab_id is not None
    assert evidence.topology_digest is not None
    assert evidence.context_digest is not None
    assert evidence.trust_generation is not None
    assert evidence.create_outcome == "succeeded"
    assert evidence.start_outcome == "succeeded"
    assert evidence.read_only_outcome == "succeeded"


def test_guarded_recovery_accepts_only_exact_deletes() -> None:
    state = set(PROFILED_STAGING_TERRAFORM_ADDRESSES)
    validate_destroy_only_plan(
        state, dict.fromkeys(state, "delete"), require_complete=True
    )
    partial = set(tuple(state)[:3])
    validate_destroy_only_plan(partial, dict.fromkeys(partial, "delete"))
    with pytest.raises(ProfiledStagingError):
        validate_destroy_only_plan(state, dict.fromkeys(state, "update"))
    with pytest.raises(ProfiledStagingError):
        validate_destroy_only_plan(
            partial | {"unknown.resource"}, dict.fromkeys(partial, "delete")
        )
    with pytest.raises(ProfiledStagingError):
        validate_destroy_only_plan(set(), {})
    with pytest.raises(ProfiledStagingError):
        validate_destroy_only_plan(
            partial, dict.fromkeys(partial, "delete"), require_complete=True
        )


def test_start_plan_is_lifecycle_update_only() -> None:
    validate_start_only_plan({"cml2_lifecycle.profiled_staging": "update"})
    for actions in (
        {"cml2_lifecycle.profiled_staging": "create"},
        {
            "cml2_lifecycle.profiled_staging": "update",
            "cml2_node.system_bridge": "update",
        },
        {},
    ):
        with pytest.raises(ProfiledStagingError, match="START plan"):
            validate_start_only_plan(actions)


def test_recovery_inputs_are_private_exact_and_contain_only_verifiers(
    tmp_path: Path,
) -> None:
    from test_profiled_realization import inventory_devices

    path = tmp_path / "recovery-inputs.tfvars.json"
    inventory = inventory_devices()
    credentials = {
        str(device.logical_name): DeviceCredentials(
            username="operator", password="unused"
        )
        for device in inventory
    }
    verifiers = {
        "core-02": "$9$ncdpCoreSalt1$abcdefghijklmnop",
        "edge-junos-01": "$6$ncdpJunosSalt$abcdefghijklmnop",
        "transit-ios-01": "$9$ncdpTransitSalt$abcdefghijklmnop",
        "access-sw-01": "$9$ncdpAccessSalt1$abcdefghijklmnop",
    }
    devices = terraform_profiled_device_variables(inventory, credentials, verifiers)
    for name, address in {
        "core_02": "192.168.4.30/24",
        "edge_junos_01": "192.168.4.40/24",
        "transit_ios_01": "192.168.4.31/24",
        "access_sw_01": "192.168.4.32/24",
    }.items():
        devices[name]["management_cidr"] = address
    payload = {
        "staging_run_id": "run-001",
        "lifecycle_state": "DEFINED_ON_CORE",
        "devices": devices,
    }
    write_recovery_inputs(path, payload)
    assert path.stat().st_mode & 0o777 == 0o600
    assert load_recovery_inputs(path, "run-001") == payload
    assert 'password"' not in path.read_text(encoding="utf-8")
    with pytest.raises(ProfiledStagingError):
        write_recovery_inputs(path, payload)


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


class ReadOnlyAdapter:
    def __init__(self, devices, *, wrong: str | None = None) -> None:
        self.devices = {str(item.logical_name): item for item in devices}
        self.wrong = wrong

    def discover(self, target, _credential):
        device = self.devices[str(target.logical_name)]
        names = {
            "core-02": ("GigabitEthernet1",),
            "edge-junos-01": ("fxp0",),
            "transit-ios-01": tuple(f"Gi0/{index}" for index in range(4)),
            "access-sw-01": tuple(f"GigabitEthernet0/{index}" for index in range(4)),
        }[str(device.logical_name)]
        management = names[0]
        address = str(device.management_endpoints.staging.binding.l3_endpoint.address)
        return tuple(
            InterfaceState(
                observed_hostname=(
                    "wrong" if self.wrong == "hostname" else device.expected_hostname
                ),
                interface=name,
                exists=True,
                protected=False,
                ipv4_addresses=(
                    () if self.wrong == "address" or name != management else (address,)
                ),
            )
            for name in (names[:-1] if self.wrong == "physical" else names)
        )


def _readiness(devices) -> dict[str, tuple[float, EvidenceReference]]:
    from test_profiled_realization import evidence

    return {
        str(device.logical_name): (
            1.25,
            evidence(f"readiness-{device.logical_name}", "7"),
        )
        for device in devices
    }


def test_read_only_validation_binds_management_address_and_real_readiness() -> None:
    from test_profiled_realization import inventory_devices, staging_context

    devices = inventory_devices()
    credentials = {
        str(device.logical_name): DeviceCredentials(
            username="operator", password="value"
        )
        for device in devices
    }
    result = validate_read_only_collection(
        staging_context(),
        devices,
        credentials,
        cast(object, ReadOnlyAdapter(devices)),
        _readiness(devices),
    )
    assert all(item.readiness_seconds == 1.25 for item in result)
    assert all(
        item.readiness_evidence.digest != staging_context().topology_evidence.digest
        for item in result
    )


@pytest.mark.parametrize("wrong", ["hostname", "address", "physical"])
def test_read_only_validation_rejects_wrong_observation(wrong: str) -> None:
    from test_profiled_realization import inventory_devices, staging_context

    devices = inventory_devices()
    credentials = {
        str(device.logical_name): DeviceCredentials(
            username="operator", password="value"
        )
        for device in devices
    }
    with pytest.raises(ProfiledStagingError, match="read-only validation"):
        validate_read_only_collection(
            staging_context(),
            devices,
            credentials,
            cast(object, ReadOnlyAdapter(devices, wrong=wrong)),
            _readiness(devices),
        )


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
