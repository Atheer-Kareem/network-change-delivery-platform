"""Bounded two-pass LIVE initialization for the exact four B5 managed states.

The module composes the accepted B4 read-only collectors.  It contains no
device write surface and no default persistent-store location.
"""

from __future__ import annotations

import ctypes
import errno
import os
import shutil
import subprocess
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, model_validator

from network_change_delivery.architecture_contracts import (
    GitCommit,
    ManagedVertical,
    Sha256Digest,
)
from network_change_delivery.audit import canonical_json_bytes, sha256_identity
from network_change_delivery.managed_state import (
    AclManagedStateSnapshot,
    OspfManagedStateSnapshot,
    RoutedUnderlayManagedStateSnapshot,
    VlanManagedStateSnapshot,
    build_current_git_managed_d1,
    project_acl_observation,
    project_ospf_observation,
    project_routed_underlay_observation,
    project_vlan_observation,
)
from network_change_delivery.managed_state_store import (
    D0ObservationOutcome,
    ManagedStateAcceptanceMode,
    ManagedStateAcceptanceRecord,
    ManagedStateComparison,
    ManagedStateResolution,
    ManagedStateStore,
    build_initial_adoption_evidence,
    compare_d0_to_d1,
    reconcile_d0_to_observation,
)
from network_change_delivery.ospf_triangle import (
    ObservedOspfInterfaceState,
    ObservedOspfRouterState,
    OspfObservation,
    OspfTriangleIntent,
    ProfileOspfReadOnlyAdapter,
    collect_ospf_observation,
)
from network_change_delivery.profile_inventory import (
    NetBoxProfileInventoryProvider,
    ProfiledInventoryPopulation,
)
from network_change_delivery.profile_read_only_adapter import ProfileReadOnlyAdapter
from network_change_delivery.profiled_live_host_trust import (
    DEFAULT_PROFILED_LIVE_TRUST_ROOT,
    KNOWN_HOSTS_NAME,
    validate_profiled_live_host_trust,
)
from network_change_delivery.reference_data_plane import (
    NetBoxReferenceDataPlaneProvider,
    ReferenceDataPlaneAllocation,
    build_accepted_reference_allocation_evidence,
)
from network_change_delivery.reference_routing_identity import (
    NetBoxReferenceRoutingIdentityProvider,
    ReferenceRoutingIdentityAllocation,
    build_accepted_routing_identity_evidence,
)
from network_change_delivery.reference_vlan_service import (
    NetBoxReferenceVlanServiceProvider,
    ReferenceVlanServiceAllocation,
    build_accepted_vlan_service_evidence,
)
from network_change_delivery.routed_underlay import (
    ObservedRoutedInterfaceState,
    RoutedUnderlayIntent,
    RoutedUnderlayObservation,
    collect_routed_underlay_observation,
)
from network_change_delivery.secrets import OpenBaoSecretProvider
from network_change_delivery.security_policy import (
    AclObservation,
    AclSecurityIntent,
    ProfileAclReadOnlyAdapter,
    collect_acl_observation,
)
from network_change_delivery.vlan_service import (
    ObservedAccessPort,
    ObservedAccessVlan,
    ObservedCoreVlanInterface,
    ProfileVlanReadOnlyAdapter,
    VlanObservation,
    VlanServiceIntent,
    build_vlan_desired_state,
    collect_vlan_observation,
)

EXACT_VERTICALS = (
    ManagedVertical.ROUTED_UNDERLAY,
    ManagedVertical.OSPF,
    ManagedVertical.VLAN,
    ManagedVertical.ACL,
)


class LiveManagedStateError(ValueError):
    """The exact LIVE adoption workflow could not safely complete."""


class LiveManagedStateInputs(BaseModel):
    """Resolved factual authorities and exact B4 service subjects."""

    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)
    data_plane: ReferenceDataPlaneAllocation
    routing: ReferenceRoutingIdentityAllocation
    vlan: ReferenceVlanServiceAllocation
    population: ProfiledInventoryPopulation | None
    underlay_intent: RoutedUnderlayIntent
    ospf_intent: OspfTriangleIntent
    vlan_intent: VlanServiceIntent
    acl_intent: AclSecurityIntent


class LiveManagedStateObservationBundle(BaseModel):
    """One secret-free, timestamped read of all four exact verticals."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal["1"] = "1"
    routed_underlay_observation: RoutedUnderlayObservation
    ospf_observation: OspfObservation
    vlan_observation: VlanObservation
    acl_observation: AclObservation
    routed_underlay_observation_evidence_digest: Sha256Digest
    ospf_observation_evidence_digest: Sha256Digest
    vlan_observation_evidence_digest: Sha256Digest
    acl_observation_evidence_digest: Sha256Digest
    routed_underlay_state: RoutedUnderlayManagedStateSnapshot
    ospf_state: OspfManagedStateSnapshot
    vlan_state: VlanManagedStateSnapshot
    acl_state: AclManagedStateSnapshot
    device_writes: Literal[0] = 0

    @model_validator(mode="after")
    def exact_bindings(self) -> LiveManagedStateObservationBundle:
        pairs = (
            (
                self.routed_underlay_observation,
                self.routed_underlay_observation_evidence_digest,
                self.routed_underlay_state,
                ManagedVertical.ROUTED_UNDERLAY,
            ),
            (
                self.ospf_observation,
                self.ospf_observation_evidence_digest,
                self.ospf_state,
                ManagedVertical.OSPF,
            ),
            (
                self.vlan_observation,
                self.vlan_observation_evidence_digest,
                self.vlan_state,
                ManagedVertical.VLAN,
            ),
            (
                self.acl_observation,
                self.acl_observation_evidence_digest,
                self.acl_state,
                ManagedVertical.ACL,
            ),
        )
        for observation, digest, state, vertical in pairs:
            if digest != full_observation_evidence_digest(observation):
                raise ValueError("LIVE observation evidence digest is invalid")
            if state.vertical is not vertical:
                raise ValueError("LIVE projection vertical is invalid")
        inputs = build_live_inputs(offline=True)
        expected_states = (
            project_routed_underlay_observation(
                self.routed_underlay_observation, inputs.underlay_intent
            ),
            project_ospf_observation(self.ospf_observation, inputs.ospf_intent),
            project_vlan_observation(self.vlan_observation, inputs.vlan_intent),
            project_acl_observation(self.acl_observation, inputs.acl_intent),
        )
        if self.states() != expected_states:
            raise ValueError(
                "LIVE canonical projections are detached from observations"
            )
        return self

    def observations(self) -> tuple[object, object, object, object]:
        return (
            self.routed_underlay_observation,
            self.ospf_observation,
            self.vlan_observation,
            self.acl_observation,
        )

    def observation_digests(self) -> tuple[str, str, str, str]:
        return (
            self.routed_underlay_observation_evidence_digest,
            self.ospf_observation_evidence_digest,
            self.vlan_observation_evidence_digest,
            self.acl_observation_evidence_digest,
        )

    def states(
        self,
    ) -> tuple[
        RoutedUnderlayManagedStateSnapshot,
        OspfManagedStateSnapshot,
        VlanManagedStateSnapshot,
        AclManagedStateSnapshot,
    ]:
        return (
            self.routed_underlay_state,
            self.ospf_state,
            self.vlan_state,
            self.acl_state,
        )


class PriorB4ObservationExpectation(BaseModel):
    """Historical continuity gate only; this is neither D0 nor an accepted ref."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal["1"] = "1"
    routed_underlay: RoutedUnderlayManagedStateSnapshot
    ospf: OspfManagedStateSnapshot
    vlan: VlanManagedStateSnapshot
    acl: AclManagedStateSnapshot

    def states(self):
        return (self.routed_underlay, self.ospf, self.vlan, self.acl)

    def digests(self) -> tuple[str, str, str, str]:
        return tuple(item.digest for item in self.states())


class InitialAdoptionVerticalResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    vertical: ManagedVertical
    continuity_expectation_digest: Sha256Digest
    first_observation_evidence_digest: Sha256Digest
    d0_canonical_digest: Sha256Digest
    acceptance_evidence_digest: Sha256Digest
    accepted_state_ref_identity: str
    generation: Literal[1] = 1
    record_digest: Sha256Digest
    second_observation_evidence_digest: Sha256Digest
    second_observation_canonical_digest: Sha256Digest
    d0_observation: ManagedStateComparison
    canonical_d1_digest: Sha256Digest
    d0_d1: ManagedStateComparison
    acceptance_mode: Literal[ManagedStateAcceptanceMode.INITIAL_ADOPTION] = (
        ManagedStateAcceptanceMode.INITIAL_ADOPTION
    )
    device_writes: Literal[0] = 0


class InitialAdoptionRunResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal["1"] = "1"
    source_git_commit: GitCommit
    store_root: str
    store_initialized: Literal[True] = True
    verticals: tuple[
        InitialAdoptionVerticalResult,
        InitialAdoptionVerticalResult,
        InitialAdoptionVerticalResult,
        InitialAdoptionVerticalResult,
    ]
    device_writes: Literal[0] = 0
    digest: Sha256Digest

    @model_validator(mode="after")
    def exact_result(self) -> InitialAdoptionRunResult:
        if tuple(item.vertical for item in self.verticals) != EXACT_VERTICALS or any(
            item.d0_observation.outcome is not D0ObservationOutcome.IN_SYNC
            or item.device_writes != 0
            for item in self.verticals
        ):
            raise ValueError("initial-adoption result verticals are not exact")
        if self.digest != self.calculated_digest():
            raise ValueError("initial-adoption result digest is invalid")
        return self

    def calculated_digest(self) -> str:
        return sha256_identity(
            canonical_json_bytes(self.model_dump(mode="json", exclude={"digest"}))
        )


def full_observation_evidence_digest(observation: BaseModel) -> str:
    """Identify one exact typed read event, including its observation timestamp."""
    return sha256_identity(canonical_json_bytes(observation.model_dump(mode="json")))


def build_live_inputs(*, offline: bool = False) -> LiveManagedStateInputs:
    """Resolve exact authorities; offline mode is reserved for tests/continuity."""
    if offline:
        data_plane = build_accepted_reference_allocation_evidence()
        routing = build_accepted_routing_identity_evidence()
        vlan = build_accepted_vlan_service_evidence()
    else:
        data_plane = NetBoxReferenceDataPlaneProvider().resolve_reference_allocation()
        routing = NetBoxReferenceRoutingIdentityProvider().resolve_routing_identities()
        vlan = NetBoxReferenceVlanServiceProvider().resolve_vlan_service()
    population = (
        None
        if offline
        else NetBoxProfileInventoryProvider().resolve_profiled_population()
    )
    underlay_intent = RoutedUnderlayIntent.from_reference_allocation(data_plane)
    ospf_intent = OspfTriangleIntent.from_allocations(data_plane, routing)
    vlan_intent = VlanServiceIntent.from_allocations(data_plane, vlan)
    acl_intent = AclSecurityIntent.from_allocations(
        data_plane, vlan, build_vlan_desired_state(vlan_intent)
    )
    return LiveManagedStateInputs(
        data_plane=data_plane,
        routing=routing,
        vlan=vlan,
        population=population,
        underlay_intent=underlay_intent,
        ospf_intent=ospf_intent,
        vlan_intent=vlan_intent,
        acl_intent=acl_intent,
    )


def project_observations(
    inputs: LiveManagedStateInputs,
    underlay: RoutedUnderlayObservation,
    ospf: OspfObservation,
    vlan: VlanObservation,
    acl: AclObservation,
) -> LiveManagedStateObservationBundle:
    states = (
        project_routed_underlay_observation(underlay, inputs.underlay_intent),
        project_ospf_observation(ospf, inputs.ospf_intent),
        project_vlan_observation(vlan, inputs.vlan_intent),
        project_acl_observation(acl, inputs.acl_intent),
    )
    digests = tuple(
        full_observation_evidence_digest(item) for item in (underlay, ospf, vlan, acl)
    )
    return LiveManagedStateObservationBundle(
        routed_underlay_observation=underlay,
        ospf_observation=ospf,
        vlan_observation=vlan,
        acl_observation=acl,
        routed_underlay_observation_evidence_digest=digests[0],
        ospf_observation_evidence_digest=digests[1],
        vlan_observation_evidence_digest=digests[2],
        acl_observation_evidence_digest=digests[3],
        routed_underlay_state=states[0],
        ospf_state=states[1],
        vlan_state=states[2],
        acl_state=states[3],
    )


def collect_live_managed_state(
    secret_provider: OpenBaoSecretProvider,
) -> LiveManagedStateObservationBundle:
    """Fresh-read every managed vertical using only the accepted adapters."""
    validate_profiled_live_host_trust()
    inputs = build_live_inputs()
    if inputs.population is None:  # pragma: no cover - excluded by live resolution
        raise LiveManagedStateError("LIVE profiled population is unavailable")
    known_hosts = DEFAULT_PROFILED_LIVE_TRUST_ROOT / KNOWN_HOSTS_NAME
    underlay = collect_routed_underlay_observation(
        inputs.underlay_intent,
        inputs.population,
        secret_provider,
        ProfileReadOnlyAdapter(known_hosts=known_hosts),
    )
    ospf = collect_ospf_observation(
        inputs.ospf_intent,
        inputs.population,
        secret_provider,
        ProfileOspfReadOnlyAdapter(known_hosts=known_hosts),
    )
    vlan = collect_vlan_observation(
        inputs.vlan_intent,
        inputs.population,
        secret_provider,
        ProfileVlanReadOnlyAdapter(known_hosts=known_hosts),
    )
    acl = collect_acl_observation(
        inputs.acl_intent,
        inputs.population,
        secret_provider,
        ProfileAclReadOnlyAdapter(known_hosts=known_hosts),
    )
    return project_observations(inputs, underlay, ospf, vlan, acl)


def build_prior_b4_observation_expectation() -> PriorB4ObservationExpectation:
    """Reconstruct the last accepted B4 managed observations, never accepted D0."""
    inputs = build_live_inputs(offline=True)
    observed_at = datetime(2026, 9, 1, tzinfo=UTC)
    endpoints = tuple(
        endpoint for link in inputs.underlay_intent.links for endpoint in link.endpoints
    )
    underlay_values = (
        ("10.6.12.1/30", True),
        ("10.6.12.2/30", True),
        (None, False),
        (None, False),
        (None, True),
        (None, False),
    )
    underlay = RoutedUnderlayObservation(
        observed_at=observed_at,
        interfaces=tuple(
            ObservedRoutedInterfaceState(
                device_identity=endpoint.interface.device,
                interface=endpoint.interface,
                exists=True,
                ipv4_addresses=(address,) if address else (),
                admin_enabled=admin,
                operational_status=None,
            )
            for endpoint, (address, admin) in zip(
                endpoints, underlay_values, strict=True
            )
        ),
    )
    ospf = OspfObservation(
        observed_at=observed_at,
        routers=tuple(
            ObservedOspfRouterState(
                device_identity=router.device_identity,
                logical_name=router.logical_name,
                automation_profile_id=router.automation_profile_id,
                process_present=False,
                interfaces=tuple(
                    ObservedOspfInterfaceState(
                        interface=interface.interface, participating=False
                    )
                    for interface in router.interfaces
                ),
            )
            for router in inputs.ospf_intent.routers
        ),
    )
    parent = inputs.vlan_intent.gateways[0].parent_interface
    gateways = inputs.vlan_intent.gateways
    access_ports = (
        inputs.vlan_intent.trunk,
        *inputs.vlan_intent.access_ports,
    )
    vlan = VlanObservation(
        observed_at=observed_at,
        core_parent=ObservedCoreVlanInterface(
            interface=parent, exists=True, admin_enabled=False
        ),
        core_subinterfaces=tuple(
            ObservedCoreVlanInterface(interface=item.subinterface, exists=False)
            for item in gateways
        ),
        access_vlans=(
            ObservedAccessVlan(vid=10, present=False),
            ObservedAccessVlan(vid=20, present=False),
        ),
        access_ports=tuple(
            ObservedAccessPort(
                interface=item.interface,
                mode="dynamic auto",
                admin_enabled=True,
                access_vlan=1,
                native_vlan=1,
            )
            for item in access_ports
        ),
    )
    acl = AclObservation(observed_at=observed_at, policy_present=False)
    projected = project_observations(inputs, underlay, ospf, vlan, acl)
    return PriorB4ObservationExpectation(
        routed_underlay=projected.routed_underlay_state,
        ospf=projected.ospf_state,
        vlan=projected.vlan_state,
        acl=projected.acl_state,
    )


def enforce_pre_adoption_continuity(
    expectation: PriorB4ObservationExpectation,
    fresh: LiveManagedStateObservationBundle,
) -> None:
    mismatches = []
    for vertical, expected, observed in zip(
        EXACT_VERTICALS, expectation.states(), fresh.states(), strict=True
    ):
        if expected.digest == observed.digest:
            continue
        paths = _managed_diff_paths(
            expected.payload.model_dump(mode="json"),
            observed.payload.model_dump(mode="json"),
        )
        mismatches.append(f"{vertical.value}[{','.join(paths)}]")
    if mismatches:
        raise LiveManagedStateError(
            "PRE_ADOPTION_CHANGE_DETECTED: " + ", ".join(mismatches)
        )


def _managed_diff_paths(
    left: object, right: object, prefix: str = "payload"
) -> tuple[str, ...]:
    """Return at most sixteen secret-free canonical managed-field paths."""
    differences: list[str] = []

    def visit(first: object, second: object, path: str) -> None:
        if len(differences) >= 16 or first == second:
            return
        if isinstance(first, dict) and isinstance(second, dict):
            for key in sorted(set(first) | set(second)):
                visit(first.get(key), second.get(key), f"{path}.{key}")
            return
        if isinstance(first, list) and isinstance(second, list):
            for index in range(max(len(first), len(second))):
                visit(
                    first[index] if index < len(first) else None,
                    second[index] if index < len(second) else None,
                    f"{path}[{index}]",
                )
            return
        differences.append(path)

    visit(left, right, prefix)
    return tuple(differences) or (prefix,)


def validate_adoption_source(checkout: Path, expected_commit: str) -> None:
    """Require the pushed implementation commit and an exactly clean checkout."""
    if not checkout.is_absolute() or not checkout.is_dir():
        raise LiveManagedStateError("adoption checkout is invalid")
    head = subprocess.run(
        ("git", "rev-parse", "HEAD"),
        cwd=checkout,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    status = subprocess.run(
        ("git", "status", "--porcelain"),
        cwd=checkout,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    if head != expected_commit or len(expected_commit) != 40:
        raise LiveManagedStateError("adoption source commit does not match HEAD")
    if status:
        raise LiveManagedStateError("adoption checkout is not clean")


def _safe_remove_staging(staging: Path, final: Path) -> None:
    expected_prefix = final.name + ".init-"
    if (
        staging.parent != final.parent
        or not staging.name.startswith(expected_prefix)
        or staging.is_symlink()
        or not staging.is_dir()
    ):
        raise LiveManagedStateError("initialization staging path is unsafe")
    shutil.rmtree(staging)


def _atomic_promote_directory(staging: Path, final: Path) -> None:
    """Same-filesystem rename with a kernel-enforced no-replace contract."""
    library = ctypes.CDLL(None, use_errno=True)
    source = os.fsencode(staging)
    destination = os.fsencode(final)
    if hasattr(library, "renamex_np"):
        operation = library.renamex_np
        arguments = (source, destination, 0x00000004)  # RENAME_EXCL
    elif hasattr(library, "renameat2"):
        operation = library.renameat2
        arguments = (-100, source, -100, destination, 1)  # RENAME_NOREPLACE
    else:  # pragma: no cover - supported acceptance platforms expose one API
        raise LiveManagedStateError("atomic no-replace directory rename is unsupported")
    operation.restype = ctypes.c_int
    if operation(*arguments) != 0:
        failure = ctypes.get_errno()
        if failure == errno.EEXIST:
            raise LiveManagedStateError(
                "final managed-state root appeared before promotion"
            )
        raise LiveManagedStateError(
            f"atomic managed-state promotion failed with errno {failure}"
        )


def _build_run_result(
    source_commit: str,
    final_root: Path,
    expectation: PriorB4ObservationExpectation,
    first: LiveManagedStateObservationBundle,
    second: LiveManagedStateObservationBundle,
    records: tuple[ManagedStateAcceptanceRecord, ...],
    resolutions: tuple[ManagedStateResolution, ...],
    d0_o: tuple[ManagedStateComparison, ...],
    d0_d1: tuple[ManagedStateComparison, ...],
) -> InitialAdoptionRunResult:
    verticals = tuple(
        InitialAdoptionVerticalResult(
            vertical=vertical,
            continuity_expectation_digest=expected.digest,
            first_observation_evidence_digest=first_digest,
            d0_canonical_digest=record.evidence.canonical_state_digest,
            acceptance_evidence_digest=record.evidence.digest,
            accepted_state_ref_identity=record.accepted_state_ref.acceptance_evidence.identity,
            record_digest=record.digest,
            second_observation_evidence_digest=second_digest,
            second_observation_canonical_digest=second_state.digest,
            d0_observation=reconciliation,
            canonical_d1_digest=proposal.right_digest,
            d0_d1=proposal,
        )
        for (
            vertical,
            expected,
            first_digest,
            record,
            _resolution,
            second_digest,
            second_state,
            reconciliation,
            proposal,
        ) in zip(
            EXACT_VERTICALS,
            expectation.states(),
            first.observation_digests(),
            records,
            resolutions,
            second.observation_digests(),
            second.states(),
            d0_o,
            d0_d1,
            strict=True,
        )
    )
    unsigned = InitialAdoptionRunResult.model_construct(
        schema_version="1",
        source_git_commit=source_commit,
        store_root=str(final_root),
        store_initialized=True,
        verticals=verticals,
        device_writes=0,
        digest="sha256:" + "0" * 64,
    )
    data = unsigned.model_dump(mode="json")
    data["digest"] = unsigned.calculated_digest()
    return InitialAdoptionRunResult.model_validate(data)


def initialize_live_d0_store(
    *,
    final_root: Path,
    checkout: Path,
    source_git_commit: str,
    collect_first: Callable[[], LiveManagedStateObservationBundle],
    collect_second: Callable[[], LiveManagedStateObservationBundle],
    accepted_at: datetime | None = None,
) -> InitialAdoptionRunResult:
    """Atomically initialize four generation-one chains after two independent reads."""
    if not final_root.is_absolute() or final_root.exists() or final_root.is_symlink():
        raise LiveManagedStateError(
            "final managed-state root must be absent and absolute"
        )
    validate_adoption_source(checkout, source_git_commit)
    if not final_root.parent.is_dir() or final_root.parent.is_symlink():
        raise LiveManagedStateError("managed-state parent must already exist")
    expectation = build_prior_b4_observation_expectation()
    first = collect_first()
    enforce_pre_adoption_continuity(expectation, first)
    staging = final_root.with_name(f"{final_root.name}.init-{uuid4()}")
    promoted = False
    try:
        staging.mkdir(mode=0o700)
        store = ManagedStateStore(staging, checkout=checkout)
        when = accepted_at or datetime.now(UTC)
        records = tuple(
            store.persist_acceptance(
                build_initial_adoption_evidence(
                    accepted_at=when,
                    observed_state=state,
                    source_git_commit=source_git_commit,
                    source_observation_evidence_digest=evidence_digest,
                )
            )
            for state, evidence_digest in zip(
                first.states(), first.observation_digests(), strict=True
            )
        )
        resolutions = tuple(
            store.resolve_current_d0(vertical) for vertical in EXACT_VERTICALS
        )
        if any(
            resolution.head.generation != 1
            or resolution.head.evidence.acceptance_mode
            is not ManagedStateAcceptanceMode.INITIAL_ADOPTION
            or resolution.head.evidence.previous_accepted_state is not None
            or resolution.head.evidence.postwrite_convergence is not None
            for resolution in resolutions
        ):
            raise LiveManagedStateError(
                "temporary D0 chain is not exact generation one"
            )
        second = collect_second()
        observation_pairs = zip(
            first.observations(),
            second.observations(),
            first.observation_digests(),
            second.observation_digests(),
            strict=True,
        )
        cached = first is second
        for (
            first_observation,
            second_observation,
            first_digest,
            second_digest,
        ) in observation_pairs:
            cached = cached or first_observation is second_observation
            cached = cached or first_digest == second_digest
        if cached:
            raise LiveManagedStateError("second LIVE observation was not independent")
        d0_o = tuple(
            reconcile_d0_to_observation(resolution, observed)
            for resolution, observed in zip(resolutions, second.states(), strict=True)
        )
        if any(item.outcome is not D0ObservationOutcome.IN_SYNC for item in d0_o):
            raise LiveManagedStateError(
                "second LIVE observation drifted during adoption"
            )
        if final_root.exists() or final_root.is_symlink():
            raise LiveManagedStateError(
                "final managed-state root appeared before promotion"
            )
        _atomic_promote_directory(staging, final_root)
        promoted = True
        final_store = ManagedStateStore(final_root, checkout=checkout, create=False)
        final_resolutions = tuple(
            final_store.resolve_current_d0(vertical) for vertical in EXACT_VERTICALS
        )
        if tuple(item.head.digest for item in final_resolutions) != tuple(
            item.digest for item in records
        ):
            raise LiveManagedStateError("promoted managed-state records changed")
        desired = build_current_git_managed_d1()
        d0_d1 = tuple(
            compare_d0_to_d1(resolution, proposal)
            for resolution, proposal in zip(final_resolutions, desired, strict=True)
        )
        return _build_run_result(
            source_git_commit,
            final_root,
            expectation,
            first,
            second,
            records,
            final_resolutions,
            d0_o,
            d0_d1,
        )
    except Exception:
        if not promoted and staging.exists():
            _safe_remove_staging(staging, final_root)
        raise
