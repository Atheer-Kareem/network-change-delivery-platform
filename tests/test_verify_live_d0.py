from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from network_change_delivery.managed_state_live import EXACT_VERTICALS
from network_change_delivery.managed_state_store import (
    D0ObservationOutcome,
    D0ProposalOutcome,
    ManagedStateComparison,
)


def _verifier_module():
    path = Path(__file__).parents[1] / "scripts/managed_state/verify_live_d0.py"
    spec = importlib.util.spec_from_file_location("verify_live_d0", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _comparisons(outcome: D0ObservationOutcome) -> tuple[ManagedStateComparison, ...]:
    from network_change_delivery.managed_state import build_current_git_managed_d1

    states = build_current_git_managed_d1()
    return tuple(
        ManagedStateComparison(
            vertical=state.vertical,
            ownership_envelope=state.ownership_envelope,
            left_digest=state.digest,
            right_digest=state.digest,
            outcome=outcome,
        )
        for state in states
    )


def _proposals() -> tuple[ManagedStateComparison, ...]:
    from network_change_delivery.managed_state import build_current_git_managed_d1

    return tuple(
        ManagedStateComparison(
            vertical=state.vertical,
            ownership_envelope=state.ownership_envelope,
            left_digest=state.digest,
            right_digest=state.digest,
            outcome=D0ProposalOutcome.CHANGE_PROPOSED,
        )
        for state in build_current_git_managed_d1()
    )


def test_change_proposed_does_not_fail_verifier() -> None:
    module = _verifier_module()
    reconciliations = _comparisons(D0ObservationOutcome.IN_SYNC)
    assert module.verification_exit_status(reconciliations) == 0


def test_any_drift_returns_status_two() -> None:
    module = _verifier_module()
    reconciliations = list(_comparisons(D0ObservationOutcome.IN_SYNC))
    reconciliations[2] = reconciliations[2].model_copy(
        update={"outcome": D0ObservationOutcome.DRIFT_DETECTED}
    )
    assert module.verification_exit_status(tuple(reconciliations)) == 2


def test_drift_payload_retains_all_four_vertical_results() -> None:
    module = _verifier_module()
    reconciliations = list(_comparisons(D0ObservationOutcome.IN_SYNC))
    reconciliations[0] = reconciliations[0].model_copy(
        update={"outcome": D0ObservationOutcome.DRIFT_DETECTED}
    )
    payload = module.build_verification_payload(tuple(reconciliations), _proposals())
    assert [item["vertical"] for item in payload["verticals"]] == [
        vertical.value for vertical in EXACT_VERTICALS
    ]
    assert json.loads(json.dumps(payload))["verticals"]
