import sys
from pathlib import Path

import pytest

from network_change_delivery.buildkite_policy import compare_promoted_digests
from network_change_delivery.cli import main
from network_change_delivery.promotion import create_promotion_bundle

sys.path.insert(0, str(Path(__file__).parent))
from test_promotion import BASELINE, PLAN, POLICY, _record


def test_promoted_values_are_exact() -> None:
    values = ("sha256:" + "a" * 64, "sha256:" + "b" * 64, "sha256:" + "c" * 64)
    compare_promoted_digests(
        *values,
        promoted_plan=values[0],
        promoted_assurance=values[1],
        promoted_promotion=values[2],
    )
    for index in range(3):
        changed = list(values)
        changed[index] = " " + changed[index]
        with pytest.raises(ValueError):
            compare_promoted_digests(
                *values,
                promoted_plan=changed[0],
                promoted_assurance=changed[1],
                promoted_promotion=changed[2],
            )


@pytest.mark.parametrize("changed_option", [4, 6, 8])
def test_cli_gate_exact_and_wrong_promoted_values(
    tmp_path, monkeypatch, changed_option: int
) -> None:
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
        "--promoted-plan-digest",
        manifest.plan_digest,
        "--promoted-assurance-digest",
        manifest.assurance_record_digest,
        "--promoted-promotion-digest",
        manifest.digest,
    ]
    assert main(args) == 0
    args[changed_option] = " " + args[changed_option]
    with pytest.raises(SystemExit):
        main(args)


def test_promotion_digest_cli_verifies_before_returning_each_value(
    tmp_path, capsys
) -> None:
    assurance = tmp_path / "assurance.json"
    assurance.write_text(_record().model_dump_json(), encoding="utf-8")
    promotion = tmp_path / "promotion"
    manifest = create_promotion_bundle(
        PLAN, POLICY, BASELINE, assurance, "a" * 40, promotion
    )
    expected = {
        "plan": manifest.plan_digest,
        "assurance": manifest.assurance_record_digest,
        "promotion": manifest.digest,
    }
    for field, value in expected.items():
        assert (
            main(
                [
                    "promotion-digest",
                    "--promotion",
                    str(promotion),
                    "--git-commit",
                    "a" * 40,
                    "--field",
                    field,
                ]
            )
            == 0
        )
        assert capsys.readouterr().out == value + "\n"

    (promotion / "plan.json").write_text("{}", encoding="utf-8")
    with pytest.raises(SystemExit):
        main(
            [
                "promotion-digest",
                "--promotion",
                str(promotion),
                "--git-commit",
                "a" * 40,
                "--field",
                "plan",
            ]
        )
