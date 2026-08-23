from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]


def test_pipeline_contract() -> None:
    pipeline = yaml.safe_load((ROOT / ".buildkite/pipeline.yml").read_text())
    steps = {step["key"]: step for step in pipeline["steps"]}
    assert set(steps) == {
        "quality",
        "pipeline-contract",
        "promotion",
        "deployment-approval",
        "deploy-gate",
    }
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

    committed_diff = quality_steps["quality-committed-diff"]["command"]
    assert committed_diff.count("git --no-pager diff --check") == 2
    assert "git diff --check" not in committed_diff
    assert committed_diff.count("$${BUILDKITE_PULL_REQUEST") == 3
    assert "${BUILDKITE_PULL_REQUEST" not in committed_diff.replace(
        "$${BUILDKITE_PULL_REQUEST", ""
    )

    assert steps["pipeline-contract"]["agents"]["queue"] == "ncdp-validation"
    assert steps["promotion"]["agents"]["queue"] == "ncdp-validation"
    assert steps["promotion"]["concurrency"] == 1
    assert steps["promotion"]["concurrency_group"] == "ncdp/batfish-promotion"
    assert steps["deploy-gate"]["agents"]["queue"] == "ncdp-deploy"
    assert steps["deploy-gate"]["concurrency"] == 1
    assert steps["deploy-gate"]["concurrency_group"] == "ncdp/network-change-deployment"
    approval = steps["deployment-approval"]
    assert approval["block"] == ":lock: Authorize exact promotion"
    assert approval["prompt"] == (
        "Authorize the exact immutable promotion verified and recorded by the "
        "promotion step."
    )
    assert approval["submit"] == "Authorize exact promotion"
    assert "fields" not in approval
    assert steps["promotion"]["depends_on"] == ["quality", "pipeline-contract"]
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
    steps = {step["key"]: step for step in pipeline["steps"]}
    for key in ("promotion", "deployment-approval", "deploy-gate"):
        assert 'build.branch == "main"' in steps[key]["if"]
        assert "build.pull_request.id == null" in steps[key]["if"]


def test_promotion_container_contract() -> None:
    compose = yaml.safe_load((ROOT / "compose.assurance.yaml").read_text())
    promotion = compose["services"]["promotion"]
    assert promotion["image"] == "ncdp-promotion:${NCDP_PROMOTION_IMAGE_TAG:-local}"
    assert promotion["build"] == {"context": ".", "target": "promotion"}
    assert promotion["environment"] == {"NCDP_BATFISH_HOST": "batfish"}

    dockerfile = (ROOT / "Dockerfile").read_text()
    assert "FROM application AS promotion" in dockerfile
    assert "COPY fixtures/batfish ./fixtures/batfish" in dockerfile
    assert "COPY . ." not in dockerfile.split("FROM application AS promotion", 1)[1]
    assert "RUN chmod -R a=rX" in dockerfile
    for path in (
        "/app/.venv",
        "/app/src",
        "/app/fixtures/batfish",
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
    assert gate.index("verify_commit.sh") < gate.index("oidc request-token")
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
    assert "uv run ncdp verify-buildkite-gate" in gate
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
        "deploy-buildkite-promotion"
    )
    assert 'request_status" -eq 3' in gate
    assert "live deployment requested: NO" not in gate
    assert gate.count("device write executed: YES") == 1
    assert "set +e" in gate
    assert "deployment_status=$?" in gate
    assert 'exit "$deployment_status"' in gate
    assert "inspect the uploaded typed ChangeRecord evidence" in gate
    assert gate.index("artifact upload") < gate.index('exit "$deployment_status"')
    assert 'cd "$tmpdir"' in gate
    assert 'buildkite-agent artifact upload "$report_relative"' in gate
    assert "deployments/live/request.yaml" not in gate
    assert not (ROOT / "deployments/live/request.yaml").exists()
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
