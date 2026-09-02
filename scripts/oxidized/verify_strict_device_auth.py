#!/usr/bin/env python3
"""Authenticate the exact profiled fleet with dedicated strict host trust only."""

from __future__ import annotations

import base64
import hashlib
import os
import sys
from pathlib import Path

import paramiko

from network_change_delivery.openbao_oxidized_bootstrap import OpenBaoOxidizedBootstrap
from network_change_delivery.oxidized_host_trust import (
    DEFAULT_TRUST_ROOT,
    validate_host_trust,
)
from network_change_delivery.profile_inventory import NetBoxProfileInventoryProvider
from network_change_delivery.secrets import OpenBaoSecretProvider

STATE_ROOT = Path("/Users/netdevops/.local/state/ncdp/oxidized")
CONFIG_ROOT = Path("/Users/netdevops/.config/ncdp/oxidized")


class StrictAuthError(ValueError):
    """Bounded authentication failure without device output."""


def _private(path: Path) -> str:
    value = path.read_text().strip()
    metadata = path.lstat()
    if (
        not value
        or metadata.st_uid != os.getuid()
        or metadata.st_mode & 0o077
        or metadata.st_nlink != 1
    ):
        raise StrictAuthError("strict authentication authority rejected")
    return value


def main() -> int:
    try:
        trust = validate_host_trust(DEFAULT_TRUST_ROOT)
        inventory = NetBoxProfileInventoryProvider(
            "http://127.0.0.1:8000", _private(CONFIG_ROOT / "netbox-token")
        )
        bootstrap = OpenBaoOxidizedBootstrap("http://127.0.0.1:8200")
        login = bootstrap.issue_source_login(
            _private(STATE_ROOT / "operator/bootstrap-role-id"),
            _private(STATE_ROOT / "operator/bootstrap-secret-id"),
            _private(STATE_ROOT / "operator/role-id"),
        )
        secrets = OpenBaoSecretProvider(
            "http://127.0.0.1:8200", login.role_id, login.secret_id
        )
        for item in trust.nodes:
            device = inventory.resolve(item.stable_name)
            credentials = secrets.load(device)
            client = paramiko.SSHClient()
            client.load_host_keys(str(DEFAULT_TRUST_ROOT / "known_hosts"))
            client.set_missing_host_key_policy(paramiko.RejectPolicy())
            client.connect(
                item.management_ip,
                port=22,
                username=credentials.username,
                password=credentials.password,
                look_for_keys=False,
                allow_agent=False,
                timeout=10,
                auth_timeout=10,
                banner_timeout=10,
            )
            transport = client.get_transport()
            if transport is None:
                raise StrictAuthError("strict authentication transport unavailable")
            key = transport.get_remote_server_key()
            fingerprint = base64.b64encode(hashlib.sha256(key.asbytes()).digest())
            observed = "SHA256:" + fingerprint.decode().rstrip("=")
            client.close()
            if observed != item.fingerprint:
                raise StrictAuthError("strict authentication host key changed")
            print(f"{item.node} {item.stable_name} strict_auth=PASS command_count=0")
    except (OSError, ValueError, paramiko.SSHException):
        print("strict device authentication failed", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
