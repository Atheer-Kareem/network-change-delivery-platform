"""Scope isolation, resolved management authority and explicit runtime versions."""

import hashlib
import json
from pathlib import Path

import pytest
from profiled_population_fixtures import declared_population

from network_change_delivery.profile_inventory import (
    LIVE_REALIZATION_SCOPE,
    OBSERVABILITY_SCOPE,
    OXIDIZED_COLLECTION_SCOPE,
    STAGING_REALIZATION_SCOPE,
    ProfiledPopulationScope,
    population_scope,
)
from network_change_delivery.profiled_staging import (
    CURRENT_STAGING_TOPOLOGY,
    ProfiledStagingError,
    ProfiledStagingLink,
    ProfiledStagingTopology,
    load_recovery_inputs,
    staging_terraform_addresses,
    terraform_profiled_device_variables,
    validate_profiled_staging_physical_topology,
    write_recovery_inputs,
)
from network_change_delivery.profiled_staging_cml import staging_link_slots
from network_change_delivery.secrets import DeviceCredentials


def test_scope_identity_ignores_unselected_managed_members():
    small, _, _, _ = declared_population(4)
    large, _, provider, _ = declared_population(5)
    selected = small.identities[:3]
    a = population_scope("service", selected, declaration=small)
    b = population_scope("service", selected, declaration=large)
    assert a == b
    assert a.model_dump_json() == b.model_dump_json()
    assert a.digest == b.digest
    assert set(a.model_dump()) == {"identity", "members"}
    assert provider.resolve_profiled_population().project(a).scope == b
    assert (
        LIVE_REALIZATION_SCOPE.digest
        == ProfiledPopulationScope.model_validate_json(
            LIVE_REALIZATION_SCOPE.model_dump_json()
        ).digest
    )
    facts = a.members[0].model_dump() | {"logical_name": "renamed-core"}
    changed = ProfiledPopulationScope(
        identity=a.identity,
        members=(type(a.members[0]).model_validate(facts), *a.members[1:]),
    )
    assert changed.digest != a.digest
    with pytest.raises(ValueError):
        provider.resolve_profiled_population().project(changed)
    with pytest.raises(ValueError):
        population_scope("unknown", ("netbox:dcim.device:999",), declaration=small)


def test_management_slot_comes_from_resolved_attachment_and_survives_recovery(
    monkeypatch, tmp_path
):
    import test_profiled_population as fixtures

    original = fixtures.interfaces

    def interfaces(device):
        values = original(device)
        if device["id"] == 14:
            for item in values:
                item["name"] = "GigabitEthernet0/3"
        return values

    monkeypatch.setattr(fixtures, "interfaces", interfaces)
    declaration, _, provider, _ = declared_population(5)
    scope = population_scope(
        "two-iosv",
        ("netbox:dcim.device:8", "netbox:dcim.device:14"),
        declaration=declaration,
    )
    devices = provider.resolve_profiled_population().project(scope).devices
    assert len({d.cml_realization_profile_id for d in devices}) == 1
    credentials = {
        d.logical_name: DeviceCredentials(username="fixture", password="unused")
        for d in devices
    }
    values = terraform_profiled_device_variables(
        devices,
        credentials,
        {d.logical_name: "$9$salt$hash" for d in devices},
        scope=scope,
    )
    assert [v["management_slot"] for v in values.values()] == [0, 3]
    topology = ProfiledStagingTopology(
        scope=scope,
        links=(
            ProfiledStagingLink(
                identity="data",
                endpoints=("transit-ios-01:Gi0/1", "synthetic-14:Gi0/2"),
            ),
        ),
    )
    links = staging_link_slots(devices, topology)
    assert links["management_synthetic_14"][1] == ("synthetic_14", 3)
    bad = ProfiledStagingTopology(
        scope=scope,
        links=(
            ProfiledStagingLink(
                identity="data",
                endpoints=("transit-ios-01:Gi0/1", "synthetic-14:Gi0/3"),
            ),
        ),
    )
    with pytest.raises(ValueError, match="resolved management slot"):
        staging_link_slots(devices, bad)
    # The production pre-Terraform boundary rejects before even reading cable facts.
    with pytest.raises(ValueError, match="resolved management slot"):
        validate_profiled_staging_physical_topology(object(), devices, topology=bad)
    payload = {
        "staging_run_id": "slot-proof",
        "lifecycle_state": "DEFINED_ON_CORE",
        "devices": values,
        "data_links": topology.terraform_links(),
    }
    path = tmp_path / "inputs.json"
    write_recovery_inputs(path, payload)
    assert (
        load_recovery_inputs(path, "slot-proof", scope=scope, topology=topology)
        == payload
    )
    for slot in (99, 2):
        tampered = json.loads(json.dumps(payload))
        tampered["devices"]["synthetic_14"]["management_slot"] = slot
        candidate = tmp_path / f"bad-{slot}.json"
        write_recovery_inputs(candidate, tampered)
        with pytest.raises(ProfiledStagingError):
            load_recovery_inputs(
                candidate, "slot-proof", scope=scope, topology=topology
            )
    assert len(staging_terraform_addresses()) == 17
    assert len(CURRENT_STAGING_TOPOLOGY.scope.members) + 2 == 6
    assert (
        len(CURRENT_STAGING_TOPOLOGY.scope.members)
        + len(CURRENT_STAGING_TOPOLOGY.links)
        + 1
        == 9
    )
    assert (
        CURRENT_STAGING_TOPOLOGY.digest
        == "sha256:764405fa9a44d7c42ae402ec2fa1d03c2b7dd9ba0916954e03c7a7d5baf68064"
    )


@pytest.mark.parametrize(
    "file,version",
    [("target-generation-v2.json", "2"), ("realization-admission-v3.json", "3")],
)
def test_old_canonical_runtime_versions_are_explicitly_stale(file, version):
    from network_change_delivery.observability_realization import RealizationAdmission
    from network_change_delivery.observability_targets import TargetGeneration

    content = (Path(__file__).parent / "fixtures/population-scopes" / file).read_bytes()
    data = json.loads(content)
    digest = data.pop("digest")
    assert data["schema_version"] == version
    assert "scope" not in data and "catalog" not in data
    assert (
        digest
        == "sha256:"
        + hashlib.sha256(
            json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )
    model = TargetGeneration if version == "2" else RealizationAdmission
    with pytest.raises(ValueError, match="schema_version"):
        model.model_validate_json(content)


def test_leaf_records_do_not_duplicate_population_admission_context():
    from test_observability_targets import Inventory
    from test_profiled_realization import live_devices, staging_devices, trust_records

    from network_change_delivery.observability_targets import targets_from_inventory

    leaves = (
        *live_devices(),
        *staging_devices(),
        *trust_records(),
        *targets_from_inventory(Inventory()),
    )
    for leaf in leaves:
        assert "declaration" not in leaf.model_dump()
        assert "scope" not in leaf.model_dump()


def test_valid_rehashed_generation_cannot_replace_expected_scope(tmp_path):
    from datetime import UTC, datetime

    from test_observability_targets import Inventory, realization

    from network_change_delivery.observability_targets import (
        ObservabilityTargetError,
        TargetGeneration,
        TargetGenerationState,
        publish_generation,
        read_generation,
        targets_from_inventory,
    )

    now = datetime(2026, 9, 8, tzinfo=UTC)
    root = tmp_path / "observability"
    record = publish_generation(
        root,
        state=TargetGenerationState.ACTIVE,
        targets=targets_from_inventory(Inventory()),
        realization=realization(),
        now=now,
    )
    assert record.schema_version == "3"
    data = record.model_dump(mode="json")
    data["scope"]["identity"] = "unreviewed-consumer"
    data.pop("digest")
    data["digest"] = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )
    changed = TargetGeneration.model_validate(data)
    (root / "runtime/target-generation.json").write_text(changed.model_dump_json())
    with pytest.raises(ObservabilityTargetError, match="scope rejected"):
        read_generation(root, now=now)


def test_scoped_readiness_uses_current_version_and_rejects_old_version():
    from datetime import UTC, datetime, timedelta

    from network_change_delivery.observability_targets import ObservabilityReady
    from network_change_delivery.profile_inventory import OBSERVABILITY_SCOPE

    now = datetime(2026, 9, 8, tzinfo=UTC)
    ready = ObservabilityReady(
        refreshed_at=now,
        expires_at=now + timedelta(minutes=15),
        target_generation_digest="sha256:" + "a" * 64,
        target_file_sha256="sha256:" + "b" * 64,
        realization_lab_id="11111111-1111-4111-8111-111111111111",
        realization_digest="sha256:" + "c" * 64,
        targets=OBSERVABILITY_SCOPE.identities,
        prometheus_container_id="d" * 64,
        blackbox_container_id="e" * 64,
        source_commit="f" * 40,
    )
    assert ready.schema_version == "3"
    old = ready.model_dump(mode="json")
    old.pop("scope")
    old["schema_version"] = "2"
    with pytest.raises(ValueError, match="schema_version"):
        ObservabilityReady.model_validate(old)


@pytest.mark.parametrize(
    "scope",
    [
        LIVE_REALIZATION_SCOPE,
        STAGING_REALIZATION_SCOPE,
        OXIDIZED_COLLECTION_SCOPE,
        OBSERVABILITY_SCOPE,
    ],
)
def test_current_scope_digests_are_stable_with_larger_admission_context(scope):
    declaration, _, _, _ = declared_population(5)
    selected = population_scope(
        scope.identity, scope.identities, declaration=declaration
    )
    assert selected == scope
    assert selected.model_dump_json() == scope.model_dump_json()
    assert selected.digest == scope.digest
