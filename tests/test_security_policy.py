"""Contracts for the exact B4-4 USERS-to-SERVERS ACL vertical."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from network_change_delivery.ansible_adapter import ProviderError
from network_change_delivery.architecture_contracts import (
    ManagedField,
    ManagedScopeKind,
)
from network_change_delivery.ospf_triangle import (
    OspfTriangleIntent,
    build_ospf_desired_state,
)
from network_change_delivery.reference_data_plane import (
    ACCEPTED_REFERENCE_ALLOCATION_DIGEST,
    build_accepted_reference_allocation_evidence,
)
from network_change_delivery.reference_routing_identity import (
    build_accepted_routing_identity_evidence,
)
from network_change_delivery.reference_vlan_service import (
    ACCEPTED_VLAN_SERVICE_ALLOCATION_DIGEST,
    build_accepted_vlan_service_evidence,
)
from network_change_delivery.routed_underlay import (
    RoutedUnderlayIntent,
    build_routed_underlay_desired_state,
)
from network_change_delivery.security_policy import (
    ACCEPTED_ACL_CANDIDATE_DIGEST,
    ACCEPTED_ACL_D1_DIGEST,
    ACL_NAME,
    ACL_POLICY_IDENTITY,
    AclAction,
    AclDirection,
    AclObservation,
    AclProtocol,
    AclSecurityIntent,
    ObservedAclAttachment,
    build_acl_candidate_snapshot,
    build_acl_desired_state,
    build_acl_ownership_envelope,
    parse_acl_observation,
    render_acl_changes,
)
from network_change_delivery.vlan_service import (
    ACCEPTED_VLAN_CANDIDATE_DIGEST,
    ACCEPTED_VLAN_D1_DIGEST,
    VlanServiceIntent,
    build_vlan_candidate_snapshot,
    build_vlan_desired_state,
)


def service_inputs():
    allocation = build_accepted_reference_allocation_evidence()
    routing = build_accepted_routing_identity_evidence()
    vlan = build_accepted_vlan_service_evidence()
    underlay_intent = RoutedUnderlayIntent.from_reference_allocation(allocation)
    underlay_desired = build_routed_underlay_desired_state(underlay_intent)
    ospf_intent = OspfTriangleIntent.from_allocations(allocation, routing)
    ospf_desired = build_ospf_desired_state(ospf_intent)
    vlan_intent = VlanServiceIntent.from_allocations(allocation, vlan)
    vlan_desired = build_vlan_desired_state(vlan_intent)
    acl_intent = AclSecurityIntent.from_allocations(allocation, vlan, vlan_desired)
    acl_desired = build_acl_desired_state(acl_intent)
    return (
        underlay_intent,
        underlay_desired,
        ospf_intent,
        ospf_desired,
        vlan_intent,
        vlan_desired,
        acl_intent,
        acl_desired,
    )


def exact_raw() -> tuple[str, str, str, str]:
    return (
        f"ip access-list extended {ACL_NAME}\n",
        (
            f"ip access-list extended {ACL_NAME}\n"
            " 10 permit tcp 10.60.10.0 0.0.0.255 10.60.20.0 0.0.0.255 eq 443\n"
            " 20 deny ip 10.60.10.0 0.0.0.255 10.60.20.0 0.0.0.255\n"
            " 30 permit ip any any\n"
        ),
        (
            "interface GigabitEthernet3.10\n"
            " encapsulation dot1Q 10\n"
            "interface GigabitEthernet3.20\n"
            f" ip access-group {ACL_NAME} out\n"
        ),
        (f"interface GigabitEthernet3.20\n ip access-group {ACL_NAME} out\n"),
    )


def test_exact_intent_desired_and_ownership_scope() -> None:
    *_, intent, desired = service_inputs()
    assert intent.policy_identity == ACL_POLICY_IDENTITY
    assert intent.vlan_d1_dependency == ACCEPTED_VLAN_D1_DIGEST
    assert tuple(item.sequence for item in intent.rules) == (10, 20, 30)
    assert tuple(item.action for item in intent.rules) == (
        AclAction.PERMIT,
        AclAction.DENY,
        AclAction.PERMIT,
    )
    assert tuple(item.protocol for item in intent.rules) == (
        AclProtocol.TCP,
        AclProtocol.IP,
        AclProtocol.IP,
    )
    assert intent.rules[0].destination_port == 443
    assert intent.attachment.interface.interface == "netbox:dcim.interface:22"
    assert intent.attachment.direction is AclDirection.OUT
    assert desired.digest == ACCEPTED_ACL_D1_DIGEST
    assert desired.source_data_plane_digest == ACCEPTED_REFERENCE_ALLOCATION_DIGEST
    assert desired.source_vlan_service_digest == (
        ACCEPTED_VLAN_SERVICE_ALLOCATION_DIGEST
    )
    envelope = build_acl_ownership_envelope(intent)
    assert envelope.targets == ("netbox:dcim.device:1",)
    assert {(item.kind, item.identity) for item in envelope.scope} == {
        (ManagedScopeKind.DEVICE, "netbox:dcim.device:1"),
        (ManagedScopeKind.INTERFACE, "netbox:dcim.interface:22"),
        (ManagedScopeKind.PREFIX, "netbox:ipam.prefix:6"),
        (ManagedScopeKind.PREFIX, "netbox:ipam.prefix:7"),
        (ManagedScopeKind.POLICY, ACL_POLICY_IDENTITY),
    }
    assert set(envelope.normalized_fields) == {
        ManagedField.ACL_RULE_SEMANTICS,
        ManagedField.ACL_RULE_ORDER,
        ManagedField.ACL_ATTACHMENT,
        ManagedField.ACL_DIRECTION,
        ManagedField.ACL_DEFAULT_ACTION,
    }
    assert "assurance-" not in envelope.model_dump_json()


def test_source_authority_tamper_fails_closed() -> None:
    *_, intent, desired = service_inputs()
    with pytest.raises(ValidationError, match="vlan_d1_dependency"):
        AclSecurityIntent.model_validate(
            intent.model_copy(
                update={"vlan_d1_dependency": "sha256:" + "0" * 64}
            ).model_dump(mode="json")
        )
    with pytest.raises(ValidationError, match="digest"):
        type(desired).model_validate(
            desired.model_copy(update={"digest": "sha256:" + "0" * 64}).model_dump(
                mode="json"
            )
        )


def test_absent_and_exact_observation_are_accepted() -> None:
    *_, intent, _desired = service_inputs()
    absent = parse_acl_observation(intent, ("", "", "", ""))
    assert not absent.policy_present
    exact = parse_acl_observation(intent, exact_raw())
    assert exact.policy_present
    assert exact.rules == intent.rules
    assert exact.attachments == (
        ObservedAclAttachment(
            interface_name="GigabitEthernet3.20",
            acl_name=ACL_NAME,
            direction="out",
        ),
    )


@pytest.mark.parametrize(
    "raw",
    [
        (
            "ip access-list extended NCDP-ROGUE\n",
            "",
            "",
            "",
        ),
        (
            f"ip access-list extended {ACL_NAME}\n",
            f"ip access-list extended {ACL_NAME}\n 10 permit ip any any\n",
            "",
            "",
        ),
        (
            f"ip access-list extended {ACL_NAME}\n",
            exact_raw()[1],
            f"interface GigabitEthernet3.20\n ip access-group {ACL_NAME} in\n",
            f"interface GigabitEthernet3.20\n ip access-group {ACL_NAME} in\n",
        ),
        (
            f"ip access-list extended {ACL_NAME}\n",
            exact_raw()[1],
            f"interface GigabitEthernet3.10\n ip access-group {ACL_NAME} out\n",
            f"interface GigabitEthernet3.10\n ip access-group {ACL_NAME} out\n",
        ),
        (
            f"ip access-list extended {ACL_NAME}\n",
            exact_raw()[1],
            "interface GigabitEthernet3.20\n ip access-group OTHER out\n",
            "",
        ),
    ],
)
def test_acl_collision_states_fail_closed(raw: tuple[str, ...]) -> None:
    *_, intent, _desired = service_inputs()
    with pytest.raises(ProviderError, match=r"ACL|acl"):
        parse_acl_observation(intent, raw)


def test_render_absent_to_exact_and_exact_to_noop() -> None:
    *_, intent, desired = service_inputs()
    absent = AclObservation(observed_at=datetime.now(UTC), policy_present=False)
    rendered = render_acl_changes(intent, absent, desired)
    assert not rendered.no_op
    assert rendered.payload == (
        f"ip access-list extended {ACL_NAME}\n"
        " 10 permit tcp 10.60.10.0 0.0.0.255 10.60.20.0 0.0.0.255 eq 443\n"
        " 20 deny ip 10.60.10.0 0.0.0.255 10.60.20.0 0.0.0.255\n"
        " 30 permit ip any any\n"
        "interface GigabitEthernet3.20\n"
        f" ip access-group {ACL_NAME} out\n"
    )
    exact = parse_acl_observation(intent, exact_raw())
    assert render_acl_changes(intent, exact, desired).no_op
    assert render_acl_changes(intent, exact, desired).payload == ""
    assert "no ip access-list" not in rendered.payload

    altered = exact.model_copy(
        update={
            "rules": (
                exact.rules[0].model_copy(update={"action": AclAction.DENY}),
                *exact.rules[1:],
            )
        }
    )
    with pytest.raises(ValueError, match="not exactly"):
        render_acl_changes(intent, altered, desired)


def test_candidate_is_acl_only_delta_and_historical_vlan_is_unchanged() -> None:
    inputs = service_inputs()
    with build_vlan_candidate_snapshot(*inputs[:6]) as baseline:
        assert baseline.manifest.digest == ACCEPTED_VLAN_CANDIDATE_DIGEST
        baseline_files = {
            item.relative_path: (baseline.root / item.relative_path).read_bytes()
            for item in baseline.manifest.files
        }
    with build_acl_candidate_snapshot(*inputs) as secured:
        assert secured.manifest.digest == ACCEPTED_ACL_CANDIDATE_DIGEST
        secured_files = {
            item.relative_path: (secured.root / item.relative_path).read_bytes()
            for item in secured.manifest.files
        }
    changed = {
        name for name in baseline_files if baseline_files[name] != secured_files[name]
    }
    assert changed == {"configs/core-02.cfg"}
    assert secured_files["configs/core-02.cfg"].endswith(
        render_acl_changes(
            inputs[6],
            AclObservation(observed_at=datetime.now(UTC), policy_present=False),
            inputs[7],
        ).payload.encode()
    )
