#!/usr/bin/env python3
"""Observe and assure the B4-1 routed-underlay proposal without writes."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime

from network_change_delivery.ansible_adapter import ProviderError
from network_change_delivery.assurance import AssuranceProviderError
from network_change_delivery.inventory import InventoryError
from network_change_delivery.profile_inventory import NetBoxProfileInventoryProvider
from network_change_delivery.profile_read_only_adapter import ProfileReadOnlyAdapter
from network_change_delivery.profiled_live_host_trust import (
    DEFAULT_PROFILED_LIVE_TRUST_ROOT,
    KNOWN_HOSTS_NAME,
    ProfiledLiveHostTrustError,
    validate_profiled_live_host_trust,
)
from network_change_delivery.reference_data_plane import (
    NetBoxReferenceDataPlaneProvider,
)
from network_change_delivery.routed_underlay import (
    RoutedUnderlayIntent,
    RoutedUnderlayProposalEvidence,
    assure_routed_underlay_candidate,
    build_routed_underlay_desired_state,
    build_routed_underlay_ownership_envelope,
    collect_routed_underlay_observation,
    render_routed_underlay,
    routed_underlay_delta,
    source_allocation_digest,
)
from network_change_delivery.secrets import OpenBaoSecretProvider, SecretError


def verify() -> RoutedUnderlayProposalEvidence:
    """Build one fresh secret-free O/D1/render/Batfish evidence record."""
    validate_profiled_live_host_trust()
    allocation = NetBoxReferenceDataPlaneProvider().resolve_reference_allocation()
    population = NetBoxProfileInventoryProvider().resolve_profiled_population()
    intent = RoutedUnderlayIntent.from_reference_allocation(allocation)
    desired = build_routed_underlay_desired_state(intent)
    adapter = ProfileReadOnlyAdapter(
        known_hosts=DEFAULT_PROFILED_LIVE_TRUST_ROOT / KNOWN_HOSTS_NAME
    )
    observation = collect_routed_underlay_observation(
        intent,
        population,
        OpenBaoSecretProvider(),
        adapter,
    )
    rendered = render_routed_underlay(intent, observation, desired, population)
    batfish = assure_routed_underlay_candidate(intent, desired, population)
    proposal = RoutedUnderlayProposalEvidence(
        generated_at=datetime.now(UTC),
        intent=intent,
        ownership_envelope=build_routed_underlay_ownership_envelope(intent),
        current_observation=observation,
        proposed_desired_state=desired,
        delta=routed_underlay_delta(observation, desired),
        rendered_targets=rendered,
        batfish=batfish,
    )
    result = {
        "schema_version": proposal.schema_version,
        "source_allocation_digest": source_allocation_digest(allocation),
        "observed_at": proposal.current_observation.observed_at.isoformat(),
        "current_observation": [
            state.model_dump(mode="json")
            for state in proposal.current_observation.interfaces
        ],
        "proposed_d1_digest": proposal.proposed_desired_state.digest,
        "proposed_d1": [
            state.model_dump(mode="json")
            for state in proposal.proposed_desired_state.interfaces
        ],
        "delta": [item.model_dump(mode="json") for item in proposal.delta],
        "rendered_targets": [
            item.model_dump(mode="json") for item in proposal.rendered_targets
        ],
        "batfish": proposal.batfish.model_dump(mode="json"),
        "device_writes": 0,
    }
    print(json.dumps(result, sort_keys=True, indent=2))
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
        print(f"routed-underlay verification failed: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
