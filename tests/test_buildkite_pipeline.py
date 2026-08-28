import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parents[1]
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


def _steps_by_key(pipeline: dict[str, object]) -> dict[str, dict[str, object]]:
    steps = {step["key"]: step for step in pipeline["steps"]}
    protected = steps["protected-delivery"]
    steps.update({step["key"]: step for step in protected["steps"]})
    return steps


def test_pipeline_contract() -> None:
    pipeline = yaml.safe_load((ROOT / ".buildkite/pipeline.yml").read_text())
    top_level_steps = {step["key"]: step for step in pipeline["steps"]}
    assert set(top_level_steps) == {
        "quality",
        "pipeline-contract",
        "cml-staging",
        "protected-delivery",
    }
    steps = _steps_by_key(pipeline)
    assert "if_changed" not in steps["quality"]
    assert "if_changed" not in steps["pipeline-contract"]
    quality = steps["quality"]
    assert quality["group"] == ":white_check_mark: quality"
    assert quality["key"] == "quality"
    quality_steps = {step["key"]: step for step in quality["steps"]}
    assert set(quality_steps) == {
        "quality-env",
        "quality-committed-diff",
        "quality-ruff-lint",
        "quality-ruff-format",
        "quality-pytest",
        "quality-ansible-lint",
        "quality-package-build",
        "quality-terraform-cml",
    }
    assert all(
        step["agents"]["queue"] == "ncdp-validation" for step in quality_steps.values()
    )

    environment = quality_steps["quality-env"]["command"]
    assert environment == (
        "docker build --target quality-base --tag "
        "ncdp-quality-env:$${BUILDKITE_BUILD_NUMBER} ."
    )

    checks = {
        "quality-ruff-lint": "uv run ruff check .",
        "quality-ruff-format": "uv run ruff format --check .",
        "quality-pytest": "uv run pytest",
        "quality-ansible-lint": "uv run ansible-lint",
        "quality-package-build": "uv build",
    }
    for key, validation_command in checks.items():
        step = quality_steps[key]
        assert step["depends_on"] == "quality-env"
        assert step["command"] == (
            "docker run --rm ncdp-quality-env:$${BUILDKITE_BUILD_NUMBER} "
            f"{validation_command}"
        )

    terraform = quality_steps["quality-terraform-cml"]
    terraform_command = terraform["command"]
    assert "hashicorp/terraform:1.15.8@sha256:" in terraform_command
    assert "${PWD}:/workspace:ro" in terraform_command
    assert "TF_DATA_DIR=/tmp/terraform-data-operator" in terraform_command
    assert "TF_DATA_DIR=/tmp/terraform-data-ephemeral" in terraform_command
    assert "terraform version" in terraform_command
    assert "fmt -check -recursive" in terraform_command
    assert "init -backend=false -input=false -lockfile=readonly" in terraform_command
    assert "terraform -chdir=infrastructure/cml validate" in terraform_command
    assert "terraform -chdir=infrastructure/cml/ephemeral validate" in terraform_command
    assert "CML2_" not in terraform_command
    for forbidden in (" plan", " apply", " import", " destroy"):
        assert forbidden not in terraform_command

    committed_diff = quality_steps["quality-committed-diff"]["command"]
    assert committed_diff.count("git --no-pager diff --check") == 2
    assert "git diff --check" not in committed_diff
    assert committed_diff.count("$${BUILDKITE_PULL_REQUEST") == 3
    assert "${BUILDKITE_PULL_REQUEST" not in committed_diff.replace(
        "$${BUILDKITE_PULL_REQUEST", ""
    )

    assert steps["pipeline-contract"]["agents"]["queue"] == "ncdp-validation"
    staging = steps["cml-staging"]
    assert staging["agents"]["queue"] == "ncdp-staging"
    assert staging["if"] == "false"
    assert staging["depends_on"] == ["quality", "pipeline-contract"]
    assert staging["command"] == "scripts/buildkite/ephemeral_staging.sh"
    assert staging["concurrency"] == 1
    assert staging["concurrency_group"] == "ncdp/cml-ephemeral-staging"
    assert staging["retry"] == {
        "automatic": False,
        "manual": {
            "allowed": False,
            "reason": "Retained staging state requires explicit operator recovery.",
        },
    }
    assert staging["if_changed"] == RUNTIME_CHANGE_CONDITION
    protected = steps["protected-delivery"]
    assert protected["depends_on"] == "cml-staging"
    assert protected["if_changed"] == RUNTIME_CHANGE_CONDITION
    assert [step["key"] for step in protected["steps"]] == [
        "promotion",
        "deployment-approval",
        "deploy-gate",
    ]
    assert steps["promotion"]["agents"]["queue"] == "ncdp-validation"
    assert steps["promotion"]["concurrency"] == 1
    assert steps["promotion"]["concurrency_group"] == "ncdp/batfish-promotion"
    assert steps["deploy-gate"]["agents"]["queue"] == "ncdp-deploy"
    assert steps["deploy-gate"]["concurrency"] == 1
    assert steps["deploy-gate"]["concurrency_group"] == "ncdp/network-change-deployment"
    assert steps["deploy-gate"]["retry"] == {
        "automatic": False,
        "manual": {
            "allowed": False,
            "reason": (
                "A fresh deployment authorization is required for another attempt."
            ),
        },
    }
    approval = steps["deployment-approval"]
    assert approval["block"] == ":lock: Authorize exact promotion"
    assert approval["prompt"] == (
        "Authorize the exact immutable promotion verified and recorded by the "
        "promotion step."
    )
    assert approval["submit"] == "Authorize exact promotion"
    assert "fields" not in approval
    assert steps["promotion"]["depends_on"] == "cml-staging"
    assert steps["deployment-approval"]["depends_on"] == "promotion"
    assert steps["deploy-gate"]["depends_on"] == "deployment-approval"
    assert len(steps["pipeline-contract"]["commands"]) == 1
    contract = " ".join(steps["pipeline-contract"]["commands"])
    assert contract == (
        "buildkite-agent pipeline upload .buildkite/pipeline.yml --dry-run "
        "--format yaml --reject-secrets --reject-parse-warnings > /dev/null"
    )
    assert "uv run" not in contract
    assert "--dry-run" in contract
    assert "--format yaml" in contract
    assert "--reject-secrets" in contract
    assert "--reject-parse-warnings" in contract


def test_pr_and_main_conditions() -> None:
    pipeline = yaml.safe_load((ROOT / ".buildkite/pipeline.yml").read_text())
    steps = _steps_by_key(pipeline)
    protected = steps["protected-delivery"]
    assert protected["if"] == (
        'false && build.branch == "main" && build.pull_request.id == null'
    )
    assert steps["cml-staging"]["if"] == "false"
    for key in ("promotion", "deployment-approval", "deploy-gate"):
        assert "if" not in steps[key]


def test_live_paths_use_fail_closed_allowlist() -> None:
    pipeline = yaml.safe_load((ROOT / ".buildkite/pipeline.yml").read_text())
    steps = _steps_by_key(pipeline)
    assert steps["cml-staging"]["if_changed"] == RUNTIME_CHANGE_CONDITION
    assert steps["protected-delivery"]["if_changed"] == RUNTIME_CHANGE_CONDITION

    assert RUNTIME_CHANGE_CONDITION["include"] == "**"
    assert set(RUNTIME_CHANGE_CONDITION["exclude"]) == {
        "docs/**",
        "README.md",
        "AGENTS.md",
        ".github/CODEOWNERS",
        ".github/pull_request_template.md",
        "tests/**",
        ".gitignore",
    }


@pytest.mark.parametrize(
    ("changed_files", "live_path_expected"),
    [
        (("docs/foo.md",), False),
        (("README.md",), False),
        (("AGENTS.md",), False),
        ((".github/CODEOWNERS",), False),
        ((".github/pull_request_template.md",), False),
        (("tests/test_something.py",), False),
        ((".gitignore",), False),
        (("docs/foo.md", "tests/test_something.py"), False),
        (("src/network_change_delivery/example.py",), True),
        (("scripts/example.sh",), True),
        ((".buildkite/pipeline.yml",), True),
        ((".github/workflows/quality.yml",), True),
        ((".github/new-control-plane-file.yml",), True),
        (("infrastructure/example.tf",), True),
        (("ansible/example.yml",), True),
        (("ansible.cfg",), True),
        (("pyproject.toml",), True),
        (("uv.lock",), True),
        ((".python-version",), True),
        (("Dockerfile",), True),
        ((".dockerignore",), True),
        (("compose.assurance.yaml",), True),
        (("deployments/example",), True),
        (("arbitrary-new-directory/example.txt",), True),
        (("docs/foo.md", "src/network_change_delivery/example.py"), True),
    ],
)
def test_installed_buildkite_change_evaluation(
    tmp_path: Path,
    changed_files: tuple[str, ...],
    live_path_expected: bool,
) -> None:
    agent = shutil.which("buildkite-agent")
    if agent is None:
        pytest.skip("Buildkite agent is not installed in this test environment")

    changed_files_path = tmp_path / "changed-files.txt"
    changed_files_path.write_text("\n".join(changed_files) + "\n")
    result = subprocess.run(
        [
            agent,
            "pipeline",
            "upload",
            str(ROOT / ".buildkite/pipeline.yml"),
            "--dry-run",
            "--format",
            "yaml",
            "--reject-secrets",
            "--reject-parse-warnings",
            "--changed-files-path",
            str(changed_files_path),
        ],
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, "BUILDKITE_AGENT_ACCESS_TOKEN": "local-dry-run"},
    )
    rendered = yaml.safe_load(result.stdout)
    rendered_steps = {step["key"]: step for step in rendered["steps"]}
    for key in ("cml-staging", "protected-delivery"):
        assert ("skip" not in rendered_steps[key]) is live_path_expected


def test_external_bootstrap_fetches_diff_base() -> None:
    setup = (ROOT / "docs/acceptance/buildkite-external-setup.md").read_text()
    assert "buildkite-agent pipeline upload --fetch-diff-base" in setup
    assert "Settings → Steps → Commands" in setup


def test_promotion_container_contract() -> None:
    compose = yaml.safe_load((ROOT / "compose.assurance.yaml").read_text())
    promotion = compose["services"]["promotion"]
    assert promotion["image"] == "ncdp-promotion:${NCDP_PROMOTION_IMAGE_TAG:-local}"
    assert promotion["build"] == {"context": ".", "target": "promotion"}
    assert promotion["environment"] == {"NCDP_BATFISH_HOST": "batfish"}

    dockerfile = (ROOT / "Dockerfile").read_text()
    assert "FROM application AS promotion" in dockerfile
    assert "COPY fixtures/batfish ./fixtures/batfish" in dockerfile
    assert "COPY deployments/live/promotion ./deployments/live/promotion" in dockerfile
    assert "COPY . ." not in dockerfile.split("FROM application AS promotion", 1)[1]
    assert "RUN chmod -R a=rX" in dockerfile
    for path in (
        "/app/.venv",
        "/app/src",
        "/app/fixtures/batfish",
        "/app/deployments/live/promotion",
        "/app/scripts/buildkite",
    ):
        assert path in dockerfile.split("FROM application AS promotion", 1)[1]


def test_scripts_static_contract() -> None:
    gate = (ROOT / "scripts/buildkite/deployment_gate.sh").read_text()
    promotion = (ROOT / ".buildkite/scripts/promotion.sh").read_text()
    promoted_keys = {
        "promoted-plan-digest",
        "promoted-assurance-digest",
        "promoted-promotion-digest",
    }
    assert gate.count("buildkite-agent meta-data get") == 3
    for key in promoted_keys:
        assert f'meta-data get "{key}"' in gate
    assert "approved-" not in gate
    assert gate.startswith("#!/usr/bin/env bash\nset -euo pipefail\n")
    oidc_command = (
        "buildkite-agent oidc request-token \\\n"
        "  --audience urn:ncdp:openbao:deploy \\\n"
        "  --lifetime 300 \\\n"
        "  --subject-claim pipeline_id |\n"
        "  uv run ncdp verify-buildkite-openbao-identity"
    )
    assert oidc_command in gate
    assert gate.count("buildkite-agent oidc request-token") == 2
    assert '[[ "${NCDP_OPENBAO_JWT_DIAGNOSTICS:-}" == 1 ]]' in gate
    assert gate.index("NCDP_OPENBAO_JWT_DIAGNOSTICS") < gate.index(
        'tmpdir="$(mktemp -d)"'
    )
    assert "--skip-redaction" not in gate
    assert "set -x" not in gate
    pre = gate.index("capture-buildkite-configuration")
    deploy = gate.index("deploy-buildkite-promotion")
    post = gate.index("capture-buildkite-configuration", pre + 1)
    parent = gate.index("--change-record")
    child = gate.index("persist-buildkite-configuration-observation")
    assert pre < deploy < post < parent < child
    assert gate.count("capture-buildkite-configuration") == 2
    assert gate.index("verify_commit.sh") < gate.index("oidc request-token")
    assert 'retry_count="${BUILDKITE_RETRY_COUNT:-0}"' in gate
    assert "retried deployment job is not authorized" in gate
    assert gate.index("BUILDKITE_STEP_KEY") < gate.index("BUILDKITE_RETRY_COUNT")
    assert gate.index("BUILDKITE_AGENT_META_DATA_QUEUE") < gate.index(
        "BUILDKITE_RETRY_COUNT"
    )
    assert gate.index("BUILDKITE_RETRY_COUNT") < gate.index("verify_commit.sh")
    assert gate.index("BUILDKITE_RETRY_COUNT") < gate.index("oidc request-token")
    assert gate.index("verify-buildkite-openbao-identity") < gate.index(
        "artifact download"
    )
    assert gate.index("verify-buildkite-openbao-identity") < gate.index(
        "verify-buildkite-gate"
    )
    for variable in (
        "NCDP_OPENBAO_ROLE_ID",
        "NCDP_OPENBAO_SECRET_ID",
        "NCDP_DEVICE_USERNAME",
        "NCDP_DEVICE_PASSWORD",
    ):
        assert variable in gate
    assert "uv run ncdp deploy " not in gate
    assert "ncdp fleet-deploy" not in gate
    assert "--step promotion" in gate
    assert '"staging-evidence/staging-run.json" "$tmpdir" --step cml-staging' in gate
    assert "uv run ncdp verify-buildkite-gate" in gate
    assert "uv run ncdp audit verify-buildkite" in gate
    assert gate.index("audit verify-buildkite") < gate.index(
        "buildkite-live-request-status"
    )
    assert gate.index("audit verify-buildkite") < gate.index(
        "deploy-buildkite-promotion"
    )
    assert gate.index("verify-buildkite-gate") < gate.index(
        "buildkite-live-request-status"
    )
    assert gate.index("buildkite-live-request-status") < gate.index(
        "verify-buildkite-live-request"
    )
    assert gate.index("verify-buildkite-live-request") < gate.rindex(
        "oidc request-token"
    )
    assert gate.index("verify-buildkite-live-request") < gate.index(
        "verify-deployment-ansible-runtime"
    )
    authorized_path = "/Users/netdevops/.local/share/ncdp/ansible/collections"
    assert f"authorized_ansible_collections={authorized_path}" in gate
    assert "deployment Ansible collection path is not authorized" in gate
    assert gate.index("authorized_ansible_collections=") < gate.index(
        "verify-deployment-ansible-runtime"
    )
    assert "ansible-galaxy" not in gate
    assert "~/.ansible" not in gate
    assert gate.index("verify-deployment-ansible-runtime") < gate.rindex(
        "oidc request-token"
    )
    assert gate.index("verify-deployment-ansible-runtime") < gate.index(
        "deploy-buildkite-promotion"
    )
    assert gate.index("verify-buildkite-live-request") < gate.index(
        "deploy-buildkite-promotion"
    )
    assert 'request_status" -eq 3' in gate
    assert "live deployment requested: NO" not in gate
    assert gate.count("device write executed: YES") == 1
    assert "set +e" in gate
    assert "deployment_status=$?" in gate
    assert "audit_status=$?" in gate
    assert gate.count("deploy-buildkite-promotion") == 1
    assert gate.rindex("audit persist-buildkite") > gate.index(
        "deploy-buildkite-promotion"
    )
    assert "will not be retried or recovered for an audit-only failure" in gate
    assert 'exit "$deployment_status"' in gate
    assert "inspect the uploaded typed ChangeRecord evidence" in gate
    assert gate.index("artifact upload") < gate.index('exit "$deployment_status"')
    assert 'cd "$tmpdir"' in gate
    assert 'buildkite-agent artifact upload "$report_relative"' in gate
    assert "deployments/live/request.yaml" not in gate
    assert "verify_commit.sh" in promotion
    assert promotion.index("verify_commit.sh") < promotion.index("assure-plan")
    assert 'promotion="$tmpdir/promotion"' in promotion
    assert "uv run" not in promotion
    assert "docker compose --project-name ncdp-promotion" in promotion
    assert 'NCDP_PROMOTION_IMAGE_TAG="$BUILDKITE_BUILD_NUMBER"' in promotion
    assert '"${compose[@]}" build promotion' in promotion
    assert (
        '"${promotion_run[@]}" python scripts/buildkite/batfish_ready.py' in promotion
    )
    assert promotion.count('"${promotion_run[@]}" ncdp ') == 6
    assert promotion.count("deployments/live/promotion/plan.json") == 2
    assert promotion.count("deployments/live/promotion/policy.yaml") == 2
    assert promotion.count("deployments/live/promotion/baseline") == 2
    assert "fixtures/batfish/plans/fleet-interface-description.json" not in promotion
    for field in ("plan", "assurance", "promotion"):
        assert promotion.count(f"--field {field}") == 1
    assert '--volume "$tmpdir:/output"' in promotion
    assert '[[ -f "$promotion/manifest.json" ]]' in promotion
    assert "buildkite-agent artifact upload 'promotion/**'" in promotion
    assert {
        line.split('"')[1]
        for line in promotion.splitlines()
        if "buildkite-agent meta-data set" in line
    } == promoted_keys
    assert "approved-" not in promotion
    upload = promotion.index("buildkite-agent artifact upload 'promotion/**'")
    digest = promotion.index("ncdp promotion-digest")
    publication = promotion.index("buildkite-agent meta-data set")
    assert promotion.index("ncdp verify-promotion") < upload < digest < publication
    metadata_section = promotion[digest:]
    assert "grep" not in metadata_section
    assert "sed" not in metadata_section
