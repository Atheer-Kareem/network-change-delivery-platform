#!/usr/bin/env python3
"""Temporary: run one PR-bound Junos SNMP rehearsal in disposable CML."""

from __future__ import annotations

import argparse
import json
import os
import secrets as runtime_secrets
import sys
from dataclasses import dataclass
from pathlib import Path

from network_change_delivery.ansible_adapter import verify_existing_host_trust
from network_change_delivery.buildkite_deployment import (
    load_live_deployment_request_at_commit,
)
from network_change_delivery.buildkite_identity import read_buildkite_oidc_jwt
from network_change_delivery.buildkite_staging import (
    BuildkiteStagingContext,
    staging_context_from_environment,
    validate_staging_state_root,
)
from network_change_delivery.ephemeral_staging import (
    StagingError,
    StagingEvidence,
    run_staging_lifecycle,
    validate_run_directory,
)
from network_change_delivery.promotion import verify_promotion_bundle
from network_change_delivery.snmp_credentials import (
    SNMP_SECRET_ALPHABET,
    SNMP_SECRET_LENGTH,
    SnmpProvisioningCredentials,
)
from network_change_delivery.snmp_mib import APPROVED_DEVICE_VIEW_OIDS
from network_change_delivery.snmp_provisioning import (
    NCDP_SNMP_GROUP,
    NCDP_SNMP_VIEW,
    SnmpOwnedStateDisposition,
    SnmpProvisioningOutcome,
    SnmpProvisioningPlan,
)
from network_change_delivery.snmp_provisioning_workflow import (
    deploy_snmp_provisioning_plan,
)
from network_change_delivery.vendor_adapter import MultiVendorAdapter
from scripts.run_ephemeral_cml_staging import ROOT, LocalOperations

LIVE_HOST = "192.168.4.20"
STAGING_HOST = "192.168.4.40"
STAGING_ENDPOINT = f"{STAGING_HOST}:830"
EXPECTED_CHANGE_ID = "CHG-SNMP-11C3-JUNOS-001"
EXPECTED_DEVICE = "netbox:dcim.device:2"
EXPECTED_USERNAME = "ncdp_snmp_d2_v1"
EXPECTED_SSH_REFERENCE = "openbao:kv-v2:ncdp/devices/2/ssh"
EXPECTED_SNMP_REFERENCE = "snmpv3:netbox:dcim.device:2:generation:v1"


@dataclass
class JunosSnmpRehearsalEvidence(StagingEvidence):
    """Explicit non-secret extension of the accepted staging evidence."""

    source_change_id: str | None = None
    source_live_plan_digest: str | None = None
    assurance_digest: str | None = None
    promotion_digest: str | None = None
    projected_rehearsal_digest: str | None = None
    projection_difference: str | None = None
    staging_endpoint: str | None = None
    strict_netconf_trust: str = "not_attempted"
    snmp_preflight: str = "not_attempted"
    snmp_execution: str = "not_attempted"
    snmp_post_validation: str = "not_attempted"
    snmp_confirmation: str = "not_attempted"
    snmp_final_outcome: str = "not_attempted"
    snmp_record_schema_version: str | None = None
    commit_confirmed_attempts: int = 0
    confirmation_attempts: int = 0
    synthetic_credentials_discarded: bool = False
    production_audit_persisted: bool = False


class SyntheticSnmpCredentialSource:
    """Generate one run-only credential only after the prewrite gate."""

    def __init__(self) -> None:
        self.load_count = 0
        self.discarded = False

    @staticmethod
    def _secret() -> str:
        return "".join(
            runtime_secrets.choice(SNMP_SECRET_ALPHABET)
            for _ in range(SNMP_SECRET_LENGTH)
        )

    def load(self) -> SnmpProvisioningCredentials:
        if self.load_count or self.discarded:
            raise StagingError("synthetic SNMP credential already consumed")
        self.load_count = 1
        authentication = self._secret()
        privacy = self._secret()
        while privacy == authentication:
            privacy = self._secret()
        return SnmpProvisioningCredentials(
            EXPECTED_USERNAME,
            authentication,
            privacy,
        )

    def discard(self) -> None:
        self.discarded = True


def _load_source_plan(
    promotion: Path,
    context: BuildkiteStagingContext,
    *,
    promoted_plan_digest: str,
    promoted_assurance_digest: str,
    promoted_promotion_digest: str,
) -> SnmpProvisioningPlan:
    manifest = verify_promotion_bundle(promotion, context.commit)
    if (
        manifest.plan_digest != promoted_plan_digest
        or manifest.assurance_record_digest != promoted_assurance_digest
        or manifest.digest != promoted_promotion_digest
    ):
        raise StagingError("rehearsal promotion metadata binding failed")
    try:
        plan = SnmpProvisioningPlan.model_validate_json(
            (promotion / "plan.json").read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        raise StagingError("rehearsal source plan rejected") from None
    request = load_live_deployment_request_at_commit(context.commit, root=ROOT)
    if request is None:
        raise StagingError("rehearsal source request is not commit-bound")
    request.verify_plan(plan)
    if (
        not plan.verify_digest()
        or plan.digest != manifest.plan_digest
        or plan.change_id != EXPECTED_CHANGE_ID
        or plan.target != "edge-junos-01"
        or plan.inventory_object_id != EXPECTED_DEVICE
        or plan.host != LIVE_HOST
        or plan.port != 830
        or plan.platform != "junos"
        or plan.expected_hostname != "edge-junos-01"
        or plan.connection_credential_reference != EXPECTED_SSH_REFERENCE
        or plan.snmp_credential.device != EXPECTED_DEVICE
        or plan.snmp_credential.reference != EXPECTED_SNMP_REFERENCE
        or plan.snmp_credential.auth_selector != "device_2_v1"
        or plan.generation != "v1"
        or plan.username != EXPECTED_USERNAME
        or plan.security_level != "authPriv"
        or plan.authentication_protocol != "SHA256"
        or plan.privacy_protocol != "AES128"
        or plan.view_name != NCDP_SNMP_VIEW
        or plan.group_name != NCDP_SNMP_GROUP
        or tuple(plan.device_view_oids) != tuple(sorted(APPROVED_DEVICE_VIEW_OIDS))
        or plan.transaction_strategy != "junos_commit_confirmed"
        or plan.confirmed_timeout_minutes != 5
        or not plan.preconditions.local_engine_id_present
        or plan.preconditions.view is not SnmpOwnedStateDisposition.ABSENT
        or plan.preconditions.group is not SnmpOwnedStateDisposition.ABSENT
        or plan.preconditions.user is not SnmpOwnedStateDisposition.ABSENT
        or plan.preconditions.foreign_objects_present
        or not plan.preconditions.safe_to_create_for("junos")
    ):
        raise StagingError("rehearsal source plan contract rejected")
    return plan


def _project_plan(source: SnmpProvisioningPlan) -> SnmpProvisioningPlan:
    unsigned = source.model_copy(
        update={"host": STAGING_HOST, "digest": "sha256:" + "0" * 64}
    )
    projected = SnmpProvisioningPlan.model_validate(
        unsigned.model_dump(mode="json") | {"digest": unsigned.calculated_digest()}
    )
    source_values = source.model_dump(mode="json", exclude={"digest"})
    projected_values = projected.model_dump(mode="json", exclude={"digest"})
    differences = {
        key for key in source_values if source_values[key] != projected_values[key]
    }
    if differences != {"host"} or projected.host != STAGING_HOST:
        raise StagingError("rehearsal plan projection exceeded endpoint authority")
    return projected


class JunosSnmpRehearsalOperations(LocalOperations):
    """Replace generic read-only validation with the production SNMP workflow."""

    def __init__(
        self,
        run_id: str,
        run_directory: Path,
        *,
        context: BuildkiteStagingContext,
        buildkite_jwt,
        promotion: Path,
        promoted_plan_digest: str,
        promoted_assurance_digest: str,
        promoted_promotion_digest: str,
    ) -> None:
        super().__init__(
            run_id,
            run_directory,
            buildkite_context=context,
            buildkite_jwt=buildkite_jwt,
        )
        self._context = context
        self._promotion = promotion
        self._promoted_plan_digest = promoted_plan_digest
        self._promoted_assurance_digest = promoted_assurance_digest
        self._promoted_promotion_digest = promoted_promotion_digest
        self._source_plan = _load_source_plan(
            promotion,
            context,
            promoted_plan_digest=promoted_plan_digest,
            promoted_assurance_digest=promoted_assurance_digest,
            promoted_promotion_digest=promoted_promotion_digest,
        )
        self._projected_plan = _project_plan(self._source_plan)

    @property
    def source_plan(self) -> SnmpProvisioningPlan:
        return self._source_plan

    @property
    def projected_plan(self) -> SnmpProvisioningPlan:
        return self._projected_plan

    def _prewrite_gate(self) -> None:
        if getattr(self, "_prewrite_consumed", False):
            raise StagingError("rehearsal prewrite gate already consumed")
        current = _load_source_plan(
            self._promotion,
            self._context,
            promoted_plan_digest=self._promoted_plan_digest,
            promoted_assurance_digest=self._promoted_assurance_digest,
            promoted_promotion_digest=self._promoted_promotion_digest,
        )
        projected = _project_plan(current)
        if (
            current.digest != self._source_plan.digest
            or projected.digest != self._projected_plan.digest
        ):
            raise StagingError("rehearsal prewrite plan binding changed")
        self._prewrite_consumed = True

    def validate(self, evidence: StagingEvidence) -> None:
        if not isinstance(evidence, JunosSnmpRehearsalEvidence):
            raise StagingError("rehearsal evidence contract rejected")
        device = self._devices.get("edge_junos_01")
        credentials = self._credentials.get("edge-junos-01")
        if device is None or credentials is None:
            raise StagingError("staging Junos authority was not resolved")
        if (
            device.host != STAGING_HOST
            or device.port != 830
            or self._projected_plan.host != STAGING_HOST
            or self._source_plan.host != LIVE_HOST
        ):
            raise StagingError("rehearsal endpoint binding rejected")
        evidence.readiness_seconds["edge_junos_01"] = self._wait_device(device.host)
        evidence.readiness_checks["edge_junos_01"] = {
            "arp": "passed",
            "icmp": "passed",
            "tcp22": "passed",
            "tcp830": "passed",
        }
        evidence.readiness_outcome = "passed"
        self._establish_host_trust(device.host, (22, 830))
        verify_existing_host_trust(device, self._known_hosts)
        evidence.strict_netconf_trust = "passed"
        adapter = MultiVendorAdapter(known_hosts=self._known_hosts)
        source = SyntheticSnmpCredentialSource()
        record = None
        try:
            record = deploy_snmp_provisioning_plan(
                self._projected_plan,
                self._projected_plan.digest,
                device,
                credentials,
                source,
                adapter,
                self._prewrite_gate,
            )
        finally:
            source.discard()
            evidence.synthetic_credentials_discarded = source.discarded
        if record is None:
            raise StagingError("Junos SNMP rehearsal produced no typed record")
        evidence.snmp_record_schema_version = record.schema_version
        evidence.snmp_preflight = (
            record.preflight.disposition.value
            if record.preflight.disposition is not None
            else ("SUCCEEDED" if record.preflight.succeeded else "FAILED")
        )
        evidence.commit_confirmed_attempts = int(record.execution.attempted)
        if record.execution.succeeded:
            evidence.snmp_execution = "SUCCEEDED"
        elif record.final_outcome is SnmpProvisioningOutcome.AMBIGUOUS:
            evidence.snmp_execution = "AMBIGUOUS"
        elif record.execution.attempted:
            evidence.snmp_execution = "FAILED"
        if record.post_validation.succeeded:
            evidence.snmp_post_validation = "EXACT_NCDP_STATE"
        elif record.post_validation.attempted:
            evidence.snmp_post_validation = "FAILED"
        confirmation_outcomes = {
            SnmpProvisioningOutcome.SUCCEEDED: "SUCCEEDED",
            SnmpProvisioningOutcome.CONFIRMATION_FAILED: "FAILED",
            SnmpProvisioningOutcome.CONFIRMATION_AMBIGUOUS: "AMBIGUOUS",
        }
        evidence.snmp_confirmation = confirmation_outcomes.get(
            record.final_outcome, "not_attempted"
        )
        evidence.confirmation_attempts = int(
            record.final_outcome in confirmation_outcomes
        )
        evidence.snmp_final_outcome = record.final_outcome.value
        evidence.ncdp_validation_outcome = (
            "passed"
            if record.final_outcome is SnmpProvisioningOutcome.SUCCEEDED
            else "failed"
        )
        if record.final_outcome is not SnmpProvisioningOutcome.SUCCEEDED:
            raise StagingError(
                f"Junos SNMP rehearsal outcome was {record.final_outcome.value}"
            )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-directory", required=True, type=Path)
    parser.add_argument("--promotion", required=True, type=Path)
    parser.add_argument("--promoted-plan-digest", required=True)
    parser.add_argument("--promoted-assurance-digest", required=True)
    parser.add_argument("--promoted-promotion-digest", required=True)
    parser.add_argument("--evidence", required=True, type=Path)
    return parser.parse_args()


def _write_evidence(path: Path, evidence: JunosSnmpRehearsalEvidence) -> None:
    payload = json.dumps(evidence.safe_dict(), indent=2, sort_keys=True) + "\n"
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        data = payload.encode()
        offset = 0
        while offset < len(data):
            written = os.write(descriptor, data[offset:])
            if written <= 0:
                raise OSError("rehearsal evidence write made no progress")
            offset += written
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    print(payload, end="")


def main() -> int:
    os.umask(0o077)
    args = parse_args()
    context = staging_context_from_environment()
    evidence = JunosSnmpRehearsalEvidence(
        schema_version="1",
        staging_run_id=args.run_id,
        orchestrator="buildkite",
        pipeline_id=context.pipeline_id,
        build_id=context.build_id,
        build_commit=context.commit,
        build_branch=context.branch,
        step_key=context.step_key,
        job_id=context.job_id,
        source_change_id=EXPECTED_CHANGE_ID,
        source_live_plan_digest=args.promoted_plan_digest,
        assurance_digest=args.promoted_assurance_digest,
        promotion_digest=args.promoted_promotion_digest,
        projection_difference=f"host:{LIVE_HOST}->{STAGING_HOST}",
        staging_endpoint=STAGING_ENDPOINT,
    )
    operations = None
    try:
        if args.run_id != context.staging_run_id:
            raise StagingError("Buildkite rehearsal run identity mismatch")
        state_root_value = os.environ.get("NCDP_STAGING_STATE_ROOT", "")
        if not state_root_value:
            raise StagingError("Buildkite staging state root is missing")
        state_root = validate_staging_state_root(Path(state_root_value), ROOT)
        expected_run_directory = state_root / "ephemeral" / context.staging_run_id
        if args.run_directory.resolve() != expected_run_directory:
            raise StagingError("Buildkite rehearsal run directory mismatch")
        validate_run_directory(args.run_id, args.run_directory)
        jwt = read_buildkite_oidc_jwt(sys.stdin)
        operations = JunosSnmpRehearsalOperations(
            args.run_id,
            args.run_directory,
            context=context,
            buildkite_jwt=jwt,
            promotion=args.promotion,
            promoted_plan_digest=args.promoted_plan_digest,
            promoted_assurance_digest=args.promoted_assurance_digest,
            promoted_promotion_digest=args.promoted_promotion_digest,
        )
        evidence.projected_rehearsal_digest = operations.projected_plan.digest
        evidence = run_staging_lifecycle(
            args.run_id,
            args.run_directory,
            operations,
            evidence=evidence,
        )
    except Exception as error:
        evidence.primary_failure = str(error)
        evidence.overall_result = "failed"
    finally:
        if (
            operations is not None
            and args.run_directory.exists()
            and not operations.managed_resources_exist
            and evidence.state_retirement_outcome != "passed"
        ):
            try:
                operations.verify_absent(evidence)
                evidence.absence_verification_outcome = "passed"
                if evidence.destroy_outcome == "not_attempted":
                    evidence.destroy_outcome = "not_required"
                operations.retire_state(evidence)
                evidence.state_retirement_outcome = "passed"
            except Exception as error:
                evidence.cleanup_failure = str(error)
                evidence.overall_result = "failed"
    _write_evidence(args.evidence, evidence)
    return (
        0
        if evidence.overall_result == "passed"
        and evidence.snmp_final_outcome == SnmpProvisioningOutcome.SUCCEEDED.value
        and evidence.destroy_outcome == "passed"
        and evidence.absence_verification_outcome == "passed"
        and evidence.state_retirement_outcome == "passed"
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
