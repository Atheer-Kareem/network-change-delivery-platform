#!/usr/bin/env python3
"""Atomically activate exact B3 devices 8/9 after CML and trust acceptance."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

CONTAINER = "netbox-docker-netbox-1"
COMPOSE_PROJECT = "netbox-docker"
COMPOSE_SERVICE = "netbox"
MANAGE_PY = "/opt/netbox/netbox/manage.py"
INSIDE_MARKER = "NCDP_B3_NETBOX_ACTIVATION_INSIDE"
RESULT_PREFIX = "NCDP_B3_NETBOX_ACTIVATION_RESULT="

DEVICE_SPECS = {
    8: {
        "name": "transit-ios-01",
        "role": "transit",
        "device_type": "iosv-159-3-m12",
        "management_interface": "GigabitEthernet0/0",
        "live": "192.168.4.16/24",
        "staging": "192.168.4.31/24",
    },
    9: {
        "name": "access-sw-01",
        "role": "access",
        "device_type": "iosvl2-2020",
        "management_interface": "GigabitEthernet0/0",
        "live": "192.168.4.17/24",
        "staging": "192.168.4.32/24",
    },
}


class ActivationError(RuntimeError):
    """Bounded local NetBox activation failure."""


def validate_container_identity(payload: str) -> None:
    try:
        items = json.loads(payload)
        item = items[0]
        labels = item["Config"]["Labels"]
        ports = item["NetworkSettings"]["Ports"]
    except (IndexError, KeyError, TypeError, json.JSONDecodeError):
        raise ActivationError("local NetBox container identity is invalid") from None
    if len(items) != 1 or not item["State"]["Running"]:
        raise ActivationError("local NetBox container is not exactly running")
    if (
        labels.get("com.docker.compose.project") != COMPOSE_PROJECT
        or labels.get("com.docker.compose.service") != COMPOSE_SERVICE
        or ports.get("8080/tcp") != [{"HostIp": "127.0.0.1", "HostPort": "8000"}]
    ):
        raise ActivationError("local NetBox container boundary is invalid")


def run_operator_activation() -> dict[str, Any]:
    """Execute this reviewed source through the accepted local admin shell."""
    inspect = subprocess.run(
        ["docker", "inspect", CONTAINER],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
        shell=False,
    )
    validate_container_identity(inspect.stdout)
    source = Path(__file__).read_text()
    command = subprocess.run(
        [
            "docker",
            "exec",
            "-i",
            "-e",
            f"{INSIDE_MARKER}=1",
            CONTAINER,
            MANAGE_PY,
            "nbshell",
            "--no-color",
            "-c",
            "exec(compile(__import__('sys').stdin.read(), "
            "'<ncdp-b3-netbox-activation>', 'exec'))",
        ],
        input=f"{source}\n\nactivation_main()\n",
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
        shell=False,
    )
    if command.returncode != 0:
        raise ActivationError("NetBox B3-4 activation failed")
    matches = [
        line.removeprefix(RESULT_PREFIX)
        for line in command.stdout.splitlines()
        if line.startswith(RESULT_PREFIX)
    ]
    if len(matches) != 1:
        raise ActivationError("NetBox B3-4 activation result is missing or ambiguous")
    try:
        result = json.loads(matches[0])
    except json.JSONDecodeError:
        raise ActivationError("NetBox B3-4 activation result is invalid") from None
    if not isinstance(result, dict):
        raise ActivationError("NetBox B3-4 activation result is invalid")
    return result


def activation_main() -> None:
    """Validate exact B3-2 authority, then atomically activate devices 8/9."""
    from dcim.models import Device, Interface
    from django.db import transaction
    from ipam.models import IPAddress

    if os.environ.get(INSIDE_MARKER) != "1":
        raise ActivationError("NetBox B3-4 activation context is invalid")

    def exact_ip(address: str, interface: Any, tag_slug: str) -> Any:
        matches = list(IPAddress.objects.filter(address=address))
        if len(matches) != 1:
            raise ActivationError(f"NetBox IP identity is invalid: {address}")
        value = matches[0]
        if (
            value.status != "active"
            or value.assigned_object_id != interface.pk
            or value.assigned_object_type.model != "interface"
            or not value.tags.filter(slug=tag_slug).exists()
        ):
            raise ActivationError(f"NetBox IP authority conflicts: {address}")
        return value

    outcomes: list[dict[str, object]] = []
    with transaction.atomic():
        resolved: list[tuple[Any, dict[str, str]]] = []
        for device_id, spec in DEVICE_SPECS.items():
            matches = list(Device.objects.filter(pk=device_id))
            if len(matches) != 1:
                raise ActivationError(f"NetBox device {device_id} is unavailable")
            device = matches[0]
            if (
                device.name != spec["name"]
                or device.status not in {"planned", "active"}
                or device.site.slug != "lab"
                or device.role.slug != spec["role"]
                or device.platform.slug != "cisco-ios"
                or device.device_type.slug != spec["device_type"]
                or not device.tags.filter(slug="ncdp-profiled-inventory").exists()
                or device.tags.filter(slug="ncdp-managed").exists()
            ):
                raise ActivationError(f"NetBox device authority conflicts: {device_id}")
            interfaces = list(
                Interface.objects.filter(
                    device=device, name=spec["management_interface"]
                )
            )
            if len(interfaces) != 1:
                raise ActivationError(
                    f"NetBox management interface conflicts: {device_id}"
                )
            management = interfaces[0]
            if not all(
                management.tags.filter(slug=tag).exists()
                for tag in ("ncdp-management-attachment", "ncdp-protected")
            ):
                raise ActivationError(
                    f"NetBox management protection conflicts: {device_id}"
                )
            live = exact_ip(spec["live"], management, "ncdp-management-live")
            exact_ip(spec["staging"], management, "ncdp-management-staging")
            if device.primary_ip4_id != live.pk:
                raise ActivationError(f"NetBox primary IPv4 conflicts: {device_id}")
            resolved.append((device, spec))
        for device, spec in resolved:
            changed = device.status == "planned"
            if changed:
                device.status = "active"
                device.full_clean()
                device.save(update_fields=("status", "last_updated"))
            outcomes.append(
                {
                    "device_id": device.pk,
                    "name": spec["name"],
                    "status": str(device.status),
                    "changed": changed,
                }
            )
    print(
        RESULT_PREFIX
        + json.dumps(
            {"schema_version": "1", "devices": outcomes},
            sort_keys=True,
            separators=(",", ":"),
        )
    )


def main() -> int:
    if len(__import__("sys").argv) != 1:
        print("command-line arguments are not accepted", file=__import__("sys").stderr)
        return 2
    try:
        result = run_operator_activation()
    except (ActivationError, OSError, subprocess.SubprocessError) as error:
        print(str(error), file=__import__("sys").stderr)
        return 2
    for item in result.get("devices", []):
        print(
            f"NetBox device {item['device_id']} {item['name']} status={item['status']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
