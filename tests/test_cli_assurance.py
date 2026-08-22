from pathlib import Path

import pytest
import yaml

from network_change_delivery import cli
from network_change_delivery.assurance import (
    AssuranceObservation,
    AssuranceProviderError,
    BatfishAssuranceIntent,
    FlowResult,
    ParseFileResult,
    ParseSummary,
)


def _inputs(tmp_path: Path) -> tuple[Path, Path, Path]:
    for name in ("baseline", "candidate"):
        configs = tmp_path / name / "configs"
        configs.mkdir(parents=True)
        (configs / "node.cfg").write_text("hostname node\n", encoding="utf-8")
    intent = tmp_path / "intent.yaml"
    intent.write_text(
        yaml.safe_dump(
            {
                "subject_digest": "sha256:" + "1" * 64,
                "expected_nodes": ["core-02"],
                "critical_flows": [
                    {
                        "source_node": "core-02",
                        "source_ip": "10.0.0.1",
                        "destination_ip": "10.0.0.2",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return intent, tmp_path / "baseline", tmp_path / "candidate"


def _observation() -> AssuranceObservation:
    parse = ParseSummary(
        files=(ParseFileResult(relative_path="node.cfg", status="PASSED"),),
        nodes=("core-02",),
        initialization_issue_count=0,
    )
    return AssuranceObservation(
        pybatfish_version="2025.7.7.2423",
        batfish_version="2026.07.20.3565",
        baseline=parse,
        candidate=parse,
        flows=(
            FlowResult(
                source_node="core-02",
                source_ip="10.0.0.1",
                destination_ip="10.0.0.2",
                baseline_reachable=True,
                candidate_reachable=True,
            ),
        ),
        differential_changed_flow_count=0,
    )


def _invoke(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, outcome: str = "pass"
) -> tuple[int, Path]:
    intent, baseline, candidate = _inputs(tmp_path)
    report = tmp_path / "report.json"

    class FakeProvider:
        def __init__(self) -> None:
            self.called = True

        def analyze(
            self, _baseline: Path, _candidate: Path, _intent: BatfishAssuranceIntent
        ):
            if outcome == "blocked":
                raise AssuranceProviderError("bounded provider unavailable")
            observation = _observation()
            if outcome == "failed":
                observation = observation.model_copy(
                    update={"differential_changed_flow_count": 1}
                )
            return observation

    monkeypatch.setattr(cli, "BatfishAssuranceAdapter", FakeProvider)
    code = cli.main(
        [
            "assure",
            "--intent",
            str(intent),
            "--baseline",
            str(baseline),
            "--candidate",
            str(candidate),
            "--report-json",
            str(report),
            "--batfish",
        ]
    )
    return code, report


def test_cli_pass_failed_blocked_and_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    code, report = _invoke(tmp_path / "pass", monkeypatch)
    assert code == 0 and report.stat().st_mode & 0o777 == 0o600
    code, report = _invoke(tmp_path / "failed", monkeypatch, "failed")
    assert code == 2 and '"outcome": "FAILED"' in report.read_text()
    code, report = _invoke(tmp_path / "blocked", monkeypatch, "blocked")
    assert code == 2 and '"outcome": "BLOCKED"' in report.read_text()


def test_cli_existing_and_symlink_reject_before_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    intent, baseline, candidate = _inputs(tmp_path)
    existing = tmp_path / "existing.json"
    existing.write_text("sentinel", encoding="utf-8")
    called = False

    class NeverProvider:
        def __init__(self) -> None:
            nonlocal called
            called = True

    monkeypatch.setattr(cli, "BatfishAssuranceAdapter", NeverProvider)
    with pytest.raises(SystemExit):
        cli.main(
            [
                "assure",
                "--intent",
                str(intent),
                "--baseline",
                str(baseline),
                "--candidate",
                str(candidate),
                "--report-json",
                str(existing),
                "--batfish",
            ]
        )
    assert not called
    link = tmp_path / "link.json"
    link.symlink_to(existing)
    with pytest.raises(SystemExit):
        cli.main(
            [
                "assure",
                "--intent",
                str(intent),
                "--baseline",
                str(baseline),
                "--candidate",
                str(candidate),
                "--report-json",
                str(link),
                "--batfish",
            ]
        )
    assert not called


def test_cli_invalid_input_leaves_no_evidence(tmp_path: Path) -> None:
    report = tmp_path / "invalid.json"
    bad = tmp_path / "bad.yaml"
    bad.write_text("bad: [", encoding="utf-8")
    with pytest.raises(SystemExit):
        cli.main(
            [
                "assure",
                "--intent",
                str(bad),
                "--baseline",
                str(tmp_path),
                "--candidate",
                str(tmp_path),
                "--report-json",
                str(report),
                "--batfish",
            ]
        )
    assert not report.exists()
