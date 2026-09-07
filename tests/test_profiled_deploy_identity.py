"""Persistent deploy identity and sanitized planning diagnostics; all HTTP is fake."""

import importlib.util
import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
import test_profiled_buildkite_delivery as delivery_tests
from test_profiled_buildkite_delivery import environment
from test_profiled_planning import (
    FakeCollector,
    FakeInventory,
    observed,
    profiled_device,
)

from network_change_delivery.architecture_contracts import AutomationProfileID
from network_change_delivery.inventory import InventoryError
from network_change_delivery.openbao_profiled_deploy_config import (
    POLICY,
    POLICY_NAME,
    POLICY_PATH,
    ROLE,
    ROLE_PATH,
    OpenBaoProfiledDeployConfigurator,
)
from network_change_delivery.secrets import OpenBaoSecretProvider, SecretError

ROOT = Path(__file__).parents[1]
URL = "https://openbao.example"
context = delivery_tests.context
driver = delivery_tests.driver
plan = delivery_tests.plan


@pytest.fixture
def helper():
    spec = importlib.util.spec_from_file_location(
        "install_identity",
        ROOT / "scripts/buildkite/install_profiled_deploy_identity.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Bao:
    def __init__(self):
        self.role = {}
        self.policy = {}
        self.calls = []
        self.issued = 0
        self.tokens = {}
        self.reject = None

    def handle(self, request):
        self.calls.append(request)
        path = request.url.path
        body = json.loads(request.content) if request.content else {}
        if path == self.reject:
            raise httpx.ReadTimeout("private-token", request=request)
        if path in (ROLE_PATH, POLICY_PATH):
            current = self.role if path == ROLE_PATH else self.policy
            if request.method == "GET":
                return httpx.Response(200 if current else 404, json={"data": current})
            if path == ROLE_PATH:
                self.role = body
            else:
                self.policy = body
            return httpx.Response(204)
        if path == ROLE_PATH + "/role-id":
            return httpx.Response(200, json={"data": {"role_id": "private-role"}})
        if path == ROLE_PATH + "/secret-id":
            self.issued += 1
            return httpx.Response(
                200,
                json={
                    "data": {
                        "secret_id": "private-secret",
                        "secret_id_ttl": 0,
                        "secret_id_num_uses": 0,
                    }
                },
            )
        if path == ROLE_PATH + "/secret-id/lookup":
            assert body == {"secret_id": "private-secret"}
            return httpx.Response(
                200,
                json={
                    "data": {
                        "secret_id_ttl": 0,
                        "secret_id_num_uses": 0,
                        "expiration_time": "0001-01-01T00:00:00Z",
                    }
                },
            )
        if path == "/v1/auth/approle/login":
            assert body == {"role_id": "private-role", "secret_id": "private-secret"}
            token = "private-token-" + str(len(self.tokens))
            self.tokens[token] = 1
            return httpx.Response(
                200, json={"auth": {"client_token": token, "lease_duration": 300}}
            )
        if path == "/v1/auth/token/lookup":
            assert request.headers["X-Vault-Token"] == "private-admin"
            assert self.tokens[body["token"]] == 1
            return httpx.Response(
                200,
                json={
                    "data": {
                        "ttl": 299,
                        "creation_ttl": 300,
                        "num_uses": 1,
                        "policies": [POLICY_NAME],
                    }
                },
            )
        if path in ("/v1/ncdp/data/devices/1/ssh", "/v1/ncdp/data/devices/2/ssh"):
            token = request.headers["X-Vault-Token"]
            assert request.method == "GET" and self.tokens[token] == 1
            self.tokens[token] -= 1
            return httpx.Response(
                200,
                json={
                    "data": {
                        "data": {
                            "username": "private-user",
                            "password": "private-password",
                        }
                    }
                },
            )
        raise AssertionError("Unexpected OpenBao path")

    def operator(self):
        return OpenBaoProfiledDeployConfigurator(
            URL, "private-admin", transport=httpx.MockTransport(self.handle)
        )


@pytest.fixture
def protected(tmp_path):
    hooks = tmp_path.resolve() / "hooks/ncdp-deploy"
    hooks.mkdir(parents=True, mode=0o700)
    external = hooks.parent.parent / "env/ncdp-deploy.env"
    external.parent.mkdir()
    external.write_text(
        f"NCDP_OPENBAO_URL={URL}\nNCDP_NETBOX_URL=https://netbox.example\nNCDP_NETBOX_TOKEN=private-netbox\n"
    )
    external.chmod(0o600)
    audit = tmp_path.resolve() / "audit"
    audit.mkdir(mode=0o700)
    original = (
        f"source {external}\nNCDP_BUILDKITE_PIPELINE_ID=keep-pipeline\n"
        "NCDP_PROFILED_DELIVERY_STATE_ROOT=/keep/state\n"
        f"NCDP_AUDIT_STORE_ROOT={audit}\n"
        'NCDP_OPENBAO_ROLE_ID="$(< /old/operator/approle-role-id)"\n'
        'NCDP_OPENBAO_SECRET_ID="$(< /old/operator/approle-secret-id)"\n'
        "# preserve comment\n"
    ).encode()
    (hooks / "profiled.env").write_bytes(original)
    (hooks / "profiled.env").chmod(0o600)
    return hooks, tmp_path.resolve() / "identity", original


def test_install_reuses_pair_and_preserves_settings_atomically(
    helper, protected, monkeypatch, capsys
):
    hooks, state, original = protected
    bao = Bao()
    replace = Path.replace

    def checked_replace(source, destination):
        assert source.stat().st_mode & 0o777 == 0o600
        if destination.name == "profiled.env":
            assert destination.read_bytes() == original
        return replace(source, destination)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "replace", checked_replace)
        helper.install(hooks, state, bao.operator())
    first = (hooks / "profiled.env").read_bytes()
    assert b"/old/operator" not in first
    assert b"NCDP_BUILDKITE_PIPELINE_ID=keep-pipeline\n" in first
    assert b"NCDP_PROFILED_DELIVERY_STATE_ROOT=/keep/state\n" in first
    assert b"# preserve comment\n" in first
    assert (
        next(
            line
            for line in original.splitlines()
            if line.startswith(b"NCDP_AUDIT_STORE_ROOT=")
        )
        in first
    )
    helper.install(hooks, state, bao.operator())
    assert (hooks / "profiled.env").read_bytes() == first
    assert bao.issued == 1
    assert len([r for r in bao.calls if r.url.path == "/v1/auth/approle/login"]) == 4
    assert all(v == 0 for v in bao.tokens.values())
    assert bao.role == ROLE and bao.policy == {"policy": POLICY}
    for p in (hooks / "profiled.env", state / "approle.env"):
        assert p.stat().st_mode & 0o777 == 0o600
        assert p.stat().st_uid == os.getuid()
    assert not (state / "issuance-pending").exists()
    assert not list(state.glob(".identity-*"))
    # A new job shell sees the dedicated pair without restarting any agent.
    result = subprocess.run(
        [
            "bash",
            "-c",
            'set -a; source "$1"; [[ "$NCDP_OPENBAO_ROLE_ID" == private-role && '
            '"$NCDP_OPENBAO_SECRET_ID" == private-secret ]]',
            "test",
            str(hooks / "profiled.env"),
        ],
        capture_output=True,
    )
    assert result.returncode == 0 and not result.stdout and not result.stderr
    assert "private" not in str(capsys.readouterr())


@pytest.mark.parametrize(
    "case", ["file-mode", "directory-mode", "symlink", "wrong-url"]
)
def test_filesystem_admission_before_openbao(helper, protected, case):
    hooks, state, original = protected
    if case == "file-mode":
        (hooks / "profiled.env").chmod(0o644)
    elif case == "directory-mode":
        hooks.chmod(0o755)
    elif case == "symlink":
        (hooks / "original").write_bytes(original)
        (hooks / "profiled.env").unlink()
        (hooks / "profiled.env").symlink_to(hooks / "original")
    operator = Bao().operator()
    if case == "wrong-url":
        operator.url = "https://wrong.example"
    with pytest.raises(ValueError):
        helper.install(hooks, state, operator)


def test_uncertain_issuance_is_not_replayed(helper, protected):
    hooks, state, original = protected
    bao = Bao()
    bao.reject = ROLE_PATH + "/secret-id"
    for _ in range(2):
        with pytest.raises((ValueError, SecretError)):
            helper.install(hooks, state, bao.operator())
    assert len([r for r in bao.calls if r.url.path == bao.reject]) == 1
    assert (hooks / "profiled.env").read_bytes() == original
    assert (state / "issuance-pending").exists()


def test_failed_env_publication_reuses_persisted_pair(helper, protected, monkeypatch):
    hooks, state, original = protected
    bao = Bao()
    replace = Path.replace

    def fail(source, target):
        if target.name == "profiled.env":
            raise OSError("private")
        return replace(source, target)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "replace", fail)
        with pytest.raises(OSError):
            helper.install(hooks, state, bao.operator())
    assert (hooks / "profiled.env").read_bytes() == original
    helper.install(hooks, state, bao.operator())
    assert bao.issued == 1


@pytest.mark.parametrize("buildkite", [True, False])
def test_installer_explicit_operator_authority_only(
    helper, monkeypatch, capsys, buildkite
):
    monkeypatch.setattr(
        helper.os, "environ", {"BUILDKITE_BUILD_ID": "job"} if buildkite else {}
    )
    monkeypatch.setattr("sys.argv", ["install"])
    assert helper.main() == 2
    assert "No device access" in capsys.readouterr().out


def test_persistent_role_does_not_grant_admin_or_devices_8_9():
    assert ROLE["secret_id_ttl"] == ROLE["secret_id_num_uses"] == 0
    assert ROLE["token_ttl"] == ROLE["token_max_ttl"] == 300
    assert ROLE["token_num_uses"] == 1 and ROLE["token_no_default_policy"]
    assert POLICY.count('capabilities = ["read"]') == 2
    assert "/1/ssh" in POLICY and "/2/ssh" in POLICY
    assert not any(
        s in POLICY
        for s in ("*", "update", "create", "delete", "/8/", "/9/", "sys/", "auth/")
    )


@pytest.mark.parametrize(
    "bad", ["expiry", "uses", "token-ttl", "token-uses", "extra-policy"]
)
def test_rejects_bad_installed_or_token_contract(helper, protected, bad):
    hooks, state, _ = protected
    bao = Bao()
    handler = bao.handle

    def response(request):
        result = handler(request)
        if request.url.path.endswith("/secret-id/lookup") and bad in {"expiry", "uses"}:
            data = result.json()["data"]
            data["secret_id_ttl" if bad == "expiry" else "secret_id_num_uses"] = 10
            return httpx.Response(200, json={"data": data})
        if request.url.path == "/v1/auth/token/lookup":
            data = result.json()["data"]
            if bad == "token-ttl":
                data["ttl"] = 601
            elif bad == "token-uses":
                data["num_uses"] = 0
            elif bad == "extra-policy":
                data["policies"].append("default")
            return httpx.Response(200, json={"data": data})
        return result

    operator = OpenBaoProfiledDeployConfigurator(
        URL, "private-admin", transport=httpx.MockTransport(response)
    )
    with pytest.raises(SecretError):
        helper.install(hooks, state, operator)
    assert not any("/data/devices/" in r.url.path for r in bao.calls)


@pytest.mark.parametrize("case", ["403", "404", "timeout", "payload"])
def test_credential_read_has_own_closed_phase(
    driver, context, tmp_path, monkeypatch, capsys, case
):
    device, interface = profiled_device(AutomationProfileID.CAT8000V_IOSXE)

    def respond(request):
        if request.url.path.endswith("/login"):
            return httpx.Response(
                200,
                json={"auth": {"client_token": "private-token", "lease_duration": 300}},
            )
        if case == "timeout":
            raise httpx.ReadTimeout("private-password", request=request)
        if case == "payload":
            return httpx.Response(
                200, json={"data": {"data": {"password": "private-password"}}}
            )
        return httpx.Response(int(case), json={"errors": ["private-password"]})

    monkeypatch.setattr(driver, "validate_profiled_live_host_trust", lambda: None)
    monkeypatch.setattr(
        driver,
        "NetBoxProfileInventoryProvider",
        lambda: FakeInventory(device, interface),
    )
    monkeypatch.setattr(
        driver,
        "OpenBaoSecretProvider",
        lambda: OpenBaoSecretProvider(
            URL,
            "private-role",
            "private-secret",
            transport=httpx.MockTransport(respond),
        ),
    )
    collector = FakeCollector(observed(device, interface))
    monkeypatch.setattr(driver, "ProfileReadOnlyAdapter", lambda **_k: collector)
    with pytest.raises(driver.PlanPhaseError) as caught:
        driver.plan_step(context, tmp_path)
    assert caught.value.phase == "OpenBao credential read" and collector.calls == 0
    monkeypatch.setattr(driver, "annotate", lambda _c, text, **_k: print(text))
    assert driver.plan_failure(context, caught.value.phase) == 2
    output = capsys.readouterr()
    assert "OpenBao credential read" in output.out
    assert "private" not in output.out + output.err


@pytest.mark.parametrize("status", [400, 401, 403])
def test_expired_login_maps_to_closed_openbao_phase(
    driver, context, tmp_path, monkeypatch, capsys, status
):
    device, interface = profiled_device(AutomationProfileID.CAT8000V_IOSXE)
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(
            status, json={"errors": ["private-token password RoleID SecretID"]}
        )

    provider = OpenBaoSecretProvider(
        URL, "private-role", "private-secret", transport=httpx.MockTransport(respond)
    )
    monkeypatch.setattr(driver, "validate_profiled_live_host_trust", lambda: None)
    monkeypatch.setattr(
        driver,
        "NetBoxProfileInventoryProvider",
        lambda: FakeInventory(device, interface),
    )
    monkeypatch.setattr(driver, "OpenBaoSecretProvider", lambda: provider)
    collector = FakeCollector(observed(device, interface))
    monkeypatch.setattr(driver, "ProfileReadOnlyAdapter", lambda **_k: collector)
    with pytest.raises(driver.PlanPhaseError) as caught:
        driver.plan_step(context, tmp_path)
    assert caught.value.phase == "OpenBao login"
    assert collector.calls == 0 and len(requests) == 1
    messages = []
    monkeypatch.setattr(
        driver, "annotate", lambda _c, text, **_k: messages.append(text)
    )
    assert driver.plan_failure(context, caught.value.phase) == 2
    assert "OpenBao login" in messages[0]
    assert (
        "private" not in repr(messages) + repr(caught.value) + capsys.readouterr().out
    )


@pytest.mark.parametrize(
    "boundary,label",
    [
        ("validate_profiled_live_host_trust", "LIVE trust"),
        ("NetBoxProfileInventoryProvider", "NetBox inventory"),
        ("OpenBaoSecretProvider", "protected environment"),
        ("plan_profiled_change", "device read-only preflight"),
        ("publish_plan", "plan publication"),
    ],
)
def test_plan_boundary_labels_are_closed(
    driver, context, plan, tmp_path, monkeypatch, boundary, label
):
    monkeypatch.setattr(driver, "validate_profiled_live_host_trust", lambda: None)
    for name in (
        "NetBoxProfileInventoryProvider",
        "OpenBaoSecretProvider",
        "ProfileReadOnlyAdapter",
    ):
        monkeypatch.setattr(driver, name, lambda **_k: object())
    monkeypatch.setattr(
        driver,
        "plan_profiled_change",
        lambda *_a: SimpleNamespace(
            plan=plan, state=SimpleNamespace(description="old")
        ),
    )

    def fail(*_a, **_k):
        raise ValueError("private-token password")

    monkeypatch.setattr(driver, boundary, fail)
    with pytest.raises(driver.PlanPhaseError) as caught:
        driver.plan_step(context, tmp_path)
    assert caught.value.phase == label and "private" not in repr(caught.value)


def test_inventory_exception_during_resolution_is_inventory_phase(
    driver, context, tmp_path, monkeypatch
):
    monkeypatch.setattr(driver, "validate_profiled_live_host_trust", lambda: None)
    for name in (
        "NetBoxProfileInventoryProvider",
        "OpenBaoSecretProvider",
        "ProfileReadOnlyAdapter",
    ):
        monkeypatch.setattr(driver, name, lambda **_k: object())
    monkeypatch.setattr(
        driver,
        "plan_profiled_change",
        lambda *_a: (_ for _ in ()).throw(InventoryError("private")),
    )
    with pytest.raises(driver.PlanPhaseError, match="NetBox inventory"):
        driver.plan_step(context, tmp_path)


@pytest.mark.parametrize("commit_ok", [False, True])
def test_main_plan_preprovider_failure_annotation(
    driver, monkeypatch, capsys, commit_ok
):
    monkeypatch.setattr(driver.os, "environ", environment("profiled-live-plan"))

    def checked(*_a):
        if not commit_ok:
            raise ValueError("private-token")

    messages = []
    monkeypatch.setattr(driver, "checked_command", checked)
    monkeypatch.setattr(
        driver, "annotate", lambda _c, text, **_k: messages.append(text)
    )
    assert driver.main() == 2
    assert ("protected environment" if commit_ok else "commit/context") in messages[0]
    assert "private-token" not in repr(messages) + capsys.readouterr().err


def test_preparation_not_in_pipeline_and_role_limits_unchanged():
    from network_change_delivery.openbao_profiled_config import _EXPECTED_LOCAL_ROLE

    assert _EXPECTED_LOCAL_ROLE["secret_id_ttl"] == 1800
    assert _EXPECTED_LOCAL_ROLE["secret_id_num_uses"] == 10
    assert _EXPECTED_LOCAL_ROLE["token_ttl"] == 300
    assert _EXPECTED_LOCAL_ROLE["token_num_uses"] == 1
    assert (
        "prepare_profiled_delivery_session"
        not in (ROOT / ".buildkite/pipeline.yml").read_text()
    )


@pytest.mark.parametrize(
    "damage", ["missing", "relative", "mode", "symlink", "namespace"]
)
def test_installer_checks_audit_setting_before_any_openbao_operation(
    helper,
    protected,
    damage,
):
    hooks, state, _original = protected
    root = hooks.parent.parent / "audit"
    protected_file = hooks / "profiled.env"
    if damage in {"missing", "relative"}:
        text = protected_file.read_text()
        line = next(
            line
            for line in text.splitlines()
            if line.startswith("NCDP_AUDIT_STORE_ROOT=")
        )
        text = text.replace(
            line, "" if damage == "missing" else "NCDP_AUDIT_STORE_ROOT=relative"
        )
        protected_file.write_text(text)
    elif damage == "mode":
        root.chmod(0o755)
    elif damage == "symlink":
        root.rmdir()
        root.symlink_to(hooks)
    else:
        (root / "profiled-records").symlink_to(hooks)
    bao = Bao()
    before = protected_file.read_bytes()
    with pytest.raises(ValueError):
        helper.install(hooks, state, bao.operator())
    assert not bao.calls and bao.issued == 0
    assert protected_file.read_bytes() == before
    assert not state.exists()
