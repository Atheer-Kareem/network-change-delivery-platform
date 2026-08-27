"""Private, fail-closed Oxidized JSONFile source materialization."""

from __future__ import annotations

import json
import os
import stat
import uuid
from contextlib import suppress
from dataclasses import dataclass
from ipaddress import IPv4Address
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from network_change_delivery.inventory import InventoryError, ManagedInventoryProvider
from network_change_delivery.models import InventoryDevice
from network_change_delivery.secrets import SecretError, SecretProvider

EXPECTED_IDENTITIES = frozenset({"netbox:dcim.device:1", "netbox:dcim.device:2"})
MODEL_MAP = {"cisco_iosxe": "ios", "junos": "junos"}
SOURCE_GROUP = "managed"
SOURCE_FILENAME = "router.json"


class OxidizedSourceError(ValueError):
    """Raised without credential or upstream response content."""


class _PrivateSourceNode(BaseModel):
    model_config = ConfigDict(
        frozen=True, extra="forbid", hide_input_in_errors=True, str_max_length=512
    )

    name: str = Field(pattern=r"^netbox-device-[1-9][0-9]*$", max_length=64)
    ip: IPv4Address
    model: Literal["ios", "junos"]
    group: Literal["managed"]
    username: str = Field(min_length=1, max_length=256, repr=False)
    password: str = Field(min_length=1, max_length=512, repr=False)
    ssh_port: Literal[22]


@dataclass(frozen=True)
class MaterializedOxidizedSource:
    """Non-secret publication result."""

    path: Path
    identities: tuple[str, ...]
    node_names: tuple[str, ...]


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _private_directory(path: Path) -> None:
    try:
        path.mkdir(mode=0o700)
    except FileExistsError:
        pass
    except OSError as error:
        raise OxidizedSourceError("Oxidized runtime directory unavailable") from error
    try:
        metadata = path.lstat()
    except OSError as error:
        raise OxidizedSourceError("Oxidized runtime directory unavailable") from error
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or stat.S_IMODE(metadata.st_mode) != 0o700
    ):
        raise OxidizedSourceError("Oxidized runtime directory rejected")


def _validate_existing_source(path: Path) -> None:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return
    except OSError as error:
        raise OxidizedSourceError("Oxidized source path unavailable") from error
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or metadata.st_nlink != 1
    ):
        raise OxidizedSourceError("Oxidized source path rejected")


def _device_id(device: InventoryDevice) -> int:
    identity = device.inventory_object_id
    if identity not in EXPECTED_IDENTITIES:
        raise OxidizedSourceError("Oxidized managed population is not exact")
    return int(identity.rsplit(":", maxsplit=1)[1])


def _source_node(
    device: InventoryDevice, provider: SecretProvider
) -> _PrivateSourceNode:
    device_id = _device_id(device)
    expected_reference = f"openbao:kv-v2:ncdp/devices/{device_id}/ssh"
    try:
        reference = provider.reference(device)
    except SecretError as error:
        raise OxidizedSourceError("Oxidized credential reference failed") from error
    if reference.source != "openbao" or reference.reference != expected_reference:
        raise OxidizedSourceError("Oxidized credential reference rejected")
    try:
        credentials = provider.load(device)
        return _PrivateSourceNode(
            name=f"netbox-device-{device_id}",
            ip=device.host,
            model=MODEL_MAP[device.platform],
            group=SOURCE_GROUP,
            username=credentials.username,
            password=credentials.password,
            ssh_port=22,
        )
    except (SecretError, ValidationError, KeyError) as error:
        raise OxidizedSourceError("Oxidized credential loading failed") from error


def _publish(path: Path, payload: bytes) -> None:
    _validate_existing_source(path)
    temporary = path.with_name(f".{path.name}.tmp-{uuid.uuid4().hex}")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = -1
    try:
        descriptor = os.open(temporary, flags, 0o600)
        written = 0
        while written < len(payload):
            written += os.write(descriptor, payload[written:])
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        temporary.replace(path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        _validate_existing_source(path)
    except OSError as error:
        raise OxidizedSourceError("Oxidized source publication failed") from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        with suppress(FileNotFoundError):
            temporary.unlink()


def materialize_oxidized_source(
    inventory: ManagedInventoryProvider,
    secrets: SecretProvider,
    root: Path,
) -> MaterializedOxidizedSource:
    """Resolve both authorities completely, then atomically publish one source."""
    if (
        not root.is_absolute()
        or root.name == "audit"
        or _is_within(root, _project_root())
    ):
        raise OxidizedSourceError("Oxidized runtime root rejected")
    try:
        devices = inventory.resolve_managed_devices()
    except InventoryError as error:
        raise OxidizedSourceError(
            "Oxidized managed inventory resolution failed"
        ) from error
    identities = tuple(device.inventory_object_id or "" for device in devices)
    if len(identities) != 2 or set(identities) != EXPECTED_IDENTITIES:
        raise OxidizedSourceError("Oxidized managed population is not exact")
    if len(set(identities)) != len(identities):
        raise OxidizedSourceError("Oxidized managed population contains duplicates")
    ordered = tuple(sorted(devices, key=_device_id))
    nodes = tuple(_source_node(device, secrets) for device in ordered)
    names = tuple(node.name for node in nodes)
    if len(set(names)) != len(names):
        raise OxidizedSourceError("Oxidized node population contains duplicates")
    payload = (
        json.dumps(
            [node.model_dump(mode="json") for node in nodes],
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode()
    _private_directory(root)
    runtime = root / "runtime"
    _private_directory(runtime)
    path = runtime / SOURCE_FILENAME
    _publish(path, payload)
    ordered_identities = tuple(device.inventory_object_id or "" for device in ordered)
    return MaterializedOxidizedSource(path, ordered_identities, names)
