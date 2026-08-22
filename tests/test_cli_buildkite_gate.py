import sys
from pathlib import Path

import pytest

from network_change_delivery.buildkite_policy import compare_approved_digests
from network_change_delivery.cli import main
from network_change_delivery.promotion import create_promotion_bundle

sys.path.insert(0, str(Path(__file__).parent))
from test_promotion import BASELINE, PLAN, POLICY, _record


def test_approval_values_are_exact() -> None:
    values = ("sha256:" + "a" * 64, "sha256:" + "b" * 64, "sha256:" + "c" * 64)
    compare_approved_digests(
        *values,
        approved_plan=values[0],
        approved_assurance=values[1],
        approved_promotion=values[2],
    )
    for index in range(3):
        changed = list(values)
        changed[index] = " " + changed[index]
        with pytest.raises(ValueError):
            compare_approved_digests(
                *values,
                approved_plan=changed[0],
                approved_assurance=changed[1],
                approved_promotion=changed[2],
            )


def test_cli_gate_exact_and_wrong_approvals(tmp_path, monkeypatch) -> None:
    assurance = tmp_path / "assurance.json"
    assurance.write_text(_record().model_dump_json(), encoding="utf-8")
    promotion = tmp_path / "promotion"
    manifest = create_promotion_bundle(
        PLAN, POLICY, BASELINE, assurance, "a" * 40, promotion
    )
    monkeypatch.setenv("BUILDKITE_COMMIT", "a" * 40)
    monkeypatch.setenv("BUILDKITE_BRANCH", "main")
    monkeypatch.setenv("BUILDKITE_PULL_REQUEST", "")
    monkeypatch.setenv("BUILDKITE_PIPELINE_ID", "pipeline")
    monkeypatch.setenv("BUILDKITE_BUILD_ID", "build")
    monkeypatch.setenv("BUILDKITE_BUILD_NUMBER", "1")
    monkeypatch.setenv("BUILDKITE_JOB_ID", "job")
    monkeypatch.setenv("BUILDKITE_STEP_KEY", "deploy-gate")
    monkeypatch.setenv("BUILDKITE_AGENT_META_DATA_QUEUE", "ncdp-deploy")
    args = [
        "verify-buildkite-gate",
        "--promotion",
        str(promotion),
        "--approved-plan-digest",
        manifest.plan_digest,
        "--approved-assurance-digest",
        manifest.assurance_record_digest,
        "--approved-promotion-digest",
        manifest.digest,
    ]
    assert main(args) == 0
    args[-1] = " " + manifest.digest
    with pytest.raises(SystemExit):
        main(args)
