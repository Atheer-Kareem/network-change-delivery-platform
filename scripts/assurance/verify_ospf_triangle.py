#!/usr/bin/env python3
"""Observe and assure the B4-2 OSPF proposal without device writes."""

from __future__ import annotations

import json
import sys

from network_change_delivery.ansible_adapter import ProviderError
from network_change_delivery.assurance import AssuranceOutcome, AssuranceProviderError
from network_change_delivery.inventory import InventoryError
from network_change_delivery.ospf_triangle import (
    OspfTriangleIntent,
    OspfTriangleProposalEvidence,
    ProfileOspfReadOnlyAdapter,
    assure_ospf_triangle_candidate,
    build_ospf_desired_state,
    build_ospf_proposal_evidence,
    collect_ospf_observation,
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
from network_change_delivery.routed_underlay import (
    RoutedUnderlayIntent,
    build_routed_underlay_desired_state,
)
from network_change_delivery.secrets import OpenBaoSecretProvider, SecretError


def _require_passed_assurance(proposal: OspfTriangleProposalEvidence) -> None:
    """Defense in depth: a non-passing candidate cannot verify successfully."""
    if proposal.combined_assurance.outcome is not AssuranceOutcome.PASSED:
        raise AssuranceProviderError("OSPF triangle candidate assurance did not pass")


def verify():
    """Build fresh secret-free O/D1/render/combined-assurance evidence."""
    validate_profiled_live_host_trust()
    underlay = NetBoxReferenceDataPlaneProvider().resolve_reference_allocation()
    routing = NetBoxReferenceRoutingIdentityProvider().resolve_routing_identities()
    population = NetBoxProfileInventoryProvider().resolve_profiled_population()
    intent = OspfTriangleIntent.from_allocations(underlay, routing)
    desired = build_ospf_desired_state(intent)
    observation = collect_ospf_observation(
        intent,
        population,
        OpenBaoSecretProvider(),
        ProfileOspfReadOnlyAdapter(
            known_hosts=DEFAULT_PROFILED_LIVE_TRUST_ROOT / KNOWN_HOSTS_NAME
        ),
    )
    underlay_intent = RoutedUnderlayIntent.from_reference_allocation(underlay)
    assurance = assure_ospf_triangle_candidate(
        underlay_intent,
        build_routed_underlay_desired_state(underlay_intent),
        intent,
        desired,
    )
    proposal = build_ospf_proposal_evidence(intent, observation, desired, assurance)
    _require_passed_assurance(proposal)
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
        print(f"OSPF triangle verification failed: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
