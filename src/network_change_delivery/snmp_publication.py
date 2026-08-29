"""Secret-free SNMP target file-SD publication contracts."""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from network_change_delivery.audit import (
    NetBoxDeviceIdentity,
    Sha256,
    canonical_json_bytes,
)
from network_change_delivery.observability_private_paths import (
    ObservabilityPrivatePathError,
    ensure_private_tree,
    validate_observability_root,
    validate_private_file,
)
from network_change_delivery.snmp_telemetry import (
    MAX_SNMP_TARGETS,
    SnmpTargetGeneration,
    SnmpTargetIdentity,
    SnmpTargetState,
)

MAX_TARGET_BYTES = 64 * 1024
_ENDPOINT = re.compile(
    r"^(?:[A-Za-z0-9](?:[A-Za-z0-9.-]{0,126}[A-Za-z0-9])?|"
    r"(?:[0-9]{1,3}\.){3}[0-9]{1,3}):([1-9][0-9]{0,4})$"
)


class SnmpTargetPublicationError(ValueError):
    """Bounded target-publication failure without route/provider content."""


class SnmpPollingTarget(BaseModel):
    """One admitted device route and its non-secret exporter selector."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    identity: SnmpTargetIdentity
    endpoint: str = Field(min_length=3, max_length=160)

    @model_validator(mode="after")
    def bounded_endpoint(self) -> SnmpPollingTarget:
        matched = _ENDPOINT.fullmatch(self.endpoint)
        if matched is None or int(matched.group(1)) > 65535:
            raise ValueError("SNMP target endpoint rejected")
        return self


class SnmpTargetPublication(BaseModel):
    """Digest-bound non-secret file-SD publication evidence."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = Field(default="1", pattern=r"^1$")
    state: SnmpTargetState
    target_generation_digest: Sha256
    target_file_sha256: Sha256
    targets: tuple[NetBoxDeviceIdentity, ...] = Field(max_length=MAX_SNMP_TARGETS)
    digest: Sha256

    @model_validator(mode="after")
    def coherent(self) -> SnmpTargetPublication:
        identities = list(self.targets)
        if identities != sorted(identities, key=_identity_number) or len(
            identities
        ) != len(set(identities)):
            raise ValueError("SNMP target publication rejected")
        if self.state is SnmpTargetState.ACTIVE and not identities:
            raise ValueError("SNMP target publication rejected")
        if (
            self.state
            in {
                SnmpTargetState.RETIRED,
                SnmpTargetState.FAILED,
                SnmpTargetState.AMBIGUOUS,
            }
            and identities
        ):
            raise ValueError("SNMP target publication rejected")
        if self.digest != self.calculated_digest():
            raise ValueError("SNMP target publication digest rejected")
        return self

    def calculated_digest(self) -> str:
        content = canonical_json_bytes(self.model_dump(mode="json", exclude={"digest"}))
        return f"sha256:{hashlib.sha256(content).hexdigest()}"


def _identity_number(value: str) -> int:
    return int(value.rsplit(":", 1)[1])


def render_snmp_file_sd(targets: tuple[SnmpPollingTarget, ...]) -> bytes:
    """Render canonical file-SD without credential or transient identity."""
    if len(targets) > MAX_SNMP_TARGETS:
        raise SnmpTargetPublicationError("SNMP target population rejected")
    ordered = sorted(targets, key=lambda item: _identity_number(item.identity.device))
    identities = [item.identity.device for item in ordered]
    endpoints = [item.endpoint for item in ordered]
    if len(identities) != len(set(identities)) or len(endpoints) != len(set(endpoints)):
        raise SnmpTargetPublicationError("SNMP target population rejected")
    return canonical_json_bytes(
        [
            {
                "targets": [target.endpoint],
                "labels": {
                    "instance": target.identity.device,
                    "__param_auth": target.identity.credential.auth_selector,
                },
            }
            for target in ordered
        ]
    )


def _atomic_publish(path: Path, content: bytes) -> None:
    if not content or len(content) > MAX_TARGET_BYTES:
        raise SnmpTargetPublicationError("SNMP target publication rejected")
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(name)
    replaced = False
    try:
        os.fchmod(descriptor, 0o600)
        os.write(descriptor, content)
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        temporary.replace(path)
        replaced = True
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        validate_private_file(path, maximum_bytes=MAX_TARGET_BYTES)
    except OSError as error:
        message = (
            "SNMP target publication ambiguous"
            if replaced
            else "SNMP target publication failed"
        )
        raise SnmpTargetPublicationError(message) from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def publish_snmp_targets(
    root: Path,
    generation: SnmpTargetGeneration,
    targets: tuple[SnmpPollingTarget, ...],
) -> SnmpTargetPublication:
    """Publish file-SD first and non-secret generation evidence second."""
    try:
        validate_observability_root(root)
        ensure_private_tree(root, "discovery", "runtime", "control")
    except ObservabilityPrivatePathError as error:
        raise SnmpTargetPublicationError("SNMP target private path rejected") from error
    active_devices = tuple(
        item.device
        for item in generation.devices
        if item.state is SnmpTargetState.ACTIVE
    )
    target_devices = tuple(
        item.identity.device
        for item in sorted(
            targets, key=lambda item: _identity_number(item.identity.device)
        )
    )
    if target_devices != active_devices:
        raise SnmpTargetPublicationError("SNMP target generation rejected")
    content = render_snmp_file_sd(targets)
    target_hash = f"sha256:{hashlib.sha256(content).hexdigest()}"
    unsigned = SnmpTargetPublication.model_construct(
        schema_version="1",
        state=generation.state,
        target_generation_digest=generation.digest,
        target_file_sha256=target_hash,
        targets=target_devices,
        digest="sha256:" + "0" * 64,
    )
    publication = SnmpTargetPublication.model_validate(
        {
            **unsigned.model_dump(mode="json", exclude={"digest"}),
            "digest": unsigned.calculated_digest(),
        }
    )
    guard = root / "control/snmp-target-publication-ambiguous"
    if guard.exists():
        raise SnmpTargetPublicationError("SNMP target publication ambiguous")
    _atomic_publish(guard, b"AMBIGUOUS\n")
    _atomic_publish(root / "discovery/snmp-targets.json", content)
    _atomic_publish(
        root / "runtime/snmp-target-publication.json",
        canonical_json_bytes(publication.model_dump(mode="json")),
    )
    try:
        guard.unlink()
        descriptor = os.open(guard.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError as error:
        raise SnmpTargetPublicationError("SNMP target publication ambiguous") from error
    return publication
