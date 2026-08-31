"""Additive Detour B architecture contracts outside the v1 execution path.

These types describe reviewed future architecture. They are deliberately not
imported by the current inventory, planning, adapter, Buildkite, or Terraform
paths. B2 may introduce an explicit, versioned migration boundary; B1 must not
change existing serialized models, digests, or provider behavior.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    IPvAnyInterface,
    StringConstraints,
    model_validator,
)

NonEmptyString = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Sha256Digest = Annotated[str, StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$")]
GitCommit = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{40}$")]
NetBoxDeviceIdentity = Annotated[
    str, StringConstraints(pattern=r"^netbox:dcim\.device:[1-9][0-9]*$")
]
NetBoxInterfaceIdentity = Annotated[
    str, StringConstraints(pattern=r"^netbox:dcim\.interface:[1-9][0-9]*$")
]
NetBoxIPAddressIdentity = Annotated[
    str, StringConstraints(pattern=r"^netbox:ipam\.ipaddress:[1-9][0-9]*$")
]


class NetworkOS(StrEnum):
    """Closed network operating-system vocabulary for Detour B."""

    IOSXE = "iosxe"
    IOS = "ios"
    JUNOS = "junos"


class OperationalRole(StrEnum):
    """NetBox-owned operational role, independent of network OS."""

    CORE = "core"
    EDGE = "edge"
    TRANSIT = "transit"
    ACCESS = "access"


class Capability(StrEnum):
    """Closed capabilities admitted by reviewed Git-owned profiles."""

    LAYER3_ROUTING = "layer3_routing"
    LAYER2_SWITCHING = "layer2_switching"
    SVI = "svi"
    DOT1Q_TRUNK = "dot1q_trunk"
    ACCESS_PORT = "access_port"
    OSPF = "ospf"
    IOS_ACL = "ios_acl"
    JUNOS_FIREWALL_FILTER = "junos_firewall_filter"
    COMMIT_CONFIRMED = "commit_confirmed"


class AutomationProfileID(StrEnum):
    """Closed reviewed automation-profile identities."""

    CAT8000V_IOSXE = "cat8000v_iosxe"
    IOSV_159_3_M12 = "iosv_159_3_m12"
    IOSVL2_2020 = "iosvl2_2020"
    VJUNOS_ROUTER = "vjunos_router"


class TransportFamily(StrEnum):
    """Behavioral transport family without changing its current implementation."""

    ANSIBLE_NETWORK_CLI = "ansible_network_cli"
    JUNOS_PYEZ_NETCONF = "junos_pyez_netconf"


class AdapterFamily(StrEnum):
    """Explicit adapter family; this is not a dynamic plugin registry."""

    CISCO_IOS = "cisco_ios"
    JUNOS_PYEZ = "junos_pyez"


class RendererFamily(StrEnum):
    """Explicit vendor-native renderer family."""

    CISCO_IOS = "cisco_ios"
    JUNOS_XML = "junos_xml"


class CollectorFamily(StrEnum):
    """Explicit normalized-state collector family."""

    CISCO_IOS_FACTS = "cisco_ios_facts"
    JUNOS_RPC = "junos_rpc"


class RecoveryFamily(StrEnum):
    """Explicit recovery semantics without claiming cross-platform transactions."""

    CISCO_TARGETED_INVERSE = "cisco_targeted_inverse"
    JUNOS_COMMIT_CONFIRMED = "junos_commit_confirmed"


class ManagementService(StrEnum):
    """Management service expected by an automation or readiness profile."""

    SSH = "ssh"
    NETCONF = "netconf"


class ReadinessServiceExpectation(BaseModel):
    """One profile-local service that must be ready before provider use."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    service: ManagementService
    port: int = Field(ge=1, le=65535)


class LegacySSHCompatibility(BaseModel):
    """Unaccepted IOSv-only compatibility possibility for B2 validation."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    scope: Literal["profile_local"] = "profile_local"
    profile_id: Literal["iosv_159_3_m12"] = "iosv_159_3_m12"
    key_exchange_algorithms: tuple[Literal["diffie-hellman-group14-sha1"], ...] = (
        "diffie-hellman-group14-sha1",
    )
    host_key_algorithms: tuple[Literal["ssh-rsa"], ...] = ("ssh-rsa",)
    acceptance: Literal["requires_b2_real_adapter_acceptance"] = (
        "requires_b2_real_adapter_acceptance"
    )

    @model_validator(mode="after")
    def exact_unaccepted_algorithms(self) -> LegacySSHCompatibility:
        if self.key_exchange_algorithms != ("diffie-hellman-group14-sha1",):
            raise ValueError("IOSv legacy KEX possibility must be exact")
        if self.host_key_algorithms != ("ssh-rsa",):
            raise ValueError("IOSv legacy host-key possibility must be exact")
        return self


class SSHCompatibilityPolicy(BaseModel):
    """Profile-local SSH policy; global relaxation is not representable."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    strict_host_key_verification: Literal[True] = True
    legacy_compatibility: LegacySSHCompatibility | None = None


class AutomationProfile(BaseModel):
    """Reviewed behavioral selection independent of role and CML realization."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal["1"] = "1"
    profile_id: AutomationProfileID
    network_os: NetworkOS
    admitted_capabilities: tuple[Capability, ...]
    transport_family: TransportFamily
    adapter_family: AdapterFamily
    renderer_family: RendererFamily
    collector_family: CollectorFamily
    readiness_services: tuple[ReadinessServiceExpectation, ...]
    recovery_family: RecoveryFamily
    ssh_policy: SSHCompatibilityPolicy

    @model_validator(mode="after")
    def validate_closed_behavior(self) -> AutomationProfile:
        """Reject duplicate capabilities/services and non-IOSv legacy policy."""
        if not self.admitted_capabilities or len(self.admitted_capabilities) != len(
            set(self.admitted_capabilities)
        ):
            raise ValueError(
                "automation profile capabilities must be unique and nonempty"
            )
        service_keys = tuple(
            (expectation.service, expectation.port)
            for expectation in self.readiness_services
        )
        if not service_keys or len(service_keys) != len(set(service_keys)):
            raise ValueError(
                "readiness service expectations must be unique and nonempty"
            )
        compatibility = self.ssh_policy.legacy_compatibility
        if compatibility is not None and (
            self.profile_id is not AutomationProfileID.IOSV_159_3_M12
            or compatibility.profile_id != self.profile_id.value
        ):
            raise ValueError(
                "legacy SSH compatibility is admitted only for exact IOSv profile"
            )
        if self.network_os is NetworkOS.JUNOS and compatibility is not None:
            raise ValueError("Junos transport cannot inherit IOSv SSH compatibility")
        return self


class StableInterfaceIdentity(BaseModel):
    """Stable inventory identity for one interface on one stable device."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    device: NetBoxDeviceIdentity
    interface: NetBoxInterfaceIdentity
    name: NonEmptyString


class ManagementPhysicalAttachment(BaseModel):
    """Physical management attachment; it does not contain CML coordinates."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    interface: StableInterfaceIdentity


class ManagementL3Endpoint(BaseModel):
    """Logical interface and address that own the management service endpoint."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    interface: StableInterfaceIdentity
    ip_address_identity: NetBoxIPAddressIdentity
    address: IPvAnyInterface
    service: ManagementService
    port: int = Field(ge=1, le=65535)


class ManagementBinding(BaseModel):
    """Separate physical attachment from the possibly different L3 IP owner."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal["1"] = "1"
    physical_attachment: ManagementPhysicalAttachment
    l3_endpoint: ManagementL3Endpoint

    @model_validator(mode="after")
    def interfaces_belong_to_same_device(self) -> ManagementBinding:
        if (
            self.physical_attachment.interface.device
            != self.l3_endpoint.interface.device
        ):
            raise ValueError("management binding interfaces must belong to one device")
        return self


class CmlRealizationProfileID(StrEnum):
    """Closed CML realization identities, distinct from automation profiles."""

    CAT8000V_17_18_02 = "cml_cat8000v_17_18_02"
    IOSV_159_3_M12 = "cml_iosv_159_3_m12"
    IOSVL2_2020 = "cml_iosvl2_2020"
    VJUNOS_ROUTER_23_2R1_15 = "cml_vjunos_router_23_2r1_15"


class CmlResourceAllocationMode(StrEnum):
    """Whether the profile pins resources or admits node-definition defaults."""

    EXPLICIT = "explicit"
    NODE_DEFINITION_DEFAULT = "node_definition_default"


class CmlResourceRequirements(BaseModel):
    """Resource requirements without inventing unmeasured IOSv/L2 values."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    allocation_mode: CmlResourceAllocationMode
    cpu_cores: int | None = Field(default=None, ge=1)
    ram_mb: int | None = Field(default=None, ge=256)

    @model_validator(mode="after")
    def explicit_values_match_mode(self) -> CmlResourceRequirements:
        values_present = self.cpu_cores is not None and self.ram_mb is not None
        if self.allocation_mode is CmlResourceAllocationMode.EXPLICIT:
            if not values_present:
                raise ValueError("explicit CML resources require CPU and RAM values")
        elif self.cpu_cores is not None or self.ram_mb is not None:
            raise ValueError("node-definition default resources cannot pin CPU or RAM")
        return self


class CmlPhysicalInterfaceSlot(BaseModel):
    """Physical interface-to-slot mapping owned only by CML realization data."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    interface_name: NonEmptyString
    cml_slot: int = Field(ge=0)


class CmlBootstrapProfileID(StrEnum):
    """Closed minimal-bootstrap template identities."""

    CAT8000V_MINIMAL = "cat8000v_minimal"
    IOSV_MINIMAL = "iosv_minimal"
    IOSVL2_VLAN1_MANAGEMENT = "iosvl2_vlan1_management"
    VJUNOS_ROUTER_MINIMAL = "vjunos_router_minimal"


class CmlReadinessProfileID(StrEnum):
    """Closed realization-readiness identities."""

    IOSXE_SSH = "iosxe_ssh"
    IOSV_SSH = "iosv_ssh"
    IOSVL2_SVI_SSH = "iosvl2_svi_ssh"
    JUNOS_NETCONF = "junos_netconf"


class CmlRealizationProfile(BaseModel):
    """CML-only realization data that is not stable inventory identity."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal["1"] = "1"
    profile_id: CmlRealizationProfileID
    node_definition: NonEmptyString
    image_definition: NonEmptyString
    resources: CmlResourceRequirements
    physical_interface_slots: tuple[CmlPhysicalInterfaceSlot, ...]
    bootstrap_profile: CmlBootstrapProfileID
    readiness_profile: CmlReadinessProfileID

    @model_validator(mode="after")
    def interface_slots_are_unambiguous(self) -> CmlRealizationProfile:
        interfaces = tuple(
            item.interface_name for item in self.physical_interface_slots
        )
        slots = tuple(item.cml_slot for item in self.physical_interface_slots)
        if not interfaces or len(interfaces) != len(set(interfaces)):
            raise ValueError("CML physical interface names must be unique and nonempty")
        if len(slots) != len(set(slots)):
            raise ValueError("CML physical interface slots must be unique")
        return self


def _service(service: ManagementService, port: int) -> ReadinessServiceExpectation:
    return ReadinessServiceExpectation(service=service, port=port)


AUTOMATION_PROFILE_CATALOG: Mapping[AutomationProfileID, AutomationProfile] = (
    MappingProxyType(
        {
            AutomationProfileID.CAT8000V_IOSXE: AutomationProfile(
                profile_id=AutomationProfileID.CAT8000V_IOSXE,
                network_os=NetworkOS.IOSXE,
                admitted_capabilities=(
                    Capability.LAYER3_ROUTING,
                    Capability.DOT1Q_TRUNK,
                    Capability.OSPF,
                    Capability.IOS_ACL,
                ),
                transport_family=TransportFamily.ANSIBLE_NETWORK_CLI,
                adapter_family=AdapterFamily.CISCO_IOS,
                renderer_family=RendererFamily.CISCO_IOS,
                collector_family=CollectorFamily.CISCO_IOS_FACTS,
                readiness_services=(_service(ManagementService.SSH, 22),),
                recovery_family=RecoveryFamily.CISCO_TARGETED_INVERSE,
                ssh_policy=SSHCompatibilityPolicy(),
            ),
            AutomationProfileID.IOSV_159_3_M12: AutomationProfile(
                profile_id=AutomationProfileID.IOSV_159_3_M12,
                network_os=NetworkOS.IOS,
                admitted_capabilities=(
                    Capability.LAYER3_ROUTING,
                    Capability.OSPF,
                    Capability.IOS_ACL,
                ),
                transport_family=TransportFamily.ANSIBLE_NETWORK_CLI,
                adapter_family=AdapterFamily.CISCO_IOS,
                renderer_family=RendererFamily.CISCO_IOS,
                collector_family=CollectorFamily.CISCO_IOS_FACTS,
                readiness_services=(_service(ManagementService.SSH, 22),),
                recovery_family=RecoveryFamily.CISCO_TARGETED_INVERSE,
                ssh_policy=SSHCompatibilityPolicy(
                    legacy_compatibility=LegacySSHCompatibility()
                ),
            ),
            AutomationProfileID.IOSVL2_2020: AutomationProfile(
                profile_id=AutomationProfileID.IOSVL2_2020,
                network_os=NetworkOS.IOS,
                admitted_capabilities=(
                    Capability.LAYER2_SWITCHING,
                    Capability.SVI,
                    Capability.DOT1Q_TRUNK,
                    Capability.ACCESS_PORT,
                ),
                transport_family=TransportFamily.ANSIBLE_NETWORK_CLI,
                adapter_family=AdapterFamily.CISCO_IOS,
                renderer_family=RendererFamily.CISCO_IOS,
                collector_family=CollectorFamily.CISCO_IOS_FACTS,
                readiness_services=(_service(ManagementService.SSH, 22),),
                recovery_family=RecoveryFamily.CISCO_TARGETED_INVERSE,
                ssh_policy=SSHCompatibilityPolicy(),
            ),
            AutomationProfileID.VJUNOS_ROUTER: AutomationProfile(
                profile_id=AutomationProfileID.VJUNOS_ROUTER,
                network_os=NetworkOS.JUNOS,
                admitted_capabilities=(
                    Capability.LAYER3_ROUTING,
                    Capability.OSPF,
                    Capability.JUNOS_FIREWALL_FILTER,
                    Capability.COMMIT_CONFIRMED,
                ),
                transport_family=TransportFamily.JUNOS_PYEZ_NETCONF,
                adapter_family=AdapterFamily.JUNOS_PYEZ,
                renderer_family=RendererFamily.JUNOS_XML,
                collector_family=CollectorFamily.JUNOS_RPC,
                readiness_services=(_service(ManagementService.NETCONF, 830),),
                recovery_family=RecoveryFamily.JUNOS_COMMIT_CONFIRMED,
                ssh_policy=SSHCompatibilityPolicy(),
            ),
        }
    )
)


def _slots(*names: str) -> tuple[CmlPhysicalInterfaceSlot, ...]:
    return tuple(
        CmlPhysicalInterfaceSlot(interface_name=name, cml_slot=slot)
        for slot, name in enumerate(names)
    )


CML_REALIZATION_PROFILE_CATALOG: Mapping[
    CmlRealizationProfileID, CmlRealizationProfile
] = MappingProxyType(
    {
        CmlRealizationProfileID.CAT8000V_17_18_02: CmlRealizationProfile(
            profile_id=CmlRealizationProfileID.CAT8000V_17_18_02,
            node_definition="cat8000v",
            image_definition="cat8000v-17-18-02",
            resources=CmlResourceRequirements(
                allocation_mode=CmlResourceAllocationMode.EXPLICIT,
                cpu_cores=1,
                ram_mb=4096,
            ),
            physical_interface_slots=_slots(
                "GigabitEthernet1",
                "GigabitEthernet2",
                "GigabitEthernet3",
                "GigabitEthernet4",
            ),
            bootstrap_profile=CmlBootstrapProfileID.CAT8000V_MINIMAL,
            readiness_profile=CmlReadinessProfileID.IOSXE_SSH,
        ),
        CmlRealizationProfileID.IOSV_159_3_M12: CmlRealizationProfile(
            profile_id=CmlRealizationProfileID.IOSV_159_3_M12,
            node_definition="iosv",
            image_definition="iosv-159-3-m12",
            resources=CmlResourceRequirements(
                allocation_mode=CmlResourceAllocationMode.NODE_DEFINITION_DEFAULT
            ),
            physical_interface_slots=_slots("Gi0/0", "Gi0/1", "Gi0/2", "Gi0/3"),
            bootstrap_profile=CmlBootstrapProfileID.IOSV_MINIMAL,
            readiness_profile=CmlReadinessProfileID.IOSV_SSH,
        ),
        CmlRealizationProfileID.IOSVL2_2020: CmlRealizationProfile(
            profile_id=CmlRealizationProfileID.IOSVL2_2020,
            node_definition="iosvl2",
            image_definition="iosvl2-2020",
            resources=CmlResourceRequirements(
                allocation_mode=CmlResourceAllocationMode.NODE_DEFINITION_DEFAULT
            ),
            physical_interface_slots=_slots("Gi0/0", "Gi0/1", "Gi0/2", "Gi0/3"),
            bootstrap_profile=CmlBootstrapProfileID.IOSVL2_VLAN1_MANAGEMENT,
            readiness_profile=CmlReadinessProfileID.IOSVL2_SVI_SSH,
        ),
        CmlRealizationProfileID.VJUNOS_ROUTER_23_2R1_15: CmlRealizationProfile(
            profile_id=CmlRealizationProfileID.VJUNOS_ROUTER_23_2R1_15,
            node_definition="vjunos-router",
            image_definition="vjunos-router-23-2r1-15",
            resources=CmlResourceRequirements(
                allocation_mode=CmlResourceAllocationMode.EXPLICIT,
                cpu_cores=4,
                ram_mb=6144,
            ),
            physical_interface_slots=_slots("fxp0", "ge-0/0/0", "ge-0/0/1", "ge-0/0/2"),
            bootstrap_profile=CmlBootstrapProfileID.VJUNOS_ROUTER_MINIMAL,
            readiness_profile=CmlReadinessProfileID.JUNOS_NETCONF,
        ),
    }
)


def get_automation_profile(profile_id: AutomationProfileID | str) -> AutomationProfile:
    """Resolve only a recognized automation profile and fail closed otherwise."""
    try:
        recognized = AutomationProfileID(profile_id)
    except ValueError:
        raise ValueError("unknown automation profile") from None
    return AUTOMATION_PROFILE_CATALOG[recognized]


def get_cml_realization_profile(
    profile_id: CmlRealizationProfileID | str,
) -> CmlRealizationProfile:
    """Resolve only a recognized CML realization profile and fail closed otherwise."""
    try:
        recognized = CmlRealizationProfileID(profile_id)
    except ValueError:
        raise ValueError("unknown CML realization profile") from None
    return CML_REALIZATION_PROFILE_CATALOG[recognized]


class AuthorityOwner(StrEnum):
    """Closed authority owners for the Detour B contract."""

    GIT = "git"
    NETBOX = "netbox"
    OPENBAO = "openbao"
    DEVICE = "device"
    TERRAFORM_CML_STATE = "terraform_cml_state"


class AuthorityProperty(StrEnum):
    """Managed properties that must each have exactly one authority."""

    STABLE_DEVICE_IDENTITY = "stable_device_identity"
    STABLE_INTERFACE_IDENTITY = "stable_interface_identity"
    DEVICE_PLATFORM_NOS_METADATA = "device_platform_nos_metadata"
    DEVICE_ROLE = "device_role"
    PHYSICAL_TOPOLOGY_CABLING = "physical_topology_cabling"
    MANAGEMENT_IPAM_RELATIONSHIPS = "management_ipam_relationships"
    VLAN_OBJECT_IDENTITY = "vlan_object_identity"
    VLAN_VID = "vlan_vid"
    CANONICAL_VLAN_NAME = "canonical_vlan_name"
    PREFIX_IP_IDENTITY = "prefix_ip_identity"
    MANAGED_DEVICE_CONFIGURATION_INTENT = "managed_device_configuration_intent"
    VLAN_DEPLOYMENT_ATTACHMENT = "vlan_deployment_attachment"
    ACCESS_TRUNK_NATIVE_ALLOWED_BEHAVIOR = "access_trunk_native_allowed_behavior"
    GATEWAY_SUBINTERFACE_DEPLOYMENT = "gateway_subinterface_deployment"
    OSPF_DESIRED_BEHAVIOR = "ospf_desired_behavior"
    ACL_SECURITY_FLOW_POLICY = "acl_security_flow_policy"
    ASSURANCE_POLICY = "assurance_policy"
    PROFILE_BEHAVIOR_CATALOG = "profile_behavior_catalog"
    DEVICE_CREDENTIALS = "device_credentials"
    OBSERVED_REALITY = "observed_reality"
    DISPOSABLE_REALIZATION_IDENTITY_LIFECYCLE = (
        "disposable_realization_identity_lifecycle"
    )


class AuthorityAssignment(BaseModel):
    """One property-to-authority assignment."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    property: AuthorityProperty
    owner: AuthorityOwner


AUTHORITY_ASSIGNMENTS: tuple[AuthorityAssignment, ...] = tuple(
    AuthorityAssignment(property=property_, owner=owner)
    for owner, properties in (
        (
            AuthorityOwner.NETBOX,
            (
                AuthorityProperty.STABLE_DEVICE_IDENTITY,
                AuthorityProperty.STABLE_INTERFACE_IDENTITY,
                AuthorityProperty.DEVICE_PLATFORM_NOS_METADATA,
                AuthorityProperty.DEVICE_ROLE,
                AuthorityProperty.PHYSICAL_TOPOLOGY_CABLING,
                AuthorityProperty.MANAGEMENT_IPAM_RELATIONSHIPS,
                AuthorityProperty.VLAN_OBJECT_IDENTITY,
                AuthorityProperty.VLAN_VID,
                AuthorityProperty.CANONICAL_VLAN_NAME,
                AuthorityProperty.PREFIX_IP_IDENTITY,
            ),
        ),
        (
            AuthorityOwner.GIT,
            (
                AuthorityProperty.MANAGED_DEVICE_CONFIGURATION_INTENT,
                AuthorityProperty.VLAN_DEPLOYMENT_ATTACHMENT,
                AuthorityProperty.ACCESS_TRUNK_NATIVE_ALLOWED_BEHAVIOR,
                AuthorityProperty.GATEWAY_SUBINTERFACE_DEPLOYMENT,
                AuthorityProperty.OSPF_DESIRED_BEHAVIOR,
                AuthorityProperty.ACL_SECURITY_FLOW_POLICY,
                AuthorityProperty.ASSURANCE_POLICY,
                AuthorityProperty.PROFILE_BEHAVIOR_CATALOG,
            ),
        ),
        (AuthorityOwner.OPENBAO, (AuthorityProperty.DEVICE_CREDENTIALS,)),
        (AuthorityOwner.DEVICE, (AuthorityProperty.OBSERVED_REALITY,)),
        (
            AuthorityOwner.TERRAFORM_CML_STATE,
            (AuthorityProperty.DISPOSABLE_REALIZATION_IDENTITY_LIFECYCLE,),
        ),
    )
    for property_ in properties
)


class ManagedVertical(StrEnum):
    """Initial managed-state ownership-envelope verticals."""

    VLAN = "vlan"
    OSPF = "ospf"
    ACL = "acl"


class ManagedField(StrEnum):
    """Normalized fields that may be owned inside an initial envelope."""

    VLAN_PRESENCE = "vlan.presence"
    VLAN_PORT_MODE = "vlan.port_mode"
    VLAN_ACCESS_VLAN = "vlan.access_vlan"
    VLAN_ALLOWED_VLANS = "vlan.allowed_vlans"
    VLAN_NATIVE_VLAN = "vlan.native_vlan"
    VLAN_GATEWAY = "vlan.gateway"
    OSPF_PROCESS = "ospf.process"
    OSPF_ROUTER_ID = "ospf.router_id"
    OSPF_INTERFACE_PARTICIPATION = "ospf.interface_participation"
    OSPF_AREA = "ospf.area"
    OSPF_NETWORK_TYPE = "ospf.network_type"
    OSPF_PASSIVE = "ospf.passive"
    OSPF_COST = "ospf.cost"
    OSPF_AUTHENTICATION = "ospf.authentication"
    OSPF_TIMERS = "ospf.timers"
    ACL_RULE_SEMANTICS = "acl.rule_semantics"
    ACL_RULE_ORDER = "acl.rule_order"
    ACL_ATTACHMENT = "acl.attachment"
    ACL_DIRECTION = "acl.direction"
    ACL_DEFAULT_ACTION = "acl.default_action"


class ManagedScopeKind(StrEnum):
    """Stable identity kind inside a managed ownership envelope."""

    DEVICE = "device"
    INTERFACE = "interface"
    VLAN = "vlan"
    PREFIX = "prefix"
    POLICY = "policy"


class ManagedScopeIdentity(BaseModel):
    """Typed stable identity delimiting one portion of managed state."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    kind: ManagedScopeKind
    identity: NonEmptyString


_FIELDS_BY_VERTICAL: Mapping[ManagedVertical, frozenset[ManagedField]] = (
    MappingProxyType(
        {
            vertical: frozenset(
                field
                for field in ManagedField
                if field.value.startswith(f"{vertical.value}.")
            )
            for vertical in ManagedVertical
        }
    )
)


class ManagedOwnershipEnvelope(BaseModel):
    """Exact normalized fields NCDP owns for one vertical and stable scope."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal["1"] = "1"
    vertical: ManagedVertical
    envelope_version: int = Field(ge=1)
    targets: tuple[NetBoxDeviceIdentity, ...]
    scope: tuple[ManagedScopeIdentity, ...]
    normalized_fields: tuple[ManagedField, ...]

    @model_validator(mode="after")
    def exact_nonoverlapping_scope(self) -> ManagedOwnershipEnvelope:
        if not self.targets or len(self.targets) != len(set(self.targets)):
            raise ValueError("ownership envelope targets must be unique and nonempty")
        scope_keys = tuple((item.kind, item.identity) for item in self.scope)
        if not scope_keys or len(scope_keys) != len(set(scope_keys)):
            raise ValueError("ownership envelope scope must be unique and nonempty")
        if not self.normalized_fields or len(self.normalized_fields) != len(
            set(self.normalized_fields)
        ):
            raise ValueError("ownership envelope fields must be unique and nonempty")
        if not set(self.normalized_fields).issubset(_FIELDS_BY_VERTICAL[self.vertical]):
            raise ValueError("ownership envelope fields do not match its vertical")
        return self


class AcceptanceEvidenceReference(BaseModel):
    """Durable identity and digest proving one accepted managed-state baseline."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    identity: NonEmptyString
    digest: Sha256Digest


class AcceptedManagedStateRef(BaseModel):
    """Versioned D0 reference for exactly one managed ownership envelope."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal["1"] = "1"
    ownership_envelope: ManagedOwnershipEnvelope
    normalized_accepted_desired_state_digest: Sha256Digest
    source_git_commit: GitCommit
    acceptance_evidence: AcceptanceEvidenceReference


def _validate_catalogs() -> None:
    if set(AUTOMATION_PROFILE_CATALOG) != set(AutomationProfileID):
        raise RuntimeError("automation profile catalog is incomplete")
    if set(CML_REALIZATION_PROFILE_CATALOG) != set(CmlRealizationProfileID):
        raise RuntimeError("CML realization profile catalog is incomplete")
    if any(
        key is not value.profile_id for key, value in AUTOMATION_PROFILE_CATALOG.items()
    ):
        raise RuntimeError("automation profile catalog key mismatch")
    if any(
        key is not value.profile_id
        for key, value in CML_REALIZATION_PROFILE_CATALOG.items()
    ):
        raise RuntimeError("CML realization profile catalog key mismatch")
    properties = tuple(item.property for item in AUTHORITY_ASSIGNMENTS)
    if set(properties) != set(AuthorityProperty) or len(properties) != len(
        set(properties)
    ):
        raise RuntimeError("every managed property must have exactly one authority")


_validate_catalogs()
