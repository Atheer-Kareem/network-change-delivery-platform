from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from network_change_delivery.architecture_contracts import (
    AUTOMATION_PROFILE_CATALOG,
    AutomationProfileID,
    Capability,
    get_automation_profile,
)
from network_change_delivery.profile_inventory import PROFILED_POPULATION_CATALOG
from network_change_delivery.snmp_credentials import (
    snmp_secret_logical_path,
    snmp_username,
)
from network_change_delivery.snmp_profile import (
    SNMP_CAPABLE_PROFILE_IDS,
    SNMP_PROFILED_DEVICE_IDENTITIES,
    eligible_profiled_subject,
    profile_supports_snmp,
)
from network_change_delivery.snmp_provisioning import SnmpV3InterfaceTelemetryIntent
from network_change_delivery.snmp_telemetry import (
    SnmpCredentialReference,
    SnmpTargetIdentity,
)


def test_only_capable_profiles_project_to_snmp() -> None:
    capability = Capability.SNMPV3_AUTHPRIV_SHA256_AES128
    assert SNMP_CAPABLE_PROFILE_IDS == (
        AutomationProfileID.CAT8000V_IOSXE,
        AutomationProfileID.VJUNOS_ROUTER,
    )
    assert SNMP_PROFILED_DEVICE_IDENTITIES == (
        "netbox:dcim.device:1",
        "netbox:dcim.device:2",
    )
    assert all(
        capability in get_automation_profile(profile_id).admitted_capabilities
        for profile_id in SNMP_CAPABLE_PROFILE_IDS
    )
    assert not profile_supports_snmp(AutomationProfileID.IOSV_159_3_M12)
    assert not profile_supports_snmp(AutomationProfileID.IOSVL2_2020)
    assert tuple(member.device_identity for member in PROFILED_POPULATION_CATALOG) == (
        "netbox:dcim.device:1",
        "netbox:dcim.device:2",
        "netbox:dcim.device:8",
        "netbox:dcim.device:9",
    )


def test_target_identity_requires_capable_profile_and_device_binding() -> None:
    for number, profile, name in (
        (8, AutomationProfileID.IOSV_159_3_M12, "transit-ios-01"),
        (9, AutomationProfileID.IOSVL2_2020, "access-sw-01"),
        (1, AutomationProfileID.IOSV_159_3_M12, "core-02"),
    ):
        with pytest.raises(ValidationError, match="lacks the accepted capability"):
            SnmpTargetIdentity(
                device=f"netbox:dcim.device:{number}",
                device_name=name,
                automation_profile_id=profile,
                credential=SnmpCredentialReference(
                    device=f"netbox:dcim.device:{number}",
                    reference=(f"snmpv3:netbox:dcim.device:{number}:generation:v1"),
                    auth_selector=f"device_{number}_v1",
                ),
            )


def test_profiled_subject_admission_precedes_capability_projection() -> None:
    device = next(
        member
        for member in PROFILED_POPULATION_CATALOG
        if member.device_identity == "netbox:dcim.device:1"
    )
    assert device.automation_profile_id is AutomationProfileID.CAT8000V_IOSXE

    # The catalog member is not a resolved device, so construct a valid subject
    # from the existing resolved-model test boundary below only after asserting
    # the stable catalog binding. A mismatched identity must fail closed at the
    # subject-admission boundary rather than being accepted by profile ID alone.
    subject = SimpleNamespace(
        device_identity="netbox:dcim.device:99",
        logical_name="core-02",
        platform=SimpleNamespace(slug="cisco-ios-xe"),
        network_os="iosxe",
        automation_profile_id=AutomationProfileID.CAT8000V_IOSXE,
    )
    with pytest.raises(ValueError, match="Git-owned subject"):
        eligible_profiled_subject(subject)


def test_catalog_capability_assignments_are_explicitly_closed() -> None:
    assert {
        profile_id
        for profile_id, profile in AUTOMATION_PROFILE_CATALOG.items()
        if Capability.SNMPV3_AUTHPRIV_SHA256_AES128 in profile.admitted_capabilities
    } == set(SNMP_CAPABLE_PROFILE_IDS)


def test_telemetry_credential_routing_uses_projection_not_fleet_membership() -> None:
    assert snmp_username(1) == "ncdp_snmp_d1_v1"
    assert snmp_username(2) == "ncdp_snmp_d2_v1"
    assert snmp_secret_logical_path(1, "v1") == "ncdp/devices/1/snmpv3/v1"
    for device_id in (8, 9):
        with pytest.raises(ValueError, match="device rejected"):
            snmp_username(device_id)


@pytest.mark.parametrize("device_id", (8, 9))
def test_telemetry_capability_does_not_grant_provisioning_authority(
    device_id: int,
) -> None:
    with pytest.raises(ValidationError, match="SNMP provisioning username rejected"):
        SnmpV3InterfaceTelemetryIntent(
            change_id="RECON-PROVISIONING-BOUNDARY",
            target="transit-ios-01" if device_id == 8 else "access-sw-01",
            device=f"netbox:dcim.device:{device_id}",
            platform="cisco_iosxe",
            username=f"ncdp_snmp_d{device_id}_v1",
            credential=SnmpCredentialReference(
                device=f"netbox:dcim.device:{device_id}",
                reference=f"snmpv3:netbox:dcim.device:{device_id}:generation:v1",
                auth_selector=f"device_{device_id}_v1",
            ),
        )
