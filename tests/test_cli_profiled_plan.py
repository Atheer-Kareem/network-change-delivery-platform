"""CLI boundary tests for schema-v2 profiled ordinary planning."""

from __future__ import annotations

import stat
from pathlib import Path

import pytest
from test_profiled_planning import (
    FakeCollector,
    FakeInventory,
    FakeSecrets,
    profiled_device,
)

from network_change_delivery import cli
from network_change_delivery.architecture_contracts import AutomationProfileID
from network_change_delivery.models import InterfaceDescriptionIntent, InterfaceState
from network_change_delivery.profiled_planning import (
    ProfiledPlanningResult,
    plan_profiled_change,
)


def _intent() -> InterfaceDescriptionIntent:
    return InterfaceDescriptionIntent.model_validate(
        {
            "change_id": "CHG-PROFILED-CLI",
            "kind": "interface_description",
            "target": "core-02",
            "interface": "GigabitEthernet2",
            "desired": {"description": "managed-by-ncdp"},
        }
    )


def _result(description: str | None = "old") -> ProfiledPlanningResult:
    device, interface = profiled_device(AutomationProfileID.CAT8000V_IOSXE)
    intent = _intent()
    state = InterfaceState(
        observed_hostname=device.expected_hostname,
        interface=intent.interface,
        exists=True,
        protected=False,
        description=description,
    )
    return plan_profiled_change(
        intent, FakeInventory(device, interface), FakeSecrets(), FakeCollector(state)
    )


def _write_change(path: Path) -> None:
    path.write_text(
        """change_id: CHG-PROFILED-CLI
kind: interface_description
target: core-02
interface: GigabitEthernet2
desired:
  description: managed-by-ncdp
""",
        encoding="utf-8",
    )


def _arguments(change: Path, output: Path) -> list[str]:
    return [
        "profiled-plan",
        "--change",
        str(change),
        "--output",
        str(output),
        "--netbox",
        "--openbao",
    ]


def _not_called(*_args: object, **_kwargs: object) -> object:
    raise AssertionError("legacy boundary must not be used")


def test_profiled_plan_is_the_only_ordinary_planning_command() -> None:
    parser = cli.build_parser()
    parsed = parser.parse_args(
        [
            "profiled-plan",
            "--change",
            "intent.yaml",
            "--output",
            "plan.json",
            "--netbox",
            "--openbao",
        ]
    )
    assert parsed.handler is cli._run_profiled_plan
    choices = parser._subparsers._group_actions[0].choices
    assert "plan" not in choices
    assert "fleet-plan" not in choices
    assert "snmp-provisioning-plan" not in choices
    with pytest.raises(SystemExit):
        parser.parse_args(["profiled-plan"])


def test_profiled_plan_composes_only_profiled_read_only_boundaries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    change = tmp_path / "change.yaml"
    output = tmp_path / "plan.json"
    _write_change(change)
    calls: list[object] = []

    def trust() -> None:
        calls.append("trust")

    def inventory() -> object:
        calls.append("inventory")
        return object()

    def secrets() -> object:
        calls.append("secrets")
        return object()

    monkeypatch.setattr(cli, "validate_profiled_live_host_trust", trust)
    monkeypatch.setattr(cli, "NetBoxProfileInventoryProvider", inventory)
    monkeypatch.setattr(cli, "OpenBaoSecretProvider", secrets)

    def adapter(*, known_hosts: Path):
        calls.append(known_hosts)
        return object()

    monkeypatch.setattr(cli, "ProfileReadOnlyAdapter", adapter)
    monkeypatch.setattr(
        cli,
        "plan_profiled_change",
        lambda *_args: calls.append("plan") or _result(),
    )
    assert cli.main(_arguments(change, output)) == 0
    assert calls == [
        "trust",
        "inventory",
        "secrets",
        cli.DEFAULT_PROFILED_LIVE_TRUST_ROOT / cli.PROFILED_LIVE_KNOWN_HOSTS_NAME,
        "plan",
    ]
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    rendered = capsys.readouterr().out
    assert "openbao:kv-v2:ncdp/devices/1/ssh" in rendered
    assert "Plan schema version: 2" in rendered
    assert "Output:" in rendered
    assert "not-printed" not in rendered


@pytest.mark.parametrize("symlink", [False, True])
def test_profiled_plan_existing_output_blocks_before_trust_or_provider(
    symlink: bool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    change = tmp_path / "change.yaml"
    output = tmp_path / "plan.json"
    sentinel = tmp_path / "sentinel"
    _write_change(change)
    sentinel.write_text("keep", encoding="utf-8")
    if symlink:
        output.symlink_to(sentinel)
    else:
        output.write_text("keep", encoding="utf-8")
    monkeypatch.setattr(cli, "validate_profiled_live_host_trust", _not_called)
    monkeypatch.setattr(cli, "NetBoxProfileInventoryProvider", _not_called)
    with pytest.raises(SystemExit) as caught:
        cli.main(_arguments(change, output))
    assert caught.value.code == 2
    assert sentinel.read_text(encoding="utf-8") == "keep"


def test_profiled_plan_compliant_result_creates_no_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    change = tmp_path / "change.yaml"
    output = tmp_path / "plan.json"
    _write_change(change)
    monkeypatch.setattr(cli, "validate_profiled_live_host_trust", lambda: None)
    monkeypatch.setattr(cli, "NetBoxProfileInventoryProvider", object)
    monkeypatch.setattr(cli, "OpenBaoSecretProvider", object)
    monkeypatch.setattr(cli, "ProfileReadOnlyAdapter", lambda **_kwargs: object())
    monkeypatch.setattr(
        cli, "plan_profiled_change", lambda *_args: _result("managed-by-ncdp")
    )
    assert cli.main(_arguments(change, output)) == 0
    assert not output.exists()
    assert "already compliant" in capsys.readouterr().out


def test_profiled_trust_failure_prevents_provider_and_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    change = tmp_path / "change.yaml"
    output = tmp_path / "plan.json"
    _write_change(change)

    def trust_failure() -> None:
        raise ValueError("trust rejected")

    monkeypatch.setattr(cli, "validate_profiled_live_host_trust", trust_failure)
    monkeypatch.setattr(cli, "NetBoxProfileInventoryProvider", _not_called)
    monkeypatch.setattr(cli, "OpenBaoSecretProvider", _not_called)
    with pytest.raises(SystemExit) as caught:
        cli.main(_arguments(change, output))
    assert caught.value.code == 2
    assert not output.exists()


def test_cli_real_compliant_planner_writes_only_non_deployable_evidence(
    tmp_path, monkeypatch, capsys
):
    from network_change_delivery.profiled_planning import ProfiledComplianceRecord

    device, interface = profiled_device(AutomationProfileID.CAT8000V_IOSXE)
    change, output, compliance = (
        tmp_path / name for name in ("intent.yaml", "plan.json", "compliant.json")
    )
    _write_change(change)
    monkeypatch.setattr(cli, "validate_profiled_live_host_trust", lambda: None)
    monkeypatch.setattr(
        cli, "NetBoxProfileInventoryProvider", lambda: FakeInventory(device, interface)
    )
    monkeypatch.setattr(cli, "OpenBaoSecretProvider", FakeSecrets)
    monkeypatch.setattr(
        cli,
        "ProfileReadOnlyAdapter",
        lambda **_k: FakeCollector(_result("managed-by-ncdp").state),
    )
    assert (
        cli.main([*_arguments(change, output), "--compliance-output", str(compliance)])
        == 0
    )
    record = ProfiledComplianceRecord.model_validate_json(compliance.read_bytes())
    assert record.outcome == "COMPLIANT" and record.plan is None
    assert not output.exists() and stat.S_IMODE(compliance.stat().st_mode) == 0o600
    assert "Outcome: COMPLIANT" in capsys.readouterr().out
    # The same bytes cannot be used as deployment authority, even after approval.
    monkeypatch.setattr(cli, "validate_profiled_live_host_trust", _not_called)
    with pytest.raises(SystemExit) as caught:
        cli.main(
            [
                "profiled-deploy",
                "--plan",
                str(compliance),
                "--approve-digest",
                record.digest,
                "--report-json",
                str(tmp_path / "execution.json"),
                "--netbox",
                "--openbao",
                "--live",
            ]
        )
    assert caught.value.code == 2
    assert not (tmp_path / "execution.json").exists()


@pytest.mark.parametrize("collision", ["same", "existing"])
def test_compliant_output_collision_precedes_providers(
    tmp_path, monkeypatch, collision
):
    change, output = tmp_path / "intent.yaml", tmp_path / "plan.json"
    _write_change(change)
    compliance = output if collision == "same" else tmp_path / "compliant.json"
    if collision == "existing":
        compliance.write_text("keep")
    monkeypatch.setattr(cli, "validate_profiled_live_host_trust", _not_called)
    with pytest.raises(SystemExit) as caught:
        cli.main([*_arguments(change, output), "--compliance-output", str(compliance)])
    assert caught.value.code == 2
    assert not output.exists()
