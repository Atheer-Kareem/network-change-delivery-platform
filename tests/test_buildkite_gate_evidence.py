"""Execution-level tests for Buildkite deployment evidence orchestration."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
GATE = ROOT / "scripts/buildkite/deployment_gate.sh"


def executable(path: Path, contents: str) -> None:
    path.write_text(contents, encoding="utf-8")
    path.chmod(0o755)


def run_gate(
    tmp_path: Path,
    *,
    deployment_status: int,
    evidence: bool,
    outcome: str,
    upload_status: int = 0,
    live_request: bool = True,
    runtime_status: int = 0,
    audit_status: int = 0,
    audit_root: bool = True,
    retry_count: str | None = "0",
) -> tuple[subprocess.CompletedProcess[str], Path]:
    (tmp_path / "scripts/buildkite").mkdir(parents=True)
    executable(tmp_path / "scripts/buildkite/verify_commit.sh", "#!/bin/sh\nexit 0\n")
    binaries = tmp_path / "bin"
    binaries.mkdir()
    upload_log = tmp_path / "uploads"
    command_log = tmp_path / "commands"
    executable(
        binaries / "buildkite-agent",
        """#!/usr/bin/env bash
set -eu
case "$1 $2" in
  "oidc request-token")
    printf '%s\\n' oidc >> "$COMMAND_LOG"
    printf '%s\\n' 'bounded-jwt'
    ;;
  "artifact download")
    if [[ "$3" == "promotion/**" ]]; then
      mkdir -p "$4/promotion"; : > "$4/promotion/manifest.json"
    else
      mkdir -p "$4/staging-evidence"; : > "$4/staging-evidence/staging-run.json"
    fi
    ;;
  "artifact upload") printf '%s\\n' "$3" >> "$UPLOAD_LOG"; exit "$UPLOAD_STATUS" ;;
  "meta-data get")
    printf 'sha256:'
    printf 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
    printf 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\\n'
    ;;
  *) exit 90 ;;
esac
""",
    )
    executable(
        binaries / "uv",
        """#!/usr/bin/env bash
set -eu
command="$3"
subcommand="${4:-}"
if [[ "$command" == audit ]]; then
  printf 'audit:%s\\n' "$subcommand" >> "$COMMAND_LOG"
else
  printf '%s\\n' "$command" >> "$COMMAND_LOG"
fi
case "$command" in
  audit)
    case "$subcommand" in
      verify-buildkite) [[ -n "${NCDP_AUDIT_STORE_ROOT:-}" ]] ;;
      persist-buildkite) exit "$AUDIT_STATUS" ;;
      *) exit 92 ;;
    esac
    ;;
  verify-buildkite-openbao-identity) read -r jwt; [[ "$jwt" == bounded-jwt ]] ;;
  verify-buildkite-gate|verify-buildkite-live-request) exit 0 ;;
  verify-deployment-ansible-runtime) exit "$RUNTIME_STATUS" ;;
  buildkite-live-request-status)
    if [[ "$LIVE_REQUEST" == 1 ]]; then exit 0; fi
    printf '%s\\n' 'live deployment requested: NO' 'device write executed: NO'
    exit 3
    ;;
  deploy-buildkite-promotion)
    read -r jwt
    [[ "$jwt" == bounded-jwt ]]
    report=''
    while [[ $# -gt 0 ]]; do
      if [[ "$1" == --report-json ]]; then report="$2"; break; fi
      shift
    done
    if [[ "$CREATE_EVIDENCE" == 1 ]]; then
      mkdir -p "$(dirname "$report")"
      printf '{"final_outcome":"%s"}\\n' "$DEPLOY_OUTCOME" > "$report"
      chmod 600 "$report"
    fi
    exit "$DEPLOY_STATUS"
    ;;
  *) exit 91 ;;
esac
""",
    )
    environment = {
        **os.environ,
        "PATH": f"{binaries}:{os.environ['PATH']}",
        "BUILDKITE_STEP_KEY": "deploy-gate",
        "BUILDKITE_AGENT_META_DATA_QUEUE": "ncdp-deploy",
        "UPLOAD_LOG": str(upload_log),
        "COMMAND_LOG": str(command_log),
        "UPLOAD_STATUS": str(upload_status),
        "DEPLOY_STATUS": str(deployment_status),
        "DEPLOY_OUTCOME": outcome,
        "CREATE_EVIDENCE": "1" if evidence else "0",
        "LIVE_REQUEST": "1" if live_request else "0",
        "RUNTIME_STATUS": str(runtime_status),
        "AUDIT_STATUS": str(audit_status),
    }
    if audit_root:
        environment["NCDP_AUDIT_STORE_ROOT"] = str(tmp_path / "audit")
    else:
        environment.pop("NCDP_AUDIT_STORE_ROOT", None)
    if retry_count is None:
        environment.pop("BUILDKITE_RETRY_COUNT", None)
    else:
        environment["BUILDKITE_RETRY_COUNT"] = retry_count
    for prohibited in (
        "NCDP_OPENBAO_ROLE_ID",
        "NCDP_OPENBAO_SECRET_ID",
        "NCDP_DEVICE_USERNAME",
        "NCDP_DEVICE_PASSWORD",
    ):
        environment.pop(prohibited, None)
    result = subprocess.run(
        ["bash", str(GATE)],
        cwd=tmp_path,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    return result, upload_log


@pytest.mark.parametrize("retry_count", ["1", "2", "malformed", "-1", "00"])
def test_retried_or_malformed_job_fails_before_oidc_and_live_boundaries(
    tmp_path: Path, retry_count: str
) -> None:
    result, uploads = run_gate(
        tmp_path,
        deployment_status=0,
        evidence=True,
        outcome="SUCCEEDED",
        retry_count=retry_count,
    )
    command_log = tmp_path / "commands"
    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr == "retried deployment job is not authorized\n"
    assert not command_log.exists()
    assert not uploads.exists()


@pytest.mark.parametrize("retry_count", ["0", None])
def test_original_job_continues_into_normal_gate_path(
    tmp_path: Path, retry_count: str | None
) -> None:
    result, uploads = run_gate(
        tmp_path,
        deployment_status=0,
        evidence=True,
        outcome="SUCCEEDED",
        retry_count=retry_count,
    )
    commands = (tmp_path / "commands").read_text(encoding="utf-8").splitlines()
    assert result.returncode == 0
    assert commands.count("oidc") == 2
    assert "verify-deployment-ansible-runtime" in commands
    assert "deploy-buildkite-promotion" in commands
    assert commands.count("audit:verify-buildkite") == 1
    assert commands.count("audit:persist-buildkite") == 1
    assert uploads.exists()


def test_absent_request_stops_before_second_jwt_and_provider_construction(
    tmp_path: Path,
) -> None:
    result, uploads = run_gate(
        tmp_path,
        deployment_status=90,
        evidence=False,
        outcome="forbidden",
        live_request=False,
    )
    commands = (tmp_path / "commands").read_text(encoding="utf-8").splitlines()
    assert result.returncode == 0
    assert commands.count("oidc") == 1
    assert "deploy-buildkite-promotion" not in commands
    assert "verify-deployment-ansible-runtime" not in commands
    assert commands.count("audit:persist-buildkite") == 1
    assert not uploads.exists()
    assert "live deployment requested: NO" in result.stdout
    assert "device write executed: NO" in result.stdout


def test_missing_audit_root_stops_before_device_capable_boundary(
    tmp_path: Path,
) -> None:
    result, _uploads = run_gate(
        tmp_path,
        deployment_status=90,
        evidence=False,
        outcome="forbidden",
        audit_root=False,
    )
    commands = (tmp_path / "commands").read_text(encoding="utf-8").splitlines()
    assert result.returncode != 0
    assert commands.count("oidc") == 1
    assert "deploy-buildkite-promotion" not in commands


def test_runtime_failure_stops_before_privileged_jwt_and_deployment(
    tmp_path: Path,
) -> None:
    result, uploads = run_gate(
        tmp_path,
        deployment_status=90,
        evidence=False,
        outcome="forbidden",
        runtime_status=2,
    )
    commands = (tmp_path / "commands").read_text(encoding="utf-8").splitlines()
    assert result.returncode == 2
    assert commands.count("oidc") == 1
    assert commands.index("verify-buildkite-live-request") < commands.index(
        "verify-deployment-ansible-runtime"
    )
    assert "deploy-buildkite-promotion" not in commands
    assert not uploads.exists()


@pytest.mark.parametrize("outcome", ["SUCCEEDED", "RECOVERED"])
def test_successful_or_recovered_deployment_uploads_evidence_and_succeeds(
    tmp_path: Path, outcome: str
) -> None:
    result, uploads = run_gate(
        tmp_path, deployment_status=0, evidence=True, outcome=outcome
    )
    assert result.returncode == 0
    assert uploads.read_text(encoding="utf-8") == (
        "deployment-evidence/change-record.json\n"
    )
    assert "device write executed: YES" in result.stdout


@pytest.mark.parametrize(
    "outcome", ["BLOCKED", "POST_VALIDATION_FAILED", "AMBIGUOUS", "RECOVERY_FAILED"]
)
def test_nonzero_deployment_uploads_evidence_and_preserves_failure(
    tmp_path: Path, outcome: str
) -> None:
    result, uploads = run_gate(
        tmp_path, deployment_status=2, evidence=True, outcome=outcome
    )
    assert result.returncode == 2
    assert uploads.read_text(encoding="utf-8") == (
        "deployment-evidence/change-record.json\n"
    )
    assert "inspect the uploaded typed ChangeRecord evidence" in result.stdout
    assert "device write executed: NO" not in result.stdout
    assert "device write executed: YES" not in result.stdout


def test_failure_before_evidence_does_not_fabricate_artifact(tmp_path: Path) -> None:
    result, uploads = run_gate(
        tmp_path, deployment_status=2, evidence=False, outcome="AMBIGUOUS"
    )
    assert result.returncode == 2
    assert not uploads.exists()
    assert "failed before typed ChangeRecord evidence" in result.stdout
    assert "device write executed:" not in result.stdout


def test_audit_failure_after_success_does_not_retry_deployment(tmp_path: Path) -> None:
    result, _uploads = run_gate(
        tmp_path,
        deployment_status=0,
        evidence=True,
        outcome="SUCCEEDED",
        audit_status=8,
    )
    commands = (tmp_path / "commands").read_text(encoding="utf-8").splitlines()
    assert result.returncode == 1
    assert commands.count("deploy-buildkite-promotion") == 1
    assert commands.count("audit:persist-buildkite") == 1
    assert "will not be retried or recovered" in result.stderr


def test_deployment_failure_remains_primary_when_audit_also_fails(
    tmp_path: Path,
) -> None:
    result, _uploads = run_gate(
        tmp_path,
        deployment_status=2,
        evidence=True,
        outcome="AMBIGUOUS",
        audit_status=8,
    )
    commands = (tmp_path / "commands").read_text(encoding="utf-8").splitlines()
    assert result.returncode == 2
    assert commands.count("deploy-buildkite-promotion") == 1
    assert "deployment outcome remains primary" in result.stdout


def test_artifact_upload_failure_fails_job_without_exposing_secrets(
    tmp_path: Path,
) -> None:
    result, uploads = run_gate(
        tmp_path,
        deployment_status=0,
        evidence=True,
        outcome="SUCCEEDED",
        upload_status=9,
    )
    commands = (tmp_path / "commands").read_text(encoding="utf-8").splitlines()
    assert result.returncode == 9
    assert commands.count("deploy-buildkite-promotion") == 1
    assert commands.count("audit:persist-buildkite") == 1
    assert uploads.exists()
    combined = result.stdout + result.stderr + uploads.read_text(encoding="utf-8")
    for secret in ("bounded-jwt", "client-token", "device-password"):
        assert secret not in combined
    assert "device write executed:" not in result.stdout
