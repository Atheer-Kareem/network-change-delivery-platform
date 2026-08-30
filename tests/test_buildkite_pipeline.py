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
        "quality-env",
        "quality-committed-diff",
        "quality-ruff-lint",
        "quality-ruff-format",
        "quality-pytest",
        "quality-ansible-lint",
        "quality-package-build",
        "quality-terraform-cml",
        "quality-snmp-generator",
        "quality-observability-11b",
        "quality-observability-11c2",
        "buildkite-definition",
        "ncdp-pipeline-contract",
        "validation-complete",
        "cml-staging",
        "protected-delivery",
    }
    assert "quality" not in top_level_steps
    assert all("group" not in step for step in pipeline["steps"][:-1])
    steps = _steps_by_key(pipeline)
    validation_keys = {
        "quality-env",
        "quality-committed-diff",
        "quality-ruff-lint",
        "quality-ruff-format",
        "quality-pytest",
        "quality-ansible-lint",
        "quality-package-build",
        "quality-terraform-cml",
        "quality-snmp-generator",
        "quality-observability-11b",
        "quality-observability-11c2",
        "buildkite-definition",
        "ncdp-pipeline-contract",
    }
    assert validation_keys < set(top_level_steps)
    assert all(
        steps[key]["agents"]["queue"] == "ncdp-validation" for key in validation_keys
    )

    environment = steps["quality-env"]["command"]
    assert environment == (
        "docker build --target quality-base --tag "
        "ncdp-quality-env:$${BUILDKITE_BUILD_NUMBER} ."
    )

    image_checks = {
        "quality-ruff-lint": "uv run ruff check .",
        "quality-ruff-format": "uv run ruff format --check .",
        "quality-pytest": "uv run pytest --ignore=tests/test_buildkite_pipeline.py",
        "quality-ansible-lint": "uv run ansible-lint",
        "quality-package-build": "uv build",
    }
    for key, validation_command in image_checks.items():
        step = steps[key]
        assert step["depends_on"] == "quality-env"
        assert step["command"] == (
            "docker run --rm ncdp-quality-env:$${BUILDKITE_BUILD_NUMBER} "
            f"{validation_command}"
        )

    independent_roots = {
        "quality-env",
        "quality-committed-diff",
        "quality-terraform-cml",
        "quality-snmp-generator",
        "buildkite-definition",
    }
    assert all("depends_on" not in steps[key] for key in independent_roots)

    observability = steps["quality-observability-11b"]
    assert observability["depends_on"] == "quality-env"
    assert observability["agents"]["queue"] == "ncdp-validation"
    assert observability["command"] == (
        "NCDP_QUALITY_IMAGE=ncdp-quality-env:$${BUILDKITE_BUILD_NUMBER} "
        "scripts/observability/verify_runtime.sh"
    )
    assert observability["if_changed"]["include"] == [
        "infrastructure/observability/**",
        "scripts/observability/**",
        "src/network_change_delivery/observability_*.py",
        "tests/test_observability_*.py",
    ]

    snmp_observability = steps["quality-observability-11c2"]
    assert snmp_observability["depends_on"] == "quality-env"
    assert snmp_observability["agents"]["queue"] == "ncdp-validation"
    assert snmp_observability["command"] == (
        "NCDP_QUALITY_IMAGE=ncdp-quality-env:$${BUILDKITE_BUILD_NUMBER} "
        "scripts/observability/verify_snmp_runtime.sh"
    )
    assert snmp_observability["if_changed"]["include"] == [
        "infrastructure/observability/**",
        "scripts/observability/**",
        "src/network_change_delivery/observability_*.py",
        "src/network_change_delivery/snmp_*.py",
        "tests/test_observability_*.py",
        "tests/test_snmp_*.py",
    ]

    snmp_generator = steps["quality-snmp-generator"]
    assert snmp_generator["command"] == (
        "uv run --frozen python scripts/observability/check_snmp_generator.py"
    )
    assert snmp_generator["if_changed"]["include"] == [
        "infrastructure/observability/snmp/**",
        "scripts/observability/check_snmp_generator.py",
        "src/network_change_delivery/snmp_mib.py",
    ]
    assert "depends_on" not in snmp_generator

    terraform = steps["quality-terraform-cml"]
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

    committed_diff = steps["quality-committed-diff"]["command"]
    assert committed_diff.count("git --no-pager diff --check") == 2
    assert "git diff --check" not in committed_diff
    assert committed_diff.count("$${BUILDKITE_PULL_REQUEST") == 3
    assert "${BUILDKITE_PULL_REQUEST" not in committed_diff.replace(
        "$${BUILDKITE_PULL_REQUEST", ""
    )

    definition = steps["buildkite-definition"]
    assert "depends_on" not in definition
    assert definition["command"] == (
        "buildkite-agent pipeline upload .buildkite/pipeline.yml --dry-run "
        "--format yaml --reject-secrets --reject-parse-warnings > /dev/null"
    )

    contract = steps["ncdp-pipeline-contract"]
    assert contract["depends_on"] == "quality-env"
    assert contract["commands"] == [
        (
            "docker run --rm ncdp-quality-env:$${BUILDKITE_BUILD_NUMBER} "
            "uv run pytest tests/test_buildkite_pipeline.py "
            "-k 'not test_installed_buildkite_change_evaluation'"
        ),
        (
            "uv run --frozen pytest tests/test_buildkite_pipeline.py "
            "-k test_installed_buildkite_change_evaluation"
        ),
    ]
    assert "docker run" not in contract["commands"][1]
    assert "buildkite-agent" not in contract["commands"][0]

    ordered_keys = [step["key"] for step in pipeline["steps"]]
    barrier = steps["validation-complete"]
    assert barrier == {"wait": None, "key": "validation-complete"}
    assert ordered_keys.index("validation-complete") < ordered_keys.index("cml-staging")

    staging = steps["cml-staging"]
    assert staging["label"] == (
        ":cloud: Ephemeral CML staging · create → validate → destroy"
    )
    assert staging["agents"]["queue"] == "ncdp-staging"
    assert "depends_on" not in staging
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
    assert protected["depends_on"] == "validation-complete"
    assert protected["if_changed"] == RUNTIME_CHANGE_CONDITION
    assert [step["key"] for step in protected["steps"]] == [
        "batfish-assurance",
        "promotion",
        "deployment-approval",
        "deploy-gate",
    ]
    batfish = steps["batfish-assurance"]
    assert batfish["agents"]["queue"] == "ncdp-validation"
    assert batfish["command"] == ".buildkite/scripts/batfish_assurance.sh"
    assert batfish["concurrency"] == 1
    assert batfish["concurrency_group"] == "ncdp/batfish-assurance"
    assert batfish["retry"] == {
        "automatic": False,
        "manual": {
            "allowed": False,
            "reason": "A fresh build is required for another assurance attempt.",
        },
    }
    assert "depends_on" not in batfish
    assert steps["promotion"]["agents"]["queue"] == "ncdp-validation"
    assert "concurrency" not in steps["promotion"]
    assert "concurrency_group" not in steps["promotion"]
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
    assert steps["promotion"]["depends_on"] == [
        "cml-staging",
        "batfish-assurance",
    ]
    assert steps["deployment-approval"]["depends_on"] == "promotion"
    assert steps["deploy-gate"]["depends_on"] == "deployment-approval"


def test_quality_image_normalizes_helper_access_after_final_copy() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text()
    quality = dockerfile.index("FROM application AS quality-base")
    final_copy = dockerfile.index("COPY . .", quality)
    access = dockerfile.index("chmod a+rx /app/scripts /app/infrastructure", final_copy)
    dev_sync = dockerfile.index("uv sync --frozen --all-groups", access)
    normalized = dockerfile[access:dev_sync]
    assert quality < final_copy < access < dev_sync
    assert "chmod -R a=rX" in normalized
    assert "/app/src" in normalized
    assert "/app/scripts/observability" in normalized
    assert "/app/infrastructure/observability" in normalized


def test_pr_and_main_conditions() -> None:
    pipeline = yaml.safe_load((ROOT / ".buildkite/pipeline.yml").read_text())
    steps = _steps_by_key(pipeline)
    protected = steps["protected-delivery"]
    assert 'build.branch == "main"' in protected["if"]
    assert "build.pull_request.id == null" in protected["if"]
    assert "if" not in steps["cml-staging"]
    for key in (
        "batfish-assurance",
        "promotion",
        "deployment-approval",
        "deploy-gate",
    ):
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
    for key in (
        "quality-snmp-generator",
        "quality-observability-11b",
        "quality-observability-11c2",
    ):
        assert "skip" in rendered_steps[key]
    assert "skip" not in rendered_steps["validation-complete"]
    for key in ("cml-staging", "protected-delivery"):
        assert ("skip" not in rendered_steps[key]) is live_path_expected


def test_installed_buildkite_change_evaluation_runs_applicable_checks_before_barrier(
    tmp_path: Path,
) -> None:
    agent = shutil.which("buildkite-agent")
    if agent is None:
        pytest.skip("Buildkite agent is not installed in this test environment")

    changed_files_path = tmp_path / "changed-files.txt"
    changed_files_path.write_text("infrastructure/observability/snmp/snmp.yml\n")
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
    for key in (
        "quality-snmp-generator",
        "quality-observability-11b",
        "quality-observability-11c2",
        "validation-complete",
        "cml-staging",
        "protected-delivery",
    ):
        assert "skip" not in rendered_steps[key]


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
    assert "scripts/buildkite/render_assurance_annotation.py" in dockerfile
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
    batfish = (ROOT / ".buildkite/scripts/batfish_assurance.sh").read_text()
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

    assert batfish.startswith("#!/usr/bin/env bash\nset -euo pipefail\n")
    assert "umask 077" in batfish
    assert batfish.index("verify_commit.sh") < batfish.index("assure-plan")
    assert "docker compose" in batfish
    assert "--project-name ncdp-batfish-assurance" in batfish
    assert 'NCDP_PROMOTION_IMAGE_TAG="$BUILDKITE_BUILD_NUMBER"' in batfish
    assert '"${compose[@]}" build promotion' in batfish
    assert '"${compose[@]}" up -d batfish' in batfish
    assert '"${compose[@]}" down' in batfish
    assert "trap cleanup EXIT" in batfish
    assert "cleanup_primary_status=$?" in batfish
    assert "trap - EXIT" in batfish
    assert 'exit "$cleanup_primary_status"' in batfish
    assert 'exit "$cleanup_status"' in batfish
    assert batfish.index('if ! "${compose[@]}" down') < batfish.index(
        'if ! rm -rf "$tmpdir"'
    )
    assert batfish.index('if ! rm -rf "$tmpdir"') < batfish.index(
        "cleanup_primary_status != 0"
    )
    assert "cleanup_status=3" in batfish
    assert "Compose teardown did not complete" in batfish
    assert "temporary directory removal did not complete" in batfish
    assert "ready_deadline=$((SECONDS + 60))" in batfish
    assert "scripts/buildkite/batfish_ready.py" in batfish
    assert batfish.count("deployments/live/promotion/plan.json") == 2
    assert batfish.count("deployments/live/promotion/policy.yaml") == 2
    assert batfish.count("deployments/live/promotion/baseline") == 2
    assert "ncdp assure-plan" in batfish
    assert "ncdp verify-assurance" in batfish
    assert batfish.index("ncdp assure-plan") < batfish.index("ncdp verify-assurance")
    assert 'evidence_relative="assurance/assurance.json"' in batfish
    assert 'buildkite-agent artifact upload "$evidence_relative"' in batfish
    assert "scripts/buildkite/render_assurance_annotation.py" in batfish
    assert "buildkite-agent annotate" in batfish
    assert "assurance_status=$?" in batfish
    assert 'exit "$assurance_status"' in batfish
    assert batfish.index("publish_evidence error") < batfish.index(
        'exit "$assurance_status"'
    )
    assert "ncdp promote" not in batfish
    assert "ncdp verify-promotion" not in batfish
    for forbidden in (
        "oidc request-token",
        "NCDP_OPENBAO",
        "NCDP_DEVICE",
        "NCDP_CML",
        "NETBOX",
        "AUDITSTORE",
        "OXIDIZED",
        "terraform",
        "ansible-playbook",
        "deployments/live/request.yaml",
        "fleet-deploy",
        "ncdp deploy",
        "deploy-buildkite-promotion",
        "deployment_gate.sh",
    ):
        assert forbidden not in batfish

    assert promotion.startswith("#!/usr/bin/env bash\nset -euo pipefail\n")
    assert "umask 077" in promotion
    assert "cleanup_primary_status=$?" in promotion
    assert "trap - EXIT" in promotion
    assert "trap cleanup EXIT" in promotion
    assert 'exit "$cleanup_primary_status"' in promotion
    assert 'exit "$cleanup_status"' in promotion
    assert promotion.index('if ! rm -rf "$tmpdir"') < promotion.index(
        "cleanup_primary_status != 0"
    )
    assert "cleanup_status=3" in promotion
    assert "temporary directory removal did not complete" in promotion
    assert "verify_commit.sh" in promotion
    assert promotion.index("verify_commit.sh") < promotion.index("artifact download")
    assert 'promotion="$tmpdir/promotion"' in promotion
    assert "uv run" not in promotion
    assert "docker compose" not in promotion
    assert "NCDP_BATFISH" not in promotion
    assert "batfish_ready.py" not in promotion
    assert "127.0.0.1:9996" not in promotion
    assert "ncdp assure-plan" not in promotion
    assert "scripts/buildkite/batfish_ready.py" not in promotion
    assert "docker build --target promotion" in promotion
    assert 'image="ncdp-promotion:$BUILDKITE_BUILD_NUMBER"' in promotion
    assert '"assurance/assurance.json" .' in promotion
    assert "--step batfish-assurance" in promotion
    assert '--build "$BUILDKITE_BUILD_ID"' in promotion
    empty_tree_check = "assert_artifact_tree_count 1"
    exact_tree_check = "assert_artifact_tree_count 3"
    assert promotion.count('[[ -d "$tmpdir" && ! -L "$tmpdir" ]]') == 2
    assert promotion.count(empty_tree_check) == 1
    assert promotion.count(exact_tree_check) == 1
    assert 'observed="$(find "$tmpdir" -print | wc -l' in promotion
    assert "Assurance artifact tree inspection failed" in promotion
    assert "Assurance artifact tree has an unexpected filesystem shape" in promotion
    assert promotion.index(empty_tree_check) < promotion.index("artifact download")
    assert promotion.index("artifact download") < promotion.index(exact_tree_check)
    assert promotion.index('[[ -d "$assurance_directory"') < promotion.index(
        exact_tree_check
    )
    assert promotion.index('[[ -f "$assurance"') < promotion.index(exact_tree_check)
    assert promotion.index(exact_tree_check) < promotion.index("ncdp verify-assurance")
    assert promotion.index("artifact download") < promotion.index(
        "ncdp verify-assurance"
    )
    assert promotion.index("ncdp verify-assurance") < promotion.index("ncdp promote")
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
