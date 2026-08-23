"""Secret-safe CLI contract for future Buildkite/OpenBao integration."""

from __future__ import annotations

import sys
from io import StringIO

import pytest

import network_change_delivery.cli as cli_module
from network_change_delivery.buildkite_identity import OpenBaoJWTAuthentication
from network_change_delivery.cli import build_parser, main

JWT = "secret-header.secret-payload.secret-signature"
CLIENT_TOKEN = "sensitive-openbao-client-token"


def buildkite_environment(monkeypatch) -> None:
    values = {
        "BUILDKITE_COMMIT": "a" * 40,
        "BUILDKITE_BRANCH": "main",
        "BUILDKITE_PULL_REQUEST": "false",
        "BUILDKITE_PIPELINE_ID": "pipeline-uuid",
        "BUILDKITE_BUILD_ID": "build-uuid",
        "BUILDKITE_BUILD_NUMBER": "17",
        "BUILDKITE_JOB_ID": "job-uuid",
        "BUILDKITE_STEP_KEY": "deploy-gate",
        "BUILDKITE_AGENT_META_DATA_QUEUE": "ncdp-deploy",
        "NCDP_OPENBAO_URL": "https://openbao.example",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)


def test_cli_reads_jwt_only_from_stdin_and_prints_non_secret_summary(
    monkeypatch, capsys
) -> None:
    buildkite_environment(monkeypatch)
    observed: dict[str, str] = {}

    class Authenticator:
        def authenticate(self, jwt, context):
            observed["jwt"] = jwt.value
            observed["pipeline"] = context.pipeline_id
            return OpenBaoJWTAuthentication(
                CLIENT_TOKEN,
                300,
                {
                    "pipeline_id": context.pipeline_id,
                    "build_commit": context.commit,
                    "build_branch": context.branch,
                    "step_key": context.step_key,
                    "job_id": context.job_id,
                },
            )

    monkeypatch.setattr(cli_module, "OpenBaoBuildkiteJWTAuthenticator", Authenticator)
    monkeypatch.setattr(sys, "stdin", StringIO(JWT + "\n"))
    argv = ["verify-buildkite-openbao-identity"]
    assert JWT not in argv
    assert main(argv) == 0
    output = capsys.readouterr()
    assert observed == {"jwt": JWT, "pipeline": "pipeline-uuid"}
    assert "Buildkite OpenBao identity verified" in output.out
    assert "300 seconds" in output.out
    assert JWT not in output.out + output.err
    assert CLIENT_TOKEN not in output.out + output.err


def test_cli_has_no_jwt_argument() -> None:
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["verify-buildkite-openbao-identity", "--jwt", JWT])


def test_cli_rejects_invalid_stdin_before_openbao(monkeypatch, capsys) -> None:
    buildkite_environment(monkeypatch)

    class UnexpectedAuthenticator:
        def __init__(self) -> None:
            raise AssertionError("OpenBao must not be contacted")

    monkeypatch.setattr(
        cli_module, "OpenBaoBuildkiteJWTAuthenticator", UnexpectedAuthenticator
    )
    monkeypatch.setattr(sys, "stdin", StringIO("two.lines\nextra"))
    with pytest.raises(SystemExit):
        main(["verify-buildkite-openbao-identity"])
    output = capsys.readouterr()
    assert "input rejected" in output.err
    assert "two.lines" not in output.err
