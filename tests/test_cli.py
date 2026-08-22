"""Tests for the command-line interface."""

from __future__ import annotations

import subprocess
import sys

import pytest

from network_change_delivery.cli import main


def test_explicit_help_exits_successfully(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Explicit help displays usage successfully."""
    with pytest.raises(SystemExit) as exit_info:
        main(["--help"])
    assert exit_info.value.code == 0
    assert "Network Change Delivery Platform" in capsys.readouterr().out


def test_no_arguments_returns_success(capsys: pytest.CaptureFixture[str]) -> None:
    """An empty argument sequence prints help without raising."""
    assert main([]) == 0
    assert "usage: ncdp" in capsys.readouterr().out


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    """The CLI discovers and displays the installed package version."""
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])
    assert exit_info.value.code == 0
    assert capsys.readouterr().out == "ncdp 0.1.0\n"


def test_module_invocation() -> None:
    """The package is executable as a Python module."""
    completed = subprocess.run(
        [sys.executable, "-m", "network_change_delivery", "--version"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0
    assert completed.stdout == "ncdp 0.1.0\n"


@pytest.mark.parametrize("command", ["plan", "deploy"])
def test_cli_rejects_both_inventory_sources(command: str) -> None:
    arguments = [command, "--inventory", "inventory.yaml", "--netbox"]
    with pytest.raises(SystemExit) as exit_info:
        main(arguments)
    assert exit_info.value.code == 2


@pytest.mark.parametrize("command", ["plan", "deploy"])
def test_cli_requires_one_inventory_source(command: str) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main([command])
    assert exit_info.value.code == 2
