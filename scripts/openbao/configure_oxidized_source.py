#!/usr/bin/env python3
"""Configure and persist the dedicated Oxidized source AppRole bootstrap."""

import os
import sys
from pathlib import Path

from network_change_delivery.openbao_oxidized_config import (
    OXIDIZED_POLICY_NAME,
    OXIDIZED_ROLE_NAME,
    OpenBaoOxidizedConfigurator,
    persist_oxidized_bootstrap,
)
from network_change_delivery.secrets import SecretError


def main() -> int:
    if len(sys.argv) != 1:
        print("command-line arguments are not accepted", file=sys.stderr)
        return 2
    root = os.environ.get("NCDP_OXIDIZED_RUNTIME_ROOT")
    if not root:
        print("OpenBao Oxidized operator configuration missing", file=sys.stderr)
        return 2
    try:
        bootstrap = OpenBaoOxidizedConfigurator.from_environment().configure()
        persist_oxidized_bootstrap(Path(root), bootstrap)
    except (SecretError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 2
    print(f"OpenBao Oxidized policy verified: {OXIDIZED_POLICY_NAME}")
    print(f"OpenBao Oxidized role verified: {OXIDIZED_ROLE_NAME}")
    print("Oxidized AppRole bootstrap persisted: SET")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
