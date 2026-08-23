#!/usr/bin/env python3
"""Configure one personal-lab Buildkite CML deployment capability."""

import sys

from network_change_delivery.openbao_cml_config import configure_cml_from_environment
from network_change_delivery.secrets import SecretError


def main() -> int:
    if len(sys.argv) != 1:
        print("command-line arguments are not accepted", file=sys.stderr)
        return 2
    try:
        policy, role = configure_cml_from_environment()
    except SecretError as error:
        print(str(error), file=sys.stderr)
        return 2
    print(f"OpenBao CML device policy: {policy} verified")
    print(f"OpenBao CML deployment role: {role} verified")
    print("Accepted Buildkite identity role: unchanged and verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
