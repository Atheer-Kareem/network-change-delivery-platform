#!/usr/bin/env python3
"""Operator-only SNMP OpenBao authority boundary; accepts no arguments."""

from __future__ import annotations

import os
import sys

from network_change_delivery.openbao_snmp_config import OpenBaoSnmpConfigurator
from network_change_delivery.secrets import SecretError


def main() -> int:
    if len(sys.argv) != 1:
        print("command-line arguments are not accepted", file=sys.stderr)
        return 2
    try:
        configurator = OpenBaoSnmpConfigurator.from_environment(os.environ)
        action = os.environ.get("NCDP_SNMP_OPERATOR_ACTION", "configure")
        if action == "configure":
            configured = configurator.configure_authorities()
            print("SNMP OpenBao authorities verified: " + ", ".join(configured))
            return 0
        if action == "create-generation":
            device = os.environ.get("NCDP_SNMP_DEVICE_ID", "")
            generation = os.environ.get("NCDP_SNMP_GENERATION", "")
            if device not in {"1", "2"} or not generation:
                raise SecretError("OpenBao SNMP generation configuration missing")
            result = configurator.create_generation(int(device), generation)
            print(
                f"SNMP generation {result.outcome}: device={result.device_id} "
                f"generation={result.generation} username={result.username}"
            )
            return 0
        raise SecretError("OpenBao SNMP operator action rejected")
    except SecretError as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
