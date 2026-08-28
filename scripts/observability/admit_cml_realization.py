#!/usr/bin/env python3
"""Admit the exact persistent live CML realization without probing devices."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from network_change_delivery.observability_realization import (
    LIVE_LAB_ID,
    CmlRealizationAuthority,
    ObservabilityRealizationError,
    publish_admission,
)

STATE_ROOT = Path("/Users/netdevops/.local/state/ncdp/observability")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lab-id", required=True, choices=(LIVE_LAB_ID,))
    parser.add_argument("--core-id", required=True)
    parser.add_argument("--junos-id", required=True)
    arguments = parser.parse_args()
    required = {
        "address": os.environ.get("NCDP_OBSERVABILITY_CML_ADDRESS"),
        "certificate": os.environ.get("NCDP_OBSERVABILITY_CML_CACERT"),
        "username": os.environ.get("NCDP_OBSERVABILITY_CML_USERNAME"),
        "password": os.environ.get("NCDP_OBSERVABILITY_CML_PASSWORD"),
    }
    if any(not value for value in required.values()):
        print("observability CML authority unavailable", file=sys.stderr)
        return 2
    try:
        authority = CmlRealizationAuthority(**required)  # type: ignore[arg-type]
        try:
            admission = authority.admit(
                arguments.lab_id,
                {
                    "netbox:dcim.device:1": arguments.core_id,
                    "netbox:dcim.device:2": arguments.junos_id,
                },
            )
        finally:
            authority.close()
        publish_admission(STATE_ROOT, admission)
    except (ObservabilityRealizationError, OSError, ValueError):
        print("observability CML realization admission failed", file=sys.stderr)
        return 2
    print(
        f"observability realization admitted: lab={admission.lab_id} "
        f"nodes={len(admission.nodes)} digest={admission.digest}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
