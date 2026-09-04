"""Historical schema-v1 SNMP fixtures used by audit compatibility tests."""

from datetime import UTC, datetime

from network_change_delivery.models import InventoryDevice
from network_change_delivery.snmp_credentials import snmp_username
from network_change_delivery.snmp_provisioning import (
    SnmpOwnedObjectState,
    SnmpProvisioningPlan,
    SnmpV3InterfaceTelemetryIntent,
    build_snmp_provisioning_plan,
)
from network_change_delivery.snmp_telemetry import SnmpCredentialReference


def snmp_plan(platform: str = "cisco_iosxe") -> SnmpProvisioningPlan:
    """Build one deterministic legacy record for parse/audit compatibility."""
    device_id = 1 if platform == "cisco_iosxe" else 2
    identity = f"netbox:dcim.device:{device_id}"
    name = "core-02" if device_id == 1 else "edge-junos-01"
    intent = SnmpV3InterfaceTelemetryIntent(
        change_id=f"CHG-SNMP-{device_id}",
        target=name,
        device=identity,
        platform=platform,
        username=snmp_username(device_id),
        credential=SnmpCredentialReference(
            device=identity,
            reference=f"snmpv3:{identity}:generation:v1",
            auth_selector=f"device_{device_id}_v1",
        ),
    )
    return build_snmp_provisioning_plan(
        intent,
        InventoryDevice(
            name=name,
            host="192.0.2.10",
            port=22 if platform == "cisco_iosxe" else 830,
            platform=platform,
            expected_hostname=name,
            inventory_source="netbox",
            inventory_object_id=identity,
        ),
        SnmpOwnedObjectState(
            observed_hostname=name,
            local_engine_id_present=True,
            view="ABSENT",
            group="ABSENT",
            user="ABSENT",
        ),
        created_at=datetime(2026, 8, 29, tzinfo=UTC),
    )
