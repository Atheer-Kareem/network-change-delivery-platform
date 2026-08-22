from pathlib import Path

import pytest

from network_change_delivery import cli

ROOT = Path(__file__).parents[1]
PLAN = ROOT / "fixtures/batfish/plans/fleet-interface-description.json"
POLICY = ROOT / "fixtures/batfish/policy.yaml"
BASELINE = ROOT / "fixtures/batfish/baseline"


def test_assure_plan_parser_has_no_candidate() -> None:
    parser = cli.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["assure-plan", "--candidate", "x"])


def test_invalid_plan_leaves_no_report(tmp_path: Path) -> None:
    invalid = tmp_path / "invalid.json"
    invalid.write_text("{}", encoding="utf-8")
    report = tmp_path / "report.json"
    with pytest.raises(SystemExit):
        cli.main(
            [
                "assure-plan",
                "--plan",
                str(invalid),
                "--policy",
                str(POLICY),
                "--baseline",
                str(BASELINE),
                "--report-json",
                str(report),
                "--batfish",
            ]
        )
    assert not report.exists()


def test_existing_report_rejected_before_preparation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = tmp_path / "report.json"
    report.write_text("sentinel", encoding="utf-8")
    called = False

    def prepare(_path: Path):
        nonlocal called
        called = True
        raise AssertionError("baseline should not be prepared")

    monkeypatch.setattr(cli, "prepare_snapshot", prepare)
    with pytest.raises(SystemExit):
        cli.main(
            [
                "assure-plan",
                "--plan",
                str(PLAN),
                "--policy",
                str(POLICY),
                "--baseline",
                str(BASELINE),
                "--report-json",
                str(report),
                "--batfish",
            ]
        )
    assert not called


def test_one_prepared_baseline_is_passed_to_engine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = tmp_path / "report.json"
    calls = []
    original = cli.assure_prepared_plan

    def wrapped(plan, policy, prepared, provider=None):
        calls.append(prepared.root)
        return original(plan, policy, prepared, provider)

    monkeypatch.setattr(cli, "assure_prepared_plan", wrapped)
    # Provider contact is expected to block in this unit test, but the same
    # prepared baseline must still reach the orchestration engine exactly once.
    assert (
        cli.main(
            [
                "assure-plan",
                "--plan",
                str(PLAN),
                "--policy",
                str(POLICY),
                "--baseline",
                str(BASELINE),
                "--report-json",
                str(report),
                "--batfish",
            ]
        )
        == 2
    )
    assert len(calls) == 1
    assert report.stat().st_mode & 0o777 == 0o600
