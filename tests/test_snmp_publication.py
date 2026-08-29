from __future__ import annotations

import json
from pathlib import Path

import pytest

from network_change_delivery.snmp_publication import (
    SnmpPollingTarget,
    SnmpTargetPublicationError,
    publish_snmp_targets,
    render_snmp_file_sd,
)
from network_change_delivery.snmp_telemetry import (
    SnmpCredentialReference,
    SnmpDeviceTargetStatus,
    SnmpTargetIdentity,
    SnmpTargetState,
    target_generation_with_digest,
)

MAPPING = "sha256:" + "a" * 64


def target(number: int, endpoint: str) -> SnmpPollingTarget:
    device = f"netbox:dcim.device:{number}"
    return SnmpPollingTarget(
        identity=SnmpTargetIdentity(
            device=device,
            device_name=f"synthetic-{number}",
            platform="cisco_iosxe" if number == 1 else "junos",
            credential=SnmpCredentialReference(
                device=device,
                reference=(
                    f"snmpv3:netbox:dcim.device:{number}:generation:synthetic_a"
                ),
                auth_selector=f"ncdp_device_{number}_a",
            ),
        ),
        endpoint=endpoint,
    )


def generation(*numbers: int, state: SnmpTargetState = SnmpTargetState.ACTIVE):
    return target_generation_with_digest(
        tuple(
            SnmpDeviceTargetStatus(
                device=f"netbox:dcim.device:{number}",
                state=state,
                interface_mapping_digest=MAPPING
                if state is SnmpTargetState.ACTIVE
                else None,
            )
            for number in numbers
        )
    )


def test_target_file_is_canonical_nonsecret_and_stable_identity() -> None:
    content = render_snmp_file_sd(
        (target(2, "synthetic-agent-b:1161"), target(1, "synthetic-agent-a:1161"))
    )
    payload = json.loads(content)
    assert [item["labels"]["instance"] for item in payload] == [
        "netbox:dcim.device:1",
        "netbox:dcim.device:2",
    ]
    assert set(payload[0]["labels"]) == {"instance", "__param_auth"}
    serialized = content.decode().casefold()
    for forbidden in (
        "username",
        "password",
        "privacy",
        "ifindex",
        "provider error",
    ):
        assert forbidden not in serialized


def test_target_publication_is_private_bound_and_can_retire_independently(
    tmp_path: Path,
) -> None:
    root = tmp_path / "external" / "observability-snmp"
    targets = (target(1, "synthetic-agent-a:1161"), target(2, "synthetic-agent-b:1161"))
    active = publish_snmp_targets(root, generation(1, 2), targets)
    assert active.targets == (
        "netbox:dcim.device:1",
        "netbox:dcim.device:2",
    )
    for path in (
        root / "discovery/snmp-targets.json",
        root / "runtime/snmp-target-publication.json",
    ):
        assert path.stat().st_mode & 0o777 == 0o600
    retired = publish_snmp_targets(
        root,
        generation(1, state=SnmpTargetState.RETIRED),
        (),
    )
    assert retired.state is SnmpTargetState.RETIRED
    assert json.loads((root / "discovery/snmp-targets.json").read_bytes()) == []


def test_target_population_mismatch_duplicate_and_bad_endpoint_fail_closed(
    tmp_path: Path,
) -> None:
    root = tmp_path / "external" / "observability-snmp"
    with pytest.raises(SnmpTargetPublicationError, match="generation"):
        publish_snmp_targets(
            root,
            generation(1, 2),
            (target(1, "synthetic-agent-a:1161"),),
        )
    with pytest.raises(SnmpTargetPublicationError, match="population"):
        render_snmp_file_sd(
            (
                target(1, "synthetic-agent-a:1161"),
                target(1, "synthetic-agent-b:1161"),
            )
        )
    with pytest.raises(ValueError, match="endpoint rejected"):
        target(1, "https://not-snmp")
