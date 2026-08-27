from __future__ import annotations

import os
import stat
from pathlib import Path

import httpx
import pytest

from network_change_delivery.openbao_oxidized_config import (
    OXIDIZED_POLICY,
    OXIDIZED_POLICY_NAME,
    OXIDIZED_ROLE,
    OXIDIZED_ROLE_NAME,
    OpenBaoOxidizedConfigurator,
    OxidizedAppRoleBootstrap,
    persist_oxidized_bootstrap,
)
from network_change_delivery.secrets import SecretError

ADMIN = "private-admin-token"


def handler(requests: list[httpx.Request], *, broaden: str | None = None):
    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        path = request.url.path
        if path == "/v1/sys/auth":
            return httpx.Response(200, json={"data": {"approle/": {"type": "approle"}}})
        if path == f"/v1/sys/policies/acl/{OXIDIZED_POLICY_NAME}":
            if request.method == "PUT":
                return httpx.Response(204)
            policy = OXIDIZED_POLICY
            if broaden == "policy":
                policy += 'path "ncdp/data/devices/3/ssh" { capabilities=["read"] }'
            return httpx.Response(200, json={"data": {"policy": policy}})
        role_path = f"/v1/auth/approle/role/{OXIDIZED_ROLE_NAME}"
        if path == role_path:
            if request.method == "POST":
                return httpx.Response(204)
            role = dict(OXIDIZED_ROLE)
            if broaden == "role":
                role["token_num_uses"] = 0
            return httpx.Response(200, json={"data": role})
        if path == f"{role_path}/role-id":
            return httpx.Response(200, json={"data": {"role_id": "private-role-id"}})
        if path == f"{role_path}/secret-id":
            return httpx.Response(
                200, json={"data": {"secret_id": "private-secret-id"}}
            )
        raise AssertionError(path)

    return respond


def test_configures_exact_read_only_approle() -> None:
    requests: list[httpx.Request] = []
    bootstrap = OpenBaoOxidizedConfigurator(
        "https://openbao.example",
        ADMIN,
        transport=httpx.MockTransport(handler(requests)),
    ).configure()
    assert "private-role-id" not in repr(bootstrap)
    assert "private-secret-id" not in repr(bootstrap)
    assert OXIDIZED_POLICY.count("path ") == 2
    assert "devices/1/ssh" in OXIDIZED_POLICY
    assert "devices/2/ssh" in OXIDIZED_POLICY
    assert "devices/3" not in OXIDIZED_POLICY
    assert "*" not in OXIDIZED_POLICY
    assert 'capabilities = ["read"]' in OXIDIZED_POLICY
    assert all(
        word not in OXIDIZED_POLICY for word in ("create", "update", "delete", "list")
    )
    assert OXIDIZED_ROLE["bind_secret_id"] is True
    assert OXIDIZED_ROLE["secret_id_ttl"] == 1800
    assert OXIDIZED_ROLE["secret_id_num_uses"] == 10
    assert OXIDIZED_ROLE["token_num_uses"] == 1
    assert OXIDIZED_ROLE["token_no_default_policy"] is True
    assert all(request.headers["X-Vault-Token"] == ADMIN for request in requests)


@pytest.mark.parametrize("broaden", ["policy", "role"])
def test_readback_drift_fails_closed(broaden: str) -> None:
    with pytest.raises(SecretError, match="verification failed"):
        OpenBaoOxidizedConfigurator(
            "https://openbao.example",
            ADMIN,
            transport=httpx.MockTransport(handler([], broaden=broaden)),
        ).configure()


def test_configurator_does_not_touch_buildkite_or_existing_approles() -> None:
    requests: list[httpx.Request] = []
    OpenBaoOxidizedConfigurator(
        "https://openbao.example",
        ADMIN,
        transport=httpx.MockTransport(handler(requests)),
    ).configure()
    paths = {request.url.path for request in requests}
    assert not any("jwt" in path or "buildkite" in path for path in paths)
    assert all(
        OXIDIZED_ROLE_NAME in path
        or OXIDIZED_POLICY_NAME in path
        or path == "/v1/sys/auth"
        for path in paths
    )
    assert ADMIN not in b"".join(request.content for request in requests).decode()


def test_bootstrap_refresh_verifies_without_reconfiguring_resources() -> None:
    requests: list[httpx.Request] = []
    OpenBaoOxidizedConfigurator(
        "https://openbao.example",
        ADMIN,
        transport=httpx.MockTransport(handler(requests)),
    ).issue_bootstrap()
    policy_path = f"/v1/sys/policies/acl/{OXIDIZED_POLICY_NAME}"
    role_path = f"/v1/auth/approle/role/{OXIDIZED_ROLE_NAME}"
    assert not any(
        request.method in {"PUT", "POST"}
        and request.url.path in {policy_path, role_path}
        for request in requests
    )
    assert any(request.url.path == f"{role_path}/secret-id" for request in requests)


def test_bootstrap_is_persisted_privately(tmp_path: Path) -> None:
    root = tmp_path / "oxidized"
    paths = persist_oxidized_bootstrap(
        root, OxidizedAppRoleBootstrap("private-role-id", "private-secret-id")
    )
    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    assert stat.S_IMODE((root / "operator").stat().st_mode) == 0o700
    for path in paths:
        metadata = path.stat()
        assert stat.S_IMODE(metadata.st_mode) == 0o600
        assert metadata.st_uid == os.getuid()
        assert metadata.st_nlink == 1
        assert stat.S_ISREG(metadata.st_mode)


@pytest.mark.parametrize("relative", [Path(), Path("nested")])
def test_bootstrap_rejects_checkout_and_descendant(relative: Path) -> None:
    root = Path(__file__).parents[1] / relative
    with pytest.raises(SecretError, match="root rejected"):
        persist_oxidized_bootstrap(
            root, OxidizedAppRoleBootstrap("private-role-id", "private-secret-id")
        )


def test_bootstrap_rejects_audit_namespace(tmp_path: Path) -> None:
    with pytest.raises(SecretError, match="root rejected"):
        persist_oxidized_bootstrap(
            tmp_path / "audit" / "oxidized",
            OxidizedAppRoleBootstrap("private-role-id", "private-secret-id"),
        )


def test_bootstrap_rejects_symlink_and_wrong_mode_roots(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir(mode=0o700)
    link = tmp_path / "oxidized-link"
    link.symlink_to(target, target_is_directory=True)
    with pytest.raises(SecretError, match="root rejected"):
        persist_oxidized_bootstrap(
            link, OxidizedAppRoleBootstrap("private-role-id", "private-secret-id")
        )
    wrong_mode = tmp_path / "oxidized"
    wrong_mode.mkdir(mode=0o755)
    with pytest.raises(SecretError, match="root rejected"):
        persist_oxidized_bootstrap(
            wrong_mode,
            OxidizedAppRoleBootstrap("private-role-id", "private-secret-id"),
        )
