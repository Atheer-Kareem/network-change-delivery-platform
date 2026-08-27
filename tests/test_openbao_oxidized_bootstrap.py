from __future__ import annotations

import httpx

from network_change_delivery.openbao_oxidized_bootstrap import (
    BOOTSTRAP_POLICY,
    BOOTSTRAP_POLICY_NAME,
    BOOTSTRAP_ROLE,
    BOOTSTRAP_ROLE_NAME,
    OpenBaoOxidizedBootstrap,
)


def test_bootstrap_contract_is_exact_and_has_no_device_authority() -> None:
    assert (
        BOOTSTRAP_POLICY
        == """path "auth/approle/role/ncdp-oxidized-source/secret-id" {
  capabilities = ["update"]
}
"""
    )
    for forbidden in (
        "ncdp/data",
        "devices/",
        "sys/",
        "auth/*",
        "list",
        "read",
        "delete",
        "sudo",
    ):
        assert forbidden not in BOOTSTRAP_POLICY
    assert BOOTSTRAP_ROLE == {
        "bind_secret_id": True,
        "secret_id_ttl": 0,
        "secret_id_num_uses": 0,
        "token_no_default_policy": True,
        "token_policies": [BOOTSTRAP_POLICY_NAME],
        "token_ttl": 60,
        "token_max_ttl": 60,
        "token_num_uses": 1,
    }


def test_machine_login_issues_only_fresh_source_secretid() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/v1/auth/approle/login":
            return httpx.Response(200, json={"auth": {"client_token": "issuer-token"}})
        return httpx.Response(200, json={"data": {"secret_id": "fresh-source-secret"}})

    provider = OpenBaoOxidizedBootstrap(
        "http://127.0.0.1:8200", transport=httpx.MockTransport(handler)
    )
    result = provider.issue_source_login(
        "machine-role", "machine-secret", "source-role"
    )
    assert result.role_id == "source-role"
    assert result.secret_id == "fresh-source-secret"
    assert [request.url.path for request in requests] == [
        "/v1/auth/approle/login",
        "/v1/auth/approle/role/ncdp-oxidized-source/secret-id",
    ]
    assert requests[1].headers["X-Vault-Token"] == "issuer-token"
    rendered = " ".join(repr(item) for item in (provider, result))
    assert "machine-secret" not in rendered
    assert "issuer-token" not in rendered
    assert "fresh-source-secret" not in rendered


def test_configure_writes_and_reads_back_exact_contract() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        path = request.url.path
        if request.method in {"PUT", "POST"} and path in {
            f"/v1/sys/policies/acl/{BOOTSTRAP_POLICY_NAME}",
            f"/v1/auth/approle/role/{BOOTSTRAP_ROLE_NAME}",
        }:
            return httpx.Response(204)
        if path == f"/v1/sys/policies/acl/{BOOTSTRAP_POLICY_NAME}":
            return httpx.Response(200, json={"data": {"policy": BOOTSTRAP_POLICY}})
        if path == f"/v1/auth/approle/role/{BOOTSTRAP_ROLE_NAME}":
            return httpx.Response(200, json={"data": BOOTSTRAP_ROLE})
        if path.endswith("/role-id"):
            return httpx.Response(200, json={"data": {"role_id": "machine-role"}})
        return httpx.Response(200, json={"data": {"secret_id": "machine-secret"}})

    result = OpenBaoOxidizedBootstrap(
        "http://127.0.0.1:8200", transport=httpx.MockTransport(handler)
    ).configure("admin-token")
    assert result.role_id == "machine-role"
    assert result.secret_id == "machine-secret"
    assert all(
        request.headers.get("X-Vault-Token") == "admin-token" for request in requests
    )
    assert "machine-secret" not in repr(result)
