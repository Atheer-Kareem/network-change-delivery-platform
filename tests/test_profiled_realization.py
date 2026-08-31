"""B3-1 four-device realization, trust, and STAGING authority tests."""

from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError
from test_profiled_population import devices, profiled_provider

from network_change_delivery.architecture_contracts import (
    AutomationProfileID,
    CmlRealizationProfileID,
    ManagementEndpoint,
    ManagementEndpointPurpose,
)
from network_change_delivery.profile_inventory import (
    ProfiledInventoryDevice,
    ProfileReadOnlyTarget,
)
from network_change_delivery.profiled_realization import (
    CmlAnchoredHostTrustGeneration,
    CmlAnchoredHostTrustRecord,
    EvidenceReference,
    PersistentProfiledRealization,
    ProfiledRealizationError,
    ProfiledRealizedDevice,
    RealizationEnvironment,
    RealizationLifecycleState,
    SSHHostKeyType,
    StagingRealizationContext,
    StagingRealizedDevice,
)

ROOT = Path(__file__).parents[1]
LAB_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
NODE_IDS = (
    "10000000-0000-4000-8000-000000000001",
    "10000000-0000-4000-8000-000000000002",
    "10000000-0000-4000-8000-000000000003",
    "10000000-0000-4000-8000-000000000004",
)
FINGERPRINT = "SHA256:mNQp+RgW/Rudeag+8Keh0OAQTMF2bwLhb1MkX9sCwXg"


def evidence(name: str, digit: str = "a") -> EvidenceReference:
    return EvidenceReference(identity=f"evidence:{name}", digest=f"sha256:{digit * 64}")


def inventory_devices() -> tuple[ProfiledInventoryDevice, ...]:
    return profiled_provider(devices()).resolve_profiled_population().devices


def live_devices() -> tuple[ProfiledRealizedDevice, ...]:
    return tuple(
        ProfiledRealizedDevice(
            device_identity=device.device_identity,
            logical_name=device.logical_name,
            operational_role=device.operational_role,
            automation_profile_id=device.automation_profile_id,
            cml_realization_profile_id=device.cml_realization_profile_id,
            cml_node_id=node_id,
            lifecycle_state=RealizationLifecycleState.READY,
            readiness_evidence=evidence(f"live-ready-{device.logical_name}", "9"),
            management_endpoint=device.management_endpoints.live,
        )
        for device, node_id in zip(inventory_devices(), NODE_IDS, strict=True)
    )


def persistent(
    *, devices_: tuple[ProfiledRealizedDevice, ...] | None = None
) -> PersistentProfiledRealization:
    now = datetime.now(UTC)
    return PersistentProfiledRealization(
        realization_identity="ncdp-live",
        cml_lab_id=LAB_ID,
        cml_lab_title="NCDP Live",
        lifecycle_state=RealizationLifecycleState.READY,
        admitted_at=now,
        expires_at=now + timedelta(minutes=15),
        admission_evidence=evidence("live-admission"),
        devices=devices_ or live_devices(),
    )


def staging_devices() -> tuple[StagingRealizedDevice, ...]:
    return tuple(
        StagingRealizedDevice(
            device_identity=device.device_identity,
            logical_name=device.logical_name,
            operational_role=device.operational_role,
            automation_profile_id=device.automation_profile_id,
            cml_realization_profile_id=device.cml_realization_profile_id,
            cml_node_id=node_id,
            staging_endpoint=device.management_endpoints.staging,
            readiness_evidence=evidence(f"ready-{device.logical_name}", "b"),
            trust_evidence=evidence(f"trust-{device.logical_name}", "c"),
        )
        for device, node_id in zip(inventory_devices(), NODE_IDS, strict=True)
    )


def staging_context(
    *,
    state: RealizationLifecycleState = RealizationLifecycleState.READY,
    devices_: tuple[StagingRealizedDevice, ...] | None = None,
    admitted_at: datetime | None = None,
    expires_at: datetime | None = None,
) -> StagingRealizationContext:
    admitted = admitted_at or datetime.now(UTC) - timedelta(seconds=1)
    expires = expires_at or datetime.now(UTC) + timedelta(minutes=10)
    return StagingRealizationContext(
        staging_run_id="run-001",
        cml_lab_id=LAB_ID,
        cml_lab_title="NCDP Staging run-001",
        lifecycle_state=state,
        admitted_at=admitted,
        expires_at=expires,
        topology_evidence=evidence("topology", "d"),
        devices=devices_ or staging_devices(),
    )


def trust_records() -> tuple[CmlAnchoredHostTrustRecord, ...]:
    generation = evidence("trust-generation", "e")
    return tuple(
        CmlAnchoredHostTrustRecord(
            environment=RealizationEnvironment.LIVE,
            realization_identity="ncdp-live",
            cml_lab_id=LAB_ID,
            cml_node_id=node_id,
            device_identity=device.device_identity,
            logical_name=device.logical_name,
            management_address=device.management_endpoints.live.binding.l3_endpoint.address.ip,
            management_port=device.management_endpoints.live.binding.l3_endpoint.port,
            automation_profile_id=device.automation_profile_id,
            cml_realization_profile_id=device.cml_realization_profile_id,
            host_key_type=SSHHostKeyType.SSH_RSA,
            host_key_fingerprint=FINGERPRINT,
            cml_anchor_evidence=evidence(f"anchor-{device.logical_name}", "f"),
            admitted_at=datetime.now(UTC),
            trust_generation=generation,
        )
        for device, node_id in zip(inventory_devices(), NODE_IDS, strict=True)
    )


def trust_generation(
    *, records: tuple[CmlAnchoredHostTrustRecord, ...] | None = None
) -> CmlAnchoredHostTrustGeneration:
    now = datetime.now(UTC)
    return CmlAnchoredHostTrustGeneration(
        environment=RealizationEnvironment.LIVE,
        realization_identity="ncdp-live",
        cml_lab_id=LAB_ID,
        admitted_at=now,
        expires_at=now + timedelta(minutes=15),
        generation_evidence=evidence("trust-generation", "e"),
        records=records or trust_records(),
    )


def test_exact_four_persistent_realization_is_immutable_and_profile_bound() -> None:
    realization = persistent()
    assert realization.environment is RealizationEnvironment.LIVE
    assert len(realization.devices) == 4
    assert tuple(item.logical_name for item in realization.devices) == tuple(
        device.logical_name for device in inventory_devices()
    )
    with pytest.raises(ValidationError):
        PersistentProfiledRealization.model_validate(
            realization.model_dump(mode="json") | {"unexpected": True}
        )


@pytest.mark.parametrize("population_size", [3, 5])
def test_persistent_realization_rejects_missing_or_extra_binding(
    population_size: int,
) -> None:
    realized = list(live_devices())
    if population_size == 3:
        realized.pop()
    else:
        realized.append(realized[-1])
    with pytest.raises(ValidationError, match="exact four"):
        persistent(devices_=tuple(realized))


def test_persistent_realization_rejects_duplicate_cml_node() -> None:
    realized = list(live_devices())
    realized[1] = realized[1].model_copy(update={"cml_node_id": NODE_IDS[0]})
    with pytest.raises(ValidationError, match="CML node identities are duplicated"):
        persistent(devices_=tuple(realized))


def test_realized_device_rejects_wrong_name_profile_and_management_binding() -> None:
    core, edge, *_ = inventory_devices()
    with pytest.raises(ValidationError, match="Git profile catalog"):
        ProfiledRealizedDevice(
            device_identity=core.device_identity,
            logical_name=core.logical_name,
            operational_role=core.operational_role,
            automation_profile_id=AutomationProfileID.IOSV_159_3_M12,
            cml_realization_profile_id=CmlRealizationProfileID.IOSV_159_3_M12,
            cml_node_id=NODE_IDS[0],
            lifecycle_state=RealizationLifecycleState.READY,
            readiness_evidence=evidence("wrong-profile-ready", "9"),
            management_endpoint=core.management_endpoints.live,
        )
    with pytest.raises(ValidationError, match="wrong stable device"):
        ProfiledRealizedDevice(
            device_identity=core.device_identity,
            logical_name=core.logical_name,
            operational_role=core.operational_role,
            automation_profile_id=core.automation_profile_id,
            cml_realization_profile_id=core.cml_realization_profile_id,
            cml_node_id=NODE_IDS[0],
            lifecycle_state=RealizationLifecycleState.READY,
            readiness_evidence=evidence("wrong-binding-ready", "9"),
            management_endpoint=edge.management_endpoints.live,
        )


def test_exact_cml_anchored_host_trust_generation_passes() -> None:
    generation = trust_generation()
    assert len(generation.records) == 4
    assert all(record.cml_anchor_evidence for record in generation.records)
    assert all(
        record.trust_generation == generation.generation_evidence
        for record in generation.records
    )


def test_host_trust_rejects_malformed_or_unanchored_record() -> None:
    payload = trust_records()[0].model_dump(mode="json")
    payload["host_key_fingerprint"] = "SHA256:not-a-fingerprint"
    with pytest.raises(ValidationError):
        CmlAnchoredHostTrustRecord.model_validate(payload)
    payload = trust_records()[0].model_dump(mode="json")
    payload.pop("cml_anchor_evidence")
    with pytest.raises(ValidationError):
        CmlAnchoredHostTrustRecord.model_validate(payload)


def test_host_trust_generation_rejects_duplicate_stable_or_cml_identity() -> None:
    records = list(trust_records())
    records[1] = records[1].model_copy(
        update={
            "device_identity": records[0].device_identity,
            "cml_node_id": records[0].cml_node_id,
        }
    )
    with pytest.raises(ValidationError, match="identities are duplicated"):
        trust_generation(records=tuple(records))


def test_normal_host_trust_evidence_has_no_raw_public_key_field() -> None:
    model_names = {
        "public_key",
        "public_key_blob",
        "raw_public_key",
        "known_hosts",
        "private_key",
    }
    assert model_names.isdisjoint(CmlAnchoredHostTrustRecord.model_fields)
    assert model_names.isdisjoint(CmlAnchoredHostTrustGeneration.model_fields)


def test_ready_staging_context_projects_only_exact_staging_target() -> None:
    device = inventory_devices()[0]
    context = staging_context()
    target = context.staging_read_only_target(device)
    staging = device.management_endpoints.staging.binding.l3_endpoint
    live = device.management_endpoints.live.binding.l3_endpoint
    assert isinstance(target, ProfileReadOnlyTarget)
    assert target.host == str(staging.address.ip)
    assert target.host != str(live.address.ip)
    assert target.automation_profile_id is device.automation_profile_id


def test_staging_context_rejects_live_substitution_or_wrong_staging_ip() -> None:
    device = inventory_devices()[0]
    realized = list(staging_devices())
    realized[0] = realized[0].model_copy(
        update={
            "staging_endpoint": ManagementEndpoint(
                purpose=ManagementEndpointPurpose.STAGING,
                binding=device.management_endpoints.live.binding,
            )
        }
    )
    with pytest.raises(ProfiledRealizationError, match="does not match"):
        staging_context(devices_=tuple(realized)).staging_read_only_target(device)

    realized = list(staging_devices())
    endpoint = realized[0].staging_endpoint
    wrong_l3 = endpoint.binding.l3_endpoint.model_copy(
        update={"ip_address_identity": "netbox:ipam.ipaddress:999"}
    )
    wrong_binding = endpoint.binding.model_copy(update={"l3_endpoint": wrong_l3})
    realized[0] = realized[0].model_copy(
        update={
            "staging_endpoint": endpoint.model_copy(update={"binding": wrong_binding})
        }
    )
    with pytest.raises(ProfiledRealizationError, match="does not match"):
        staging_context(devices_=tuple(realized)).staging_read_only_target(device)


@pytest.mark.parametrize(
    "state",
    [
        RealizationLifecycleState.PREPARING,
        RealizationLifecycleState.CLEANING,
        RealizationLifecycleState.RETIRED,
        RealizationLifecycleState.FAILED,
        RealizationLifecycleState.AMBIGUOUS,
    ],
)
def test_nonready_staging_context_never_projects(
    state: RealizationLifecycleState,
) -> None:
    with pytest.raises(ProfiledRealizationError, match="not READY"):
        staging_context(state=state).staging_read_only_target(inventory_devices()[0])


def test_expired_or_future_staging_context_never_projects() -> None:
    now = datetime.now(UTC)
    expired = staging_context(
        admitted_at=now - timedelta(minutes=2),
        expires_at=now - timedelta(minutes=1),
    )
    with pytest.raises(ProfiledRealizationError, match="not fresh"):
        expired.staging_read_only_target(inventory_devices()[0])
    future = staging_context(
        admitted_at=now + timedelta(minutes=1),
        expires_at=now + timedelta(minutes=2),
    )
    with pytest.raises(ProfiledRealizationError, match="not fresh"):
        future.staging_read_only_target(inventory_devices()[0])


def test_staging_context_rejects_wrong_device_or_profile_pairing() -> None:
    device = inventory_devices()[0]
    unknown = device.model_copy(update={"device_identity": "netbox:dcim.device:999"})
    with pytest.raises(ProfiledRealizationError, match="exact stable device"):
        staging_context().staging_read_only_target(unknown)
    wrong_profile = device.model_copy(
        update={"automation_profile_id": AutomationProfileID.IOSV_159_3_M12}
    )
    with pytest.raises(ProfiledRealizationError, match="does not match"):
        staging_context().staging_read_only_target(wrong_profile)
    wrong_cml_profile = device.model_copy(
        update={"cml_realization_profile_id": CmlRealizationProfileID.IOSV_159_3_M12}
    )
    with pytest.raises(ProfiledRealizationError, match="does not match"):
        staging_context().staging_read_only_target(wrong_cml_profile)


def test_staging_projection_api_has_no_generic_purpose_or_live_fallback() -> None:
    parameters = inspect.signature(
        StagingRealizationContext.staging_read_only_target
    ).parameters
    assert tuple(parameters) == ("self", "profiled_device")
    assert not hasattr(ProfiledInventoryDevice, "staging_read_only_target")
    assert not hasattr(ProfiledInventoryDevice, "target")
    source = inspect.getsource(StagingRealizationContext.staging_read_only_target)
    assert "live_read_only_target" not in source
    assert "primary_ip4" not in source


def test_new_contract_models_are_secret_free_and_have_no_write_surface() -> None:
    prohibited_fields = {
        "credential",
        "credentials",
        "password",
        "token",
        "secret",
        "private_key",
        "configuration",
        "command",
    }
    models: tuple[type[BaseModel], ...] = (
        ProfiledRealizedDevice,
        PersistentProfiledRealization,
        CmlAnchoredHostTrustRecord,
        CmlAnchoredHostTrustGeneration,
        StagingRealizedDevice,
        StagingRealizationContext,
    )
    for model in models:
        assert prohibited_fields.isdisjoint(model.model_fields)
    for prohibited_method in ("execute", "deploy", "write", "configure", "enroll"):
        assert not hasattr(StagingRealizationContext, prohibited_method)
        assert not hasattr(ProfileReadOnlyTarget, prohibited_method)


def test_current_runtime_does_not_import_b3_realization_contracts() -> None:
    current_paths = (
        "src/network_change_delivery/inventory.py",
        "src/network_change_delivery/observability_realization.py",
        "src/network_change_delivery/oxidized_host_trust.py",
        "src/network_change_delivery/ephemeral_staging.py",
        "src/network_change_delivery/buildkite_deployment.py",
        "src/network_change_delivery/vendor_adapter.py",
        "src/network_change_delivery/fleet.py",
    )
    for path in current_paths:
        assert "profiled_realization" not in (ROOT / path).read_text(encoding="utf-8")
