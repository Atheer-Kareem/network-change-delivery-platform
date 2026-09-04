"""Deletion-gate regressions for the final exact-four profiled architecture."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from network_change_delivery.architecture_contracts import AutomationProfileID
from network_change_delivery.cli import build_parser
from network_change_delivery.profile_inventory import PROFILED_POPULATION_IDENTITIES
from network_change_delivery.profiled_planning import (
    PROFILED_OPERATION_ADMISSIONS,
    ProfiledOperation,
)
from network_change_delivery.snmp_profile import SNMP_PROFILED_DEVICE_IDENTITIES

ROOT = Path(__file__).parents[1]


def _commands() -> set[str]:
    parser = build_parser()
    subparsers = next(
        action
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    return set(subparsers.choices)


def test_exact_four_population_and_capability_projections_are_closed() -> None:
    assert PROFILED_POPULATION_IDENTITIES == (
        "netbox:dcim.device:1",
        "netbox:dcim.device:2",
        "netbox:dcim.device:8",
        "netbox:dcim.device:9",
    )
    assert SNMP_PROFILED_DEVICE_IDENTITIES == (
        "netbox:dcim.device:1",
        "netbox:dcim.device:2",
    )
    admitted = {
        profile
        for profile, operation in PROFILED_OPERATION_ADMISSIONS
        if operation is ProfiledOperation.INTERFACE_DESCRIPTION
    }
    assert admitted == {
        AutomationProfileID.CAT8000V_IOSXE,
        AutomationProfileID.VJUNOS_ROUTER,
    }
    assert AutomationProfileID.IOSV_159_3_M12 not in admitted
    assert AutomationProfileID.IOSVL2_2020 not in admitted


def test_only_profiled_ordinary_change_commands_are_exposed() -> None:
    commands = _commands()
    assert {"profiled-plan", "profiled-deploy"} <= commands
    assert commands.isdisjoint(
        {
            "plan",
            "deploy",
            "fleet-plan",
            "fleet-deploy",
            "snmp-provisioning-plan",
            "deploy-buildkite-promotion",
        }
    )
    source = (ROOT / "src/network_change_delivery/cli.py").read_text(encoding="utf-8")
    for dependency in (
        "NetBoxInventoryProvider",
        "MultiVendorAdapter",
        "plan_change",
        "deploy_plan",
        "plan_fleet",
        "deploy_fleet",
    ):
        assert re.search(rf"\b{dependency}\b", source) is None


def test_pipeline_has_no_retired_staging_or_device_write_path() -> None:
    source = (ROOT / ".buildkite/pipeline.yml").read_text(encoding="utf-8")
    for retired in (
        "cml-staging",
        "protected-delivery",
        "deployment_gate.sh",
        "deploy-buildkite-promotion",
        "profiled-deploy",
        "ncdp-deploy",
        "ncdp-staging",
    ):
        assert retired not in source
    assert not (ROOT / "scripts/buildkite/deployment_gate.sh").exists()
    assert not (ROOT / "scripts/buildkite/ephemeral_staging.sh").exists()
    assert not (ROOT / "infrastructure/cml").joinpath("topology.tf").exists()


def test_retained_runtime_consumers_have_no_legacy_population_dependency() -> None:
    retained = (
        "scripts/cml/verify_profiled_live.py",
        "src/network_change_delivery/observability_targets.py",
        "src/network_change_delivery/oxidized_source.py",
        "src/network_change_delivery/snmp_profile.py",
    )
    for relative in retained:
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert "ncdp-managed" not in source
        assert "NetBoxInventoryProvider" not in source
    verifier = (ROOT / retained[0]).read_text(encoding="utf-8")
    assert "legacy population exact-two" not in verifier
    assert "profiled population exact-four PASS" in verifier


def test_profiled_execution_remains_outside_b5_acceptance() -> None:
    source = "\n".join(
        (ROOT / "src/network_change_delivery" / filename).read_text(encoding="utf-8")
        for filename in ("profiled_execution.py", "profiled_write_adapter.py")
    )
    assert "managed_state_acceptance_attempted: Literal[False] = False" in source
    for dependency in (
        "ManagedStateStore",
        "managed_state_store",
        "build_postwrite_validated_evidence",
    ):
        assert re.search(rf"\b{dependency}\b", source) is None


def test_current_docs_record_retirement_and_pending_external_tag_acceptance() -> None:
    roadmap = (ROOT / "docs/roadmap.md").read_text(encoding="utf-8")
    lifecycle = (ROOT / "docs/architecture/change-lifecycle.md").read_text(
        encoding="utf-8"
    )
    workflow = (ROOT / "docs/architecture/buildkite-workflow.md").read_text(
        encoding="utf-8"
    )
    assert "external tag retirement pending" in roadmap
    assert "schema-v1 fleet engine" in lifecycle
    assert "historically" in lifecycle and "accepted" in lifecycle
    assert "device-write" in workflow and "validation and assurance only" in workflow
    assert "not paused" not in workflow
    assert "temporarily paused" not in roadmap + lifecycle + workflow
