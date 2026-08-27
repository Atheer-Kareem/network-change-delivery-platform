#!/usr/bin/env python3
"""Materialize the complete private Oxidized JSONFile source."""

import os
import sys
from pathlib import Path

from network_change_delivery.inventory import InventoryError, NetBoxInventoryProvider
from network_change_delivery.oxidized_source import (
    OxidizedSourceError,
    materialize_oxidized_source,
)
from network_change_delivery.secrets import OpenBaoSecretProvider, SecretError

REQUIRED = (
    "NCDP_OXIDIZED_NETBOX_URL",
    "NCDP_OXIDIZED_NETBOX_TOKEN",
    "NCDP_OXIDIZED_OPENBAO_URL",
    "NCDP_OXIDIZED_OPENBAO_ROLE_ID",
    "NCDP_OXIDIZED_OPENBAO_SECRET_ID",
    "NCDP_OXIDIZED_RUNTIME_ROOT",
)


def main() -> int:
    if len(sys.argv) != 1:
        print("command-line arguments are not accepted", file=sys.stderr)
        return 2
    if any(not os.environ.get(name) for name in REQUIRED):
        print("Oxidized materializer configuration missing", file=sys.stderr)
        return 2
    try:
        inventory = NetBoxInventoryProvider(
            os.environ["NCDP_OXIDIZED_NETBOX_URL"],
            os.environ["NCDP_OXIDIZED_NETBOX_TOKEN"],
        )
        secrets = OpenBaoSecretProvider(
            os.environ["NCDP_OXIDIZED_OPENBAO_URL"],
            os.environ["NCDP_OXIDIZED_OPENBAO_ROLE_ID"],
            os.environ["NCDP_OXIDIZED_OPENBAO_SECRET_ID"],
        )
        result = materialize_oxidized_source(
            inventory, secrets, Path(os.environ["NCDP_OXIDIZED_RUNTIME_ROOT"])
        )
    except (InventoryError, SecretError, OxidizedSourceError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 2
    print(f"Oxidized source materialized: {len(result.identities)} nodes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
