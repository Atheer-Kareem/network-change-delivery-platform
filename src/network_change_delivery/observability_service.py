"""Persistent Prometheus/Blackbox runtime and readiness contracts."""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx
from pydantic import ValidationError

from network_change_delivery.audit import canonical_json_bytes
from network_change_delivery.observability_private_paths import (
    ObservabilityPrivatePathError,
    ensure_private_tree,
    validate_private_file,
)
from network_change_delivery.observability_targets import (
    EXPECTED_IDENTITIES,
    ObservabilityReady,
    TargetGeneration,
)

SERVICE_LABEL = "com.ncdp.observability"
PROJECT_NAME = "ncdp-observability"
PROMETHEUS_CONTAINER = "ncdp-prometheus"
BLACKBOX_CONTAINER = "ncdp-blackbox-exporter"
PROMETHEUS_URL = "http://127.0.0.1:9090"
ENSURE_INTERVAL_SECONDS = 300
DOCKER_TIMEOUT_SECONDS = 45


class ObservabilityServiceError(ValueError):
    """Bounded observability lifecycle failure."""


def invalidate_readiness(path: Path) -> None:
    path.unlink(missing_ok=True)


def _publish_private(path: Path, content: bytes) -> None:
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
        validate_private_file(path)
    except OSError as error:
        message = (
            "observability readiness publication ambiguous"
            if replaced
            else "observability readiness publication failed"
        )
        raise ObservabilityServiceError(message) from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def publish_readiness(
    root: Path,
    generation: TargetGeneration,
    *,
    prometheus_container_id: str,
    blackbox_container_id: str,
    source_commit: str,
    now: datetime | None = None,
) -> ObservabilityReady:
    if (
        generation.expires_at is None
        or generation.realization_lab_id is None
        or generation.realization_digest is None
    ):
        raise ObservabilityServiceError("observability readiness rejected")
    refreshed = (now or datetime.now(UTC)).astimezone(UTC)
    expires = min(
        generation.expires_at,
        refreshed + (generation.expires_at - generation.generated_at),
    )
    marker = ObservabilityReady(
        refreshed_at=refreshed,
        expires_at=expires,
        target_generation_digest=generation.digest,
        target_file_sha256=generation.target_file_sha256,
        realization_lab_id=generation.realization_lab_id,
        realization_digest=generation.realization_digest,
        targets=EXPECTED_IDENTITIES,
        prometheus_container_id=prometheus_container_id,
        blackbox_container_id=blackbox_container_id,
        source_commit=source_commit,
    )
    ensure_private_tree(root, "runtime", "control")
    guard = root / "control/readiness-publication-ambiguous"
    _publish_private(guard, b"AMBIGUOUS\n")
    _publish_private(
        root / "runtime/observability-ready.json",
        canonical_json_bytes(marker.model_dump(mode="json")),
    )
    guard.unlink()
    directory = os.open(guard.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    return marker


def read_readiness(
    root: Path,
    generation: TargetGeneration,
    *,
    prometheus_container_id: str,
    blackbox_container_id: str,
    source_commit: str,
    now: datetime | None = None,
) -> ObservabilityReady:
    if re.fullmatch(r"[0-9a-f]{40}", source_commit) is None:
        raise ObservabilityServiceError("observability readiness rejected")
    try:
        if (root / "control/readiness-publication-ambiguous").exists():
            raise ObservabilityServiceError("observability readiness rejected")
        content = validate_private_file(root / "runtime/observability-ready.json")
        assert content is not None
        marker = ObservabilityReady.model_validate_json(content)
    except (ValidationError, ValueError, ObservabilityPrivatePathError):
        raise ObservabilityServiceError("observability readiness rejected") from None
    current = (now or datetime.now(UTC)).astimezone(UTC)
    if (
        marker.expires_at <= current
        or marker.target_generation_digest != generation.digest
        or marker.target_file_sha256 != generation.target_file_sha256
        or marker.realization_lab_id != generation.realization_lab_id
        or marker.realization_digest != generation.realization_digest
        or marker.prometheus_container_id != prometheus_container_id
        or marker.blackbox_container_id != blackbox_container_id
        or marker.source_commit != source_commit
    ):
        raise ObservabilityServiceError("observability readiness rejected")
    return marker


def docker_compose_environment(config_root: Path, state_root: Path) -> dict[str, str]:
    return {
        "HOME": str(Path.home()),
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "LC_ALL": "C",
        "NCDP_OBSERVABILITY_UID": str(os.getuid()),
        "NCDP_OBSERVABILITY_GID": str(os.getgid()),
        "NCDP_OBSERVABILITY_CONFIG_ROOT": str(config_root),
        "NCDP_OBSERVABILITY_STATE_ROOT": str(state_root),
    }


def run_compose(
    compose_path: Path,
    config_root: Path,
    state_root: Path,
    *arguments: str,
) -> str:
    try:
        result = subprocess.run(
            [
                "/usr/local/bin/docker",
                "compose",
                "--project-name",
                PROJECT_NAME,
                "--file",
                str(compose_path),
                *arguments,
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=True,
            timeout=DOCKER_TIMEOUT_SECONDS,
            shell=False,
            env=docker_compose_environment(config_root, state_root),
        )
    except (OSError, subprocess.SubprocessError):
        raise ObservabilityServiceError(
            "observability Docker operation failed"
        ) from None
    return result.stdout.strip()


def inspect_containers() -> dict[str, dict[str, object]]:
    try:
        result = subprocess.run(
            [
                "/usr/local/bin/docker",
                "container",
                "inspect",
                PROMETHEUS_CONTAINER,
                BLACKBOX_CONTAINER,
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=True,
            timeout=15,
            env={"PATH": "/usr/local/bin:/usr/bin:/bin", "LC_ALL": "C"},
        )
        values = json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, ValueError):
        raise ObservabilityServiceError(
            "observability container inspection failed"
        ) from None
    if not isinstance(values, list) or len(values) != 2:
        raise ObservabilityServiceError("observability container inspection failed")
    inspected = {
        item.get("Name", "").lstrip("/"): item
        for item in values
        if isinstance(item, dict)
    }
    if set(inspected) != {PROMETHEUS_CONTAINER, BLACKBOX_CONTAINER}:
        raise ObservabilityServiceError("observability container inspection failed")
    return inspected


def verify_container_definitions(
    inspected: dict[str, dict[str, object]],
    *,
    prometheus_image_id: str,
    blackbox_image_id: str,
    config_root: Path,
    state_root: Path,
) -> tuple[str, str]:
    expected_images = {
        PROMETHEUS_CONTAINER: prometheus_image_id,
        BLACKBOX_CONTAINER: blackbox_image_id,
    }
    identifiers: dict[str, str] = {}
    for name, expected_image in expected_images.items():
        item = inspected[name]
        host = item.get("HostConfig")
        config = item.get("Config")
        state = item.get("State")
        identifier = item.get("Id")
        if not all(
            isinstance(value, dict) for value in (host, config, state)
        ) or not isinstance(identifier, str):
            raise ObservabilityServiceError(
                "observability container definition rejected"
            )
        assert (
            isinstance(host, dict)
            and isinstance(config, dict)
            and isinstance(state, dict)
        )
        restart = host.get("RestartPolicy")
        security = host.get("SecurityOpt") or []
        cap_drop = host.get("CapDrop") or []
        labels = config.get("Labels") or {}
        if (
            item.get("Image") != expected_image
            or state.get("Running") is not True
            or host.get("ReadonlyRootfs") is not True
            or not isinstance(restart, dict)
            or restart.get("Name") not in {"", "no"}
            or "ALL" not in cap_drop
            or not any(str(value).startswith("no-new-privileges") for value in security)
            or config.get("User") != f"{os.getuid()}:{os.getgid()}"
            or not isinstance(labels, dict)
            or labels.get("com.docker.compose.project") != PROJECT_NAME
            or host.get("NetworkMode") != "ncdp-observability-telemetry"
        ):
            raise ObservabilityServiceError(
                "observability container definition rejected"
            )
        ports = host.get("PortBindings") or {}
        if name == PROMETHEUS_CONTAINER:
            binding = ports.get("9090/tcp") if isinstance(ports, dict) else None
            if binding != [{"HostIp": "127.0.0.1", "HostPort": "9090"}]:
                raise ObservabilityServiceError(
                    "observability port publication rejected"
                )
        elif ports:
            raise ObservabilityServiceError("observability port publication rejected")
        binds = host.get("Binds") or []
        expected_binds = (
            {
                f"{config_root}/prometheus.yml:/etc/ncdp/prometheus.yml:ro",
                f"{state_root}/discovery:/etc/ncdp/targets:ro",
                f"{state_root}/prometheus:/prometheus:rw",
            }
            if name == PROMETHEUS_CONTAINER
            else {f"{config_root}/blackbox.yml:/etc/ncdp/blackbox.yml:ro"}
        )
        if not isinstance(binds, list) or set(binds) != expected_binds:
            raise ObservabilityServiceError(
                "observability container definition rejected"
            )
        rendered = json.dumps(item, sort_keys=True)
        for forbidden in (
            "docker.sock",
            "/.ssh",
            "/audit",
            "config-history.git",
            "NCDP_NETBOX_TOKEN",
            "OPENBAO",
            "password",
        ):
            if forbidden in rendered:
                raise ObservabilityServiceError(
                    "observability container definition rejected"
                )
        identifiers[name] = identifier
    return identifiers[PROMETHEUS_CONTAINER], identifiers[BLACKBOX_CONTAINER]


def wait_service_health(*, require_device_targets: bool, attempts: int = 30) -> None:
    with httpx.Client(timeout=2, follow_redirects=False, trust_env=False) as client:
        for _ in range(attempts):
            try:
                ready = client.get(f"{PROMETHEUS_URL}/-/ready")
                exporter = client.get(
                    f"{PROMETHEUS_URL}/api/v1/query",
                    params={"query": 'up{job="ncdp-blackbox-exporter"}'},
                )
                payload = exporter.json()
                results = payload.get("data", {}).get("result", [])
                target_ok = True
                if require_device_targets:
                    targets = client.get(f"{PROMETHEUS_URL}/api/v1/targets").json()
                    active = [
                        item
                        for item in targets.get("data", {}).get("activeTargets", [])
                        if item.get("labels", {}).get("job")
                        == "ncdp-management-service"
                    ]
                    target_ok = {
                        item.get("labels", {}).get("instance") for item in active
                    } == set(EXPECTED_IDENTITIES)
                if (
                    ready.status_code == 200
                    and len(results) == 1
                    and results[0].get("value", [None, None])[1] == "1"
                    and target_ok
                ):
                    return
            except (httpx.HTTPError, ValueError, AttributeError):
                pass
            time.sleep(1)
    raise ObservabilityServiceError("observability service health failed")


def wait_targets_retired(attempts: int = 30) -> None:
    with httpx.Client(timeout=2, follow_redirects=False, trust_env=False) as client:
        for _ in range(attempts):
            try:
                payload = client.get(f"{PROMETHEUS_URL}/api/v1/targets").json()
                active = [
                    item
                    for item in payload.get("data", {}).get("activeTargets", [])
                    if item.get("labels", {}).get("job") == "ncdp-management-service"
                ]
                if not active:
                    return
            except (httpx.HTTPError, ValueError, AttributeError):
                pass
            time.sleep(1)
    raise ObservabilityServiceError("observability target retirement not settled")
