#!/usr/bin/env python3
"""Establish the exact Detour B3-5 data-plane authority in local NetBox.

The host entry point verifies the accepted loopback-only NetBox container, then
executes this reviewed source through NetBox's administrative shell. The
migration is atomic, idempotent, secret-free, and has no delete path.
"""

from __future__ import annotations

import ipaddress
import json
import os
import subprocess
from pathlib import Path
from typing import Any

CONTAINER = "netbox-docker-netbox-1"
COMPOSE_PROJECT = "netbox-docker"
COMPOSE_SERVICE = "netbox"
MANAGE_PY = "/opt/netbox/netbox/manage.py"
INSIDE_MARKER = "NCDP_B3_DATA_PLANE_MIGRATION_INSIDE"
RESULT_PREFIX = "NCDP_B3_DATA_PLANE_RESULT="
DATA_PLANE_TAG = "ncdp-data-plane"
READ_PERMISSION_NAME = "NCDP data-plane read-only"

PREFIX_SPECS = (
    {
        "logical_name": "data-plane-parent",
        "prefix": "10.60.0.0/16",
        "description": "NCDP data-plane parent",
        "vlan_vid": None,
    },
    {
        "logical_name": "core-junos-link",
        "prefix": "10.60.0.0/30",
        "description": "NCDP routed link core-02 to edge-junos-01",
        "vlan_vid": None,
    },
    {
        "logical_name": "core-transit-link",
        "prefix": "10.60.0.4/30",
        "description": "NCDP routed link core-02 to transit-ios-01",
        "vlan_vid": None,
    },
    {
        "logical_name": "junos-transit-link",
        "prefix": "10.60.0.8/30",
        "description": "NCDP routed link edge-junos-01 to transit-ios-01",
        "vlan_vid": None,
    },
    {
        "logical_name": "users-vlan-prefix",
        "prefix": "10.60.10.0/24",
        "description": "NCDP VLAN 10 USERS prefix",
        "vlan_vid": 10,
    },
    {
        "logical_name": "servers-vlan-prefix",
        "prefix": "10.60.20.0/24",
        "description": "NCDP VLAN 20 SERVERS prefix",
        "vlan_vid": 20,
    },
    {
        "logical_name": "routing-identity-pool",
        "prefix": "10.60.255.0/24",
        "description": "NCDP router-ID / loopback allocation pool",
        "vlan_vid": None,
    },
)

VLAN_SPECS = {
    10: {"name": "USERS", "description": "NCDP USERS service identity"},
    20: {"name": "SERVERS", "description": "NCDP SERVERS service identity"},
}

ROUTED_IP_SPECS = (
    {
        "logical_link": "core-junos-link",
        "address": "10.60.0.1/30",
        "device_id": 1,
        "device_name": "core-02",
        "interface_id": 11,
        "interface_name": "GigabitEthernet4",
    },
    {
        "logical_link": "core-junos-link",
        "address": "10.60.0.2/30",
        "device_id": 2,
        "device_name": "edge-junos-01",
        "interface_id": 12,
        "interface_name": "ge-0/0/0",
    },
    {
        "logical_link": "core-transit-link",
        "address": "10.60.0.5/30",
        "device_id": 1,
        "device_name": "core-02",
        "interface_id": 2,
        "interface_name": "GigabitEthernet2",
    },
    {
        "logical_link": "core-transit-link",
        "address": "10.60.0.6/30",
        "device_id": 8,
        "device_name": "transit-ios-01",
        "interface_id": 14,
        "interface_name": "GigabitEthernet0/1",
    },
    {
        "logical_link": "junos-transit-link",
        "address": "10.60.0.9/30",
        "device_id": 2,
        "device_name": "edge-junos-01",
        "interface_id": 4,
        "interface_name": "ge-0/0/1",
    },
    {
        "logical_link": "junos-transit-link",
        "address": "10.60.0.10/30",
        "device_id": 8,
        "device_name": "transit-ios-01",
        "interface_id": 15,
        "interface_name": "GigabitEthernet0/2",
    },
)

MANAGEMENT_ADDRESSES = frozenset(
    {
        "192.168.4.14/24",
        "192.168.4.20/24",
        "192.168.4.16/24",
        "192.168.4.17/24",
        "192.168.4.30/24",
        "192.168.4.40/24",
        "192.168.4.31/24",
        "192.168.4.32/24",
    }
)


class MigrationError(RuntimeError):
    """Bounded local-authority failure without administrative output."""


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
    """Run the reviewed migration through the accepted local admin shell."""
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
            "'<ncdp-b3-data-plane-migration>', 'exec'))",
        ],
        input=f"{source}\n\nmigration_main()\n",
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
        shell=False,
    )
    if command.returncode != 0:
        raise MigrationError("NetBox B3-5 migration failed")
    matches = [
        line.removeprefix(RESULT_PREFIX)
        for line in command.stdout.splitlines()
        if line.startswith(RESULT_PREFIX)
    ]
    if len(matches) != 1:
        raise MigrationError("NetBox B3-5 migration result is missing or ambiguous")
    try:
        result = json.loads(matches[0])
    except json.JSONDecodeError:
        raise MigrationError("NetBox B3-5 migration result is invalid") from None
    if not isinstance(result, dict):
        raise MigrationError("NetBox B3-5 migration result is invalid")
    return result


def migration_main() -> None:
    """Apply and verify the one exact B3-5 authority transition."""
    from dcim.models import Device, Interface, Site
    from django.contrib.contenttypes.models import ContentType
    from django.db import transaction
    from extras.models import Tag
    from ipam.models import VLAN, IPAddress, Prefix
    from users.models import ObjectPermission, User

    if os.environ.get(INSIDE_MARKER) != "1":
        raise MigrationError("NetBox B3-5 migration context is invalid")

    changes: dict[str, list[str]] = {"created": [], "updated": [], "reused": []}

    def save(instance: Any) -> None:
        instance.full_clean()
        instance.save()

    def exact_one(model: Any, noun: str, **filters: Any) -> Any:
        matches = list(model.objects.filter(**filters))
        if len(matches) != 1:
            raise MigrationError(f"NetBox requires exactly one {noun}")
        return matches[0]

    def add_tag(instance: Any, tag: Any, noun: str) -> None:
        if instance.tags.filter(pk=tag.pk).exists():
            return
        instance.tags.add(tag)
        changes["updated"].append(f"{noun}:{instance.pk}:tag+{tag.slug}")

    def management_snapshot() -> tuple[tuple[object, ...], ...]:
        devices = tuple(
            (device.pk, device.name, device.primary_ip4_id)
            for device in Device.objects.filter(pk__in=(1, 2, 8, 9)).order_by("pk")
        )
        ips = tuple(
            (
                value.pk,
                str(value.address),
                value.assigned_object_type_id,
                value.assigned_object_id,
                tuple(value.tags.order_by("slug").values_list("slug", flat=True)),
            )
            for value in IPAddress.objects.filter(
                address__in=MANAGEMENT_ADDRESSES
            ).order_by("pk")
        )
        if len(devices) != 4 or len(ips) != len(MANAGEMENT_ADDRESSES):
            raise MigrationError("NetBox management authority is incomplete")
        return devices + ips

    def ensure_tag() -> Any:
        matches = list(Tag.objects.filter(slug=DATA_PLANE_TAG))
        if len(matches) > 1:
            raise MigrationError("NetBox data-plane tag is ambiguous")
        if not matches:
            value = Tag(name=DATA_PLANE_TAG, slug=DATA_PLANE_TAG, color="455a64")
            save(value)
            changes["created"].append(f"tag:{DATA_PLANE_TAG}:{value.pk}")
            return value
        value = matches[0]
        if value.name != DATA_PLANE_TAG:
            raise MigrationError("NetBox data-plane tag conflicts")
        changes["reused"].append(f"tag:{DATA_PLANE_TAG}:{value.pk}")
        return value

    def ensure_vlan(site: Any, tag: Any, vid: int, spec: dict[str, str]) -> Any:
        matches = list(VLAN.objects.filter(vid=vid))
        name_conflicts = VLAN.objects.filter(name=spec["name"]).exclude(vid=vid)
        if len(matches) > 1:
            raise MigrationError(f"NetBox VLAN {vid} is ambiguous")
        if name_conflicts.exists():
            raise MigrationError(f"NetBox VLAN {spec['name']} conflicts")
        if not matches:
            value = VLAN(
                site=site,
                vid=vid,
                name=spec["name"],
                status="active",
                description=spec["description"],
            )
            save(value)
            changes["created"].append(f"vlan:{vid}:{value.pk}")
        else:
            value = matches[0]
            if (
                value.site_id != site.pk
                or value.group_id is not None
                or value.name != spec["name"]
                or value.status != "active"
                or value.description != spec["description"]
            ):
                raise MigrationError(f"NetBox VLAN {vid} conflicts")
            changes["reused"].append(f"vlan:{vid}:{value.pk}")
        add_tag(value, tag, "vlan")
        return value

    def ensure_prefix(
        site: Any,
        site_type: Any,
        tag: Any,
        vlans: dict[int, Any],
        spec: dict[str, Any],
    ) -> Any:
        matches = list(Prefix.objects.filter(prefix=spec["prefix"]))
        if len(matches) > 1:
            raise MigrationError(f"NetBox prefix is ambiguous: {spec['prefix']}")
        vlan = vlans.get(spec["vlan_vid"])
        if not matches:
            value = Prefix(
                prefix=spec["prefix"],
                scope_type=site_type,
                scope_id=site.pk,
                status="active",
                vlan=vlan,
                description=spec["description"],
            )
            save(value)
            changes["created"].append(f"prefix:{spec['prefix']}:{value.pk}")
        else:
            value = matches[0]
            if (
                value.scope_type_id != site_type.pk
                or value.scope_id != site.pk
                or value.vrf_id is not None
                or value.status != "active"
                or value.vlan_id != (vlan.pk if vlan else None)
                or value.description != spec["description"]
                or value.is_pool
                or value.mark_utilized
            ):
                raise MigrationError(f"NetBox prefix conflicts: {spec['prefix']}")
            changes["reused"].append(f"prefix:{spec['prefix']}:{value.pk}")
        add_tag(value, tag, "prefix")
        return value

    def expected_interface(spec: dict[str, Any]) -> Any:
        matches = list(
            Interface.objects.filter(
                pk=spec["interface_id"],
                name=spec["interface_name"],
                device_id=spec["device_id"],
                device__name=spec["device_name"],
            )
        )
        if len(matches) != 1:
            raise MigrationError(
                "NetBox routed interface identity conflicts: "
                f"{spec['device_name']}/{spec['interface_name']}"
            )
        return matches[0]

    def ensure_ip(tag: Any, spec: dict[str, Any]) -> Any:
        interface = expected_interface(spec)
        host = spec["address"].split("/", maxsplit=1)[0]
        matches = list(IPAddress.objects.filter(address__net_host=host))
        if len(matches) > 1:
            raise MigrationError(f"NetBox IP address is ambiguous: {host}")
        description = f"NCDP {spec['logical_link']} endpoint"
        if not matches:
            value = IPAddress(
                address=spec["address"],
                status="active",
                assigned_object=interface,
                description=description,
            )
            save(value)
            changes["created"].append(f"ip:{spec['address']}:{value.pk}")
        else:
            value = matches[0]
            if (
                str(value.address) != spec["address"]
                or value.status != "active"
                or value.assigned_object_type.model != "interface"
                or value.assigned_object_id != interface.pk
                or value.description != description
            ):
                raise MigrationError(f"NetBox IP address conflicts: {host}")
            changes["reused"].append(f"ip:{spec['address']}:{value.pk}")
        add_tag(interface, tag, "interface")
        add_tag(value, tag, "ip")
        return value

    def ensure_read_permission() -> Any:
        reader = exact_one(User, "NCDP reader user", username="ncdp-netbox-reader")
        if not reader.is_active:
            raise MigrationError("NetBox NCDP reader user is inactive")
        expected_types = {
            ContentType.objects.get_for_model(Prefix),
            ContentType.objects.get_for_model(VLAN),
        }
        matches = list(ObjectPermission.objects.filter(name=READ_PERMISSION_NAME))
        if len(matches) > 1:
            raise MigrationError("NetBox data-plane read permission is ambiguous")
        if not matches:
            value = ObjectPermission(
                name=READ_PERMISSION_NAME,
                enabled=True,
                actions=["view"],
                constraints=None,
                description="GET-only NCDP reference data-plane VLAN/prefix authority",
            )
            save(value)
            value.object_types.set(expected_types)
            value.users.set((reader,))
            changes["created"].append(f"permission:{value.pk}")
            return value
        value = matches[0]
        if (
            not value.enabled
            or value.actions != ["view"]
            or value.constraints is not None
            or set(value.object_types.all()) != expected_types
            or set(value.users.all()) != {reader}
            or value.groups.exists()
        ):
            raise MigrationError("NetBox data-plane read permission conflicts")
        changes["reused"].append(f"permission:{value.pk}")
        return value

    with transaction.atomic():
        site = exact_one(Site, "lab site", slug="lab")
        if site.name != "lab" or site.status != "active":
            raise MigrationError("NetBox lab site conflicts")
        before_management = management_snapshot()
        expected_prefixes = {spec["prefix"] for spec in PREFIX_SPECS}
        parent_network = ipaddress.ip_network("10.60.0.0/16")
        conflicting_prefixes = [
            str(value.prefix)
            for value in Prefix.objects.all()
            if ipaddress.ip_network(str(value.prefix)).overlaps(parent_network)
            and str(value.prefix) not in expected_prefixes
        ]
        if conflicting_prefixes:
            raise MigrationError("NetBox data-plane prefix space conflicts")
        tag = ensure_tag()
        vlans = {
            vid: ensure_vlan(site, tag, vid, spec) for vid, spec in VLAN_SPECS.items()
        }
        site_type = ContentType.objects.get_for_model(site)
        prefixes = {
            spec["logical_name"]: ensure_prefix(site, site_type, tag, vlans, spec)
            for spec in PREFIX_SPECS
        }
        routed_ips = tuple(ensure_ip(tag, spec) for spec in ROUTED_IP_SPECS)
        permission = ensure_read_permission()
        if management_snapshot() != before_management:
            raise MigrationError("NetBox management authority changed")

        tagged_prefixes = list(Prefix.objects.filter(tags=tag).order_by("prefix"))
        tagged_vlans = list(VLAN.objects.filter(tags=tag).order_by("vid"))
        tagged_ips = list(IPAddress.objects.filter(tags=tag).order_by("address"))
        tagged_interfaces = list(Interface.objects.filter(tags=tag).order_by("pk"))
        if (
            {str(value.prefix) for value in tagged_prefixes} != expected_prefixes
            or {value.vid for value in tagged_vlans} != set(VLAN_SPECS)
            or {str(value.address) for value in tagged_ips}
            != {spec["address"] for spec in ROUTED_IP_SPECS}
            or {value.pk for value in tagged_interfaces}
            != {spec["interface_id"] for spec in ROUTED_IP_SPECS}
        ):
            raise MigrationError("NetBox data-plane tagged population is not exact")
        if set(Device.objects.filter(primary_ip4__in=routed_ips)):
            raise MigrationError("NetBox routed IP became a device primary address")

        result = {
            "schema_version": "1",
            "changes": changes,
            "tag": {"id": tag.pk, "slug": tag.slug},
            "permission": {
                "id": permission.pk,
                "name": permission.name,
                "actions": permission.actions,
                "user": "ncdp-netbox-reader",
                "object_types": ["ipam.prefix", "ipam.vlan"],
            },
            "prefixes": [
                {
                    "logical_name": logical_name,
                    "id": value.pk,
                    "prefix": str(value.prefix),
                    "vlan_id": value.vlan_id,
                }
                for logical_name, value in prefixes.items()
            ],
            "vlans": [
                {"id": value.pk, "vid": value.vid, "name": value.name}
                for value in vlans.values()
            ],
            "routed_ips": [
                {
                    "id": value.pk,
                    "address": str(value.address),
                    "interface_id": spec["interface_id"],
                    "device": spec["device_name"],
                    "interface": spec["interface_name"],
                }
                for spec, value in zip(ROUTED_IP_SPECS, routed_ips, strict=True)
            ],
            "management_unchanged": True,
        }
    print(RESULT_PREFIX + json.dumps(result, sort_keys=True, separators=(",", ":")))


def main() -> int:
    if len(__import__("sys").argv) != 1:
        print("command-line arguments are not accepted", file=__import__("sys").stderr)
        return 2
    try:
        result = run_operator_migration()
    except (MigrationError, OSError, subprocess.SubprocessError) as error:
        print(str(error), file=__import__("sys").stderr)
        return 2
    print(
        "NetBox B3-5 data-plane migration: "
        f"created={len(result['changes']['created'])} "
        f"updated={len(result['changes']['updated'])} "
        f"reused={len(result['changes']['reused'])}"
    )
    for prefix in result["prefixes"]:
        print(f"prefix {prefix['id']} {prefix['prefix']}")
    for vlan in result["vlans"]:
        print(f"VLAN {vlan['id']} vid={vlan['vid']} name={vlan['name']}")
    for address in result["routed_ips"]:
        print(
            f"IP {address['id']} {address['address']} -> "
            f"{address['device']}/{address['interface']} "
            f"interface-id={address['interface_id']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
