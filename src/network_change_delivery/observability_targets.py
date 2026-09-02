"""Typed, secret-free management-service reachability target contracts."""

from __future__ import annotations

import hashlib
import ipaddress
import os
import tempfile
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from network_change_delivery.architecture_contracts import (
    AutomationProfileID,
    ManagementService,
    NetworkOS,
    get_automation_profile,
)
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
from network_change_delivery.profile_inventory import NetBoxProfileInventoryProvider

EXPECTED_IDENTITIES = (
    "netbox:dcim.device:1",
    "netbox:dcim.device:2",
    "netbox:dcim.device:8",
    "netbox:dcim.device:9",
)
MAX_PUBLICATION_BYTES = 64 * 1024
READINESS_TTL = timedelta(minutes=15)


class ObservabilityTargetError(ValueError):
    """Bounded target/publication failure without provider response content."""


class TargetGenerationState(StrEnum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"
    FAILED = "FAILED"
    AMBIGUOUS = "AMBIGUOUS"


class TargetFailureClassification(StrEnum):
    AUTHORITY_UNAVAILABLE = "AUTHORITY_UNAVAILABLE"
    INVENTORY_REJECTED = "INVENTORY_REJECTED"
    REALIZATION_REJECTED = "REALIZATION_REJECTED"
    PUBLICATION_FAILED = "PUBLICATION_FAILED"
    PUBLICATION_AMBIGUOUS = "PUBLICATION_AMBIGUOUS"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"


class ObservabilityTarget(BaseModel):
    """One stable NetBox identity and its private management-service route."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    inventory_object_id: NetBoxDeviceIdentity
    device_name: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._-]+$")
    platform_slug: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    network_os: NetworkOS
    automation_profile_id: AutomationProfileID
    host: str
    port: int = Field(ge=1, le=65535)
    management_service: ManagementService
    telemetry_source: Literal["tcp_connect"] = "tcp_connect"
    environment: Literal["operator_cml"] = "operator_cml"

    @model_validator(mode="after")
    def exact_inventory_contract(self) -> ObservabilityTarget:
        try:
            ipaddress.IPv4Address(self.host)
        except ValueError:
            raise ValueError("observability target address rejected") from None
        profile = get_automation_profile(self.automation_profile_id)
        if (
            profile.network_os is not self.network_os
            or len(profile.readiness_services) != 1
        ):
            raise ValueError("observability management service rejected")
        expected = profile.readiness_services[0]
        if (
            self.management_service is not expected.service
            or self.port != expected.port
        ):
            raise ValueError("observability management service rejected")
        return self

    def prometheus_labels(self) -> dict[str, str]:
        """Return the exact bounded durable label set."""
        return {
            "instance": self.inventory_object_id,
            "device_name": self.device_name,
            "platform": self.platform_slug,
            "network_os": self.network_os.value,
            "automation_profile": self.automation_profile_id.value,
            "management_service": self.management_service.value,
            "telemetry_source": self.telemetry_source,
            "environment": self.environment,
        }


class RealizationReference(Protocol):
    lab_id: str
    digest: Sha256


class TargetGeneration(BaseModel):
    """Canonical private ACTIVE/RETIRED/failure target-generation status."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["2"] = "2"
    state: TargetGenerationState
    generated_at: datetime
    expires_at: datetime | None = None
    realization_lab_id: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$"
    )
    realization_digest: Sha256 | None = None
    targets: tuple[ObservabilityTarget, ...] = ()
    target_file_sha256: Sha256
    failure_classification: TargetFailureClassification | None = None
    digest: Sha256

    @model_validator(mode="after")
    def coherent_state(self) -> TargetGeneration:
        if self.generated_at.tzinfo is None or self.generated_at.utcoffset() is None:
            raise ValueError("target-generation timestamp rejected")
        active = self.state is TargetGenerationState.ACTIVE
        if active:
            if (
                self.expires_at is None
                or self.expires_at <= self.generated_at
                or self.realization_lab_id is None
                or self.realization_digest is None
                or tuple(item.inventory_object_id for item in self.targets)
                != EXPECTED_IDENTITIES
                or self.failure_classification is not None
            ):
                raise ValueError("active target generation rejected")
        elif (
            self.expires_at is not None
            or self.realization_lab_id is not None
            or self.realization_digest is not None
            or self.targets
            or (
                self.state
                in {TargetGenerationState.FAILED, TargetGenerationState.AMBIGUOUS}
                and self.failure_classification is None
            )
            or (
                self.state is TargetGenerationState.RETIRED
                and self.failure_classification is not None
            )
        ):
            raise ValueError("inactive target generation rejected")
        if self.digest != self.calculated_digest():
            raise ValueError("target-generation digest rejected")
        return self

    def calculated_digest(self) -> str:
        value = canonical_json_bytes(self.model_dump(mode="json", exclude={"digest"}))
        return f"sha256:{hashlib.sha256(value).hexdigest()}"


class ObservabilityReady(BaseModel):
    """Fresh authorization binding active targets to service/runtime identity."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["2"] = "2"
    service_contract: Literal["11A"] = "11A"
    refreshed_at: datetime
    expires_at: datetime
    target_generation_digest: Sha256
    target_file_sha256: Sha256
    realization_lab_id: str = Field(
        pattern=r"^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$"
    )
    realization_digest: Sha256
    targets: tuple[
        NetBoxDeviceIdentity,
        NetBoxDeviceIdentity,
        NetBoxDeviceIdentity,
        NetBoxDeviceIdentity,
    ]
    prometheus_container_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    blackbox_container_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_commit: str = Field(pattern=r"^[0-9a-f]{40}$")

    @model_validator(mode="after")
    def fresh_exact_contract(self) -> ObservabilityReady:
        if (
            self.refreshed_at.tzinfo is None
            or self.refreshed_at.utcoffset() is None
            or self.expires_at <= self.refreshed_at
            or self.targets != EXPECTED_IDENTITIES
        ):
            raise ValueError("observability readiness rejected")
        return self


def targets_from_inventory(
    inventory: NetBoxProfileInventoryProvider,
) -> tuple[
    ObservabilityTarget,
    ObservabilityTarget,
    ObservabilityTarget,
    ObservabilityTarget,
]:
    """Project exact profiled LIVE management endpoints into reachability targets."""
    population = inventory.resolve_profiled_population()
    devices = population.devices
    if tuple(item.inventory_object_id for item in devices) != EXPECTED_IDENTITIES:
        raise ObservabilityTargetError("observability inventory population rejected")
    targets: list[ObservabilityTarget] = []
    for device in devices:
        target = device.live_read_only_target()
        profile = get_automation_profile(device.automation_profile_id)
        if len(profile.readiness_services) != 1:
            raise ObservabilityTargetError("observability management service rejected")
        service = profile.readiness_services[0]
        if target.port != service.port:
            raise ObservabilityTargetError("observability management service rejected")
        targets.append(
            ObservabilityTarget(
                inventory_object_id=device.inventory_object_id,
                device_name=device.logical_name,
                platform_slug=device.platform.slug,
                network_os=device.network_os,
                automation_profile_id=device.automation_profile_id,
                host=target.host,
                port=target.port,
                management_service=service.service,
            )
        )
    return (targets[0], targets[1], targets[2], targets[3])


def render_file_sd(targets: tuple[ObservabilityTarget, ...]) -> bytes:
    """Render canonical private Prometheus file-SD with exact safe labels."""
    payload = [
        {
            "targets": [f"{target.host}:{target.port}"],
            "labels": target.prometheus_labels(),
        }
        for target in targets
    ]
    return canonical_json_bytes(payload)


def empty_file_sd() -> bytes:
    return canonical_json_bytes([])


def _publication_digest(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def _publish(path: Path, content: bytes) -> None:
    if not content or len(content) > MAX_PUBLICATION_BYTES:
        raise ObservabilityTargetError("observability publication rejected")
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
        validate_private_file(path, maximum_bytes=MAX_PUBLICATION_BYTES)
    except OSError as error:
        if replaced:
            raise ObservabilityTargetError(
                "observability publication outcome ambiguous"
            ) from error
        raise ObservabilityTargetError("observability publication failed") from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def _generation(
    *,
    state: TargetGenerationState,
    target_file: bytes,
    targets: tuple[ObservabilityTarget, ...] = (),
    realization: RealizationReference | None = None,
    failure: TargetFailureClassification | None = None,
    now: datetime | None = None,
) -> TargetGeneration:
    generated = (now or datetime.now(UTC)).astimezone(UTC)
    unsigned = TargetGeneration.model_construct(
        schema_version="2",
        state=state,
        generated_at=generated,
        expires_at=generated + READINESS_TTL
        if state is TargetGenerationState.ACTIVE
        else None,
        realization_lab_id=realization.lab_id if realization else None,
        realization_digest=realization.digest if realization else None,
        targets=targets,
        target_file_sha256=_publication_digest(target_file),
        failure_classification=failure,
        digest="sha256:" + "0" * 64,
    )
    return TargetGeneration.model_validate(
        {
            **unsigned.model_dump(mode="json", exclude={"digest"}),
            "digest": unsigned.calculated_digest(),
        }
    )


def publish_generation(
    root: Path,
    *,
    state: TargetGenerationState,
    targets: tuple[ObservabilityTarget, ...] = (),
    realization: RealizationReference | None = None,
    failure: TargetFailureClassification | None = None,
    now: datetime | None = None,
) -> TargetGeneration:
    """Atomically publish targets first and status second under an ambiguity guard."""
    validate_observability_root(root)
    ensure_private_tree(root, "runtime", "discovery", "control")
    runtime = root / "runtime"
    discovery = root / "discovery"
    control = root / "control"
    target_file = (
        render_file_sd(targets)
        if state is TargetGenerationState.ACTIVE
        else empty_file_sd()
    )
    guard = control / "target-publication-ambiguous"
    _publish(guard, b"AMBIGUOUS\n")
    try:
        _publish(discovery / "targets.json", target_file)
        generation = _generation(
            state=state,
            target_file=target_file,
            targets=targets,
            realization=realization,
            failure=failure,
            now=now,
        )
        _publish(
            runtime / "target-generation.json",
            canonical_json_bytes(generation.model_dump(mode="json")),
        )
    except (ObservabilityTargetError, ObservabilityPrivatePathError):
        raise
    guard.unlink()
    directory = os.open(control, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    return generation


def read_generation(root: Path, *, now: datetime | None = None) -> TargetGeneration:
    """Read and verify one generation, its target bytes, guard, digest and freshness."""
    if (root / "control/target-publication-ambiguous").exists():
        raise ObservabilityTargetError("observability target publication ambiguous")
    try:
        content = validate_private_file(root / "runtime/target-generation.json")
        target_bytes = validate_private_file(root / "discovery/targets.json")
        assert content is not None and target_bytes is not None
        generation = TargetGeneration.model_validate_json(content)
    except (ValueError, ObservabilityPrivatePathError):
        raise ObservabilityTargetError(
            "observability target generation rejected"
        ) from None
    if generation.target_file_sha256 != _publication_digest(target_bytes):
        raise ObservabilityTargetError("observability target generation rejected")
    expected = (
        render_file_sd(generation.targets)
        if generation.state is TargetGenerationState.ACTIVE
        else empty_file_sd()
    )
    if target_bytes != expected:
        raise ObservabilityTargetError("observability target generation rejected")
    current = (now or datetime.now(UTC)).astimezone(UTC)
    if generation.state is TargetGenerationState.ACTIVE and (
        generation.expires_at is None or generation.expires_at <= current
    ):
        raise ObservabilityTargetError("observability target generation expired")
    return generation


def retire_targets(root: Path, readiness_path: Path) -> TargetGeneration:
    """Invalidate readiness before publishing a verified empty RETIRED generation."""
    readiness_path.unlink(missing_ok=True)
    generation = publish_generation(root, state=TargetGenerationState.RETIRED)
    verified = read_generation(root)
    if (
        verified != generation
        or validate_private_file(root / "discovery/targets.json") != empty_file_sd()
    ):
        raise ObservabilityTargetError("observability target retirement rejected")
    return generation
