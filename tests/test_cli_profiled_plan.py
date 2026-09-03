"""CLI boundary tests for schema-v2 profiled ordinary planning."""

from __future__ import annotations

import stat
from pathlib import Path

import pytest
from test_profiled_planning import profiled_device

from network_change_delivery import cli
from network_change_delivery.architecture_contracts import AutomationProfileID
from network_change_delivery.models import InterfaceDescriptionIntent, InterfaceState
from network_change_delivery.profiled_planning import (
    ProfiledPlanningResult,
    build_profiled_plan,
)
from network_change_delivery.secrets import CredentialReference


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
    credential = CredentialReference("openbao", "openbao:kv-v2:ncdp/devices/1/ssh")
    plan = (
        None
        if description == intent.desired.description
        else build_profiled_plan(
            intent, device, interface, state, credential=credential
        )
    )
    return ProfiledPlanningResult(
        plan=plan,
        state=state,
        credential=credential,
        message=(
            "interface is already compliant; no profiled plan produced"
            if plan is None
            else "profiled immutable plan created"
        ),
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


def test_profiled_plan_parser_is_separate_and_requires_authorities() -> None:
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
    assert (
        parser.parse_args(
            [
                "plan",
                "--change",
                "intent.yaml",
                "--output",
                "plan.json",
                "--inventory",
                "inventory.yaml",
                "--environment-secrets",
            ]
        ).handler
        is cli._run_plan
    )
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
    monkeypatch.setattr(cli, "NetBoxInventoryProvider", _not_called)
    monkeypatch.setattr(cli, "MultiVendorAdapter", _not_called)
    monkeypatch.setattr(cli, "deploy_plan", _not_called)

    assert cli.main(_arguments(change, output)) == 0
    assert calls == [
        "trust",
        "inventory",
        "secrets",
        cli.DEFAULT_PROFILED_LIVE_TRUST_ROOT / cli.KNOWN_HOSTS_NAME,
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
