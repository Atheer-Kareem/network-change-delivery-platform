#!/usr/bin/env python3
"""Configure and persist the minimal persistent Oxidized machine bootstrap."""

import os
import sys
from pathlib import Path

from network_change_delivery.openbao_oxidized_bootstrap import OpenBaoOxidizedBootstrap
from network_change_delivery.oxidized_service import publish_private_text
from network_change_delivery.secrets import SecretError


def main() -> int:
    if len(sys.argv) != 1:
        print("command-line arguments are not accepted", file=sys.stderr)
        return 2
    url = os.environ.get("NCDP_OXIDIZED_OPENBAO_URL")
    token = os.environ.get("BAO_TOKEN")
    root = os.environ.get("NCDP_OXIDIZED_RUNTIME_ROOT")
    if not url or not token or not root:
        print("OpenBao Oxidized bootstrap configuration missing", file=sys.stderr)
        return 2
    try:
        bootstrap = OpenBaoOxidizedBootstrap(url).configure(token)
        operator = Path(root) / "operator"
        publish_private_text(operator / "bootstrap-role-id", bootstrap.role_id)
        publish_private_text(operator / "bootstrap-secret-id", bootstrap.secret_id)
    except (OSError, SecretError, ValueError):
        print("OpenBao Oxidized bootstrap configuration failed", file=sys.stderr)
        return 2
    print("OpenBao Oxidized machine bootstrap persisted: SET")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
