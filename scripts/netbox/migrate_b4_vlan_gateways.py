#!/usr/bin/env python3
"""Establish exact Detour B4-3 VLAN gateway authority in local NetBox.

The wrapper admits only the established loopback-only NetBox container and
executes this reviewed source through ``nbshell``. The transaction has no delete
path, is idempotent, and emits only stable, non-secret identity evidence.
"""

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
INSIDE_MARKER = "NCDP_B4_VLAN_GATEWAYS_INSIDE"
RESULT_PREFIX = "NCDP_B4_VLAN_GATEWAYS_RESULT="
GATEWAY_TAG = "ncdp-vlan-gateway"
DATA_PLANE_TAG = "ncdp-data-plane"
ROUTING_IDENTITY_TAG = "ncdp-routing-identity"

VLAN_SPECS = (
    {"id": 1, "vid": 10, "name": "USERS", "prefix_id": 6, "prefix": "10.60.10.0/24"},
    {"id": 2, "vid": 20, "name": "SERVERS", "prefix_id": 7, "prefix": "10.60.20.0/24"},
)
SUBINTERFACE_SPECS = (
    {
        "name": "GigabitEthernet3.10",
        "vlan": 10,
        "address": "10.60.10.1/24",
        "description": "NCDP VLAN 10 USERS gateway",
    },
    {
        "name": "GigabitEthernet3.20",
        "vlan": 20,
        "address": "10.60.20.1/24",
        "description": "NCDP VLAN 20 SERVERS gateway",
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
EXPECTED_DATA_PLANE_IP_IDS = frozenset({17, 18, 19, 20, 21, 22})
EXPECTED_ROUTING_IDENTITY_IP_IDS = frozenset({23, 24, 25})


class MigrationError(RuntimeError):
    """Bounded migration failure that never includes administrative output."""


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
        or ports.get("8080/tcp") != [{"HostIp": "127.0.0.1", "HostPort": "8000"}]
    ):
        raise MigrationError("local NetBox container boundary is invalid")


def run_operator_migration() -> dict[str, Any]:
    """Run the reviewed migration through the established local admin shell."""
    inspected = subprocess.run(
        ["docker", "inspect", CONTAINER],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
        shell=False,
    )
    validate_container_identity(inspected.stdout)
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
            "'<ncdp-b4-vlan-gateway-migration>', 'exec'))",
        ],
        input=f"{source}\n\nmigration_main()\n",
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
        shell=False,
    )
    if command.returncode != 0:
        raise MigrationError("NetBox B4-3 VLAN gateway migration failed")
    matches = [
        line.removeprefix(RESULT_PREFIX)
        for line in command.stdout.splitlines()
        if line.startswith(RESULT_PREFIX)
    ]
    if len(matches) != 1:
        raise MigrationError("NetBox B4-3 migration result is missing or ambiguous")
    try:
        result = json.loads(matches[0])
    except json.JSONDecodeError:
        raise MigrationError("NetBox B4-3 migration result is invalid") from None
    if not isinstance(result, dict):
        raise MigrationError("NetBox B4-3 migration result is invalid")
    return result


def migration_main() -> None:
    """Apply and verify the exact VLAN gateway authority transaction."""
    from dcim.models import Cable, Device, Interface
    from django.db import transaction
    from extras.models import Tag
    from ipam.models import VLAN, IPAddress, Prefix

    if os.environ.get(INSIDE_MARKER) != "1":
        raise MigrationError("NetBox B4-3 migration context is invalid")
    changes: dict[str, list[str]] = {"created": [], "updated": [], "reused": []}

    def save(instance: Any) -> None:
        instance.full_clean()
        instance.save()

    def exact_one(model: Any, noun: str, **filters: Any) -> Any:
        matches = list(model.objects.filter(**filters))
        if len(matches) != 1:
            raise MigrationError(f"NetBox requires exactly one {noun}")
        return matches[0]

    def management_snapshot() -> tuple[tuple[object, ...], ...]:
        devices = tuple(
            (item.pk, item.name, item.primary_ip4_id)
            for item in Device.objects.filter(pk__in=(1, 2, 8, 9)).order_by("pk")
        )
        addresses = tuple(
            (
                item.pk,
                str(item.address),
                item.assigned_object_type_id,
                item.assigned_object_id,
                tuple(item.tags.order_by("slug").values_list("slug", flat=True)),
            )
            for item in IPAddress.objects.filter(
                address__in=MANAGEMENT_ADDRESSES
            ).order_by("pk")
        )
        if len(devices) != 4 or len(addresses) != len(MANAGEMENT_ADDRESSES):
            raise MigrationError("NetBox management authority is incomplete")
        return devices + addresses

    def ensure_tag() -> Any:
        matches = list(Tag.objects.filter(slug=GATEWAY_TAG))
        if len(matches) > 1:
            raise MigrationError("NetBox VLAN gateway tag is ambiguous")
        if not matches:
            tag = Tag(name=GATEWAY_TAG, slug=GATEWAY_TAG, color="00897b")
            save(tag)
            changes["created"].append(f"tag:{GATEWAY_TAG}:{tag.pk}")
            return tag
        tag = matches[0]
        if tag.name != GATEWAY_TAG:
            raise MigrationError("NetBox VLAN gateway tag conflicts")
        changes["reused"].append(f"tag:{GATEWAY_TAG}:{tag.pk}")
        return tag

    def ensure_subinterface(
        core: Any, parent: Any, tag: Any, spec: dict[str, Any]
    ) -> Any:
        matches = list(Interface.objects.filter(device=core, name=spec["name"]))
        if len(matches) > 1:
            raise MigrationError("NetBox gateway subinterface is ambiguous")
        if not matches:
            interface = Interface(
                device=core,
                name=spec["name"],
                type="virtual",
                parent=parent,
                description=spec["description"],
                enabled=True,
            )
            save(interface)
            changes["created"].append(f"interface:{spec['name']}:{interface.pk}")
        else:
            interface = matches[0]
            if (
                interface.type != "virtual"
                or interface.parent_id != parent.pk
                or interface.description != spec["description"]
                or not interface.enabled
                or interface.cable_id is not None
                or interface.mode
                or interface.untagged_vlan_id is not None
                or interface.tagged_vlans.exists()
            ):
                raise MigrationError("NetBox gateway subinterface conflicts")
            changes["reused"].append(f"interface:{spec['name']}:{interface.pk}")
        if not interface.tags.filter(pk=tag.pk).exists():
            interface.tags.add(tag)
            changes["updated"].append(f"interface:{interface.pk}:tag+{tag.slug}")
        if interface.tags.filter(slug=DATA_PLANE_TAG).exists():
            raise MigrationError("NetBox gateway interface has routed population tag")
        return interface

    def ensure_gateway(interface: Any, tag: Any, spec: dict[str, Any]) -> Any:
        host = spec["address"].split("/", 1)[0]
        matches = list(IPAddress.objects.filter(address__net_host=host))
        if len(matches) > 1:
            raise MigrationError("NetBox VLAN gateway address is ambiguous")
        if not matches:
            value = IPAddress(
                address=spec["address"],
                status="active",
                description=spec["description"],
                assigned_object=interface,
            )
            save(value)
            changes["created"].append(f"ip:{spec['address']}:{value.pk}")
        else:
            value = matches[0]
            if (
                str(value.address) != spec["address"]
                or value.status != "active"
                or value.description != spec["description"]
                or value.assigned_object_type.model != "interface"
                or value.assigned_object_id != interface.pk
            ):
                raise MigrationError("NetBox VLAN gateway address conflicts")
            changes["reused"].append(f"ip:{spec['address']}:{value.pk}")
        if not value.tags.filter(pk=tag.pk).exists():
            value.tags.add(tag)
            changes["updated"].append(f"ip:{value.pk}:tag+{tag.slug}")
        if value.tags.filter(slug=DATA_PLANE_TAG).exists():
            raise MigrationError("NetBox gateway address has routed population tag")
        if Device.objects.filter(primary_ip4=value).exists():
            raise MigrationError("NetBox VLAN gateway became a device primary address")
        return value

    with transaction.atomic():
        before_management = management_snapshot()
        core = exact_one(Device, "core device", pk=1, name="core-02")
        access = exact_one(Device, "access device", pk=9, name="access-sw-01")
        parent = exact_one(
            Interface,
            "core trunk parent",
            pk=7,
            device=core,
            name="GigabitEthernet3",
        )
        trunk = exact_one(
            Interface,
            "access trunk",
            pk=18,
            device=access,
            name="GigabitEthernet0/1",
        )
        users_port = exact_one(
            Interface,
            "USERS access port",
            pk=19,
            device=access,
            name="GigabitEthernet0/2",
        )
        servers_port = exact_one(
            Interface,
            "SERVERS access port",
            pk=20,
            device=access,
            name="GigabitEthernet0/3",
        )
        cable = exact_one(Cable, "core/access cable", pk=4, status="connected")
        termination_ids = {
            (item.termination_type.model, item.termination_id)
            for item in cable.terminations.all()
        }
        if termination_ids != {("interface", parent.pk), ("interface", trunk.pk)}:
            raise MigrationError("NetBox core/access cable conflicts")
        if users_port.cable_id is not None or servers_port.cable_id is not None:
            raise MigrationError("NetBox access service port is unexpectedly cabled")
        if any(
            item.mode or item.untagged_vlan_id is not None or item.tagged_vlans.exists()
            for item in (parent, trunk, users_port, servers_port)
        ):
            raise MigrationError("NetBox L2 deployment fields are populated")

        for spec in VLAN_SPECS:
            vlan = exact_one(VLAN, f"VLAN {spec['vid']}", pk=spec["id"])
            prefix = exact_one(
                Prefix, f"VLAN {spec['vid']} prefix", pk=spec["prefix_id"]
            )
            if (
                vlan.vid != spec["vid"]
                or vlan.name != spec["name"]
                or vlan.status != "active"
                or str(prefix.prefix) != spec["prefix"]
                or prefix.status != "active"
                or prefix.vlan_id != vlan.pk
            ):
                raise MigrationError("NetBox VLAN/prefix authority conflicts")

        data_plane = exact_one(Tag, "data-plane tag", slug=DATA_PLANE_TAG)
        routing = exact_one(Tag, "routing-identity tag", slug=ROUTING_IDENTITY_TAG)
        if (
            set(IPAddress.objects.filter(tags=data_plane).values_list("pk", flat=True))
            != EXPECTED_DATA_PLANE_IP_IDS
        ):
            raise MigrationError("NetBox routed IP population changed")
        if (
            set(IPAddress.objects.filter(tags=routing).values_list("pk", flat=True))
            != EXPECTED_ROUTING_IDENTITY_IP_IDS
        ):
            raise MigrationError("NetBox routing-identity population changed")

        tag = ensure_tag()
        interfaces = tuple(
            ensure_subinterface(core, parent, tag, spec) for spec in SUBINTERFACE_SPECS
        )
        gateways = tuple(
            ensure_gateway(interface, tag, spec)
            for interface, spec in zip(interfaces, SUBINTERFACE_SPECS, strict=True)
        )
        tagged_interfaces = list(Interface.objects.filter(tags=tag).order_by("pk"))
        tagged_ips = list(IPAddress.objects.filter(tags=tag).order_by("pk"))
        if (
            {item.pk for item in tagged_interfaces} != {item.pk for item in interfaces}
            or {item.pk for item in tagged_ips} != {item.pk for item in gateways}
            or any(item.parent_id != parent.pk for item in interfaces)
            or any(
                item.assigned_object_id != interface.pk
                for item, interface in zip(gateways, interfaces, strict=True)
            )
            or management_snapshot() != before_management
        ):
            raise MigrationError("NetBox VLAN gateway authority is not exact")

        result = {
            "schema_version": "1",
            "changes": changes,
            "tag": {"id": tag.pk, "slug": tag.slug},
            "parent": {"id": parent.pk, "device_id": core.pk, "name": parent.name},
            "access_interfaces": [
                {"id": item.pk, "name": item.name, "cable_id": item.cable_id}
                for item in (trunk, users_port, servers_port)
            ],
            "cable": {"id": cable.pk, "endpoints": sorted(termination_ids)},
            "gateways": [
                {
                    "vlan": spec["vlan"],
                    "interface_id": interface.pk,
                    "interface": interface.name,
                    "ip_id": gateway.pk,
                    "address": str(gateway.address),
                }
                for spec, interface, gateway in zip(
                    SUBINTERFACE_SPECS, interfaces, gateways, strict=True
                )
            ],
            "management_unchanged": True,
            "data_plane_ip_ids": sorted(EXPECTED_DATA_PLANE_IP_IDS),
            "routing_identity_ip_ids": sorted(EXPECTED_ROUTING_IDENTITY_IP_IDS),
        }
    print(RESULT_PREFIX + json.dumps(result, sort_keys=True, separators=(",", ":")))


def main() -> int:
    try:
        result = run_operator_migration()
    except (MigrationError, subprocess.SubprocessError):
        print("NetBox B4-3 VLAN gateway migration failed", flush=True)
        return 2
    changes = result.get("changes", {})
    created = len(changes.get("created", [])) if isinstance(changes, dict) else 0
    updated = len(changes.get("updated", [])) if isinstance(changes, dict) else 0
    reused = len(changes.get("reused", [])) if isinstance(changes, dict) else 0
    print(
        "NetBox B4-3 VLAN gateway migration: "
        f"created={created} updated={updated} reused={reused}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
