"""CLI activation tests for the schema-v2 profiled execution boundary."""

from __future__ import annotations

import stat
from pathlib import Path

import pytest
from test_profiled_execution import Cisco, Collector, Inventory, Secrets, plan, writer

from network_change_delivery import cli
from network_change_delivery.models import (
    ExecutionDisposition,
    ExecutionResult,
    FinalOutcome,
)
from network_change_delivery.profiled_execution import execute_profiled_plan


def _arguments(plan_path: Path, report: Path, approval: str, *, live: bool = True):
    arguments = [
        "profiled-deploy",
        "--plan",
        str(plan_path),
        "--approve-digest",
        approval,
        "--report-json",
        str(report),
        "--netbox",
        "--openbao",
    ]
    if live:
        arguments.append("--live")
    return arguments


def _write_plan(path: Path):
    value, _device, _interface, _state = plan()
    path.write_text(value.model_dump_json(indent=2), encoding="utf-8")
    return value


def _record(outcome: FinalOutcome):
    value, device, interface, state = plan()
    result = ExecutionResult(
        disposition=(
            ExecutionDisposition.SUCCEEDED
            if outcome in {FinalOutcome.SUCCEEDED, FinalOutcome.RECOVERED}
            else ExecutionDisposition.FAILED
        ),
        message="bounded",
    )
    record = execute_profiled_plan(
        value,
        value.digest,
        Inventory(device, interface),
        Secrets(),
        Collector([state, state.model_copy(update={"description": "new"})]),
        writer(Cisco([result])),
    )
    return record.model_copy(update={"final_outcome": outcome})


def _not_called(*_args: object, **_kwargs: object) -> object:
    raise AssertionError("unexpected boundary invocation")


def test_profiled_deploy_parser_requires_explicit_authority_and_keeps_v1() -> None:
    parser = cli.build_parser()
    parsed = parser.parse_args(
        _arguments(Path("plan.json"), Path("record.json"), "sha256:" + "a" * 64)
    )
    assert parsed.handler is cli._run_profiled_deploy
    assert parsed.live is True
    assert (
        parser.parse_args(
            [
                "profiled-plan",
                "--change",
                "change.yaml",
                "--output",
                "plan.json",
                "--netbox",
                "--openbao",
            ]
        ).handler
        is cli._run_profiled_plan
    )
    assert (
        parser.parse_args(
            [
                "deploy",
                "--plan",
                "v1.json",
                "--approve-digest",
                "sha256:" + "a" * 64,
                "--report-json",
                "v1-record.json",
                "--netbox",
                "--openbao",
            ]
        ).handler
        is cli._run_deploy
    )
    with pytest.raises(SystemExit):
        parser.parse_args(
            _arguments(Path("p"), Path("r"), "sha256:" + "a" * 64, live=False)
        )


def test_malformed_approval_rejects_before_handler_boundaries(tmp_path, monkeypatch):
    plan_path, report = tmp_path / "plan.json", tmp_path / "record.json"
    _write_plan(plan_path)
    monkeypatch.setattr(cli, "validate_profiled_live_host_trust", _not_called)
    with pytest.raises(SystemExit) as caught:
        cli.main(_arguments(plan_path, report, "sha256:" + "A" * 64))
    assert caught.value.code == 2 and not report.exists()


def test_invalid_schema_v2_plan_blocks_before_provider_access(tmp_path, monkeypatch):
    plan_path, report = tmp_path / "plan.json", tmp_path / "record.json"
    plan_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(cli, "validate_profiled_live_host_trust", _not_called)
    monkeypatch.setattr(cli, "NetBoxProfileInventoryProvider", _not_called)
    with pytest.raises(SystemExit) as caught:
        cli.main(_arguments(plan_path, report, "sha256:" + "a" * 64))
    assert caught.value.code == 2 and not report.exists()


@pytest.mark.parametrize("symlink", [False, True])
def test_evidence_collision_blocks_before_execution(tmp_path, monkeypatch, symlink):
    plan_path, report, sentinel = (
        tmp_path / "plan.json",
        tmp_path / "record.json",
        tmp_path / "sentinel",
    )
    value = _write_plan(plan_path)
    sentinel.write_text("keep", encoding="utf-8")
    if symlink:
        report.symlink_to(sentinel)
    else:
        report.write_text("keep", encoding="utf-8")
    monkeypatch.setattr(cli, "validate_profiled_live_host_trust", lambda: None)
    monkeypatch.setattr(cli, "NetBoxProfileInventoryProvider", object)
    monkeypatch.setattr(cli, "OpenBaoSecretProvider", object)
    monkeypatch.setattr(cli, "ProfileReadOnlyAdapter", lambda **_kwargs: object())
    monkeypatch.setattr(cli, "ProfiledWriteAdapter", lambda **_kwargs: object())
    monkeypatch.setattr(cli, "execute_profiled_plan", _not_called)
    with pytest.raises(SystemExit) as caught:
        cli.main(_arguments(plan_path, report, value.digest))
    assert caught.value.code == 2 and sentinel.read_text(encoding="utf-8") == "keep"


@pytest.mark.parametrize(
    ("outcome", "status"),
    [
        (FinalOutcome.SUCCEEDED, 0),
        (FinalOutcome.RECOVERED, 0),
        (FinalOutcome.BLOCKED, 2),
        (FinalOutcome.AMBIGUOUS, 2),
        (FinalOutcome.AUTO_ROLLBACK_PENDING, 2),
        (FinalOutcome.CONFIRMATION_AMBIGUOUS, 2),
    ],
)
def test_profiled_deploy_composes_exact_boundaries_and_publishes_evidence(
    tmp_path, monkeypatch, capsys, outcome, status
):
    plan_path, report = tmp_path / "plan.json", tmp_path / "record.json"
    value = _write_plan(plan_path)
    record = _record(outcome)
    calls: list[object] = []

    monkeypatch.setattr(
        cli, "validate_profiled_live_host_trust", lambda: calls.append("trust")
    )
    monkeypatch.setattr(
        cli,
        "NetBoxProfileInventoryProvider",
        lambda: calls.append("inventory") or object(),
    )
    monkeypatch.setattr(
        cli, "OpenBaoSecretProvider", lambda: calls.append("secrets") or object()
    )
    monkeypatch.setattr(
        cli,
        "ProfileReadOnlyAdapter",
        lambda *, known_hosts: calls.append(("read", known_hosts)) or object(),
    )
    monkeypatch.setattr(
        cli,
        "ProfiledWriteAdapter",
        lambda *, known_hosts: calls.append(("write", known_hosts)) or object(),
    )

    def execute(*args):
        calls.append(("execute", args[0], args[1]))
        return record

    monkeypatch.setattr(cli, "execute_profiled_plan", execute)
    monkeypatch.setattr(cli, "NetBoxInventoryProvider", _not_called)
    monkeypatch.setattr(cli, "MultiVendorAdapter", _not_called)
    monkeypatch.setattr(cli, "deploy_plan", _not_called)
    assert cli.main(_arguments(plan_path, report, value.digest)) == status
    known_hosts = (
        cli.DEFAULT_PROFILED_LIVE_TRUST_ROOT / cli.PROFILED_LIVE_KNOWN_HOSTS_NAME
    )
    assert calls == [
        "trust",
        "inventory",
        "secrets",
        ("read", known_hosts),
        ("write", known_hosts),
        ("execute", value, value.digest),
    ]
    assert stat.S_IMODE(report.stat().st_mode) == 0o600
    assert report.read_text(encoding="utf-8") == record.model_dump_json(indent=2) + "\n"
    rendered = capsys.readouterr().out
    assert value.credential_reference not in rendered
    assert "secret-user" not in rendered and "secret-password" not in rendered
    assert "Managed-state acceptance attempted: False" in rendered
    assert "secret-user" not in report.read_text(encoding="utf-8")
