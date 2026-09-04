"""Strict run-scoped host trust for profiled disposable staging."""

from __future__ import annotations

import base64
import hashlib
import os
import socket
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path

import paramiko

from network_change_delivery.architecture_contracts import get_automation_profile
from network_change_delivery.profile_inventory import ProfiledInventoryDevice
from network_change_delivery.profiled_realization import (
    CmlAnchoredHostTrustGeneration,
    CmlAnchoredHostTrustRecord,
    EvidenceReference,
    RealizationEnvironment,
    RealizationLifecycleState,
    SSHHostKeyType,
    StagingRealizationContext,
)


class ProfiledStagingTrustError(ValueError):
    """Bounded strict-trust failure without public-key output."""


KNOWN_HOSTS_NAME = "known_hosts"
HOST_KEY_SAMPLES = 3


def _private_directory(path: Path) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    metadata = path.lstat()
    if (
        path.is_symlink()
        or not path.is_dir()
        or metadata.st_uid != os.getuid()
        or stat.S_IMODE(metadata.st_mode) != 0o700
    ):
        raise ProfiledStagingTrustError("staging trust root rejected")


def _fingerprint(encoded: str) -> str:
    try:
        key = base64.b64decode(encoded, validate=True)
    except ValueError:
        raise ProfiledStagingTrustError("staging host key rejected") from None
    if not key:
        raise ProfiledStagingTrustError("staging host key rejected")
    encoded = base64.b64encode(hashlib.sha256(key).digest()).decode().rstrip("=")
    return "SHA256:" + encoded


def _observe_server_key(host: str, port: int) -> tuple[SSHHostKeyType, str, str]:
    """Observe the negotiated server key through one direct SSH handshake."""
    transport: paramiko.Transport | None = None
    try:
        connection = socket.create_connection((host, port), timeout=10)
        transport = paramiko.Transport(connection)
        transport.start_client(timeout=10)
        key = transport.get_remote_server_key()
        key_type = SSHHostKeyType(key.get_name())
        encoded = key.get_base64()
    except (OSError, EOFError, ValueError, paramiko.SSHException):
        raise ProfiledStagingTrustError("staging host-key acquisition failed") from None
    finally:
        if transport is not None:
            transport.close()
    return key_type, _fingerprint(encoded), encoded


def _stable_server_key(host: str, port: int) -> tuple[SSHHostKeyType, str, str]:
    samples = tuple(_observe_server_key(host, port) for _ in range(HOST_KEY_SAMPLES))
    if len(set(samples)) != 1:
        raise ProfiledStagingTrustError("staging host-key identity is unstable")
    return samples[0]


def establish_profiled_staging_trust(
    context: StagingRealizationContext,
    devices: tuple[ProfiledInventoryDevice, ...],
    root: Path,
    cml_anchors: dict[str, EvidenceReference],
    *,
    ttl: timedelta = timedelta(hours=1),
) -> CmlAnchoredHostTrustGeneration:
    """Create one exact-four private known_hosts generation for a staging run."""
    if context.lifecycle_state is not RealizationLifecycleState.PREPARING:
        raise ProfiledStagingTrustError("staging trust requires PREPARING realization")
    _private_directory(root)
    if root.name != "trust":
        raise ProfiledStagingTrustError("staging trust root identity rejected")
    path = root / KNOWN_HOSTS_NAME
    if path.exists() or path.is_symlink():
        raise ProfiledStagingTrustError("staging known_hosts already exists")
    admitted = datetime.now(UTC)
    digest = "sha256:" + "0" * 64
    generation = EvidenceReference(
        identity=f"staging-trust:{context.staging_run_id}", digest=digest
    )
    records: list[CmlAnchoredHostTrustRecord] = []
    rendered: list[str] = []
    for device in devices:
        realized = next(
            item
            for item in context.devices
            if item.device_identity == device.device_identity
        )
        profile = get_automation_profile(device.automation_profile_id)
        expected = profile.readiness_services[0]
        endpoint = realized.staging_endpoint.binding.l3_endpoint
        host = str(endpoint.address.ip)
        if endpoint.port != expected.port:
            raise ProfiledStagingTrustError("staging trust endpoint rejected")
        key_type, fingerprint, encoded = _stable_server_key(host, endpoint.port)
        host_field = host if endpoint.port == 22 else f"[{host}]:{endpoint.port}"
        line = f"{host_field} {key_type.value} {encoded}\n"
        rendered.append(line)
        anchor = cml_anchors.get(str(device.logical_name))
        if anchor is None:
            raise ProfiledStagingTrustError("staging CML anchor evidence missing")
        records.append(
            CmlAnchoredHostTrustRecord(
                environment=RealizationEnvironment.STAGING,
                realization_identity=f"staging:{context.staging_run_id}",
                cml_lab_id=context.cml_lab_id,
                cml_node_id=realized.cml_node_id,
                device_identity=device.device_identity,
                logical_name=device.logical_name,
                management_address=host,
                management_port=endpoint.port,
                automation_profile_id=device.automation_profile_id,
                cml_realization_profile_id=device.cml_realization_profile_id,
                host_key_type=key_type,
                host_key_fingerprint=fingerprint,
                cml_anchor_evidence=anchor,
                admitted_at=admitted,
                trust_generation=generation,
            )
        )
    content = "".join(rendered).encode()
    actual = "sha256:" + hashlib.sha256(content).hexdigest()
    generation = EvidenceReference(identity=generation.identity, digest=actual)
    records = [
        record.model_copy(update={"trust_generation": generation}) for record in records
    ]
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError:
        raise ProfiledStagingTrustError(
            "staging known_hosts publication failed"
        ) from None
    try:
        os.write(descriptor, content)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return CmlAnchoredHostTrustGeneration(
        environment=RealizationEnvironment.STAGING,
        realization_identity=f"staging:{context.staging_run_id}",
        cml_lab_id=context.cml_lab_id,
        admitted_at=admitted,
        expires_at=admitted + ttl,
        generation_evidence=generation,
        records=tuple(records),
    )
