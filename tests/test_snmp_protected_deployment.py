"""Promotion and sole-deploy-gate contracts for SNMP provisioning."""

from __future__ import annotations

import json
import re
from argparse import Namespace
from datetime import UTC, datetime
from pathlib import Path

import yaml

from network_change_delivery import cli
from network_change_delivery.assurance import prepare_snapshot
from network_change_delivery.buildkite_audit import (
    _correlation_values,
    validate_snmp_record,
)
from network_change_delivery.buildkite_deployment import LiveDeploymentRequest
from network_change_delivery.buildkite_policy import BuildkiteDeploymentContext
from network_change_delivery.models import InventoryDevice
from network_change_delivery.plan_assurance import (
    SnmpPlanSnapshotMutation,
    load_plan,
    materialize_candidate,
    subject_from_plan,
)
from network_change_delivery.secrets import DeviceCredentials
from network_change_delivery.snmp_credentials import snmp_username
from network_change_delivery.snmp_provisioning import (
    SnmpOwnedObjectState,
    SnmpProvisioningOutcome,
    SnmpProvisioningPlan,
    SnmpProvisioningRecord,
    SnmpProvisioningStage,
    SnmpV3InterfaceTelemetryIntent,
    build_snmp_provisioning_plan,
)
from network_change_delivery.snmp_telemetry import SnmpCredentialReference

ROOT = Path(__file__).resolve().parents[1]


def snmp_plan(platform: str = "cisco_iosxe") -> SnmpProvisioningPlan:
    device_id = 1 if platform == "cisco_iosxe" else 2
    identity = f"netbox:dcim.device:{device_id}"
    name = "core-02" if device_id == 1 else "edge-junos-01"
    intent = SnmpV3InterfaceTelemetryIntent(
        change_id=f"CHG-SNMP-{device_id}",
        target=name,
        device=identity,
        platform=platform,
        username=snmp_username(device_id),
        credential=SnmpCredentialReference(
            device=identity,
            reference=f"snmpv3:{identity}:generation:v1",
            auth_selector=f"device_{device_id}_v1",
        ),
    )
    return build_snmp_provisioning_plan(
        intent,
        InventoryDevice(
            name=name,
            host="192.0.2.10",
            port=22 if platform == "cisco_iosxe" else 830,
            platform=platform,
            expected_hostname=name,
            inventory_source="netbox",
            inventory_object_id=identity,
        ),
        SnmpOwnedObjectState(
            observed_hostname=name,
            local_engine_id_present=True,
            view="ABSENT",
            group="ABSENT",
            user="ABSENT",
        ),
        created_at=datetime(2026, 8, 29, tzinfo=UTC),
    )


def test_snmp_plan_loads_as_typed_sibling_and_binds_live_request(
    tmp_path: Path,
) -> None:
    value = snmp_plan()
    path = tmp_path / "plan.json"
    path.write_text(value.model_dump_json(), encoding="utf-8")
    loaded = load_plan(path)
    assert isinstance(loaded, SnmpProvisioningPlan)
    assert loaded == value
    assert subject_from_plan(value).plan_type == "snmp_provisioning_plan"
    LiveDeploymentRequest(
        schema_version="1",
        action="deploy",
        change_id=value.change_id,
        plan_digest=value.digest,
        inventory_object_id=value.inventory_object_id,
    ).verify_plan(value)


def test_read_only_planner_creates_promotable_plan_without_snmp_secret(
    tmp_path: Path, monkeypatch
) -> None:
    value = snmp_plan()
    change = tmp_path / "intent.yaml"
    output = tmp_path / "plan.json"
    intent = SnmpV3InterfaceTelemetryIntent(
        change_id=value.change_id,
        target=value.target,
        device=value.inventory_object_id,
        platform=value.platform,
        username=value.username,
        credential=value.snmp_credential,
    )
    change.write_text(
        yaml.safe_dump(intent.model_dump(mode="json"), sort_keys=True),
        encoding="utf-8",
    )
    events: list[str] = []

    class Inventory:
        def resolve(self, target: str) -> InventoryDevice:
            events.append("inventory")
            assert target == value.target
            return InventoryDevice(
                name=value.target,
                host=value.host,
                port=value.port,
                platform=value.platform,
                expected_hostname=value.expected_hostname,
                inventory_source="netbox",
                inventory_object_id=value.inventory_object_id,
            )

    class Secrets:
        def load(self, _device: InventoryDevice) -> DeviceCredentials:
            events.append("ssh-secret")
            return DeviceCredentials("ssh-user", "ssh-secret-sentinel")

    class Adapter:
        def preflight(self, _device, credentials, subject):
            events.append("read-only-preflight")
            assert credentials.password == "ssh-secret-sentinel"
            assert isinstance(subject, SnmpV3InterfaceTelemetryIntent)
            return value.preconditions

    monkeypatch.setattr(cli, "NetBoxInventoryProvider", Inventory)
    monkeypatch.setattr(cli, "OpenBaoSecretProvider", Secrets)
    monkeypatch.setattr(cli, "MultiVendorAdapter", Adapter)
    assert cli._run_snmp_provisioning_plan(Namespace(change=change, output=output)) == 0
    generated = SnmpProvisioningPlan.model_validate_json(output.read_text())
    assert generated.inventory_object_id == value.inventory_object_id
    assert generated.snmp_credential == value.snmp_credential
    assert events == ["inventory", "ssh-secret", "read-only-preflight"]
    assert "ssh-secret-sentinel" not in output.read_text()
    assert "authentication_secret" not in output.read_text()


def test_offline_assurance_candidate_contains_only_nonsecret_structural_subset(
    tmp_path: Path,
) -> None:
    baseline = tmp_path / "baseline"
    configs = baseline / "configs"
    configs.mkdir(parents=True)
    (configs / "core-02.cfg").write_text(
        "hostname core-02\ninterface GigabitEthernet1\n no shutdown\n",
        encoding="utf-8",
    )
    value = snmp_plan()
    with prepare_snapshot(baseline) as prepared:
        candidate, derivation = materialize_candidate(prepared, value)
        with candidate:
            rendered = (candidate.root / "configs/core-02.cfg").read_text()
    assert len(derivation) == 1
    assert isinstance(derivation[0], SnmpPlanSnapshotMutation)
    assert derivation[0].secret_bearing_user_omitted is True
    assert f"snmp-server group {value.group_name} v3 priv read" in rendered
    assert f"snmp-server user {value.username}" not in rendered
    for forbidden in ("authentication_secret", "privacy_secret", "password"):
        assert forbidden not in rendered.casefold()


def test_pipeline_retains_one_protected_write_path_for_typed_single_device_plans() -> (
    None
):
    pipeline = (ROOT / ".buildkite/pipeline.yml").read_text(encoding="utf-8")
    gate = (ROOT / "scripts/buildkite/deployment_gate.sh").read_text(encoding="utf-8")
    assert pipeline.count("key: deploy-gate") == 1
    assert pipeline.count("key: deployment-approval") == 1
    assert "snmp-deploy" not in pipeline
    assert "buildkite-live-plan-kind" in gate
    assert "snmpv3_interface_telemetry" in gate
    assert "snmp-deploy" not in pipeline


def test_live_input_rejects_secret_fields_but_allows_controlled_username(
    tmp_path: Path,
) -> None:
    source = tmp_path / "plan.json"
    source.write_text(
        '{"username":"ncdp_snmp_d1_v1", "authentication_secret":"sentinel"}',
        encoding="utf-8",
    )
    forbidden = re.compile(r"(?i)(authentication_secret|privacy_secret|password)")
    assert forbidden.search(source.read_text(encoding="utf-8")) is not None


def test_plan_and_public_evidence_surfaces_cannot_contain_secret_fields() -> None:
    payload = json.loads(snmp_plan().model_dump_json())
    serialized = json.dumps(payload, sort_keys=True)
    assert "authentication_secret" not in serialized
    assert "privacy_secret" not in serialized
    assert "password" not in serialized


def test_audit_correlation_records_device_scope_and_two_separate_references() -> None:
    value = snmp_plan()
    context = BuildkiteDeploymentContext(
        commit="a" * 40,
        branch="main",
        pipeline_id="01a02ab4-2472-4726-be31-dbf4f216210f",
        build_id="01a02ab4-2472-4726-be31-dbf4f2162101",
        build_number="243",
        job_id="01a02ab4-2472-4726-be31-dbf4f2162102",
        step_key="deploy-gate",
        queue_key="ncdp-deploy",
    )
    _git, _buildkite, target, credentials = _correlation_values(
        context, "https://github.com/example/repository.git", value
    )
    assert target.device == value.inventory_object_id
    assert target.interface is None
    assert [item.source for item in credentials] == ["openbao", "openbao_snmp"]
    assert credentials[0].reference.endswith("/ssh")
    assert credentials[1].reference == value.snmp_credential.reference


def test_snmp_evidence_binds_only_normalized_nonsecret_plan_identity() -> None:
    value = snmp_plan()
    stage = SnmpProvisioningStage(
        attempted=True, succeeded=True, message="bounded normalized result"
    )
    record = SnmpProvisioningRecord(
        generated_at=datetime(2026, 8, 29, tzinfo=UTC),
        change_id=value.change_id,
        plan_digest=value.digest,
        approval_digest=value.digest,
        device=value.inventory_object_id,
        platform=value.platform,
        generation=value.generation,
        username=value.username,
        credential_reference=value.snmp_credential.reference,
        view_name=value.view_name,
        group_name=value.group_name,
        oid_closure_digest=value.oid_closure_digest,
        preflight=stage,
        execution=stage,
        post_validation=stage,
        recovery=SnmpProvisioningStage(message="not required"),
        final_outcome=SnmpProvisioningOutcome.SUCCEEDED,
    )
    validate_snmp_record(record, value)
    serialized = record.model_dump_json()
    for forbidden in (
        "authentication_secret",
        "privacy_secret",
        "localized",
        "running configuration",
    ):
        assert forbidden not in serialized.casefold()
