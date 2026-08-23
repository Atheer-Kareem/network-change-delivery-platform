"""CLI tests for protected single-device Buildkite deployment composition."""

from __future__ import annotations

import json
import stat
import sys
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

import pytest

import network_change_delivery.buildkite_deployment as deployment_module
import network_change_delivery.cli as cli_module
from network_change_delivery.buildkite_deployment import (
    LIVE_DEPLOYMENT_REQUEST,
    LiveDeploymentRequest,
    live_deployment_request_changed,
    load_promoted_single_plan,
)
from network_change_delivery.models import FinalOutcome
from network_change_delivery.promotion import PromotionError

sys.path.insert(0, str(Path(__file__).parent))
from test_workflow import plan as workflow_plan

JWT = "secret.header.signature"


def environment(monkeypatch: pytest.MonkeyPatch) -> None:
    values = {
        "BUILDKITE_COMMIT": "a" * 40,
        "BUILDKITE_BRANCH": "main",
        "BUILDKITE_PULL_REQUEST": "false",
        "BUILDKITE_PIPELINE_ID": "pipeline-uuid",
        "BUILDKITE_BUILD_ID": "build-uuid",
        "BUILDKITE_BUILD_NUMBER": "17",
        "BUILDKITE_JOB_ID": "job-uuid",
        "BUILDKITE_STEP_KEY": "deploy-gate",
        "BUILDKITE_AGENT_META_DATA_QUEUE": "ncdp-deploy",
        "NCDP_OPENBAO_URL": "https://openbao.example",
        "NCDP_NETBOX_URL": "https://netbox.example",
        "NCDP_NETBOX_TOKEN": "sensitive-netbox-token",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)


def promoted_plan():
    candidate = workflow_plan().model_copy(
        update={
            "inventory_source": "netbox",
            "inventory_object_id": "netbox:dcim.device:1",
            "inventory_interface_object_id": "netbox:dcim.interface:2",
            "credential_source": "openbao",
            "credential_reference": "openbao:kv-v2:ncdp/devices/1/ssh",
            "digest": "sha256:pending",
        }
    )
    return candidate.model_copy(update={"digest": candidate.calculated_digest()})


def request_for(plan):
    return LiveDeploymentRequest(
        schema_version="1",
        action="deploy",
        change_id=plan.change_id,
        plan_digest=plan.digest,
        inventory_object_id=plan.inventory_object_id,
    )


def test_deploy_command_reads_jwt_from_stdin_reuses_deploy_plan_and_writes_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    environment(monkeypatch)
    approved = promoted_plan()
    request = request_for(approved)
    monkeypatch.setattr(
        cli_module,
        "_verified_live_request",
        lambda _promotion, _context: (object(), approved, request),
    )
    observed: dict[str, object] = {}

    class Inventory:
        pass

    class Secrets:
        def __init__(self, jwt, context):
            observed["jwt"] = jwt.value
            observed["pipeline"] = context.pipeline_id

    class Adapter:
        pass

    class Record:
        final_outcome = FinalOutcome.SUCCEEDED

        def model_dump_json(self, *, indent: int) -> str:
            assert indent == 2
            return '{"final_outcome":"SUCCEEDED"}'

    def deploy_spy(plan, digest, inventory, secrets, collector, executor):
        observed.update(
            plan=plan,
            digest=digest,
            inventory=inventory,
            secrets=secrets,
            same_adapter=collector is executor,
        )
        return Record()

    monkeypatch.setattr(cli_module, "NetBoxInventoryProvider", Inventory)
    monkeypatch.setattr(cli_module, "BuildkiteOpenBaoDeploymentSecretProvider", Secrets)
    monkeypatch.setattr(cli_module, "MultiVendorAdapter", Adapter)
    monkeypatch.setattr(cli_module, "deploy_plan", deploy_spy)
    monkeypatch.setattr(sys, "stdin", StringIO(JWT + "\n"))
    report = tmp_path / "evidence" / "record.json"
    assert (
        cli_module.main(
            [
                "deploy-buildkite-promotion",
                "--promotion",
                str(tmp_path / "promotion"),
                "--report-json",
                str(report),
            ]
        )
        == 0
    )
    assert observed["jwt"] == JWT
    assert observed["pipeline"] == "pipeline-uuid"
    assert observed["plan"] is approved
    assert observed["digest"] == approved.digest
    assert observed["same_adapter"] is True
    assert stat.S_IMODE(report.stat().st_mode) == 0o600
    output = capsys.readouterr()
    assert JWT not in output.out + output.err
    assert "sensitive-netbox-token" not in output.out + output.err


def test_verify_live_request_uses_no_inventory_secret_or_adapter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    environment(monkeypatch)
    approved = promoted_plan()
    request = request_for(approved)
    monkeypatch.setattr(
        cli_module,
        "_verified_live_request",
        lambda _promotion, _context: (object(), approved, request),
    )

    class Forbidden:
        def __init__(self, *_args, **_kwargs):
            raise AssertionError("provider construction is forbidden")

    monkeypatch.setattr(cli_module, "NetBoxInventoryProvider", Forbidden)
    monkeypatch.setattr(
        cli_module, "BuildkiteOpenBaoDeploymentSecretProvider", Forbidden
    )
    monkeypatch.setattr(cli_module, "MultiVendorAdapter", Forbidden)
    assert (
        cli_module.main(["verify-buildkite-live-request", "--promotion", str(tmp_path)])
        == 0
    )
    assert "live deployment requested: YES" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("returncode", "present", "expected"),
    [(0, False, False), (1, False, False), (1, True, True)],
)
def test_commit_bound_request_unchanged_deleted_or_changed_present(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    returncode: int,
    present: bool,
    expected: bool,
) -> None:
    if present:
        request = tmp_path / LIVE_DEPLOYMENT_REQUEST
        request.parent.mkdir(parents=True)
        request.write_text("bounded", encoding="utf-8")
    observed: dict[str, object] = {}

    def run_spy(command, **kwargs):
        observed["command"] = command
        observed["kwargs"] = kwargs
        return SimpleNamespace(returncode=returncode)

    monkeypatch.setattr(deployment_module.subprocess, "run", run_spy)
    assert live_deployment_request_changed("a" * 40, root=tmp_path) is expected
    assert observed["command"] == [
        "git",
        "diff",
        "--quiet",
        "a" * 40 + "^",
        "a" * 40,
        "--",
        "deployments/live/request.yaml",
    ]


def test_no_request_status_stops_without_providers(
    monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    environment(monkeypatch)
    monkeypatch.setattr(
        cli_module, "live_deployment_request_changed", lambda _commit: False
    )

    class Forbidden:
        def __init__(self, *_args, **_kwargs):
            raise AssertionError("provider construction is forbidden")

    monkeypatch.setattr(cli_module, "NetBoxInventoryProvider", Forbidden)
    monkeypatch.setattr(
        cli_module, "BuildkiteOpenBaoDeploymentSecretProvider", Forbidden
    )
    assert cli_module.main(["buildkite-live-request-status"]) == 3
    output = capsys.readouterr().out
    assert "live deployment requested: NO" in output
    assert "device write executed: NO" in output


def test_deployment_boundary_independently_requires_request_changed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = SimpleNamespace(commit="a" * 40)
    monkeypatch.setattr(
        cli_module, "live_deployment_request_changed", lambda _commit: False
    )
    monkeypatch.setattr(
        cli_module,
        "load_promoted_single_plan",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("promotion must not load for an unchanged request")
        ),
    )
    with pytest.raises(PromotionError, match="was not changed"):
        cli_module._verified_live_request(tmp_path, context)


def test_promoted_fleet_plan_is_rejected_before_model_or_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    promotion = tmp_path / "promotion"
    promotion.mkdir()
    (promotion / "plan.json").write_text(
        json.dumps({"schema_version": "1", "members": []}), encoding="utf-8"
    )
    monkeypatch.setattr(
        deployment_module,
        "verify_promotion_bundle",
        lambda _path, _commit: SimpleNamespace(plan_digest="sha256:" + "a" * 64),
    )
    with pytest.raises(PromotionError, match="one DeploymentPlan"):
        load_promoted_single_plan(promotion, "a" * 40)


@pytest.mark.parametrize(
    "changes",
    [
        {"inventory_source": "local_yaml"},
        {"credential_source": "environment"},
        {"credential_reference": "openbao:kv-v2:ncdp/devices/2/ssh"},
    ],
)
def test_promoted_plan_requires_netbox_and_exact_openbao_provenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, changes: dict[str, object]
) -> None:
    approved = promoted_plan().model_copy(update=changes)
    approved = approved.model_copy(update={"digest": approved.calculated_digest()})
    promotion = tmp_path / "promotion"
    promotion.mkdir()
    (promotion / "plan.json").write_text(approved.model_dump_json(), encoding="utf-8")
    monkeypatch.setattr(
        deployment_module,
        "verify_promotion_bundle",
        lambda _path, _commit: SimpleNamespace(plan_digest=approved.digest),
    )
    with pytest.raises(PromotionError, match="provenance rejected"):
        load_promoted_single_plan(promotion, "a" * 40)
