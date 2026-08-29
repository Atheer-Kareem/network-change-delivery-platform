"""Dedicated SNMP exporter container-definition contract for later composition."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from network_change_delivery.snmp_mib import EXPORTER_IMAGE

SNMP_EXPORTER_CONTAINER = "ncdp-snmp-exporter"
SNMP_EXPORTER_SERVICE = "snmp_exporter"
SNMP_MODULE_TARGET = "/etc/ncdp/snmp/modules"
SNMP_AUTH_TARGET = "/etc/ncdp/snmp/auth"


class SnmpServiceError(ValueError):
    """Bounded SNMP exporter container-contract failure."""


def verify_snmp_exporter_definition(
    inspected: dict[str, object],
    *,
    image_id: str,
    module_root: Path,
    auth_root: Path,
    project_name: str,
    control_network_name: str,
    device_network_name: str,
    container_name: str = SNMP_EXPORTER_CONTAINER,
) -> str:
    """Verify one exact private, non-root exporter definition."""
    host = inspected.get("HostConfig")
    config = inspected.get("Config")
    state = inspected.get("State")
    network_settings = inspected.get("NetworkSettings")
    identifier = inspected.get("Id")
    if (
        not all(
            isinstance(value, dict) for value in (host, config, state, network_settings)
        )
        or not isinstance(identifier, str)
        or re.fullmatch(r"[0-9a-f]{64}", identifier) is None
        or re.fullmatch(r"sha256:[0-9a-f]{64}", image_id) is None
    ):
        raise SnmpServiceError("SNMP exporter definition rejected")
    assert isinstance(host, dict)
    assert isinstance(config, dict)
    assert isinstance(state, dict)
    assert isinstance(network_settings, dict)
    labels = config.get("Labels") or {}
    networks = network_settings.get("Networks") or {}
    restart = host.get("RestartPolicy") or {}
    command = config.get("Cmd") or []
    expected_command = [
        f"--config.file={SNMP_MODULE_TARGET}/snmp-modules.yml",
        f"--config.file={SNMP_AUTH_TARGET}/snmp-auth.yml",
    ]
    expected_networks = {control_network_name, device_network_name}
    if (
        inspected.get("Name") != f"/{container_name}"
        or inspected.get("Image") != image_id
        or config.get("Image") != EXPORTER_IMAGE
        or config.get("User") != f"{os.getuid()}:{os.getgid()}"
        or config.get("Env")
        != ["PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"]
        or state.get("Running") is not True
        or host.get("ReadonlyRootfs") is not True
        or not isinstance(restart, dict)
        or restart.get("Name") not in {"", "no"}
        or set(host.get("CapDrop") or []) != {"ALL"}
        or not any(
            str(value).startswith("no-new-privileges")
            for value in host.get("SecurityOpt") or []
        )
        or not isinstance(labels, dict)
        or labels.get("com.docker.compose.project") != project_name
        or labels.get("com.docker.compose.service") != SNMP_EXPORTER_SERVICE
        or host.get("NetworkMode") not in expected_networks
        or not isinstance(networks, dict)
        or set(networks) != expected_networks
        or command != expected_command
        or host.get("PortBindings") not in ({}, None)
    ):
        raise SnmpServiceError("SNMP exporter definition rejected")
    expected_binds = {
        f"{module_root}:{SNMP_MODULE_TARGET}:ro",
        f"{auth_root}:{SNMP_AUTH_TARGET}:ro",
    }
    binds = host.get("Binds") or []
    if not isinstance(binds, list) or set(binds) != expected_binds:
        raise SnmpServiceError("SNMP exporter mounts rejected")
    rendered = json.dumps(inspected, sort_keys=True).casefold()
    for forbidden in (
        "docker.sock",
        "/.ssh",
        "/audit",
        "config-history",
        "netbox_token",
        "openbao",
        "cml_password",
        "auth_password",
        "priv_password",
        "config.expand-environment-variables",
    ):
        if forbidden in rendered:
            raise SnmpServiceError("SNMP exporter authority rejected")
    return identifier
