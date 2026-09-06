"""Fake processes only: success receipts never turn failure into authorization."""

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
REPO = "https://github.com/Atheer-Kareem/network-change-delivery-platform.git"
COMMIT = "a" * 40


@pytest.mark.parametrize(
    "failure", ["none", "assurance", "verification", "digest", "publication", "cleanup"]
)
def test_batfish_receipt_only_after_verified_success_and_cleanup(tmp_path, failure):
    scripts = tmp_path / "scripts/buildkite"
    scripts.mkdir(parents=True)
    verifier = scripts / "verify_commit.sh"
    verifier.write_text("#!/bin/sh\nexit 0\n")
    verifier.chmod(0o700)
    bindir = tmp_path / "bin"
    bindir.mkdir()
    marker = tmp_path / "receipt"
    docker = bindir / "docker"
    docker.write_text("""#!/usr/bin/env python3
import os, pathlib, sys
args = sys.argv[1:]
failure = os.environ["FAKE_FAILURE"]
if "down" in args:
    sys.exit(3 if failure == "cleanup" and "--remove-orphans" not in args else 0)
if "--volume" not in args:
    sys.exit(0)
directory = pathlib.Path(args[args.index("--volume") + 1].split(":")[0])
if any("verify_profiled_pr_candidate.py" in a for a in args):
    if "--verify-only" not in args:
        (directory / "assurance/profiled-pr-assurance.json").write_text("{}")
        sys.exit(7 if failure == "assurance" else 0)
    if failure == "verification":
        sys.exit(8)
    if "--digest-only" in args:
        print("invalid" if failure == "digest" else "sha256:" + "a" * 64)
if any("render_profiled_pr_assurance_annotation.py" in a for a in args):
    print("sanitized evidence summary")
""")
    docker.chmod(0o700)
    agent = bindir / "buildkite-agent"
    agent.write_text("""#!/usr/bin/env python3
import os, pathlib, sys
if os.environ["FAKE_FAILURE"] == "publication":
    sys.exit(3)
if sys.argv[1] == "meta-data":
    pathlib.Path(os.environ["FAKE_MARKER"]).write_text(" ".join(sys.argv[1:]))
""")
    agent.chmod(0o700)
    result = subprocess.run(
        ["bash", str(ROOT / ".buildkite/scripts/profiled_pr_batfish_assurance.sh")],
        cwd=tmp_path,
        env={
            "PATH": f"{bindir}:{os.environ['PATH']}",
            "FAKE_FAILURE": failure,
            "FAKE_MARKER": str(marker),
            "BUILDKITE_STEP_KEY": "pr-batfish-assurance",
            "BUILDKITE_AGENT_META_DATA_QUEUE": "ncdp-validation",
            "BUILDKITE_RETRY_COUNT": "0",
            "BUILDKITE_BUILD_NUMBER": "1",
            "BUILDKITE_JOB_ID": "fake-job",
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert (result.returncode == 0) is (failure == "none")
    assert marker.exists() is (failure == "none")
    if marker.exists():
        assert "profiled-batfish-success sha256:" in marker.read_text()
    if failure == "assurance":
        assert result.returncode == 7


@pytest.mark.parametrize(
    "branch,pr,origin,accepted",
    [
        ("main", "false", "", True),
        ("feature", "136", REPO, True),
        ("feature", "false", "", False),
        ("main", "136", "fork", False),
        ("main", "", "", False),
        ("main", "false", REPO, False),
    ],
)
def test_batfish_canonical_pr_or_main_without_demo_mode(
    tmp_path, branch, pr, origin, accepted
):
    git = tmp_path / "git"
    git.write_text(f'#!/bin/sh\nif [ "$1" = rev-parse ]; then echo {COMMIT}; fi\n')
    git.chmod(0o700)
    result = subprocess.run(
        ["bash", str(ROOT / "scripts/buildkite/verify_commit.sh")],
        cwd=tmp_path,
        env={
            "PATH": f"{tmp_path}:/usr/bin:/bin",
            "BUILDKITE_BRANCH": branch,
            "BUILDKITE_COMMIT": COMMIT,
            "BUILDKITE_STEP_KEY": "pr-batfish-assurance",
            "BUILDKITE_REPO": REPO,
            "BUILDKITE_PULL_REQUEST": pr,
            "BUILDKITE_PULL_REQUEST_REPO": origin,
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert (result.returncode == 0) is accepted


@pytest.mark.parametrize("exitcode", [0, 5])
def test_failed_engineering_command_cannot_publish_success_receipt(tmp_path, exitcode):
    import yaml

    steps = yaml.safe_load((ROOT / ".buildkite/pipeline.yml").read_text())["steps"]
    docker = tmp_path / "docker"
    docker.write_text(f"#!/bin/sh\nexit {exitcode}\n")
    docker.chmod(0o700)
    uv = tmp_path / "uv"
    marker = tmp_path / "receipt"
    uv.write_text(f"#!/bin/sh\ntouch '{marker}'\n")
    uv.chmod(0o700)
    source = next(s["command"] for s in steps if s["key"] == "quality-ruff-lint")
    result = subprocess.run(
        ["bash", "-c", source.replace("$$", "$")],
        env={"PATH": f"{tmp_path}:/usr/bin:/bin", "BUILDKITE_BUILD_NUMBER": "1"},
        capture_output=True,
        check=False,
    )
    assert result.returncode == exitcode
    assert marker.exists() is (exitcode == 0)
