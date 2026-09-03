"""Profiled ordinary planning contracts without device-write authority."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from network_change_delivery.architecture_contracts import (
    AutomationProfileID,
    CmlRealizationProfileID,
    ManagementBinding,
    ManagementEndpoint,
    ManagementEndpointPurpose,
    ManagementEndpointSet,
    ManagementL3Endpoint,
    ManagementPhysicalAttachment,
    ManagementService,
    NetworkOS,
    OperationalRole,
    StableInterfaceIdentity,
)
from network_change_delivery.models import (
    CiscoConfigArtifact,
    InterfaceDescriptionIntent,
    InterfaceState,
    JunosConfigArtifact,
)
from network_change_delivery.profile_inventory import (
    NetBoxDeviceTypeFact,
    NetBoxPlatformFact,
    NetBoxRoleFact,
    ProfiledInventoryDevice,
)
from network_change_delivery.profiled_planning import (
    PROFILED_OPERATION_ADMISSIONS,
    ProfiledDeploymentPlan,
    ProfiledOperation,
    ProfiledPlanningError,
    admit_profiled_operation,
    build_profiled_plan,
    plan_profiled_change,
)
from network_change_delivery.secrets import (
    CredentialReference,
    DeviceCredentials,
)


PROFILE_FACTS = {
    AutomationProfileID.CAT8000V_IOSXE: {
        "device_id": 1,
        "name": "core-02",
        "platform_slug": "cisco-ios-xe",
        "platform_name": "Cisco IOS XE",
        "device_type_slug": "c8000v",
        "device_type_model": "C8000V",
        "role": OperationalRole.CORE,
        "network_os": NetworkOS.IOSXE,
        "realization": CmlRealizationProfileID.CAT8000V_17_18_02,
        "service": ManagementService.SSH,
        "port": 22,
        "live": "192.168.4.14/24",
        "staging": "192.168.4.30/24",
        "management_interface": (1, "GigabitEthernet1"),
        "change_interface": (2, "GigabitEthernet2"),
    },
    AutomationProfileID.VJUNOS_ROUTER: {
        "device_id": 2,
        "name": "edge-junos-01",
        "platform_slug": "juniper-junos",
        "platform_name": "Juniper Junos",
        "device_type_slug": "vjunos-router-lab",
        "device_type_model": "vJunos Router (Synthetic Lab)",
        "role": OperationalRole.EDGE,
        "network_os": NetworkOS.JUNOS,
        "realization": CmlRealizationProfileID.VJUNOS_ROUTER_23_2R1_15,
        "service": ManagementService.NETCONF,
        "port": 830,
        "live": "192.168.4.20/24",
        "staging": "192.168.4.40/24",
        "management_interface": (3, "fxp0"),
        "change_interface": (4, "ge-0/0/0"),
    },
    AutomationProfileID.IOSV_159_3_M12: {
        "device_id": 8,
        "name": "transit-ios-01",
        "platform_slug": "cisco-ios",
        "platform_name": "Cisco IOS",
        "device_type_slug": "iosv-159-3-m12",
        "device_type_model": "IOSv 15.9(3)M12",
        "role": OperationalRole.TRANSIT,
        "network_os": NetworkOS.IOS,
        "realization": CmlRealizationProfileID.IOSV_159_3_M12,
        "service": ManagementService.SSH,
        "port": 22,
        "live": "192.168.4.16/24",
        "staging": "192.168.4.31/24",
        "management_interface": (13, "GigabitEthernet0/0"),
        "change_interface": (14, "GigabitEthernet0/1"),
    },
    AutomationProfileID.IOSVL2_2020: {
        "device_id": 9,
        "name": "access-sw-01",
        "platform_slug": "cisco-ios",
        "platform_name": "Cisco IOS",
        "device_type_slug": "iosvl2-2020",
        "device_type_model": "IOSvL2 2020",
        "role": OperationalRole.ACCESS,
        "network_os": NetworkOS.IOS,
        "realization": CmlRealizationProfileID.IOSVL2_2020,
        "service": ManagementService.SSH,
        "port": 22,
        "live": "192.168.4.17/24",
        "staging": "192.168.4.32/24",
        "management_interface": (17, "GigabitEthernet0/0"),
        "change_interface": (18, "GigabitEthernet0/1"),
    },
}


def profiled_device(
    profile_id: AutomationProfileID,
) -> tuple[ProfiledInventoryDevice, StableInterfaceIdentity]:
    facts = PROFILE_FACTS[profile_id]
    identity = f"netbox:dcim.device:{facts['device_id']}"
    management_id, management_name = facts["management_interface"]
    change_id, change_name = facts["change_interface"]
    management = StableInterfaceIdentity(
        device=identity,
        interface=f"netbox:dcim.interface:{management_id}",
        name=management_name,
    )
    change = StableInterfaceIdentity(
        device=identity,
        interface=f"netbox:dcim.interface:{change_id}",
        name=change_name,
    )

    def binding(ip_id: int, address: str) -> ManagementBinding:
        return ManagementBinding(
            physical_attachment=ManagementPhysicalAttachment(interface=management),
            l3_endpoint=ManagementL3Endpoint(
                interface=management,
                ip_address_identity=f"netbox:ipam.ipaddress:{ip_id}",
                address=address,
                service=facts["service"],
                port=facts["port"],
            ),
        )

    device = ProfiledInventoryDevice(
        device_identity=identity,
        logical_name=facts["name"],
        expected_hostname=facts["name"],
        platform=NetBoxPlatformFact(
            object_id=10,
            slug=facts["platform_slug"],
            name=facts["platform_name"],
        ),
        device_type=NetBoxDeviceTypeFact(
            object_id=20,
            slug=facts["device_type_slug"],
            model=facts["device_type_model"],
        ),
        role=NetBoxRoleFact(
            object_id=30,
            slug=facts["role"].value,
            name=facts["role"].value.title(),
        ),
        operational_role=facts["role"],
        network_os=facts["network_os"],
        automation_profile_id=profile_id,
        cml_realization_profile_id=facts["realization"],
        management_endpoints=ManagementEndpointSet(
            logical_device=identity,
            automation_profile_id=profile_id,
            live=ManagementEndpoint(
                purpose=ManagementEndpointPurpose.LIVE,
                binding=binding(100 + facts["device_id"], facts["live"]),
            ),
            staging=ManagementEndpoint(
                purpose=ManagementEndpointPurpose.STAGING,
                binding=binding(200 + facts["device_id"], facts["staging"]),
            ),
        ),
        protected_interfaces=(management,),
    )
    return device, change


def intent(device: ProfiledInventoryDevice, interface: StableInterfaceIdentity):
    return InterfaceDescriptionIntent(
        change_id="CHG-PROFILED-PLAN-001",
        kind="interface_description",
        target=device.logical_name,
        interface=interface.name,
        desired={"description": "profiled-plan"},
    )


def observed(
    device: ProfiledInventoryDevice,
    interface: StableInterfaceIdentity,
    *,
    description: str | None = "previous",
    protected: bool = False,
) -> InterfaceState:
    return InterfaceState(
        observed_hostname=device.expected_hostname,
        software_version="bounded-version",
        interface=interface.name,
        exists=True,
        description=description,
        protected=protected,
    )


class FakeInventory:
    def __init__(
        self,
        device: ProfiledInventoryDevice,
        interface: StableInterfaceIdentity,
    ) -> None:
        self.device = device
        self.interface = interface
        self.resolve_calls = 0
        self.interface_calls = 0

    def resolve(self, target: str) -> ProfiledInventoryDevice:
        self.resolve_calls += 1
        assert target == self.device.logical_name
        return self.device

    def resolve_interface(
        self,
        device: ProfiledInventoryDevice,
        interface_name: str,
    ) -> StableInterfaceIdentity:
        self.interface_calls += 1
        assert device.device_identity == self.device.device_identity
        assert interface_name == self.interface.name
        return self.interface


class WrongTargetInventory(FakeInventory):
    """Return a different valid profiled subject than the requested target."""

    def resolve(self, target: str) -> ProfiledInventoryDevice:
        del target
        self.resolve_calls += 1
        return self.device


class FakeSecrets:
    def __init__(self, *, source: str = "openbao") -> None:
        self.source = source
        self.reference_calls = 0
        self.load_calls = 0

    def reference(self, device: ProfiledInventoryDevice) -> CredentialReference:
        self.reference_calls += 1
        if self.source == "openbao":
            device_id = device.device_identity.rsplit(":", 1)[1]
            return CredentialReference(
                "openbao",
                f"openbao:kv-v2:ncdp/devices/{device_id}/ssh",
            )
        return CredentialReference(
            "environment",
            "environment:NCDP_DEVICE_USERNAME+NCDP_DEVICE_PASSWORD",
        )

    def load(self, device: ProfiledInventoryDevice) -> DeviceCredentials:
        del device
        self.load_calls += 1
        return DeviceCredentials(username="test-user", password="test-password")


class FakeCollector:
    def __init__(self, state: InterfaceState) -> None:
        self.state = state
        self.calls = 0

    def collect(
        self,
        target,
        credentials: DeviceCredentials,
        interface: str,
    ) -> InterfaceState:
        del target, credentials
        self.calls += 1
        assert interface == self.state.interface
        return self.state


def test_operation_admission_is_profile_specific_and_not_ios_family_fallback() -> None:
    expected = {
        (
            AutomationProfileID.CAT8000V_IOSXE,
            ProfiledOperation.INTERFACE_DESCRIPTION,
        ),
        (
            AutomationProfileID.VJUNOS_ROUTER,
            ProfiledOperation.INTERFACE_DESCRIPTION,
        ),
    }
    assert set(PROFILED_OPERATION_ADMISSIONS) == expected

    for profile_id in (
        AutomationProfileID.CAT8000V_IOSXE,
        AutomationProfileID.VJUNOS_ROUTER,
    ):
        device, _interface = profiled_device(profile_id)
        assert (
            admit_profiled_operation(
                device, ProfiledOperation.INTERFACE_DESCRIPTION
            ).automation_profile_id
            is profile_id
        )

    for profile_id in (
        AutomationProfileID.IOSV_159_3_M12,
        AutomationProfileID.IOSVL2_2020,
    ):
        device, _interface = profiled_device(profile_id)
        with pytest.raises(ProfiledPlanningError, match="does not admit"):
            admit_profiled_operation(device, ProfiledOperation.INTERFACE_DESCRIPTION)


@pytest.mark.parametrize(
    "profile_id",
    (
        AutomationProfileID.IOSV_159_3_M12,
        AutomationProfileID.IOSVL2_2020,
    ),
)
def test_unsupported_profile_fails_before_interface_secret_or_transport(
    profile_id: AutomationProfileID,
) -> None:
    device, interface = profiled_device(profile_id)
    inventory = FakeInventory(device, interface)
    secrets = FakeSecrets()
    collector = FakeCollector(observed(device, interface))

    with pytest.raises(ProfiledPlanningError, match="does not admit"):
        plan_profiled_change(
            intent(device, interface),
            inventory,
            secrets,
            collector,
        )

    assert inventory.resolve_calls == 1
    assert inventory.interface_calls == 0
    assert secrets.reference_calls == 0
    assert secrets.load_calls == 0
    assert collector.calls == 0


def test_different_valid_profiled_subject_cannot_retarget_intent() -> None:
    requested_device, requested_interface = profiled_device(
        AutomationProfileID.CAT8000V_IOSXE
    )
    returned_device, returned_interface = profiled_device(
        AutomationProfileID.VJUNOS_ROUTER
    )
    inventory = WrongTargetInventory(returned_device, returned_interface)
    secrets = FakeSecrets()
    collector = FakeCollector(observed(returned_device, returned_interface))

    with pytest.raises(ProfiledPlanningError, match="target identity"):
        plan_profiled_change(
            intent(requested_device, requested_interface),
            inventory,
            secrets,
            collector,
        )

    assert inventory.resolve_calls == 1
    assert inventory.interface_calls == 0
    assert secrets.reference_calls == 0
    assert secrets.load_calls == 0
    assert collector.calls == 0


def test_direct_plan_builder_rejects_intent_target_retargeting() -> None:
    requested_device, requested_interface = profiled_device(
        AutomationProfileID.CAT8000V_IOSXE
    )
    returned_device, returned_interface = profiled_device(
        AutomationProfileID.VJUNOS_ROUTER
    )
    credential = CredentialReference(
        "openbao",
        "openbao:kv-v2:ncdp/devices/2/ssh",
    )

    with pytest.raises(ProfiledPlanningError, match="target identity"):
        build_profiled_plan(
            intent(requested_device, requested_interface),
            returned_device,
            returned_interface,
            observed(returned_device, returned_interface),
            credential=credential,
        )


def test_profiled_cisco_plan_is_schema_v2_identity_bound_and_digest_bound() -> None:
    device, interface = profiled_device(AutomationProfileID.CAT8000V_IOSXE)
    inventory = FakeInventory(device, interface)
    secrets = FakeSecrets()
    collector = FakeCollector(observed(device, interface))

    result = plan_profiled_change(
        intent(device, interface),
        inventory,
        secrets,
        collector,
        created_at=datetime(2026, 9, 3, tzinfo=UTC),
    )

    assert result.plan is not None
    plan = result.plan
    assert plan.schema_version == "2"
    assert plan.plan_type == "profiled_deployment_plan"
    assert plan.device_identity == "netbox:dcim.device:1"
    assert plan.interface == interface
    assert plan.automation_profile_id is AutomationProfileID.CAT8000V_IOSXE
    assert plan.network_os is NetworkOS.IOSXE
    assert plan.host == "192.168.4.14"
    assert plan.port == 22
    assert plan.credential_reference == "openbao:kv-v2:ncdp/devices/1/ssh"
    assert plan.operation_admission.transaction_strategy == "cisco_targeted_inverse"
    assert isinstance(plan.execution_artifact, CiscoConfigArtifact)
    assert isinstance(plan.recovery_artifact, CiscoConfigArtifact)
    assert plan.execution_artifact.lines == ("description profiled-plan",)
    assert plan.recovery_artifact.lines == ("description previous",)
    assert plan.verify_digest()
    assert secrets.load_calls == 1
    assert collector.calls == 1


def test_profiled_junos_plan_preserves_netconf_and_confirmed_commit_contract() -> None:
    device, interface = profiled_device(AutomationProfileID.VJUNOS_ROUTER)
    result = plan_profiled_change(
        intent(device, interface),
        FakeInventory(device, interface),
        FakeSecrets(),
        FakeCollector(observed(device, interface)),
        created_at=datetime(2026, 9, 3, tzinfo=UTC),
    )

    assert result.plan is not None
    plan = result.plan
    assert plan.device_identity == "netbox:dcim.device:2"
    assert plan.automation_profile_id is AutomationProfileID.VJUNOS_ROUTER
    assert plan.host == "192.168.4.20"
    assert plan.port == 830
    assert plan.operation_admission.transaction_strategy == "junos_commit_confirmed"
    assert plan.operation_admission.confirmed_timeout_minutes == 5
    assert plan.operation_admission.confirmation_operation == "confirm_previous_commit"
    assert isinstance(plan.execution_artifact, JunosConfigArtifact)
    assert plan.recovery_artifact is None
    assert "<description>profiled-plan</description>" in plan.execution_artifact.xml
    assert plan.verify_digest()


def test_already_compliant_profiled_target_produces_no_plan() -> None:
    device, interface = profiled_device(AutomationProfileID.CAT8000V_IOSXE)
    result = plan_profiled_change(
        intent(device, interface),
        FakeInventory(device, interface),
        FakeSecrets(),
        FakeCollector(observed(device, interface, description="profiled-plan")),
    )
    assert result.plan is None
    assert result.message == "interface is already compliant; no profiled plan produced"


def test_non_openbao_reference_fails_before_secret_load_or_collection() -> None:
    device, interface = profiled_device(AutomationProfileID.CAT8000V_IOSXE)
    secrets = FakeSecrets(source="environment")
    collector = FakeCollector(observed(device, interface))
    with pytest.raises(ProfiledPlanningError, match="credential binding"):
        plan_profiled_change(
            intent(device, interface),
            FakeInventory(device, interface),
            secrets,
            collector,
        )
    assert secrets.reference_calls == 1
    assert secrets.load_calls == 0
    assert collector.calls == 0


def test_profiled_subject_mismatch_fails_closed_before_secret_or_transport() -> None:
    device, interface = profiled_device(AutomationProfileID.CAT8000V_IOSXE)
    mismatched = device.model_copy(update={"device_identity": "netbox:dcim.device:99"})
    inventory = FakeInventory(mismatched, interface)
    secrets = FakeSecrets()
    collector = FakeCollector(observed(device, interface))
    with pytest.raises(ValueError, match="Git-owned subject"):
        plan_profiled_change(
            intent(device, interface),
            inventory,
            secrets,
            collector,
        )
    assert secrets.reference_calls == 0
    assert secrets.load_calls == 0
    assert collector.calls == 0


def test_stable_protected_interface_identity_blocks_before_secret_or_transport() -> (
    None
):
    device, _interface = profiled_device(AutomationProfileID.CAT8000V_IOSXE)
    protected = device.protected_interfaces[0]
    secrets = FakeSecrets()
    collector = FakeCollector(observed(device, protected))
    with pytest.raises(ProfiledPlanningError, match="protected"):
        plan_profiled_change(
            intent(device, protected),
            FakeInventory(device, protected),
            secrets,
            collector,
        )
    assert secrets.reference_calls == 0
    assert secrets.load_calls == 0
    assert collector.calls == 0


def test_profiled_plan_rejects_old_schema_and_profile_tampering() -> None:
    device, interface = profiled_device(AutomationProfileID.CAT8000V_IOSXE)
    result = plan_profiled_change(
        intent(device, interface),
        FakeInventory(device, interface),
        FakeSecrets(),
        FakeCollector(observed(device, interface)),
    )
    assert result.plan is not None
    payload = result.plan.model_dump(mode="json")

    old = dict(payload)
    old["schema_version"] = "1"
    with pytest.raises(ValidationError):
        ProfiledDeploymentPlan.model_validate(old)

    wrong_profile = dict(payload)
    wrong_profile["automation_profile_id"] = AutomationProfileID.IOSV_159_3_M12
    with pytest.raises((ValidationError, ValueError)):
        ProfiledDeploymentPlan.model_validate(wrong_profile)


def test_profiled_planning_has_no_legacy_inventory_or_write_adapter_dependency() -> (
    None
):
    source = (
        Path(__file__).parents[1] / "src/network_change_delivery/profiled_planning.py"
    ).read_text(encoding="utf-8")

    assert "from network_change_delivery.inventory import" not in source
    assert "MultiVendorAdapter" not in source
    assert "ncdp-managed" not in source
