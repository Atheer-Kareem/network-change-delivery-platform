#!/usr/bin/env python3
"""Configure the two exact Buildkite staging secret capabilities."""

import sys

from network_change_delivery.openbao_staging_config import (
    OpenBaoBuildkiteStagingConfigurator,
)
from network_change_delivery.secrets import SecretError


def main() -> int:
    if len(sys.argv) != 1:
        print("command-line arguments are not accepted", file=sys.stderr)
        return 2
    try:
        configured = OpenBaoBuildkiteStagingConfigurator.from_environment().configure()
    except SecretError as error:
        print(str(error), file=sys.stderr)
        return 2
    for policy, role in configured:
        print(f"OpenBao staging policy verified: {policy}")
        print(f"OpenBao staging role verified: {role}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
