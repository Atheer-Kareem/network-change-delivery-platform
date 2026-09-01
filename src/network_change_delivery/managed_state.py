"""Canonical managed-state projections for the four reviewed service verticals.

These snapshots are deliberately distinct from B4 proposal and observation
digests.  They contain only fields owned by an exact ownership envelope, so an
observed state and desired state with equal managed semantics hash identically.
"""

from __future__ import annotations

import ipaddress
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from network_change_delivery.architecture_contracts import (
    ManagedOwnershipEnvelope,
    ManagedScopeKind,
    ManagedVertical,
    NetBoxDeviceIdentity,
    Sha256Digest,
    StableInterfaceIdentity,
)
from network_change_delivery.audit import canonical_json_bytes, sha256_identity
from network_change_delivery.ospf_triangle import (
    OspfDesiredState,
    OspfObservation,
    OspfTriangleIntent,
    build_ospf_desired_state,
    build_ospf_ownership_envelope,
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
    RoutedUnderlayDesiredState,
    RoutedUnderlayIntent,
    RoutedUnderlayObservation,
    build_routed_underlay_desired_state,
    build_routed_underlay_ownership_envelope,
)
from network_change_delivery.security_policy import (
    AclAction,
    AclDesiredState,
    AclObservation,
    AclRuleIntent,
    AclSecurityIntent,
    build_acl_desired_state,
    build_acl_ownership_envelope,
)
from network_change_delivery.vlan_service import (
    VlanDesiredState,
    VlanObservation,
    VlanServiceIntent,
    build_vlan_desired_state,
    build_vlan_ownership_envelope,
)


class ManagedStateProjectionError(ValueError):
    """A semantic state cannot be projected into the exact owned envelope."""


class RoutedInterfaceManagedState(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    interface: StableInterfaceIdentity
    routed_l3_present: bool
    ipv4_addresses: tuple[ipaddress.IPv4Interface, ...]
    admin_enabled: bool | None

    @model_validator(mode="after")
    def absent_shape(self) -> RoutedInterfaceManagedState:
        if not self.routed_l3_present and (
            self.ipv4_addresses or self.admin_enabled is not None
        ):
            raise ValueError("absent routed interface has managed state")
        if self.routed_l3_present and self.admin_enabled is None:
            raise ValueError("routed interface admin state is unobservable")
        return self


class RoutedUnderlayManagedPayload(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    interfaces: tuple[RoutedInterfaceManagedState, ...]


class OspfInterfaceManagedState(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    interface: StableInterfaceIdentity
    participating: bool
    area: str | None = None
    network_type: str | None = None
    passive: bool | None = None

    @model_validator(mode="after")
    def participation_shape(self) -> OspfInterfaceManagedState:
        details = (self.area, self.network_type, self.passive)
        if self.participating != all(value is not None for value in details):
            raise ValueError("OSPF interface managed state is incomplete")
        return self


class OspfRouterManagedState(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    device_identity: NetBoxDeviceIdentity
    process_present: bool
    router_id: ipaddress.IPv4Address | None = None
    interfaces: tuple[OspfInterfaceManagedState, ...]

    @model_validator(mode="after")
    def process_shape(self) -> OspfRouterManagedState:
        if not self.process_present and any(
            item.participating for item in self.interfaces
        ):
            raise ValueError("absent OSPF process has participating interfaces")
        return self


class OspfManagedPayload(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    routers: tuple[OspfRouterManagedState, ...]


class VlanManagedVlan(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    vid: Literal[10, 20]
    present: bool
    name: str | None = None

    @model_validator(mode="after")
    def presence_shape(self) -> VlanManagedVlan:
        if self.present != (self.name is not None):
            raise ValueError("VLAN presence and name disagree")
        return self


class VlanCoreInterfaceManagedState(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    interface: StableInterfaceIdentity
    present: bool
    admin_enabled: bool | None
    encapsulation_vlan: int | None = None
    gateway_addresses: tuple[ipaddress.IPv4Interface, ...] = ()

    @model_validator(mode="after")
    def presence_shape(self) -> VlanCoreInterfaceManagedState:
        if not self.present and (
            self.admin_enabled is not None
            or self.encapsulation_vlan is not None
            or self.gateway_addresses
        ):
            raise ValueError("absent VLAN interface has managed state")
        if self.present and self.admin_enabled is None:
            raise ValueError("VLAN interface admin state is unobservable")
        return self


class VlanPortManagedState(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    interface: StableInterfaceIdentity
    mode: Literal["trunk", "access", "dynamic auto", "dynamic desirable", "none"]
    allowed_vlans: tuple[int, ...] = ()
    access_vlan: int | None = None
    admin_enabled: bool


class VlanManagedPayload(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    vlans: tuple[VlanManagedVlan, VlanManagedVlan]
    core_interfaces: tuple[
        VlanCoreInterfaceManagedState,
        VlanCoreInterfaceManagedState,
        VlanCoreInterfaceManagedState,
    ]
    access_ports: tuple[
        VlanPortManagedState, VlanPortManagedState, VlanPortManagedState
    ]


class AclManagedAttachment(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    device_identity: NetBoxDeviceIdentity
    interface: StableInterfaceIdentity


class AclManagedPayload(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    policy_present: bool
    rules: tuple[AclRuleIntent, ...] = ()
    attachment: AclManagedAttachment | None = None
    direction: Literal["in", "out"] | None = None
    effective_default_action: AclAction | None = None

    @model_validator(mode="after")
    def presence_shape(self) -> AclManagedPayload:
        if self.policy_present:
            if (
                not self.rules
                or self.attachment is None
                or self.direction is None
                or self.effective_default_action is None
            ):
                raise ValueError("present ACL managed state is incomplete")
        elif (
            self.rules
            or self.attachment is not None
            or self.direction is not None
            or self.effective_default_action is not None
        ):
            raise ValueError("absent ACL has managed state")
        return self


class _ManagedStateSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal["1"] = "1"
    ownership_envelope: ManagedOwnershipEnvelope
    digest: Sha256Digest

    def calculated_digest(self) -> str:
        return sha256_identity(
            canonical_json_bytes(self.model_dump(mode="json", exclude={"digest"}))
        )

    @model_validator(mode="after")
    def valid_digest_and_vertical(self) -> _ManagedStateSnapshot:
        if self.ownership_envelope.vertical is not self.vertical:
            raise ValueError("managed-state vertical and ownership envelope disagree")
        if self.digest != self.calculated_digest():
            raise ValueError("managed-state digest is invalid")
        return self


class RoutedUnderlayManagedStateSnapshot(_ManagedStateSnapshot):
    vertical: Literal[ManagedVertical.ROUTED_UNDERLAY] = ManagedVertical.ROUTED_UNDERLAY
    payload: RoutedUnderlayManagedPayload

    @model_validator(mode="after")
    def exact_scope(self) -> RoutedUnderlayManagedStateSnapshot:
        expected = tuple(
            item.identity
            for item in self.ownership_envelope.scope
            if item.kind is ManagedScopeKind.INTERFACE
        )
        if (
            tuple(item.interface.interface for item in self.payload.interfaces)
            != expected
        ):
            raise ValueError("routed-underlay payload is outside its exact scope")
        return self


class OspfManagedStateSnapshot(_ManagedStateSnapshot):
    vertical: Literal[ManagedVertical.OSPF] = ManagedVertical.OSPF
    payload: OspfManagedPayload

    @model_validator(mode="after")
    def exact_scope(self) -> OspfManagedStateSnapshot:
        devices = tuple(item.device_identity for item in self.payload.routers)
        interfaces = tuple(
            item.interface.interface
            for router in self.payload.routers
            for item in router.interfaces
        )
        expected_interfaces = tuple(
            item.identity
            for item in self.ownership_envelope.scope
            if item.kind is ManagedScopeKind.INTERFACE
        )
        if (
            devices != self.ownership_envelope.targets
            or interfaces != expected_interfaces
        ):
            raise ValueError("OSPF payload is outside its exact scope")
        return self


class VlanManagedStateSnapshot(_ManagedStateSnapshot):
    vertical: Literal[ManagedVertical.VLAN] = ManagedVertical.VLAN
    payload: VlanManagedPayload

    @model_validator(mode="after")
    def exact_scope(self) -> VlanManagedStateSnapshot:
        interfaces = tuple(
            item.interface.interface
            for item in (*self.payload.core_interfaces, *self.payload.access_ports)
        )
        expected = tuple(
            item.identity
            for item in self.ownership_envelope.scope
            if item.kind is ManagedScopeKind.INTERFACE
        )
        if interfaces != expected:
            raise ValueError("VLAN payload is outside its exact scope")
        return self


class AclManagedStateSnapshot(_ManagedStateSnapshot):
    vertical: Literal[ManagedVertical.ACL] = ManagedVertical.ACL
    payload: AclManagedPayload

    @model_validator(mode="after")
    def exact_scope(self) -> AclManagedStateSnapshot:
        if self.payload.attachment is not None:
            interfaces = tuple(
                item.identity
                for item in self.ownership_envelope.scope
                if item.kind is ManagedScopeKind.INTERFACE
            )
            if interfaces != (self.payload.attachment.interface.interface,):
                raise ValueError("ACL attachment is outside its exact scope")
        return self


type ManagedStateSnapshot = Annotated[
    RoutedUnderlayManagedStateSnapshot
    | OspfManagedStateSnapshot
    | VlanManagedStateSnapshot
    | AclManagedStateSnapshot,
    Field(discriminator="vertical"),
]
MANAGED_STATE_ADAPTER = TypeAdapter(ManagedStateSnapshot)


def _snapshot(
    model: type[_ManagedStateSnapshot],
    envelope: ManagedOwnershipEnvelope,
    payload: BaseModel,
) -> ManagedStateSnapshot:
    unsigned = model.model_construct(
        schema_version="1",
        vertical=envelope.vertical,
        ownership_envelope=envelope,
        payload=payload,
        digest="sha256:" + "0" * 64,
    )
    payload_data = unsigned.model_dump(mode="json")
    payload_data["digest"] = unsigned.calculated_digest()
    return model.model_validate(payload_data)


def project_routed_underlay_observation(
    observation: RoutedUnderlayObservation, intent: RoutedUnderlayIntent
) -> RoutedUnderlayManagedStateSnapshot:
    payload = RoutedUnderlayManagedPayload(
        interfaces=tuple(
            RoutedInterfaceManagedState(
                interface=item.interface,
                routed_l3_present=item.exists,
                ipv4_addresses=tuple(sorted(item.ipv4_addresses, key=str)),
                admin_enabled=item.admin_enabled if item.exists else None,
            )
            for item in observation.interfaces
        )
    )
    return _snapshot(
        RoutedUnderlayManagedStateSnapshot,
        build_routed_underlay_ownership_envelope(intent),
        payload,
    )  # type: ignore[return-value]


def project_routed_underlay_desired(
    desired: RoutedUnderlayDesiredState, intent: RoutedUnderlayIntent
) -> RoutedUnderlayManagedStateSnapshot:
    payload = RoutedUnderlayManagedPayload(
        interfaces=tuple(
            RoutedInterfaceManagedState(
                interface=item.interface,
                routed_l3_present=item.routed_l3_present,
                ipv4_addresses=tuple(sorted(item.ipv4_addresses, key=str)),
                admin_enabled=item.admin_enabled,
            )
            for item in desired.interfaces
        )
    )
    return _snapshot(
        RoutedUnderlayManagedStateSnapshot,
        build_routed_underlay_ownership_envelope(intent),
        payload,
    )  # type: ignore[return-value]


def _ospf_interface(item: object) -> OspfInterfaceManagedState:
    return OspfInterfaceManagedState(
        interface=item.interface,
        participating=item.participating,
        area=item.area,
        network_type=item.network_type.value
        if hasattr(item.network_type, "value")
        else item.network_type,
        passive=item.passive,
    )


def project_ospf_observation(
    observation: OspfObservation, intent: OspfTriangleIntent
) -> OspfManagedStateSnapshot:
    payload = OspfManagedPayload(
        routers=tuple(
            OspfRouterManagedState(
                device_identity=item.device_identity,
                process_present=item.process_present,
                router_id=item.router_id,
                interfaces=tuple(
                    _ospf_interface(interface) for interface in item.interfaces
                ),
            )
            for item in observation.routers
        )
    )
    return _snapshot(
        OspfManagedStateSnapshot, build_ospf_ownership_envelope(intent), payload
    )  # type: ignore[return-value]


def project_ospf_desired(
    desired: OspfDesiredState, intent: OspfTriangleIntent
) -> OspfManagedStateSnapshot:
    payload = OspfManagedPayload(
        routers=tuple(
            OspfRouterManagedState(
                device_identity=item.device_identity,
                process_present=item.process_present,
                router_id=item.router_id,
                interfaces=tuple(
                    _ospf_interface(interface) for interface in item.interfaces
                ),
            )
            for item in desired.routers
        )
    )
    return _snapshot(
        OspfManagedStateSnapshot, build_ospf_ownership_envelope(intent), payload
    )  # type: ignore[return-value]


def project_vlan_observation(
    observation: VlanObservation, intent: VlanServiceIntent
) -> VlanManagedStateSnapshot:
    core = (observation.core_parent, *observation.core_subinterfaces)
    payload = VlanManagedPayload(
        vlans=tuple(
            VlanManagedVlan(
                vid=item.vid,
                present=item.present,
                name=item.name if item.present else None,
            )
            for item in observation.access_vlans
        ),  # type: ignore[arg-type]
        core_interfaces=tuple(
            VlanCoreInterfaceManagedState(
                interface=item.interface,
                present=item.exists,
                admin_enabled=item.admin_enabled if item.exists else None,
                encapsulation_vlan=item.encapsulation_vlan,
                gateway_addresses=tuple(sorted(item.ipv4_addresses, key=str)),
            )
            for item in core
        ),  # type: ignore[arg-type]
        access_ports=tuple(
            VlanPortManagedState(
                interface=item.interface,
                mode=item.mode,
                allowed_vlans=tuple(sorted(item.allowed_vlans)),
                access_vlan=item.access_vlan,
                admin_enabled=item.admin_enabled,
            )
            for item in observation.access_ports
        ),  # type: ignore[arg-type]
    )
    return _snapshot(
        VlanManagedStateSnapshot, build_vlan_ownership_envelope(intent), payload
    )  # type: ignore[return-value]


def project_vlan_desired(
    desired: VlanDesiredState, intent: VlanServiceIntent
) -> VlanManagedStateSnapshot:
    parent = VlanCoreInterfaceManagedState(
        interface=desired.core_parent,
        present=True,
        admin_enabled=True,
        encapsulation_vlan=None,
        gateway_addresses=(),
    )
    gateways = tuple(
        VlanCoreInterfaceManagedState(
            interface=item.subinterface,
            present=True,
            admin_enabled=item.admin_enabled,
            encapsulation_vlan=item.vid,
            gateway_addresses=(item.gateway,),
        )
        for item in desired.gateways
    )
    payload = VlanManagedPayload(
        vlans=tuple(
            VlanManagedVlan(vid=item.vid, present=True, name=item.name)
            for item in desired.gateways
        ),  # type: ignore[arg-type]
        core_interfaces=(parent, *gateways),  # type: ignore[arg-type]
        access_ports=tuple(
            VlanPortManagedState(
                interface=item.interface,
                mode=item.mode,
                allowed_vlans=item.allowed_vlans,
                access_vlan=item.access_vlan,
                admin_enabled=item.admin_enabled,
            )
            for item in desired.access_ports
        ),  # type: ignore[arg-type]
    )
    return _snapshot(
        VlanManagedStateSnapshot, build_vlan_ownership_envelope(intent), payload
    )  # type: ignore[return-value]


def project_acl_observation(
    observation: AclObservation, intent: AclSecurityIntent
) -> AclManagedStateSnapshot:
    attachment = None
    direction = None
    if observation.policy_present:
        observed = observation.attachments[0]
        attachment = AclManagedAttachment(
            device_identity=intent.attachment.device_identity,
            interface=intent.attachment.interface,
        )
        direction = observed.direction
    payload = AclManagedPayload(
        policy_present=observation.policy_present,
        rules=observation.rules,
        attachment=attachment,
        direction=direction,
        effective_default_action=AclAction.PERMIT
        if observation.policy_present
        else None,
    )
    return _snapshot(
        AclManagedStateSnapshot, build_acl_ownership_envelope(intent), payload
    )  # type: ignore[return-value]


def project_acl_desired(
    desired: AclDesiredState, intent: AclSecurityIntent
) -> AclManagedStateSnapshot:
    payload = AclManagedPayload(
        policy_present=True,
        rules=desired.rules,
        attachment=AclManagedAttachment(
            device_identity=desired.attachment.device_identity,
            interface=desired.attachment.interface,
        ),
        direction=desired.attachment.direction.value,
        effective_default_action=desired.effective_default_action,
    )
    return _snapshot(
        AclManagedStateSnapshot, build_acl_ownership_envelope(intent), payload
    )  # type: ignore[return-value]


def build_current_git_managed_d1() -> tuple[
    RoutedUnderlayManagedStateSnapshot,
    OspfManagedStateSnapshot,
    VlanManagedStateSnapshot,
    AclManagedStateSnapshot,
]:
    """Project the accepted B4 Git proposals into the separate B5 state form."""
    data_plane = build_accepted_reference_allocation_evidence()
    routing = build_accepted_routing_identity_evidence()
    vlan_allocation = build_accepted_vlan_service_evidence()

    underlay_intent = RoutedUnderlayIntent.from_reference_allocation(data_plane)
    underlay = project_routed_underlay_desired(
        build_routed_underlay_desired_state(underlay_intent), underlay_intent
    )
    ospf_intent = OspfTriangleIntent.from_allocations(data_plane, routing)
    ospf = project_ospf_desired(build_ospf_desired_state(ospf_intent), ospf_intent)
    vlan_intent = VlanServiceIntent.from_allocations(data_plane, vlan_allocation)
    vlan = project_vlan_desired(build_vlan_desired_state(vlan_intent), vlan_intent)
    acl_intent = AclSecurityIntent.from_allocations(
        data_plane, vlan_allocation, build_vlan_desired_state(vlan_intent)
    )
    acl = project_acl_desired(build_acl_desired_state(acl_intent), acl_intent)
    return underlay, ospf, vlan, acl
