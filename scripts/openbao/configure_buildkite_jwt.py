#!/usr/bin/env python3
"""Configure the personal-lab OpenBao Buildkite JWT boundary."""

import sys

from network_change_delivery.openbao_jwt_config import configure_from_environment
from network_change_delivery.secrets import SecretError


def main() -> int:
    if len(sys.argv) != 1:
        print("command-line arguments are not accepted", file=sys.stderr)
        return 2
    try:
        enabled = configure_from_environment()
    except SecretError as error:
        print(str(error), file=sys.stderr)
        return 2
    state = "enabled" if enabled else "already enabled"
    print(f"OpenBao jwt/ auth mount: {state}")
    print("OpenBao Buildkite JWT backend: verified")
    print("OpenBao Buildkite JWT role: verified")
    print("Device secret capability: NONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
