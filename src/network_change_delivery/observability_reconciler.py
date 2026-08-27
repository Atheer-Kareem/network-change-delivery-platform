"""Repository-independent one-shot observability service reconciler."""

from __future__ import annotations

import json
import os
import re
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from network_change_delivery.inventory import InventoryError, NetBoxInventoryProvider
from network_change_delivery.observability_private_paths import validate_private_file
from network_change_delivery.observability_realization import (
    CmlRealizationAuthority,
    ObservabilityRealizationError,
    publish_admission,
    read_admission,
)
from network_change_delivery.observability_service import (
    ObservabilityServiceError,
    inspect_containers,
    invalidate_readiness,
    publish_readiness,
    run_compose,
    verify_container_definitions,
    wait_service_health,
)
from network_change_delivery.observability_targets import (
    ObservabilityTargetError,
    TargetFailureClassification,
    TargetGenerationState,
    publish_generation,
    targets_from_inventory,
)

STATE_ROOT = Path("/Users/netdevops/.local/state/ncdp/observability")
CONFIG_ROOT = Path("/Users/netdevops/.config/ncdp/observability")


@contextmanager
def _runtime_transition_lock() -> Iterator[None]:
    lock = CONFIG_ROOT / "runtime-transition.lock"
    try:
        lock.mkdir(mode=0o700)
    except OSError:
        raise ObservabilityServiceError(
            "observability runtime transition ambiguous"
        ) from None
    try:
        yield
    finally:
        try:
            lock.rmdir()
        except OSError:
            raise ObservabilityServiceError(
                "observability runtime transition ambiguous"
            ) from None


def _private_text(path: Path) -> str:
    content = validate_private_file(path)
    if content is None:
        raise ObservabilityServiceError("observability private input unavailable")
    try:
        value = content.decode().strip()
    except UnicodeDecodeError:
        raise ObservabilityServiceError(
            "observability private input unavailable"
        ) from None
    if not value:
        raise ObservabilityServiceError("observability private input unavailable")
    return value


def _settings() -> dict[str, str]:
    try:
        content = validate_private_file(CONFIG_ROOT / "authority.json")
        assert content is not None
        payload = json.loads(content)
    except (ValueError, OSError):
        raise ObservabilityServiceError(
            "observability authority settings rejected"
        ) from None
    required = {
        "netbox_url",
        "cml_address",
        "cml_certificate",
        "cml_username",
        "cml_password",
    }
    if set(payload) != required or any(
        not isinstance(payload[key], str) or not payload[key] for key in required
    ):
        raise ObservabilityServiceError("observability authority settings rejected")
    return payload


def _runtime_source_commit() -> str:
    if (CONFIG_ROOT / "runtime-update-in-progress").exists():
        raise ObservabilityServiceError("observability runtime update ambiguous")
    source_commit = _private_text(CONFIG_ROOT / "source-commit")
    runtime_commit = os.environ.get("NCDP_OBSERVABILITY_RUNTIME_COMMIT", "")
    if (
        re.fullmatch(r"[0-9a-f]{40}", source_commit) is None
        or re.fullmatch(r"[0-9a-f]{40}", runtime_commit) is None
        or source_commit != runtime_commit
    ):
        raise ObservabilityServiceError("observability runtime identity rejected")
    return source_commit


def _refresh_admission(settings: dict[str, str]):
    previous = read_admission(STATE_ROOT)
    node_ids = {item.inventory_object_id: item.cml_node_id for item in previous.nodes}
    authority = CmlRealizationAuthority(
        settings["cml_address"],
        settings["cml_certificate"],
        settings["cml_username"],
        settings["cml_password"],
    )
    try:
        refreshed = authority.admit(previous.lab_id, node_ids)
    finally:
        authority.close()
    publish_admission(STATE_ROOT, refreshed)
    return refreshed


def _reconcile_locked() -> str:
    readiness = STATE_ROOT / "runtime/observability-ready.json"
    invalidate_readiness(readiness)
    source_commit = _runtime_source_commit()
    admission_exists = (
        validate_private_file(STATE_ROOT / "operator/realization.json", missing_ok=True)
        is not None
    )
    if admission_exists:
        try:
            settings = _settings()
            admission = _refresh_admission(settings)
        except (ObservabilityRealizationError, ObservabilityServiceError):
            publish_generation(
                STATE_ROOT,
                state=TargetGenerationState.FAILED,
                failure=TargetFailureClassification.REALIZATION_REJECTED,
            )
            raise ObservabilityServiceError(
                "observability realization reconciliation failed"
            ) from None
        try:
            targets = targets_from_inventory(
                NetBoxInventoryProvider(
                    settings["netbox_url"],
                    _private_text(CONFIG_ROOT / "netbox-token"),
                )
            )
            generation = publish_generation(
                STATE_ROOT,
                state=TargetGenerationState.ACTIVE,
                targets=targets,
                realization=admission,
            )
        except (InventoryError, ObservabilityTargetError):
            publish_generation(
                STATE_ROOT,
                state=TargetGenerationState.FAILED,
                failure=TargetFailureClassification.INVENTORY_REJECTED,
            )
            raise ObservabilityServiceError(
                "observability inventory reconciliation failed"
            ) from None
    else:
        generation = publish_generation(STATE_ROOT, state=TargetGenerationState.RETIRED)

    compose_path = Path(_private_text(CONFIG_ROOT / "compose-path"))
    run_compose(
        compose_path,
        CONFIG_ROOT,
        STATE_ROOT,
        "up",
        "--detach",
        "--pull",
        "never",
        "--no-build",
        "--remove-orphans",
    )
    inspected = inspect_containers()
    prometheus_id, blackbox_id = verify_container_definitions(
        inspected,
        prometheus_image_id=_private_text(CONFIG_ROOT / "prometheus-image-id"),
        blackbox_image_id=_private_text(CONFIG_ROOT / "blackbox-image-id"),
        config_root=CONFIG_ROOT,
        state_root=STATE_ROOT,
    )
    wait_service_health(require_device_targets=admission_exists)
    if not admission_exists:
        return generation.state.value
    if _runtime_source_commit() != source_commit:
        raise ObservabilityServiceError("observability runtime identity rejected")
    publish_readiness(
        STATE_ROOT,
        generation,
        prometheus_container_id=prometheus_id,
        blackbox_container_id=blackbox_id,
        source_commit=source_commit,
    )
    return generation.digest


def reconcile() -> str:
    with _runtime_transition_lock():
        return _reconcile_locked()


def main() -> int:
    if len(sys.argv) != 1:
        print("observability service arguments rejected", file=sys.stderr)
        return 2
    try:
        digest = reconcile()
    except (ValueError, OSError):
        print("observability service reconciliation failed", file=sys.stderr)
        return 2
    print(f"observability service reconciled: READY generation={digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
