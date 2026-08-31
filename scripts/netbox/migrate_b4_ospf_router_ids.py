#!/usr/bin/env python3
"""Allocate the exact Detour B4-2 OSPF router-ID authority in local NetBox.

The host wrapper admits only the established loopback-only NetBox container and
executes this reviewed source through ``nbshell``. The transaction has no delete
path, is idempotent, and emits only stable non-secret identity evidence.
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
INSIDE_MARKER = "NCDP_B4_OSPF_ROUTER_IDS_INSIDE"
RESULT_PREFIX = "NCDP_B4_OSPF_ROUTER_IDS_RESULT="
ROUTING_IDENTITY_TAG = "ncdp-routing-identity"
DATA_PLANE_TAG = "ncdp-data-plane"
POOL_ID = 8
POOL_PREFIX = "10.60.255.0/24"

ROUTER_ID_SPECS = (
    {
        "device_id": 1,
        "device_name": "core-02",
        "address": "10.60.255.1/32",
        "description": "NCDP OSPF router ID for core-02",
    },
    {
        "device_id": 2,
        "device_name": "edge-junos-01",
        "address": "10.60.255.2/32",
        "description": "NCDP OSPF router ID for edge-junos-01",
    },
    {
        "device_id": 8,
        "device_name": "transit-ios-01",
        "address": "10.60.255.3/32",
        "description": "NCDP OSPF router ID for transit-ios-01",
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
    ):
        raise MigrationError("local NetBox Compose identity is invalid")
    if ports.get("8080/tcp") != [{"HostIp": "127.0.0.1", "HostPort": "8000"}]:
        raise MigrationError("local NetBox listener boundary is invalid")


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
            "'<ncdp-b4-ospf-router-id-migration>', 'exec'))",
        ],
        input=f"{source}\n\nmigration_main()\n",
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
        shell=False,
    )
    if command.returncode != 0:
        raise MigrationError("NetBox B4-2 router-ID migration failed")
    matches = [
        line.removeprefix(RESULT_PREFIX)
        for line in command.stdout.splitlines()
        if line.startswith(RESULT_PREFIX)
    ]
    if len(matches) != 1:
        raise MigrationError("NetBox B4-2 migration result is missing or ambiguous")
    try:
        result = json.loads(matches[0])
    except json.JSONDecodeError:
        raise MigrationError("NetBox B4-2 migration result is invalid") from None
    if not isinstance(result, dict):
        raise MigrationError("NetBox B4-2 migration result is invalid")
    return result


def migration_main() -> None:
    """Apply and verify the exact router-ID authority transaction."""
    from dcim.models import Device
    from django.db import transaction
    from extras.models import Tag
    from ipam.models import IPAddress, Prefix

    if os.environ.get(INSIDE_MARKER) != "1":
        raise MigrationError("NetBox B4-2 migration context is invalid")

    changes: dict[str, list[str]] = {"created": [], "updated": [], "reused": []}

    def save(instance: Any) -> None:
        instance.full_clean()
        instance.save()

    def management_snapshot() -> tuple[tuple[object, ...], ...]:
        devices = tuple(
            (device.pk, device.name, device.primary_ip4_id)
            for device in Device.objects.filter(pk__in=(1, 2, 8, 9)).order_by("pk")
        )
        addresses = tuple(
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
        if len(devices) != 4 or len(addresses) != len(MANAGEMENT_ADDRESSES):
            raise MigrationError("NetBox management authority is incomplete")
        return devices + addresses

    def ensure_tag() -> Any:
        matches = list(Tag.objects.filter(slug=ROUTING_IDENTITY_TAG))
        if len(matches) > 1:
            raise MigrationError("NetBox routing-identity tag is ambiguous")
        if not matches:
            value = Tag(
                name=ROUTING_IDENTITY_TAG,
                slug=ROUTING_IDENTITY_TAG,
                color="6a1b9a",
            )
            save(value)
            changes["created"].append(f"tag:{ROUTING_IDENTITY_TAG}:{value.pk}")
            return value
        value = matches[0]
        if value.name != ROUTING_IDENTITY_TAG:
            raise MigrationError("NetBox routing-identity tag conflicts")
        changes["reused"].append(f"tag:{ROUTING_IDENTITY_TAG}:{value.pk}")
        return value

    def exact_device(spec: dict[str, object]) -> Any:
        matches = list(
            Device.objects.filter(pk=spec["device_id"], name=spec["device_name"])
        )
        if len(matches) != 1:
            raise MigrationError("NetBox OSPF device identity conflicts")
        return matches[0]

    def ensure_router_id(tag: Any, spec: dict[str, object]) -> Any:
        device = exact_device(spec)
        host = str(spec["address"]).split("/", maxsplit=1)[0]
        matches = list(IPAddress.objects.filter(address__net_host=host))
        if len(matches) > 1:
            raise MigrationError(f"NetBox router ID is ambiguous: {host}")
        if not matches:
            value = IPAddress(
                address=spec["address"],
                status="active",
                description=spec["description"],
            )
            save(value)
            changes["created"].append(f"ip:{spec['address']}:{value.pk}")
        else:
            value = matches[0]
            if (
                str(value.address) != spec["address"]
                or value.status != "active"
                or value.assigned_object_type_id is not None
                or value.assigned_object_id is not None
                or value.description != spec["description"]
            ):
                raise MigrationError(f"NetBox router ID conflicts: {host}")
            changes["reused"].append(f"ip:{spec['address']}:{value.pk}")
        if value.tags.filter(slug=DATA_PLANE_TAG).exists():
            raise MigrationError("NetBox router ID has data-plane population tag")
        if not value.tags.filter(pk=tag.pk).exists():
            value.tags.add(tag)
            changes["updated"].append(f"ip:{value.pk}:tag+{tag.slug}")
        if device.primary_ip4_id == value.pk:
            raise MigrationError("NetBox router ID became a device primary address")
        return value

    with transaction.atomic():
        pool_matches = list(Prefix.objects.filter(pk=POOL_ID, prefix=POOL_PREFIX))
        if len(pool_matches) != 1:
            raise MigrationError("NetBox routing-identity pool conflicts")
        pool = pool_matches[0]
        before_management = management_snapshot()
        expected_devices = {1: "core-02", 2: "edge-junos-01", 8: "transit-ios-01"}
        if {
            device.pk: device.name
            for device in Device.objects.filter(pk__in=(1, 2, 8)).order_by("pk")
        } != expected_devices:
            raise MigrationError("NetBox OSPF device population conflicts")
        access = list(Device.objects.filter(pk=9, name="access-sw-01"))
        if len(access) != 1:
            raise MigrationError("NetBox access device identity conflicts")

        data_plane = Tag.objects.filter(slug=DATA_PLANE_TAG).first()
        if data_plane is None:
            raise MigrationError("NetBox data-plane authority is missing")
        if set(
            IPAddress.objects.filter(tags=data_plane).values_list("pk", flat=True)
        ) != (EXPECTED_DATA_PLANE_IP_IDS):
            raise MigrationError("NetBox routed IP population changed")

        tag = ensure_tag()
        router_ids = tuple(ensure_router_id(tag, spec) for spec in ROUTER_ID_SPECS)
        if management_snapshot() != before_management:
            raise MigrationError("NetBox management authority changed")
        tagged = list(IPAddress.objects.filter(tags=tag).order_by("address"))
        if (
            len(tagged) != 3
            or tuple(str(value.address) for value in tagged)
            != tuple(spec["address"] for spec in ROUTER_ID_SPECS)
            or any(
                value.assigned_object_type_id is not None
                or value.assigned_object_id is not None
                for value in tagged
            )
            or Device.objects.filter(primary_ip4__in=tagged).exists()
            or access[0].primary_ip4_id in {value.pk for value in tagged}
        ):
            raise MigrationError("NetBox routing-identity population is not exact")
        pool_network = ipaddress.ip_network(str(pool.prefix))
        for value in router_ids:
            router_id = ipaddress.ip_interface(str(value.address)).ip
            if router_id not in pool_network:
                raise MigrationError("NetBox router ID is outside prefix 8")

        result = {
            "schema_version": "1",
            "changes": changes,
            "tag": {"id": tag.pk, "slug": tag.slug},
            "pool": {"id": pool.pk, "prefix": str(pool.prefix)},
            "router_ids": [
                {
                    "id": value.pk,
                    "address": str(value.address),
                    "device_id": spec["device_id"],
                    "device_name": spec["device_name"],
                    "assigned": False,
                    "primary": False,
                }
                for spec, value in zip(ROUTER_ID_SPECS, router_ids, strict=True)
            ],
            "data_plane_ip_ids": sorted(EXPECTED_DATA_PLANE_IP_IDS),
            "management_unchanged": True,
        }
    print(RESULT_PREFIX + json.dumps(result, sort_keys=True, separators=(",", ":")))


def main() -> int:
    try:
        result = run_operator_migration()
    except (MigrationError, subprocess.SubprocessError):
        print("NetBox B4-2 router-ID migration failed", flush=True)
        return 2
    changes = result.get("changes", {})
    created = len(changes.get("created", [])) if isinstance(changes, dict) else 0
    updated = len(changes.get("updated", [])) if isinstance(changes, dict) else 0
    reused = len(changes.get("reused", [])) if isinstance(changes, dict) else 0
    print(
        "NetBox B4-2 router-ID migration: "
        f"created={created} updated={updated} reused={reused}"
    )
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
