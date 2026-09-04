"""Regression snapshots proving B1 leaves current v1 contracts unchanged."""

from __future__ import annotations

import hashlib
import inspect
import json
from pathlib import Path

from test_audit_store import change_record, plan, record
from test_configuration_observation import observation_record
from test_fleet import make_plan
from test_fleet_execution import execute

from network_change_delivery.audit import AuditArtifactKind, AuditArtifactReference
from network_change_delivery.models import InventoryDevice
from network_change_delivery.plan_assurance import load_plan

ROOT = Path(__file__).parents[1]


def canonical_sha256(value: object) -> str:
    payload = value.model_dump(mode="json")  # type: ignore[attr-defined]
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def test_representative_v1_models_remain_readable_and_byte_stable() -> None:
    inventory = InventoryDevice(
        name="core-02",
        host="192.0.2.14",
        platform="cisco_iosxe",
        expected_hostname="core-02",
        inventory_source="netbox",
        inventory_object_id="netbox:dcim.device:1",
        inventory_interface_object_id="netbox:dcim.interface:7",
    )
    deployment_plan = plan()
    fleet_plan = make_plan().plan
    assert fleet_plan is not None
    change_evidence = change_record()
    fleet_evidence = execute()[1]
    plan_reference = AuditArtifactReference(
        kind=AuditArtifactKind.DEPLOYMENT_PLAN,
        schema_version="1",
        sha256=deployment_plan.digest,
        locator=(
            f"artifacts/deployment_plan/{deployment_plan.digest.removeprefix('sha256:')}.json"
        ),
        size_bytes=2,
    )
    audit_evidence = record(plan_reference)
    observation_evidence = observation_record()
    promotion_plan = load_plan(ROOT / "deployments/live/promotion/plan.json")

    snapshots = (
        (inventory, "f974621a744618faf5c06af9b61781ef7a4ae65eaf11adc4ae19e3e16a36777a"),
        (
            deployment_plan,
            "ca61e1937b91ba112ac8f14dce3f825663f7c8be4271cbb90dec9738a8d0842a",
        ),
        (
            fleet_plan,
            "3ed13099ea7037f64e78ab66a38ae5fe66d8bb67f307afeb05538d0d93ed4008",
        ),
        (
            change_evidence,
            "12a599910d44d9e7cbdb4b5fb6f356e6885ef729204a2ef0d432beba0ae5c6f0",
        ),
        (
            fleet_evidence,
            "31213eb7151973bff8413ab98ffd687dc661439b86b0461f5ca54290aed72e44",
        ),
        (
            audit_evidence,
            "f555f15ecea8a15adf4e98abd40836076aced942a9ba5472904741a2a2147a1f",
        ),
        (
            observation_evidence,
            "d03ce33120ed35a6f813c405111a5a346e61b6483c3ef596df5321b1f6a01b68",
        ),
        (
            promotion_plan,
            "ce0906abd37feb470adba559d12db4d2418a989394c7227a4875ed24810c5640",
        ),
    )
    for value, expected_sha256 in snapshots:
        serialized = value.model_dump_json()
        assert type(value).model_validate_json(serialized) == value
        assert canonical_sha256(value) == expected_sha256

    assert deployment_plan.schema_version == "1"
    assert deployment_plan.digest == (
        "sha256:2f566ff3a44d5731a9630195b60492cc558faac3569e2fda5191709ca0150d9a"
    )
    assert fleet_plan.schema_version == "1"
    assert fleet_plan.digest == (
        "sha256:e5dc68ba5216376db2eb484c984507b8f2a0ac0bbb068bde0316ec73bd12acbc"
    )
    assert audit_evidence.schema_version == "1"
    assert audit_evidence.digest == (
        "sha256:56fead41faccb2ab748e7b0014f84061dc1e3052df23e7baa4fba1f7fa4cd3ee"
    )
    assert observation_evidence.schema_version == "1"
    assert observation_evidence.digest == (
        "sha256:a98d25023d703e32ccbb1f30683a547cce2d750d7557dbe6bc5fb7f1f70069de"
    )
    assert promotion_plan.schema_version == "1"
    assert promotion_plan.digest == (
        "sha256:3d07ea20778999dc67b9963d7443427b5125b0892ba0503f37dbc8188a19d7f6"
    )


def test_existing_fleet_fixture_and_child_digests_remain_valid() -> None:
    fixture = ROOT / "fixtures/batfish/plans/fleet-interface-description.json"
    from network_change_delivery.models import FleetDeploymentPlan

    approved = FleetDeploymentPlan.model_validate_json(fixture.read_text())
    assert approved.verify_digest()
    assert approved.digest == (
        "sha256:02a3bece7cc1f67ae77e4f3cd436d1366489fa63fddf7b3b442f7115866086f4"
    )
    assert tuple(member.child_plan.digest for member in approved.members) == (
        "sha256:83d52e39c673063dce142ae79c878d2b874909ab1ce9c8de30d0be81e47983ec",
        "sha256:060db13dbe0a938ec80c8d0b66f74be0a8d4f8173223f5b0e9b5e6737fe1f5a0",
        "sha256:cd9200fccf8fe5e0c37b03d3c89561b59c7d828fb2a330d8c4c844752365c467",
    )


def test_dormant_v1_compatibility_modules_do_not_import_profiled_runtime() -> None:
    compatibility_modules = (
        "workflow.py",
        "vendor_adapter.py",
        "fleet.py",
        "buildkite_deployment.py",
        "ephemeral_staging.py",
    )
    for filename in compatibility_modules:
        source = (ROOT / "src/network_change_delivery" / filename).read_text(
            encoding="utf-8"
        )
        assert "profile_inventory" not in source
        assert "profile_read_only_adapter" not in source

    from network_change_delivery import cli

    source = inspect.getsource(cli)
    assert "MultiVendorAdapter" not in source
    assert "NetBoxInventoryProvider" not in source
    assert "deploy_plan" not in source
