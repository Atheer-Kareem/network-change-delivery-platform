"""Fake-only Buildkite admission, shared lifecycle, and publication boundaries."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from test_buildkite_staging import (
    BUILD_ID,
    COMMIT,
    JOB_ID,
    JWT,
    PIPELINE_ID,
    context,
    handler,
    profiled_target,
)
from test_profiled_realization import inventory_devices, staging_context

from network_change_delivery.buildkite_identity import BuildkiteOIDCJWT
from network_change_delivery.buildkite_staging import BuildkiteStagingSecretProvider
from network_change_delivery.profiled_realization import (
    EvidenceReference,
    StagingRealizationContext,
)
from network_change_delivery.profiled_staging import (
    ProfiledStagingAmbiguousError,
    ProfiledStagingDeviceEvidence,
    ProfiledStagingError,
    ProfiledStagingEvidence,
    ProfiledStagingReadinessEvidence,
)
from network_change_delivery.secrets import SecretError

ROOT = Path(__file__).parents[1]
CANONICAL = "https://github.com/Atheer-Kareem/network-change-delivery-platform.git"


@pytest.mark.parametrize(
    "timing",
    [
        {"password": 1},
        {"start": -1},
        {"start": float("nan")},
        {"start": "bearer-secret"},
    ],
)
def test_timing_evidence_rejects_unknown_labels_and_non_duration_values(timing):
    with pytest.raises(ValueError):
        ProfiledStagingEvidence(
            staging_run_id="run-001",
            orchestrator="local",
            lab_title="NCDP Staging run-001",
            timings_seconds=timing,
        )


def test_staging_summary_renders_only_closed_numeric_timings(driver):
    evidence = ProfiledStagingEvidence(
        staging_run_id="run-001",
        orchestrator="local",
        lab_title="NCDP Staging run-001",
        timings_seconds={
            "start": 4.123,
            "transit_first_boot": 30,
            "transit_persistence": 60,
            "lifecycle_total": 410,
        },
        primary_failure="bearer-secret",
    )
    rendered = driver.summary(evidence, succeeded=False)
    assert "CML lab start: 4.1s" in rendered
    assert "Transit first boot: 30.0s" in rendered
    assert "Total lifecycle: 410.0s" in rendered
    assert "bearer-secret" not in rendered


@pytest.mark.parametrize(
    "phase",
    [
        "admission",
        "infrastructure create",
        "CML lab start",
        "transit recycle",
        "service readiness",
        "strict trust",
        "read-only validation",
        "cleanup",
    ],
)
def test_failed_phase_is_closed_state_derived_and_secret_safe(driver, phase):
    from test_profiled_staging import Operations

    phases = [
        "admission",
        "infrastructure create",
        "CML lab start",
        "transit recycle",
        "service readiness",
        "strict trust",
        "read-only validation",
        "cleanup",
    ]
    index = phases.index(phase)
    operation = Operations()
    operation.create()
    evidence = ProfiledStagingEvidence(
        staging_run_id="run-001",
        orchestrator="local",
        lab_title="NCDP Staging run-001",
        create_outcome="not_attempted"
        if index == 0
        else "attempted"
        if index == 1
        else "succeeded",
        start_outcome="attempted" if index <= 2 else "succeeded",
        transit_recycle_outcome="attempted" if index <= 3 else "succeeded",
        transit_recycle_evidence=None
        if index <= 3
        else EvidenceReference(
            identity="staging-transit-recycle:run-001:transit-ios-01",
            digest="sha256:" + "d" * 64,
        ),
        readiness=operation.readiness_evidence if index > 4 else (),
        trust_generation=None
        if index <= 5
        else EvidenceReference(
            identity="staging-trust:run-001", digest="sha256:" + "e" * 64
        ),
        primary_failure="synthetic-secret-provider-body" if index < 7 else None,
        cleanup_failure="synthetic-secret-provider-body" if index == 7 else None,
    )
    rendered = driver.summary(evidence, succeeded=False)
    assert f"Failed phase: {phase}" in rendered
    assert "synthetic-secret" not in rendered
    assert rendered.count("Failed phase:") == 1


def test_start_reference_must_be_exact_and_only_with_success():
    for identity, outcome in (
        ("staging-lab-start:wrong", "succeeded"),
        ("staging-lab-start:run-001", "attempted"),
    ):
        with pytest.raises(ValueError, match="lab start evidence rejected"):
            ProfiledStagingEvidence(
                staging_run_id="run-001",
                orchestrator="local",
                lab_title="NCDP Staging run-001",
                start_outcome=outcome,
                lab_start_evidence=EvidenceReference(
                    identity=identity, digest="sha256:" + "f" * 64
                ),
            )


@pytest.fixture
def driver(tmp_path, monkeypatch):
    path = ROOT / "scripts/buildkite/run_profiled_cml_staging.py"
    spec = importlib.util.spec_from_file_location("buildkite_profiled_driver", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    environment = {
        "BUILDKITE_PIPELINE_ID": PIPELINE_ID,
        "NCDP_BUILDKITE_PIPELINE_ID": PIPELINE_ID,
        "BUILDKITE_BUILD_ID": BUILD_ID,
        "BUILDKITE_JOB_ID": JOB_ID,
        "BUILDKITE_COMMIT": COMMIT,
        "BUILDKITE_BRANCH": "feature/staging",
        "BUILDKITE_STEP_KEY": "cml-staging",
        "BUILDKITE_AGENT_META_DATA_QUEUE": "ncdp-staging",
        "BUILDKITE_RETRY_COUNT": "0",
        "NCDP_STAGING_STATE_ROOT": str(tmp_path),
        "NCDP_NETBOX_URL": "https://netbox.example",
        "NCDP_STAGING_NETBOX_TOKEN": "dedicated-token",
        "NCDP_OPENBAO_URL": "https://openbao.example",
        "CML2_ADDRESS": "https://cml.example",
        "CML2_CACERT": "fake-ca",
        "NCDP_CML_STAGING_USERNAME": "operator",
        "NCDP_CML_STAGING_PASSWORD": "protected-password",
    }
    for key in (
        "NCDP_OPENBAO_ROLE_ID",
        "NCDP_OPENBAO_SECRET_ID",
        "NCDP_NETBOX_TOKEN",
        "CML2_TOKEN",
        "NCDP_DEVICE_USERNAME",
        "NCDP_DEVICE_PASSWORD",
    ):
        monkeypatch.delenv(key, raising=False)
    for key, value in environment.items():
        monkeypatch.setenv(key, value)
    tmp_path.chmod(0o700)
    return module


@pytest.mark.parametrize(
    "key,value",
    [
        ("BUILDKITE_STEP_KEY", "deploy-gate"),
        ("BUILDKITE_AGENT_META_DATA_QUEUE", "ncdp-validation"),
        ("BUILDKITE_RETRY_COUNT", "1"),
        ("BUILDKITE_RETRY_COUNT", ""),
        ("BUILDKITE_PIPELINE_ID", "wrong"),
        ("BUILDKITE_PIPELINE_ID", JOB_ID),
        ("NCDP_BUILDKITE_PIPELINE_ID", ""),
        ("NCDP_BUILDKITE_PIPELINE_ID", JOB_ID),
        ("BUILDKITE_BUILD_ID", "wrong"),
        ("BUILDKITE_JOB_ID", "wrong"),
        ("BUILDKITE_COMMIT", "HEAD"),
        ("NCDP_OPENBAO_ROLE_ID", "forbidden"),
        ("NCDP_OPENBAO_SECRET_ID", "forbidden"),
        ("CML2_TOKEN", "forbidden"),
        ("NCDP_NETBOX_TOKEN", "forbidden"),
        ("NCDP_DEVICE_USERNAME", "forbidden"),
        ("NCDP_DEVICE_PASSWORD", "forbidden"),
        ("NCDP_STAGING_NETBOX_TOKEN", ""),
        ("NCDP_STAGING_STATE_ROOT", "relative"),
    ],
)
def test_admission_fails_before_authority(driver, monkeypatch, key, value):
    monkeypatch.setenv(key, value)
    calls = []
    monkeypatch.setattr(driver, "command", lambda *a, **_kw: calls.append(a))
    monkeypatch.setattr(driver, "authenticate_cml", lambda: calls.append("CML"))
    monkeypatch.setattr(
        driver, "BuildkiteStagingSecretProvider", lambda *a, **_kw: calls.append(a)
    )
    with pytest.raises((ValueError, SecretError, ProfiledStagingError)):
        driver.admit()
    assert calls == []


def test_exact_commit_verifier_runs_before_oidc_or_cml(driver, monkeypatch):
    calls = []
    monkeypatch.setattr(driver, "command", lambda args: calls.append(args))
    admitted, root = driver.admit()
    assert admitted == context()
    assert root.name
    assert calls == [["scripts/buildkite/verify_commit.sh"]]


def test_missing_expected_pipeline_fails_before_helpers(driver, monkeypatch):
    monkeypatch.delenv("NCDP_BUILDKITE_PIPELINE_ID")
    calls = []
    monkeypatch.setattr(driver, "command", lambda *a, **_kw: calls.append(a))
    monkeypatch.setattr(driver, "authenticate_cml", lambda: calls.append("CML"))
    with pytest.raises(ProfiledStagingError, match="configuration missing"):
        driver.admit()
    assert calls == []


@pytest.mark.parametrize(
    "claim",
    ["pipeline_id", "build_id", "build_commit", "build_branch", "step_key", "job_id"],
)
@pytest.mark.usefixtures("driver")
def test_wrong_signed_identity_cannot_read_secret(claim):
    requests = []
    normal = handler(requests)

    def wrong(request):
        response = normal(request)
        payload = response.json()
        payload["auth"]["metadata"][claim] = "wrong"
        return httpx.Response(200, json=payload)

    provider = BuildkiteStagingSecretProvider(
        BuildkiteOIDCJWT(JWT),
        context(),
        "https://openbao.example",
        transport=httpx.MockTransport(wrong),
    )
    with pytest.raises(SecretError, match="identity mismatch"):
        provider.load(profiled_target(1))
    with pytest.raises(SecretError, match="already consumed"):
        provider.load(profiled_target(1))
    assert len(requests) == 1


@pytest.mark.parametrize("status", [200, 401, 500])
def test_one_memory_only_cml_authentication_no_replay(driver, monkeypatch, status):
    calls = []
    monkeypatch.setattr(driver.ssl, "create_default_context", lambda **_kw: True)

    def respond(request):
        calls.append(request)
        assert request.method == "POST"
        assert request.url.path == "/api/v0/authenticate"
        assert json.loads(request.content)["password"] == "protected-password"
        return httpx.Response(status, json="memory-only-bearer")

    transport = httpx.MockTransport(respond)
    if status == 200:
        assert driver.authenticate_cml(transport=transport) == "memory-only-bearer"
    else:
        with pytest.raises(ProfiledStagingError) as failure:
            driver.authenticate_cml(transport=transport)
        assert "memory-only-bearer" not in repr(failure.value)
        assert "protected-password" not in repr(failure.value)
    assert len(calls) == 1
    assert "CML2_TOKEN" not in os.environ


def test_local_defaults_and_injected_providers_are_same_operations(
    driver, monkeypatch, tmp_path
):
    local = __import__("run_profiled_cml_staging")
    default_inventory, default_secrets = object(), object()
    monkeypatch.setattr(
        local, "NetBoxProfileInventoryProvider", lambda: default_inventory
    )
    monkeypatch.setattr(local, "OpenBaoSecretProvider", lambda: default_secrets)
    defaults = local.LocalTerraformOperations("run-1", tmp_path)
    assert defaults._inventory is default_inventory
    assert defaults._secrets is default_secrets
    injected = local.LocalTerraformOperations(
        "run-1", tmp_path, inventory=object(), secrets=object(), cml_token="bearer"
    )
    assert type(injected) is driver.LocalTerraformOperations
    assert injected._inventory is not default_inventory
    assert injected._secrets is not default_secrets
    assert injected._environment()["CML2_TOKEN"] == "bearer"
    assert "bearer" not in repr(injected)
    assert "CML2_TOKEN" not in os.environ


def fake_lifecycle_operations(driver, monkeypatch, *, cleanup_fails):
    """Patch vendor operations only; run the real shared lifecycle and providers."""
    members = inventory_devices()
    requests, calls = [], []
    original = driver.LocalTerraformOperations
    monkeypatch.setattr(
        driver, "NetBoxProfileInventoryProvider", lambda **kw: SimpleNamespace(**kw)
    )
    monkeypatch.setattr(
        driver,
        "BuildkiteStagingSecretProvider",
        lambda jwt, ctx, **kw: BuildkiteStagingSecretProvider(
            jwt, ctx, **kw, transport=httpx.MockTransport(handler(requests))
        ),
    )

    def make(run_id, run_directory, **providers):
        assert providers["inventory"].token == "dedicated-token"
        assert isinstance(providers["secrets"], BuildkiteStagingSecretProvider)
        assert providers["cml_token"] == "memory-only-bearer"
        operation = original(run_id, run_directory, **providers)
        monkeypatch.setattr(original, "source_commit", property(lambda _: COMMIT))
        monkeypatch.setattr(
            original, "managed_resources_exist", property(lambda _: True)
        )
        ready_context = staging_context().model_dump(mode="python")
        trust = EvidenceReference(
            identity=f"staging-trust:{run_id}", digest="sha256:" + "a" * 64
        )
        ready_context.update(
            staging_run_id=run_id, cml_lab_title=f"NCDP Staging {run_id}"
        )
        ready_context["devices"] = tuple(
            item | {"trust_evidence": trust} for item in ready_context["devices"]
        )
        ready_context = StagingRealizationContext.model_validate(ready_context)

        def admit():
            calls.append("admit")
            for member in members:
                providers["secrets"].load(member)

        def create():
            calls.append("create")
            operation.create_stage = operation.start_stage = "succeeded"
            operation.lab_start_evidence = EvidenceReference(
                identity=f"staging-lab-start:{run_id}",
                digest="sha256:" + "c" * 64,
            )
            operation.transit_recycle_outcome = "succeeded"
            operation.transit_recycle_evidence = EvidenceReference(
                identity=f"staging-transit-recycle:{run_id}:transit-ios-01",
                digest="sha256:" + "b" * 64,
            )
            operation.readiness_evidence = tuple(
                ProfiledStagingReadinessEvidence(
                    device_identity=item.device_identity,
                    logical_name=item.logical_name,
                    automation_profile_id=item.automation_profile_id,
                    cml_realization_profile_id=item.cml_realization_profile_id,
                    cml_node_id=item.cml_node_id,
                    management_address=str(
                        item.staging_endpoint.binding.l3_endpoint.address.ip
                    ),
                    readiness_service=item.staging_endpoint.binding.l3_endpoint.service,
                    readiness_port=item.staging_endpoint.binding.l3_endpoint.port,
                    outcome="READY",
                    elapsed_seconds=1,
                    readiness_evidence=item.readiness_evidence,
                )
                for item in ready_context.devices
            )
            return ready_context

        def validate(_context):
            calls.append("validate")
            return tuple(
                ProfiledStagingDeviceEvidence(
                    **item.model_dump(
                        exclude={
                            "management_address",
                            "outcome",
                            "elapsed_seconds",
                            "cml_node_state",
                            "first_booted_seconds",
                        }
                    ),
                    readiness_seconds=1,
                    read_only_collection="succeeded",
                )
                for item in operation.readiness_evidence
            )

        def destroy(**_kwargs):
            calls.append("destroy")
            if cleanup_fails:
                raise ProfiledStagingAmbiguousError(
                    "memory-only-bearer protected-password"
                )

        def retire():
            calls.append("retire")
            run_directory.rmdir()

        operation.admit, operation.create, operation.validate = admit, create, validate
        operation.destroy_owned = destroy
        operation.verify_absent = lambda: calls.append("absence")
        operation.retire_state = retire
        return operation

    monkeypatch.setattr(driver, "LocalTerraformOperations", make)
    monkeypatch.setattr(driver, "authenticate_cml", lambda: "memory-only-bearer")
    return calls, requests


@pytest.mark.parametrize(
    "cleanup_fails,publication_fails,expected",
    [(False, False, 0), (False, True, 3), (True, False, 2), (True, True, 2)],
)
def test_driver_runs_shared_lifecycle_once_and_preserves_failure(
    driver, monkeypatch, tmp_path, capsys, cleanup_fails, publication_fails, expected
):
    calls, requests = fake_lifecycle_operations(
        driver, monkeypatch, cleanup_fails=cleanup_fails
    )
    commands = []

    def command(args, **kwargs):
        commands.append((args, kwargs))
        if args[1] == "oidc":
            return JWT + "\n"
        if publication_fails:
            raise OSError("publication secret must stay private")
        return ""

    monkeypatch.setattr(driver, "command", command)
    assert driver.run(context(), tmp_path) == expected
    assert calls == (
        ["admit", "create", "validate", "destroy"]
        + ([] if cleanup_fails else ["absence", "retire"])
    )
    assert len(requests) == 8
    assert commands[0][0] == [
        "buildkite-agent",
        "oidc",
        "request-token",
        "--audience",
        "urn:ncdp:openbao:staging",
        "--lifetime",
        "300",
        "--subject-claim",
        "pipeline_id",
        "--claim",
        "build_id",
    ]
    assert len(commands) == (4 if expected == 0 else 2)
    metadata_commands = [args for args, _ in commands if args[1] == "meta-data"]
    if expected == 0:
        from network_change_delivery.profiled_promotion import digest_bytes

        assert metadata_commands == [
            [
                "buildkite-agent",
                "meta-data",
                "set",
                "profiled-cml-success",
                digest_bytes(
                    (tmp_path / "evidence" / f"bk-{BUILD_ID}.json").read_bytes()
                ),
                "--job",
                JOB_ID,
            ]
        ]
        assert commands[-2][0][1:3] == ["artifact", "upload"]
    else:
        assert metadata_commands == []
    run = tmp_path / "ephemeral" / f"bk-{BUILD_ID}"
    assert run.exists() is cleanup_fails
    evidence_path = tmp_path / "evidence" / f"bk-{BUILD_ID}.json"
    text = evidence_path.read_text()
    evidence = ProfiledStagingEvidence.model_validate_json(text)
    assert evidence.build_id == BUILD_ID and evidence.source_commit == COMMIT
    assert driver.evidence_succeeded(evidence, context()) is not cleanup_fails
    if not cleanup_fails:
        for field in driver._PHASES:
            assert not driver.evidence_succeeded(
                evidence.model_copy(update={field: "not_attempted"}), context()
            )
        for field in (
            "lab_id",
            "topology_digest",
            "context_digest",
            "trust_generation",
            "transit_recycle_evidence",
            "lab_start_evidence",
        ):
            assert not driver.evidence_succeeded(
                evidence.model_copy(update={field: None}), context()
            )
        historical = ProfiledStagingEvidence.model_validate(
            evidence.model_dump(exclude={"lab_start_evidence"})
        )
        assert historical.final_outcome.value == "SUCCEEDED"
        assert not driver.evidence_succeeded(historical, context())
        for field, value in (
            ("source_commit", "b" * 40),
            ("build_id", JOB_ID),
            ("staging_run_id", "wrong-run"),
            ("readiness", ()),
            ("devices", ()),
            ("primary_failure", "failure"),
            ("cleanup_failure", "failure"),
        ):
            assert not driver.evidence_succeeded(
                evidence.model_copy(update={field: value}), context()
            )
    output = capsys.readouterr()
    for secret in (JWT, "memory-only-bearer", "protected-password", "dedicated-token"):
        assert secret not in text + output.out + output.err + repr(evidence) + repr(
            commands
        )
    assert "CML2_TOKEN" not in os.environ
    with pytest.raises(FileExistsError):
        driver.run(context(), tmp_path)
    assert len(commands) == (4 if expected == 0 else 2)


@pytest.mark.parametrize(
    "changes",
    [
        {"BUILDKITE_PULL_REQUEST_REPO": "https://github.com/fork/repo.git"},
        {"BUILDKITE_PULL_REQUEST_REPO": ""},
        {"BUILDKITE_REPO": "https://github.com/fork/repo.git"},
        {"BUILDKITE_RETRY_COUNT": "1"},
        {"BUILDKITE_STEP_KEY": "other"},
        {"BUILDKITE_AGENT_META_DATA_QUEUE": "ncdp-validation"},
        {"BUILDKITE_COMMAND": "scripts/buildkite/ephemeral_staging.sh"},
        {"BUILDKITE_COMMAND": ".buildkite/scripts/profiled_cml_staging.sh; env"},
    ],
)
def test_agent_hook_rejects_before_sourcing_credentials(tmp_path, changes):
    hook = tmp_path / "command"
    hook.write_text(
        (ROOT / "scripts/buildkite/staging_agent_command_hook.sh").read_text()
    )
    marker = tmp_path / "sourced"
    protected = tmp_path / "staging.env"
    protected.write_text(f'touch "{marker}"\n')
    protected.chmod(0o600)
    env = {
        "PATH": os.environ["PATH"],
        "BUILDKITE_STEP_KEY": "cml-staging",
        "BUILDKITE_AGENT_META_DATA_QUEUE": "ncdp-staging",
        "BUILDKITE_RETRY_COUNT": "0",
        "BUILDKITE_COMMAND": ".buildkite/scripts/profiled_cml_staging.sh",
        "BUILDKITE_REPO": CANONICAL,
        "BUILDKITE_PULL_REQUEST": "135",
        "BUILDKITE_PULL_REQUEST_REPO": CANONICAL,
        **changes,
    }
    result = subprocess.run(
        ["bash", str(hook)], env=env, cwd=tmp_path, capture_output=True
    )
    assert result.returncode == 2
    assert not marker.exists()


@pytest.mark.parametrize(
    "pull_request,branch", [("135", "feature/staging"), ("false", "main")]
)
def test_agent_hook_sources_only_installed_environment_then_exact_wrapper(
    tmp_path, pull_request, branch
):
    hook = tmp_path / "command"
    hook.write_text(
        (ROOT / "scripts/buildkite/staging_agent_command_hook.sh").read_text()
    )
    protected = tmp_path / "staging.env"
    protected.write_text(
        f"NCDP_BUILDKITE_PIPELINE_ID={PIPELINE_ID}\nNCDP_STAGING_TEST_ONLY=admitted\n"
    )
    protected.chmod(0o600)
    scripts = tmp_path / ".buildkite/scripts"
    scripts.mkdir(parents=True)
    wrapper = scripts / "profiled_cml_staging.sh"
    wrapper.write_text('#!/bin/bash\n[[ "$NCDP_STAGING_TEST_ONLY" == admitted ]]\n')
    wrapper.chmod(0o700)
    result = subprocess.run(
        ["bash", str(hook)],
        cwd=tmp_path,
        capture_output=True,
        env={
            "PATH": os.environ["PATH"],
            "BUILDKITE_STEP_KEY": "cml-staging",
            "BUILDKITE_PIPELINE_ID": PIPELINE_ID,
            "BUILDKITE_AGENT_META_DATA_QUEUE": "ncdp-staging",
            "BUILDKITE_RETRY_COUNT": "0",
            "BUILDKITE_COMMAND": ".buildkite/scripts/profiled_cml_staging.sh",
            "BUILDKITE_REPO": CANONICAL,
            "BUILDKITE_PULL_REQUEST": pull_request,
            "BUILDKITE_PULL_REQUEST_REPO": CANONICAL,
            "BUILDKITE_BRANCH": branch,
        },
    )
    assert result.returncode == 0
    assert result.stdout == b""


@pytest.mark.parametrize(
    "mode,actual,expected",
    [
        (0o600, JOB_ID, PIPELINE_ID),
        (0o600, PIPELINE_ID, None),
        (0o600, "", PIPELINE_ID),
        (0o644, PIPELINE_ID, PIPELINE_ID),
        (0o700, PIPELINE_ID, PIPELINE_ID),
        (0o600, PIPELINE_ID, PIPELINE_ID),
    ],
)
def test_hook_environment_mode_and_pipeline_before_checkout(
    tmp_path, mode, actual, expected
):
    hook = tmp_path / "command"
    hook.write_text(
        (ROOT / "scripts/buildkite/staging_agent_command_hook.sh").read_text()
    )
    sourced = tmp_path / "sourced"
    executed = tmp_path / "executed"
    protected = tmp_path / "staging.env"
    protected.write_text(
        f'touch "{sourced}"\n'
        "NCDP_CML_STAGING_PASSWORD=synthetic-secret-do-not-print\n"
        + (f"NCDP_BUILDKITE_PIPELINE_ID={expected}\n" if expected else "")
    )
    protected.chmod(mode)
    scripts = tmp_path / ".buildkite/scripts"
    scripts.mkdir(parents=True)
    wrapper = scripts / "profiled_cml_staging.sh"
    wrapper.write_text(f'#!/bin/bash\ntouch "{executed}"\n')
    wrapper.chmod(0o700)
    result = subprocess.run(
        ["bash", str(hook)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env={
            "PATH": os.environ["PATH"],
            "BUILDKITE_STEP_KEY": "cml-staging",
            "BUILDKITE_AGENT_META_DATA_QUEUE": "ncdp-staging",
            "BUILDKITE_RETRY_COUNT": "0",
            "BUILDKITE_COMMAND": ".buildkite/scripts/profiled_cml_staging.sh",
            "BUILDKITE_REPO": CANONICAL,
            "BUILDKITE_PULL_REQUEST": "135",
            "BUILDKITE_PULL_REQUEST_REPO": CANONICAL,
            "BUILDKITE_PIPELINE_ID": actual,
            # Even an inherited matching expected ID cannot replace a missing
            # declaration in the protected file.
            "NCDP_BUILDKITE_PIPELINE_ID": PIPELINE_ID,
        },
    )
    admitted = mode == 0o600 and actual == expected
    assert result.returncode == (0 if admitted else 2)
    assert sourced.exists() is (mode == 0o600)
    assert executed.exists() is admitted
    assert "synthetic-secret-do-not-print" not in result.stdout + result.stderr
    assert PIPELINE_ID not in result.stdout + result.stderr


@pytest.mark.parametrize(
    "key,value",
    [
        ("BUILDKITE_STEP_KEY", "other"),
        ("BUILDKITE_AGENT_META_DATA_QUEUE", "other"),
        ("BUILDKITE_RETRY_COUNT", "1"),
    ],
)
def test_shell_wrapper_fails_before_driver(key, value):
    result = subprocess.run(
        ["bash", str(ROOT / ".buildkite/scripts/profiled_cml_staging.sh")],
        capture_output=True,
        env={
            "PATH": os.environ["PATH"],
            "BUILDKITE_STEP_KEY": "cml-staging",
            "BUILDKITE_AGENT_META_DATA_QUEUE": "ncdp-staging",
            "BUILDKITE_RETRY_COUNT": "0",
            key: value,
        },
    )
    assert result.returncode == 2
    assert b"context rejected" in result.stderr


@pytest.mark.parametrize(
    "case", ["wrong-commit", "dirty", "untracked", "clean-pr", "clean-main"]
)
@pytest.mark.skipif(shutil.which("git") is None, reason="Git is not installed")
def test_staging_commit_verification_is_exact_without_remote_fetch(tmp_path, case):
    def git(*args):
        return subprocess.run(
            ["git", *args], cwd=tmp_path, capture_output=True, text=True, check=True
        ).stdout.strip()

    git("init", "--quiet")
    tracked = tmp_path / "tracked"
    tracked.write_text("original\n")
    git("add", "tracked")
    git(
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "commit",
        "--quiet",
        "-m",
        "fixture",
    )
    commit = git("rev-parse", "HEAD")
    if case == "dirty":
        tracked.write_text("changed\n")
    if case == "untracked":
        (tmp_path / "unknown").touch()
    result = subprocess.run(
        ["bash", str(ROOT / "scripts/buildkite/verify_commit.sh")],
        cwd=tmp_path,
        capture_output=True,
        env={
            "PATH": os.environ["PATH"],
            "BUILDKITE_STEP_KEY": "cml-staging",
            "BUILDKITE_COMMIT": "a" * 40 if case == "wrong-commit" else commit,
            "BUILDKITE_BRANCH": "main" if case == "clean-main" else "feature/staging",
        },
    )
    assert result.returncode == (0 if case.startswith("clean") else 2)


def test_driver_helper_children_never_inherit_staging_secrets(driver, monkeypatch):
    calls = []

    def execute(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=0, stdout="bounded")

    monkeypatch.setattr(driver.subprocess, "run", execute)
    assert driver.command(["buildkite-agent", "annotate"], stdin="summary") == "bounded"
    assert not set(driver._PROTECTED_NAMES) & set(calls[0][1]["env"])
    assert "CML2_TOKEN" not in calls[0][1]["env"]
