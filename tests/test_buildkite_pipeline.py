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
    graph = yaml.safe_load(PIPELINE.read_text())["steps"]
    return [child for step in graph for child in step.get("steps", [step])]


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


NON_RUNTIME = [
    "docs/**",
    "README.md",
    "AGENTS.md",
    ".github/CODEOWNERS",
    ".github/pull_request_template.md",
    "tests/**",
    ".gitignore",
]
RUNTIME_VALIDATIONS = {
    "quality-terraform-profiled-staging",
    "quality-snmp-generator",
    "quality-observability-runtime",
    "quality-snmpv3-synthetic",
}
RUNTIME_JOBS = RUNTIME_VALIDATIONS | {"pr-batfish-assurance", "cml-staging", *MAIN_KEYS}


def test_shared_runtime_boundary_and_receipt_closure():
    top = yaml.safe_load(PIPELINE.read_text())["steps"]
    group = top[-1]
    assert group["key"] == "runtime-delivery"
    assert [s["key"] for s in group["steps"]] == list(MAIN_KEYS)
    assert set(group) == {"group", "key", "if_changed", "steps"}
    gate = group["if_changed"]
    assert gate == {"include": "**", "exclude": NON_RUNTIME}
    for step in top[:-1]:
        if step["key"] in RUNTIME_JOBS:
            # YAML aliases bind one condition, rather than independent component gates.
            assert step["if_changed"] is gate
        else:
            assert "if_changed" not in step
            assert "if" not in step
        assert "skip" not in step
    for step in group["steps"]:
        assert (
            "if_changed" not in step
        )  # A bare block does not evaluate this attribute.
        assert "skip" not in step
    assert set(VALIDATION_KEYS) - RUNTIME_VALIDATIONS == {
        "quality-env",
        "quality-committed-diff",
        "quality-ruff-lint",
        "quality-ruff-format",
        "quality-pytest",
        "quality-ansible-lint",
        "quality-package-build",
        "buildkite-definition",
        "ncdp-pipeline-contract",
    }


def parsed_steps(graph, inherited_skip=False):
    """Expose effective group scheduling, including a skipped human block."""
    for step in graph:
        skipped = inherited_skip or bool(step.get("skip"))
        if "steps" in step:
            yield from parsed_steps(step["steps"], skipped)
        else:
            yield step["key"], skipped


def agent_evaluation(tmp_path, *options):
    agent = shutil.which("buildkite-agent")
    if agent is None:
        pytest.skip("Buildkite agent is not installed")
    # Use local dry-run inputs only; never inherit a running job's diff/agent settings.
    environment = {
        k: v for k, v in os.environ.items() if not k.startswith("BUILDKITE_")
    }
    environment["BUILDKITE_AGENT_ACCESS_TOKEN"] = "local-dry-run"
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
            *options,
        ],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return dict(parsed_steps(yaml.safe_load(result.stdout)["steps"])), result.stderr


def assert_scheduling(skipped, runtime):
    assert set(skipped) == {s["key"] for s in steps()}
    assert {key for key, value in skipped.items() if value} == (
        set() if runtime else RUNTIME_JOBS
    )
    # Whenever promotion is eligible, every required receipt producer is eligible.
    if not skipped["profiled-promotion"]:
        assert all(not skipped[key] for key in VALIDATION_KEYS)
    else:
        assert all(skipped[key] for key in MAIN_KEYS)


@pytest.mark.parametrize(
    ("paths", "runtime"),
    [
        (["docs/roadmap.md"], False),
        (["docs/nested/foo.md"], False),
        (["tests/test_something.py"], False),
        (["README.md", "AGENTS.md", ".gitignore"], False),
        ([".github/CODEOWNERS"], False),
        ([".github/pull_request_template.md"], False),
        (["docs/foo.md", "src/network_change_delivery/foo.py"], True),
        (["src/network_change_delivery/foo.py"], True),
        (["scripts/foo.py"], True),
        (["infrastructure/foo.tf"], True),
        (["ansible/foo.yml"], True),
        (["deployments/live/profiled-demo.yaml"], True),
        ([".buildkite/pipeline.yml"], True),
        ([".github/workflows/foo.yml"], True),
        ([".github/CODEOWNERS.extra"], True),
        (["unknown/new-file"], True),
        (["new-root-file"], True),
    ],
)
def test_installed_buildkite_change_evaluation_paths(tmp_path, paths, runtime):
    changed = tmp_path / "changes"
    changed.write_text("\n".join(paths) + "\n")
    skipped, _ = agent_evaluation(tmp_path, "--changed-files-path", str(changed))
    assert_scheduling(skipped, runtime)


def test_installed_buildkite_change_evaluation_unavailable(tmp_path):
    # No Git repository: the real agent must disable filtering, not guess docs-only.
    skipped, diagnostics = agent_evaluation(tmp_path, "--fetch-diff-base")
    assert_scheduling(skipped, True)
    assert "if_changed" in diagnostics


@pytest.mark.parametrize("mode", ["pr", "main", "unavailable-ref"])
@pytest.mark.parametrize("runtime", [False, True])
def test_installed_buildkite_change_evaluation_fetch_diff_base(tmp_path, mode, runtime):
    if shutil.which("buildkite-agent") is None:
        pytest.skip("Buildkite agent is not installed; evaluated on the host gate")
    environment = {
        **os.environ,
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
    }

    def git(*args):
        result = subprocess.run(
            ["git", "-c", "core.hooksPath=/dev/null", *args],
            cwd=tmp_path,
            env=environment,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()

    # Fully local remote: no provider, Buildkite build, or live infrastructure access.
    remote = tmp_path / "remote.git"
    git("init", "--bare", str(remote))
    git("init", "-b", "main")
    git("config", "user.name", "Fixture")
    git("config", "user.email", "fixture@example.invalid")
    git("commit", "--allow-empty", "-m", "base")
    git("remote", "add", "origin", str(remote))
    git("push", "origin", "main")
    if mode == "pr":
        git("switch", "-c", "fixture-pr")
    changed = tmp_path / ("src/example.py" if runtime else "docs/example.md")
    changed.parent.mkdir(exist_ok=True)
    changed.write_text("fixture\n")
    git("add", str(changed.relative_to(tmp_path)))
    git("commit", "-m", "change")
    if mode == "main":
        # Local origin/main remains behind until upload fetches it. HEAD==base
        # then exercises the agent's main-merge parent comparison.
        git("push", "origin", "main")
        git("update-ref", "refs/remotes/origin/main", "HEAD^")
    base = "origin/nonexistent" if mode == "unavailable-ref" else "origin/main"
    skipped, _ = agent_evaluation(
        tmp_path, "--fetch-diff-base", "--git-diff-base", base
    )
    assert_scheduling(skipped, runtime or mode == "unavailable-ref")
    if mode == "main":
        assert git("rev-parse", "origin/main") == git("rev-parse", "HEAD")
