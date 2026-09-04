"""Strict run-scoped host trust for profiled disposable staging."""

from __future__ import annotations

import base64
import hashlib
import os
import stat
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

from network_change_delivery.architecture_contracts import get_automation_profile
from network_change_delivery.profile_inventory import ProfiledInventoryDevice
from network_change_delivery.profiled_realization import (
    CmlAnchoredHostTrustGeneration,
    CmlAnchoredHostTrustRecord,
    EvidenceReference,
    RealizationEnvironment,
    SSHHostKeyType,
    StagingRealizationContext,
)


class ProfiledStagingTrustError(ValueError):
    """Bounded strict-trust failure without public-key output."""


KNOWN_HOSTS_NAME = "known_hosts"
MAX_SCAN_BYTES = 16 * 1024


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


def _scan(host: str, port: int) -> tuple[SSHHostKeyType, str, str]:
    """Acquire one bounded key without ambient trust or enrollment fallback."""
    try:
        result = subprocess.run(
            ["ssh-keyscan", "-T", "10", "-p", str(port), host],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        raise ProfiledStagingTrustError("staging host-key acquisition failed") from None
    if (
        result.returncode != 0
        or not result.stdout
        or len(result.stdout.encode()) > MAX_SCAN_BYTES
    ):
        raise ProfiledStagingTrustError("staging host-key acquisition failed")
    lines = [line.split() for line in result.stdout.splitlines()]
    accepted = [
        line
        for line in lines
        if len(line) == 3 and line[0] in {host, f"[{host}]:{port}"}
    ]
    if len(accepted) != 1:
        raise ProfiledStagingTrustError("staging host-key identity is ambiguous")
    _, algorithm, encoded = accepted[0]
    try:
        key_type = SSHHostKeyType(algorithm)
    except ValueError:
        raise ProfiledStagingTrustError("staging host-key algorithm rejected") from None
    return key_type, _fingerprint(encoded), " ".join(accepted[0]) + "\n"


def establish_profiled_staging_trust(
    context: StagingRealizationContext,
    devices: tuple[ProfiledInventoryDevice, ...],
    root: Path,
    *,
    ttl: timedelta = timedelta(hours=1),
) -> CmlAnchoredHostTrustGeneration:
    """Create one exact-four private known_hosts generation for a staging run."""
    _private_directory(root)
    if root.name != "trust":
        raise ProfiledStagingTrustError("staging trust root identity rejected")
    admitted = datetime.now(UTC)
    digest = "sha256:" + "0" * 64
    generation = EvidenceReference(
        identity=f"staging-trust:{context.staging_run_id}", digest=digest
    )
    records: list[CmlAnchoredHostTrustRecord] = []
    rendered: list[str] = []
    for device in devices:
        target = context.staging_read_only_target(device)
        realized = next(
            item
            for item in context.devices
            if item.device_identity == device.device_identity
        )
        profile = get_automation_profile(device.automation_profile_id)
        expected = profile.readiness_services[0]
        if target.port != expected.port:
            raise ProfiledStagingTrustError("staging trust endpoint rejected")
        key_type, fingerprint, line = _scan(target.host, target.port)
        rendered.append(line)
        anchor = EvidenceReference(
            identity=f"cml-anchor:{context.cml_lab_id}:{realized.cml_node_id}",
            digest="sha256:"
            + hashlib.sha256(
                f"{context.cml_lab_id}:{realized.cml_node_id}:{device.device_identity}".encode()
            ).hexdigest(),
        )
        records.append(
            CmlAnchoredHostTrustRecord(
                environment=RealizationEnvironment.STAGING,
                realization_identity=f"staging:{context.staging_run_id}",
                cml_lab_id=context.cml_lab_id,
                cml_node_id=realized.cml_node_id,
                device_identity=device.device_identity,
                logical_name=device.logical_name,
                management_address=target.host,
                management_port=target.port,
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
    path = root / KNOWN_HOSTS_NAME
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
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
