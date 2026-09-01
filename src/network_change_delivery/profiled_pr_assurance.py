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
    OspfTriangleIntent,
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
from network_change_delivery.reference_vlan_service import (
    ACCEPTED_VLAN_SERVICE_ALLOCATION_DIGEST,
    build_accepted_vlan_service_evidence,
    vlan_service_allocation_digest,
)
from network_change_delivery.routed_underlay import (
    ACCEPTED_ROUTED_UNDERLAY_D1_DIGEST,
    RoutedUnderlayIntent,
    build_routed_underlay_desired_state,
)
from network_change_delivery.security_policy import (
    ACCEPTED_ACL_CANDIDATE_DIGEST,
    ACCEPTED_ACL_D1_DIGEST,
    ACL_COMBINED_INVARIANTS,
    AclSecurityAssuranceProvider,
    AclSecurityFlow,
    AclSecurityIntent,
    assure_acl_security_candidate,
    build_acl_desired_state,
)
from network_change_delivery.vlan_service import (
    ACCEPTED_VLAN_CANDIDATE_DIGEST,
    ACCEPTED_VLAN_D1_DIGEST,
    ASSURANCE_FIXTURE_HOSTS,
    MODELED_NODES,
    VlanServiceIntent,
    build_vlan_desired_state,
)

PROFILED_ARCHITECTURE_IDENTITY = "profiled-four-device"
PROFILED_MANAGED_NETWORK_NODES = (
    "access-sw-01",
    "core-02",
    "edge-junos-01",
    "transit-ios-01",
)
PROFILED_ASSURANCE_FIXTURE_HOSTS = ASSURANCE_FIXTURE_HOSTS
PROFILED_MODELED_NODES = MODELED_NODES
ROUTED_UNDERLAY_D1_DIGEST = ACCEPTED_ROUTED_UNDERLAY_D1_DIGEST
OSPF_D1_DIGEST = (
    "sha256:55f5718089228eb4e9f3badebca036135461c10b3c4312184462b5468d463182"
)
PROFILED_BEHAVIORAL_BASELINE_CANDIDATE_DIGEST = ACCEPTED_VLAN_CANDIDATE_DIGEST
PROFILED_COMBINED_CANDIDATE_DIGEST = ACCEPTED_ACL_CANDIDATE_DIGEST
VLAN_D1_DIGEST = ACCEPTED_VLAN_D1_DIGEST
ACL_D1_DIGEST = ACCEPTED_ACL_D1_DIGEST
PROFILED_COMBINED_INVARIANTS = ACL_COMBINED_INVARIANTS


class ProfiledService(StrEnum):
    """Closed service stack evaluated by current profiled PR assurance."""

    ROUTED_UNDERLAY = "routed_underlay"
    OSPF = "ospf"
    VLAN = "vlan"
    ACL = "acl"


class ProfiledServiceSubject(BaseModel):
    """One independently normalized service subject in the PR candidate."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    service: ProfiledService
    digest: Sha256Digest


class ProfiledPrAssuranceEvidence(BaseModel):
    """Deterministic secret-free evidence for one exact profiled candidate."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal["4"] = "4"
    architecture_identity: Literal["profiled-four-device"] = (
        PROFILED_ARCHITECTURE_IDENTITY
    )
    active_service_stack: tuple[ProfiledService, ...]
    accepted_source_allocation_digest: Sha256Digest
    accepted_routing_identity_digest: Sha256Digest
    accepted_vlan_service_digest: Sha256Digest
    service_subjects: tuple[ProfiledServiceSubject, ...]
    behavioral_baseline_candidate_digest: Sha256Digest
    secured_candidate_digest: Sha256Digest
    candidate_snapshot_digest: Sha256Digest
    managed_network_nodes: tuple[str, ...]
    assurance_fixture_hosts: tuple[str, ...]
    modeled_nodes: tuple[str, ...]
    pybatfish_version: str
    batfish_version: str
    ospf_router_count: int
    ospf_adjacency_count: int
    vlan_count: int
    vlan_gateway_count: int
    infrastructure_layer1_edge_count: int
    assurance_fixture_edge_count: int
    total_layer1_edge_count: int
    acl_policy_count: int
    acl_rule_count: int
    acl_attachment_count: int
    baseline_flows: tuple[AclSecurityFlow, ...]
    secured_flows: tuple[AclSecurityFlow, ...]
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
            != (
                ProfiledService.ROUTED_UNDERLAY,
                ProfiledService.OSPF,
                ProfiledService.VLAN,
                ProfiledService.ACL,
            )
            or self.accepted_source_allocation_digest
            != ACCEPTED_REFERENCE_ALLOCATION_DIGEST
            or self.accepted_routing_identity_digest
            != ACCEPTED_ROUTING_IDENTITY_ALLOCATION_DIGEST
            or self.accepted_vlan_service_digest
            != ACCEPTED_VLAN_SERVICE_ALLOCATION_DIGEST
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
                ProfiledServiceSubject(
                    service=ProfiledService.VLAN,
                    digest=VLAN_D1_DIGEST,
                ),
                ProfiledServiceSubject(
                    service=ProfiledService.ACL,
                    digest=ACL_D1_DIGEST,
                ),
            )
            or self.behavioral_baseline_candidate_digest
            != PROFILED_BEHAVIORAL_BASELINE_CANDIDATE_DIGEST
            or self.secured_candidate_digest != PROFILED_COMBINED_CANDIDATE_DIGEST
            or self.candidate_snapshot_digest != PROFILED_COMBINED_CANDIDATE_DIGEST
            or self.managed_network_nodes != PROFILED_MANAGED_NETWORK_NODES
            or self.assurance_fixture_hosts != PROFILED_ASSURANCE_FIXTURE_HOSTS
            or self.modeled_nodes != PROFILED_MODELED_NODES
            or self.ospf_router_count != 3
            or self.ospf_adjacency_count != 3
            or self.vlan_count != 2
            or self.vlan_gateway_count != 2
            or self.infrastructure_layer1_edge_count != 4
            or self.assurance_fixture_edge_count != 2
            or self.total_layer1_edge_count != 6
            or (self.acl_policy_count, self.acl_rule_count, self.acl_attachment_count)
            != (1, 3, 1)
            or invariant_names != PROFILED_COMBINED_INVARIANTS
            or self.outcome is not expected_outcome
        ):
            raise ValueError("profiled PR assurance evidence is inconsistent")
        if not self.verify_digest():
            raise ValueError("profiled PR assurance evidence digest is invalid")
        return self


def assure_profiled_pr_candidate(
    provider: AclSecurityAssuranceProvider | None = None,
) -> ProfiledPrAssuranceEvidence:
    """Evaluate the current explicit profiled service stack entirely offline."""
    allocation = build_accepted_reference_allocation_evidence()
    allocation_digest = reference_allocation_digest(allocation)
    routing = build_accepted_routing_identity_evidence()
    routing_digest = routing_identity_allocation_digest(routing)
    vlan_allocation = build_accepted_vlan_service_evidence()
    vlan_allocation_digest = vlan_service_allocation_digest(vlan_allocation)
    underlay_intent = RoutedUnderlayIntent.from_reference_allocation(allocation)
    underlay_desired = build_routed_underlay_desired_state(underlay_intent)
    ospf_intent = OspfTriangleIntent.from_allocations(allocation, routing)
    ospf_desired = build_ospf_desired_state(ospf_intent)
    vlan_intent = VlanServiceIntent.from_allocations(allocation, vlan_allocation)
    vlan_desired = build_vlan_desired_state(vlan_intent)
    acl_intent = AclSecurityIntent.from_allocations(
        allocation, vlan_allocation, vlan_desired
    )
    acl_desired = build_acl_desired_state(acl_intent)
    if underlay_desired.digest != ROUTED_UNDERLAY_D1_DIGEST:
        raise ValueError("profiled PR routed-underlay D1 digest changed")
    if ospf_desired.digest != OSPF_D1_DIGEST:
        raise ValueError("profiled PR OSPF D1 digest changed")
    if vlan_desired.digest != VLAN_D1_DIGEST:
        raise ValueError("profiled PR VLAN D1 digest changed")
    if acl_desired.digest != ACL_D1_DIGEST:
        raise ValueError("profiled PR ACL D1 digest changed")
    combined = assure_acl_security_candidate(
        underlay_intent,
        underlay_desired,
        ospf_intent,
        ospf_desired,
        vlan_intent,
        vlan_desired,
        acl_intent,
        acl_desired,
        provider,
    )
    if combined.secured_candidate_digest != PROFILED_COMBINED_CANDIDATE_DIGEST:
        raise ValueError("profiled PR candidate snapshot digest changed")
    unsigned = ProfiledPrAssuranceEvidence.model_construct(
        schema_version="4",
        architecture_identity=PROFILED_ARCHITECTURE_IDENTITY,
        active_service_stack=(
            ProfiledService.ROUTED_UNDERLAY,
            ProfiledService.OSPF,
            ProfiledService.VLAN,
            ProfiledService.ACL,
        ),
        accepted_source_allocation_digest=allocation_digest,
        accepted_routing_identity_digest=routing_digest,
        accepted_vlan_service_digest=vlan_allocation_digest,
        service_subjects=(
            ProfiledServiceSubject(
                service=ProfiledService.ROUTED_UNDERLAY,
                digest=underlay_desired.digest,
            ),
            ProfiledServiceSubject(
                service=ProfiledService.OSPF,
                digest=ospf_desired.digest,
            ),
            ProfiledServiceSubject(
                service=ProfiledService.VLAN,
                digest=vlan_desired.digest,
            ),
            ProfiledServiceSubject(
                service=ProfiledService.ACL,
                digest=acl_desired.digest,
            ),
        ),
        behavioral_baseline_candidate_digest=(
            combined.behavioral_baseline_candidate_digest
        ),
        secured_candidate_digest=combined.secured_candidate_digest,
        candidate_snapshot_digest=combined.secured_candidate_digest,
        managed_network_nodes=combined.managed_network_nodes,
        assurance_fixture_hosts=combined.assurance_fixture_hosts,
        modeled_nodes=combined.modeled_nodes,
        pybatfish_version=combined.pybatfish_version,
        batfish_version=combined.batfish_version,
        ospf_router_count=combined.ospf_router_count,
        ospf_adjacency_count=combined.ospf_adjacency_count,
        vlan_count=combined.vlan_count,
        vlan_gateway_count=combined.vlan_gateway_count,
        infrastructure_layer1_edge_count=combined.infrastructure_layer1_edge_count,
        assurance_fixture_edge_count=combined.assurance_fixture_edge_count,
        total_layer1_edge_count=combined.total_layer1_edge_count,
        acl_policy_count=combined.acl_policy_count,
        acl_rule_count=combined.acl_rule_count,
        acl_attachment_count=combined.acl_attachment_count,
        baseline_flows=combined.baseline_flows,
        secured_flows=combined.secured_flows,
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
