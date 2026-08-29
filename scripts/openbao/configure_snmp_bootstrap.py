#!/usr/bin/env python3
"""Configure and persist the SNMP materializer bootstrap; accepts no arguments."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from network_change_delivery.openbao_snmp_bootstrap import (
    OpenBaoSnmpBootstrap,
    persist_snmp_machine_bootstrap,
)
from network_change_delivery.secrets import SecretError


def main() -> int:
    if len(sys.argv) != 1:
        print("command-line arguments are not accepted", file=sys.stderr)
        return 2
    url = os.environ.get("NCDP_OPENBAO_URL", "")
    token = os.environ.get("BAO_TOKEN", "")
    root = os.environ.get("NCDP_OBSERVABILITY_PRIVATE_ROOT", "")
    if not url or not token or not root:
        print("OpenBao SNMP bootstrap operator configuration missing", file=sys.stderr)
        return 2
    try:
        bootstrap = OpenBaoSnmpBootstrap(url).configure(token)
        persist_snmp_machine_bootstrap(Path(root), bootstrap)
    except SecretError as error:
        print(str(error), file=sys.stderr)
        return 2
    print("SNMP observability machine bootstrap configured and privately persisted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
