#!/usr/bin/env python3
"""Build or verify the exact offline profiled PR Batfish assurance record."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from network_change_delivery.assurance import AssuranceOutcome, AssuranceProviderError
from network_change_delivery.profiled_pr_assurance import (
    assure_profiled_pr_candidate,
    load_profiled_pr_evidence,
    write_profiled_pr_evidence,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--verify-only", action="store_true")
    arguments = parser.parse_args()
    try:
        if arguments.verify_only:
            evidence = load_profiled_pr_evidence(arguments.evidence)
        else:
            evidence = assure_profiled_pr_candidate()
            write_profiled_pr_evidence(evidence, arguments.evidence)
    except (AssuranceProviderError, ValueError) as error:
        print(f"profiled PR assurance failed: {error}", file=sys.stderr)
        return 2
    print(
        "profiled PR assurance: "
        f"{evidence.outcome.value}; managed_nodes="
        f"{len(evidence.managed_network_nodes)}; fixtures="
        f"{len(evidence.assurance_fixture_hosts)}; modeled_nodes="
        f"{len(evidence.modeled_nodes)}; "
        f"invariants={sum(item.passed for item in evidence.invariants)}/"
        f"{len(evidence.invariants)}"
    )
    return 0 if evidence.outcome is AssuranceOutcome.PASSED else 2


if __name__ == "__main__":
    raise SystemExit(main())
