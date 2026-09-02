"""Profile-derived eligibility for the accepted SNMP telemetry contract."""

from __future__ import annotations

from collections.abc import Iterable
from types import MappingProxyType

from network_change_delivery.architecture_contracts import (
    AUTOMATION_PROFILE_CATALOG,
    AutomationProfileID,
    Capability,
    get_automation_profile,
)
from network_change_delivery.profile_inventory import (
    PROFILED_POPULATION_CATALOG,
    ProfiledInventoryDevice,
    admit_profiled_subject,
)

SNMP_TELEMETRY_CAPABILITY = Capability.SNMPV3_AUTHPRIV_SHA256_AES128

SNMP_CAPABLE_PROFILE_IDS = tuple(
    profile_id
    for profile_id, profile in AUTOMATION_PROFILE_CATALOG.items()
    if SNMP_TELEMETRY_CAPABILITY in profile.admitted_capabilities
)
SNMP_CAPABLE_PROFILES = MappingProxyType(
    {
        profile_id: get_automation_profile(profile_id)
        for profile_id in SNMP_CAPABLE_PROFILE_IDS
    }
)

SNMP_PROFILED_DEVICE_IDENTITIES = tuple(
    member.device_identity
    for member in PROFILED_POPULATION_CATALOG
    if member.automation_profile_id in SNMP_CAPABLE_PROFILES
)


def profile_supports_snmp(profile_id: AutomationProfileID) -> bool:
    """Return whether one reviewed profile supports the current SNMP contract."""
    return (
        SNMP_TELEMETRY_CAPABILITY
        in get_automation_profile(profile_id).admitted_capabilities
    )


def eligible_profiled_subject(device: ProfiledInventoryDevice) -> bool:
    """Validate the complete profiled subject before applying capability policy."""
    admit_profiled_subject(
        device_identity=device.device_identity,
        logical_name=device.logical_name,
        platform_slug=device.platform.slug,
        network_os=device.network_os,
        automation_profile_id=device.automation_profile_id,
    )
    return profile_supports_snmp(device.automation_profile_id)


def snmp_capable_profiles(
    profiles: Iterable[AutomationProfileID] = AUTOMATION_PROFILE_CATALOG,
) -> tuple[AutomationProfileID, ...]:
    """Return the capability projection in canonical profile-catalog order."""
    return tuple(
        profile_id for profile_id in profiles if profile_supports_snmp(profile_id)
    )
