from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts/buildkite/ephemeral_staging.sh"
AGENT_HOOK = ROOT / "scripts/buildkite/staging_agent_command_hook.sh"


def executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def run_script(
    tmp_path: Path,
    *,
    staging_status: int = 0,
    evidence: bool = True,
    upload_status: int = 0,
    retry_count: str = "0",
) -> tuple[subprocess.CompletedProcess[str], Path, Path]:
    work = tmp_path / "work"
    work.mkdir()
    (work / "scripts/buildkite").mkdir(parents=True)
    executable(
        work / "scripts/buildkite/verify_staging_commit.sh",
        "#!/bin/sh\nexit 0\n",
    )
    binary = tmp_path / "bin"
    binary.mkdir()
    command_log = tmp_path / "commands"
    upload_log = tmp_path / "uploads"
    executable(
        binary / "buildkite-agent",
        """#!/usr/bin/env bash
set -eu
case "$1 $2" in
  "oidc request-token")
    printf '%s\n' "$*" >> "$COMMAND_LOG"
    printf '%s\n' 'header.payload.signature'
    ;;
  "artifact upload")
    printf '%s\n' "$3" >> "$UPLOAD_LOG"
    exit "$UPLOAD_STATUS"
    ;;
  *) exit 90 ;;
esac
""",
    )
    executable(
        binary / "uv",
        """#!/usr/bin/env bash
set -eu
read -r jwt
[[ "$jwt" == header.payload.signature ]]
printf '%s\n' "$*" >> "$COMMAND_LOG"
evidence=''
while [[ $# -gt 0 ]]; do
  if [[ "$1" == --evidence ]]; then evidence="$2"; break; fi
  shift
done
if [[ "$CREATE_EVIDENCE" == 1 ]]; then
  mkdir -p "$(dirname "$evidence")"
  printf '{"overall_result":"passed"}\n' > "$evidence"
fi
exit "$STAGING_STATUS"
""",
    )
    state_root = tmp_path / "state"
    state_root.mkdir(mode=0o700)
    environment = {
        **os.environ,
        "PATH": f"{binary}:{os.environ['PATH']}",
        "BUILDKITE_STEP_KEY": "cml-staging",
        "BUILDKITE_AGENT_META_DATA_QUEUE": "ncdp-staging",
        "BUILDKITE_RETRY_COUNT": retry_count,
        "BUILDKITE_BUILD_ID": "79c012df-23bf-49b3-a6dd-f28799c4bb24",
        "NCDP_STAGING_STATE_ROOT": str(state_root),
        "COMMAND_LOG": str(command_log),
        "UPLOAD_LOG": str(upload_log),
        "UPLOAD_STATUS": str(upload_status),
        "STAGING_STATUS": str(staging_status),
        "CREATE_EVIDENCE": "1" if evidence else "0",
    }
    for name in (
        "NCDP_OPENBAO_ROLE_ID",
        "NCDP_OPENBAO_SECRET_ID",
        "NCDP_NETBOX_TOKEN",
        "CML2_TOKEN",
        "NCDP_DEVICE_USERNAME",
        "NCDP_DEVICE_PASSWORD",
    ):
        environment.pop(name, None)
    result = subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=work,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    return result, command_log, upload_log


def test_shell_requests_exact_oidc_and_uploads_evidence(tmp_path: Path) -> None:
    result, commands, uploads = run_script(tmp_path)
    assert result.returncode == 0
    logged = commands.read_text()
    assert "--audience urn:ncdp:openbao:staging" in logged
    assert "--lifetime 300" in logged
    assert "--subject-claim pipeline_id" in logged
    assert "--claim build_id" in logged
    assert "--identity buildkite" in logged
    assert "bk-79c012df-23bf-49b3-a6dd-f28799c4bb24" in logged
    assert uploads.read_text().strip() == "staging-evidence/staging-run.json"
    evidence = tmp_path / "work/staging-evidence/staging-run.json"
    assert stat.S_IMODE(evidence.stat().st_mode) == 0o600


@pytest.mark.parametrize("retry", ["1", "2", "-1", "00", "malformed"])
def test_retry_rejected_before_oidc(tmp_path: Path, retry: str) -> None:
    result, commands, _uploads = run_script(tmp_path, retry_count=retry)
    assert result.returncode == 2
    assert not commands.exists()


def test_wrong_step_or_queue_is_rejected_before_oidc(tmp_path: Path) -> None:
    environment = os.environ | {
        "BUILDKITE_STEP_KEY": "deploy-gate",
        "BUILDKITE_AGENT_META_DATA_QUEUE": "ncdp-staging",
    }
    rejected = subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=tmp_path,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert rejected.returncode == 2
    assert "step or queue" in rejected.stderr


def test_primary_failure_preserved_when_evidence_upload_succeeds(
    tmp_path: Path,
) -> None:
    result, _commands, uploads = run_script(tmp_path, staging_status=7)
    assert result.returncode == 7
    assert uploads.read_text().strip() == "staging-evidence/staging-run.json"


def test_artifact_upload_failure_fails_successful_job(tmp_path: Path) -> None:
    result, _commands, _uploads = run_script(tmp_path, upload_status=9)
    assert result.returncode == 9


def test_no_evidence_is_not_fabricated(tmp_path: Path) -> None:
    result, _commands, uploads = run_script(tmp_path, staging_status=3, evidence=False)
    assert result.returncode == 3
    assert not uploads.exists()


def test_agent_hook_rejects_fork_and_non_staging_commands(tmp_path: Path) -> None:
    hook_directory = tmp_path / ".config/buildkite/ncdp-lab/hooks/ncdp-staging"
    hook_directory.mkdir(parents=True)
    (hook_directory / "staging.env").write_text("export STAGING_TEST=1\n")
    (hook_directory / "staging.env").chmod(0o600)
    wrapper = tmp_path / "scripts/buildkite/ephemeral_staging.sh"
    wrapper.parent.mkdir(parents=True)
    executable(wrapper, "#!/usr/bin/env bash\n[[ $STAGING_TEST == 1 ]]\n")
    environment = os.environ | {
        "BUILDKITE_STEP_KEY": "cml-staging",
        "BUILDKITE_AGENT_META_DATA_QUEUE": "ncdp-staging",
        "BUILDKITE_COMMAND": "scripts/buildkite/ephemeral_staging.sh",
        "BUILDKITE_REPO": "git@github.com:example/ncdp.git",
        "BUILDKITE_PULL_REQUEST_REPO": "git@github.com:fork/ncdp.git",
        "HOME": str(tmp_path),
    }
    rejected = subprocess.run(
        [str(AGENT_HOOK)],
        cwd=tmp_path,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert rejected.returncode == 2
    assert "fork-origin" in rejected.stderr

    environment["BUILDKITE_PULL_REQUEST_REPO"] = environment["BUILDKITE_REPO"]
    environment["BUILDKITE_COMMAND"] = "malicious-command"
    rejected = subprocess.run(
        [str(AGENT_HOOK)], cwd=tmp_path, env=environment, check=False
    )
    assert rejected.returncode != 0

    environment["BUILDKITE_COMMAND"] = "scripts/buildkite/ephemeral_staging.sh"
    accepted = subprocess.run(
        [str(AGENT_HOOK)], cwd=tmp_path, env=environment, check=False
    )
    assert accepted.returncode == 0
