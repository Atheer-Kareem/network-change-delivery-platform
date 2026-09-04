"""Detour B1 additive architecture-contract tests."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from network_change_delivery.architecture_contracts import (
    AUTHORITY_ASSIGNMENTS,
    AUTOMATION_PROFILE_CATALOG,
    CML_REALIZATION_PROFILE_CATALOG,
    TWIN_SHARED_DATA_PLANE_PROPERTIES,
    AcceptanceEvidenceReference,
    AcceptedManagedStateRef,
    AuthorityOwner,
    AuthorityProperty,
    AutomationProfile,
    AutomationProfileID,
    Capability,
    CmlBootstrapProfileID,
    CmlReadinessProfileID,
    CmlRealizationProfileID,
    ManagedField,
    ManagedOwnershipEnvelope,
    ManagedScopeIdentity,
    ManagedScopeKind,
    ManagedVertical,
    ManagementBinding,
    ManagementEndpoint,
    ManagementEndpointPurpose,
    ManagementEndpointSet,
    ManagementL3Endpoint,
    ManagementPhysicalAttachment,
    ManagementService,
    NetworkOS,
    OperationalRole,
    ProvisionalEndpointFixtureName,
    ProvisionalManagedDeviceName,
    SSHCompatibilityPolicy,
    StableInterfaceIdentity,
    TwinSharedDataPlaneProperty,
    get_automation_profile,
    get_cml_realization_profile,
)

ROOT = Path(__file__).parents[1]


def interface(device: int, interface_id: int, name: str) -> StableInterfaceIdentity:
    return StableInterfaceIdentity(
        device=f"netbox:dcim.device:{device}",
        interface=f"netbox:dcim.interface:{interface_id}",
        name=name,
    )


def management_binding(
    *,
    device: int = 4,
    physical_interface_id: int = 40,
    physical_name: str = "Gi0/0",
    l3_interface_id: int = 40,
    l3_name: str = "Gi0/0",
    ip_address_id: int = 60,
    address: str = "192.0.2.60/24",
    service: ManagementService = ManagementService.SSH,
    port: int = 22,
) -> ManagementBinding:
    return ManagementBinding(
        physical_attachment=ManagementPhysicalAttachment(
            interface=interface(device, physical_interface_id, physical_name)
        ),
        l3_endpoint=ManagementL3Endpoint(
            interface=interface(device, l3_interface_id, l3_name),
            ip_address_identity=f"netbox:ipam.ipaddress:{ip_address_id}",
            address=address,
            service=service,
            port=port,
        ),
    )


def test_ios_router_and_switch_share_nos_but_not_profile_or_capabilities() -> None:
    router = get_automation_profile(AutomationProfileID.IOSV_159_3_M12)
    switch = get_automation_profile(AutomationProfileID.IOSVL2_2020)
    assert router.network_os is NetworkOS.IOS
    assert switch.network_os is NetworkOS.IOS
    assert router.profile_id is not switch.profile_id
    assert Capability.LAYER3_ROUTING in router.admitted_capabilities
    assert Capability.LAYER2_SWITCHING not in router.admitted_capabilities
    assert Capability.LAYER2_SWITCHING in switch.admitted_capabilities
    assert Capability.LAYER3_ROUTING not in switch.admitted_capabilities
    assert "role" not in AutomationProfile.model_fields
    assert set(OperationalRole) == {
        OperationalRole.CORE,
        OperationalRole.EDGE,
        OperationalRole.TRANSIT,
        OperationalRole.ACCESS,
    }


def test_profile_and_capability_vocabularies_are_closed_and_complete() -> None:
    assert set(AUTOMATION_PROFILE_CATALOG) == set(AutomationProfileID)
    assert set(CML_REALIZATION_PROFILE_CATALOG) == set(CmlRealizationProfileID)
    assert {profile.value for profile in AutomationProfileID} == {
        "cat8000v_iosxe",
        "iosv_159_3_m12",
        "iosvl2_2020",
        "vjunos_router",
    }
    with pytest.raises(ValueError, match="unknown automation profile"):
        get_automation_profile("dynamic-plugin-profile")
    with pytest.raises(ValueError, match="unknown CML realization profile"):
        get_cml_realization_profile("title-derived-realization")
    payload = get_automation_profile(AutomationProfileID.IOSVL2_2020).model_dump(
        mode="json"
    )
    payload["admitted_capabilities"].append("unknown_capability")
    with pytest.raises(ValidationError):
        AutomationProfile.model_validate(payload)


def test_iosvl2_preferred_management_uses_routed_gi00_for_both_identities() -> None:
    binding = management_binding()
    assert binding.physical_attachment.interface.name == "Gi0/0"
    assert binding.l3_endpoint.interface.name == "Gi0/0"
    assert (
        binding.physical_attachment.interface.interface
        == binding.l3_endpoint.interface.interface
    )


def test_generic_management_binding_still_permits_split_interfaces() -> None:
    binding = management_binding(
        physical_interface_id=50,
        physical_name="Ethernet0",
        l3_interface_id=51,
        l3_name="Loopback0",
    )
    assert binding.physical_attachment.interface.name == "Ethernet0"
    assert binding.l3_endpoint.interface.name == "Loopback0"
    assert (
        binding.physical_attachment.interface.interface
        != binding.l3_endpoint.interface.interface
    )


def test_management_binding_excludes_cml_slot_and_requires_one_device() -> None:
    assert "cml_slot" not in ManagementBinding.model_fields
    assert "cml_slot" not in ManagementPhysicalAttachment.model_fields
    assert "cml_slot" not in ManagementL3Endpoint.model_fields
    assert "cml_slot" not in ManagementEndpoint.model_fields
    assert "cml_slot" not in ManagementEndpointSet.model_fields
    payload = {
        "interface": interface(4, 40, "Gi0/0").model_dump(mode="json"),
        "cml_slot": 0,
    }
    with pytest.raises(ValidationError):
        ManagementPhysicalAttachment.model_validate(payload)
    with pytest.raises(ValidationError, match="one device"):
        ManagementBinding(
            physical_attachment=ManagementPhysicalAttachment(
                interface=interface(4, 40, "Gi0/0")
            ),
            l3_endpoint=ManagementL3Endpoint(
                interface=interface(3, 41, "Vlan1"),
                ip_address_identity="netbox:ipam.ipaddress:60",
                address="192.0.2.60/24",
                service=ManagementService.SSH,
                port=22,
            ),
        )


def test_cml_slots_exist_only_in_realization_contract() -> None:
    switch = get_cml_realization_profile(CmlRealizationProfileID.IOSVL2_2020)
    assert switch.image_definition == "iosvl2-2020"
    assert switch.bootstrap_profile is CmlBootstrapProfileID.IOSVL2_ROUTED_MANAGEMENT
    assert switch.readiness_profile is CmlReadinessProfileID.IOSVL2_ROUTED_SSH
    assert "vlan1" not in switch.bootstrap_profile.value.casefold()
    assert "svi" not in switch.readiness_profile.value.casefold()
    assert (
        Capability.SVI
        in get_automation_profile(AutomationProfileID.IOSVL2_2020).admitted_capabilities
    )
    assert [
        (item.interface_name, item.cml_slot) for item in switch.physical_interface_slots
    ] == [
        ("Gi0/0", 0),
        ("Gi0/1", 1),
        ("Gi0/2", 2),
        ("Gi0/3", 3),
    ]
    assert {
        profile.image_definition for profile in CML_REALIZATION_PROFILE_CATALOG.values()
    } == {
        "cat8000v-17-18-02",
        "iosv-159-3-m12",
        "iosvl2-2020",
        "vjunos-router-23-2r1-15",
    }


def test_live_and_staging_management_endpoints_are_explicit_and_distinct() -> None:
    endpoints = ManagementEndpointSet(
        logical_device="netbox:dcim.device:4",
        automation_profile_id=AutomationProfileID.IOSVL2_2020,
        live=ManagementEndpoint(
            purpose=ManagementEndpointPurpose.LIVE,
            binding=management_binding(
                ip_address_id=24,
                address="192.0.2.200/24",
            ),
        ),
        staging=ManagementEndpoint(
            purpose=ManagementEndpointPurpose.STAGING,
            binding=management_binding(
                ip_address_id=50,
                address="192.0.2.1/24",
            ),
        ),
    )
    assert endpoints.live.purpose is ManagementEndpointPurpose.LIVE
    assert endpoints.staging.purpose is ManagementEndpointPurpose.STAGING
    assert (
        endpoints.live.binding.physical_attachment.interface
        == endpoints.staging.binding.physical_attachment.interface
    )
    assert (
        endpoints.live.binding.l3_endpoint.interface
        == endpoints.staging.binding.l3_endpoint.interface
    )
    assert (
        endpoints.live.binding.l3_endpoint.ip_address_identity
        != endpoints.staging.binding.l3_endpoint.ip_address_identity
    )
    assert (
        endpoints.live.binding.l3_endpoint.address.ip
        != endpoints.staging.binding.l3_endpoint.address.ip
    )
    missing_staging = endpoints.model_dump(mode="json")
    del missing_staging["staging"]
    with pytest.raises(ValidationError):
        ManagementEndpointSet.model_validate(missing_staging)
    extra_endpoint = endpoints.model_dump(mode="json")
    extra_endpoint["alternate"] = extra_endpoint["staging"]
    with pytest.raises(ValidationError):
        ManagementEndpointSet.model_validate(extra_endpoint)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("purpose", "LIVE purpose"),
        ("device", "logical device"),
        ("physical", "physical management interface"),
        ("l3", "L3 management interface"),
        ("ip_identity", "IP identities must differ"),
        ("address", "addresses must differ"),
        ("service", "incompatible with automation profile"),
    ],
)
def test_management_endpoint_set_fails_closed(mutation: str, message: str) -> None:
    live_binding = management_binding(ip_address_id=24, address="192.0.2.24/24")
    staging_binding = management_binding(
        ip_address_id=50,
        address="192.0.2.50/24",
    )
    live_purpose = ManagementEndpointPurpose.LIVE
    if mutation == "purpose":
        live_purpose = ManagementEndpointPurpose.STAGING
    elif mutation == "device":
        staging_binding = management_binding(
            device=5,
            ip_address_id=50,
            address="192.0.2.50/24",
        )
    elif mutation == "physical":
        staging_binding = management_binding(
            physical_interface_id=41,
            physical_name="Gi0/1",
            ip_address_id=50,
            address="192.0.2.50/24",
        )
    elif mutation == "l3":
        staging_binding = management_binding(
            l3_interface_id=41,
            l3_name="Loopback0",
            ip_address_id=50,
            address="192.0.2.50/24",
        )
    elif mutation == "ip_identity":
        staging_binding = management_binding(
            ip_address_id=24,
            address="192.0.2.50/24",
        )
    elif mutation == "address":
        staging_binding = management_binding(
            ip_address_id=50,
            address="192.0.2.24/25",
        )
    elif mutation == "service":
        staging_binding = management_binding(
            ip_address_id=50,
            address="192.0.2.50/24",
            service=ManagementService.NETCONF,
            port=830,
        )
    with pytest.raises(ValidationError, match=message):
        ManagementEndpointSet(
            logical_device="netbox:dcim.device:4",
            automation_profile_id=AutomationProfileID.IOSVL2_2020,
            live=ManagementEndpoint(
                purpose=live_purpose,
                binding=live_binding,
            ),
            staging=ManagementEndpoint(
                purpose=ManagementEndpointPurpose.STAGING,
                binding=staging_binding,
            ),
        )


def test_all_profiles_require_strict_ssh_without_algorithm_relaxation() -> None:
    for profile_id in AutomationProfileID:
        policy = get_automation_profile(profile_id).ssh_policy
        assert policy.strict_host_key_verification is True
        assert policy.model_dump(mode="json") == {"strict_host_key_verification": True}
    with pytest.raises(ValidationError):
        SSHCompatibilityPolicy.model_validate({"strict_host_key_verification": False})
    for unsupported_field in (
        "legacy_compatibility",
        "key_exchange_algorithms",
        "host_key_algorithms",
    ):
        with pytest.raises(ValidationError):
            SSHCompatibilityPolicy.model_validate(
                {
                    "strict_host_key_verification": True,
                    unsupported_field: ["unsupported-relaxation"],
                }
            )


def test_authority_catalog_assigns_every_property_exactly_once() -> None:
    properties = tuple(assignment.property for assignment in AUTHORITY_ASSIGNMENTS)
    assert set(properties) == set(AuthorityProperty)
    assert len(properties) == len(set(properties))
    by_property = {
        assignment.property: assignment.owner for assignment in AUTHORITY_ASSIGNMENTS
    }
    assert by_property[AuthorityProperty.VLAN_VID] is AuthorityOwner.NETBOX
    assert by_property[AuthorityProperty.DEVICE_TYPE_METADATA] is AuthorityOwner.NETBOX
    assert (
        by_property[AuthorityProperty.VLAN_DEPLOYMENT_ATTACHMENT] is AuthorityOwner.GIT
    )
    assert by_property[AuthorityProperty.PROFILE_BEHAVIOR_CATALOG] is AuthorityOwner.GIT
    assert (
        by_property[AuthorityProperty.DISPOSABLE_REALIZATION_IDENTITY_LIFECYCLE]
        is AuthorityOwner.TERRAFORM_CML_STATE
    )


def test_accepted_managed_state_ref_binds_one_exact_envelope() -> None:
    envelope = ManagedOwnershipEnvelope(
        vertical=ManagedVertical.VLAN,
        envelope_version=1,
        targets=("netbox:dcim.device:4",),
        scope=(
            ManagedScopeIdentity(
                kind=ManagedScopeKind.INTERFACE,
                identity="netbox:dcim.interface:42",
            ),
            ManagedScopeIdentity(
                kind=ManagedScopeKind.VLAN,
                identity="netbox:ipam.vlan:10",
            ),
        ),
        normalized_fields=(
            ManagedField.VLAN_PRESENCE,
            ManagedField.VLAN_PORT_MODE,
            ManagedField.VLAN_ACCESS_VLAN,
        ),
    )
    accepted = AcceptedManagedStateRef(
        ownership_envelope=envelope,
        normalized_accepted_desired_state_digest="sha256:" + "a" * 64,
        source_git_commit="b" * 40,
        acceptance_evidence=AcceptanceEvidenceReference(
            identity="audit:change-record:11111111-1111-4111-8111-111111111111",
            digest="sha256:" + "c" * 64,
        ),
    )
    loaded = AcceptedManagedStateRef.model_validate_json(accepted.model_dump_json())
    assert loaded == accepted
    assert loaded.ownership_envelope.vertical is ManagedVertical.VLAN
    assert loaded.ownership_envelope.envelope_version == 1
    assert loaded.ownership_envelope.targets == ("netbox:dcim.device:4",)
    assert loaded.normalized_accepted_desired_state_digest == "sha256:" + "a" * 64
    assert loaded.source_git_commit == "b" * 40
    assert loaded.acceptance_evidence.digest == "sha256:" + "c" * 64


@pytest.mark.parametrize(
    ("kind", "identity"),
    [
        (ManagedScopeKind.DEVICE, "netbox:dcim.device:1"),
        (ManagedScopeKind.INTERFACE, "netbox:dcim.interface:2"),
        (ManagedScopeKind.IP_ADDRESS, "netbox:ipam.ipaddress:23"),
        (ManagedScopeKind.VLAN, "netbox:ipam.vlan:10"),
        (ManagedScopeKind.PREFIX, "netbox:ipam.prefix:20"),
        (ManagedScopeKind.POLICY, "git:policy:users-to-servers"),
    ],
)
def test_managed_scope_identity_accepts_only_closed_namespaces(
    kind: ManagedScopeKind, identity: str
) -> None:
    scope = ManagedScopeIdentity(kind=kind, identity=identity)
    assert scope.identity == identity


@pytest.mark.parametrize(
    ("kind", "identity"),
    [
        (ManagedScopeKind.VLAN, "netbox:dcim.device:1"),
        (ManagedScopeKind.INTERFACE, "arbitrary-interface"),
        (ManagedScopeKind.IP_ADDRESS, "netbox:ipam.prefix:8"),
        (ManagedScopeKind.DEVICE, "netbox:dcim.device:0"),
        (ManagedScopeKind.VLAN, "netbox:ipam.vlan:-1"),
        (ManagedScopeKind.PREFIX, "netbox:ipam.prefix:0"),
        (ManagedScopeKind.POLICY, "policy:users-to-servers"),
        (ManagedScopeKind.POLICY, "git:policy:Unsafe Policy"),
    ],
)
def test_managed_scope_identity_namespace_mismatch_fails_closed(
    kind: ManagedScopeKind, identity: str
) -> None:
    with pytest.raises(ValidationError):
        ManagedScopeIdentity(kind=kind, identity=identity)


def test_stable_logical_names_and_endpoint_fixtures_are_realization_neutral() -> None:
    managed_names = {name.value for name in ProvisionalManagedDeviceName}
    endpoint_names = {name.value for name in ProvisionalEndpointFixtureName}
    assert managed_names == {
        "core-02",
        "edge-junos-01",
        "transit-ios-01",
        "access-sw-01",
    }
    assert endpoint_names == {"users-host-01", "servers-host-01"}
    assert managed_names.isdisjoint(endpoint_names)
    assert all("staging" not in name for name in managed_names | endpoint_names)


def test_live_and_staging_share_every_logical_data_plane_property() -> None:
    assert {
        TwinSharedDataPlaneProperty.ROUTED_LINK_PREFIXES,
        TwinSharedDataPlaneProperty.DATA_PLANE_INTERFACE_ADDRESSES,
        TwinSharedDataPlaneProperty.LOOPBACK_ROUTER_ID_ADDRESSES,
        TwinSharedDataPlaneProperty.VLAN_IDS,
        TwinSharedDataPlaneProperty.VLAN_PREFIXES,
        TwinSharedDataPlaneProperty.GATEWAY_ADDRESSES,
        TwinSharedDataPlaneProperty.ENDPOINT_ADDRESSES,
        TwinSharedDataPlaneProperty.OSPF_INTENT,
        TwinSharedDataPlaneProperty.ACL_SECURITY_INTENT,
    } == TWIN_SHARED_DATA_PLANE_PROPERTIES


def test_ownership_envelope_rejects_wrong_vertical_and_whole_config_field() -> None:
    with pytest.raises(ValidationError, match="do not match"):
        ManagedOwnershipEnvelope(
            vertical=ManagedVertical.OSPF,
            envelope_version=1,
            targets=("netbox:dcim.device:1",),
            scope=(
                ManagedScopeIdentity(
                    kind=ManagedScopeKind.DEVICE,
                    identity="netbox:dcim.device:1",
                ),
            ),
            normalized_fields=(ManagedField.VLAN_PRESENCE,),
        )
    payload = {
        "vertical": "acl",
        "envelope_version": 1,
        "targets": ["netbox:dcim.device:1"],
        "scope": [{"kind": "policy", "identity": "git:policy:users-to-servers"}],
        "normalized_fields": ["whole_running_config"],
    }
    with pytest.raises(ValidationError):
        ManagedOwnershipEnvelope.model_validate(payload)


def test_b1_contracts_are_not_imported_by_current_execution_paths() -> None:
    current_paths = (
        "src/network_change_delivery/models.py",
        "src/network_change_delivery/inventory.py",
        "src/network_change_delivery/ansible_adapter.py",
        "src/network_change_delivery/workflow.py",
        "src/network_change_delivery/fleet.py",
        "src/network_change_delivery/buildkite_deployment.py",
    )
    for relative_path in current_paths:
        source = (ROOT / relative_path).read_text(encoding="utf-8")
        assert "architecture_contracts" not in source
