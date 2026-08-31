#!/usr/bin/env python3
"""Reconcile the two reviewed IOS nodes into persistent NCDP Live."""

from __future__ import annotations

import sys
from dataclasses import dataclass

from network_change_delivery.profiled_live_cml import (
    NEW_NODE_SPECS,
    ProfiledLiveCmlError,
    ProfiledLiveCmlOperator,
    ios_scrypt_password_hash,
)
from network_change_delivery.secrets import OpenBaoSecretProvider, SecretError


@dataclass(frozen=True)
class _CredentialTarget:
    inventory_source: str
    inventory_object_id: str


def main() -> int:
    if len(sys.argv) != 1:
        print("command-line arguments are not accepted", file=sys.stderr)
        return 2
    operator: ProfiledLiveCmlOperator | None = None
    try:
        provider = OpenBaoSecretProvider()
        credentials = {
            spec.device_id: provider.load(
                _CredentialTarget(
                    inventory_source="netbox",
                    inventory_object_id=f"netbox:dcim.device:{spec.device_id}",
                )
            )
            for spec in NEW_NODE_SPECS
        }
        hashes = {
            spec.device_id: ios_scrypt_password_hash(
                credentials[spec.device_id].password, spec.password_salt
            )
            for spec in NEW_NODE_SPECS
        }
        operator = ProfiledLiveCmlOperator.from_environment()
        result = operator.realize(
            usernames={
                device_id: value.username for device_id, value in credentials.items()
            },
            password_hashes=hashes,
        )
    except (ProfiledLiveCmlError, SecretError) as error:
        print(f"persistent profiled CML realization failed: {error}", file=sys.stderr)
        return 2
    finally:
        if operator is not None:
            operator.close()
    print(f"persistent CML lab verified: {result.lab_id}")
    print(f"transit-ios-01 CML node: {result.transit_node_id}")
    print(f"access-sw-01 CML node: {result.access_node_id}")
    print(f"rebootstrapped nodes: {len(result.rebootstrapped_node_ids)}")
    print(f"created links: {len(result.created_link_ids)}")
    print("bootstrap credential values: REDACTED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
