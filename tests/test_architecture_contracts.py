"""Detour B1 additive architecture-contract tests."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from network_change_delivery.architecture_contracts import (
    AUTHORITY_ASSIGNMENTS,
    AUTOMATION_PROFILE_CATALOG,
    CML_REALIZATION_PROFILE_CATALOG,
    AcceptanceEvidenceReference,
    AcceptedManagedStateRef,
    AuthorityOwner,
    AuthorityProperty,
    AutomationProfile,
    AutomationProfileID,
    Capability,
    CmlRealizationProfileID,
    LegacySSHCompatibility,
    ManagedField,
    ManagedOwnershipEnvelope,
    ManagedScopeIdentity,
    ManagedScopeKind,
    ManagedVertical,
    ManagementBinding,
    ManagementL3Endpoint,
    ManagementPhysicalAttachment,
    ManagementService,
    NetworkOS,
    OperationalRole,
    SSHCompatibilityPolicy,
    StableInterfaceIdentity,
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


def test_iosvl2_management_attachment_and_l3_owner_may_differ() -> None:
    binding = ManagementBinding(
        physical_attachment=ManagementPhysicalAttachment(
            interface=interface(4, 40, "Gi0/0")
        ),
        l3_endpoint=ManagementL3Endpoint(
            interface=interface(4, 41, "Vlan1"),
            ip_address_identity="netbox:ipam.ipaddress:60",
            address="192.0.2.60/24",
            service=ManagementService.SSH,
            port=22,
        ),
    )
    assert binding.physical_attachment.interface.name == "Gi0/0"
    assert binding.l3_endpoint.interface.name == "Vlan1"
    assert (
        binding.physical_attachment.interface.interface
        != binding.l3_endpoint.interface.interface
    )


def test_management_binding_excludes_cml_slot_and_requires_one_device() -> None:
    assert "cml_slot" not in ManagementBinding.model_fields
    assert "cml_slot" not in ManagementPhysicalAttachment.model_fields
    assert "cml_slot" not in ManagementL3Endpoint.model_fields
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


def test_legacy_ssh_is_exact_profile_local_and_pending_b2_acceptance() -> None:
    iosv = get_automation_profile(AutomationProfileID.IOSV_159_3_M12)
    compatibility = iosv.ssh_policy.legacy_compatibility
    assert compatibility is not None
    assert compatibility.scope == "profile_local"
    assert compatibility.profile_id == "iosv_159_3_m12"
    assert compatibility.key_exchange_algorithms == ("diffie-hellman-group14-sha1",)
    assert compatibility.host_key_algorithms == ("ssh-rsa",)
    assert compatibility.acceptance == "requires_b2_real_adapter_acceptance"
    assert iosv.ssh_policy.strict_host_key_verification is True
    with pytest.raises(ValidationError):
        LegacySSHCompatibility.model_validate({"scope": "global"})
    with pytest.raises(ValidationError, match="KEX possibility must be exact"):
        LegacySSHCompatibility(key_exchange_algorithms=())
    with pytest.raises(ValidationError):
        SSHCompatibilityPolicy.model_validate({"strict_host_key_verification": False})


def test_strict_profiles_cannot_inherit_iosv_legacy_compatibility() -> None:
    strict_ids = (
        AutomationProfileID.CAT8000V_IOSXE,
        AutomationProfileID.IOSVL2_2020,
        AutomationProfileID.VJUNOS_ROUTER,
    )
    assert all(
        get_automation_profile(profile_id).ssh_policy.legacy_compatibility is None
        for profile_id in strict_ids
    )
    payload = get_automation_profile(AutomationProfileID.CAT8000V_IOSXE).model_dump(
        mode="json"
    )
    payload["ssh_policy"]["legacy_compatibility"] = LegacySSHCompatibility().model_dump(
        mode="json"
    )
    with pytest.raises(ValidationError, match="only for exact IOSv profile"):
        AutomationProfile.model_validate(payload)


def test_authority_catalog_assigns_every_property_exactly_once() -> None:
    properties = tuple(assignment.property for assignment in AUTHORITY_ASSIGNMENTS)
    assert set(properties) == set(AuthorityProperty)
    assert len(properties) == len(set(properties))
    by_property = {
        assignment.property: assignment.owner for assignment in AUTHORITY_ASSIGNMENTS
    }
    assert by_property[AuthorityProperty.VLAN_VID] is AuthorityOwner.NETBOX
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
        "scope": [{"kind": "policy", "identity": "policy:users-servers"}],
        "normalized_fields": ["whole_running_config"],
    }
    with pytest.raises(ValidationError):
        ManagedOwnershipEnvelope.model_validate(payload)


def test_b1_contracts_are_not_imported_by_current_execution_paths() -> None:
    current_paths = (
        "src/network_change_delivery/models.py",
        "src/network_change_delivery/inventory.py",
        "src/network_change_delivery/ansible_adapter.py",
        "src/network_change_delivery/vendor_adapter.py",
        "src/network_change_delivery/workflow.py",
        "src/network_change_delivery/fleet.py",
        "src/network_change_delivery/buildkite_deployment.py",
    )
    for relative_path in current_paths:
        source = (ROOT / relative_path).read_text(encoding="utf-8")
        assert "architecture_contracts" not in source
