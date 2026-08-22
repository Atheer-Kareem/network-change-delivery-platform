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
    assert evidence["differential_changed_flow_count"] == 0
    assert len(evidence["baseline_parse"]["files"]) == 3
    assert len(evidence["candidate_parse"]["files"]) == 3
    assert evidence["pybatfish_version"] == "2025.7.7.2423"
    assert evidence["batfish_version"] == "2026.07.20.3565"
    assert report.stat().st_mode & 0o777 == 0o600


def test_disruptive_candidate(tmp_path: Path) -> None:
    completed, evidence, report = _run("disruptive", tmp_path)
    assert completed.returncode == 2
    assert evidence["outcome"] == "FAILED"
    assert evidence["differential_changed_flow_count"] > 0
    assert report.stat().st_mode & 0o777 == 0o600
