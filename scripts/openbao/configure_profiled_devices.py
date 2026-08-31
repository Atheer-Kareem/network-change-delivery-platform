#!/usr/bin/env python3
"""Configure the exact local OpenBao B3 profiled-device credentials."""

import sys

from network_change_delivery.openbao_profiled_config import (
    OpenBaoProfiledDeviceConfigurator,
)
from network_change_delivery.secrets import SecretError


def main() -> int:
    if len(sys.argv) != 1:
        print("command-line arguments are not accepted", file=sys.stderr)
        return 2
    try:
        result = OpenBaoProfiledDeviceConfigurator.from_environment().configure()
    except SecretError as error:
        print(str(error), file=sys.stderr)
        return 2
    print(f"OpenBao local AppRole verified: {result.local_approle}")
    print(f"OpenBao exact local policy verified: {result.local_policy}")
    for device_id in result.created_device_ids:
        print(f"OpenBao device credential created: netbox:dcim.device:{device_id}")
    for device_id in result.reused_device_ids:
        print(f"OpenBao device credential reused: netbox:dcim.device:{device_id}")
    print("OpenBao credential values: REDACTED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
