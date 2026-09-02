"""Private, fail-closed Oxidized JSONFile source materialization."""

from __future__ import annotations

import json
import os
import uuid
from contextlib import suppress
from dataclasses import dataclass
from ipaddress import IPv4Address
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from network_change_delivery.architecture_contracts import AutomationProfileID
from network_change_delivery.inventory import InventoryError
from network_change_delivery.oxidized_private_paths import (
    OxidizedPrivatePathError,
    ensure_private_directory,
    validate_oxidized_root,
    validate_private_file,
)
from network_change_delivery.profile_inventory import (
    PROFILED_POPULATION_IDENTITIES,
    ProfiledInventoryDevice,
    ProfiledInventoryPopulation,
)
from network_change_delivery.secrets import SecretError, SecretProvider

EXPECTED_IDENTITIES = frozenset(PROFILED_POPULATION_IDENTITIES)
OXIDIZED_MODEL_BY_PROFILE = {
    AutomationProfileID.CAT8000V_IOSXE: "ios",
    AutomationProfileID.VJUNOS_ROUTER: "junos",
    AutomationProfileID.IOSV_159_3_M12: "ios",
    AutomationProfileID.IOSVL2_2020: "ios",
}
SOURCE_GROUP = "managed"
SOURCE_FILENAME = "router.json"


class OxidizedSourceError(ValueError):
    """Raised without credential or upstream response content."""


class OxidizedSourcePublicationAmbiguousError(OxidizedSourceError):
    """Raised after publication visibility changed but durability was not proven."""


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
    changed: bool


def _validate_existing_source(path: Path) -> None:
    try:
        validate_private_file(path, missing_ok=True)
    except OxidizedPrivatePathError as error:
        raise OxidizedSourceError("Oxidized source path rejected") from error


class _ProfileInventory(Protocol):
    def resolve_profiled_population(self) -> ProfiledInventoryPopulation: ...


def _device_id(device: ProfiledInventoryDevice) -> int:
    identity = device.device_identity
    if identity not in EXPECTED_IDENTITIES:
        raise OxidizedSourceError("Oxidized managed population is not exact")
    return int(identity.rsplit(":", maxsplit=1)[1])


def _source_node(
    device: ProfiledInventoryDevice, provider: SecretProvider
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
            ip=device.live_read_only_target().host,
            model=OXIDIZED_MODEL_BY_PROFILE[device.automation_profile_id],
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
    committed = False
    try:
        descriptor = os.open(temporary, flags, 0o600)
        written = 0
        while written < len(payload):
            written += os.write(descriptor, payload[written:])
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        validate_private_file(temporary)
        temporary.replace(path)
        committed = True
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        validate_private_file(path)
    except (OSError, OxidizedPrivatePathError) as error:
        if committed:
            raise OxidizedSourcePublicationAmbiguousError(
                "Oxidized source publication outcome ambiguous"
            ) from error
        raise OxidizedSourceError("Oxidized source publication failed") from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        with suppress(FileNotFoundError):
            temporary.unlink()


def _existing_payload_matches(path: Path, payload: bytes) -> bool:
    """Compare one already-validated private cache without exposing its bytes."""
    if not path.exists():
        return False
    try:
        validate_private_file(path)
        if path.stat().st_size != len(payload):
            return False
        with path.open("rb") as stream:
            return stream.read(len(payload) + 1) == payload
    except (OSError, OxidizedPrivatePathError) as error:
        raise OxidizedSourceError("Oxidized source comparison failed") from error


def materialize_oxidized_source(
    inventory: _ProfileInventory,
    secrets: SecretProvider,
    root: Path,
) -> MaterializedOxidizedSource:
    """Resolve both authorities completely, then atomically publish one source."""
    try:
        validate_oxidized_root(root)
    except OxidizedPrivatePathError as error:
        raise OxidizedSourceError("Oxidized runtime root rejected") from error
    try:
        population = inventory.resolve_profiled_population()
        devices = population.devices
    except InventoryError as error:
        raise OxidizedSourceError(
            "Oxidized managed inventory resolution failed"
        ) from error
    identities = tuple(device.device_identity for device in devices)
    if len(identities) != 4 or set(identities) != EXPECTED_IDENTITIES:
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
    try:
        ensure_private_directory(root)
    except OxidizedPrivatePathError as error:
        raise OxidizedSourceError("Oxidized runtime directory rejected") from error
    runtime = root / "runtime"
    try:
        ensure_private_directory(runtime)
    except OxidizedPrivatePathError as error:
        raise OxidizedSourceError("Oxidized runtime directory rejected") from error
    path = runtime / SOURCE_FILENAME
    changed = not _existing_payload_matches(path, payload)
    if changed:
        _publish(path, payload)
    ordered_identities = tuple(device.device_identity for device in ordered)
    return MaterializedOxidizedSource(path, ordered_identities, names, changed)
