"""Temporary contract tests for the JUNOS-001 diagnostic rehearsal commit."""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

from network_change_delivery.snmp_credentials import validate_snmp_secret
from network_change_delivery.snmp_provisioning import SnmpProvisioningPlan

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))

from scripts.run_junos_snmp_rehearsal import (  # noqa: E402
    LIVE_HOST,
    STAGING_HOST,
    JunosSnmpRehearsalEvidence,
    SyntheticSnmpCredentialSource,
    _project_plan,
)


def source_plan() -> SnmpProvisioningPlan:
    return SnmpProvisioningPlan.model_validate_json(
        (ROOT / "deployments/live/promotion/plan.json").read_text(encoding="utf-8")
    )


def test_projection_changes_only_endpoint_and_digest() -> None:
    source = source_plan()
    projected = _project_plan(source)
    assert source.host == LIVE_HOST
    assert projected.host == STAGING_HOST
    assert projected.digest != source.digest
    assert projected.verify_digest()
    source_values = source.model_dump(mode="json", exclude={"digest", "host"})
    projected_values = projected.model_dump(mode="json", exclude={"digest", "host"})
    assert projected_values == source_values


def test_synthetic_credentials_are_one_use_distinct_and_discarded(monkeypatch) -> None:
    values = iter(("A" * 48, "B" * 48))
    monkeypatch.setattr(
        SyntheticSnmpCredentialSource,
        "_secret",
        staticmethod(lambda: next(values)),
    )
    source = SyntheticSnmpCredentialSource()
    credentials = source.load()
    assert credentials.username == "ncdp_snmp_d2_v1"
    assert validate_snmp_secret(credentials.authentication_secret)
    assert validate_snmp_secret(credentials.privacy_secret)
    assert credentials.authentication_secret != credentials.privacy_secret
    source.discard()
    assert source.discarded is True


def test_rehearsal_evidence_allowlist_contains_no_secret_or_engine_value() -> None:
    evidence = JunosSnmpRehearsalEvidence(
        schema_version="1", staging_run_id="bk-123"
    ).safe_dict()
    serialized = repr(evidence)
    for forbidden in (
        "authentication_secret",
        "privacy_secret",
        "engine_id",
        "candidate_xml",
        "ssh_password",
    ):
        assert forbidden not in serialized
    assert evidence["production_audit_persisted"] is False


def test_temporary_pipeline_is_staging_only_and_nonretryable() -> None:
    pipeline_path = ROOT / ".buildkite/pipeline.yml"
    content = pipeline_path.read_text(encoding="utf-8")
    pipeline = yaml.safe_load(content)
    steps = pipeline["steps"]
    assert [step["key"] for step in steps] == [
        "rehearsal-contract",
        "rehearsal-promotion",
        "junos-rehearsal-approval",
        "cml-staging",
    ]
    assert steps[0]["agents"]["queue"] == "ncdp-validation"
    assert steps[1]["agents"]["queue"] == "ncdp-validation"
    assert steps[3]["agents"]["queue"] == "ncdp-staging"
    assert steps[3]["command"] == "scripts/buildkite/ephemeral_staging.sh"
    for step in (steps[0], steps[1], steps[3]):
        assert step["retry"]["automatic"] is False
        assert step["retry"]["manual"]["allowed"] is False
    assert "ncdp-deploy" not in content
    assert "deploy-gate" not in content
    assert "urn:ncdp:openbao:deploy" not in content


def test_rehearsal_shell_uses_only_staging_oidc_and_production_workflow() -> None:
    shell = (ROOT / "scripts/buildkite/ephemeral_staging.sh").read_text()
    driver = (ROOT / "scripts/run_junos_snmp_rehearsal.py").read_text()
    assert "--audience urn:ncdp:openbao:staging" in shell
    assert "urn:ncdp:openbao:deploy" not in shell
    assert "scripts.run_junos_snmp_rehearsal" in shell
    assert "deploy_snmp_provisioning_plan(" in driver
    assert "MultiVendorAdapter(" in driver
    assert "production_audit_persisted: bool = False" in driver
