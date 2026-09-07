"""Fake OpenBao and filesystem-only operator preparation; no device access."""

import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
import test_profiled_buildkite_delivery as delivery_tests
from test_openbao_profiled_config import OpenBaoState, configurator
from test_profiled_buildkite_delivery import environment
from test_profiled_planning import (
    FakeCollector,
    FakeInventory,
    observed,
    profiled_device,
)

from network_change_delivery.architecture_contracts import AutomationProfileID
from network_change_delivery.inventory import InventoryError
from network_change_delivery.openbao_profiled_config import ProfiledOpenBaoSession
from network_change_delivery.secrets import OpenBaoSecretProvider, SecretError

ROOT = Path(__file__).parents[1]
URL = "https://openbao.example"
context = delivery_tests.context
driver = delivery_tests.driver
plan = delivery_tests.plan


@pytest.fixture
def helper():
    spec = importlib.util.spec_from_file_location(
        "prepare_session",
        ROOT / "scripts/buildkite/prepare_profiled_delivery_session.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def protected(tmp_path, helper):
    directory = tmp_path.resolve() / "hooks/ncdp-deploy"
    directory.mkdir(parents=True, mode=0o700)
    source = (
        "# preserve operator settings\n"
        + "\n".join(
            f"{name}='{URL if name == 'NCDP_OPENBAO_URL' else 'old-private-value'}'"
            for name in sorted(helper.REQUIRED)
        )
        + "\nEXTRA_SETTING='unchanged'\n"
    ).encode()
    path = directory / "profiled.env"
    path.write_bytes(source)
    path.chmod(0o600)
    return directory, source


def test_preparation_is_atomic_preserves_other_bytes_and_only_issues_session(
    helper, protected, monkeypatch, capsys
):
    directory, original = protected
    state = OpenBaoState()
    replacements = []
    original_replace = Path.replace

    def replace(path, target):
        assert path.stat().st_mode & 0o777 == 0o600
        if target.name == "profiled.env":
            assert target.read_bytes() == original
            replacements.append(target)
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", replace)
    helper.prepare(directory, configurator(state, []), URL)
    assert replacements == [directory / "profiled.env"]
    result = (directory / "profiled.env").read_bytes()
    session = ProfiledOpenBaoSession(
        "private-role", "private-session-secret", "session-accessor"
    )
    assert result == helper.replace_session(original, session)
    for path in (directory / "profiled.env", directory / helper.ACCESSOR):
        assert path.stat().st_mode & 0o777 == 0o600
        assert path.stat().st_uid == os.getuid()
    assert not list(directory.glob(".session-tmp-*"))
    writes = [r.url.path for r in state.requests if r.method != "GET"]
    assert writes == ["/v1/auth/approle/role/ncdp-personal-lab/secret-id"]
    assert not any(
        "/data/devices/" in r.url.path or r.url.path.endswith("/login")
        for r in state.requests
    )
    output = capsys.readouterr()
    assert "private" not in output.out + output.err


def test_retire_prior_known_accessor_before_new_session(helper, protected):
    directory, _ = protected
    state = OpenBaoState()
    operator = configurator(state, [])
    helper.prepare(directory, operator, URL)
    state.requests.clear()
    helper.prepare(directory, operator, URL)
    writes = [r.url.path for r in state.requests if r.method == "POST"]
    assert writes == [
        "/v1/auth/approle/role/ncdp-personal-lab/secret-id-accessor/destroy",
        "/v1/auth/approle/role/ncdp-personal-lab/secret-id",
    ]
    state.requests.clear()
    helper.prepare(directory, operator, URL, retire_only=True)
    assert not (directory / helper.ACCESSOR).exists()
    assert b"NCDP_OPENBAO_SECRET_ID=''" in (directory / "profiled.env").read_bytes()
    assert len(state.requests) == 1 and state.requests[0].url.path.endswith("/destroy")


def test_failed_atomic_install_preserves_env_and_journals_accessor(
    helper, protected, monkeypatch
):
    directory, original = protected
    original_replace = Path.replace

    def replace(path, target):
        if target.name == "profiled.env":
            raise OSError("private-secret")
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", replace)
    with pytest.raises(OSError):
        helper.prepare(directory, configurator(OpenBaoState(), []), URL)
    assert (directory / "profiled.env").read_bytes() == original
    assert (directory / helper.ACCESSOR).read_text().strip() == "session-accessor"
    assert not list(directory.glob(".session-tmp-*"))


@pytest.mark.parametrize(
    "case",
    [
        "mode",
        "directory-mode",
        "symlink",
        "missing-name",
        "duplicate",
        "wrong-url",
        "retire-unknown",
    ],
)
def test_local_admission_before_operator_requests(helper, protected, case):
    directory, original = protected
    path = directory / "profiled.env"
    if case == "mode":
        path.chmod(0o644)
    elif case == "directory-mode":
        directory.chmod(0o755)
    elif case == "symlink":
        moved = directory / "original"
        path.rename(moved)
        path.symlink_to(moved)
    elif case == "missing-name":
        path.write_bytes(original.replace(b"NCDP_NETBOX_TOKEN", b"OTHER"))
    elif case == "duplicate":
        path.write_bytes(original + b"NCDP_OPENBAO_ROLE_ID=duplicate\n")
    state = OpenBaoState()
    with pytest.raises(ValueError):
        helper.prepare(
            directory,
            configurator(state, []),
            "https://wrong.example" if case == "wrong-url" else URL,
            retire_only=case == "retire-unknown",
        )
    assert state.requests == []


def test_existing_external_settings_source_is_inspected_not_executed(helper, protected):
    directory, original = protected
    external = directory.parent.parent / "env/ncdp-deploy.env"
    external.parent.mkdir()
    external.write_bytes(original)
    external.chmod(0o600)
    source = (
        f"source {external}\nNCDP_OPENBAO_ROLE_ID=old\nNCDP_OPENBAO_SECRET_ID=old\n"
    ).encode()
    (directory / "profiled.env").write_bytes(source)
    helper.prepare(directory, configurator(OpenBaoState(), []), URL)
    assert external.read_bytes() == original
    assert (
        (directory / "profiled.env")
        .read_bytes()
        .startswith(f"source {external}\n".encode())
    )


@pytest.mark.parametrize("failure", ["mint", "retire"])
def test_uncertain_operator_mutation_is_not_replayed(helper, protected, failure):
    directory, original = protected
    calls = []
    if failure == "retire":
        helper.atomic_private(directory / helper.ACCESSOR, b"session-accessor\n")

    def reject(*_args):
        calls.append(failure)
        raise SecretError("private-secret")

    operator = SimpleNamespace(
        issue_bounded_session=reject, retire_bounded_session=reject
    )
    with pytest.raises(SecretError):
        helper.prepare(directory, operator, URL)
    assert calls == [failure]
    assert (directory / "profiled.env").read_bytes() == original


@pytest.mark.parametrize("buildkite", [True, False])
def test_operator_cli_requires_explicit_authority_and_redacts_failure(
    helper, protected, monkeypatch, capsys, buildkite
):
    directory, _ = protected
    monkeypatch.setattr(
        helper.os, "environ", {"BUILDKITE_BUILD_ID": "job"} if buildkite else {}
    )
    monkeypatch.setattr(
        "sys.argv",
        ["prepare", "prepare", "--directory", str(directory), "--confirm-idle"],
    )
    assert helper.main() == 2
    assert "No device access" in capsys.readouterr().out


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
    assert caught.value.phase == "OpenBao authentication"
    assert collector.calls == 0 and len(requests) == 1
    messages = []
    monkeypatch.setattr(
        driver, "annotate", lambda _c, text, **_k: messages.append(text)
    )
    assert driver.plan_failure(context, caught.value.phase) == 2
    assert "OpenBao authentication" in messages[0]
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
