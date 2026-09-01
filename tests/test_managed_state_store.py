import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from network_change_delivery.managed_state import (
    RoutedUnderlayManagedStateSnapshot,
    build_current_git_managed_d1,
)
from network_change_delivery.managed_state_store import (
    D0ObservationOutcome,
    D0ProposalOutcome,
    ManagedStateAcceptanceMode,
    ManagedStateAcceptanceRecord,
    ManagedStateResolutionStatus,
    ManagedStateStore,
    ManagedStateStoreError,
    PostWriteOutcome,
    build_acceptance_evidence,
    compare_d0_to_d1,
    compare_postwrite_to_d1,
    derive_accepted_managed_state_ref,
    reconcile_d0_to_observation,
)

COMMIT = "b6726ec995091f1d1bf92f29b0c03c24f0f6a3a3"
OBSERVATION = "sha256:" + "1" * 64
NOW = datetime(2026, 9, 1, tzinfo=UTC)


def private_root(tmp_path: Path) -> Path:
    root = tmp_path / "managed-state"
    root.mkdir(mode=0o700, parents=True)
    root.chmod(0o700)
    return root


def initial_evidence(state=None):
    state = state or build_current_git_managed_d1()[0]
    return build_acceptance_evidence(
        acceptance_mode=ManagedStateAcceptanceMode.INITIAL_ADOPTION,
        accepted_at=NOW,
        canonical_state=state,
        source_git_commit=COMMIT,
        source_observation_evidence_digest=OBSERVATION,
    )


def changed_underlay(state: RoutedUnderlayManagedStateSnapshot):
    interface = state.payload.interfaces[0]
    payload = state.payload.model_copy(
        update={
            "interfaces": (
                interface.model_copy(update={"ipv4_addresses": ("10.6.12.1/30",)}),
                *state.payload.interfaces[1:],
            )
        }
    )
    unsigned = state.model_construct(
        schema_version=state.schema_version,
        vertical=state.vertical,
        ownership_envelope=state.ownership_envelope,
        payload=payload,
        digest="sha256:" + "0" * 64,
    )
    payload = unsigned.model_dump(mode="json")
    payload["digest"] = unsigned.calculated_digest()
    return RoutedUnderlayManagedStateSnapshot.model_validate(payload)


def test_store_is_explicit_private_outside_checkout_and_has_no_pointer(
    tmp_path: Path,
) -> None:
    checkout = Path(__file__).parents[1]
    root = private_root(tmp_path)
    store = ManagedStateStore(root, checkout=checkout)
    assert (
        store.resolve_current_d0("routed_underlay").status
        is ManagedStateResolutionStatus.UNINITIALIZED
    )
    assert not tuple(root.rglob("current.json"))
    assert {item.name for item in (root / "accepted").iterdir()} == {
        "routed_underlay",
        "ospf",
        "vlan",
        "acl",
    }


def test_store_rejects_relative_inside_checkout_wrong_mode_and_symlink(
    tmp_path: Path,
) -> None:
    checkout = Path(__file__).parents[1]
    with pytest.raises(ManagedStateStoreError):
        ManagedStateStore(Path("relative"), checkout=checkout)
    inside = checkout / ".managed-state-test-invalid"
    inside.mkdir(mode=0o700)
    try:
        with pytest.raises(ManagedStateStoreError):
            ManagedStateStore(inside, checkout=checkout)
    finally:
        inside.rmdir()
    wrong = tmp_path / "wrong"
    wrong.mkdir(mode=0o755)
    wrong.chmod(0o755)
    with pytest.raises(ManagedStateStoreError):
        ManagedStateStore(wrong, checkout=checkout)
    target = private_root(tmp_path / "target")
    link = tmp_path / "link"
    link.symlink_to(target, target_is_directory=True)
    with pytest.raises(ManagedStateStoreError):
        ManagedStateStore(link, checkout=checkout)


def test_generation_one_persists_and_resolves_derived_ref(tmp_path: Path) -> None:
    store = ManagedStateStore(
        private_root(tmp_path), checkout=Path(__file__).parents[1]
    )
    evidence = initial_evidence()
    record = store.persist_acceptance(evidence)
    resolution = store.resolve_current_d0("routed_underlay")
    assert record.generation == 1
    assert resolution.head == record
    assert resolution.accepted_state_ref == derive_accepted_managed_state_ref(evidence)
    assert resolution.accepted_state_ref.acceptance_evidence.identity == (
        f"managed-state:acceptance:routed_underlay:{evidence.digest}"
    )
    assert record == store.persist_acceptance(evidence)


def test_postwrite_record_must_extend_exact_head(tmp_path: Path) -> None:
    store = ManagedStateStore(
        private_root(tmp_path), checkout=Path(__file__).parents[1]
    )
    first = store.persist_acceptance(initial_evidence())
    next_evidence = build_acceptance_evidence(
        acceptance_mode=ManagedStateAcceptanceMode.POST_WRITE_VALIDATED,
        accepted_at=NOW,
        canonical_state=first.evidence.canonical_state,
        source_git_commit=COMMIT,
        source_observation_evidence_digest="sha256:" + "2" * 64,
        previous_accepted_state=first.accepted_state_ref,
    )
    second = store.persist_acceptance(next_evidence)
    assert second.generation == 2
    assert second.previous_record_digest == first.digest
    assert store.resolve_current_d0("routed_underlay").records == (first, second)


def test_acceptance_modes_and_source_commit_fail_closed() -> None:
    state = build_current_git_managed_d1()[0]
    with pytest.raises(ValidationError):
        build_acceptance_evidence(
            acceptance_mode=ManagedStateAcceptanceMode.POST_WRITE_VALIDATED,
            accepted_at=NOW,
            canonical_state=state,
            source_git_commit=COMMIT,
            source_observation_evidence_digest=OBSERVATION,
        )
    with pytest.raises(ValidationError):
        build_acceptance_evidence(
            acceptance_mode=ManagedStateAcceptanceMode.INITIAL_ADOPTION,
            accepted_at=NOW,
            canonical_state=state,
            source_git_commit="main",
            source_observation_evidence_digest=OBSERVATION,
        )
    assert set(ManagedStateAcceptanceMode) == {
        ManagedStateAcceptanceMode.INITIAL_ADOPTION,
        ManagedStateAcceptanceMode.POST_WRITE_VALIDATED,
    }


def test_corruption_unexpected_filename_and_broken_chain_fail_closed(
    tmp_path: Path,
) -> None:
    root = private_root(tmp_path)
    checkout = Path(__file__).parents[1]
    store = ManagedStateStore(root, checkout=checkout)
    record = store.persist_acceptance(initial_evidence())
    path = root / "accepted" / "routed_underlay" / f"{record.digest[7:]}.json"
    payload = json.loads(path.read_bytes())
    payload["generation"] = 2
    path.write_text(json.dumps(payload, separators=(",", ":"), sort_keys=True))
    path.chmod(0o600)
    with pytest.raises(ManagedStateStoreError):
        store.resolve_current_d0("routed_underlay")

    root2 = private_root(tmp_path / "second")
    store2 = ManagedStateStore(root2, checkout=checkout)
    unexpected = root2 / "accepted" / "ospf" / "current.json"
    unexpected.write_text("{}")
    unexpected.chmod(0o600)
    with pytest.raises(ManagedStateStoreError):
        store2.resolve_current_d0("ospf")


def test_private_record_permissions_are_enforced(tmp_path: Path) -> None:
    root = private_root(tmp_path)
    store = ManagedStateStore(root, checkout=Path(__file__).parents[1])
    record = store.persist_acceptance(initial_evidence())
    path = root / "accepted" / "routed_underlay" / f"{record.digest[7:]}.json"
    path.chmod(0o644)
    with pytest.raises(ManagedStateStoreError):
        store.resolve_current_d0("routed_underlay")


def test_two_generation_one_heads_fail_closed(tmp_path: Path) -> None:
    checkout = Path(__file__).parents[1]
    root = private_root(tmp_path / "first")
    other_root = private_root(tmp_path / "other")
    store = ManagedStateStore(root, checkout=checkout)
    other = ManagedStateStore(other_root, checkout=checkout)
    store.persist_acceptance(initial_evidence())
    competing = build_acceptance_evidence(
        acceptance_mode=ManagedStateAcceptanceMode.INITIAL_ADOPTION,
        accepted_at=NOW,
        canonical_state=build_current_git_managed_d1()[0],
        source_git_commit=COMMIT,
        source_observation_evidence_digest="sha256:" + "9" * 64,
    )
    other_record = other.persist_acceptance(competing)
    source = (
        other_root / "accepted" / "routed_underlay" / f"{other_record.digest[7:]}.json"
    )
    destination = (
        root / "accepted" / "routed_underlay" / f"{other_record.digest[7:]}.json"
    )
    destination.write_bytes(source.read_bytes())
    destination.chmod(0o600)
    with pytest.raises(ManagedStateStoreError):
        store.resolve_current_d0("routed_underlay")


def test_d0_observation_proposal_and_postwrite_relations(tmp_path: Path) -> None:
    state = build_current_git_managed_d1()[0]
    changed = changed_underlay(state)
    store = ManagedStateStore(
        private_root(tmp_path), checkout=Path(__file__).parents[1]
    )
    store.persist_acceptance(initial_evidence(state))
    d0 = store.resolve_current_d0("routed_underlay")
    assert (
        reconcile_d0_to_observation(d0, state).outcome is D0ObservationOutcome.IN_SYNC
    )
    drift = reconcile_d0_to_observation(d0, changed)
    assert drift.outcome is D0ObservationOutcome.DRIFT_DETECTED
    assert drift.device_writes == 0
    assert compare_d0_to_d1(d0, state).outcome is D0ProposalOutcome.NO_CHANGE
    assert compare_d0_to_d1(d0, changed).outcome is D0ProposalOutcome.CHANGE_PROPOSED
    assert compare_postwrite_to_d1(state, state).outcome is PostWriteOutcome.CONVERGED
    assert (
        compare_postwrite_to_d1(changed, state).outcome
        is PostWriteOutcome.POST_VALIDATION_FAILED
    )


def test_vertical_or_envelope_mismatch_fails_comparison(tmp_path: Path) -> None:
    states = build_current_git_managed_d1()
    store = ManagedStateStore(
        private_root(tmp_path), checkout=Path(__file__).parents[1]
    )
    store.persist_acceptance(initial_evidence(states[0]))
    d0 = store.resolve_current_d0("routed_underlay")
    with pytest.raises(ManagedStateStoreError):
        reconcile_d0_to_observation(d0, states[1])
    tampered = d0.model_copy(
        update={
            "records": (
                d0.head.model_copy(
                    update={"previous_record_digest": "sha256:" + "0" * 64}
                ),
            )
        }
    )
    with pytest.raises(ValidationError):
        reconcile_d0_to_observation(tampered, states[0])


def test_record_model_rejects_ref_and_digest_tampering(tmp_path: Path) -> None:
    store = ManagedStateStore(
        private_root(tmp_path), checkout=Path(__file__).parents[1]
    )
    record = store.persist_acceptance(initial_evidence())
    with pytest.raises(ValidationError):
        ManagedStateAcceptanceRecord.model_validate(
            record.model_copy(update={"digest": "sha256:" + "f" * 64}).model_dump()
        )
    wrong_ref = record.accepted_state_ref.model_copy(
        update={"source_git_commit": "0" * 40}
    )
    with pytest.raises(ValidationError):
        ManagedStateAcceptanceRecord.model_validate(
            record.model_copy(update={"accepted_state_ref": wrong_ref}).model_dump()
        )
