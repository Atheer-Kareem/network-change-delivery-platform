import pytest

from network_change_delivery.buildkite_policy import (
    BuildkiteDeploymentContext,
    compare_approved_digests,
)


def context(**changes):
    values = {
        "commit": "a" * 40,
        "branch": "main",
        "pipeline_id": "p",
        "build_id": "b",
        "build_number": "1",
        "job_id": "j",
        "step_key": "deploy-gate",
        "queue_key": "ncdp-deploy",
    }
    values.update(changes)
    return values


def test_context_contract() -> None:
    assert BuildkiteDeploymentContext.model_validate(context()).commit == "a" * 40
    with pytest.raises(ValueError):
        BuildkiteDeploymentContext.model_validate(context(branch="feature"))
    with pytest.raises(ValueError):
        BuildkiteDeploymentContext.model_validate(context(queue_key="ncdp-validation"))


def test_approval_digest_match_is_exact() -> None:
    compare_approved_digests(
        "p", "a", "x", approved_plan="p", approved_assurance="a", approved_promotion="x"
    )
    with pytest.raises(ValueError):
        compare_approved_digests(
            "p ",
            "a",
            "x",
            approved_plan="p",
            approved_assurance="a",
            approved_promotion="x",
        )
