#!/usr/bin/env python3
"""Recover one exact retained local ephemeral staging run."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from run_ephemeral_cml_staging import LocalOperations

from network_change_delivery.ephemeral_staging import StagingEvidence


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-directory", required=True, type=Path)
    parser.add_argument("--evidence", required=True, type=Path)
    args = parser.parse_args()
    evidence = StagingEvidence(
        schema_version="2",
        staging_run_id=args.run_id,
        orchestrator="operator-recovery",
    )
    try:
        LocalOperations(args.run_id, args.run_directory).recover(evidence)
    except Exception as error:
        evidence.cleanup_failure = str(error)
        evidence.overall_result = "failed"
    payload = json.dumps(evidence.safe_dict(), indent=2, sort_keys=True) + "\n"
    args.evidence.write_text(payload, encoding="utf-8")
    args.evidence.chmod(0o600)
    print(payload, end="")
    if evidence.overall_result != "passed":
        print(
            "staging recovery failed; retained state was not retired", file=sys.stderr
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
