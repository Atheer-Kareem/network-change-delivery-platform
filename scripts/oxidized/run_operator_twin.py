#!/usr/bin/env python3
"""Run the accepted local operator CML twin without exposing authority values."""

from __future__ import annotations

import argparse
import json
import os
import re
import ssl
import stat
import subprocess
import sys
from pathlib import Path

import httpx

from network_change_delivery.inventory import NetBoxInventoryProvider
from network_change_delivery.openbao_oxidized_bootstrap import OpenBaoOxidizedBootstrap
from network_change_delivery.secrets import OpenBaoSecretProvider

ROOT = Path(__file__).resolve().parents[2]
TERRAFORM_ROOT = ROOT / "infrastructure/cml"
SAFE_UI = ROOT / "scripts/terraform_cml_safe_ui.py"
STATE_ROOT = Path("/Users/netdevops/.local/state/ncdp/terraform/cml")
STATE_PATH = STATE_ROOT / "terraform.tfstate"
DATA_PATH = STATE_ROOT / "operator-data"
OXIDIZED_STATE = Path("/Users/netdevops/.local/state/ncdp/oxidized")
OXIDIZED_CONFIG = Path("/Users/netdevops/.config/ncdp/oxidized")
EXPECTED_NODES = frozenset(
    {"system_bridge", "management_switch", "core_02", "edge_junos_01"}
)
EXPECTED_LINKS = frozenset(
    {
        "system_bridge_management",
        "management_core_02",
        "management_edge_junos_01",
        "core_02_edge_junos_01",
    }
)


class OperatorTwinError(ValueError):
    """Secret-free local operator lifecycle failure."""


def _private(path: Path) -> str:
    metadata = path.lstat()
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or metadata.st_mode & 0o077
        or metadata.st_nlink != 1
    ):
        raise OperatorTwinError("operator authority metadata rejected")
    value = path.read_text().strip()
    if not value:
        raise OperatorTwinError("operator authority unavailable")
    return value


def _cml_token() -> str:
    address = os.environ.get("CML2_ADDRESS")
    certificate = os.environ.get("CML2_CACERT")
    username = os.environ.get("NCDP_CML_STAGING_USERNAME")
    password = os.environ.get("NCDP_CML_STAGING_PASSWORD")
    if not all((address, certificate, username, password)):
        raise OperatorTwinError("CML operator identity unavailable")
    context = ssl.create_default_context(cadata=certificate)
    try:
        response = httpx.post(
            f"{address.rstrip('/')}/api/v0/authenticate",
            json={"username": username, "password": password},
            verify=context,
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError):
        raise OperatorTwinError("CML operator authentication failed") from None
    token = payload if isinstance(payload, str) else payload.get("token")
    if not isinstance(token, str) or not token:
        raise OperatorTwinError("CML operator authentication failed")
    return token


def _environment(lifecycle: str) -> dict[str, str]:
    inventory = NetBoxInventoryProvider(
        "http://127.0.0.1:8000", _private(OXIDIZED_CONFIG / "netbox-token")
    )
    bootstrap = OpenBaoOxidizedBootstrap("http://127.0.0.1:8200")
    source_login = bootstrap.issue_source_login(
        _private(OXIDIZED_STATE / "operator/bootstrap-role-id"),
        _private(OXIDIZED_STATE / "operator/bootstrap-secret-id"),
        _private(OXIDIZED_STATE / "operator/role-id"),
    )
    secrets = OpenBaoSecretProvider(
        "http://127.0.0.1:8200", source_login.role_id, source_login.secret_id
    )
    core = inventory.resolve("core-02")
    edge = inventory.resolve("edge-junos-01")
    if (
        core.inventory_object_id != "netbox:dcim.device:1"
        or core.host != "192.168.4.14"
        or core.platform != "cisco_iosxe"
        or edge.inventory_object_id != "netbox:dcim.device:2"
        or edge.host != "192.168.4.20"
        or edge.platform != "junos"
    ):
        raise OperatorTwinError("operator inventory authority rejected")
    core_credentials = secrets.load(core)
    edge_credentials = secrets.load(edge)
    verifier = subprocess.run(
        [
            "/opt/homebrew/bin/openssl",
            "passwd",
            "-6",
            "-salt",
            "ncdpedgejunos01",
            "-stdin",
        ],
        input=edge_credentials.password,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    if not re.fullmatch(r"\$6\$ncdpedgejunos01\$[A-Za-z0-9./]{86}", verifier):
        raise OperatorTwinError("Junos verifier derivation failed")
    environment = os.environ.copy()
    environment.update(
        {
            "CML2_TOKEN": _cml_token(),
            "TF_DATA_DIR": str(DATA_PATH),
            "TF_VAR_twin_lifecycle_state": lifecycle,
            "TF_VAR_core_02_bootstrap_hostname": "core-02",
            "TF_VAR_core_02_bootstrap_management_cidr": "192.168.4.14/24",
            "TF_VAR_core_02_bootstrap_username": core_credentials.username,
            "TF_VAR_core_02_bootstrap_password": core_credentials.password,
            "TF_VAR_edge_junos_01_bootstrap_hostname": "edge-junos-01",
            "TF_VAR_edge_junos_01_bootstrap_management_cidr": "192.168.4.20/24",
            "TF_VAR_edge_junos_01_bootstrap_username": edge_credentials.username,
            "TF_VAR_edge_junos_01_bootstrap_password_hash": verifier,
        }
    )
    return environment


def _plain(arguments: list[str], environment: dict[str, str]) -> str:
    result = subprocess.run(
        ["terraform", f"-chdir={TERRAFORM_ROOT}", *arguments],
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise OperatorTwinError("Terraform structural operation failed")
    return result.stdout


def _safe(arguments: list[str], environment: dict[str, str]) -> list[str]:
    terraform = subprocess.Popen(
        [
            "terraform",
            f"-chdir={TERRAFORM_ROOT}",
            *arguments,
            "-json",
            "-input=false",
        ],
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    assert terraform.stdout is not None
    renderer = subprocess.run(
        [sys.executable, str(SAFE_UI)],
        stdin=terraform.stdout,
        text=True,
        capture_output=True,
        check=False,
    )
    terraform.stdout.close()
    terraform_code = terraform.wait()
    lines = renderer.stdout.splitlines()
    for line in lines:
        print(line, flush=True)
    if terraform_code or renderer.returncode:
        raise OperatorTwinError("safe Terraform operation failed")
    return lines


def _changes(lines: list[str]) -> dict[str, str]:
    changes = {}
    for line in lines:
        match = re.fullmatch(r"planned resource=([^ ]+) action=([^ ]+)(?: .*)?", line)
        if match:
            changes[match.group(1)] = match.group(2)
    return changes


def _expected_addresses() -> set[str]:
    return (
        {"cml2_lab.twin", "module.twin.cml2_lifecycle.twin"}
        | {f"module.twin.cml2_node.{role}" for role in EXPECTED_NODES}
        | {f"module.twin.cml2_link.{role}" for role in EXPECTED_LINKS}
    )


def _prepare(environment: dict[str, str]) -> None:
    STATE_ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    STATE_ROOT.chmod(0o700)
    DATA_PATH.mkdir(mode=0o700, exist_ok=True)
    DATA_PATH.chmod(0o700)
    _plain(
        [
            "init",
            "-input=false",
            "-lockfile=readonly",
            f"-backend-config=path={STATE_PATH}",
        ],
        environment,
    )


def _outputs(environment: dict[str, str]) -> dict[str, object]:
    payload = json.loads(_plain(["output", "-json"], environment))
    return {key: item["value"] for key, item in payload.items()}


def run(action: str) -> None:
    lifecycle = "STARTED" if action in {"start", "destroy"} else "DEFINED_ON_CORE"
    environment = _environment(lifecycle)
    _prepare(environment)
    if action == "create":
        if _changes(_safe(["plan"], environment)) != dict.fromkeys(
            _expected_addresses(), "create"
        ):
            raise OperatorTwinError("Terraform create graph was not exactly 10 creates")
        _safe(["apply", "-auto-approve"], environment)
    elif action == "start":
        if _changes(_safe(["plan"], environment)) != {
            "module.twin.cml2_lifecycle.twin": "update"
        }:
            raise OperatorTwinError("Terraform STARTED graph was not lifecycle-only")
        _safe(["apply", "-auto-approve"], environment)
    elif action == "destroy":
        if _changes(_safe(["plan", "-destroy"], environment)) != dict.fromkeys(
            _expected_addresses(), "delete"
        ):
            raise OperatorTwinError(
                "Terraform destroy graph was not exactly 10 deletes"
            )
        _safe(["destroy", "-auto-approve"], environment)
    elif action != "status":
        raise OperatorTwinError("operator action rejected")
    if STATE_PATH.exists():
        STATE_PATH.chmod(0o600)
    managed = [
        line for line in _plain(["state", "list"], environment).splitlines() if line
    ]
    print(f"managed_resources={len(managed)}")
    if managed:
        outputs = _outputs(environment)
        print(f"lab_id={outputs['twin_lab_id']}")
        for role, node_id in sorted(outputs["twin_node_ids"].items()):
            print(f"node_id {role}={node_id}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("status", "create", "start", "destroy"))
    arguments = parser.parse_args()
    try:
        run(arguments.action)
    except OperatorTwinError as error:
        print(f"operator CML lifecycle failed: {error}", file=sys.stderr)
        return 2
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(
            f"operator CML lifecycle failed: bounded {type(error).__name__}",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
