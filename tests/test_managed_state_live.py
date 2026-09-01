from __future__ import annotations

import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from network_change_delivery.architecture_contracts import (
    AcceptedManagedStateRef,
    ManagedVertical,
)
from network_change_delivery.managed_state_live import (
    EXACT_VERTICALS,
    LiveManagedStateError,
    PriorB4ObservationExpectation,
    build_live_inputs,
    build_prior_b4_observation_expectation,
    enforce_pre_adoption_continuity,
    initialize_live_d0_store,
    project_observations,
    validate_adoption_source,
)
from network_change_delivery.managed_state_store import (
    D0ObservationOutcome,
    D0ProposalOutcome,
    ManagedStateAcceptanceMode,
    ManagedStateStore,
)
from network_change_delivery.ospf_triangle import (
    ObservedOspfInterfaceState,
    ObservedOspfRouterState,
    OspfObservation,
)
from network_change_delivery.routed_underlay import (
    ObservedRoutedInterfaceState,
    RoutedUnderlayObservation,
)
from network_change_delivery.security_policy import AclObservation
from network_change_delivery.vlan_service import (
    ObservedAccessPort,
    ObservedAccessVlan,
    ObservedCoreVlanInterface,
    VlanObservation,
)

NOW = datetime(2026, 9, 1, tzinfo=UTC)
SOURCE_COMMIT = "1" * 40
CONTINUITY_DIGESTS = (
    "sha256:6951568295ee0d1c1ff118ce68fd1324ade2a241a3d85049c82c83eaa1543c40",
    "sha256:99f0e0bd53255faf9deb57984edabb7ca49c42bfeb487ee31a3bf3cdee9f4684",
    "sha256:3c244903ad393c1647a2818473400bb14ed4bdcd92ff694d5492bd791af6aa54",
    "sha256:388138ae96e36bb5e5ba3e5c7fdd387986950993598857bdf63040a0391b2dea",
)


def observation_bundle(*, seconds: int = 0, underlay_change: bool = False):
    inputs = build_live_inputs(offline=True)
    expectation = build_prior_b4_observation_expectation()
    # The canonical expectation intentionally retains no raw provider evidence;
    # use the same exact fixture construction via this small test-only mapping.
    endpoints = tuple(
        endpoint for link in inputs.underlay_intent.links for endpoint in link.endpoints
    )
    timestamp = NOW + timedelta(seconds=seconds)
    values = (
        ("10.6.12.9/30" if underlay_change else "10.6.12.1/30", True),
        ("10.6.12.2/30", True),
        (None, False),
        (None, False),
        (None, True),
        (None, False),
    )
    underlay = RoutedUnderlayObservation(
        observed_at=timestamp,
        interfaces=tuple(
            ObservedRoutedInterfaceState(
                device_identity=endpoint.interface.device,
                interface=endpoint.interface,
                exists=True,
                ipv4_addresses=(address,) if address else (),
                admin_enabled=admin,
                operational_status="up" if seconds else "down",
            )
            for endpoint, (address, admin) in zip(endpoints, values, strict=True)
        ),
    )
    ospf = OspfObservation(
        observed_at=timestamp,
        routers=tuple(
            ObservedOspfRouterState(
                device_identity=router.device_identity,
                logical_name=router.logical_name,
                automation_profile_id=router.automation_profile_id,
                process_present=False,
                interfaces=tuple(
                    ObservedOspfInterfaceState(
                        interface=item.interface, participating=False
                    )
                    for item in router.interfaces
                ),
            )
            for router in inputs.ospf_intent.routers
        ),
    )
    gateways = inputs.vlan_intent.gateways
    ports = (inputs.vlan_intent.trunk, *inputs.vlan_intent.access_ports)
    vlan = VlanObservation(
        observed_at=timestamp,
        core_parent=ObservedCoreVlanInterface(
            interface=gateways[0].parent_interface,
            exists=True,
            admin_enabled=False,
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
                native_vlan=2 if seconds else 1,
            )
            for item in ports
        ),
    )
    acl = AclObservation(observed_at=timestamp, policy_present=False)
    bundle = project_observations(inputs, underlay, ospf, vlan, acl)
    assert build_prior_b4_observation_expectation().digests() == expectation.digests()
    return bundle


def test_exact_prior_b4_continuity_expectations_are_not_d0() -> None:
    expectation = build_prior_b4_observation_expectation()
    assert isinstance(expectation, PriorB4ObservationExpectation)
    assert not isinstance(expectation, AcceptedManagedStateRef)
    assert expectation.digests() == CONTINUITY_DIGESTS
    enforce_pre_adoption_continuity(expectation, observation_bundle())


def test_continuity_ignores_unowned_fields_but_rejects_owned_change() -> None:
    expectation = build_prior_b4_observation_expectation()
    enforce_pre_adoption_continuity(expectation, observation_bundle(seconds=1))
    with pytest.raises(LiveManagedStateError, match="PRE_ADOPTION_CHANGE_DETECTED"):
        enforce_pre_adoption_continuity(
            expectation, observation_bundle(underlay_change=True)
        )


def test_successful_initialization_is_two_pass_and_exact_four(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "network_change_delivery.managed_state_live.validate_adoption_source",
        lambda *_args: None,
    )
    calls = []

    def collect():
        calls.append(object())
        return observation_bundle(seconds=len(calls))

    final = tmp_path / "managed-state"
    result = initialize_live_d0_store(
        final_root=final,
        checkout=Path.cwd(),
        source_git_commit=SOURCE_COMMIT,
        collect_first=collect,
        collect_second=collect,
        accepted_at=NOW,
    )
    assert len(calls) == 2 and calls[0] is not calls[1]
    assert result.device_writes == 0
    assert tuple(item.vertical for item in result.verticals) == EXACT_VERTICALS
    assert all(
        item.d0_observation.outcome is D0ObservationOutcome.IN_SYNC
        for item in result.verticals
    )
    assert all(
        item.d0_d1.outcome is D0ProposalOutcome.CHANGE_PROPOSED
        for item in result.verticals
    )
    store = ManagedStateStore(final, checkout=Path.cwd(), create=False)
    for vertical in ManagedVertical:
        resolution = store.resolve_current_d0(vertical)
        assert len(resolution.records) == 1
        assert resolution.head.generation == 1
        assert (
            resolution.head.evidence.acceptance_mode
            is ManagedStateAcceptanceMode.INITIAL_ADOPTION
        )
        assert resolution.head.evidence.previous_accepted_state is None
        assert resolution.head.evidence.postwrite_convergence is None
    assert not tuple(final.rglob("current.json"))


def test_existing_root_fails_before_collection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "network_change_delivery.managed_state_live.validate_adoption_source",
        lambda *_args: None,
    )
    final = tmp_path / "managed-state"
    final.mkdir()
    called = False

    def collect():
        nonlocal called
        called = True
        return observation_bundle()

    with pytest.raises(LiveManagedStateError, match="must be absent"):
        initialize_live_d0_store(
            final_root=final,
            checkout=Path.cwd(),
            source_git_commit=SOURCE_COMMIT,
            collect_first=collect,
            collect_second=collect,
        )
    assert not called


def test_continuity_or_second_read_failure_leaves_no_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "network_change_delivery.managed_state_live.validate_adoption_source",
        lambda *_args: None,
    )
    continuity_final = tmp_path / "continuity"
    with pytest.raises(LiveManagedStateError, match="PRE_ADOPTION"):
        initialize_live_d0_store(
            final_root=continuity_final,
            checkout=Path.cwd(),
            source_git_commit=SOURCE_COMMIT,
            collect_first=lambda: observation_bundle(underlay_change=True),
            collect_second=observation_bundle,
        )
    assert not continuity_final.exists()

    drift_final = tmp_path / "drift"
    with pytest.raises(LiveManagedStateError, match="drifted during adoption"):
        initialize_live_d0_store(
            final_root=drift_final,
            checkout=Path.cwd(),
            source_git_commit=SOURCE_COMMIT,
            collect_first=observation_bundle,
            collect_second=lambda: observation_bundle(seconds=1, underlay_change=True),
        )
    assert not drift_final.exists()
    assert not tuple(tmp_path.glob("drift.init-*"))


def test_cached_first_observation_cannot_pass_as_second(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "network_change_delivery.managed_state_live.validate_adoption_source",
        lambda *_args: None,
    )
    cached = observation_bundle()
    final = tmp_path / "cached"
    with pytest.raises(LiveManagedStateError, match="not independent"):
        initialize_live_d0_store(
            final_root=final,
            checkout=Path.cwd(),
            source_git_commit=SOURCE_COMMIT,
            collect_first=lambda: cached,
            collect_second=lambda: cached,
        )
    assert not final.exists()
    assert not tuple(tmp_path.glob("cached.init-*"))


def test_source_validation_rejects_wrong_head_and_dirty_tree(tmp_path: Path) -> None:
    checkout = tmp_path / "repo"
    checkout.mkdir()
    subprocess.run(("git", "init", "-q"), cwd=checkout, check=True)
    subprocess.run(
        ("git", "config", "user.email", "test@example.invalid"),
        cwd=checkout,
        check=True,
    )
    subprocess.run(("git", "config", "user.name", "test"), cwd=checkout, check=True)
    (checkout / "tracked").write_text("one\n")
    subprocess.run(("git", "add", "tracked"), cwd=checkout, check=True)
    subprocess.run(("git", "commit", "-qm", "initial"), cwd=checkout, check=True)
    head = subprocess.run(
        ("git", "rev-parse", "HEAD"),
        cwd=checkout,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    with pytest.raises(LiveManagedStateError, match="does not match"):
        validate_adoption_source(checkout, "0" * 40)
    validate_adoption_source(checkout, head)
    (checkout / "tracked").write_text("dirty\n")
    with pytest.raises(LiveManagedStateError, match="not clean"):
        validate_adoption_source(checkout, head)
