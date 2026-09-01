#!/usr/bin/env python3
"""Read-only reconciliation of the exact four LIVE managed-state chains."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from network_change_delivery.managed_state import build_current_git_managed_d1
from network_change_delivery.managed_state_live import (
    EXACT_VERTICALS,
    collect_live_managed_state,
)
from network_change_delivery.managed_state_store import (
    D0ObservationOutcome,
    ManagedStateComparison,
    ManagedStateStore,
    compare_d0_to_d1,
    reconcile_d0_to_observation,
)
from network_change_delivery.openbao_profiled_config import (
    OpenBaoProfiledDeviceConfigurator,
)
from network_change_delivery.secrets import OpenBaoSecretProvider


def verification_exit_status(
    reconciliations: tuple[ManagedStateComparison, ...],
) -> int:
    """Return shell status for complete D0/O verification results."""
    return (
        int(
            not all(
                item.outcome is D0ObservationOutcome.IN_SYNC for item in reconciliations
            )
        )
        * 2
    )


def build_verification_payload(
    reconciliations: tuple[ManagedStateComparison, ...],
    proposals: tuple[ManagedStateComparison, ...],
) -> dict[str, object]:
    """Build the bounded, secret-free verifier output."""
    return {
        "device_writes": 0,
        "verticals": [
            {
                "vertical": vertical.value,
                "d0_observation": reconciliation.model_dump(mode="json"),
                "d0_d1": proposal.model_dump(mode="json"),
            }
            for vertical, reconciliation, proposal in zip(
                EXACT_VERTICALS, reconciliations, proposals, strict=True
            )
        ],
    }


def main() -> int:
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--store-root",
        type=Path,
        default=os.environ.get("NCDP_MANAGED_STATE_STORE_ROOT"),
        required="NCDP_MANAGED_STATE_STORE_ROOT" not in os.environ,
    )
    arguments = parser.parse_args()
    checkout = Path(__file__).resolve().parents[2]
    store = ManagedStateStore(arguments.store_root, checkout=checkout, create=False)
    resolutions = tuple(store.resolve_current_d0(item) for item in EXACT_VERTICALS)
    issuer = OpenBaoProfiledDeviceConfigurator.from_environment()
    session = issuer.issue_bounded_session()
    try:
        observed = collect_live_managed_state(
            OpenBaoSecretProvider(
                url=os.environ.get("NCDP_OPENBAO_URL"),
                role_id=session.role_id,
                secret_id=session.secret_id,
            )
        )
    finally:
        issuer.retire_bounded_session(session)
    reconciliations = tuple(
        reconcile_d0_to_observation(resolution, state)
        for resolution, state in zip(resolutions, observed.states(), strict=True)
    )
    proposals = tuple(
        compare_d0_to_d1(resolution, desired)
        for resolution, desired in zip(
            resolutions, build_current_git_managed_d1(), strict=True
        )
    )
    print(
        json.dumps(
            build_verification_payload(reconciliations, proposals),
            sort_keys=True,
            indent=2,
        )
    )
    return verification_exit_status(reconciliations)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError) as error:
        print(f"LIVE D0 verification failed: {error}", file=sys.stderr)
        raise SystemExit(2) from None
