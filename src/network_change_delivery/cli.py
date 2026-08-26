"""Command-line interface for the platform shell."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from collections.abc import Sequence
from datetime import UTC, datetime
from importlib.metadata import version
from io import TextIOWrapper
from pathlib import Path
from uuid import UUID

import yaml
from pydantic import ValidationError

from network_change_delivery.ansible_adapter import (
    ProviderError,
    verify_deployment_ansible_runtime,
)
from network_change_delivery.assurance import (
    AssuranceEvidence,
    AssuranceOutcome,
    AssuranceProviderError,
    BatfishAssuranceAdapter,
    BatfishAssuranceIntent,
    InvariantResult,
    evaluate_assurance,
    prepare_snapshot,
)
from network_change_delivery.audit_store import MAX_AUDIT_RECORD_SCAN, AuditStore
from network_change_delivery.buildkite_audit import (
    persist_buildkite_audit,
    verify_buildkite_audit_inputs,
)
from network_change_delivery.buildkite_deployment import (
    BuildkiteOpenBaoDeploymentSecretProvider,
    load_live_deployment_request_at_commit,
    load_promoted_single_plan,
)
from network_change_delivery.buildkite_identity import (
    OpenBaoBuildkiteJWTAuthenticator,
    read_buildkite_oidc_jwt,
)
from network_change_delivery.buildkite_policy import (
    buildkite_deployment_context_from_environment,
    compare_promoted_digests,
)
from network_change_delivery.fleet import FleetSafetyError, deploy_fleet, plan_fleet
from network_change_delivery.inventory import (
    InventoryError,
    LocalYamlInventoryProvider,
    NetBoxInventoryProvider,
)
from network_change_delivery.models import (
    DeploymentPlan,
    FinalOutcome,
    FleetDeploymentPlan,
    FleetFinalOutcome,
    FleetInterfaceDescriptionIntent,
    FleetMemberClassification,
    InterfaceDescriptionIntent,
)
from network_change_delivery.plan_assurance import (
    BatfishAssurancePolicy,
    PlanAssuranceError,
    PlanAssuranceRecord,
    assure_prepared_plan,
    load_plan,
    verify_plan_assurance,
)
from network_change_delivery.promotion import (
    PromotionError,
    create_promotion_bundle,
    promotion_summary,
    verify_promotion_bundle,
)
from network_change_delivery.secrets import (
    EnvironmentSecretProvider,
    OpenBaoSecretProvider,
    SecretError,
)
from network_change_delivery.vendor_adapter import MultiVendorAdapter
from network_change_delivery.workflow import SafetyError, deploy_plan, plan_change

MAX_AUDIT_FIND_RESULTS = 100


def _audit_change_id(value: str) -> str:
    if not 1 <= len(value) <= 255 or re.search(r"[\x00-\x1f\x7f]", value):
        raise argparse.ArgumentTypeError("audit change ID is invalid")
    return value


def _audit_commit(value: str) -> str:
    if re.fullmatch(r"[0-9a-f]{40}", value) is None:
        raise argparse.ArgumentTypeError("audit commit is invalid")
    return value


def _audit_device_id(value: str) -> str:
    if re.fullmatch(r"netbox:dcim\.device:[1-9][0-9]*", value) is None:
        raise argparse.ArgumentTypeError("audit device identity is invalid")
    return value


def _write_json(path: Path, value: str) -> None:
    """Write a local artifact atomically enough with restrictive permissions."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")
    path.chmod(0o600)


def _require_unused_fleet_plan_path(path: Path) -> None:
    """Fail before provider construction for files and even broken symlinks."""
    if path.exists() or path.is_symlink():
        raise OSError("fleet plan output already exists")


def _write_new_fleet_plan(path: Path, value: str) -> None:
    """Create one new mode-0600 fleet artifact without an overwrite race."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(value)
    path.chmod(0o600)


def _reserve_fleet_evidence(path: Path) -> TextIOWrapper:
    """Exclusively reserve the final evidence inode before any device operation."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    return os.fdopen(descriptor, "w", encoding="utf-8")


def _load_change(path: Path) -> InterfaceDescriptionIntent:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    return InterfaceDescriptionIntent.model_validate(payload)


def _load_plan(path: Path) -> DeploymentPlan:
    return DeploymentPlan.model_validate_json(path.read_text(encoding="utf-8"))


def _load_fleet_change(path: Path) -> FleetInterfaceDescriptionIntent:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    return FleetInterfaceDescriptionIntent.model_validate(payload)


def _load_fleet_plan(path: Path) -> FleetDeploymentPlan:
    return FleetDeploymentPlan.model_validate_json(path.read_text(encoding="utf-8"))


def _reserve_assurance_evidence(path: Path) -> TextIOWrapper:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    return os.fdopen(descriptor, "w", encoding="utf-8")


def _load_assurance_intent(path: Path) -> BatfishAssuranceIntent:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    return BatfishAssuranceIntent.model_validate(payload)


def _blocked_assurance_evidence(
    intent: BatfishAssuranceIntent,
    baseline_digest: str,
    candidate_digest: str,
    message: str,
) -> AssuranceEvidence:
    return AssuranceEvidence(
        generated_at=datetime.now(UTC),
        subject_digest=intent.subject_digest,
        pybatfish_version="unknown",
        baseline_snapshot_digest=baseline_digest,
        candidate_snapshot_digest=candidate_digest,
        expected_nodes=tuple(sorted(intent.expected_nodes)),
        baseline_parse=None,
        candidate_parse=None,
        critical_flows=(),
        invariants=(InvariantResult(name="provider", passed=False, detail=message),),
        failure_reason=message,
        outcome=AssuranceOutcome.BLOCKED,
    )


def _run_assure(arguments: argparse.Namespace) -> int:
    # Input errors are reported without reserving an evidence artifact.
    intent = _load_assurance_intent(arguments.intent)
    with (
        prepare_snapshot(arguments.baseline) as prepared_baseline,
        prepare_snapshot(arguments.candidate) as prepared_candidate,
    ):
        baseline = prepared_baseline.manifest
        candidate = prepared_candidate.manifest
        with _reserve_assurance_evidence(arguments.report_json) as evidence:
            try:
                observation = BatfishAssuranceAdapter().analyze(
                    prepared_baseline.root, prepared_candidate.root, intent
                )
                result = evaluate_assurance(intent, baseline, candidate, observation)
            except (OSError, ValueError, AssuranceProviderError) as error:
                result = _blocked_assurance_evidence(
                    intent, baseline.digest, candidate.digest, str(error)
                )
            evidence.write(result.model_dump_json(indent=2) + "\n")
            evidence.flush()
            os.fsync(evidence.fileno())
    print(f"Subject digest: {result.subject_digest}")
    print(f"Baseline snapshot digest: {result.baseline_snapshot_digest}")
    print(f"Candidate snapshot digest: {result.candidate_snapshot_digest}")
    parsed_nodes = len(result.candidate_parse.nodes) if result.candidate_parse else 0
    print(f"Parsed node count: {parsed_nodes}")
    issue_count = sum(
        summary.initialization_issue_count
        for summary in (result.baseline_parse, result.candidate_parse)
        if summary is not None
    )
    print(f"Initialization issues: {issue_count}")
    print(f"Critical flows: {len(result.critical_flows)}")
    print(f"Differential changed-flow count: {result.differential_changed_flow_count}")
    print(f"Final assurance outcome: {result.outcome}")
    print(f"Evidence: {arguments.report_json}")
    return 0 if result.outcome is AssuranceOutcome.PASSED else 2


def _load_policy(path: Path) -> BatfishAssurancePolicy:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    return BatfishAssurancePolicy.model_validate(payload)


def _run_assure_plan(arguments: argparse.Namespace) -> int:
    plan = load_plan(arguments.plan)
    policy = _load_policy(arguments.policy)
    if arguments.report_json.exists() or arguments.report_json.is_symlink():
        raise OSError("assurance evidence path already exists")
    with (
        prepare_snapshot(arguments.baseline) as prepared_baseline,
        _reserve_assurance_evidence(arguments.report_json) as evidence,
    ):
        record = assure_prepared_plan(plan, policy, prepared_baseline)
        evidence.write(record.model_dump_json(indent=2) + "\n")
        evidence.flush()
        os.fsync(evidence.fileno())
    print(f"Plan digest: {record.subject.plan_digest}")
    print(f"Policy digest: {record.policy_digest}")
    print(f"Baseline snapshot digest: {record.baseline_snapshot_digest}")
    print(f"Candidate snapshot digest: {record.candidate_snapshot_digest}")
    print(f"Final assurance outcome: {record.outcome}")
    print(f"Evidence: {arguments.report_json}")
    return 0 if record.outcome is AssuranceOutcome.PASSED else 2


def _run_verify_assurance(arguments: argparse.Namespace) -> int:
    plan = load_plan(arguments.plan)
    policy = _load_policy(arguments.policy)
    record = PlanAssuranceRecord.model_validate_json(
        arguments.evidence.read_text(encoding="utf-8")
    )
    verified = verify_plan_assurance(plan, policy, arguments.baseline, record)
    print(f"Plan assurance verified: {verified}")
    return 0 if verified else 2


def _run_promote(arguments: argparse.Namespace) -> int:
    manifest = create_promotion_bundle(
        arguments.plan,
        arguments.policy,
        arguments.baseline,
        arguments.assurance,
        arguments.git_commit,
        arguments.output,
    )
    print(f"Promotion digest: {manifest.digest}")
    return 0


def _run_verify_promotion(arguments: argparse.Namespace) -> int:
    manifest = verify_promotion_bundle(arguments.promotion, arguments.git_commit)
    print(promotion_summary(manifest))
    return 0


def _run_promotion_digest(arguments: argparse.Namespace) -> int:
    manifest = verify_promotion_bundle(arguments.promotion, arguments.git_commit)
    values = {
        "plan": manifest.plan_digest,
        "assurance": manifest.assurance_record_digest,
        "promotion": manifest.digest,
    }
    print(values[arguments.field])
    return 0


def _run_verify_buildkite_gate(arguments: argparse.Namespace) -> int:
    context = buildkite_deployment_context_from_environment(os.environ)
    manifest = verify_promotion_bundle(arguments.promotion, context.commit)
    compare_promoted_digests(
        manifest.plan_digest,
        manifest.assurance_record_digest,
        manifest.digest,
        promoted_plan=arguments.promoted_plan_digest,
        promoted_assurance=arguments.promoted_assurance_digest,
        promoted_promotion=arguments.promoted_promotion_digest,
    )
    print(f"commit: {context.commit}")
    print(f"plan digest: {manifest.plan_digest}")
    print(f"assurance digest: {manifest.assurance_record_digest}")
    print(f"promotion digest: {manifest.digest}")
    print("deployment authorization gate: PASSED")
    return 0


def _verified_live_request(promotion: Path, context):
    request = load_live_deployment_request_at_commit(context.commit)
    if request is None:
        raise PromotionError("live deployment request was not changed by this commit")
    manifest, plan = load_promoted_single_plan(promotion, context.commit)
    request.verify_plan(plan)
    return manifest, plan, request


def _run_verify_buildkite_live_request(arguments: argparse.Namespace) -> int:
    context = buildkite_deployment_context_from_environment(os.environ)
    _manifest, plan, request = _verified_live_request(arguments.promotion, context)
    print("live deployment requested: YES")
    print(f"change: {request.change_id}")
    print(f"plan digest: {plan.digest}")
    print(f"inventory identity: {request.inventory_object_id}")
    return 0


def _run_buildkite_live_request_status(arguments: argparse.Namespace) -> int:
    del arguments
    context = buildkite_deployment_context_from_environment(os.environ)
    if load_live_deployment_request_at_commit(context.commit) is None:
        print("live deployment requested: NO")
        print("device write executed: NO")
        return 3
    print("commit-bound live deployment request changed: YES")
    return 0


def _run_verify_deployment_ansible_runtime(arguments: argparse.Namespace) -> int:
    del arguments
    verified = verify_deployment_ansible_runtime()
    print(
        "Deployment Ansible runtime verified: "
        + ", ".join(f"{name}={version}" for name, version in verified)
    )
    return 0


def _run_deploy_buildkite_promotion(arguments: argparse.Namespace) -> int:
    import sys

    context = buildkite_deployment_context_from_environment(os.environ)
    _manifest, plan, _request = _verified_live_request(arguments.promotion, context)
    if arguments.report_json.exists() or arguments.report_json.is_symlink():
        raise OSError("deployment evidence path already exists")
    jwt = read_buildkite_oidc_jwt(sys.stdin)
    inventory = NetBoxInventoryProvider()
    secrets = BuildkiteOpenBaoDeploymentSecretProvider(jwt, context)
    adapter = MultiVendorAdapter()
    record = deploy_plan(
        plan,
        plan.digest,
        inventory,
        secrets,
        adapter,
        adapter,
    )
    _write_new_fleet_plan(
        arguments.report_json, record.model_dump_json(indent=2) + "\n"
    )
    print(f"Final outcome: {record.final_outcome}")
    print(f"Evidence: {arguments.report_json}")
    return (
        0
        if record.final_outcome
        in {
            FinalOutcome.SUCCEEDED,
            FinalOutcome.RECOVERED,
        }
        else 2
    )


def _run_verify_buildkite_openbao_identity(arguments: argparse.Namespace) -> int:
    del arguments
    import sys

    context = buildkite_deployment_context_from_environment(os.environ)
    jwt = read_buildkite_oidc_jwt(sys.stdin)
    authenticator = OpenBaoBuildkiteJWTAuthenticator()
    if os.environ.get("NCDP_OPENBAO_JWT_DIAGNOSTICS") == "1":
        authenticator.diagnose(jwt, context, sys.stdout)
        return 0
    authentication = authenticator.authenticate(jwt, context)
    print(f"Buildkite OpenBao identity verified: pipeline={context.pipeline_id}")
    print(f"commit: {context.commit}")
    print(f"job: {context.job_id}")
    print(f"OpenBao token lease: {authentication.lease_duration} seconds")
    return 0


def _checkout_root() -> Path:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise ValueError("unable to establish repository checkout root") from error
    value = result.stdout.strip()
    root = Path(value)
    if not value or not root.is_absolute() or not root.is_dir():
        raise ValueError("unable to establish repository checkout root")
    return root


def _audit_store(arguments: argparse.Namespace) -> AuditStore:
    configured = arguments.store_root or os.environ.get("NCDP_AUDIT_STORE_ROOT")
    if not configured:
        raise ValueError("NCDP_AUDIT_STORE_ROOT is required")
    return AuditStore(Path(configured), checkout=_checkout_root())


def _run_audit_verify_store(arguments: argparse.Namespace) -> int:
    _audit_store(arguments)
    print("audit store: VERIFIED")
    return 0


def _run_audit_persist_buildkite(arguments: argparse.Namespace) -> int:
    context = buildkite_deployment_context_from_environment(os.environ)
    repository = os.environ.get("BUILDKITE_REPO", "")
    record_id, digest, outcome = persist_buildkite_audit(
        store=_audit_store(arguments),
        context=context,
        repository=repository,
        promotion=arguments.promotion,
        staging_evidence_path=arguments.staging_evidence,
        checkout=_checkout_root(),
        change_record_path=arguments.change_record,
    )
    print(f"audit record ID: {record_id}")
    print(f"audit record digest: {digest}")
    print(f"audit final outcome: {outcome}")
    return 0


def _run_audit_verify_buildkite(arguments: argparse.Namespace) -> int:
    context = buildkite_deployment_context_from_environment(os.environ)
    _audit_store(arguments)
    verify_buildkite_audit_inputs(
        context=context,
        repository=os.environ.get("BUILDKITE_REPO", ""),
        promotion=arguments.promotion,
        staging_evidence_path=arguments.staging_evidence,
    )
    print("Buildkite audit pre-write boundary: VERIFIED")
    return 0


def _run_audit_show(arguments: argparse.Namespace) -> int:
    record = _audit_store(arguments).read_record(arguments.record_id)
    print(json.dumps(record.model_dump(mode="json"), sort_keys=True, indent=2))
    return 0


def _run_audit_find(arguments: argparse.Namespace) -> int:
    store = _audit_store(arguments)
    records = store.iter_records(max_scan=MAX_AUDIT_RECORD_SCAN)
    if arguments.change_id is not None:
        matches = [
            record for record in records if record.change_id == arguments.change_id
        ]
    elif arguments.commit is not None:
        matches = [
            record for record in records if record.git.commit == arguments.commit
        ]
    elif arguments.build_id is not None:
        matches = [
            record
            for record in records
            if record.buildkite is not None
            and record.buildkite.build_id == arguments.build_id
        ]
    else:
        matches = [
            record
            for record in records
            if any(target.device == arguments.device_id for target in record.targets)
        ]
    matches.sort(key=lambda record: (record.generated_at, str(record.record_id)))
    if len(matches) > arguments.max_results:
        raise ValueError("audit query result bound exceeded")
    summaries = [
        {
            "record_id": str(record.record_id),
            "generated_at": record.generated_at.isoformat(),
            "change_id": record.change_id,
            "commit": record.git.commit,
            "build_id": (
                str(record.buildkite.build_id) if record.buildkite is not None else None
            ),
            "final_outcome": record.final_outcome,
            "device_ids": [target.device for target in record.targets],
        }
        for record in matches
    ]
    print(json.dumps(summaries, sort_keys=True, indent=2))
    return 0


def _inventory(arguments: argparse.Namespace):
    if arguments.netbox:
        return NetBoxInventoryProvider()
    return LocalYamlInventoryProvider(arguments.inventory)


def _secrets(arguments: argparse.Namespace):
    if arguments.openbao:
        return OpenBaoSecretProvider()
    return EnvironmentSecretProvider()


def _run_plan(arguments: argparse.Namespace) -> int:
    intent = _load_change(arguments.change)
    inventory = _inventory(arguments)
    secrets = _secrets(arguments)
    adapter = MultiVendorAdapter()
    result = plan_change(
        intent,
        inventory,
        secrets,
        adapter,
    )
    print(f"Credential source: {result.credential.source}")
    print(f"Credential reference: {result.credential.reference}")
    if result.plan is None:
        print(result.message)
        return 0
    _write_json(arguments.output, result.plan.model_dump_json(indent=2) + "\n")
    print(f"Target: {result.plan.target}")
    print(f"Observed hostname: {result.plan.preconditions.observed_hostname}")
    print(f"Interface: {result.plan.interface}")
    print(f"Current description: {result.plan.current_description!r}")
    print(f"Desired description: {result.plan.desired_description!r}")
    print("Execution artifact:")
    print(result.plan.execution_artifact.cli_preview())
    print(f"Transaction strategy: {result.plan.transaction_strategy}")
    if result.plan.confirmed_timeout_minutes is not None:
        print(
            f"Commit-confirmed timeout: {result.plan.confirmed_timeout_minutes} minutes"
        )
        print(f"Confirmation operation: {result.plan.confirmation_operation}")
    if result.plan.recovery_artifact is not None:
        print("Recovery artifact:")
        print(result.plan.recovery_artifact.cli_preview())
    print(f"Plan digest: {result.plan.digest}")
    return 0


def _run_deploy(arguments: argparse.Namespace) -> int:
    plan = _load_plan(arguments.plan)
    inventory = _inventory(arguments)
    secrets = _secrets(arguments)
    adapter = MultiVendorAdapter()
    record = deploy_plan(
        plan,
        arguments.approve_digest,
        inventory,
        secrets,
        adapter,
        adapter,
    )
    _write_json(arguments.report_json, record.model_dump_json(indent=2) + "\n")
    print(f"Final outcome: {record.final_outcome}")
    print(f"Evidence: {arguments.report_json}")
    return 0 if record.final_outcome.value in {"SUCCEEDED", "RECOVERED"} else 2


def _run_fleet_plan(arguments: argparse.Namespace) -> int:
    _require_unused_fleet_plan_path(arguments.plan_out)
    intent = _load_fleet_change(arguments.change)
    inventory = NetBoxInventoryProvider()
    secrets = OpenBaoSecretProvider()
    result = plan_fleet(intent, inventory, secrets, MultiVendorAdapter())
    deployable = sum(
        member.classification is FleetMemberClassification.DEPLOYABLE
        for member in result.members
    )
    compliant = len(result.members) - deployable
    platform_counts = {
        platform: sum(member.platform == platform for member in result.members)
        for platform in sorted({member.platform for member in result.members})
    }
    print(
        "Selector: "
        f"device_tag={intent.selector.device_tag}, "
        f"interface_tag={intent.selector.interface_tag}"
    )
    print(f"Selected members: {len(result.members)}")
    print(f"Deployable members: {deployable}")
    print(f"Compliant members: {compliant}")
    print(
        "Platform counts: "
        + ", ".join(
            f"{platform}={count}" for platform, count in platform_counts.items()
        )
    )
    if result.plan is None:
        print(result.message)
        return 0
    _write_new_fleet_plan(
        arguments.plan_out, result.plan.model_dump_json(indent=2) + "\n"
    )
    by_id = {
        member.inventory_object_id: member.target for member in result.plan.members
    }
    print(
        "Canaries: "
        + ", ".join(
            f"{identity} ({by_id[identity]})" for identity in result.plan.canaries
        )
    )
    for index, wave in enumerate(result.plan.waves, start=1):
        print(
            f"Wave {index}: "
            + ", ".join(f"{identity} ({by_id[identity]})" for identity in wave)
        )
    for member in result.plan.members:
        if member.child_plan is not None:
            print(f"Child plan {member.target}: {member.child_plan.digest}")
    print(f"Fleet plan digest: {result.plan.digest}")
    return 0


def _run_fleet_deploy(arguments: argparse.Namespace) -> int:
    with _reserve_fleet_evidence(arguments.report_json) as evidence:
        plan = _load_fleet_plan(arguments.plan)
        inventory = NetBoxInventoryProvider()
        secrets = OpenBaoSecretProvider()
        adapter = MultiVendorAdapter()
        record = deploy_fleet(
            plan,
            arguments.approve_digest,
            inventory,
            secrets,
            adapter,
            adapter,
        )
        evidence.write(record.model_dump_json(indent=2) + "\n")
        evidence.flush()
        os.fsync(evidence.fileno())
    attempted = sum(member.attempted for member in record.members)
    succeeded = sum(
        member.child_record is not None
        and member.child_record.final_outcome.value == "SUCCEEDED"
        for member in record.members
    )
    compliant = sum(
        member.classification is FleetMemberClassification.COMPLIANT
        for member in record.members
    )
    validation = (
        "not attempted"
        if not record.final_validation.attempted
        else "succeeded"
        if record.final_validation.succeeded
        else "failed"
    )
    print(f"Fleet digest: {record.fleet_plan_digest}")
    print(f"Final outcome: {record.final_outcome}")
    print(f"Full preflight: {'succeeded' if record.preflight.succeeded else 'failed'}")
    print(f"Attempted members: {attempted}")
    print(f"Succeeded members: {succeeded}")
    print(f"Compliant no-ops: {compliant}")
    if record.stop_member_identity is not None:
        stopped = next(
            member
            for member in record.members
            if member.inventory_object_id == record.stop_member_identity
        )
        print(f"Stopped at: {stopped.target} / {record.stop_child_outcome}")
    print(f"Final fleet validation: {validation}")
    print(f"Evidence: {arguments.report_json}")
    return 0 if record.final_outcome is FleetFinalOutcome.SUCCEEDED else 2


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    parser = argparse.ArgumentParser(
        prog="ncdp",
        description="Network Change Delivery Platform",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {version('network-change-delivery')}",
    )
    subparsers = parser.add_subparsers(dest="command")

    plan_parser = subparsers.add_parser(
        "plan",
        help="collect live state and create an immutable plan",
    )
    plan_parser.add_argument("--change", required=True, type=Path)
    plan_inventory = plan_parser.add_mutually_exclusive_group(required=True)
    plan_inventory.add_argument("--inventory", type=Path)
    plan_inventory.add_argument("--netbox", action="store_true")
    plan_secrets = plan_parser.add_mutually_exclusive_group(required=True)
    plan_secrets.add_argument("--openbao", action="store_true")
    plan_secrets.add_argument("--environment-secrets", action="store_true")
    plan_parser.add_argument("--output", required=True, type=Path)
    plan_parser.set_defaults(handler=_run_plan)

    fleet_plan_parser = subparsers.add_parser(
        "fleet-plan",
        help="resolve and read-only preflight one NetBox-selected fleet",
    )
    fleet_plan_parser.add_argument("--change", required=True, type=Path)
    fleet_plan_parser.add_argument("--plan-out", required=True, type=Path)
    fleet_plan_parser.add_argument("--netbox", required=True, action="store_true")
    fleet_plan_parser.add_argument("--openbao", required=True, action="store_true")
    fleet_plan_parser.set_defaults(handler=_run_fleet_plan)

    fleet_deploy_parser = subparsers.add_parser(
        "fleet-deploy",
        help="execute one explicitly digest-approved immutable fleet plan",
    )
    fleet_deploy_parser.add_argument("--plan", required=True, type=Path)
    fleet_deploy_parser.add_argument("--approve-digest", required=True)
    fleet_deploy_parser.add_argument("--netbox", required=True, action="store_true")
    fleet_deploy_parser.add_argument("--openbao", required=True, action="store_true")
    fleet_deploy_parser.add_argument("--report-json", required=True, type=Path)
    fleet_deploy_parser.set_defaults(handler=_run_fleet_deploy)

    assure_parser = subparsers.add_parser(
        "assure",
        help="run offline Batfish assurance over two snapshots",
    )
    assure_parser.add_argument("--intent", required=True, type=Path)
    assure_parser.add_argument("--baseline", required=True, type=Path)
    assure_parser.add_argument("--candidate", required=True, type=Path)
    assure_parser.add_argument("--report-json", required=True, type=Path)
    assure_parser.add_argument("--batfish", required=True, action="store_true")
    assure_parser.set_defaults(handler=_run_assure)

    assure_plan_parser = subparsers.add_parser(
        "assure-plan", help="run exact plan-bound offline Batfish assurance"
    )
    assure_plan_parser.add_argument("--plan", required=True, type=Path)
    assure_plan_parser.add_argument("--policy", required=True, type=Path)
    assure_plan_parser.add_argument("--baseline", required=True, type=Path)
    assure_plan_parser.add_argument("--report-json", required=True, type=Path)
    assure_plan_parser.add_argument("--batfish", required=True, action="store_true")
    assure_plan_parser.set_defaults(handler=_run_assure_plan)

    verify_parser = subparsers.add_parser(
        "verify-assurance", help="verify an exact plan-bound assurance record"
    )
    verify_parser.add_argument("--plan", required=True, type=Path)
    verify_parser.add_argument("--policy", required=True, type=Path)
    verify_parser.add_argument("--baseline", required=True, type=Path)
    verify_parser.add_argument("--evidence", required=True, type=Path)
    verify_parser.set_defaults(handler=_run_verify_assurance)

    promote_parser = subparsers.add_parser(
        "promote", help="create an offline immutable Buildkite promotion bundle"
    )
    promote_parser.add_argument("--plan", required=True, type=Path)
    promote_parser.add_argument("--policy", required=True, type=Path)
    promote_parser.add_argument("--baseline", required=True, type=Path)
    promote_parser.add_argument("--assurance", required=True, type=Path)
    promote_parser.add_argument("--git-commit", required=True)
    promote_parser.add_argument("--output", required=True, type=Path)
    promote_parser.set_defaults(handler=_run_promote)

    verify_promotion_parser = subparsers.add_parser(
        "verify-promotion", help="verify an offline promotion bundle"
    )
    verify_promotion_parser.add_argument("--promotion", required=True, type=Path)
    verify_promotion_parser.add_argument("--git-commit", required=True)
    verify_promotion_parser.set_defaults(handler=_run_verify_promotion)

    promotion_digest_parser = subparsers.add_parser(
        "promotion-digest",
        help="verify a promotion and print one machine-readable digest",
    )
    promotion_digest_parser.add_argument("--promotion", required=True, type=Path)
    promotion_digest_parser.add_argument("--git-commit", required=True)
    promotion_digest_parser.add_argument(
        "--field", required=True, choices=("plan", "assurance", "promotion")
    )
    promotion_digest_parser.set_defaults(handler=_run_promotion_digest)

    gate_parser = subparsers.add_parser(
        "verify-buildkite-gate", help="verify Buildkite deployment authorization"
    )
    gate_parser.add_argument("--promotion", required=True, type=Path)
    gate_parser.add_argument("--promoted-plan-digest", required=True)
    gate_parser.add_argument("--promoted-assurance-digest", required=True)
    gate_parser.add_argument("--promoted-promotion-digest", required=True)
    gate_parser.set_defaults(handler=_run_verify_buildkite_gate)

    live_request_parser = subparsers.add_parser(
        "verify-buildkite-live-request",
        help="verify one commit-bound promoted live deployment request",
    )
    live_request_parser.add_argument("--promotion", required=True, type=Path)
    live_request_parser.set_defaults(handler=_run_verify_buildkite_live_request)

    live_status_parser = subparsers.add_parser(
        "buildkite-live-request-status",
        help="check whether this commit changed the fixed live request",
    )
    live_status_parser.set_defaults(handler=_run_buildkite_live_request_status)

    deployment_runtime_parser = subparsers.add_parser(
        "verify-deployment-ansible-runtime",
        help="verify exact repository-pinned deployment Ansible collections",
    )
    deployment_runtime_parser.set_defaults(
        handler=_run_verify_deployment_ansible_runtime
    )

    identity_parser = subparsers.add_parser(
        "verify-buildkite-openbao-identity",
        help="verify Buildkite workload identity through OpenBao JWT auth",
    )
    identity_parser.set_defaults(handler=_run_verify_buildkite_openbao_identity)

    buildkite_deploy_parser = subparsers.add_parser(
        "deploy-buildkite-promotion",
        help="deploy one requested protected Buildkite promotion",
    )
    buildkite_deploy_parser.add_argument("--promotion", required=True, type=Path)
    buildkite_deploy_parser.add_argument("--report-json", required=True, type=Path)
    buildkite_deploy_parser.set_defaults(handler=_run_deploy_buildkite_promotion)

    audit_parser = subparsers.add_parser(
        "audit", help="verify, persist, and query durable audit evidence"
    )
    audit_subparsers = audit_parser.add_subparsers(dest="audit_command", required=True)

    def add_audit_root(command: argparse.ArgumentParser) -> None:
        command.add_argument(
            "--store-root",
            type=Path,
            help="external audit root; defaults to NCDP_AUDIT_STORE_ROOT",
        )

    audit_verify_parser = audit_subparsers.add_parser(
        "verify-store", help="validate the external audit-store boundary"
    )
    add_audit_root(audit_verify_parser)
    audit_verify_parser.set_defaults(handler=_run_audit_verify_store)

    audit_persist_parser = audit_subparsers.add_parser(
        "persist-buildkite", help="persist one correlated protected Buildkite audit"
    )
    add_audit_root(audit_persist_parser)
    audit_persist_parser.add_argument("--promotion", required=True, type=Path)
    audit_persist_parser.add_argument("--staging-evidence", required=True, type=Path)
    audit_persist_parser.add_argument("--change-record", type=Path)
    audit_persist_parser.set_defaults(handler=_run_audit_persist_buildkite)

    audit_buildkite_parser = audit_subparsers.add_parser(
        "verify-buildkite", help="verify protected audit inputs before device access"
    )
    add_audit_root(audit_buildkite_parser)
    audit_buildkite_parser.add_argument("--promotion", required=True, type=Path)
    audit_buildkite_parser.add_argument("--staging-evidence", required=True, type=Path)
    audit_buildkite_parser.set_defaults(handler=_run_audit_verify_buildkite)

    audit_show_parser = audit_subparsers.add_parser(
        "show", help="read one verified audit envelope by UUID"
    )
    add_audit_root(audit_show_parser)
    audit_show_parser.add_argument("record_id", type=UUID)
    audit_show_parser.set_defaults(handler=_run_audit_show)

    audit_find_parser = audit_subparsers.add_parser(
        "find", help="scan verified audit envelopes using one bounded filter"
    )
    add_audit_root(audit_find_parser)
    filters = audit_find_parser.add_mutually_exclusive_group(required=True)
    filters.add_argument("--change-id", type=_audit_change_id)
    filters.add_argument("--commit", type=_audit_commit)
    filters.add_argument("--build-id", type=UUID)
    filters.add_argument("--device-id", type=_audit_device_id)
    audit_find_parser.add_argument(
        "--max-results",
        type=int,
        choices=range(1, MAX_AUDIT_FIND_RESULTS + 1),
        default=100,
    )
    audit_find_parser.set_defaults(handler=_run_audit_find)

    deploy_parser = subparsers.add_parser(
        "deploy",
        help="execute one explicitly digest-approved immutable plan",
    )
    deploy_parser.add_argument("--plan", required=True, type=Path)
    deploy_inventory = deploy_parser.add_mutually_exclusive_group(required=True)
    deploy_inventory.add_argument("--inventory", type=Path)
    deploy_inventory.add_argument("--netbox", action="store_true")
    deploy_secrets = deploy_parser.add_mutually_exclusive_group(required=True)
    deploy_secrets.add_argument("--openbao", action="store_true")
    deploy_secrets.add_argument("--environment-secrets", action="store_true")
    deploy_parser.add_argument("--approve-digest", required=True)
    deploy_parser.add_argument("--report-json", required=True, type=Path)
    deploy_parser.set_defaults(handler=_run_deploy)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command-line interface and return its exit status."""
    parser = build_parser()
    arguments = list(argv) if argv is not None else None
    if arguments == []:
        parser.print_help()
        return 0
    if arguments is None:
        import sys

        if len(sys.argv) == 1:
            parser.print_help()
            return 0
    parsed = parser.parse_args(arguments)
    if not hasattr(parsed, "handler"):
        parser.print_help()
        return 0
    try:
        return int(parsed.handler(parsed))
    except (
        InventoryError,
        FleetSafetyError,
        OSError,
        ProviderError,
        PlanAssuranceError,
        PromotionError,
        SafetyError,
        SecretError,
        ValueError,
        ValidationError,
        yaml.YAMLError,
    ) as error:
        parser.error(str(error))
    return 2
