#!/usr/bin/env python3
"""Observe and assure the B4-4 ACL proposal without device writes."""

from __future__ import annotations

import json
import sys

from network_change_delivery.ansible_adapter import ProviderError
from network_change_delivery.assurance import AssuranceOutcome, AssuranceProviderError
from network_change_delivery.inventory import InventoryError
from network_change_delivery.ospf_triangle import (
    OspfTriangleIntent,
    build_ospf_desired_state,
)
from network_change_delivery.profile_inventory import NetBoxProfileInventoryProvider
from network_change_delivery.profiled_live_host_trust import (
    DEFAULT_PROFILED_LIVE_TRUST_ROOT,
    KNOWN_HOSTS_NAME,
    ProfiledLiveHostTrustError,
    validate_profiled_live_host_trust,
)
from network_change_delivery.reference_data_plane import (
    NetBoxReferenceDataPlaneProvider,
)
from network_change_delivery.reference_routing_identity import (
    NetBoxReferenceRoutingIdentityProvider,
)
from network_change_delivery.reference_vlan_service import (
    NetBoxReferenceVlanServiceProvider,
)
from network_change_delivery.routed_underlay import (
    RoutedUnderlayIntent,
    build_routed_underlay_desired_state,
)
from network_change_delivery.secrets import OpenBaoSecretProvider, SecretError
from network_change_delivery.security_policy import (
    AclSecurityIntent,
    ProfileAclReadOnlyAdapter,
    assure_acl_security_candidate,
    build_acl_desired_state,
    build_acl_proposal_evidence,
    collect_acl_observation,
)
from network_change_delivery.vlan_service import (
    VlanServiceIntent,
    build_vlan_desired_state,
)


def verify():
    validate_profiled_live_host_trust()
    data_plane = NetBoxReferenceDataPlaneProvider().resolve_reference_allocation()
    routing = NetBoxReferenceRoutingIdentityProvider().resolve_routing_identities()
    vlan_facts = NetBoxReferenceVlanServiceProvider().resolve_vlan_service()
    population = NetBoxProfileInventoryProvider().resolve_profiled_population()
    underlay_intent = RoutedUnderlayIntent.from_reference_allocation(data_plane)
    underlay_desired = build_routed_underlay_desired_state(underlay_intent)
    ospf_intent = OspfTriangleIntent.from_allocations(data_plane, routing)
    ospf_desired = build_ospf_desired_state(ospf_intent)
    vlan_intent = VlanServiceIntent.from_allocations(data_plane, vlan_facts)
    vlan_desired = build_vlan_desired_state(vlan_intent)
    acl_intent = AclSecurityIntent.from_allocations(
        data_plane, vlan_facts, vlan_desired
    )
    acl_desired = build_acl_desired_state(acl_intent)
    observation = collect_acl_observation(
        acl_intent,
        population,
        OpenBaoSecretProvider(),
        ProfileAclReadOnlyAdapter(
            known_hosts=DEFAULT_PROFILED_LIVE_TRUST_ROOT / KNOWN_HOSTS_NAME
        ),
    )
    assurance = assure_acl_security_candidate(
        underlay_intent,
        underlay_desired,
        ospf_intent,
        ospf_desired,
        vlan_intent,
        vlan_desired,
        acl_intent,
        acl_desired,
    )
    proposal = build_acl_proposal_evidence(
        acl_intent, observation, acl_desired, assurance
    )
    if proposal.combined_assurance.outcome is not AssuranceOutcome.PASSED:
        raise AssuranceProviderError("ACL security candidate assurance did not pass")
    print(json.dumps(proposal.model_dump(mode="json"), sort_keys=True, indent=2))
    return proposal


def main() -> int:
    try:
        verify()
    except (
        AssuranceProviderError,
        InventoryError,
        ProfiledLiveHostTrustError,
        ProviderError,
        SecretError,
        ValueError,
    ) as error:
        print(f"ACL security verification failed: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
