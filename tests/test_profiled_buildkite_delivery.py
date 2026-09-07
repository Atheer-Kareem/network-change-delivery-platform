"""Fake-only current promotion, authorization, publication and trusted-hook tests."""

import importlib.util
import json
import subprocess
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_profiled_planning import (
    FakeCollector,
    FakeInventory,
    FakeSecrets,
    observed,
    profiled_device,
)

from network_change_delivery.architecture_contracts import AutomationProfileID
from network_change_delivery.models import InterfaceDescriptionIntent
from network_change_delivery.profiled_planning import plan_profiled_change
from network_change_delivery.profiled_promotion import (
    CHANGE_ID,
    DESCRIPTION,
    PLANNING_METADATA,
    VALIDATION_KEYS,
    ProfiledBuildContext,
    ProfiledPlanningPublication,
    ProfiledPromotion,
    authorize,
    digest_bytes,
    promote,
    validation_receipt,
)

ROOT = Path(__file__).parents[1]
BUILD = "11111111-1111-4111-8111-111111111111"
JOB = "22222222-2222-4222-8222-222222222222"
COMMIT = "a" * 40
DIGEST = "sha256:" + "b" * 64
REPO = "https://github.com/Atheer-Kareem/network-change-delivery-platform.git"


def environment(step="profiled-deploy"):
    return {
        "BUILDKITE_BUILD_ID": BUILD,
        "BUILDKITE_JOB_ID": JOB,
        "BUILDKITE_COMMIT": COMMIT,
        "BUILDKITE_STEP_KEY": step,
        "BUILDKITE_REPO": REPO,
        "BUILDKITE_BRANCH": "main",
        "BUILDKITE_PULL_REQUEST": "false",
        "BUILDKITE_RETRY_COUNT": "0",
        "BUILDKITE_AGENT_META_DATA_QUEUE": "ncdp-deploy",
        "BUILDKITE_PIPELINE_ID": BUILD,
        "NCDP_BUILDKITE_PIPELINE_ID": BUILD,
        "BUILDKITE_COMMAND": ".buildkite/scripts/profiled_delivery.sh",
    }


@pytest.fixture
def context():
    return ProfiledBuildContext.from_environment(environment())


@pytest.fixture
def plan():
    device, interface = profiled_device(AutomationProfileID.CAT8000V_IOSXE)
    intent = InterfaceDescriptionIntent(
        kind="interface_description",
        change_id=CHANGE_ID,
        target=device.logical_name,
        interface=interface.name,
        desired={"description": DESCRIPTION},
    )
    return plan_profiled_change(
        intent,
        FakeInventory(device, interface),
        FakeSecrets(),
        FakeCollector(observed(device, interface)),
    ).plan


@pytest.fixture
def receipts(context):
    return {
        key: validation_receipt(context.build_id, context.commit, key)
        for key in VALIDATION_KEYS
    }


@pytest.fixture
def driver(monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "delivery_driver", ROOT / "scripts/buildkite/profiled_delivery.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(
        module,
        "checked_command",
        lambda *_a, **_k: pytest.fail(
            "unmocked external helper forbidden in delivery tests"
        ),
    )
    return module


def planning_receipt(context, value):
    raw = value.model_dump_json().encode()
    return ProfiledPlanningPublication(
        build_id=context.build_id,
        commit=context.commit,
        artifact_kind="plan" if hasattr(value, "plan_type") else "compliance",
        artifact_digest=digest_bytes(raw),
        result_digest=value.digest,
    ).model_dump_json()


def test_current_promotion_round_trip_and_authorization(context, plan, receipts):
    raw = plan.model_dump_json().encode()
    promotion = promote(context, raw, receipts, DIGEST, DIGEST)
    assert promotion.schema_version == "2"
    assert promotion.plan_artifact_digest == digest_bytes(raw)
    assert promotion.plan_digest == plan.digest
    assert promotion.build_id == BUILD and promotion.commit == COMMIT
    assert (
        ProfiledPromotion.model_validate_json(promotion.model_dump_json()) == promotion
    )
    assert (
        authorize(
            context,
            promotion.model_dump_json().encode(),
            raw,
            receipts,
            DIGEST,
            DIGEST,
            promotion.digest,
            JOB,
        )
        == plan
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("BUILDKITE_REPO", "https://github.com/fork/repo.git"),
        ("BUILDKITE_BRANCH", "feature"),
        ("BUILDKITE_PULL_REQUEST", "136"),
        ("BUILDKITE_PULL_REQUEST_REPO", REPO),
        ("BUILDKITE_RETRY_COUNT", "1"),
        ("BUILDKITE_AGENT_META_DATA_QUEUE", "ncdp-validation"),
        ("BUILDKITE_BUILD_ID", "bad"),
        ("BUILDKITE_JOB_ID", "bad"),
        ("BUILDKITE_COMMIT", "HEAD"),
        ("BUILDKITE_STEP_KEY", "protected-delivery"),
    ],
)
def test_context_rejects_before_any_helper(driver, monkeypatch, field, value):
    env = environment()
    env[field] = value
    monkeypatch.setattr(driver.os, "environ", env)
    monkeypatch.setattr(
        driver,
        "checked_command",
        lambda *_a, **_k: pytest.fail("helper before admission"),
    )
    assert driver.main() == 2


@pytest.mark.parametrize("missing", VALIDATION_KEYS)
def test_each_validation_failure_blocks_promotion(context, plan, receipts, missing):
    receipts.pop(missing)
    with pytest.raises(ValueError):
        promote(context, plan.model_dump_json().encode(), receipts, DIGEST, DIGEST)


@pytest.mark.parametrize(
    "batfish,cml", [("", DIGEST), (DIGEST, ""), ("FAILED", DIGEST), (DIGEST, "FAILED")]
)
def test_assurance_failure_cannot_mint_promotion(context, plan, receipts, batfish, cml):
    with pytest.raises(ValueError):
        promote(context, plan.model_dump_json().encode(), receipts, batfish, cml)


@pytest.mark.parametrize(
    "case",
    [
        "build",
        "commit",
        "artifact",
        "plan",
        "digest",
        "batfish",
        "cml",
        "validation",
        "human",
        "legacy_plan",
        "legacy_promotion",
    ],
)
def test_authorization_independently_rejects_every_binding(
    context, plan, receipts, case
):
    raw = plan.model_dump_json().encode()
    promotion = promote(context, raw, receipts, DIGEST, DIGEST)
    serialized = promotion.model_dump_json().encode()
    digest, human, batfish, cml = promotion.digest, JOB, DIGEST, DIGEST
    if case == "build":
        context = replace(context, build_id=JOB)
    elif case == "commit":
        context = replace(context, commit="c" * 40)
    elif case == "artifact":
        raw += b"\n"
    elif case in {"plan", "legacy_plan"}:
        value = json.loads(raw)
        value["schema_version" if case == "legacy_plan" else "digest"] = (
            "1" if case == "legacy_plan" else DIGEST
        )
        raw = json.dumps(value).encode()
    elif case == "legacy_promotion":
        serialized = serialized.replace(
            b'"schema_version":"2"', b'"schema_version":"1"'
        )
    elif case == "digest":
        digest = DIGEST
    elif case == "batfish":
        batfish = "sha256:" + "c" * 64
    elif case == "cml":
        cml = ""
    elif case == "validation":
        receipts[VALIDATION_KEYS[0]] = DIGEST
    elif case == "human":
        human = ""
    with pytest.raises(ValueError):
        authorize(context, serialized, raw, receipts, batfish, cml, digest, human)


@pytest.mark.parametrize(
    "profile", [AutomationProfileID.IOSV_159_3_M12, AutomationProfileID.IOSVL2_2020]
)
def test_read_only_devices_remain_unplannable(profile):
    device, interface = profiled_device(profile)
    secret = FakeSecrets()
    with pytest.raises(ValueError):
        plan_profiled_change(
            InterfaceDescriptionIntent(
                kind="interface_description",
                change_id=CHANGE_ID,
                target=device.logical_name,
                interface=interface.name,
                desired={"description": DESCRIPTION},
            ),
            FakeInventory(device, interface),
            secret,
            FakeCollector(observed(device, interface)),
        )
    assert secret.load_calls == 0


def test_invalid_promotion_reaches_no_write_and_evidence_remains_truthful(
    driver, context, tmp_path, monkeypatch
):
    messages = []
    monkeypatch.setattr(
        driver, "annotate", lambda _c, text, **_k: messages.append(text)
    )
    monkeypatch.setattr(
        driver,
        "download",
        lambda *_a: (_ for _ in ()).throw(ValueError("private-secret")),
    )
    monkeypatch.setattr(
        driver, "command", lambda *_a, **_k: pytest.fail("device execution forbidden")
    )
    monkeypatch.setattr(
        driver,
        "validate_profiled_live_host_trust",
        lambda: pytest.fail("trust before authorization"),
    )
    monkeypatch.setenv("BUILDKITE_UNBLOCKER_ID", JOB)
    monkeypatch.setattr(
        driver, "metadata", lambda *_a: (_ for _ in ()).throw(ValueError("missing"))
    )
    assert driver.deploy_step(context, tmp_path) == 2
    assert "NO WRITE" in messages[0]
    assert driver.evidence_step(context, tmp_path) == 2
    assert "No typed execution record produced" in messages[1]
    assert "private-secret" not in repr(messages)


@pytest.mark.parametrize("returncode", [0, 2, 17])
def test_valid_authorization_calls_only_current_cli_once(
    driver, context, plan, receipts, tmp_path, monkeypatch, returncode
):
    raw = plan.model_dump_json().encode()
    promotion = promote(context, raw, receipts, DIGEST, DIGEST)
    monkeypatch.setattr(
        driver,
        "download",
        lambda _c, _d, _name, step: (
            raw
            if step == "profiled-live-plan"
            else promotion.model_dump_json().encode()
        ),
    )
    monkeypatch.setattr(driver, "prerequisites", lambda _c: (receipts, DIGEST, DIGEST))
    monkeypatch.setattr(
        driver,
        "metadata",
        lambda _c, key: (
            planning_receipt(context, plan)
            if key == PLANNING_METADATA
            else promotion.digest
        ),
    )
    monkeypatch.setenv("BUILDKITE_UNBLOCKER_ID", JOB)
    events = []
    monkeypatch.setattr(
        driver, "validate_profiled_live_host_trust", lambda: events.append("trust")
    )
    monkeypatch.setattr(driver, "annotate", lambda *_a, **_k: None)

    def command(args, **kwargs):
        events.append(args)
        assert kwargs == {"device_authority": True}
        return SimpleNamespace(returncode=returncode)

    monkeypatch.setattr(driver, "command", command)
    assert driver.deploy_step(context, tmp_path) == (
        returncode or 3
    )  # no record != success
    assert len(events) == 2 and events[0] == "trust"
    args = events[1]
    assert args[:4] == ["uv", "run", "--frozen", "ncdp"]
    assert args[4] == "profiled-deploy" and "deploy" not in args
    assert args[args.index("--approve-digest") + 1] == plan.digest
    assert args[-3:] == ["--netbox", "--openbao", "--live"]


@pytest.mark.parametrize("no_change", [False, True])
def test_planning_reuses_current_read_only_implementation(
    driver, context, tmp_path, monkeypatch, no_change
):
    messages, uploaded = [], []
    monkeypatch.setattr(driver, "validate_profiled_live_host_trust", lambda: None)
    for name in (
        "NetBoxProfileInventoryProvider",
        "OpenBaoSecretProvider",
        "ProfileReadOnlyAdapter",
    ):
        monkeypatch.setattr(driver, name, lambda **_k: object())
    device, interface = profiled_device(AutomationProfileID.CAT8000V_IOSXE)
    intent = InterfaceDescriptionIntent(
        kind="interface_description",
        change_id=CHANGE_ID,
        target=device.logical_name,
        interface=interface.name,
        desired={"description": DESCRIPTION},
    )
    result = plan_profiled_change(
        intent,
        FakeInventory(device, interface),
        FakeSecrets(),
        FakeCollector(
            observed(device, interface).model_copy(
                update={"description": DESCRIPTION if no_change else "previous"}
            )
        ),
    )
    monkeypatch.setattr(driver, "plan_profiled_change", lambda *_a: result)
    monkeypatch.setattr(driver, "upload", lambda *a: uploaded.append(a))
    monkeypatch.setattr(driver, "annotate", lambda _c, text: messages.append(text))
    published = []
    monkeypatch.setattr(driver, "publish_metadata", lambda *a: published.append(a))
    assert driver.plan_step(context, tmp_path) == 0
    assert len(uploaded) == 1 and len(published) == 1
    assert ("already compliant" in messages[0]) is no_change
    assert (DESCRIPTION if no_change else "previous") in messages[0]


@pytest.mark.parametrize("mode", [0o755, 0o770, 0o777])
def test_private_state_rejects_permissions(driver, tmp_path, mode):
    tmp_path.chmod(mode)
    with pytest.raises(ValueError):
        driver.private_directory(tmp_path.resolve())


def test_same_build_download_and_create_only_artifacts(
    driver, context, tmp_path, monkeypatch
):
    calls = []

    def checked(args, **_kwargs):
        calls.append(args)
        driver.write_new(tmp_path / "plan.json", b"{}")

    monkeypatch.setattr(driver, "checked_command", checked)
    assert (
        driver.download(context, tmp_path, "plan.json", "profiled-live-plan") == b"{}"
    )
    assert calls[0][-4:] == ["--step", "profiled-live-plan", "--build", BUILD]
    with pytest.raises(ValueError):
        driver.download(context, tmp_path, "plan.json", "profiled-live-plan")
    with pytest.raises(FileExistsError):
        driver.write_new(tmp_path / "plan.json", b"overwrite")


def test_typed_execution_evidence_reports_real_attempts_only(
    driver, context, plan, tmp_path, monkeypatch
):
    from datetime import UTC, datetime

    from network_change_delivery.models import FinalOutcome, StageResult
    from network_change_delivery.profiled_execution import _record

    record = _record(
        plan,
        plan.digest,
        FinalOutcome.SUCCEEDED,
        preflight=StageResult(
            attempted=True,
            succeeded=True,
            observed_description=plan.current_description,
            message="private-body",
        ),
        post=StageResult(
            attempted=True,
            succeeded=True,
            observed_description=plan.desired_description,
            message="private-body",
        ),
        execution=StageResult(attempted=True, succeeded=True, message="private-body"),
        now=lambda: datetime.now(UTC),
    )
    raw = record.model_dump_json().encode()
    monkeypatch.setattr(
        driver,
        "download",
        lambda _c, _d, _n, step: (
            raw if step == "profiled-deploy" else plan.model_dump_json().encode()
        ),
    )
    monkeypatch.setattr(driver, "metadata", lambda *_a: planning_receipt(context, plan))
    messages = []
    monkeypatch.setattr(driver, "annotate", lambda _c, text: messages.append(text))
    assert driver.evidence_step(context, tmp_path) == 0
    assert "Write attempted: True" in messages[0]
    assert "Recovery attempted: False" in messages[0]
    assert "SUCCEEDED" in messages[0] and plan.digest in messages[0]
    assert "private-body" not in messages[0]


def test_private_state_rejects_symlink_checkout_and_wrong_owner(
    driver, tmp_path, monkeypatch
):
    root = tmp_path.resolve() / "root"
    root.mkdir(mode=0o700)
    link = tmp_path / "link"
    link.symlink_to(root, target_is_directory=True)
    with pytest.raises(ValueError):
        driver.private_directory(link)
    monkeypatch.setattr(driver.os, "getuid", lambda: root.stat().st_uid + 1)
    with pytest.raises(ValueError):
        driver.private_directory(root)
    monkeypatch.undo()
    monkeypatch.setattr(driver, "ROOT", tmp_path.resolve())
    with pytest.raises(ValueError):
        driver.private_directory(root)


def test_helper_children_do_not_inherit_device_authority(driver, monkeypatch):
    for key in driver.PROTECTED | {"CML2_TOKEN", "NCDP_DEVICE_PASSWORD"}:
        monkeypatch.setenv(key, "private-secret")
    calls = []
    monkeypatch.setattr(driver.subprocess, "run", lambda *a, **k: calls.append((a, k)))
    driver.command(["buildkite-agent", "annotate"])
    environment = calls[0][1]["env"]
    assert not driver.PROTECTED.intersection(environment)
    assert "CML2_TOKEN" not in environment and "NCDP_DEVICE_PASSWORD" not in environment


@pytest.mark.parametrize(
    "changes",
    [
        {"BUILDKITE_BRANCH": "feature"},
        {"BUILDKITE_PULL_REQUEST": "136"},
        {"BUILDKITE_REPO": "fork"},
        {"BUILDKITE_PULL_REQUEST_REPO": REPO},
        {"BUILDKITE_RETRY_COUNT": "1"},
        {"BUILDKITE_AGENT_META_DATA_QUEUE": "ncdp-validation"},
        {"BUILDKITE_STEP_KEY": "profiled-promotion"},
        {"BUILDKITE_COMMAND": "env"},
        {"BUILDKITE_COMMIT": "b" * 40},
        {"NCDP_NETBOX_TOKEN": "ambient-secret"},
    ],
)
def test_agent_hook_rejects_before_protected_source(tmp_path, changes):
    result, marker = run_hook(tmp_path, changes)
    assert result.returncode == 2 and not marker.exists()
    assert "protected-secret" not in result.stdout + result.stderr


def run_hook(tmp_path, changes=None, mode=0o600, expected=BUILD):
    hook = tmp_path / "hooks"
    hook.mkdir(mode=0o700)
    (hook / "command").write_bytes(
        (ROOT / "scripts/buildkite/profiled_deploy_agent_command_hook.sh").read_bytes()
    )
    marker = tmp_path / "sourced"
    (hook / "profiled.env").write_text(
        f"touch '{marker}'\nNCDP_BUILDKITE_PIPELINE_ID={expected}\n"
        + "\n".join(
            f"{key}=protected-secret"
            for key in (
                "NCDP_NETBOX_URL",
                "NCDP_NETBOX_TOKEN",
                "NCDP_OPENBAO_URL",
                "NCDP_OPENBAO_ROLE_ID",
                "NCDP_OPENBAO_SECRET_ID",
                "NCDP_PROFILED_DELIVERY_STATE_ROOT",
            )
        )
    )
    (hook / "profiled.env").chmod(mode)
    bindir = tmp_path / "bin"
    bindir.mkdir()
    git = bindir / "git"
    git.write_text(f'#!/bin/sh\nif [ "$1" = rev-parse ]; then echo {COMMIT}; fi\n')
    git.chmod(0o700)
    wrapper = tmp_path / ".buildkite/scripts/profiled_delivery.sh"
    wrapper.parent.mkdir(parents=True)
    wrapper.write_text('#!/bin/sh\necho "WRAPPER EXECUTED"\n')
    wrapper.chmod(0o700)
    env = {"PATH": f"{bindir}:/usr/bin:/bin", **environment(), **(changes or {})}
    result = subprocess.run(
        ["bash", str(hook / "command")],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    return result, marker


@pytest.mark.parametrize(
    "mode,expected,success,sourced",
    [
        (0o600, BUILD, True, True),
        (0o644, BUILD, False, False),
        (0o600, JOB, False, True),
        (0o600, "", False, True),
    ],
)
def test_agent_protected_mode_pipeline_and_exact_wrapper(
    tmp_path, mode, expected, success, sourced
):
    result, marker = run_hook(tmp_path, mode=mode, expected=expected)
    assert (result.returncode == 0) is success
    assert ("WRAPPER EXECUTED" in result.stdout) is success
    assert marker.exists() is sourced
    assert "protected-secret" not in result.stdout + result.stderr


@pytest.mark.parametrize("mismatch", [False, True])
def test_execution_publication_and_final_render_require_exact_plan_binding(
    driver, context, plan, receipts, tmp_path, monkeypatch, mismatch
):
    from datetime import UTC, datetime

    from network_change_delivery.models import FinalOutcome, StageResult
    from network_change_delivery.profiled_execution import _record

    record = _record(
        plan,
        plan.digest,
        FinalOutcome.SUCCEEDED,
        preflight=StageResult(
            message="reviewed state observed",
            attempted=True,
            succeeded=True,
            observed_description=plan.current_description,
        ),
        execution=StageResult(
            attempted=True, succeeded=True, changed=None, message="provider success"
        ),
        post=StageResult(
            message="desired state observed",
            attempted=True,
            succeeded=True,
            changed=True,
            observed_description=plan.desired_description,
        ),
        now=lambda: datetime.now(UTC),
    )
    if mismatch:
        # Coherent record with matching digests but belonging to a different change.
        record = record.model_copy(update={"change_id": "CHG-DIFFERENT"})
    raw = plan.model_dump_json().encode()
    promotion = promote(context, raw, receipts, DIGEST, DIGEST)
    monkeypatch.setattr(
        driver,
        "metadata",
        lambda _c, key: (
            planning_receipt(context, plan)
            if key == PLANNING_METADATA
            else promotion.digest
        ),
    )
    monkeypatch.setattr(driver, "prerequisites", lambda _c: (receipts, DIGEST, DIGEST))
    monkeypatch.setenv("BUILDKITE_UNBLOCKER_ID", JOB)
    monkeypatch.setattr(driver, "validate_profiled_live_host_trust", lambda: None)
    artifacts = {
        "profiled-live-plan": raw,
        "profiled-promotion": promotion.model_dump_json().encode(),
        "profiled-deploy": record.model_dump_json().encode(),
    }
    monkeypatch.setattr(driver, "download", lambda _c, _d, _n, step: artifacts[step])
    uploaded, annotations, commands = [], [], []
    monkeypatch.setattr(driver, "upload", lambda *_a: uploaded.append(_a[-1]))
    monkeypatch.setattr(
        driver, "annotate", lambda _c, text, **_k: annotations.append(text)
    )

    def command(args, **_k):
        commands.append(args)
        Path(args[args.index("--report-json") + 1]).write_bytes(
            artifacts["profiled-deploy"]
        )
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(driver, "command", command)
    assert driver.deploy_step(context, tmp_path) == (3 if mismatch else 0)
    assert len(commands) == 1  # Publication failure never retries execution.
    assert len(uploaded) == (0 if mismatch else 1)
    assert driver.evidence_step(context, tmp_path) == (2 if mismatch else 0)
    assert ("Outcome: SUCCEEDED" in annotations[-1]) is not mismatch
