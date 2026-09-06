#!/usr/bin/env python3
"""Explicit manual-main demo projection; normal uploads retain the source YAML."""

from __future__ import annotations

import argparse
import copy
import os
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
PIPELINE = ROOT / ".buildkite/pipeline.yml"
FLAG = "NCDP_DEMO_CONTINUE_ON_FAILURE"
DEMO_CONDITION = (
    'build.source == "ui" && build.branch == "main" && '
    "build.pull_request.id == null && "
    'build.env("NCDP_DEMO_CONTINUE_ON_FAILURE") == "1"'
)
REPOSITORIES = {
    "https://github.com/Atheer-Kareem/network-change-delivery-platform.git",
    "git@github.com:Atheer-Kareem/network-change-delivery-platform.git",
}
# A new step/shape needs explicit review, not an automatic non-blocking projection.
COMMAND_KEYS = {
    "quality-env",
    "quality-committed-diff",
    "quality-ruff-lint",
    "quality-ruff-format",
    "quality-pytest",
    "quality-ansible-lint",
    "quality-package-build",
    "quality-terraform-profiled-staging",
    "quality-snmp-generator",
    "quality-observability-runtime",
    "quality-snmpv3-synthetic",
    "buildkite-definition",
    "ncdp-pipeline-contract",
    "pr-batfish-assurance",
    "cml-staging",
}
COMMAND_FIELDS = {
    "label",
    "key",
    "command",
    "commands",
    "agents",
    "depends_on",
    "if",
    "if_changed",
    "concurrency",
    "concurrency_group",
    "retry",
}
BANNER = """# DEMO MODE — CONTINUE ON FAILURE

Failures remain visible and failure evidence remains truthful. Downstream steps
continue for demonstration. **This build is not merge/deployment acceptance.**
Normal CI remains hard-fail. No device-write or retry authority is added.
"""


def admit_demo(environment: Mapping[str, str]) -> None:
    if (
        environment.get(FLAG) != "1"
        or environment.get("BUILDKITE_SOURCE") != "ui"
        or environment.get("BUILDKITE_BRANCH") != "main"
        or environment.get("BUILDKITE_PULL_REQUEST") != "false"
        or environment.get("BUILDKITE_PULL_REQUEST_REPO")
        or environment.get("BUILDKITE_PULL_REQUEST_BASE_BRANCH")
        or environment.get("BUILDKITE_TRIGGERED_FROM_BUILD_ID")
        or environment.get("BUILDKITE_TAG")
        or environment.get("BUILDKITE_REPO") not in REPOSITORIES
        or environment.get("BUILDKITE_RETRY_COUNT") != "0"
        or environment.get("BUILDKITE_AGENT_META_DATA_QUEUE") != "ncdp-validation"
    ):
        raise ValueError("demo context rejected")


def validate_graph(pipeline: object) -> None:
    """Admit only the current flat command/wait graph, never hooks/plugins/writes."""
    if not isinstance(pipeline, dict) or set(pipeline) != {"steps"}:
        raise ValueError("demo graph rejected")
    steps = pipeline["steps"]
    if not isinstance(steps, list) or len(steps) != len(COMMAND_KEYS) + 1:
        raise ValueError("demo graph rejected")
    keys = []
    for step in steps:
        if not isinstance(step, dict):
            raise ValueError("demo step rejected")
        key = step.get("key")
        keys.append(key)
        if key == "validation-complete":
            if step != {"wait": None, "key": key}:
                raise ValueError("demo wait rejected")
            continue
        if (
            not isinstance(key, str)
            or key not in COMMAND_KEYS
            or not set(step) <= COMMAND_FIELDS
            or not isinstance(step.get("label"), str)
            or ("command" in step) == ("commands" in step)
            or step.get("agents")
            != {"queue": "ncdp-staging" if key == "cml-staging" else "ncdp-validation"}
        ):
            raise ValueError("demo command shape rejected")
        command = step.get("command", step.get("commands"))
        if not (
            (isinstance(command, str) and command)
            or (
                isinstance(command, list)
                and command
                and all(isinstance(item, str) and item for item in command)
            )
        ):
            raise ValueError("demo command rejected")
        expected_if = "build.pull_request.id != null"
        if (key == "pr-batfish-assurance" and step.get("if") != expected_if) or (
            key != "pr-batfish-assurance" and "if" in step
        ):
            raise ValueError("demo condition rejected")
        dependencies = step.get("depends_on", [])
        dependencies = [dependencies] if isinstance(dependencies, str) else dependencies
        if not isinstance(dependencies, list) or any(
            not isinstance(item, str)
            or item not in COMMAND_KEYS | {"validation-complete"}
            or item == key
            for item in dependencies
        ):
            raise ValueError("demo dependency shape rejected")
        if "if_changed" in step:
            changed = step["if_changed"]
            if (
                not isinstance(changed, dict)
                or "include" not in changed
                or not set(changed) <= {"include", "exclude"}
                or any(
                    not (
                        isinstance(value, str)
                        or (
                            isinstance(value, list)
                            and all(isinstance(item, str) for item in value)
                        )
                    )
                    for value in changed.values()
                )
            ):
                raise ValueError("demo path shape rejected")
        if ("concurrency" in step or "concurrency_group" in step) and (
            type(step.get("concurrency")) is not int
            or step["concurrency"] != 1
            or not isinstance(step.get("concurrency_group"), str)
        ):
            raise ValueError("demo concurrency shape rejected")
        retry = step.get("retry", {})
        if (
            not isinstance(retry, dict)
            or not set(retry) <= {"automatic", "manual"}
            or ("automatic" in retry and retry["automatic"] is not False)
            or (
                "manual" in retry
                and (
                    not isinstance(retry["manual"], dict)
                    or not set(retry["manual"]) <= {"allowed", "reason"}
                    or retry["manual"].get("allowed") is not False
                )
            )
        ):
            raise ValueError("demo retry contract rejected")
    if set(keys) != COMMAND_KEYS | {"validation-complete"}:
        raise ValueError("demo step population rejected")


def render_demo(pipeline: object, environment: Mapping[str, str]) -> dict:
    admit_demo(environment)
    validate_graph(pipeline)
    result = copy.deepcopy(pipeline)
    for step in result["steps"]:
        step["if"] = DEMO_CONDITION
        if "wait" in step:
            step["continue_on_failure"] = True
            continue
        step["soft_fail"] = True
        step["label"] = "DEMO · " + step["label"]
        step.pop("if_changed", None)
        # Preserve explicit prohibitions/reasons; close omitted retry defaults.
        retry = step.setdefault("retry", {})
        retry.setdefault("automatic", False)
        retry.setdefault("manual", {"allowed": False})
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--upload",
        action="store_true",
        help="select normal/demo, annotate demo first, then upload once",
    )
    args = parser.parse_args()
    try:
        if args.upload and not os.environ.get(FLAG):
            # No YAML transformation, extra steps, banner, or changed-file override.
            return subprocess.run(
                [
                    "buildkite-agent",
                    "pipeline",
                    "upload",
                    str(PIPELINE),
                    "--fetch-diff-base",
                    "--reject-secrets",
                    "--reject-parse-warnings",
                ],
                cwd=ROOT,
                check=False,
            ).returncode
        demo = render_demo(yaml.safe_load(PIPELINE.read_text()), os.environ)
        rendered = yaml.safe_dump(demo, sort_keys=False, allow_unicode=True)
        if not args.upload:
            print(rendered, end="")
            return 0
        # Publication/admission/upload fail hard. No half-pipeline on render error.
        subprocess.run(
            [
                "buildkite-agent",
                "annotate",
                "--style",
                "warning",
                "--context",
                "ncdp-demo-mode",
            ],
            input=BANNER,
            text=True,
            cwd=ROOT,
            check=True,
        )
        return subprocess.run(
            [
                "buildkite-agent",
                "pipeline",
                "upload",
                "--reject-secrets",
                "--reject-parse-warnings",
            ],
            input=rendered,
            text=True,
            cwd=ROOT,
            check=False,
        ).returncode
    except (ValueError, TypeError, OSError, yaml.YAMLError, subprocess.SubprocessError):
        print("Demo pipeline admission/render/publication failed", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
