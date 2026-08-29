"""Offline tests for the SNMP observability SecretID issuer boundary."""

from __future__ import annotations

import stat
from pathlib import Path

import httpx
import pytest

from network_change_delivery.openbao_snmp_bootstrap import (
    SNMP_BOOTSTRAP_POLICY,
    SNMP_BOOTSTRAP_POLICY_NAME,
    SNMP_BOOTSTRAP_ROLE,
    SNMP_BOOTSTRAP_ROLE_NAME,
    OpenBaoSnmpBootstrap,
    SnmpMachineBootstrap,
    persist_snmp_machine_bootstrap,
)
from network_change_delivery.openbao_snmp_config import SNMP_OBSERVABILITY_ROLE_NAME
from network_change_delivery.secrets import SecretError


def data(value: dict[str, object]) -> dict[str, object]:
    return {"data": value}


def test_bootstrap_is_exact_one_use_issuer_and_returns_redacted_pair() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        path = request.url.path
        if request.method in {"PUT", "POST"} and not path.endswith(
            ("role-id", "secret-id")
        ):
            return httpx.Response(204)
        if path.endswith(f"policies/acl/{SNMP_BOOTSTRAP_POLICY_NAME}"):
            return httpx.Response(200, json=data({"policy": SNMP_BOOTSTRAP_POLICY}))
        if path.endswith(f"role/{SNMP_BOOTSTRAP_ROLE_NAME}"):
            return httpx.Response(200, json=data(SNMP_BOOTSTRAP_ROLE))
        if path.endswith(f"role/{SNMP_BOOTSTRAP_ROLE_NAME}/role-id"):
            return httpx.Response(200, json=data({"role_id": "bootstrap-role-id"}))
        if path.endswith(f"role/{SNMP_OBSERVABILITY_ROLE_NAME}/role-id"):
            return httpx.Response(200, json=data({"role_id": "source-role-id"}))
        if path.endswith("secret-id"):
            return httpx.Response(200, json=data({"secret_id": "bootstrap-secret-id"}))
        raise AssertionError(path)

    value = OpenBaoSnmpBootstrap(
        "https://openbao.example", transport=httpx.MockTransport(handler)
    ).configure("admin")
    assert value.bootstrap_role_id == "bootstrap-role-id"
    assert value.bootstrap_secret_id == "bootstrap-secret-id"
    assert value.source_role_id == "source-role-id"
    assert "bootstrap-secret-id" not in repr(value)
    assert SNMP_BOOTSTRAP_ROLE["token_no_default_policy"] is True
    assert SNMP_BOOTSTRAP_ROLE["token_num_uses"] == 1
    assert (
        f'path "auth/approle/role/{SNMP_OBSERVABILITY_ROLE_NAME}/secret-id" {{\n'
        '  capabilities = ["update"]\n}\n'
    ) == SNMP_BOOTSTRAP_POLICY


def test_machine_bootstrap_spends_one_token_for_exact_source_secretid() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/v1/auth/approle/login":
            return httpx.Response(
                200,
                json={
                    "auth": {
                        "client_token": "one-use-token",
                        "lease_duration": 60,
                        "token_policies": [SNMP_BOOTSTRAP_POLICY_NAME],
                        "policies": [SNMP_BOOTSTRAP_POLICY_NAME],
                        "identity_policies": [],
                    }
                },
            )
        return httpx.Response(200, json=data({"secret_id": "source-secret-id"}))

    source = OpenBaoSnmpBootstrap(
        "https://openbao.example", transport=httpx.MockTransport(handler)
    ).issue_source_login("bootstrap-role", "bootstrap-secret", "source-role")
    assert source.role_id == "source-role"
    assert source.secret_id == "source-secret-id"
    assert "source-secret-id" not in repr(source)
    assert requests[1].url.path == (
        f"/v1/auth/approle/role/{SNMP_OBSERVABILITY_ROLE_NAME}/secret-id"
    )
    assert requests[1].headers["X-Vault-Token"] == "one-use-token"


def test_machine_bootstrap_rejects_extra_policy_before_secretid_issue() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "auth": {
                    "client_token": "token",
                    "lease_duration": 60,
                    "token_policies": [SNMP_BOOTSTRAP_POLICY_NAME, "default"],
                    "policies": [SNMP_BOOTSTRAP_POLICY_NAME, "default"],
                }
            },
        )

    with pytest.raises(SecretError, match="bootstrap login failed"):
        OpenBaoSnmpBootstrap(
            "https://openbao.example", transport=httpx.MockTransport(handler)
        ).issue_source_login("bootstrap-role", "bootstrap-secret", "source-role")
    assert len(requests) == 1


def test_machine_bootstrap_private_files_are_distinct_and_restrictive(
    tmp_path: Path,
) -> None:
    paths = persist_snmp_machine_bootstrap(
        tmp_path / "observability",
        SnmpMachineBootstrap("bootstrap-role", "bootstrap-secret", "source-role"),
    )
    assert [path.name for path in paths] == [
        "bootstrap-role-id",
        "bootstrap-secret-id",
        "source-role-id",
    ]
    assert [path.read_text() for path in paths] == [
        "bootstrap-role",
        "bootstrap-secret",
        "source-role",
    ]
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in paths)
    assert stat.S_IMODE(paths[0].parent.stat().st_mode) == 0o700


def test_machine_bootstrap_rejects_checkout_and_symlink_roots(tmp_path: Path) -> None:
    value = SnmpMachineBootstrap("bootstrap-role", "bootstrap-secret", "source-role")
    with pytest.raises(SecretError):
        persist_snmp_machine_bootstrap(Path.cwd() / "forbidden-snmp-bootstrap", value)
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    link = tmp_path / "link"
    link.symlink_to(private, target_is_directory=True)
    with pytest.raises(SecretError):
        persist_snmp_machine_bootstrap(link, value)
