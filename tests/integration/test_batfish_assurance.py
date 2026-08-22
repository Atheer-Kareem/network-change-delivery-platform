import json
import os
import shutil
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
    assert evidence["subject"]["plan_digest"] == (
        "sha256:02a3bece7cc1f67ae77e4f3cd436d1366489fa63fddf7b3b442f7115866086f4"
    )
    assert evidence["policy_digest"] == (
        "sha256:73abec7fbac0a8c986236c159415a94a9f7c88cc9a18236067f4736e35bcae91"
    )
    assert evidence["baseline_snapshot_digest"] == (
        "sha256:f05307ae50aea3fef4cedc8c883937b849671d8b3cc4916b10204c42f270f258"
    )
    assert evidence["subject"]["plan_type"] == "fleet_deployment_plan"
    assert evidence["policy_digest"].startswith("sha256:")
    assert (
        evidence["candidate_snapshot_digest"]
        == "sha256:38809e5c4169676edb2adb0859cf21cc1401b09788fd9c446730247af1497808"
    )
    assert len(evidence["candidate_derivation"]) == 3
    assert [
        (m["target"], m["interface"], m["classification"], m["changed"])
        for m in evidence["candidate_derivation"]
    ] == [
        ("core-02", "GigabitEthernet1", "DEPLOYABLE", True),
        ("edge-junos-01", "ge-0/0/0", "DEPLOYABLE", True),
        ("core-03", "GigabitEthernet1", "DEPLOYABLE", True),
    ]
    assert evidence["assurance"]["baseline_parse"]["nodes"] == [
        "core-02",
        "core-03",
        "edge-junos-01",
    ]
    assert all(i["passed"] for i in evidence["assurance"]["invariants"])
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

    # All negative checks are offline verifier calls; no provider is constructed.
    plan_payload = json.loads(PLAN.read_text(encoding="utf-8"))
    plan_payload["created_at"] = "2026-08-22T00:00:00Z"
    from network_change_delivery.models import FleetDeploymentPlan

    changed_plan = FleetDeploymentPlan.model_validate(plan_payload)
    plan_payload["digest"] = changed_plan.calculated_digest()
    wrong_plan = tmp_path / "wrong-plan.json"
    wrong_plan.write_text(json.dumps(plan_payload), encoding="utf-8")
    modified_policy = tmp_path / "modified-policy.yaml"
    modified_policy.write_text(
        POLICY.read_text(encoding="utf-8").replace(
            "require_no_differential_reachability: true",
            "require_no_differential_reachability: false",
        ),
        encoding="utf-8",
    )
    changed_baseline = tmp_path / "changed-baseline"
    shutil.copytree(BASELINE, changed_baseline)
    (changed_baseline / "configs/core-02.cfg").write_text(
        (changed_baseline / "configs/core-02.cfg").read_text() + "\n",
        encoding="utf-8",
    )
    for plan_arg, policy_arg, baseline_arg in [
        (wrong_plan, POLICY, BASELINE),
        (PLAN, modified_policy, BASELINE),
        (PLAN, POLICY, changed_baseline),
    ]:
        rejected = subprocess.run(
            [
                sys.executable,
                "-m",
                "network_change_delivery",
                "verify-assurance",
                "--plan",
                str(plan_arg),
                "--policy",
                str(policy_arg),
                "--baseline",
                str(baseline_arg),
                "--evidence",
                str(report),
            ],
            cwd=ROOT,
            env=os.environ.copy(),
            text=True,
            capture_output=True,
            check=False,
        )
        assert rejected.returncode == 2
