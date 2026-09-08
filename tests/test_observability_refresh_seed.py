from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from test_observability_realization import admit, authority
from test_observability_realization import mock_tls as mock_tls
from test_observability_service import Inventory

from network_change_delivery import observability_reconciler as reconciler
from network_change_delivery.audit import canonical_json_bytes
from network_change_delivery.observability_realization import (
    ADMISSION_TTL,
    CURRENT_OBSERVABILITY_REALIZATION,
    ObservabilityRealizationError,
    publish_admission,
    read_admission,
    read_admission_for_refresh,
)
from network_change_delivery.observability_service import read_readiness
from network_change_delivery.observability_targets import (
    TargetFailureClassification,
    TargetGenerationState,
    publish_generation,
    read_generation,
    targets_from_inventory,
)
from network_change_delivery.profile_inventory import (
    OBSERVABILITY_SCOPE,
    population_scope,
)


@pytest.mark.parametrize(
    "age", [ADMISSION_TTL + timedelta(microseconds=1), timedelta(days=30)]
)
def test_expired_admission_can_seed_fresh_cml_revalidation(tmp_path, monkeypatch, age):
    root = tmp_path / "observability"
    client = authority()
    previous = admit(client, datetime.now(UTC) - age)
    client.close()
    publish_admission(root, previous)
    with pytest.raises(ObservabilityRealizationError, match="expired"):
        read_admission(root)
    monkeypatch.setattr(reconciler, "STATE_ROOT", root)
    monkeypatch.setattr(
        reconciler,
        "_settings",
        lambda: dict.fromkeys(
            ("cml_address", "cml_certificate", "cml_username", "cml_password"),
            "synthetic",
        ),
    )
    calls = []

    def fresh_authority(*_args):
        calls.append("CML")
        return authority()

    monkeypatch.setattr(reconciler, "CmlRealizationAuthority", fresh_authority)
    _, refreshed = reconciler._refresh_admission()
    assert calls == ["CML"]
    assert refreshed.admitted_at > previous.expires_at
    assert refreshed.expires_at == refreshed.admitted_at + ADMISSION_TTL
    assert read_admission(root) == refreshed


@pytest.fixture
def world(tmp_path, monkeypatch):
    """Real private publications/readers with external boundaries replaced only."""
    root = tmp_path / "observability"
    client = authority()
    previous = admit(client, datetime.now(UTC) - timedelta(days=30))
    client.close()
    path = publish_admission(root, previous)
    # Simulate targets left behind when a previously healthy service went offline.
    publish_generation(
        root,
        state=TargetGenerationState.ACTIVE,
        targets=targets_from_inventory(Inventory()),
        realization=previous,
        now=previous.admitted_at,
    )
    ready = root / "runtime/observability-ready.json"
    ready.write_text("old readiness must be invalidated")
    ready.chmod(0o600)
    calls = []
    state = SimpleNamespace(
        root=root, path=path, previous=previous, calls=calls, cml_failed=False
    )
    monkeypatch.setattr(reconciler, "STATE_ROOT", root)
    monkeypatch.setattr(reconciler, "CONFIG_ROOT", tmp_path / "config")
    monkeypatch.setattr(reconciler, "_runtime_source_commit", lambda: "a" * 40)
    monkeypatch.setattr(reconciler, "_private_text", lambda _p: "/synthetic")
    monkeypatch.setattr(
        reconciler,
        "_settings",
        lambda: dict.fromkeys(
            (
                "netbox_url",
                "cml_address",
                "cml_certificate",
                "cml_username",
                "cml_password",
            ),
            "synthetic",
        ),
    )

    def cml(*_args):
        calls.append("fresh CML")
        assert not ready.exists()
        return authority(booted=not state.cml_failed)

    monkeypatch.setattr(reconciler, "CmlRealizationAuthority", cml)

    def publish(root, value):
        calls.append("fresh admission publication")
        assert value.admitted_at > previous.admitted_at
        return publish_admission(root, value)

    monkeypatch.setattr(reconciler, "publish_admission", publish)
    monkeypatch.setattr(
        reconciler,
        "NetBoxProfileInventoryProvider",
        lambda *_args: calls.append("managed population") or Inventory(),
    )
    monkeypatch.setattr(
        reconciler, "run_compose", lambda *_args: calls.append("compose")
    )
    monkeypatch.setattr(reconciler, "inspect_containers", lambda: {})
    monkeypatch.setattr(
        reconciler,
        "verify_container_definitions",
        lambda *_args, **_kwargs: (
            calls.append("container verification") or ("b" * 64, "c" * 64)
        ),
    )
    monkeypatch.setattr(
        reconciler,
        "wait_service_health",
        lambda **kwargs: calls.append(("health", kwargs["require_device_targets"])),
    )
    return state


@pytest.mark.parametrize(
    "age", [timedelta(minutes=1), ADMISSION_TTL, timedelta(days=30)]
)
def test_reconciliation_republishes_fresh_admission_exact_targets_and_readiness(
    world, age
):
    client = authority()
    seed = admit(client, datetime.now(UTC) - age)
    client.close()
    publish_admission(world.root, seed)
    started = datetime.now(UTC)
    digest = reconciler._reconcile_locked()
    admission = read_admission(world.root)
    generation = read_generation(world.root)
    marker = read_readiness(
        world.root,
        generation,
        prometheus_container_id="b" * 64,
        blackbox_container_id="c" * 64,
        source_commit="a" * 40,
    )
    assert admission.admitted_at >= started
    assert admission.expires_at == admission.admitted_at + ADMISSION_TTL
    assert admission.digest != seed.digest
    assert generation.digest == digest
    assert generation.realization_digest == admission.digest
    assert generation.state is TargetGenerationState.ACTIVE
    assert (
        tuple(t.inventory_object_id for t in generation.targets)
        == OBSERVABILITY_SCOPE.identities
    )
    assert [(t.management_service.value, t.port) for t in generation.targets] == [
        ("ssh", 22),
        ("netconf", 830),
        ("ssh", 22),
        ("ssh", 22),
    ]
    assert (
        admission.schema_version,
        generation.schema_version,
        marker.schema_version,
    ) == ("4", "3", "3")
    assert marker.targets == OBSERVABILITY_SCOPE.identities
    assert world.calls == [
        "fresh CML",
        "fresh admission publication",
        "managed population",
        "compose",
        "container verification",
        ("health", True),
    ]


def assert_failed_empty(world):
    generation = read_generation(world.root)
    assert generation.state is TargetGenerationState.FAILED
    assert (
        generation.failure_classification
        is TargetFailureClassification.REALIZATION_REJECTED
    )
    assert generation.targets == ()
    assert json.loads((world.root / "discovery/targets.json").read_bytes()) == []
    assert not (world.root / "runtime/observability-ready.json").exists()


def test_expired_seed_cml_failure_cannot_publish_targets_or_readiness(world):
    original = world.path.read_bytes()
    world.cml_failed = True
    with pytest.raises(reconciler.AdmissionRefreshError) as caught:
        reconciler._reconcile_locked()
    assert caught.value.stage is reconciler.AdmissionRefreshStage.CML_REVALIDATION
    assert world.calls == ["fresh CML"]
    assert world.path.read_bytes() == original
    assert_failed_empty(world)


def test_missing_admission_stays_intentionally_retired_without_cml(world):
    world.path.unlink()
    assert reconciler._reconcile_locked() == "RETIRED"
    assert read_generation(world.root).state is TargetGenerationState.RETIRED
    assert world.calls == ["compose", "container verification", ("health", False)]
    assert not world.path.exists()
    assert not (world.root / "runtime/observability-ready.json").exists()


def rehash(payload):
    payload["digest"] = (
        "sha256:"
        + hashlib.sha256(
            canonical_json_bytes({k: v for k, v in payload.items() if k != "digest"})
        ).hexdigest()
    )


@pytest.mark.parametrize(
    "case",
    [
        "json",
        "digest",
        "old-v3",
        "wrong-schema",
        "catalog",
        "lab",
        "node-id",
        "device-id",
        "missing-node",
        "extra-node",
        "reordered",
        "malformed-time",
        "naive-expiry",
        "reversed-time",
        "unknown-field",
        "file-mode",
        "symlink",
        "dangling-link",
        "hardlink",
        "directory",
        "operator-symlink",
        "operator-mode",
    ],
)
def test_invalid_retained_state_fails_before_cml_and_clears_targets(world, case):
    payload = json.loads(world.path.read_bytes())
    if case == "json":
        world.path.write_text("{invalid synthetic JSON")
    elif case == "file-mode":
        world.path.chmod(0o644)
    elif case in {"symlink", "dangling-link"}:
        target = world.path.with_name("retained")
        world.path.rename(target)
        world.path.symlink_to(
            target if case == "symlink" else target.with_name("absent")
        )
    elif case == "hardlink":
        os.link(world.path, world.path.with_name("second-link"))
    elif case == "directory":
        world.path.unlink()
        world.path.mkdir()
    elif case == "operator-symlink":
        target = world.root / "retained-operator"
        world.path.parent.rename(target)
        world.path.parent.symlink_to(target, target_is_directory=True)
    elif case == "operator-mode":
        world.path.parent.chmod(0o755)
    else:
        if case == "digest":
            payload["digest"] = "sha256:" + "0" * 64
        elif case in {"old-v3", "wrong-schema"}:
            payload["schema_version"] = "3" if case == "old-v3" else "99"
            if case == "old-v3":
                payload.pop("catalog")  # Exact pre-scoped shape, valid old self-digest.
        elif case == "catalog":
            scope = population_scope("other-reviewed-scope", ("netbox:dcim.device:1",))
            payload["catalog"] = CURRENT_OBSERVABILITY_REALIZATION.project(
                scope
            ).model_dump(mode="json")
            payload["nodes"] = payload["nodes"][:1]
        elif case == "lab":
            payload["lab_id"] = "99999999-9999-9999-9999-999999999999"
        elif case in {"node-id", "device-id"}:
            key = "cml_node_id" if case == "node-id" else "inventory_object_id"
            payload["nodes"][0][key] = (
                "99999999-9999-9999-9999-999999999999"
                if case == "node-id"
                else "netbox:dcim.device:99"
            )
        elif case == "missing-node":
            payload["nodes"].pop()
        elif case == "extra-node":
            payload["nodes"].append(payload["nodes"][0])
        elif case == "reordered":
            payload["nodes"].reverse()
        elif case == "malformed-time":
            payload["admitted_at"] = "invalid"
        elif case == "naive-expiry":
            payload["expires_at"] = "2026-01-01T00:00:00"
        elif case == "reversed-time":
            payload["expires_at"] = payload["admitted_at"]
        elif case == "unknown-field":
            payload["unreviewed"] = "synthetic-private-value"
        if case != "digest":
            rehash(payload)
        world.path.write_bytes(canonical_json_bytes(payload))
    with pytest.raises(reconciler.AdmissionRefreshError) as caught:
        reconciler._reconcile_locked()
    assert caught.value.stage is reconciler.AdmissionRefreshStage.ADMISSION_READ
    assert world.calls == []
    assert_failed_empty(world)
    assert (
        "synthetic-private-value"
        not in (world.root / "runtime/target-generation.json").read_text()
    )


def test_refresh_reader_requires_caller_owned_catalog_and_preserves_scoped_reader(
    world,
):
    scope = population_scope("small-consumer", ("netbox:dcim.device:1",))
    catalog = CURRENT_OBSERVABILITY_REALIZATION.project(scope)
    client = authority()
    record = client.admit(
        world.previous.lab_id,
        {"netbox:dcim.device:1": world.previous.nodes[0].cml_node_id},
        catalog=catalog,
    )
    client.close()
    publish_admission(world.root, record)
    with pytest.raises(ObservabilityRealizationError):
        read_admission_for_refresh(world.root)
    assert read_admission_for_refresh(world.root, catalog=catalog) == record
    assert read_admission(world.root, catalog=catalog) == record
