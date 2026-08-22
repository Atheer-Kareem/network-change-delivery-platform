import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.batfish_integration

ROOT = Path(__file__).parents[2]
INTENT = ROOT / "fixtures/batfish/intent.yaml"
BASELINE = ROOT / "fixtures/batfish/baseline"
PLAN = ROOT / "fixtures/batfish/plans/fleet-interface-description.json"
POLICY = ROOT / "fixtures/batfish/policy.yaml"


def _run(
    candidate: str, tmp_path: Path
) -> tuple[subprocess.CompletedProcess[str], dict, Path]:
    report = tmp_path / f"{candidate}.json"
    env = os.environ.copy()
    if env.get("NCDP_BATFISH_INTEGRATION") != "1":
        pytest.skip("set NCDP_BATFISH_INTEGRATION=1 to run local Batfish acceptance")
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "network_change_delivery",
            "assure",
            "--intent",
            str(INTENT),
            "--baseline",
            str(BASELINE),
            "--candidate",
            str(ROOT / "fixtures/batfish" / candidate),
            "--report-json",
            str(report),
            "--batfish",
        ],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    return completed, json.loads(report.read_text(encoding="utf-8")), report


def test_good_candidate(tmp_path: Path) -> None:
    # The service is started externally by the acceptance workflow.
    completed, evidence, report = _run("candidate", tmp_path)
    assert completed.returncode == 0
    assert evidence["outcome"] == "PASSED"
    expected_files = {"core-02.cfg", "core-03.cfg", "edge-junos-01.cfg"}
    for summary in (evidence["baseline_parse"], evidence["candidate_parse"]):
        assert {item["relative_path"] for item in summary["files"]} == expected_files
        assert all(item["status"] == "PASSED" for item in summary["files"])
        assert set(summary["nodes"]) == {"core-02", "core-03", "edge-junos-01"}
        assert summary["initialization_issue_count"] == 0
    assert len(evidence["critical_flows"]) == 1
    assert evidence["critical_flows"][0]["baseline_reachable"] is True
    assert evidence["critical_flows"][0]["candidate_reachable"] is True
    assert evidence["differential_changed_flow_count"] == 0
    assert evidence["pybatfish_version"] == "2025.7.7.2423"
    assert evidence["batfish_version"] == "2026.07.20.3565"
    assert report.stat().st_mode & 0o777 == 0o600


def test_disruptive_candidate(tmp_path: Path) -> None:
    completed, evidence, report = _run("disruptive", tmp_path)
    assert completed.returncode == 2
    assert evidence["outcome"] == "FAILED"
    expected_files = {"core-02.cfg", "core-03.cfg", "edge-junos-01.cfg"}
    for summary in (evidence["baseline_parse"], evidence["candidate_parse"]):
        assert {item["relative_path"] for item in summary["files"]} == expected_files
        assert all(item["status"] == "PASSED" for item in summary["files"])
        assert set(summary["nodes"]) == {"core-02", "core-03", "edge-junos-01"}
        assert summary["initialization_issue_count"] == 0
    assert evidence["critical_flows"][0]["baseline_reachable"] is True
    assert evidence["critical_flows"][0]["candidate_reachable"] is False
    assert evidence["differential_changed_flow_count"] > 0
    assert report.stat().st_mode & 0o777 == 0o600


def test_plan_bound_candidate_and_verifier(tmp_path: Path) -> None:
    if os.environ.get("NCDP_BATFISH_INTEGRATION") != "1":
        pytest.skip("set NCDP_BATFISH_INTEGRATION=1 to run local Batfish acceptance")
    report = tmp_path / "plan-assurance.json"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "network_change_delivery",
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
        ],
        cwd=ROOT,
        env=os.environ.copy(),
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    evidence = json.loads(report.read_text(encoding="utf-8"))
    assert evidence["outcome"] == "PASSED"
    assert evidence["subject"]["plan_type"] == "fleet_deployment_plan"
    assert evidence["policy_digest"].startswith("sha256:")
    assert (
        evidence["candidate_snapshot_digest"]
        == "sha256:38809e5c4169676edb2adb0859cf21cc1401b09788fd9c446730247af1497808"
    )
    assert len(evidence["candidate_derivation"]) == 3
    assert evidence["assurance"]["differential_changed_flow_count"] == 0
    assert report.stat().st_mode & 0o777 == 0o600
    verified = subprocess.run(
        [
            sys.executable,
            "-m",
            "network_change_delivery",
            "verify-assurance",
            "--plan",
            str(PLAN),
            "--policy",
            str(POLICY),
            "--baseline",
            str(BASELINE),
            "--evidence",
            str(report),
        ],
        cwd=ROOT,
        env=os.environ.copy(),
        text=True,
        capture_output=True,
        check=False,
    )
    assert verified.returncode == 0
