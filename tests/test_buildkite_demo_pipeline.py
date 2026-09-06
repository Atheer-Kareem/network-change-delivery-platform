"""Local-only manual-main demo contracts; no Buildkite/runtime API calls."""

from __future__ import annotations

import copy
import importlib.util
import os
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

ROOT = Path(__file__).parents[1]
NORMAL = ROOT / ".buildkite/pipeline.yml"
CANONICAL = "https://github.com/Atheer-Kareem/network-change-delivery-platform.git"


@pytest.fixture
def renderer():
    spec = importlib.util.spec_from_file_location(
        "demo_renderer", ROOT / "scripts/buildkite/render_demo_pipeline.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def demo_environment():
    return {
        "NCDP_DEMO_CONTINUE_ON_FAILURE": "1",
        "BUILDKITE_SOURCE": "ui",
        "BUILDKITE_BRANCH": "main",
        "BUILDKITE_PULL_REQUEST": "false",
        "BUILDKITE_REPO": CANONICAL,
        "BUILDKITE_AGENT_META_DATA_QUEUE": "ncdp-validation",
        "BUILDKITE_RETRY_COUNT": "0",
    }


INVALID_CONTEXTS = (
    [
        {"BUILDKITE_SOURCE": source}
        for source in ("webhook", "api", "schedule", "trigger_job", "", "UI")
    ]
    + [
        {"BUILDKITE_BRANCH": "feature/demo"},
        {"BUILDKITE_BRANCH": "refs/heads/main"},
        {"BUILDKITE_PULL_REQUEST": "136"},
        {"BUILDKITE_PULL_REQUEST": ""},
        {"BUILDKITE_PULL_REQUEST_REPO": CANONICAL},
        {"BUILDKITE_PULL_REQUEST_BASE_BRANCH": "main"},
        {"BUILDKITE_TRIGGERED_FROM_BUILD_ID": "synthetic-trigger"},
        {"BUILDKITE_TAG": "v1"},
        {"BUILDKITE_REPO": "https://github.com/fork/repo.git"},
        {"BUILDKITE_RETRY_COUNT": "1"},
        {"BUILDKITE_AGENT_META_DATA_QUEUE": "ncdp-staging"},
    ]
    + [
        {"NCDP_DEMO_CONTINUE_ON_FAILURE": value}
        for value in ("", "0", "true", "01", "1 ")
    ]
)


@pytest.mark.parametrize("override", INVALID_CONTEXTS)
def test_demo_requires_all_manual_main_conditions_before_render(renderer, override):
    with pytest.raises(ValueError, match="context rejected"):
        renderer.render_demo(None, demo_environment() | override)


@pytest.mark.parametrize("missing", list(demo_environment()))
def test_demo_missing_required_context_rejected(renderer, missing):
    environment = demo_environment()
    del environment[missing]
    with pytest.raises(ValueError, match="context rejected"):
        renderer.admit_demo(environment)


def test_demo_projection_preserves_every_normal_step_and_authority(renderer):
    normal = yaml.safe_load(NORMAL.read_text())
    original = copy.deepcopy(normal)
    demo = renderer.render_demo(normal, demo_environment())
    assert normal == original
    assert len(demo["steps"]) == len(normal["steps"]) == 16
    assert {step["key"] for step in demo["steps"]} == renderer.COMMAND_KEYS | {
        "validation-complete"
    }
    assert "DEMO MODE — CONTINUE ON FAILURE" in renderer.BANNER
    assert "not merge/deployment acceptance" in renderer.BANNER
    for before, after in zip(normal["steps"], demo["steps"], strict=True):
        assert "soft_fail" not in before
        assert "continue_on_failure" not in before
        assert "allow_dependency_failure" not in after
        assert after["if"] == (
            'build.source == "ui" && build.branch == "main" && '
            "build.pull_request.id == null && "
            'build.env("NCDP_DEMO_CONTINUE_ON_FAILURE") == "1"'
        )
        if "wait" in before:
            assert after == before | {
                "if": renderer.DEMO_CONDITION,
                "continue_on_failure": True,
            }
            continue
        assert after["soft_fail"] is True
        assert "if_changed" not in after
        assert after["label"].startswith("DEMO · ")
        assert after["retry"]["automatic"] is False
        assert after["retry"]["manual"]["allowed"] is False
        for key, value in before.get("retry", {}).items():
            assert after["retry"][key] == value
        mutable = {"if", "if_changed", "soft_fail", "label", "retry"}
        assert {k: v for k, v in after.items() if k not in mutable} == {
            k: v for k, v in before.items() if k not in mutable
        }
    # The only demo-only execution exception is the guarded PR Batfish condition.
    by_key = {step["key"]: step for step in demo["steps"]}
    assert by_key["pr-batfish-assurance"]["depends_on"] == "validation-complete"
    assert by_key["cml-staging"]["depends_on"] == [
        "validation-complete",
        "pr-batfish-assurance",
    ]
    source = yaml.safe_dump(demo)
    for forbidden in (
        "profiled-deploy",
        "protected-delivery",
        "ncdp-deploy",
        "promotion.sh",
    ):
        assert forbidden not in source


@pytest.mark.parametrize(
    "damage",
    [
        "root",
        "extra_step",
        "missing",
        "duplicate",
        "group",
        "plugin",
        "environment",
        "soft_fail",
        "skip",
        "wait",
        "condition",
        "queue",
        "retry",
        "commands",
        "dependencies",
        "paths",
        "concurrency",
    ],
)
def test_unreviewed_graph_shape_fails_closed(renderer, damage):
    normal = yaml.safe_load(NORMAL.read_text())
    first = normal["steps"][0]
    if damage == "root":
        normal["env"] = {}
    elif damage == "extra_step":
        normal["steps"].append(copy.deepcopy(first))
    elif damage == "missing":
        normal["steps"].pop()
    elif damage == "duplicate":
        normal["steps"][-1] = copy.deepcopy(first)
    elif damage == "group":
        normal["steps"][0] = {"group": "new", "steps": [first]}
    elif damage == "wait":
        normal["steps"][13]["continue_on_failure"] = True
    else:
        field, value = {
            "plugin": ("plugins", []),
            "environment": ("env", {}),
            "soft_fail": ("soft_fail", True),
            "skip": ("skip", True),
            "condition": ("if", "true"),
            "queue": ("agents", {"queue": "ncdp-deploy"}),
            "retry": ("retry", {"automatic": True}),
            "commands": ("command", {}),
            "dependencies": ("depends_on", [{"step": "quality-env"}]),
            "paths": ("if_changed", {"unknown": "**"}),
            "concurrency": ("concurrency", 2),
        }[damage]
        first[field] = value
    with pytest.raises(ValueError):
        renderer.render_demo(normal, demo_environment())


def configure_main(renderer, monkeypatch, environment):
    for key in set(demo_environment()) | {
        "BUILDKITE_PULL_REQUEST_REPO",
        "BUILDKITE_PULL_REQUEST_BASE_BRANCH",
        "BUILDKITE_TAG",
        "BUILDKITE_TRIGGERED_FROM_BUILD_ID",
    }:
        monkeypatch.delenv(key, raising=False)
    for key, value in environment.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(renderer.sys, "argv", ["renderer", "--upload"])


@pytest.mark.parametrize("source", ["webhook", "api", "schedule", "trigger_job", "ui"])
def test_normal_upload_never_transforms_or_annotates(renderer, monkeypatch, source):
    configure_main(renderer, monkeypatch, {"BUILDKITE_SOURCE": source})
    calls = []
    monkeypatch.setattr(
        renderer.subprocess,
        "run",
        lambda args, **kwargs: (
            calls.append((args, kwargs)) or SimpleNamespace(returncode=0)
        ),
    )
    monkeypatch.setattr(
        renderer, "render_demo", lambda *_: pytest.fail("normal mutated")
    )
    assert renderer.main() == 0
    assert calls == [
        (
            [
                "buildkite-agent",
                "pipeline",
                "upload",
                str(NORMAL),
                "--fetch-diff-base",
                "--reject-secrets",
                "--reject-parse-warnings",
            ],
            {"cwd": ROOT, "check": False},
        )
    ]


@pytest.mark.parametrize("override", INVALID_CONTEXTS)
def test_invalid_demo_upload_has_no_publication_or_upload(
    renderer, monkeypatch, capsys, override
):
    # Empty flag means normal, not a demo attempt; use render-only for that case.
    configure_main(renderer, monkeypatch, demo_environment() | override)
    if override.get(renderer.FLAG) == "":
        monkeypatch.setattr(renderer.sys, "argv", ["renderer"])
    monkeypatch.setenv("SYNTHETIC_PASSWORD", "never-print-this-secret")
    monkeypatch.setattr(
        renderer.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("external call"),
    )
    assert renderer.main() == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "Demo pipeline admission/render/publication failed\n"


@pytest.mark.parametrize("failure", ["none", "banner", "upload"])
def test_demo_banner_precedes_single_upload_and_failures_propagate(
    renderer, monkeypatch, failure
):
    configure_main(renderer, monkeypatch, demo_environment())
    calls = []

    def run(args, **kwargs):
        calls.append((args, kwargs))
        if args[1] == "annotate" and failure == "banner":
            raise subprocess.CalledProcessError(1, args)
        return SimpleNamespace(returncode=7 if failure == "upload" else 0)

    monkeypatch.setattr(renderer.subprocess, "run", run)
    assert renderer.main() == {"none": 0, "banner": 2, "upload": 7}[failure]
    assert calls[0][0][1] == "annotate"
    assert calls[0][1]["input"] == renderer.BANNER
    assert len(calls) == (1 if failure == "banner" else 2)
    if failure != "banner":
        assert calls[1][0] == [
            "buildkite-agent",
            "pipeline",
            "upload",
            "--reject-secrets",
            "--reject-parse-warnings",
        ]
        assert yaml.safe_load(calls[1][1]["input"]) == renderer.render_demo(
            yaml.safe_load(NORMAL.read_text()), demo_environment()
        )


@pytest.mark.parametrize("demo", [False, True])
def test_installed_buildkite_parser_normal_and_demo(renderer, demo, tmp_path):
    agent = shutil.which("buildkite-agent")
    if agent is None:
        pytest.skip("Buildkite agent is not installed")
    source = NORMAL.read_text()
    if demo:
        source = yaml.safe_dump(
            renderer.render_demo(yaml.safe_load(source), demo_environment())
        )
    changed = tmp_path / "changed-paths.txt"
    changed.write_text("docs/demo/readiness-and-reset.md\n")
    result = subprocess.run(
        [
            agent,
            "pipeline",
            "upload",
            "--dry-run",
            "--format",
            "yaml",
            "--reject-secrets",
            "--reject-parse-warnings",
            "--changed-files-path",
            str(changed),
        ],
        input=source,
        text=True,
        capture_output=True,
        check=False,
        cwd=ROOT,
        env={**os.environ, "BUILDKITE_AGENT_ACCESS_TOKEN": "local-dry-run"},
    )
    assert result.returncode == 0, result.stderr
    if demo:
        parsed = yaml.safe_load(result.stdout)
        assert len(parsed["steps"]) == 16
        for step in parsed["steps"]:
            assert step.get("skip") is None
            if "command" in step or "commands" in step:
                assert step["soft_fail"] is True
    else:
        parsed = yaml.safe_load(result.stdout)
        by_key = {step["key"]: step for step in parsed["steps"]}
        assert by_key["pr-batfish-assurance"]["skip"]
        assert by_key["cml-staging"]["skip"]


@pytest.mark.parametrize("demo", [False, True])
@pytest.mark.parametrize(
    "case", ["clean", "wrong-commit", "dirty", "untracked", "fork"]
)
@pytest.mark.skipif(shutil.which("git") is None, reason="Git is not installed")
def test_batfish_context_keeps_exact_commit_verification(tmp_path, demo, case):
    def git(*args):
        return subprocess.run(
            ["git", *args], cwd=tmp_path, capture_output=True, text=True, check=True
        ).stdout.strip()

    git("init", "--quiet")
    tracked = tmp_path / "tracked"
    tracked.write_text("original\n")
    git("add", "tracked")
    git(
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "commit",
        "--quiet",
        "-m",
        "fixture",
    )
    environment = demo_environment() | {
        "PATH": os.environ["PATH"],
        "BUILDKITE_STEP_KEY": "pr-batfish-assurance",
        "BUILDKITE_COMMIT": "a" * 40
        if case == "wrong-commit"
        else git("rev-parse", "HEAD"),
    }
    if not demo:
        environment.update(
            BUILDKITE_SOURCE="webhook",
            BUILDKITE_BRANCH="feature/test",
            BUILDKITE_PULL_REQUEST="136",
            BUILDKITE_PULL_REQUEST_REPO=CANONICAL,
        )
        environment.pop("NCDP_DEMO_CONTINUE_ON_FAILURE")
    if case == "dirty":
        tracked.write_text("changed\n")
    elif case == "untracked":
        (tmp_path / "unexpected").touch()
    elif case == "fork":
        environment["BUILDKITE_PULL_REQUEST_REPO"] = "https://github.com/fork/repo.git"
    result = subprocess.run(
        ["bash", str(ROOT / "scripts/buildkite/verify_commit.sh")],
        cwd=tmp_path,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == (0 if case == "clean" else 2)


@pytest.mark.parametrize("override", [*INVALID_CONTEXTS, {}, {"normal_pr": "1"}])
def test_batfish_wrapper_admits_only_canonical_pr_or_demo_before_work(
    tmp_path, override
):
    environment = demo_environment() | {
        "BUILDKITE_STEP_KEY": "pr-batfish-assurance",
        "BUILDKITE_COMMIT": "a" * 40,
    }
    accepted = override == {} or override == {"normal_pr": "1"}
    if "normal_pr" in override:
        environment.update(
            BUILDKITE_SOURCE="webhook",
            BUILDKITE_BRANCH="feature/test",
            BUILDKITE_PULL_REQUEST="136",
            BUILDKITE_PULL_REQUEST_REPO=CANONICAL,
        )
        environment.pop("NCDP_DEMO_CONTINUE_ON_FAILURE")
    else:
        environment.update(override)
    # The real wrapper and real verifier execute. First git call is a sentinel;
    # rejection must happen before it (and therefore before Docker/temp creation).
    binary = tmp_path / "git"
    binary.write_text('#!/bin/sh\necho "reached-commit-verification" >&2\nexit 93\n')
    binary.chmod(0o700)
    result = subprocess.run(
        ["bash", str(ROOT / ".buildkite/scripts/profiled_pr_batfish_assurance.sh")],
        cwd=ROOT,
        env={"PATH": f"{tmp_path}:/usr/bin:/bin", **environment},
        text=True,
        capture_output=True,
        check=False,
    )
    assert ("reached-commit-verification" in result.stderr) == accepted
    assert result.returncode != 0  # No Docker or live work even for admitted cases.
    assert "never-print-this-secret" not in result.stdout + result.stderr
