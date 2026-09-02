"""Private, realization-bound SSH host trust for persistent Oxidized."""

from __future__ import annotations

import base64
import binascii
import hashlib
import os
import re
import stat
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

EXPECTED_HOSTS = {
    "netbox-device-1": "192.168.4.14",
    "netbox-device-2": "192.168.4.20",
    "netbox-device-8": "192.168.4.16",
    "netbox-device-9": "192.168.4.17",
}
SUPPORTED_KEY_ALGORITHMS = frozenset(
    {
        "ssh-ed25519",
        "ecdsa-sha2-nistp256",
        "ssh-rsa",
    }
)
DEFAULT_TRUST_ROOT = Path("/Users/netdevops/.config/ncdp/oxidized/ssh")
KNOWN_HOSTS_NAME = "known_hosts"
METADATA_NAME = "host-trust.json"
AMBIGUITY_NAME = "host-trust-publication-ambiguous"
MAX_TRUST_BYTES = 16 * 1024
_UUID = re.compile(r"^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$")


class OxidizedHostTrustError(ValueError):
    """Bounded host-trust failure that never exposes public-key bytes."""


class HostTrustNode(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    node: Literal[
        "netbox-device-1",
        "netbox-device-2",
        "netbox-device-8",
        "netbox-device-9",
    ]
    stable_name: Literal["core-02", "edge-junos-01", "transit-ios-01", "access-sw-01"]
    cml_node_id: str
    management_ip: Literal[
        "192.168.4.14", "192.168.4.20", "192.168.4.16", "192.168.4.17"
    ]
    algorithm: Literal[
        "ssh-ed25519",
        "ecdsa-sha2-nistp256",
        "ssh-rsa",
    ]
    fingerprint: str = Field(pattern=r"^SHA256:[A-Za-z0-9+/]{43}$")

    @field_validator("cml_node_id")
    @classmethod
    def valid_uuid(cls, value: str) -> str:
        if not _UUID.fullmatch(value):
            raise ValueError("CML node identity rejected")
        return value


class HostTrustMetadata(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["2"] = "2"
    lab_id: str
    enrolled_at: datetime
    known_hosts_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    nodes: tuple[HostTrustNode, ...]

    @field_validator("lab_id")
    @classmethod
    def valid_lab_uuid(cls, value: str) -> str:
        if not _UUID.fullmatch(value):
            raise ValueError("CML lab identity rejected")
        return value

    @field_validator("enrolled_at")
    @classmethod
    def utc_only(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("host-trust timestamp rejected")
        return value.astimezone(UTC)


def _validate_root(root: Path, *, create: bool = False) -> None:
    if not root.is_absolute() or "audit" in root.parts:
        raise OxidizedHostTrustError("Oxidized host-trust root rejected")
    checkout = Path(__file__).resolve().parents[2]
    try:
        if root.resolve().is_relative_to(checkout.resolve()):
            raise OxidizedHostTrustError("Oxidized host-trust root rejected")
        if create and not root.exists():
            root.mkdir(mode=0o700, parents=True)
        metadata = root.lstat()
    except OSError:
        raise OxidizedHostTrustError("Oxidized host-trust root rejected") from None
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or stat.S_IMODE(metadata.st_mode) != 0o700
    ):
        raise OxidizedHostTrustError("Oxidized host-trust root rejected")


def _private_file(path: Path) -> bytes:
    try:
        metadata = path.lstat()
        value = path.read_bytes()
    except OSError:
        raise OxidizedHostTrustError("Oxidized host trust unavailable") from None
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or metadata.st_nlink != 1
        or not value
        or len(value) > MAX_TRUST_BYTES
    ):
        raise OxidizedHostTrustError("Oxidized host trust unavailable")
    return value


def _fingerprint(encoded_key: str) -> str:
    try:
        key = base64.b64decode(encoded_key, validate=True)
    except (ValueError, binascii.Error):
        raise OxidizedHostTrustError("Oxidized known-host key rejected") from None
    if not key:
        raise OxidizedHostTrustError("Oxidized known-host key rejected")
    digest = base64.b64encode(hashlib.sha256(key).digest()).decode().rstrip("=")
    return f"SHA256:{digest}"


def parse_known_hosts(value: bytes) -> dict[str, tuple[str, str]]:
    """Return exact host -> (algorithm, fingerprint), never key bytes."""
    try:
        text = value.decode("ascii")
    except UnicodeDecodeError:
        raise OxidizedHostTrustError("Oxidized known-host file rejected") from None
    parsed: dict[str, tuple[str, str]] = {}
    for line in text.splitlines():
        fields = line.split()
        if len(fields) != 3:
            raise OxidizedHostTrustError("Oxidized known-host file rejected")
        host, algorithm, encoded = fields
        if (
            host not in EXPECTED_HOSTS.values()
            or algorithm not in SUPPORTED_KEY_ALGORITHMS
        ):
            raise OxidizedHostTrustError("Oxidized known-host identity rejected")
        if host in parsed:
            raise OxidizedHostTrustError("Oxidized known-host identity rejected")
        parsed[host] = (algorithm, _fingerprint(encoded))
    if set(parsed) != set(EXPECTED_HOSTS.values()):
        raise OxidizedHostTrustError("Oxidized known-host population rejected")
    return parsed


def _validate_host_trust(root: Path, *, reject_ambiguity: bool) -> HostTrustMetadata:
    _validate_root(root)
    if reject_ambiguity and (
        (root / AMBIGUITY_NAME).exists() or (root / AMBIGUITY_NAME).is_symlink()
    ):
        raise OxidizedHostTrustError("Oxidized host-trust publication ambiguous")
    known_hosts = _private_file(root / KNOWN_HOSTS_NAME)
    parsed = parse_known_hosts(known_hosts)
    try:
        metadata = HostTrustMetadata.model_validate_json(
            _private_file(root / METADATA_NAME)
        )
    except (ValidationError, ValueError):
        raise OxidizedHostTrustError("Oxidized host-trust metadata rejected") from None
    digest = hashlib.sha256(known_hosts).hexdigest()
    expected_nodes = {
        item.node: (
            item.stable_name,
            item.management_ip,
            item.algorithm,
            item.fingerprint,
        )
        for item in metadata.nodes
    }
    stable_names = {
        "netbox-device-1": "core-02",
        "netbox-device-2": "edge-junos-01",
        "netbox-device-8": "transit-ios-01",
        "netbox-device-9": "access-sw-01",
    }
    if (
        metadata.known_hosts_sha256 != digest
        or set(expected_nodes) != set(EXPECTED_HOSTS)
        or len(metadata.nodes) != 4
        or any(
            expected_nodes[node] != (stable_names[node], ip, *parsed[ip])
            for node, ip in EXPECTED_HOSTS.items()
        )
        or len({item.cml_node_id for item in metadata.nodes}) != 4
    ):
        raise OxidizedHostTrustError("Oxidized host-trust metadata rejected")
    return metadata


def validate_host_trust(root: Path = DEFAULT_TRUST_ROOT) -> HostTrustMetadata:
    return _validate_host_trust(root, reject_ambiguity=True)


def _publish(path: Path, value: bytes) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        os.write(descriptor, value)
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        temporary.replace(path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except OSError:
        raise OxidizedHostTrustError("Oxidized host-trust publication failed") from None
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def publish_host_trust(
    known_hosts: bytes,
    *,
    lab_id: str,
    nodes: tuple[HostTrustNode, ...],
    root: Path = DEFAULT_TRUST_ROOT,
    now: datetime | None = None,
) -> HostTrustMetadata:
    """Durably publish one exact, already CML-anchored trust generation."""
    _validate_root(root, create=True)
    parsed = parse_known_hosts(known_hosts)
    del parsed
    metadata = HostTrustMetadata(
        lab_id=lab_id,
        enrolled_at=now or datetime.now(UTC),
        known_hosts_sha256=hashlib.sha256(known_hosts).hexdigest(),
        nodes=nodes,
    )
    ambiguity = root / AMBIGUITY_NAME
    _publish(ambiguity, b"AMBIGUOUS\n")
    try:
        _publish(root / KNOWN_HOSTS_NAME, known_hosts)
        _publish(root / METADATA_NAME, metadata.model_dump_json().encode() + b"\n")
        _validate_host_trust(root, reject_ambiguity=False)
        ambiguity.unlink()
        directory = os.open(root, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except (OSError, OxidizedHostTrustError):
        raise OxidizedHostTrustError(
            "Oxidized host-trust publication ambiguous"
        ) from None
    return metadata


def retire_host_trust(readiness_path: Path, root: Path = DEFAULT_TRUST_ROOT) -> None:
    """Invalidate collection first, then retire current realization trust."""
    try:
        readiness_path.unlink(missing_ok=True)
        if readiness_path.parent.exists():
            directory = os.open(readiness_path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        _validate_root(root)
        for name in (METADATA_NAME, KNOWN_HOSTS_NAME, AMBIGUITY_NAME):
            (root / name).unlink(missing_ok=True)
        directory = os.open(root, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except OSError:
        raise OxidizedHostTrustError("Oxidized host-trust retirement failed") from None


def retire_main() -> int:
    if len(sys.argv) != 1:
        print("Oxidized host-trust retirement arguments rejected", file=sys.stderr)
        return 2
    try:
        retire_host_trust(
            Path(
                "/Users/netdevops/.local/state/ncdp/oxidized/runtime/"
                "collection-ready.json"
            )
        )
    except (OSError, ValueError):
        print("Oxidized host-trust retirement failed", file=sys.stderr)
        return 2
    print("Oxidized host trust retired")
    return 0
