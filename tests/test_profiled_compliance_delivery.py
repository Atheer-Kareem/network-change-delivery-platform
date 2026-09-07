"""Offline current planning through final evidence; no external helpers."""

import json
from dataclasses import replace

import pytest
from test_profiled_buildkite_delivery import (
    CHANGE_ID,
    DESCRIPTION,
    PLANNING_METADATA,
)
from test_profiled_buildkite_delivery import (
    context as context_fixture,
)
from test_profiled_buildkite_delivery import (
    driver as driver_fixture,
)
from test_profiled_planning import (
    FakeCollector,
    FakeInventory,
    FakeSecrets,
    observed,
    profiled_device,
)

from network_change_delivery.architecture_contracts import AutomationProfileID
from network_change_delivery.models import InterfaceDescriptionIntent
from network_change_delivery.profiled_planning import (
    ProfiledComplianceRecord,
    ProfiledDeploymentPlan,
    plan_profiled_change,
)
from network_change_delivery.profiled_promotion import digest_bytes

context = context_fixture
driver = driver_fixture


@pytest.fixture
def offline(driver, monkeypatch):
    device, interface = profiled_device(AutomationProfileID.CAT8000V_IOSXE)
    state = observed(device, interface).model_copy(update={"description": DESCRIPTION})
    monkeypatch.setattr(driver, "validate_profiled_live_host_trust", lambda: None)
    monkeypatch.setattr(
        driver,
        "NetBoxProfileInventoryProvider",
        lambda: FakeInventory(device, interface),
    )
    monkeypatch.setattr(driver, "OpenBaoSecretProvider", FakeSecrets)
    monkeypatch.setattr(
        driver, "ProfileReadOnlyAdapter", lambda **_k: FakeCollector(state)
    )
    artifacts, metadata, annotations = {}, {}, []

    def upload(ctx, directory, name):
        artifacts[(ctx.build_id, ctx.step, name)] = (directory / name).read_bytes()

    def download(ctx, directory, name, step):
        raw = artifacts.get((ctx.build_id, step, name))
        if raw is None:
            raise ValueError("missing exact artifact")
        driver.write_new(directory / name, raw)
        return raw

    def get_metadata(ctx, key):
        value = metadata.get((ctx.build_id, key))
        if value is None:
            raise ValueError("missing publication receipt")
        return value

    monkeypatch.setattr(driver, "upload", upload)
    monkeypatch.setattr(driver, "download", download)
    monkeypatch.setattr(driver, "metadata", get_metadata)
    monkeypatch.setattr(
        driver,
        "publish_metadata",
        lambda c, k, v: metadata.__setitem__((c.build_id, k), v),
    )
    monkeypatch.setattr(
        driver, "annotate", lambda c, text, **_k: annotations.append((c.step, text))
    )
    monkeypatch.setattr(
        driver, "command", lambda *_a, **_k: pytest.fail("deploy command forbidden")
    )
    return artifacts, metadata, annotations


def planning(driver, context, tmp_path):
    ctx = replace(context, step="profiled-live-plan")
    directory = tmp_path / "planning"
    directory.mkdir()
    assert driver.plan_step(ctx, directory) == 0


def downstream(driver, context, tmp_path):
    for step, function in (
        ("profiled-promotion", driver.promotion_step),
        ("profiled-deploy", driver.deploy_step),
        ("profiled-deployment-evidence", driver.evidence_step),
    ):
        directory = tmp_path / step
        directory.mkdir()
        yield step, function, replace(context, step=step), directory


@pytest.mark.parametrize("unblocker", [None, "reviewer-continued"])
def test_real_compliant_planner_through_entire_static_delivery_tail(
    driver, context, offline, tmp_path, monkeypatch, unblocker
):
    artifacts, metadata, annotations = offline
    planning(driver, context, tmp_path)
    assert len(artifacts) == 1 and len(metadata) == 1
    key, raw = next(iter(artifacts.items()))
    assert key[1] == "profiled-live-plan" and key[2].endswith("-compliance.json")
    value = ProfiledComplianceRecord.model_validate_json(raw)
    assert value.plan is None and value.outcome == "COMPLIANT"
    assert value.observed_description == value.desired_description == DESCRIPTION
    assert not value.promotion_minted
    assert not value.execution_attempted and not value.recovery_attempted
    with pytest.raises(ValueError):
        ProfiledDeploymentPlan.model_validate_json(raw)
    if unblocker is None:
        monkeypatch.delenv("BUILDKITE_UNBLOCKER_ID", raising=False)
    else:
        monkeypatch.setenv("BUILDKITE_UNBLOCKER_ID", unblocker)
    for name in (
        "promote",
        "authorize",
        "prerequisites",
        "validate_profiled_live_host_trust",
        "NetBoxProfileInventoryProvider",
        "OpenBaoSecretProvider",
        "ProfileReadOnlyAdapter",
    ):
        monkeypatch.setattr(
            driver,
            name,
            lambda *_a, **_k: pytest.fail("device/authority path forbidden"),
        )
    for _step, function, ctx, directory in downstream(driver, context, tmp_path):
        assert function(ctx, directory) == 0
        assert [p.name for p in directory.iterdir()] == [key[2]]
    assert len(artifacts) == len(metadata) == 1
    for _step, message in annotations[1:]:
        for text in (
            "Outcome: COMPLIANT",
            "Write attempted: False",
            "Recovery attempted: False",
            "Promotion minted: False",
            "unblock grants zero write authority",
            "Compliance was established by the planning observation at "
            f"{value.observed_at.isoformat()}",
            "downstream continuation does not perform a fresh device-state check",
            "because no write is authorized",
        ):
            assert text in message


@pytest.mark.parametrize(
    "damage",
    [
        "receipt_missing",
        "artifact_missing",
        "build",
        "commit",
        "kind",
        "bytes",
        "result_digest",
        "model_digest",
        "description",
        "attempted",
        "promotion",
        "interface",
        "profile",
        "credential",
        "timestamp",
        "target",
    ],
)
def test_invalid_or_missing_compliance_never_becomes_authority_or_success(
    driver, context, offline, tmp_path, damage, monkeypatch
):
    artifacts, metadata, annotations = offline
    planning(driver, context, tmp_path)
    key, raw = next(iter(artifacts.items()))
    receipt_key = (context.build_id, PLANNING_METADATA)
    receipt = json.loads(metadata[receipt_key])
    if damage == "receipt_missing":
        metadata.clear()
    elif damage == "artifact_missing":
        artifacts.clear()
    elif damage in {"build", "commit", "kind", "bytes", "result_digest"}:
        field, value = {
            "build": ("build_id", "99999999-9999-4999-8999-999999999999"),
            "commit": ("commit", "b" * 40),
            "kind": ("artifact_kind", "plan"),
            "bytes": ("artifact_digest", "sha256:" + "0" * 64),
            "result_digest": ("result_digest", "sha256:" + "0" * 64),
        }[damage]
        receipt[field] = value
        metadata[receipt_key] = json.dumps(receipt)
    else:
        body = json.loads(raw)
        field, value = {
            "model_digest": ("digest", "sha256:" + "0" * 64),
            "description": ("observed_description", "not desired"),
            "attempted": ("execution_attempted", True),
            "promotion": ("promotion_minted", True),
            "interface": (
                "interface",
                {**body["interface"], "device": "netbox:dcim.device:2"},
            ),
            "profile": ("automation_profile_id", "iosv"),
            "credential": ("credential_reference", "openbao:kv-v2:ncdp/devices/9/ssh"),
            "timestamp": ("observed_at", "2026-01-01T00:00:00"),
            "target": ("target", "unadmitted"),
        }[damage]
        body[field] = value
        # Even recomputing the outer receipt cannot repair an invalid typed result.
        raw = json.dumps(body).encode()
        artifacts[key] = raw
        receipt["artifact_digest"] = digest_bytes(raw)
        receipt["result_digest"] = body["digest"]
        metadata[receipt_key] = json.dumps(receipt)
    monkeypatch.setenv("BUILDKITE_UNBLOCKER_ID", "reviewer-continued")
    annotations.clear()
    for step, function, ctx, directory in downstream(driver, context, tmp_path):
        if step == "profiled-promotion":
            with pytest.raises(ValueError):
                function(ctx, directory)
        else:
            assert function(ctx, directory) == 2
    assert all("Outcome: COMPLIANT" not in message for _, message in annotations)
    assert "Artifact unavailability is not proof of absence" in annotations[-1][1]
    assert not any(
        k[2].endswith(("-promotion.json", "-record.json")) for k in artifacts
    )


def test_failed_actual_planning_publishes_neither_artifact_nor_receipt(
    driver, context, offline, tmp_path, monkeypatch
):
    artifacts, metadata, annotations = offline
    device, interface = profiled_device(AutomationProfileID.CAT8000V_IOSXE)
    wrong = observed(device, interface).model_copy(
        update={"observed_hostname": "wrong"}
    )
    monkeypatch.setattr(
        driver, "ProfileReadOnlyAdapter", lambda **_k: FakeCollector(wrong)
    )
    with pytest.raises(driver.PlanPhaseError):
        driver.plan_step(replace(context, step="profiled-live-plan"), tmp_path)
    assert not artifacts and not metadata and not annotations
    for step, function, ctx, directory in downstream(driver, context, tmp_path):
        if step == "profiled-promotion":
            with pytest.raises(ValueError):
                function(ctx, directory)
        else:
            assert function(ctx, directory) == 2
    assert all("Outcome: COMPLIANT" not in message for _, message in annotations)


@pytest.mark.parametrize("failure", ["upload", "annotate"])
def test_incomplete_publication_never_issues_planning_receipt(
    driver, context, offline, tmp_path, monkeypatch, failure
):
    def fail(*_a, **_k):
        raise ValueError("publication unavailable")

    monkeypatch.setattr(driver, failure, fail)
    with pytest.raises(driver.PlanPhaseError):
        driver.plan_step(replace(context, step="profiled-live-plan"), tmp_path)
    assert not offline[1]


@pytest.mark.parametrize(
    "profile", [AutomationProfileID.CAT8000V_IOSXE, AutomationProfileID.VJUNOS_ROUTER]
)
def test_compliance_contract_is_shared_by_both_admitted_vendor_planners(profile):
    device, interface = profiled_device(profile)
    intent = InterfaceDescriptionIntent(
        kind="interface_description",
        change_id=CHANGE_ID,
        target=device.logical_name,
        interface=interface.name,
        desired={"description": DESCRIPTION},
    )
    value = plan_profiled_change(
        intent,
        FakeInventory(device, interface),
        FakeSecrets(),
        FakeCollector(
            observed(device, interface).model_copy(update={"description": DESCRIPTION})
        ),
    )
    assert value.plan is None
    assert value.compliance.automation_profile_id is profile
    assert (
        ProfiledComplianceRecord.model_validate_json(value.compliance.model_dump_json())
        == value.compliance
    )
    with pytest.raises(ValueError):
        value.compliance.target = "changed"
