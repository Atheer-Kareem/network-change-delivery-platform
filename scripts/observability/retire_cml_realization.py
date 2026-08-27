#!/usr/bin/env python3
"""Retire observability authorization before an operator twin is destroyed."""

from __future__ import annotations

import sys
from pathlib import Path

from network_change_delivery.observability_realization import retire_admission
from network_change_delivery.observability_service import (
    ObservabilityServiceError,
    invalidate_readiness,
    wait_targets_retired,
)
from network_change_delivery.observability_targets import (
    ObservabilityTargetError,
    TargetGenerationState,
    publish_generation,
    read_generation,
)

STATE_ROOT = Path("/Users/netdevops/.local/state/ncdp/observability")


def main() -> int:
    if len(sys.argv) != 1:
        print("observability retirement arguments rejected", file=sys.stderr)
        return 2
    try:
        invalidate_readiness(STATE_ROOT / "runtime/observability-ready.json")
        retire_admission(STATE_ROOT)
        generation = publish_generation(STATE_ROOT, state=TargetGenerationState.RETIRED)
        if read_generation(STATE_ROOT) != generation:
            raise ObservabilityTargetError("observability retirement rejected")
        wait_targets_retired()
    except (ObservabilityServiceError, ObservabilityTargetError, OSError, ValueError):
        print("observability realization retirement failed", file=sys.stderr)
        return 2
    print(f"observability realization retired: generation={generation.digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
