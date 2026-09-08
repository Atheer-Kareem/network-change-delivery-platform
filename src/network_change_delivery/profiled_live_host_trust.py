"""Private scope-bound host trust for the persistent profiled LIVE realization."""

from __future__ import annotations

import base64
import binascii
import hashlib
import os
import stat
import tempfile
from pathlib import Path

from pydantic import ValidationError

from network_change_delivery.profiled_live_cml import (
    CURRENT_LIVE_REALIZATION,
    LIVE_LAB_ID,
    ProfiledLiveRealizationCatalog,
)
from network_change_delivery.profiled_realization import (
    CmlAnchoredHostTrustGeneration,
)

DEFAULT_PROFILED_LIVE_TRUST_ROOT = Path(
    "/Users/netdevops/.config/ncdp/profiled-live/ssh"
)
KNOWN_HOSTS_NAME = "known_hosts"
METADATA_NAME = "host-trust.json"
AMBIGUITY_NAME = "host-trust-publication-ambiguous"
MAX_TRUST_BYTES = 32 * 1024
# Compatibility exports derived from reviewed realization data, not admission logic.
EXPECTED_LIVE_ENDPOINTS = tuple(
    (a.management_address, a.management_port) for a in CURRENT_LIVE_REALIZATION.anchors
)
EXPECTED_LIVE_DEVICE_IDENTITIES = CURRENT_LIVE_REALIZATION.scope.identities
EXPECTED_LIVE_NODE_IDS = tuple(a.cml_node_id for a in CURRENT_LIVE_REALIZATION.anchors)
EXPECTED_LIVE_ADDRESSES = tuple(
    a.management_address for a in CURRENT_LIVE_REALIZATION.anchors
)
SUPPORTED_KEY_ALGORITHMS = frozenset(
    {
        "ssh-rsa",
        "ssh-ed25519",
        "ecdsa-sha2-nistp256",
        "ecdsa-sha2-nistp384",
        "ecdsa-sha2-nistp521",
    }
)


class ProfiledLiveHostTrustError(ValueError):
    """Bounded profiled LIVE trust failure without public-key bytes."""


def _validate_root(root: Path, *, create: bool = False) -> None:
    if not root.is_absolute() or "audit" in root.parts:
        raise ProfiledLiveHostTrustError("profiled LIVE host-trust root rejected")
    checkout = Path(__file__).resolve().parents[2]
    try:
        if root.resolve().is_relative_to(checkout.resolve()):
            raise ProfiledLiveHostTrustError("profiled LIVE host-trust root rejected")
        if create and not root.exists():
            root.mkdir(mode=0o700, parents=True)
        metadata = root.lstat()
    except OSError:
        raise ProfiledLiveHostTrustError(
            "profiled LIVE host-trust root rejected"
        ) from None
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or stat.S_IMODE(metadata.st_mode) != 0o700
    ):
        raise ProfiledLiveHostTrustError("profiled LIVE host-trust root rejected")


def _private_file(path: Path) -> bytes:
    try:
        metadata = path.lstat()
        value = path.read_bytes()
    except OSError:
        raise ProfiledLiveHostTrustError(
            "profiled LIVE host trust unavailable"
        ) from None
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or metadata.st_nlink != 1
        or not value
        or len(value) > MAX_TRUST_BYTES
    ):
        raise ProfiledLiveHostTrustError("profiled LIVE host trust unavailable")
    return value


def _fingerprint(encoded_key: str) -> str:
    try:
        key = base64.b64decode(encoded_key, validate=True)
    except (ValueError, binascii.Error):
        raise ProfiledLiveHostTrustError(
            "profiled LIVE known-host key rejected"
        ) from None
    if not key:
        raise ProfiledLiveHostTrustError("profiled LIVE known-host key rejected")
    digest = base64.b64encode(hashlib.sha256(key).digest()).decode().rstrip("=")
    return f"SHA256:{digest}"


def parse_profiled_live_known_hosts(
    value: bytes, *, catalog: ProfiledLiveRealizationCatalog = CURRENT_LIVE_REALIZATION
) -> dict[str, tuple[str, str]]:
    """Return exact address to algorithm/fingerprint metadata without key bytes."""
    try:
        lines = value.decode("ascii").splitlines()
    except UnicodeDecodeError:
        raise ProfiledLiveHostTrustError(
            "profiled LIVE known-host file rejected"
        ) from None
    expected_addresses = tuple(a.management_address for a in catalog.anchors)
    parsed: dict[str, tuple[str, str]] = {}
    for line in lines:
        fields = line.split()
        if len(fields) != 3:
            raise ProfiledLiveHostTrustError("profiled LIVE known-host file rejected")
        host, algorithm, encoded = fields
        if (
            host not in expected_addresses
            or algorithm not in SUPPORTED_KEY_ALGORITHMS
            or host in parsed
        ):
            raise ProfiledLiveHostTrustError(
                "profiled LIVE known-host identity rejected"
            )
        parsed[host] = (algorithm, _fingerprint(encoded))
    if tuple(parsed) != expected_addresses:
        raise ProfiledLiveHostTrustError("profiled LIVE known-host population rejected")
    return parsed


def _validate_generation(
    known_hosts: bytes,
    generation: CmlAnchoredHostTrustGeneration,
    *,
    catalog: ProfiledLiveRealizationCatalog = CURRENT_LIVE_REALIZATION,
) -> None:
    parsed = parse_profiled_live_known_hosts(known_hosts, catalog=catalog)
    expected_names = tuple(member.logical_name for member in catalog.scope.members)
    if (
        generation.scope != catalog.scope
        or generation.environment.value != "LIVE"
        or generation.realization_identity != "ncdp-live"
        or generation.cml_lab_id != LIVE_LAB_ID
        or tuple(record.logical_name for record in generation.records) != expected_names
        or tuple(record.device_identity for record in generation.records)
        != catalog.scope.identities
        or tuple(record.cml_node_id for record in generation.records)
        != tuple(a.cml_node_id for a in catalog.anchors)
    ):
        raise ProfiledLiveHostTrustError(
            "profiled LIVE trust metadata population rejected"
        )
    known_hosts_digest = f"sha256:{hashlib.sha256(known_hosts).hexdigest()}"
    if generation.generation_evidence.digest != known_hosts_digest:
        raise ProfiledLiveHostTrustError("profiled LIVE trust digest rejected")
    for record, (address, port) in zip(
        generation.records,
        tuple((a.management_address, a.management_port) for a in catalog.anchors),
        strict=True,
    ):
        if (
            str(record.management_address) != address
            or record.management_port != port
            or (record.host_key_type.value, record.host_key_fingerprint)
            != parsed[address]
        ):
            raise ProfiledLiveHostTrustError("profiled LIVE trust record rejected")


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
        raise ProfiledLiveHostTrustError(
            "profiled LIVE host-trust publication failed"
        ) from None
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def publish_profiled_live_host_trust(
    known_hosts: bytes,
    generation: CmlAnchoredHostTrustGeneration,
    root: Path = DEFAULT_PROFILED_LIVE_TRUST_ROOT,
    *,
    catalog: ProfiledLiveRealizationCatalog = CURRENT_LIVE_REALIZATION,
) -> CmlAnchoredHostTrustGeneration:
    """Atomically publish one already CML-anchored scope-bound generation."""
    _validate_root(root, create=True)
    _validate_generation(known_hosts, generation, catalog=catalog)
    ambiguity = root / AMBIGUITY_NAME
    _publish(ambiguity, b"AMBIGUOUS\n")
    try:
        _publish(root / KNOWN_HOSTS_NAME, known_hosts)
        _publish(root / METADATA_NAME, generation.model_dump_json().encode() + b"\n")
        validate_profiled_live_host_trust(root, reject_ambiguity=False, catalog=catalog)
        ambiguity.unlink()
        directory = os.open(root, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except (OSError, ProfiledLiveHostTrustError):
        raise ProfiledLiveHostTrustError(
            "profiled LIVE host-trust publication ambiguous"
        ) from None
    return generation


def validate_profiled_live_host_trust(
    root: Path = DEFAULT_PROFILED_LIVE_TRUST_ROOT,
    *,
    reject_ambiguity: bool = True,
    catalog: ProfiledLiveRealizationCatalog = CURRENT_LIVE_REALIZATION,
) -> CmlAnchoredHostTrustGeneration:
    """Validate private rendering material and its secret-free B3 metadata."""
    _validate_root(root)
    if reject_ambiguity and (
        (root / AMBIGUITY_NAME).exists() or (root / AMBIGUITY_NAME).is_symlink()
    ):
        raise ProfiledLiveHostTrustError(
            "profiled LIVE host-trust publication ambiguous"
        )
    known_hosts = _private_file(root / KNOWN_HOSTS_NAME)
    try:
        generation = CmlAnchoredHostTrustGeneration.model_validate_json(
            _private_file(root / METADATA_NAME)
        )
    except (ValidationError, ValueError):
        raise ProfiledLiveHostTrustError(
            "profiled LIVE host-trust metadata rejected"
        ) from None
    _validate_generation(known_hosts, generation, catalog=catalog)
    return generation
