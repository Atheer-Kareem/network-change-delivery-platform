#!/usr/bin/env python3
"""Prepare secret-free synthetic SNMP targets and Prometheus configuration."""

from __future__ import annotations

import argparse
import os
import tempfile
from pathlib import Path

from network_change_delivery.snmp_private import publish_snmp_auth
from network_change_delivery.snmp_prometheus import render_snmp_prometheus_config
from network_change_delivery.snmp_publication import (
    SnmpPollingTarget,
    publish_snmp_targets,
)
from network_change_delivery.snmp_telemetry import (
    ExpectedSnmpInterface,
    ExpectedSnmpInterfacePopulation,
    ObservedSnmpInterface,
    SnmpCredentialReference,
    SnmpDeviceTargetStatus,
    SnmpTargetIdentity,
    SnmpTargetState,
    normalize_interfaces,
    target_generation_with_digest,
)


def _mapping(device_number: int, interface_offset: int):
    device = f"netbox:dcim.device:{device_number}"
    return normalize_interfaces(
        ExpectedSnmpInterfacePopulation(
            device=device,
            pagination_complete=True,
            interfaces=(
                ExpectedSnmpInterface(
                    device=device,
                    inventory_object_id=(
                        f"netbox:dcim.interface:{interface_offset + 1}"
                    ),
                    name="eth0",
                ),
            ),
        ),
        (
            ObservedSnmpInterface(if_index=1, if_name="lo"),
            ObservedSnmpInterface(if_index=2, if_name="eth0"),
        ),
    )


def mappings():
    return (_mapping(1, 100), _mapping(2, 200))


def _target(device_number: int, generation: str) -> SnmpPollingTarget:
    device = f"netbox:dcim.device:{device_number}"
    return SnmpPollingTarget(
        identity=SnmpTargetIdentity(
            device=device,
            device_name=f"synthetic-snmp-{device_number}",
            platform="cisco_iosxe" if device_number == 1 else "junos",
            credential=SnmpCredentialReference(
                device=device,
                reference=(
                    f"snmpv3:netbox:dcim.device:{device_number}:generation:"
                    f"synthetic_{generation}"
                ),
                auth_selector=f"ncdp_device_{device_number}_{generation}",
            ),
        ),
        endpoint=f"synthetic-snmp-agent-{device_number}:1161",
    )


def publish_targets(state_root: Path, generation_name: str) -> None:
    current_mappings = mappings()
    statuses = tuple(
        SnmpDeviceTargetStatus(
            device=f"netbox:dcim.device:{index}",
            state=SnmpTargetState.ACTIVE,
            interface_mapping_digest=current_mappings[index - 1].digest,
        )
        for index in (1, 2)
    )
    publish_snmp_targets(
        state_root,
        target_generation_with_digest(statuses),
        tuple(_target(index, generation_name) for index in (1, 2)),
    )


def _write_private(path: Path, content: bytes) -> None:
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(name)
    try:
        os.fchmod(descriptor, 0o600)
        os.write(descriptor, content)
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        temporary.replace(path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    subcommands = parser.add_subparsers(dest="command", required=True)
    auth = subcommands.add_parser("publish-auth")
    auth.add_argument("--directory", type=Path, required=True)
    auth.add_argument("--source", type=Path, required=True)
    targets = subcommands.add_parser("publish-targets")
    targets.add_argument("--state-root", type=Path, required=True)
    targets.add_argument("--generation", choices=("a", "b"), required=True)
    prepare = subcommands.add_parser("prepare")
    prepare.add_argument("--base-prometheus", type=Path, required=True)
    prepare.add_argument("--prometheus-output", type=Path, required=True)
    prepare.add_argument("--state-root", type=Path, required=True)
    prepare.add_argument("--generation", choices=("a", "b"), required=True)
    arguments = parser.parse_args()
    if arguments.command == "publish-auth":
        publish_snmp_auth(arguments.directory, arguments.source.read_bytes())
    elif arguments.command == "publish-targets":
        publish_targets(arguments.state_root, arguments.generation)
    else:
        publish_targets(arguments.state_root, arguments.generation)
        rendered = render_snmp_prometheus_config(
            arguments.base_prometheus.read_bytes(), mappings()
        )
        _write_private(arguments.prometheus_output, rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
