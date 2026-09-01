from datetime import UTC, datetime

import pytest

from network_change_delivery.managed_state import (
    AclManagedStateSnapshot,
    OspfManagedStateSnapshot,
    RoutedUnderlayManagedStateSnapshot,
    VlanManagedStateSnapshot,
    build_current_git_managed_d1,
    project_acl_observation,
    project_ospf_observation,
    project_routed_underlay_observation,
    project_vlan_observation,
)
from network_change_delivery.ospf_triangle import (
    ObservedOspfInterfaceState,
    ObservedOspfRouterState,
    OspfObservation,
    OspfTriangleIntent,
)
from network_change_delivery.reference_data_plane import (
    build_accepted_reference_allocation_evidence,
)
from network_change_delivery.reference_routing_identity import (
    build_accepted_routing_identity_evidence,
)
from network_change_delivery.reference_vlan_service import (
    build_accepted_vlan_service_evidence,
)
from network_change_delivery.routed_underlay import (
    ObservedRoutedInterfaceState,
    RoutedUnderlayIntent,
    RoutedUnderlayObservation,
)
from network_change_delivery.security_policy import (
    ACL_NAME,
    ACL_TARGET_INTERFACE_NAME,
    AclAction,
    AclObservation,
    AclSecurityIntent,
    ObservedAclAttachment,
)
from network_change_delivery.vlan_service import (
    ObservedAccessPort,
    ObservedAccessVlan,
    ObservedCoreVlanInterface,
    VlanObservation,
    VlanServiceIntent,
    build_vlan_desired_state,
)

NOW = datetime(2026, 9, 1, tzinfo=UTC)
CANONICAL_D1_DIGESTS = (
    "sha256:f610b0aae6d3e27d52823ef6740e67dfc3078592c4a244346dd31259732bb2f0",
    "sha256:22d403c2899738ce4a192bc702bd5e485f6b9ac97f5a0bb586603b9f6efc0d16",
    "sha256:4df7b44ebca3b62109dbb6a74f074ba83627b6b235eb932edb53f082396ae19e",
    "sha256:88720b02bf3a2fc5d95aa155e8408bd992ea08d1123ac3a992c5404219efd946",
)


def service_inputs():
    data_plane = build_accepted_reference_allocation_evidence()
    routing = build_accepted_routing_identity_evidence()
    vlan_allocation = build_accepted_vlan_service_evidence()
    underlay_intent = RoutedUnderlayIntent.from_reference_allocation(data_plane)
    ospf_intent = OspfTriangleIntent.from_allocations(data_plane, routing)
    vlan_intent = VlanServiceIntent.from_allocations(data_plane, vlan_allocation)
    vlan_desired = build_vlan_desired_state(vlan_intent)
    acl_intent = AclSecurityIntent.from_allocations(
        data_plane, vlan_allocation, vlan_desired
    )
    return underlay_intent, ospf_intent, vlan_intent, acl_intent


def resign(state, *, payload):
    unsigned = type(state).model_construct(
        schema_version=state.schema_version,
        vertical=state.vertical,
        ownership_envelope=state.ownership_envelope,
        payload=payload,
        digest="sha256:" + "0" * 64,
    )
    data = unsigned.model_dump(mode="json")
    data["digest"] = unsigned.calculated_digest()
    return type(state).model_validate(data)


def test_current_git_canonical_d1_digests_are_frozen_and_separate() -> None:
    states = build_current_git_managed_d1()
    assert tuple(item.digest for item in states) == CANONICAL_D1_DIGESTS
    assert tuple(type(item) for item in states) == (
        RoutedUnderlayManagedStateSnapshot,
        OspfManagedStateSnapshot,
        VlanManagedStateSnapshot,
        AclManagedStateSnapshot,
    )


def test_routed_observation_equivalence_and_unowned_operational_state() -> None:
    desired = build_current_git_managed_d1()[0]
    intent = service_inputs()[0]
    interfaces = tuple(
        ObservedRoutedInterfaceState(
            device_identity=item.interface.device,
            interface=item.interface,
            exists=True,
            ipv4_addresses=item.ipv4_addresses,
            admin_enabled=item.admin_enabled,
            operational_status="down",
        )
        for item in desired.payload.interfaces
    )
    observation = RoutedUnderlayObservation(observed_at=NOW, interfaces=interfaces)
    assert (
        project_routed_underlay_observation(observation, intent).digest
        == desired.digest
    )
    changed_status = observation.model_copy(
        update={
            "interfaces": (
                interfaces[0].model_copy(update={"operational_status": "up"}),
                *interfaces[1:],
            )
        }
    )
    assert (
        project_routed_underlay_observation(changed_status, intent).digest
        == desired.digest
    )
    changed_address = observation.model_copy(
        update={
            "interfaces": (
                interfaces[0].model_copy(update={"ipv4_addresses": ("10.6.12.1/30",)}),
                *interfaces[1:],
            )
        }
    )
    assert (
        project_routed_underlay_observation(changed_address, intent).digest
        != desired.digest
    )


def test_routed_observation_is_normalized_by_stable_identity_not_provider_order() -> (
    None
):
    desired = build_current_git_managed_d1()[0]
    intent = service_inputs()[0]
    interfaces = tuple(
        ObservedRoutedInterfaceState(
            device_identity=item.interface.device,
            interface=item.interface,
            exists=True,
            ipv4_addresses=item.ipv4_addresses,
            admin_enabled=item.admin_enabled,
            operational_status="up",
        )
        for item in desired.payload.interfaces
    )
    grouped_provider_order = (
        interfaces[0],
        interfaces[2],
        interfaces[1],
        interfaces[4],
        interfaces[3],
        interfaces[5],
    )
    observation = RoutedUnderlayObservation(
        observed_at=NOW, interfaces=grouped_provider_order
    )
    assert (
        project_routed_underlay_observation(observation, intent).digest
        == desired.digest
    )


def test_ospf_observation_equivalence_excludes_process_identity() -> None:
    desired = build_current_git_managed_d1()[1]
    intent = service_inputs()[1]
    routers = tuple(
        ObservedOspfRouterState(
            device_identity=item.device_identity,
            logical_name=intent.routers[index].logical_name,
            automation_profile_id=intent.routers[index].automation_profile_id,
            process_present=True,
            process_identity="provider-local-99",
            router_id=item.router_id,
            interfaces=tuple(
                ObservedOspfInterfaceState(**interface.model_dump())
                for interface in item.interfaces
            ),
        )
        for index, item in enumerate(desired.payload.routers)
    )
    observation = OspfObservation(observed_at=NOW, routers=routers)
    assert project_ospf_observation(observation, intent).digest == desired.digest
    changed = observation.model_copy(
        update={
            "routers": (
                routers[0].model_copy(update={"router_id": "192.0.2.1"}),
                *routers[1:],
            )
        }
    )
    assert project_ospf_observation(changed, intent).digest != desired.digest


def test_vlan_observation_equivalence_excludes_native_and_collision_metadata() -> None:
    desired = build_current_git_managed_d1()[2]
    intent = service_inputs()[2]
    core = tuple(
        ObservedCoreVlanInterface(
            interface=item.interface,
            exists=item.present,
            admin_enabled=item.admin_enabled,
            encapsulation_vlan=item.encapsulation_vlan,
            ipv4_addresses=item.gateway_addresses,
        )
        for item in desired.payload.core_interfaces
    )
    vlans = tuple(
        ObservedAccessVlan(
            vid=item.vid,
            present=item.present,
            name=item.name,
            member_interfaces=("GigabitEthernet0/1",),
        )
        for item in desired.payload.vlans
    )
    ports = tuple(
        ObservedAccessPort(
            interface=item.interface,
            mode=item.mode,
            admin_enabled=item.admin_enabled,
            allowed_vlans=item.allowed_vlans,
            access_vlan=item.access_vlan,
            native_vlan=1,
        )
        for item in desired.payload.access_ports
    )
    observation = VlanObservation(
        observed_at=NOW,
        core_parent=core[0],
        core_subinterfaces=core[1:],
        access_vlans=vlans,
        access_ports=ports,
    )
    assert project_vlan_observation(observation, intent).digest == desired.digest
    changed_native = observation.model_copy(
        update={
            "access_ports": (
                ports[0].model_copy(update={"native_vlan": 2}),
                *ports[1:],
            )
        }
    )
    assert project_vlan_observation(changed_native, intent).digest == desired.digest
    changed_membership_evidence = observation.model_copy(
        update={
            "access_vlans": (
                vlans[0].model_copy(
                    update={"member_interfaces": ("GigabitEthernet0/2",)}
                ),
                vlans[1],
            )
        }
    )
    assert (
        project_vlan_observation(changed_membership_evidence, intent).digest
        == desired.digest
    )
    changed_mode = observation.model_copy(
        update={
            "access_ports": (
                ports[0].model_copy(update={"mode": "access", "allowed_vlans": ()}),
                *ports[1:],
            )
        }
    )
    assert project_vlan_observation(changed_mode, intent).digest != desired.digest


def test_acl_absent_and_desired_equivalence() -> None:
    desired = build_current_git_managed_d1()[3]
    intent = service_inputs()[3]
    absent = project_acl_observation(
        AclObservation(observed_at=NOW, policy_present=False), intent
    )
    assert absent.payload.policy_present is False
    assert absent.digest != desired.digest
    exact = AclObservation(
        observed_at=NOW,
        policy_present=True,
        reserved_acl_names=(ACL_NAME,),
        rules=desired.payload.rules,
        attachments=(
            ObservedAclAttachment(
                interface_name=ACL_TARGET_INTERFACE_NAME,
                acl_name=ACL_NAME,
                direction="out",
            ),
        ),
    )
    assert project_acl_observation(exact, intent).digest == desired.digest
    later = exact.model_copy(update={"observed_at": datetime(2026, 9, 2, tzinfo=UTC)})
    assert project_acl_observation(later, intent).digest == desired.digest
    changed = exact.model_copy(update={"rules": tuple(reversed(exact.rules))})
    with pytest.raises(ValueError):
        AclObservation.model_validate(changed.model_dump())


def test_acl_owned_rule_order_direction_default_and_attachment_are_bound() -> None:
    desired = build_current_git_managed_d1()[3]
    first = desired.payload.rules[0]
    mutations = (
        desired.payload.model_copy(
            update={
                "rules": (
                    first.model_copy(update={"action": AclAction.DENY}),
                    *desired.payload.rules[1:],
                )
            }
        ),
        desired.payload.model_copy(
            update={"rules": tuple(reversed(desired.payload.rules))}
        ),
        desired.payload.model_copy(update={"direction": "in"}),
        desired.payload.model_copy(update={"effective_default_action": AclAction.DENY}),
    )
    assert all(
        resign(desired, payload=item).digest != desired.digest for item in mutations
    )
    wrong_attachment = desired.payload.attachment.model_copy(
        update={
            "interface": desired.payload.attachment.interface.model_copy(
                update={"interface": "netbox:dcim.interface:21"}
            )
        }
    )
    with pytest.raises(ValueError):
        resign(
            desired,
            payload=desired.payload.model_copy(update={"attachment": wrong_attachment}),
        )


def test_owned_admin_presence_and_participation_changes_are_bound() -> None:
    underlay, ospf, vlan, _ = build_current_git_managed_d1()
    changed_underlay = underlay.payload.model_copy(
        update={
            "interfaces": (
                underlay.payload.interfaces[0].model_copy(
                    update={"admin_enabled": False}
                ),
                *underlay.payload.interfaces[1:],
            )
        }
    )
    assert resign(underlay, payload=changed_underlay).digest != underlay.digest

    router = ospf.payload.routers[0]
    interface = router.interfaces[0].model_copy(
        update={
            "participating": False,
            "area": None,
            "network_type": None,
            "passive": None,
        }
    )
    changed_ospf = ospf.payload.model_copy(
        update={
            "routers": (
                router.model_copy(
                    update={"interfaces": (interface, router.interfaces[1])}
                ),
                *ospf.payload.routers[1:],
            )
        }
    )
    assert resign(ospf, payload=changed_ospf).digest != ospf.digest

    changed_vlan = vlan.payload.model_copy(
        update={
            "vlans": (
                vlan.payload.vlans[0].model_copy(
                    update={"present": False, "name": None}
                ),
                vlan.payload.vlans[1],
            )
        }
    )
    assert resign(vlan, payload=changed_vlan).digest != vlan.digest
