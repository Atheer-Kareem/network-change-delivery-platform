"""Committed selection through real planning/delivery composition, offline only."""

import ast
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
import yaml
from profiled_chronology_fixtures import observation
from profiled_intent_fixtures import historical_core_intent
from test_profiled_buildkite_delivery import DIGEST, JOB, ROOT
from test_profiled_buildkite_delivery import context as context_fixture
from test_profiled_buildkite_delivery import driver as driver_fixture
from test_profiled_compliance_delivery import offline as offline_fixture
from test_profiled_execution import Cisco, Collector, Inventory, Junos, Secrets, writer
from test_profiled_planning import (
    FakeCollector,
    FakeInventory,
    FakeSecrets,
    observed,
    profiled_device,
)

from network_change_delivery.architecture_contracts import (
    AutomationProfileID as Profile,
)
from network_change_delivery.audit import AuditArtifactKind as Kind
from network_change_delivery.audit import canonical_json_bytes
from network_change_delivery.models import ExecutionResult, InterfaceDescriptionIntent
from network_change_delivery.profiled_configuration_observation_store import (
    ProfiledConfigurationObservationStore,
)
from network_change_delivery.profiled_execution import execute_profiled_plan
from network_change_delivery.profiled_intent import (
    ACTIVE_INTENT_PATH,
    MAX_INTENT_BYTES,
    admit_intent_result,
    load_committed_intent,
)
from network_change_delivery.profiled_planning import (
    ProfiledDeploymentPlan,
    plan_profiled_change,
)
from network_change_delivery.profiled_promotion import (
    VALIDATION_KEYS,
    ProfiledPromotion,
    authorize,
    digest_bytes,
    promote,
    validation_receipt,
)

context, driver, offline = context_fixture, driver_fixture, offline_fixture
PROFILES = (
    Profile.CAT8000V_IOSXE,
    Profile.VJUNOS_ROUTER,
    Profile.IOSV_159_3_M12,
    Profile.IOSVL2_2020,
)


def selected(profile, compliant=False):
    device, interface = profiled_device(profile)
    if profile in (Profile.CAT8000V_IOSXE, Profile.VJUNOS_ROUTER):
        interface = interface.model_copy(
            update={
                "name": "ge-0/0/1"
                if profile is Profile.VJUNOS_ROUTER
                else "GigabitEthernet3",
                "interface": "netbox:dcim.interface:99",
            }
        )
    intent = InterfaceDescriptionIntent(
        change_id="CHG-INTENT-JUNOS-001"
        if profile is Profile.VJUNOS_ROUTER
        else "CHG-INTENT-CISCO-002",
        kind="interface_description",
        target=device.logical_name,
        interface=interface.name,
        desired={"description": "reviewed alternative description"},
    )
    state = observed(
        device,
        interface,
        description=intent.desired.description if compliant else "previous",
    )
    return intent, device, interface, state


def committed(checkout, intent):
    path = checkout / ACTIVE_INTENT_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(intent.model_dump(mode="json")))
    return path


def receipts(context):
    return {
        key: validation_receipt(context.build_id, context.commit, key)
        for key in VALIDATION_KEYS
    }


def planned(profile=Profile.VJUNOS_ROUTER, compliant=False):
    intent, device, interface, state = selected(profile, compliant)
    result = plan_profiled_change(
        intent, FakeInventory(device, interface), FakeSecrets(), FakeCollector(state)
    )
    return intent, result.plan or result.compliance


@pytest.mark.parametrize(
    "fault",
    [
        "missing",
        "empty",
        "directory",
        "symlink",
        "parent_symlink",
        "malformed",
        "multiple",
        "unknown_field",
        "kind",
        "unknown_target",
        "duplicate_key",
        "oversized",
    ],
)
def test_fixed_loader_fails_closed(tmp_path, fault):
    intent, *_ = selected(Profile.CAT8000V_IOSXE)
    path = committed(tmp_path, intent)
    if fault == "missing":
        path.unlink()
    elif fault == "empty":
        path.write_bytes(b"")
    elif fault == "directory":
        path.unlink()
        path.mkdir()
    elif fault == "symlink":
        outside = tmp_path / "outside.yaml"
        path.rename(outside)
        path.symlink_to(outside)
    elif fault == "parent_symlink":
        outside = tmp_path / "outside"
        path.parent.rename(outside)
        path.parent.symlink_to(outside, target_is_directory=True)
    elif fault == "malformed":
        path.write_text("[invalid")
    elif fault == "multiple":
        path.write_text(path.read_text() + "\n---\n{}\n")
    elif fault == "unknown_field":
        path.write_text(path.read_text() + "host: 192.0.2.1\n")
    elif fault == "duplicate_key":
        path.write_text(path.read_text() + "target: core-02\n")
    elif fault == "oversized":
        path.write_bytes(b" " * (MAX_INTENT_BYTES + 1))
    else:
        data = intent.model_dump()
        data["kind" if fault == "kind" else "target"] = "unsupported"
        path.write_text(yaml.safe_dump(data))
    with pytest.raises(ValueError, match="committed deployment intent"):
        load_committed_intent(tmp_path)


def test_loader_has_no_environment_selector(tmp_path, monkeypatch):
    intent, *_ = selected(Profile.VJUNOS_ROUTER)
    committed(tmp_path, intent)
    monkeypatch.setenv("NCDP_INTENT_PATH", "/missing")
    monkeypatch.setenv("NCDP_TARGET", "core-02")
    assert load_committed_intent(tmp_path) == intent


@pytest.mark.parametrize("profile", PROFILES)
@pytest.mark.parametrize("case", ["execution", "compliant", "chronology_failure"])
def test_same_driver_plans_promotes_authorizes_and_persists_admitted_profiles(
    driver, context, offline, tmp_path, monkeypatch, profile, case
):
    compliant = case == "compliant"
    chronology_failure = case == "chronology_failure"
    if chronology_failure:

        def fail_publication(*_args, **_kwargs):
            raise ValueError("synthetic chronology persistence failure")

        monkeypatch.setattr(
            ProfiledConfigurationObservationStore,
            "persist_profiled_observation_record",
            fail_publication,
        )
    intent, device, interface, state = selected(profile, compliant)
    checkout = tmp_path / "checkout"
    committed(checkout, intent)
    (checkout / ".buildkite").mkdir()
    (checkout / ".buildkite/pipeline.yml").write_bytes(
        (ROOT / ".buildkite/pipeline.yml").read_bytes()
    )
    monkeypatch.setattr(driver, "ROOT", checkout)
    monkeypatch.setattr(
        driver,
        "NetBoxProfileInventoryProvider",
        lambda: FakeInventory(device, interface),
    )
    monkeypatch.setattr(
        driver, "ProfileReadOnlyAdapter", lambda **_k: FakeCollector(state)
    )
    _artifacts, metadata, annotations = offline
    for key, value in receipts(context).items():
        metadata[(context.build_id, "profiled-validation-" + key)] = value
    metadata[(context.build_id, driver.BATFISH_METADATA)] = DIGEST
    metadata[(context.build_id, driver.CML_METADATA)] = DIGEST
    monkeypatch.setenv("BUILDKITE_UNBLOCKER_ID", JOB)
    calls = []

    def command(args, **kwargs):
        assert kwargs == {"device_authority": True}
        calls.append(args)
        plan = ProfiledDeploymentPlan.model_validate_json(
            Path(args[args.index("--plan") + 1]).read_bytes()
        )
        success = ExecutionResult(
            disposition="SUCCEEDED", changed=None, message="fixture"
        )
        record = execute_profiled_plan(
            plan,
            plan.digest,
            Inventory(device, interface),
            Secrets(),
            Collector(
                [
                    state,
                    state.model_copy(
                        update={"description": intent.desired.description}
                    ),
                ]
            ),
            writer(Cisco([success]), Junos(success, success)),
        )
        assert record.final_outcome.value == "SUCCEEDED"
        if profile is Profile.VJUNOS_ROUTER:
            assert (
                record.candidate_validation.succeeded and record.confirmation.succeeded
            )
        Path(args[args.index("--report-json") + 1]).write_bytes(
            record.model_dump_json().encode()
        )
        return SimpleNamespace(returncode=0)

    def capture(_plan, *, expected_before=None):
        attempt = observation(expected_before=expected_before)
        data = attempt.model_dump(mode="json")
        for key in ("before_revision", "after_revision"):
            data[key]["config_path"] = (
                "managed/netbox-device-" + device.device_identity.rsplit(":", 1)[1]
            )
        return type(attempt).model_validate(data)

    monkeypatch.setattr(driver, "command", command)
    monkeypatch.setattr(driver, "capture_profiled_attempt", capture)
    for step, func in [
        ("profiled-live-plan", driver.plan_step),
        ("profiled-promotion", driver.promotion_step),
        ("profiled-deploy", driver.deploy_step),
        ("profiled-deployment-evidence", driver.evidence_step),
    ]:
        directory = tmp_path / step
        directory.mkdir(mode=0o700)
        if compliant and step != "profiled-live-plan":
            for name in (
                "command",
                "capture_profiled_attempt",
                "prerequisites",
                "authorize",
                "promote",
                "validate_profiled_live_host_trust",
                "NetBoxProfileInventoryProvider",
                "OpenBaoSecretProvider",
                "ProfileReadOnlyAdapter",
            ):
                monkeypatch.setattr(
                    driver,
                    name,
                    lambda *_a, **_k: pytest.fail(
                        "compliant downstream must not enter authority or devices"
                    ),
                )
        expected = (
            3
            if chronology_failure
            and step in {"profiled-deploy", "profiled-deployment-evidence"}
            else 0
        )
        assert func(replace(context, step=step), directory) == expected
    store = ProfiledConfigurationObservationStore(
        Path(driver.os.environ["NCDP_AUDIT_STORE_ROOT"]),
        checkout=checkout,
        create=False,
    )
    record = store.read_profiled_record(UUID(JOB))
    assert (
        record.target.device == device.device_identity
        and record.target.interface == interface.interface
    )
    assert record.credential.device == device.device_identity
    assert len(calls) == (0 if compliant else 1)
    if compliant:
        assert record.authorization is None and record.assurance is None
        assert {a.kind for a in record.artifacts} == {Kind.PROFILED_COMPLIANCE_RECORD}
        assert store.iter_profiled_observation_records() == ()
        assert (
            "Configuration chronology: NOT REQUIRED — COMPLIANT" in annotations[-1][1]
        )
        assert "Transaction strategy" not in annotations[0][1]
    else:
        assert (
            record.authorization.promotion_digest
            == metadata[(context.build_id, driver.PROMOTION_METADATA)]
        )
        assert (
            record.assurance.batfish_digest == DIGEST
            and record.assurance.cml_digest == DIGEST
        )
        assert record.final_outcome.value == "SUCCEEDED"
        assert len(store.find_by_profiled_parent(record.record_id)) == (
            0 if chronology_failure else 1
        )
        status = "NOT ESTABLISHED" if chronology_failure else "SUCCEEDED"
        assert f"Configuration chronology: {status}" in annotations[-1][1]
        assert str(record.record_id) in annotations[-1][1]
        assert "Durable publication: NOT ESTABLISHED" not in annotations[-1][1]
    for fact in (
        intent.change_id,
        intent.target,
        device.device_identity,
        interface.name,
        interface.interface,
        profile.value,
        intent.desired.description,
    ):
        assert fact in annotations[0][1]


@pytest.mark.parametrize(
    "field", ["target", "interface", "description", "change_id", "kind"]
)
def test_mutated_committed_intent_cannot_authorize_old_promotion(context, field):
    intent, plan = planned()
    promotion = promote(
        context,
        plan.model_dump_json().encode(),
        receipts(context),
        DIGEST,
        DIGEST,
        intent=intent,
    )
    data = intent.model_dump()
    if field == "description":
        data["desired"]["description"] = "different"
    else:
        data[field] = {
            "target": "core-02",
            "interface": "ge-0/0/2",
            "change_id": "CHG-CHANGED",
            "kind": "unsupported",
        }[field]
    with pytest.raises(ValueError):
        current = InterfaceDescriptionIntent.model_validate(data)
        authorize(
            context,
            promotion.model_dump_json().encode(),
            plan.model_dump_json().encode(),
            receipts(context),
            DIGEST,
            DIGEST,
            promotion.digest,
            JOB,
            intent=current,
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("target", "core-02"),
        ("device_identity", "netbox:dcim.device:1"),
        ("pair", None),
        ("plan_digest", "sha256:" + "c" * 64),
        ("plan_artifact_digest", "sha256:" + "c" * 64),
        ("build_id", JOB),
        ("commit", "b" * 40),
        ("validation_digest", "sha256:" + "c" * 64),
        ("batfish_digest", "sha256:" + "c" * 64),
        ("cml_digest", "sha256:" + "c" * 64),
    ],
)
def test_rehashed_promotion_tampering_fails(context, field, value):
    intent, plan = planned()
    raw = plan.model_dump_json().encode()
    p = promote(context, raw, receipts(context), DIGEST, DIGEST, intent=intent)
    data = p.model_dump(mode="json")
    if field == "pair":
        data.update(target="core-02", device_identity="netbox:dcim.device:1")
    else:
        data[field] = value
    data["digest"] = digest_bytes(
        canonical_json_bytes({k: v for k, v in data.items() if k != "digest"})
    )
    with pytest.raises(ValueError):
        authorize(
            context,
            json.dumps(data).encode(),
            raw,
            receipts(context),
            DIGEST,
            DIGEST,
            data["digest"],
            JOB,
            intent=intent,
        )


@pytest.mark.parametrize("compliant", [False, True])
@pytest.mark.parametrize("field", ["change_id", "description", "interface", "target"])
def test_valid_rehashed_result_disagrees_with_committed_intent(
    driver, context, offline, tmp_path, compliant, field
):
    intent, value = planned(compliant=compliant)
    if field == "target":
        _, value = planned(Profile.CAT8000V_IOSXE, compliant)
    else:
        altered = intent.model_dump()
        if field == "description":
            altered["desired"]["description"] = "changed"
        else:
            altered[field] = "CHG-OTHER" if field == "change_id" else "ge-0/0/2"
        other = InterfaceDescriptionIntent.model_validate(altered)
        # The real planner supplies valid evidence with its own canonical digest.
        _, device, interface, state = selected(Profile.VJUNOS_ROUTER, compliant)
        interface = interface.model_copy(update={"name": other.interface})
        state = observed(
            device,
            interface,
            description=other.desired.description if compliant else "old",
        )
        r = plan_profiled_change(
            other, FakeInventory(device, interface), FakeSecrets(), FakeCollector(state)
        )
        value = r.plan or r.compliance
    checkout = tmp_path / "checkout"
    committed(checkout, intent)
    driver.ROOT = checkout
    artifacts, metadata, _ = offline
    kind = "compliance" if compliant else "plan"
    raw = value.model_dump_json().encode()
    artifacts[
        (context.build_id, "profiled-live-plan", driver.artifact_name(context, kind))
    ] = raw
    metadata[(context.build_id, driver.PLANNING_METADATA)] = (
        driver.ProfiledPlanningPublication(
            build_id=context.build_id,
            commit=context.commit,
            artifact_kind=kind,
            artifact_digest=digest_bytes(raw),
            result_digest=value.digest,
        ).model_dump_json()
    )
    with pytest.raises(ValueError, match="intent and planning result"):
        driver.promotion_step(context, tmp_path)


@pytest.mark.parametrize("profile", [Profile.IOSV_159_3_M12, Profile.IOSVL2_2020])
def test_missing_explicit_operation_admission_has_no_promotion(
    driver, context, offline, tmp_path, monkeypatch, profile
):
    from network_change_delivery import profiled_planning

    monkeypatch.setattr(
        profiled_planning,
        "PROFILED_OPERATION_ADMISSIONS",
        {
            k: v
            for k, v in profiled_planning.PROFILED_OPERATION_ADMISSIONS.items()
            if k[0] is not profile
        },
    )
    device, interface = profiled_device(profile)
    intent = InterfaceDescriptionIntent(
        change_id="CHG-DENIED",
        kind="interface_description",
        target=device.logical_name,
        interface=interface.name,
        desired={"description": "denied"},
    )
    checkout = tmp_path / "checkout"
    committed(checkout, intent)
    driver.ROOT = checkout
    inventory = FakeInventory(device, interface)
    secrets = FakeSecrets()
    monkeypatch.setattr(driver, "NetBoxProfileInventoryProvider", lambda: inventory)
    monkeypatch.setattr(driver, "OpenBaoSecretProvider", lambda: secrets)
    with pytest.raises(ValueError):
        driver.plan_step(context, tmp_path)
    assert (
        inventory.interface_calls == secrets.reference_calls == secrets.load_calls == 0
    )
    assert offline[0] == {}


def test_historical_core_v2_bytes_keep_their_digest():
    path = ROOT / "tests/fixtures/intent-delivery/core-promotion-v2.json"
    raw = path.read_bytes()
    p = ProfiledPromotion.model_validate_json(raw)
    assert (
        p.digest
        == p.calculated_digest()
        == "sha256:4aac9415f7c4856985e957158718a72a743c9b507827fc0476116a544a4d7d54"
    )
    assert p.model_dump_json(indent=2).encode() + b"\n" == raw
    assert p.schema_version == "2" and p.target == "core-02"


def test_generic_modules_have_no_demo_dispatch():
    for file in [
        "src/network_change_delivery/profiled_promotion.py",
        "src/network_change_delivery/profiled_intent.py",
        "scripts/buildkite/profiled_delivery.py",
    ]:
        text = (ROOT / file).read_text()
        ast.parse(text)
        for literal in [
            "CHG-PROFILED-LAB-DEMO",
            "managed-by-ncdp-profiled-demo",
            "core-02",
            "edge-junos-01",
            "netbox:dcim.device:1",
            "GigabitEthernet2",
            "admit_demo_plan",
        ]:
            assert literal not in text


@pytest.mark.parametrize(
    "field", ["target", "interface", "description", "change_id", "kind"]
)
def test_deploy_independently_reloads_mutated_intent_before_any_command(
    driver, context, offline, tmp_path, monkeypatch, field
):
    from profiled_audit_fixtures import execution_artifacts, raw_bytes

    values = execution_artifacts()
    plan, promotion = (
        values[Kind.PROFILED_DEPLOYMENT_PLAN],
        values[Kind.PROFILED_PROMOTION],
    )
    original = historical_core_intent()
    admit_intent_result(original, plan)
    data = original.model_dump()
    if field == "description":
        data["desired"]["description"] = "changed after promotion"
    else:
        data[field] = {
            "target": "edge-junos-01",
            "interface": "GigabitEthernet3",
            "change_id": "CHG-AFTER",
            "kind": "unsupported",
        }[field]
    checkout = tmp_path / "checkout"
    path = committed(checkout, original)
    path.write_text(yaml.safe_dump(data))
    (checkout / ".buildkite").mkdir()
    (checkout / ".buildkite/pipeline.yml").write_bytes(
        (ROOT / ".buildkite/pipeline.yml").read_bytes()
    )
    monkeypatch.setattr(driver, "ROOT", checkout)
    artifacts, metadata, _ = offline
    for step, kind, value in [
        ("profiled-live-plan", "plan", plan),
        ("profiled-promotion", "promotion", promotion),
    ]:
        artifacts[(context.build_id, step, driver.artifact_name(context, kind))] = (
            raw_bytes(value)
        )
    metadata[(context.build_id, driver.PLANNING_METADATA)] = (
        driver.ProfiledPlanningPublication(
            build_id=context.build_id,
            commit=context.commit,
            artifact_kind="plan",
            artifact_digest=digest_bytes(raw_bytes(plan)),
            result_digest=plan.digest,
        ).model_dump_json()
    )
    for key, value in receipts(context).items():
        metadata[(context.build_id, "profiled-validation-" + key)] = value
    metadata[(context.build_id, driver.BATFISH_METADATA)] = DIGEST
    metadata[(context.build_id, driver.CML_METADATA)] = DIGEST
    metadata[(context.build_id, driver.PROMOTION_METADATA)] = promotion.digest
    monkeypatch.setenv("BUILDKITE_UNBLOCKER_ID", JOB)
    # offline fixture's command fails the test if invoked.
    assert driver.deploy_step(context, tmp_path) == 2
    assert not (
        Path(driver.os.environ["NCDP_AUDIT_STORE_ROOT"]) / "profiled-records"
    ).exists()


@pytest.mark.parametrize("profile", PROFILES)
def test_protected_interface_never_publishes_a_plan(
    driver, context, offline, tmp_path, monkeypatch, profile
):
    device, _ = profiled_device(profile)
    interface = device.protected_interfaces[0]
    intent = InterfaceDescriptionIntent(
        change_id="CHG-PROTECTED",
        kind="interface_description",
        target=device.logical_name,
        interface=interface.name,
        desired={"description": "denied"},
    )
    checkout = tmp_path / "checkout"
    committed(checkout, intent)
    monkeypatch.setattr(driver, "ROOT", checkout)
    monkeypatch.setattr(
        driver,
        "NetBoxProfileInventoryProvider",
        lambda: FakeInventory(device, interface),
    )
    with pytest.raises(ValueError):
        driver.plan_step(context, tmp_path)
    assert offline[0] == {}


def test_another_unblocker_cannot_select_another_target(context):
    intent, plan = planned()
    raw = plan.model_dump_json().encode()
    promotion = promote(context, raw, receipts(context), DIGEST, DIGEST, intent=intent)
    for unblocker in [JOB, "99999999-9999-4999-8999-999999999999"]:
        assert (
            authorize(
                context,
                promotion.model_dump_json().encode(),
                raw,
                receipts(context),
                DIGEST,
                DIGEST,
                promotion.digest,
                unblocker,
                intent=intent,
            )
            == plan
        )
