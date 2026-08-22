"""Command-line interface for the platform shell."""

from __future__ import annotations

import argparse
import os
from collections.abc import Sequence
from contextlib import suppress
from datetime import UTC, datetime
from importlib.metadata import version
from io import TextIOWrapper
from pathlib import Path

import yaml
from pydantic import ValidationError

from network_change_delivery.ansible_adapter import ProviderError
from network_change_delivery.assurance import (
    AssuranceEvidence,
    AssuranceOutcome,
    AssuranceProviderError,
    BatfishAssuranceAdapter,
    BatfishAssuranceIntent,
    InvariantResult,
    ParseSummary,
    build_snapshot_manifest,
    evaluate_assurance,
)
from network_change_delivery.fleet import FleetSafetyError, deploy_fleet, plan_fleet
from network_change_delivery.inventory import (
    InventoryError,
    LocalYamlInventoryProvider,
    NetBoxInventoryProvider,
)
from network_change_delivery.models import (
    DeploymentPlan,
    FleetDeploymentPlan,
    FleetFinalOutcome,
    FleetInterfaceDescriptionIntent,
    FleetMemberClassification,
    InterfaceDescriptionIntent,
)
from network_change_delivery.secrets import (
    EnvironmentSecretProvider,
    OpenBaoSecretProvider,
    SecretError,
)
from network_change_delivery.vendor_adapter import MultiVendorAdapter
from network_change_delivery.workflow import SafetyError, deploy_plan, plan_change


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
    empty = ParseSummary(nodes=(), parse_status={}, initialization_issue_count=0)
    return AssuranceEvidence(
        generated_at=datetime.now(UTC),
        subject_digest=intent.subject_digest,
        pybatfish_version="unknown",
        baseline_snapshot_digest=baseline_digest,
        candidate_snapshot_digest=candidate_digest,
        expected_nodes=tuple(sorted(intent.expected_nodes)),
        baseline_parse=empty,
        candidate_parse=empty,
        baseline_initialization_issue_count=0,
        candidate_initialization_issue_count=0,
        critical_flows=(),
        differential_changed_flow_count=0,
        invariants=(InvariantResult(name="provider", passed=False, detail=message),),
        outcome=AssuranceOutcome.BLOCKED,
    )


def _run_assure(arguments: argparse.Namespace) -> int:
    with _reserve_assurance_evidence(arguments.report_json) as evidence:
        try:
            intent = _load_assurance_intent(arguments.intent)
            baseline = build_snapshot_manifest(arguments.baseline)
            candidate = build_snapshot_manifest(arguments.candidate)
            observation = BatfishAssuranceAdapter().analyze(
                arguments.baseline, arguments.candidate, intent
            )
            result = evaluate_assurance(intent, baseline, candidate, observation)
        except (OSError, ValueError, AssuranceProviderError) as error:
            baseline_digest = "sha256:" + "0" * 64
            candidate_digest = "sha256:" + "0" * 64
            with suppress(OSError, ValueError):
                baseline_digest = build_snapshot_manifest(arguments.baseline).digest
            with suppress(OSError, ValueError):
                candidate_digest = build_snapshot_manifest(arguments.candidate).digest
            result = _blocked_assurance_evidence(
                intent
                if "intent" in locals()
                else BatfishAssuranceIntent(
                    subject_digest="sha256:" + "0" * 64,
                    expected_nodes=(),
                    critical_flows=(),
                ),
                baseline_digest,
                candidate_digest,
                str(error),
            )
        evidence.write(result.model_dump_json(indent=2) + "\n")
        evidence.flush()
        os.fsync(evidence.fileno())
    print(f"Subject digest: {result.subject_digest}")
    print(f"Baseline snapshot digest: {result.baseline_snapshot_digest}")
    print(f"Candidate snapshot digest: {result.candidate_snapshot_digest}")
    print(f"Parsed node count: {len(result.candidate_parse.nodes)}")
    issue_count = (
        result.baseline_initialization_issue_count
        + result.candidate_initialization_issue_count
    )
    print(f"Initialization issues: {issue_count}")
    print(f"Critical flows: {len(result.critical_flows)}")
    print(f"Differential changed-flow count: {result.differential_changed_flow_count}")
    print(f"Final assurance outcome: {result.outcome}")
    print(f"Evidence: {arguments.report_json}")
    return 0 if result.outcome is AssuranceOutcome.PASSED else 2


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
        SafetyError,
        SecretError,
        ValidationError,
        yaml.YAMLError,
    ) as error:
        parser.error(str(error))
    return 2
