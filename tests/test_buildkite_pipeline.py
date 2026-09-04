"""Static contract for the final profiled validation-only Buildkite pipeline."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parents[1]
PIPELINE = ROOT / ".buildkite/pipeline.yml"
RUNTIME_CHANGE_CONDITION = {
    "include": "**",
    "exclude": [
        "docs/**",
        "README.md",
        "AGENTS.md",
        ".github/CODEOWNERS",
        ".github/pull_request_template.md",
        "tests/**",
        ".gitignore",
    ],
}


def _steps() -> dict[str, dict[str, object]]:
    pipeline = yaml.safe_load(PIPELINE.read_text(encoding="utf-8"))
    return {step["key"]: step for step in pipeline["steps"]}


def test_pipeline_retains_validation_and_profiled_pr_assurance_only() -> None:
    steps = _steps()
    assert set(steps) == {
        "quality-env",
        "quality-committed-diff",
        "quality-ruff-lint",
        "quality-ruff-format",
        "quality-pytest",
        "quality-ansible-lint",
        "quality-package-build",
        "quality-snmp-generator",
        "quality-observability-runtime",
        "quality-snmpv3-synthetic",
        "buildkite-definition",
        "ncdp-pipeline-contract",
        "validation-complete",
        "pr-batfish-assurance",
    }
    assert steps["validation-complete"] == {"wait": None, "key": "validation-complete"}
    assurance = steps["pr-batfish-assurance"]
    assert assurance["command"] == ".buildkite/scripts/profiled_pr_batfish_assurance.sh"
    assert assurance["depends_on"] == "validation-complete"
    assert assurance["if"] == "build.pull_request.id != null"
    assert assurance["agents"] == {"queue": "ncdp-validation"}
    assert assurance["retry"]["automatic"] is False
    assert assurance["if_changed"] == RUNTIME_CHANGE_CONDITION


def test_pipeline_contains_no_retired_or_device_write_surface() -> None:
    source = PIPELINE.read_text(encoding="utf-8")
    for retired in (
        "quality-terraform-cml",
        "cml-staging",
        "protected-delivery",
        ".buildkite/scripts/batfish_assurance.sh",
        ".buildkite/scripts/promotion.sh",
        "scripts/buildkite/deployment_gate.sh",
        "deploy-buildkite-promotion",
        "profiled-deploy",
        "fleet-deploy",
        "ncdp deploy",
    ):
        assert retired not in source
    assert "ncdp-staging" not in source
    assert "ncdp-deploy" not in source


def test_retained_quality_commands_are_fail_closed() -> None:
    steps = _steps()
    image = "ncdp-quality-env:$${BUILDKITE_BUILD_NUMBER}"
    assert steps["quality-env"]["command"] == (
        f"docker build --target quality-base --tag {image} ."
    )
    expected = {
        "quality-ruff-lint": "uv run ruff check .",
        "quality-ruff-format": "uv run ruff format --check .",
        "quality-pytest": "uv run pytest --ignore=tests/test_buildkite_pipeline.py",
        "quality-ansible-lint": "uv run ansible-lint",
        "quality-package-build": "uv build",
    }
    for key, command in expected.items():
        assert steps[key]["depends_on"] == "quality-env"
        assert steps[key]["command"] == f"docker run --rm {image} {command}"
        assert steps[key]["agents"] == {"queue": "ncdp-validation"}

    for key in ("quality-observability-runtime", "quality-snmpv3-synthetic"):
        assert steps[key]["depends_on"] == "quality-env"
        assert steps[key]["agents"] == {"queue": "ncdp-validation"}
        assert steps[key]["retry"] == {"automatic": False}

    contract = steps["ncdp-pipeline-contract"]
    assert contract["depends_on"] == "quality-env"
    assert "test_installed_buildkite_change_evaluation" in contract["commands"][1]


def test_profiled_assurance_wrapper_has_no_runtime_authority() -> None:
    source = (ROOT / ".buildkite/scripts/profiled_pr_batfish_assurance.sh").read_text(
        encoding="utf-8"
    )
    assert '"${BUILDKITE_STEP_KEY:-}" != pr-batfish-assurance' in source
    assert '"${BUILDKITE_AGENT_META_DATA_QUEUE:-}" != ncdp-validation' in source
    assert '"${BUILDKITE_RETRY_COUNT:-}" != 0' in source
    assert "scripts/buildkite/verify_commit.sh" in source
    assert "scripts/assurance/verify_profiled_pr_candidate.py" in source
    for forbidden in (
        "NCDP_OPENBAO",
        "NCDP_NETBOX",
        "oidc request-token",
        "ansible-playbook",
        "profiled-deploy",
        "deployment_gate.sh",
        "terraform",
    ):
        assert forbidden not in source


def test_installed_buildkite_change_evaluation() -> None:
    """The installed parser accepts the final source without contacting Buildkite."""
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
