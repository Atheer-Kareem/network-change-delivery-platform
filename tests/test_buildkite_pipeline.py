"""Continuation is presentation; same-build promotion owns write admission."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from network_change_delivery.profiled_promotion import MAIN_KEYS, VALIDATION_KEYS

ROOT = Path(__file__).parents[1]
PIPELINE = ROOT / ".buildkite/pipeline.yml"


def steps():
    return yaml.safe_load(PIPELINE.read_text())["steps"]


def test_exact_order_and_unconditional_command_continuation():
    graph = steps()
    assert [step["key"] for step in graph] == [
        *VALIDATION_KEYS,
        "validation-complete",
        "pr-batfish-assurance",
        "cml-staging",
        *MAIN_KEYS,
    ]
    assert len({step["key"] for step in graph}) == len(graph)
    assert sum("command" in step for step in graph) == 19
    for step in graph:
        assert "if_changed" not in step
        assert "allow_dependency_failure" not in step
        if "command" in step:
            assert step["soft_fail"] is True
            assert step["retry"]["automatic"] is False
            assert step["retry"]["manual"]["allowed"] is False
        else:
            assert "soft_fail" not in step
    assert graph[13] == {
        "key": "validation-complete",
        "wait": None,
        "continue_on_failure": True,
    }


def test_pr_vs_main_graph_and_real_human_block():
    indexed = {step["key"]: step for step in steps()}
    batfish = indexed["pr-batfish-assurance"]
    assert batfish["if"] == 'build.pull_request.id != null || build.branch == "main"'
    assert batfish["depends_on"] == "validation-complete"
    assert batfish["command"] == ".buildkite/scripts/profiled_pr_batfish_assurance.sh"
    assert batfish["agents"] == {"queue": "ncdp-validation"}
    assert batfish["concurrency"] == 1
    assert batfish["concurrency_group"] == "ncdp/batfish-assurance"
    cml = indexed["cml-staging"]
    # Temporary development exception: PR and non-main development jobs skip CML.
    # The same main-only condition still schedules the full authorized delivery tail.
    assert cml["if"] == 'build.branch == "main" && build.pull_request.id == null'
    assert cml["depends_on"] == ["validation-complete", "pr-batfish-assurance"]
    assert cml["command"] == ".buildkite/scripts/profiled_cml_staging.sh"
    assert cml["agents"] == {"queue": "ncdp-staging"}
    assert cml["concurrency"] == 1
    assert cml["concurrency_group"] == "ncdp/cml-ephemeral-staging"
    previous = "cml-staging"
    for key in MAIN_KEYS:
        step = indexed[key]
        assert step["if"] == 'build.branch == "main" && build.pull_request.id == null'
        assert step["depends_on"] == previous
        previous = key
        if key != "profiled-human-authorization":
            assert step["command"] == ".buildkite/scripts/profiled_delivery.sh"
            queue = (
                "ncdp-deploy"
                if key in {MAIN_KEYS[0], MAIN_KEYS[3]}
                else "ncdp-validation"
            )
            assert step["agents"] == {"queue": queue}
    block = indexed[MAIN_KEYS[2]]
    assert block["block"] == "Human continuation · promoted change or compliance"
    assert "fields" not in block and "command" not in block
    assert "For a real promotion, review the promoted schema-v2 plan" in block["prompt"]
    assert "unblocking authorizes only this exact build/promotion" in block["prompt"]
    assert "For COMPLIANT, no plan or promotion exists" in block["prompt"]
    assert "continuation grants no write authority" in block["prompt"]
    assert "Human continuation never repairs failed prerequisites" in block["prompt"]
    assert indexed["profiled-promotion"]["label"] == (
        "Delivery decision · promotion or compliance"
    )
    assert indexed["profiled-deploy"]["label"] == (
        "Profiled delivery · authorized execution or compliant no-write"
    )
    for key in (MAIN_KEYS[0], MAIN_KEYS[3]):
        assert indexed[key]["concurrency"] == 1
        assert indexed[key]["concurrency_group"] == "ncdp/profiled-live-delivery"


def test_no_legacy_or_separate_demo_projection():
    source = PIPELINE.read_text()
    for forbidden in (
        "NCDP_DEMO_CONTINUE_ON_FAILURE",
        "render_demo_pipeline",
        "protected-delivery",
        "deploy-buildkite-promotion",
        "fleet-deploy",
        "ncdp deploy",
        "deployment_gate.sh",
        ".buildkite/scripts/promotion.sh",
    ):
        assert forbidden not in source
    assert not (ROOT / "scripts/buildkite/render_demo_pipeline.py").exists()


def test_temporary_development_cml_exception_retains_real_main_prerequisite():
    indexed = {step["key"]: step for step in steps()}
    cml = indexed["cml-staging"]
    assert cml["if"] == 'build.branch == "main" && build.pull_request.id == null'
    assert cml["if"] == indexed["profiled-live-plan"]["if"]
    assert indexed["profiled-live-plan"]["depends_on"] == "cml-staging"
    # Skipping a scheduled job cannot produce a substitute receipt command.
    assert cml["command"] == ".buildkite/scripts/profiled_cml_staging.sh"
    assert "profiled-cml-success" not in PIPELINE.read_text()
    ledger = (ROOT / "docs/roadmap.md").read_text()
    assert "Disposable CML staging on PR/development builds — ACTIVE" in ledger
    assert "before final integrated acceptance of the refinement roadmap" in ledger


def test_engineering_commands_keep_truthful_exit_and_receipt_last():
    indexed = {step["key"]: step for step in steps()}
    expected = {
        "quality-env": "docker build --target quality-base",
        "quality-ruff-lint": "uv run ruff check .",
        "quality-ruff-format": "uv run ruff format --check .",
        "quality-pytest": "uv run pytest --ignore=tests/test_buildkite_pipeline.py",
        "quality-ansible-lint": "uv run ansible-lint",
        "quality-package-build": "uv build",
        "quality-terraform-profiled-staging": (
            "scripts/buildkite/profiled_terraform_validate.sh"
        ),
        "ncdp-pipeline-contract": "test_installed_buildkite_change_evaluation",
    }
    for key in VALIDATION_KEYS:
        source = indexed[key]["command"]
        assert source.startswith("set -euo pipefail\n")
        assert source.rstrip().endswith(
            "uv run --frozen python scripts/buildkite/publish_validation_receipt.py"
        )
        assert "|| true" not in source
        assert indexed[key]["agents"] == {"queue": "ncdp-validation"}
        if key in expected:
            assert expected[key] in source


def test_batfish_remains_credential_free():
    source = (ROOT / ".buildkite/scripts/profiled_pr_batfish_assurance.sh").read_text()
    for forbidden in (
        "NCDP_OPENBAO",
        "NCDP_NETBOX",
        "oidc request-token",
        "ansible-playbook",
        "profiled-deploy",
        "terraform",
    ):
        assert forbidden not in source
    assert "scripts/buildkite/verify_commit.sh" in source
    assert "scripts/assurance/verify_profiled_pr_candidate.py" in source


def test_installed_buildkite_change_evaluation():
    agent = shutil.which("buildkite-agent")
    if agent is None:
        pytest.skip("Buildkite agent is not installed")
    result = subprocess.run(
        [
            agent,
            "pipeline",
            "upload",
            str(PIPELINE),
            "--dry-run",
            "--format",
            "yaml",
            "--reject-secrets",
            "--reject-parse-warnings",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "BUILDKITE_AGENT_ACCESS_TOKEN": "local-dry-run"},
    )
    assert result.returncode == 0, result.stderr
