from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from network_change_delivery.architecture_contracts import (
    AutomationProfileID,
    NetworkOS,
)
from network_change_delivery.observability_private_paths import (
    ObservabilityPrivatePathError,
    validate_private_file,
)
from network_change_delivery.observability_targets import (
    EXPECTED_IDENTITIES,
    ManagementService,
    ObservabilityTargetError,
    TargetFailureClassification,
    TargetGenerationState,
    empty_file_sd,
    publish_generation,
    read_generation,
    render_file_sd,
    targets_from_inventory,
)


def device(
    identity: str,
    name: str,
    slug: str,
    network_os: NetworkOS,
    profile: AutomationProfileID,
    host: str,
    port: int,
):
    class Device(SimpleNamespace):
        def live_read_only_target(self):
            return SimpleNamespace(host=self.host, port=self.port)

    return Device(
        inventory_object_id=identity,
        logical_name=name,
        platform=SimpleNamespace(slug=slug),
        network_os=network_os,
        automation_profile_id=profile,
        host=host,
        port=port,
    )


DEVICES = (
    device(
        "netbox:dcim.device:1",
        "core-02",
        "cisco-ios-xe",
        NetworkOS.IOSXE,
        AutomationProfileID.CAT8000V_IOSXE,
        "192.0.2.14",
        22,
    ),
    device(
        "netbox:dcim.device:2",
        "edge-junos-01",
        "juniper-junos",
        NetworkOS.JUNOS,
        AutomationProfileID.VJUNOS_ROUTER,
        "192.0.2.20",
        830,
    ),
    device(
        "netbox:dcim.device:8",
        "transit-ios-01",
        "cisco-ios",
        NetworkOS.IOS,
        AutomationProfileID.IOSV_159_3_M12,
        "192.0.2.16",
        22,
    ),
    device(
        "netbox:dcim.device:9",
        "access-sw-01",
        "cisco-ios",
        NetworkOS.IOS,
        AutomationProfileID.IOSVL2_2020,
        "192.0.2.17",
        22,
    ),
)


class Inventory:
    def __init__(self, devices=DEVICES) -> None:
        self.devices = devices

    def resolve_profiled_population(self):
        return SimpleNamespace(devices=self.devices)


def realization():
    return SimpleNamespace(
        lab_id="11111111-1111-1111-1111-111111111111",
        digest="sha256:" + "a" * 64,
    )


def test_profiled_inventory_derives_all_management_services() -> None:
    targets = targets_from_inventory(Inventory())
    assert [(item.port, item.management_service) for item in targets] == [
        (22, ManagementService.SSH),
        (830, ManagementService.NETCONF),
        (22, ManagementService.SSH),
        (22, ManagementService.SSH),
    ]
    assert tuple(item.inventory_object_id for item in targets) == EXPECTED_IDENTITIES


@pytest.mark.parametrize(
    "population",
    [(), (DEVICES[0],), DEVICES[::-1], (*DEVICES, DEVICES[0])],
)
def test_population_is_exact_ordered_and_unique(population) -> None:
    with pytest.raises(ObservabilityTargetError, match="population"):
        targets_from_inventory(Inventory(population))


@pytest.mark.parametrize(
    "changed",
    [
        {"automation_profile_id": AutomationProfileID.VJUNOS_ROUTER},
        {"inventory_object_id": "netbox:dcim.device:3"},
    ],
)
def test_identity_and_platform_contract_fail_closed(changed) -> None:
    candidate = SimpleNamespace(**{**DEVICES[0].__dict__, **changed})
    candidate.live_read_only_target = DEVICES[0].live_read_only_target
    with pytest.raises((ObservabilityTargetError, ValueError)):
        targets_from_inventory(Inventory((candidate, *DEVICES[1:])))


def test_file_sd_keeps_route_private_and_identity_stable() -> None:
    payload = json.loads(render_file_sd(targets_from_inventory(Inventory())))
    assert payload[0]["targets"] == ["192.0.2.14:22"]
    assert payload[1]["targets"] == ["192.0.2.20:830"]
    assert [item["targets"] for item in payload[2:]] == [
        ["192.0.2.16:22"],
        ["192.0.2.17:22"],
    ]
    for index, item in zip((1, 2, 8, 9), payload, strict=True):
        labels = item["labels"]
        assert labels["instance"] == f"netbox:dcim.device:{index}"
        assert set(labels) == {
            "instance",
            "device_name",
            "platform",
            "network_os",
            "automation_profile",
            "management_service",
            "telemetry_source",
            "environment",
        }
        assert "192.0.2" not in json.dumps(labels)
        assert "uuid" not in json.dumps(labels).casefold()


def test_active_generation_is_canonical_private_and_digest_bound(
    tmp_path: Path,
) -> None:
    root = tmp_path / "external" / "observability"
    now = datetime(2026, 8, 28, tzinfo=UTC)
    generation = publish_generation(
        root,
        state=TargetGenerationState.ACTIVE,
        targets=targets_from_inventory(Inventory()),
        realization=realization(),
        now=now,
    )
    assert read_generation(root, now=now) == generation
    assert generation.schema_version == "2"
    assert generation.expires_at == now + timedelta(minutes=15)
    assert generation.failure_classification is None
    for path in (
        root / "discovery/targets.json",
        root / "runtime/target-generation.json",
    ):
        assert path.stat().st_uid == os.getuid()
        assert path.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize(
    "targets",
    [
        DEVICES[:3],
        DEVICES[::-1],
        (*DEVICES, DEVICES[0]),
    ],
)
def test_active_generation_rejects_noncanonical_target_population(
    tmp_path: Path, targets
) -> None:
    projected = targets_from_inventory(Inventory())
    if len(targets) == 3:
        candidate = projected[:3]
    elif len(targets) == 4:
        candidate = projected[::-1]
    else:
        candidate = (*projected, projected[0])
    with pytest.raises(ValueError, match="active target generation"):
        publish_generation(
            tmp_path / "external" / "observability",
            state=TargetGenerationState.ACTIVE,
            targets=candidate,
            realization=realization(),
        )


def test_retired_failed_and_ambiguous_states_are_distinct(tmp_path: Path) -> None:
    root = tmp_path / "external" / "observability"
    retired = publish_generation(root, state=TargetGenerationState.RETIRED)
    assert retired.state is TargetGenerationState.RETIRED
    assert validate_private_file(root / "discovery/targets.json") == empty_file_sd()
    failed = publish_generation(
        root,
        state=TargetGenerationState.FAILED,
        failure=TargetFailureClassification.AUTHORITY_UNAVAILABLE,
    )
    assert failed.state is TargetGenerationState.FAILED
    ambiguous = publish_generation(
        root,
        state=TargetGenerationState.AMBIGUOUS,
        failure=TargetFailureClassification.PUBLICATION_AMBIGUOUS,
    )
    assert ambiguous.state is TargetGenerationState.AMBIGUOUS


def test_digest_or_target_tamper_fails_closed(tmp_path: Path) -> None:
    root = tmp_path / "external" / "observability"
    publish_generation(
        root,
        state=TargetGenerationState.ACTIVE,
        targets=targets_from_inventory(Inventory()),
        realization=realization(),
    )
    target = root / "discovery/targets.json"
    target.write_bytes(empty_file_sd())
    target.chmod(0o600)
    with pytest.raises(ObservabilityTargetError, match="rejected"):
        read_generation(root)


def test_ambiguity_guard_rejects_generation(tmp_path: Path) -> None:
    root = tmp_path / "external" / "observability"
    publish_generation(root, state=TargetGenerationState.RETIRED)
    guard = root / "control/target-publication-ambiguous"
    guard.write_text("AMBIGUOUS\n")
    guard.chmod(0o600)
    with pytest.raises(ObservabilityTargetError, match="ambiguous"):
        read_generation(root)


def test_private_boundary_rejects_checkout_audit_oxidized_and_symlink(
    tmp_path: Path,
) -> None:
    checkout = Path(__file__).parents[1] / "observability-private"
    with pytest.raises(ObservabilityPrivatePathError):
        publish_generation(checkout, state=TargetGenerationState.RETIRED)
    for name in ("audit", "oxidized"):
        with pytest.raises(ObservabilityPrivatePathError):
            publish_generation(tmp_path / name, state=TargetGenerationState.RETIRED)
    real = tmp_path / "real"
    real.mkdir(mode=0o700)
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    with pytest.raises(ObservabilityPrivatePathError):
        publish_generation(link, state=TargetGenerationState.RETIRED)


def test_contract_contains_no_credential_or_configuration_fields() -> None:
    schema = json.dumps(
        targets_from_inventory(Inventory())[0].model_json_schema(), sort_keys=True
    ).casefold()
    for forbidden in (
        "password",
        "username",
        "credential",
        "known_hosts",
        "configuration",
        "diff",
    ):
        assert forbidden not in schema
