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
    assert steps["quality"]["agents"]["queue"] == "ncdp-validation"
    assert steps["pipeline-contract"]["agents"]["queue"] == "ncdp-validation"
    assert steps["promotion"]["agents"]["queue"] == "ncdp-validation"
    assert steps["promotion"]["concurrency"] == 1
    assert steps["promotion"]["concurrency_group"] == "ncdp/batfish-promotion"
    assert steps["deploy-gate"]["agents"]["queue"] == "ncdp-deploy"
    assert steps["deploy-gate"]["concurrency"] == 1
    assert steps["deploy-gate"]["concurrency_group"] == "ncdp/network-change-deployment"
    assert {field["key"] for field in steps["deployment-approval"]["fields"]} == {
        "approved-plan-digest",
        "approved-assurance-digest",
        "approved-promotion-digest",
    }
    assert all(
        field["format"] == "sha256:[0-9a-f]{64}"
        for field in steps["deployment-approval"]["fields"]
    )
    assert steps["promotion"]["depends_on"] == ["quality", "pipeline-contract"]
    assert steps["deployment-approval"]["depends_on"] == "promotion"
    assert steps["deploy-gate"]["depends_on"] == "deployment-approval"
    quality = "\n".join(steps["quality"]["commands"])
    assert quality.count("git --no-pager diff --check") == 2
    assert "git diff --check" not in quality

    assert len(steps["pipeline-contract"]["commands"]) == 1
    contract = " ".join(steps["pipeline-contract"]["commands"])
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


def test_scripts_static_contract() -> None:
    gate = (ROOT / "scripts/buildkite/deployment_gate.sh").read_text()
    promotion = (ROOT / ".buildkite/scripts/promotion.sh").read_text()
    assert 'meta-data get "approved-plan-digest"' in gate
    assert 'meta-data get "approved-assurance-digest"' in gate
    assert 'meta-data get "approved-promotion-digest"' in gate
    assert "BUILDKITE_APPROVED_" not in gate
    assert "--step promotion" in gate
    assert "uv run ncdp verify-buildkite-gate" in gate
    assert "verify_commit.sh" in promotion
    assert promotion.index("verify_commit.sh") < promotion.index("assure-plan")
    assert 'promotion="$tmpdir/promotion"' in promotion
