#!/usr/bin/env python3
"""Apply the explicit Detour B3-2 inventory migration to local NetBox.

The host-side entry point verifies the accepted loopback-only NetBox container,
then executes the same reviewed source through NetBox's administrative shell.
The migration is atomic, idempotent, secret-free, and contains no delete path.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path
from typing import Any

CONTAINER = "netbox-docker-netbox-1"
COMPOSE_PROJECT = "netbox-docker"
COMPOSE_SERVICE = "netbox"
MANAGE_PY = "/opt/netbox/netbox/manage.py"
INSIDE_MARKER = "NCDP_B3_NETBOX_MIGRATION_INSIDE"
RESULT_PREFIX = "NCDP_B3_NETBOX_RESULT="

ROLE_SPECS = {
    "core": {"name": "Core", "color": "1976d2"},
    "edge": {"name": "Edge", "color": "7b1fa2"},
    "transit": {"name": "Transit", "color": "ef6c00"},
    "access": {"name": "Access", "color": "00897b"},
}

TAG_SPECS = {
    "ncdp-profiled-inventory": {
        "name": "ncdp-profiled-inventory",
        "color": "1565c0",
    },
    "ncdp-management-attachment": {
        "name": "ncdp-management-attachment",
        "color": "ef6c00",
    },
    "ncdp-management-live": {
        "name": "ncdp-management-live",
        "color": "2e7d32",
    },
    "ncdp-management-staging": {
        "name": "ncdp-management-staging",
        "color": "7b1fa2",
    },
}

NEW_DEVICE_SPECS = {
    "transit-ios-01": {
        "device_type_slug": "iosv-159-3-m12",
        "role_slug": "transit",
        "interfaces": (
            "GigabitEthernet0/0",
            "GigabitEthernet0/1",
            "GigabitEthernet0/2",
            "GigabitEthernet0/3",
        ),
        "management_interface": "GigabitEthernet0/0",
        "live": "192.168.4.16/24",
        "staging": "192.168.4.31/24",
    },
    "access-sw-01": {
        "device_type_slug": "iosvl2-2020",
        "role_slug": "access",
        "interfaces": (
            "GigabitEthernet0/0",
            "GigabitEthernet0/1",
            "GigabitEthernet0/2",
            "GigabitEthernet0/3",
        ),
        "management_interface": "GigabitEthernet0/0",
        "live": "192.168.4.17/24",
        "staging": "192.168.4.32/24",
    },
}

CABLE_SPECS = (
    (("core-02", "GigabitEthernet4"), ("edge-junos-01", "ge-0/0/0")),
    (("core-02", "GigabitEthernet2"), ("transit-ios-01", "GigabitEthernet0/1")),
    (("edge-junos-01", "ge-0/0/1"), ("transit-ios-01", "GigabitEthernet0/2")),
    (("core-02", "GigabitEthernet3"), ("access-sw-01", "GigabitEthernet0/1")),
)


class MigrationError(RuntimeError):
    """Raised when the local authority does not match the bounded migration."""


def validate_container_identity(payload: str) -> None:
    """Fail closed unless Docker reports the accepted local NetBox listener."""
    try:
        items = json.loads(payload)
        item = items[0]
        labels = item["Config"]["Labels"]
        ports = item["NetworkSettings"]["Ports"]
    except (IndexError, KeyError, TypeError, json.JSONDecodeError):
        raise MigrationError("local NetBox container identity is invalid") from None
    if len(items) != 1 or not item["State"]["Running"]:
        raise MigrationError("local NetBox container is not exactly running")
    if (
        labels.get("com.docker.compose.project") != COMPOSE_PROJECT
        or labels.get("com.docker.compose.service") != COMPOSE_SERVICE
    ):
        raise MigrationError("local NetBox Compose identity is invalid")
    if ports.get("8080/tcp") != [{"HostIp": "127.0.0.1", "HostPort": "8000"}]:
        raise MigrationError("local NetBox listener boundary is invalid")


def run_operator_migration() -> dict[str, Any]:
    """Run the reviewed migration source inside the accepted NetBox shell."""
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
    program = f"{source}\n\nmigration_main()\n"
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
            "'<ncdp-b3-netbox-migration>', 'exec'))",
        ],
        input=program,
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
        shell=False,
    )
    if command.returncode != 0:
        raise MigrationError(
            "NetBox B3-2 migration failed; inspect the local administrative shell"
        )
    matches = [
        line.removeprefix(RESULT_PREFIX)
        for line in command.stdout.splitlines()
        if line.startswith(RESULT_PREFIX)
    ]
    if len(matches) != 1:
        raise MigrationError("NetBox B3-2 migration result is missing or ambiguous")
    try:
        result = json.loads(matches[0])
    except json.JSONDecodeError:
        raise MigrationError("NetBox B3-2 migration result is invalid") from None
    if not isinstance(result, dict):
        raise MigrationError("NetBox B3-2 migration result is invalid")
    return result


def migration_main() -> None:
    """Apply and verify the one accepted B3-2 authority transition."""
    from dcim.models import (
        Cable,
        Device,
        DeviceRole,
        DeviceType,
        Interface,
        Manufacturer,
        Platform,
        Site,
    )
    from django.db import transaction
    from extras.models import Tag
    from ipam.models import IPAddress

    changes: dict[str, list[str]] = {
        "created": [],
        "updated": [],
        "reused": [],
    }

    def save(instance: Any) -> None:
        instance.full_clean()
        instance.save()

    def exact_one(model: Any, noun: str, **filters: Any) -> Any:
        matches = list(model.objects.filter(**filters))
        if len(matches) != 1:
            raise MigrationError(f"NetBox requires exactly one {noun}")
        return matches[0]

    def ensure_slugged(
        model: Any,
        noun: str,
        slug: str,
        create_fields: dict[str, Any],
        exact_fields: dict[str, Any],
    ) -> Any:
        matches = list(model.objects.filter(slug=slug))
        if len(matches) > 1:
            raise MigrationError(f"NetBox {noun} slug is ambiguous: {slug}")
        if not matches:
            instance = model(slug=slug, **create_fields)
            save(instance)
            changes["created"].append(f"{noun}:{slug}:{instance.pk}")
            return instance
        instance = matches[0]
        for field, expected in exact_fields.items():
            if getattr(instance, field) != expected:
                raise MigrationError(f"NetBox {noun} conflicts with {slug}")
        changes["reused"].append(f"{noun}:{slug}:{instance.pk}")
        return instance

    def add_tag(instance: Any, tag: Any, noun: str) -> None:
        if instance.tags.filter(pk=tag.pk).exists():
            return
        instance.tags.add(tag)
        changes["updated"].append(f"{noun}:{instance.pk}:tag+{tag.slug}")

    def ensure_interface(device: Any, name: str) -> Any:
        matches = list(Interface.objects.filter(device=device, name=name))
        if len(matches) > 1:
            raise MigrationError(f"NetBox interface is ambiguous: {device.name}/{name}")
        if not matches:
            interface = Interface(
                device=device,
                name=name,
                type="1000base-t",
                enabled=True,
                mgmt_only=False,
            )
            save(interface)
            changes["created"].append(f"interface:{device.name}/{name}:{interface.pk}")
            return interface
        interface = matches[0]
        if (
            interface.type != "1000base-t"
            or not interface.enabled
            or interface.mgmt_only
        ):
            raise MigrationError(f"NetBox interface conflicts: {device.name}/{name}")
        changes["reused"].append(f"interface:{device.name}/{name}:{interface.pk}")
        return interface

    def ensure_ip(
        address: str,
        interface: Any,
        purpose_tag: Any,
    ) -> Any:
        matches = list(IPAddress.objects.filter(address=address))
        if len(matches) > 1:
            raise MigrationError(f"NetBox IP address is ambiguous: {address}")
        if not matches:
            ip_address = IPAddress(
                address=address,
                status="active",
                assigned_object=interface,
            )
            save(ip_address)
            changes["created"].append(f"ip:{address}:{ip_address.pk}")
        else:
            ip_address = matches[0]
            if (
                ip_address.status != "active"
                or ip_address.assigned_object_id != interface.pk
                or ip_address.assigned_object_type.model != "interface"
            ):
                raise MigrationError(f"NetBox IP address conflicts: {address}")
            changes["reused"].append(f"ip:{address}:{ip_address.pk}")
        add_tag(ip_address, purpose_tag, "ip")
        return ip_address

    def ensure_cable(endpoint_a: tuple[str, str], endpoint_b: tuple[str, str]) -> Any:
        device_a = exact_one(Device, "cable device A", name=endpoint_a[0])
        device_b = exact_one(Device, "cable device B", name=endpoint_b[0])
        interface_a = exact_one(
            Interface,
            "cable interface A",
            device=device_a,
            name=endpoint_a[1],
        )
        interface_b = exact_one(
            Interface,
            "cable interface B",
            device=device_b,
            name=endpoint_b[1],
        )
        cable_ids = {interface_a.cable_id, interface_b.cable_id} - {None}
        if not cable_ids:
            cable = Cable(
                a_terminations=[interface_a],
                b_terminations=[interface_b],
                status="connected",
            )
            save(cable)
            changes["created"].append(f"cable:{cable.pk}")
            return cable
        if len(cable_ids) != 1 or interface_a.cable_id != interface_b.cable_id:
            raise MigrationError(
                f"NetBox cable endpoints conflict: {endpoint_a} <-> {endpoint_b}"
            )
        cable = Cable.objects.get(pk=cable_ids.pop())
        endpoints = {
            (termination.termination.device.name, termination.termination.name)
            for termination in cable.terminations.all()
        }
        if endpoints != {endpoint_a, endpoint_b} or cable.status != "connected":
            raise MigrationError(
                f"NetBox cable identity conflicts: {endpoint_a} <-> {endpoint_b}"
            )
        changes["reused"].append(f"cable:{cable.pk}")
        return cable

    with transaction.atomic():
        site = exact_one(Site, "site lab", slug="lab")
        if site.name != "lab" or site.status != "active":
            raise MigrationError("NetBox site lab conflicts with B3-2")
        cisco = exact_one(Manufacturer, "Cisco manufacturer", slug="cisco")
        if cisco.name != "Cisco":
            raise MigrationError("NetBox Cisco manufacturer conflicts with B3-2")

        roles = {
            slug: ensure_slugged(
                DeviceRole,
                "role",
                slug,
                {"name": spec["name"], "color": spec["color"]},
                {"name": spec["name"]},
            )
            for slug, spec in ROLE_SPECS.items()
        }
        tags = {
            slug: ensure_slugged(
                Tag,
                "tag",
                slug,
                {"name": spec["name"], "color": spec["color"]},
                {"name": spec["name"]},
            )
            for slug, spec in TAG_SPECS.items()
        }
        managed_tag = exact_one(Tag, "legacy managed tag", slug="ncdp-managed")
        protected_tag = exact_one(Tag, "protected tag", slug="ncdp-protected")
        fleet_interface_tag = exact_one(
            Tag,
            "legacy fleet interface tag",
            slug="ncdp-fleet-interface-live-001",
        )

        cisco_ios = ensure_slugged(
            Platform,
            "platform",
            "cisco-ios",
            {"name": "Cisco IOS", "manufacturer": cisco},
            {"name": "Cisco IOS", "manufacturer_id": cisco.pk},
        )
        device_types = {
            "iosv-159-3-m12": ensure_slugged(
                DeviceType,
                "device-type",
                "iosv-159-3-m12",
                {
                    "model": "IOSv 15.9(3)M12",
                    "manufacturer": cisco,
                },
                {"model": "IOSv 15.9(3)M12", "manufacturer_id": cisco.pk},
            ),
            "iosvl2-2020": ensure_slugged(
                DeviceType,
                "device-type",
                "iosvl2-2020",
                {
                    "model": "IOSvL2 2020",
                    "manufacturer": cisco,
                },
                {"model": "IOSvL2 2020", "manufacturer_id": cisco.pk},
            ),
        }

        existing_specs = {
            "core-02": {
                "id": 1,
                "role": roles["core"],
                "management": "GigabitEthernet1",
                "live": "192.168.4.14/24",
                "staging": "192.168.4.30/24",
            },
            "edge-junos-01": {
                "id": 2,
                "role": roles["edge"],
                "management": "fxp0",
                "live": "192.168.4.20/24",
                "staging": "192.168.4.40/24",
            },
        }
        for name, spec in existing_specs.items():
            device = exact_one(Device, f"existing device {name}", name=name)
            if (
                device.pk != spec["id"]
                or device.status != "active"
                or device.site_id != site.pk
                or not device.tags.filter(pk=managed_tag.pk).exists()
            ):
                raise MigrationError(f"NetBox existing device conflicts: {name}")
            if device.role_id != spec["role"].pk:
                device.role = spec["role"]
                save(device)
                changes["updated"].append(f"device:{name}:role")
            add_tag(device, tags["ncdp-profiled-inventory"], "device")
            management = ensure_interface(device, spec["management"])
            add_tag(management, protected_tag, "interface")
            add_tag(management, tags["ncdp-management-attachment"], "interface")
            live = ensure_ip(spec["live"], management, tags["ncdp-management-live"])
            ensure_ip(spec["staging"], management, tags["ncdp-management-staging"])
            if device.primary_ip4_id != live.pk:
                raise MigrationError(f"NetBox existing primary IPv4 conflicts: {name}")

        core = Device.objects.get(name="core-02")
        edge = Device.objects.get(name="edge-junos-01")
        ensure_interface(core, "GigabitEthernet2")
        core_gi3 = ensure_interface(core, "GigabitEthernet3")
        if not core_gi3.tags.filter(pk=fleet_interface_tag.pk).exists():
            raise MigrationError("NetBox core fleet-interface tag is missing")
        ensure_interface(core, "GigabitEthernet4")
        ensure_interface(edge, "ge-0/0/0")
        ensure_interface(edge, "ge-0/0/1")

        for name, spec in NEW_DEVICE_SPECS.items():
            matches = list(Device.objects.filter(name=name))
            if len(matches) > 1:
                raise MigrationError(f"NetBox new device name is ambiguous: {name}")
            if not matches:
                device = Device(
                    name=name,
                    site=site,
                    device_type=device_types[spec["device_type_slug"]],
                    role=roles[spec["role_slug"]],
                    platform=cisco_ios,
                    status="planned",
                )
                save(device)
                changes["created"].append(f"device:{name}:{device.pk}")
            else:
                device = matches[0]
                if (
                    device.site_id != site.pk
                    or device.device_type_id
                    != device_types[spec["device_type_slug"]].pk
                    or device.role_id != roles[spec["role_slug"]].pk
                    or device.platform_id != cisco_ios.pk
                    or device.status != "planned"
                ):
                    raise MigrationError(f"NetBox new device conflicts: {name}")
                changes["reused"].append(f"device:{name}:{device.pk}")
            if device.tags.filter(pk=managed_tag.pk).exists():
                raise MigrationError(f"NetBox new device has legacy authority: {name}")
            add_tag(device, tags["ncdp-profiled-inventory"], "device")
            interfaces = {
                interface_name: ensure_interface(device, interface_name)
                for interface_name in spec["interfaces"]
            }
            actual_names = set(
                Interface.objects.filter(device=device).values_list("name", flat=True)
            )
            if actual_names != set(spec["interfaces"]):
                raise MigrationError(
                    f"NetBox new device interfaces are not exact: {name}"
                )
            management = interfaces[spec["management_interface"]]
            add_tag(management, protected_tag, "interface")
            add_tag(management, tags["ncdp-management-attachment"], "interface")
            live = ensure_ip(spec["live"], management, tags["ncdp-management-live"])
            ensure_ip(spec["staging"], management, tags["ncdp-management-staging"])
            if device.primary_ip4_id is None:
                device.primary_ip4 = live
                save(device)
                changes["updated"].append(f"device:{name}:primary-ipv4")
            elif device.primary_ip4_id != live.pk:
                raise MigrationError(f"NetBox new primary IPv4 conflicts: {name}")

        cables = [ensure_cable(*spec) for spec in CABLE_SPECS]

        legacy_names = tuple(
            Device.objects.filter(tags=managed_tag, status="active")
            .order_by("id")
            .values_list("name", flat=True)
        )
        profiled_names = tuple(
            Device.objects.filter(tags=tags["ncdp-profiled-inventory"])
            .order_by("id")
            .values_list("name", flat=True)
        )
        active_profiled_names = tuple(
            Device.objects.filter(tags=tags["ncdp-profiled-inventory"], status="active")
            .order_by("id")
            .values_list("name", flat=True)
        )
        if legacy_names != ("core-02", "edge-junos-01"):
            raise MigrationError("NetBox legacy managed population changed")
        if set(profiled_names) != {
            "core-02",
            "edge-junos-01",
            "transit-ios-01",
            "access-sw-01",
        }:
            raise MigrationError("NetBox profiled population is not exact")
        if active_profiled_names != ("core-02", "edge-junos-01"):
            raise MigrationError("NetBox planned profiled population is not isolated")

        result = {
            "schema_version": "1",
            "changes": changes,
            "legacy_managed": legacy_names,
            "profiled_inventory": profiled_names,
            "active_profiled_inventory": active_profiled_names,
            "devices": [
                {
                    "id": device.pk,
                    "name": device.name,
                    "status": device.status,
                    "role": device.role.slug,
                    "platform": device.platform.slug,
                    "device_type": device.device_type.slug,
                    "primary_ip4": str(device.primary_ip4.address),
                    "tags": sorted(device.tags.values_list("slug", flat=True)),
                    "interfaces": [
                        {
                            "id": interface.pk,
                            "name": interface.name,
                            "tags": sorted(
                                interface.tags.values_list("slug", flat=True)
                            ),
                        }
                        for interface in Interface.objects.filter(
                            device=device
                        ).order_by("id")
                    ],
                }
                for device in Device.objects.filter(
                    name__in=(
                        "core-02",
                        "edge-junos-01",
                        "transit-ios-01",
                        "access-sw-01",
                    )
                ).order_by("id")
            ],
            "management_ips": [
                {
                    "id": ip_address.pk,
                    "address": str(ip_address.address),
                    "interface": (
                        f"{ip_address.assigned_object.device.name}/"
                        f"{ip_address.assigned_object.name}"
                    ),
                    "tags": sorted(ip_address.tags.values_list("slug", flat=True)),
                }
                for ip_address in IPAddress.objects.filter(
                    address__in=(
                        "192.168.4.14/24",
                        "192.168.4.20/24",
                        "192.168.4.30/24",
                        "192.168.4.40/24",
                        "192.168.4.16/24",
                        "192.168.4.31/24",
                        "192.168.4.17/24",
                        "192.168.4.32/24",
                    )
                ).order_by("id")
            ],
            "cables": [
                {
                    "id": cable.pk,
                    "status": cable.status,
                    "endpoints": sorted(
                        f"{termination.termination.device.name}/"
                        f"{termination.termination.name}"
                        for termination in cable.terminations.all()
                    ),
                }
                for cable in sorted(cables, key=lambda item: item.pk)
            ],
        }
        print(f"{RESULT_PREFIX}{json.dumps(result, sort_keys=True)}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Apply the explicit local NetBox Detour B3-2 migration."
    )
    parser.parse_args()
    result = run_operator_migration()
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__" and os.environ.get(INSIDE_MARKER) != "1":
    raise SystemExit(main())
