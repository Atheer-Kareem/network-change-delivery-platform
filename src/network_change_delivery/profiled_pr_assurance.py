"""Offline Batfish assurance for the exact profiled pull-request candidate."""

from __future__ import annotations

import os
from contextlib import suppress
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

from network_change_delivery.architecture_contracts import Sha256Digest
from network_change_delivery.assurance import AssuranceOutcome, InvariantResult
from network_change_delivery.audit import canonical_json_bytes, sha256_identity
from network_change_delivery.ospf_triangle import (
    OspfTriangleAssuranceProvider,
    OspfTriangleIntent,
    assure_ospf_triangle_candidate,
    build_ospf_desired_state,
)
from network_change_delivery.reference_data_plane import (
    ACCEPTED_REFERENCE_ALLOCATION_DIGEST,
    build_accepted_reference_allocation_evidence,
    reference_allocation_digest,
)
from network_change_delivery.reference_routing_identity import (
    ACCEPTED_ROUTING_IDENTITY_ALLOCATION_DIGEST,
    build_accepted_routing_identity_evidence,
    routing_identity_allocation_digest,
)
from network_change_delivery.routed_underlay import (
    ACCEPTED_ROUTED_UNDERLAY_D1_DIGEST,
    RoutedUnderlayIntent,
    build_routed_underlay_desired_state,
)

PROFILED_ARCHITECTURE_IDENTITY = "profiled-four-device"
PROFILED_CANDIDATE_NODES = (
    "access-sw-01",
    "core-02",
    "edge-junos-01",
    "transit-ios-01",
)
ROUTED_UNDERLAY_D1_DIGEST = ACCEPTED_ROUTED_UNDERLAY_D1_DIGEST
OSPF_D1_DIGEST = (
    "sha256:55f5718089228eb4e9f3badebca036135461c10b3c4312184462b5468d463182"
)
PROFILED_COMBINED_CANDIDATE_DIGEST = (
    "sha256:7e7f67500084682194be69d81d94f58d8ae0f6c8722e5de3b3a6c25521e5c269"
)
PROFILED_COMBINED_INVARIANTS = (
    "candidate_exact_parse_files",
    "candidate_parse_status",
    "candidate_exact_nodes",
    "candidate_initialization_issues",
    "exact_routed_interface_prefixes",
    "exact_two_participants_per_link",
    "access_switch_excluded",
    "management_addresses_excluded",
    "exact_direct_neighbor_flows",
    "ospf_exact_routers",
    "ospf_access_excluded",
    "ospf_exact_interfaces",
    "ospf_management_excluded",
    "ospf_exact_adjacencies",
    "ospf_remote_routes",
    "ospf_remote_reachability",
)


class ProfiledService(StrEnum):
    """Closed service stack evaluated by current profiled PR assurance."""

    ROUTED_UNDERLAY = "routed_underlay"
    OSPF = "ospf"


class ProfiledServiceSubject(BaseModel):
    """One independently normalized service subject in the PR candidate."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    service: ProfiledService
    digest: Sha256Digest


class ProfiledPrAssuranceEvidence(BaseModel):
    """Deterministic secret-free evidence for one exact profiled candidate."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal["2"] = "2"
    architecture_identity: Literal["profiled-four-device"] = (
        PROFILED_ARCHITECTURE_IDENTITY
    )
    active_service_stack: tuple[ProfiledService, ...]
    accepted_source_allocation_digest: Sha256Digest
    accepted_routing_identity_digest: Sha256Digest
    service_subjects: tuple[ProfiledServiceSubject, ...]
    candidate_snapshot_digest: Sha256Digest
    candidate_nodes: tuple[str, ...]
    pybatfish_version: str
    batfish_version: str
    ospf_router_count: int
    ospf_adjacency_count: int
    invariants: tuple[InvariantResult, ...]
    outcome: AssuranceOutcome
    digest: Sha256Digest

    def digest_input(self) -> bytes:
        return canonical_json_bytes(self.model_dump(mode="json", exclude={"digest"}))

    def calculated_digest(self) -> str:
        return sha256_identity(self.digest_input())

    def verify_digest(self) -> bool:
        return self.digest == self.calculated_digest()

    @model_validator(mode="after")
    def exact_profiled_contract(self) -> ProfiledPrAssuranceEvidence:
        invariant_names = tuple(item.name for item in self.invariants)
        expected_outcome = (
            AssuranceOutcome.PASSED
            if self.invariants and all(item.passed for item in self.invariants)
            else AssuranceOutcome.FAILED
        )
        if (
            self.active_service_stack
            != (ProfiledService.ROUTED_UNDERLAY, ProfiledService.OSPF)
            or self.accepted_source_allocation_digest
            != ACCEPTED_REFERENCE_ALLOCATION_DIGEST
            or self.accepted_routing_identity_digest
            != ACCEPTED_ROUTING_IDENTITY_ALLOCATION_DIGEST
            or self.service_subjects
            != (
                ProfiledServiceSubject(
                    service=ProfiledService.ROUTED_UNDERLAY,
                    digest=ROUTED_UNDERLAY_D1_DIGEST,
                ),
                ProfiledServiceSubject(
                    service=ProfiledService.OSPF,
                    digest=OSPF_D1_DIGEST,
                ),
            )
            or self.candidate_snapshot_digest != PROFILED_COMBINED_CANDIDATE_DIGEST
            or self.candidate_nodes != PROFILED_CANDIDATE_NODES
            or self.ospf_router_count != 3
            or self.ospf_adjacency_count != 3
            or invariant_names != PROFILED_COMBINED_INVARIANTS
            or self.outcome is not expected_outcome
        ):
            raise ValueError("profiled PR assurance evidence is inconsistent")
        if not self.verify_digest():
            raise ValueError("profiled PR assurance evidence digest is invalid")
        return self


def assure_profiled_pr_candidate(
    provider: OspfTriangleAssuranceProvider | None = None,
) -> ProfiledPrAssuranceEvidence:
    """Evaluate the current explicit profiled service stack entirely offline."""
    allocation = build_accepted_reference_allocation_evidence()
    allocation_digest = reference_allocation_digest(allocation)
    routing = build_accepted_routing_identity_evidence()
    routing_digest = routing_identity_allocation_digest(routing)
    underlay_intent = RoutedUnderlayIntent.from_reference_allocation(allocation)
    underlay_desired = build_routed_underlay_desired_state(underlay_intent)
    ospf_intent = OspfTriangleIntent.from_allocations(allocation, routing)
    ospf_desired = build_ospf_desired_state(ospf_intent)
    if underlay_desired.digest != ROUTED_UNDERLAY_D1_DIGEST:
        raise ValueError("profiled PR routed-underlay D1 digest changed")
    if ospf_desired.digest != OSPF_D1_DIGEST:
        raise ValueError("profiled PR OSPF D1 digest changed")
    combined = assure_ospf_triangle_candidate(
        underlay_intent,
        underlay_desired,
        ospf_intent,
        ospf_desired,
        provider,
    )
    if combined.candidate_snapshot_digest != PROFILED_COMBINED_CANDIDATE_DIGEST:
        raise ValueError("profiled PR candidate snapshot digest changed")
    unsigned = ProfiledPrAssuranceEvidence.model_construct(
        schema_version="2",
        architecture_identity=PROFILED_ARCHITECTURE_IDENTITY,
        active_service_stack=(ProfiledService.ROUTED_UNDERLAY, ProfiledService.OSPF),
        accepted_source_allocation_digest=allocation_digest,
        accepted_routing_identity_digest=routing_digest,
        service_subjects=(
            ProfiledServiceSubject(
                service=ProfiledService.ROUTED_UNDERLAY,
                digest=underlay_desired.digest,
            ),
            ProfiledServiceSubject(
                service=ProfiledService.OSPF,
                digest=ospf_desired.digest,
            ),
        ),
        candidate_snapshot_digest=combined.candidate_snapshot_digest,
        candidate_nodes=combined.candidate_nodes,
        pybatfish_version=combined.pybatfish_version,
        batfish_version=combined.batfish_version,
        ospf_router_count=combined.ospf_router_count,
        ospf_adjacency_count=combined.ospf_adjacency_count,
        invariants=combined.invariants,
        outcome=combined.outcome,
        digest="sha256:" + "0" * 64,
    )
    return ProfiledPrAssuranceEvidence.model_validate(
        unsigned.model_copy(update={"digest": unsigned.calculated_digest()})
    )


def write_profiled_pr_evidence(
    evidence: ProfiledPrAssuranceEvidence, path: Path
) -> None:
    """Atomically write one private regular evidence file."""
    if not evidence.verify_digest() or path.is_symlink():
        raise ValueError("profiled PR assurance evidence output is invalid")
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(temporary, flags, 0o600)
        try:
            os.write(descriptor, (evidence.model_dump_json(indent=2) + "\n").encode())
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        temporary.replace(path)
    except OSError as error:
        with suppress(FileNotFoundError):
            temporary.unlink()
        raise ValueError("profiled PR assurance evidence write failed") from error


def load_profiled_pr_evidence(path: Path) -> ProfiledPrAssuranceEvidence:
    """Load and verify one regular typed profiled assurance record."""
    if path.is_symlink() or not path.is_file():
        raise ValueError("profiled PR assurance evidence file is invalid")
    try:
        return ProfiledPrAssuranceEvidence.model_validate_json(path.read_text())
    except (OSError, ValueError):
        raise ValueError("profiled PR assurance evidence file is invalid") from None
