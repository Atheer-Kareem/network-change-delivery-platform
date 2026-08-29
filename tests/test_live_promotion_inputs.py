"""Contracts for the repository-owned 10C-7 single-device promotion input."""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

from network_change_delivery.assurance import (
    AssuranceObservation,
    AssuranceOutcome,
    FlowResult,
    ParseFileResult,
    ParseSummary,
    build_snapshot_manifest,
)
from network_change_delivery.models import DeploymentPlan
from network_change_delivery.plan_assurance import (
    BatfishAssurancePolicy,
    assure_plan,
    load_plan,
)
from network_change_delivery.promotion import (
    create_promotion_bundle,
    verify_promotion_bundle,
)
from network_change_delivery.snmp_credentials import snmp_username
from network_change_delivery.snmp_mib import APPROVED_DEVICE_VIEW_OIDS
from network_change_delivery.snmp_provisioning import (
    SnmpProvisioningPlan,
    oid_closure_digest,
)

ROOT = Path(__file__).parents[1]
INPUTS = ROOT / "deployments/live/promotion"
PLAN = INPUTS / "plan.json"
POLICY = INPUTS / "policy.yaml"
BASELINE = INPUTS / "baseline"

_FORBIDDEN_LIVE_INPUT_SECRET = re.compile(
    r"(?i)(authentication_secret|privacy_secret|password|private[_ -]?key|"
    r"snmp-server community|enable secret|secret_id|client_token|x-vault-token|"
    r"certificate|aaa (authentication|authorization|accounting)|"
    r"authorization:\s*bearer)"
)


def _forbidden_live_input_secret(text: str) -> re.Match[str] | None:
    return _FORBIDDEN_LIVE_INPUT_SECRET.search(text)


def _assert_live_input_secret_free(root: Path) -> None:
    for source in sorted(root.rglob("*")):
        if source.is_file():
            assert (
                _forbidden_live_input_secret(source.read_text(encoding="utf-8")) is None
            )


class PassingProvider:
    def __init__(self, policy: BatfishAssurancePolicy) -> None:
        self.policy = policy

    def analyze(self, baseline, candidate, _intent):
        def summary(root):
            manifest = build_snapshot_manifest(root)
            return ParseSummary(
                files=tuple(
                    ParseFileResult(relative_path=item.relative_path, status="PASSED")
                    for item in manifest.files
                ),
                nodes=tuple(sorted(self.policy.expected_nodes)),
                initialization_issue_count=0,
            )

        return AssuranceObservation(
            pybatfish_version="2025.7.7.2423",
            batfish_version="2026.07.20.3565",
            baseline=summary(baseline),
            candidate=summary(candidate),
            flows=(
                FlowResult(
                    source_node="core-02",
                    source_ip="10.6.12.1",
                    destination_ip="10.6.12.2",
                    baseline_reachable=True,
                    candidate_reachable=True,
                ),
            ),
            differential_changed_flow_count=0,
        )


def live_plan() -> DeploymentPlan | SnmpProvisioningPlan:
    plan = load_plan(PLAN)
    assert isinstance(plan, (DeploymentPlan, SnmpProvisioningPlan))
    return plan


def policy() -> BatfishAssurancePolicy:
    return BatfishAssurancePolicy.model_validate(
        yaml.safe_load(POLICY.read_text(encoding="utf-8"))
    )


def test_active_plan_is_single_device_digest_verified_and_exactly_provenanced() -> None:
    payload = json.loads(PLAN.read_text(encoding="utf-8"))
    assert "members" not in payload
    plan = live_plan()
    assert plan.verify_digest()
    assert plan.inventory_source == "netbox"
    request = yaml.safe_load((ROOT / "deployments/live/request.yaml").read_text())
    assert request["change_id"] == plan.change_id
    assert request["plan_digest"] == plan.digest
    assert request["inventory_object_id"] == plan.inventory_object_id
    if isinstance(plan, DeploymentPlan):
        assert plan.inventory_object_id == "netbox:dcim.device:1"
        assert plan.inventory_object_id == "netbox:dcim.device:1"
        assert plan.inventory_interface_object_id == "netbox:dcim.interface:2"
        assert plan.credential_source == "openbao"
        assert plan.credential_reference == "openbao:kv-v2:ncdp/devices/1/ssh"
        assert plan.interface == "GigabitEthernet2"
        assert plan.interface != "GigabitEthernet1"
        assert plan.preconditions.interface_exists is True
        assert plan.preconditions.interface_protected is False
    else:
        device_id = int(plan.inventory_object_id.rsplit(":", 1)[1])
        assert plan.platform in {"cisco_iosxe", "junos"}
        assert device_id in {1, 2}
        expected_device = {
            1: ("core-02", "cisco_iosxe"),
            2: ("edge-junos-01", "junos"),
        }[device_id]
        assert (plan.target, plan.platform) == expected_device
        assert plan.generation == "v1"
        assert plan.username == snmp_username(device_id, plan.generation)
        assert plan.security_level == "authPriv"
        assert plan.view_name == "NCDP_IFMIB"
        assert plan.group_name == "NCDP_SNMP_RO"
        assert plan.authentication_protocol == "SHA256"
        assert plan.privacy_protocol == "AES128"
        assert frozenset(plan.device_view_oids) == APPROVED_DEVICE_VIEW_OIDS
        assert plan.oid_closure_digest == oid_closure_digest(plan.device_view_oids)
        assert plan.connection_credential_reference == (
            f"openbao:kv-v2:ncdp/devices/{device_id}/ssh"
        )
        assert plan.snmp_credential.reference == (
            f"snmpv3:netbox:dcim.device:{device_id}:generation:v1"
        )
        assert plan.snmp_credential.auth_selector == f"device_{device_id}_v1"
        assert plan.preconditions.safe_to_create_for(plan.platform)
        assert plan.preconditions.view == "ABSENT"
        assert plan.preconditions.group == "ABSENT"
        assert plan.preconditions.user == "ABSENT"


def test_sanitized_baseline_contains_exact_plan_precondition() -> None:
    plan = live_plan()
    if isinstance(plan, SnmpProvisioningPlan):
        return
    core = (BASELINE / "configs/core-02.cfg").read_text(encoding="utf-8")
    assert plan.current_description is None
    interface_block = core.split(f"interface {plan.interface}\n", 1)[1].split(
        "interface ", 1
    )[0]
    assert " description " not in interface_block
    assert plan.desired_description not in core


def test_committed_plan_assurance_and_promotion_verify(tmp_path: Path) -> None:
    plan = live_plan()
    assurance_policy = policy()
    record = assure_plan(
        plan, assurance_policy, BASELINE, PassingProvider(assurance_policy)
    )
    assert record.outcome is AssuranceOutcome.PASSED
    assurance = tmp_path / "assurance.json"
    assurance.write_text(record.model_dump_json(), encoding="utf-8")
    bundle = tmp_path / "promotion"
    manifest = create_promotion_bundle(
        PLAN, POLICY, BASELINE, assurance, "a" * 40, bundle
    )
    verified = verify_promotion_bundle(bundle, "a" * 40)
    assert verified.digest == manifest.digest
    assert manifest.plan_digest == plan.digest
    promoted = load_plan(bundle / "plan.json")
    assert type(promoted) is type(plan)
    assert promoted.digest == plan.digest


def test_live_promotion_inputs_are_secret_free(tmp_path: Path) -> None:
    _assert_live_input_secret_free(INPUTS)
    positive = tmp_path / "username.json"
    positive.write_text('{"username":"ncdp_snmp_d1_v1"}', encoding="utf-8")
    _assert_live_input_secret_free(tmp_path)
    for field in ("authentication_secret", "privacy_secret", "password"):
        fixture = tmp_path / f"{field}.json"
        fixture.write_text(f'{{"{field}":"sentinel"}}', encoding="utf-8")
        assert _forbidden_live_input_secret(fixture.read_text()) is not None
