"""Offline protected rollout planning and promotion; execution is forbidden."""

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_profiled_buildkite_delivery import (
    BUILD,
    COMMIT,
    DIGEST,
    JOB,
    ROOT,
    environment,
    run_hook,
)
from test_profiled_buildkite_delivery import (
    driver as driver_fixture,
)
from test_profiled_planning import FakeSecrets, observed
from test_profiled_rollout import Inventory

from network_change_delivery import profiled_rollout as rollout
from network_change_delivery.openbao_profiled_deploy_config import (
    DEVICE_IDS,
    POLICY,
    POLICY_NAME,
    ROLE,
    ROLE_NAME,
    ProtectedRolloutCredentialAuthority,
)
from network_change_delivery.profiled_intent import load_committed_intent
from network_change_delivery.profiled_promotion import (
    VALIDATION_KEYS,
    ProfiledBuildContext,
    ProfiledPromotion,
    digest_bytes,
    validation_receipt,
)
from network_change_delivery.profiled_rollout_intent import (
    ACTIVE_ROLLOUT_INTENT_PATH,
    MAX_ROLLOUT_INTENT_BYTES,
    load_committed_rollout_intent,
)
from network_change_delivery.profiled_rollout_promotion import (
    PLAN_TYPES,
    ROLLOUT_PLANNING_METADATA,
    ROLLOUT_PROMOTION_BYTES_METADATA,
    ROLLOUT_PROMOTION_METADATA,
    RolloutPlanningPublication,
    promote_rollout,
    verify_rollout_promotion,
)

driver = driver_fixture


def forbidden(*_a, **_k):
    pytest.fail("rollout invoked a forbidden execution/evidence provider")


@pytest.fixture(autouse=True)
def no_execution(monkeypatch):
    from network_change_delivery import profiled_execution, profiled_write_adapter
    from network_change_delivery.audit_store import AuditStore
    from network_change_delivery.profiled_configuration_observation_store import (
        ProfiledConfigurationObservationStore,
    )

    monkeypatch.setattr(profiled_execution, "execute_profiled_plan", forbidden)
    for method in (
        "execute_cisco",
        "junos_transaction",
        "confirm_junos",
    ):
        monkeypatch.setattr(
            profiled_write_adapter.ProfiledWriteAdapter, method, forbidden
        )
    for method in ("persist_artifact", "persist_profiled_record"):
        monkeypatch.setattr(AuditStore, method, forbidden)
    monkeypatch.setattr(
        ProfiledConfigurationObservationStore,
        "persist_profiled_observation_record",
        forbidden,
    )


@pytest.fixture
def runtime(driver, monkeypatch):
    intent = load_committed_rollout_intent(ROOT)
    target = driver.ROOT / ACTIVE_ROLLOUT_INTENT_PATH
    target.write_text(intent.model_dump_json())
    inventory = Inventory()
    # Match current real reviewed Junos interface; historic fixture remains unchanged.
    device, interface = inventory.pairs["edge-junos-01"]
    inventory.pairs["edge-junos-01"] = (
        device,
        interface.model_copy(update={"name": "ge-0/0/1"}),
    )
    expanded = intent.expand(inventory.population.declaration)
    events, metadata, artifacts, annotations = [], {}, {}, []
    compliant = set()
    authority = ProtectedRolloutCredentialAuthority()
    secrets = FakeSecrets()
    original_load = secrets.load

    def load(device):
        assert events == [m.target for m in expanded]
        return original_load(device)

    secrets.load = load

    class Authority:
        def admit(self, identity):
            result = authority.admit(identity)
            events.append(
                next(
                    d.logical_name
                    for d in inventory.population.devices
                    if d.device_identity == identity
                )
            )
            return result

    class Collector:
        def __init__(self):
            self.calls = []
            self.fail = None

        def collect(self, target, credentials, interface_name):
            assert len(events) == 4
            assert credentials.username == "test-user"
            assert interface_name == inventory.pairs[target.logical_name][1].name
            self.calls.append(target.logical_name)
            if target.logical_name == self.fail:
                raise ValueError("read-only observation failed")
            device, interface = inventory.pairs[target.logical_name]
            desired = next(
                m.desired.description
                for m in expanded
                if m.target == target.logical_name
            )
            return observed(
                device,
                interface,
                description=desired if target.logical_name in compliant else "previous",
            )

    collector = Collector()
    monkeypatch.setattr(driver, "validate_profiled_live_host_trust", lambda: None)
    monkeypatch.setattr(driver, "NetBoxProfileInventoryProvider", lambda: inventory)
    monkeypatch.setattr(driver, "OpenBaoSecretProvider", lambda: secrets)
    monkeypatch.setattr(driver, "ProtectedRolloutCredentialAuthority", Authority)
    monkeypatch.setattr(driver, "ProfileReadOnlyAdapter", lambda **_k: collector)
    monkeypatch.setattr(driver, "command", forbidden)
    monkeypatch.setattr(driver, "capture_profiled_attempt", forbidden)
    monkeypatch.setattr(driver, "metadata", lambda _c, k: metadata[k])
    monkeypatch.setattr(
        driver, "publish_metadata", lambda _c, k, v: metadata.__setitem__(k, v)
    )
    monkeypatch.setattr(
        driver, "annotate", lambda _c, text, **_k: annotations.append(text)
    )
    monkeypatch.setattr(
        driver,
        "upload",
        lambda c, d, n: artifacts.__setitem__((c.step, n), (d / n).read_bytes()),
    )
    monkeypatch.setattr(
        driver, "download", lambda _c, _d, n, step: artifacts[(step, n)]
    )
    ctx = ProfiledBuildContext.from_environment(
        environment("profiled-rollout-live-plan")
    )
    receipts = {key: validation_receipt(BUILD, COMMIT, key) for key in VALIDATION_KEYS}
    metadata.update({"profiled-validation-" + k: v for k, v in receipts.items()})
    metadata.update({driver.BATFISH_METADATA: DIGEST, driver.CML_METADATA: DIGEST})
    return SimpleNamespace(**locals())


def published(runtime, driver, tmp_path):
    assert driver.rollout_plan_step(runtime.ctx, tmp_path) == 0
    receipt = RolloutPlanningPublication.model_validate_json(
        runtime.metadata[ROLLOUT_PLANNING_METADATA]
    )
    raw = runtime.artifacts[
        (
            runtime.ctx.step,
            driver.artifact_name(runtime.ctx, "rollout-" + receipt.artifact_kind),
        )
    ]
    return receipt, raw, receipt.read(runtime.ctx, raw, runtime.intent)


@pytest.mark.parametrize(
    "compliant",
    [(), ("core-02",), ("core-02", "edge-junos-01", "transit-ios-01", "access-sw-01")],
)
def test_real_planner_publication_and_promotion(runtime, driver, tmp_path, compliant):
    runtime.compliant.update(compliant)
    receipt, raw, parent = published(runtime, driver, tmp_path)
    assert parent.schema_version == "2" and len(parent.children) == 4
    assert parent.source_commit == COMMIT and receipt.artifact_digest == digest_bytes(
        raw
    )
    assert tuple(c.device.device_identity for c in parent.children) == tuple(
        f"netbox:dcim.device:{i}" for i in (1, 2, 8, 9)
    )
    assert runtime.secrets.load_calls == len(runtime.collector.calls) == 4
    for child in parent.children:
        assert child.artifact_digest == digest_bytes(child.artifact_bytes())
        assert child.result().schema_version == "2"
    ctx = replace(runtime.ctx, step="profiled-rollout-promotion")
    # Promotion must not use any device/credential/evidence provider.
    for name in (
        "validate_profiled_live_host_trust",
        "NetBoxProfileInventoryProvider",
        "OpenBaoSecretProvider",
        "ProfileReadOnlyAdapter",
        "ProtectedRolloutCredentialAuthority",
    ):
        setattr(driver, name, forbidden)
    assert driver.rollout_promotion_step(ctx, tmp_path) == 0
    if len(compliant) == 4:
        assert not isinstance(parent, PLAN_TYPES)
        assert len(runtime.artifacts) == 1
        assert ROLLOUT_PROMOTION_METADATA not in runtime.metadata
        assert "no promotion" in runtime.annotations[-1]
        with pytest.raises(ValueError):
            promote_rollout(
                ctx,
                raw,
                receipt,
                runtime.receipts,
                DIGEST,
                DIGEST,
                intent=runtime.intent,
            )
    else:
        name = driver.artifact_name(ctx, "rollout-promotion")
        promotion_raw = runtime.artifacts[(ctx.step, name)]
        promotion = verify_rollout_promotion(
            promotion_raw,
            ctx,
            raw,
            receipt,
            runtime.receipts,
            DIGEST,
            DIGEST,
            intent=runtime.intent,
        )
        assert promotion.schema_version == "1"
        assert promotion.digest == runtime.metadata[ROLLOUT_PROMOTION_METADATA]
        assert (
            digest_bytes(promotion_raw)
            == runtime.metadata[ROLLOUT_PROMOTION_BYTES_METADATA]
        )
        with pytest.raises(ValueError):
            ProfiledPromotion.model_validate_json(promotion_raw)
    assert "Frozen rollout facts shown" in runtime.annotations[-1]


@pytest.mark.parametrize(
    "failure",
    [
        "secret-authority",
        "protected",
        "interface",
        "observation",
        "source",
        "cml",
        "batfish",
        "validation",
    ],
)
def test_whole_rollout_failure_never_publishes(
    runtime, driver, tmp_path, monkeypatch, failure
):
    if failure == "secret-authority":

        class Denied:
            def admit(self, identity):
                if identity.endswith(":9"):
                    raise ValueError("denied")
                return runtime.authority.admit(identity)

        monkeypatch.setattr(driver, "ProtectedRolloutCredentialAuthority", Denied)
    elif failure in {"protected", "interface"}:
        device, interface = runtime.inventory.pairs["access-sw-01"]
        if failure == "protected":
            data = runtime.intent.model_dump(mode="json")
            data["selectors"][2]["interface"] = "GigabitEthernet0/0"
            (driver.ROOT / ACTIVE_ROLLOUT_INTENT_PATH).write_text(json.dumps(data))
            for name in ("transit-ios-01", "access-sw-01"):
                device, _ = runtime.inventory.pairs[name]
                runtime.inventory.pairs[name] = (device, device.protected_interfaces[0])
        else:
            interface = interface.model_copy(update={"device": "netbox:dcim.device:8"})
            runtime.inventory.pairs["access-sw-01"] = (device, interface)
    elif failure == "observation":
        runtime.collector.fail = "access-sw-01"
    elif failure == "source":
        planner = driver.plan_profiled_rollout
        monkeypatch.setattr(
            driver,
            "plan_profiled_rollout",
            lambda *a, **k: planner(*a, **(k | {"source_commit": "b" * 40})),
        )
    else:
        key = {
            "cml": driver.CML_METADATA,
            "batfish": driver.BATFISH_METADATA,
            "validation": "profiled-validation-quality-env",
        }[failure]
        runtime.metadata[key] = "invalid"
    with pytest.raises(ValueError):
        driver.rollout_plan_step(runtime.ctx, tmp_path)
    assert not runtime.artifacts and ROLLOUT_PLANNING_METADATA not in runtime.metadata
    if failure not in {"source", "observation"}:
        assert runtime.secrets.reference_calls == runtime.secrets.load_calls == 0
        assert not runtime.collector.calls


@pytest.mark.parametrize("key", VALIDATION_KEYS)
def test_every_same_build_receipt_required(runtime, driver, tmp_path, key):
    receipt, raw, _ = published(runtime, driver, tmp_path)
    del runtime.receipts[key]
    with pytest.raises(ValueError):
        promote_rollout(
            replace(runtime.ctx, step="profiled-rollout-promotion"),
            raw,
            receipt,
            runtime.receipts,
            DIGEST,
            DIGEST,
            intent=runtime.intent,
        )


@pytest.mark.parametrize(
    "damage",
    [
        "bytes",
        "build",
        "commit",
        "kind",
        "version",
        "digest",
        "intent",
        "batfish",
        "cml",
    ],
)
def test_promotion_rejects_detached_publication(runtime, driver, tmp_path, damage):
    receipt, raw, _ = published(runtime, driver, tmp_path)
    intent, batfish, cml = runtime.intent, DIGEST, DIGEST
    if damage == "bytes":
        raw += b" "
    elif damage == "intent":
        intent = intent.model_copy(update={"change_id": "CHG-CHANGED"})
    elif damage == "batfish":
        batfish = ""
    elif damage == "cml":
        cml = ""
    else:
        field, value = {
            "build": ("build_id", JOB),
            "commit": ("commit", "b" * 40),
            "kind": ("artifact_kind", "compliance"),
            "version": ("parent_schema_version", "1"),
            "digest": ("result_digest", DIGEST),
        }[damage]
        receipt = receipt.model_copy(update={field: value})
    with pytest.raises(ValueError):
        promote_rollout(
            replace(runtime.ctx, step="profiled-rollout-promotion"),
            raw,
            receipt,
            runtime.receipts,
            batfish,
            cml,
            intent=intent,
        )


@pytest.mark.parametrize(
    "damage",
    [
        "build_id",
        "source_commit",
        "parent_digest",
        "parent_artifact_digest",
        "validation_digest",
        "batfish_digest",
        "cml_digest",
        "child_bytes",
        "child_result",
        "order",
        "canaries",
        "waves",
    ],
)
def test_rehashed_promotion_cannot_detach_parent(runtime, driver, tmp_path, damage):
    receipt, raw, _ = published(runtime, driver, tmp_path)
    ctx = replace(runtime.ctx, step="profiled-rollout-promotion")
    args = (ctx, raw, receipt, runtime.receipts, DIGEST, DIGEST)
    promotion = promote_rollout(*args, intent=runtime.intent)
    data = promotion.model_dump(mode="json")
    if damage.startswith("child_"):
        data["children"][0][
            "artifact_digest" if damage == "child_bytes" else "result_digest"
        ] = DIGEST
    elif damage == "order":
        data["children"].reverse()
    elif damage == "canaries":
        data["canaries"].reverse()
    elif damage == "waves":
        data["waves"].reverse()
    else:
        data[damage] = (
            JOB
            if damage == "build_id"
            else "b" * 40
            if damage == "source_commit"
            else "sha256:" + "d" * 64
        )
    data["digest"] = digest_bytes(
        json.dumps(
            {k: v for k, v in data.items() if k != "digest"},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    )
    with pytest.raises(ValueError):
        verify_rollout_promotion(
            json.dumps(data).encode(), *args, intent=runtime.intent
        )


@pytest.mark.parametrize(
    "damage",
    [
        "missing",
        "empty",
        "directory",
        "symlink",
        "parent-link",
        "duplicate",
        "multi-doc",
        "unknown",
        "query",
        "size",
        "malformed",
    ],
)
def test_fixed_loader_rejects_unsafe_input(tmp_path, damage):
    path = tmp_path / ACTIVE_ROLLOUT_INTENT_PATH
    path.parent.mkdir(parents=True)
    raw = (ROOT / ACTIVE_ROLLOUT_INTENT_PATH).read_text()
    if damage == "missing":
        pass
    elif damage == "directory":
        path.mkdir()
    elif damage == "symlink":
        path.symlink_to(ROOT / ACTIVE_ROLLOUT_INTENT_PATH)
    elif damage == "parent-link":
        path.parent.rmdir()
        path.parent.symlink_to(ROOT / "deployments/live")
    else:
        raw = {
            "empty": "",
            "duplicate": raw + "\noperation: interface_description\n",
            "multi-doc": raw + "\n---\n{}",
            "unknown": raw + "\nextra: true",
            "query": raw + "\nquery: all",
            "size": " " * (MAX_ROLLOUT_INTENT_BYTES + 1),
            "malformed": "[",
        }[damage]
        path.write_text(raw)
    with pytest.raises(ValueError):
        load_committed_rollout_intent(tmp_path)


def test_static_authority_never_inherits_membership():
    assert DEVICE_IDS == (1, 2, 8, 9)
    assert POLICY.count('capabilities = ["read"]') == 4
    for device_id in DEVICE_IDS:
        identity = f"netbox:dcim.device:{device_id}"
        result = ProtectedRolloutCredentialAuthority().admit(identity)
        assert result.authority == ROLE_NAME and result.device_identity == identity
    for identity in (
        "netbox:dcim.device:10",
        "netbox:dcim.device:999999",
        "netbox:dcim.device:01",
    ):
        with pytest.raises(ValueError):
            ProtectedRolloutCredentialAuthority().admit(identity)
    assert all(
        word not in POLICY
        for word in ("*", "list", "update", "create", "delete", "auth/", "sys/")
    )
    assert ROLE["token_policies"] == [POLICY_NAME] and ROLE["token_no_default_policy"]
    assert (
        ROLE["token_num_uses"] == 1
        and ROLE["token_ttl"] == ROLE["token_max_ttl"] == 300
    )
    assert ROLE["secret_id_ttl"] == ROLE["secret_id_num_uses"] == 0


@pytest.mark.parametrize(
    "step,allowed",
    [
        ("profiled-rollout-live-plan", True),
        ("profiled-rollout-promotion", False),
        ("profiled-rollout-deploy", False),
        ("arbitrary", False),
    ],
)
def test_hook_exact_rollout_plan_only_without_audit(tmp_path, step, allowed):
    result, marker = run_hook(
        tmp_path, {"BUILDKITE_STEP_KEY": step}, audit_case="missing"
    )
    assert (result.returncode == 0) is allowed
    assert marker.exists() is (allowed or step == "profiled-rollout-deploy")


def test_single_target_intent_unchanged():
    value = load_committed_intent(ROOT)
    assert value.change_id == "CHG-NCDP-DEMO-20260909"
    assert value.desired.description == "ncdp-demo-reviewed-20260909"


@pytest.mark.parametrize("version", ["1", "2"])
@pytest.mark.parametrize("compliant", [False, True])
def test_publication_strict_version_readback(
    runtime, driver, tmp_path, version, compliant
):
    if compliant:
        runtime.compliant.update(runtime.inventory.pairs)
    if version == "1":
        original = runtime.intent
        explicit = rollout.ProfiledRolloutSelectionIntent(
            change_id=original.change_id,
            operation=original.operation,
            explicit_members=tuple(
                m.member_intent()
                for m in original.expand(runtime.inventory.population.declaration)
            ),
            policy=original.policy,
        )
        runtime.intent = explicit
        (driver.ROOT / ACTIVE_ROLLOUT_INTENT_PATH).write_text(
            explicit.model_dump_json()
        )
    receipt, raw, parent = published(runtime, driver, tmp_path)
    assert parent.schema_version == version
    assert receipt.read(runtime.ctx, raw, runtime.intent) == parent
    bad = receipt.model_copy(
        update={"parent_schema_version": "2" if version == "1" else "1"}
    )
    with pytest.raises(ValueError):
        bad.read(runtime.ctx, raw, runtime.intent)


@pytest.mark.parametrize(
    "change",
    [
        {"BUILDKITE_BRANCH": "feature"},
        {"BUILDKITE_PULL_REQUEST": "162"},
        {"BUILDKITE_RETRY_COUNT": "1"},
        {"BUILDKITE_COMMAND": "env"},
        {"NCDP_OPENBAO_SECRET_ID": "ambient"},
        {"BUILDKITE_REPO": "fork"},
        {"BUILDKITE_COMMIT": "b" * 40},
        {"BUILDKITE_AGENT_META_DATA_QUEUE": "ncdp-validation"},
    ],
)
def test_rollout_hook_rejects_before_private_env(tmp_path, change):
    result, marker = run_hook(
        tmp_path, {"BUILDKITE_STEP_KEY": "profiled-rollout-live-plan", **change}
    )
    assert result.returncode == 2 and not marker.exists()


def test_rollout_hook_dirty_checkout_fails_before_private_env(tmp_path, monkeypatch):
    original = Path.write_text

    def write(path, content, *a, **k):
        if path.name == "git":
            content += '\nif [ "$1" = diff ]; then exit 1; fi\n'
        return original(path, content, *a, **k)

    monkeypatch.setattr(Path, "write_text", write)
    result, marker = run_hook(
        tmp_path, {"BUILDKITE_STEP_KEY": "profiled-rollout-live-plan"}
    )
    assert result.returncode == 2 and not marker.exists()


@pytest.mark.parametrize("missing", ["cml", "batfish", *VALIDATION_KEYS])
def test_assurance_phase_fails_before_all_providers(
    runtime, driver, tmp_path, monkeypatch, missing
):
    key = {"cml": driver.CML_METADATA, "batfish": driver.BATFISH_METADATA}.get(
        missing, "profiled-validation-" + missing
    )
    runtime.metadata.pop(key)
    for name in (
        "validate_profiled_live_host_trust",
        "NetBoxProfileInventoryProvider",
        "OpenBaoSecretProvider",
        "ProfileReadOnlyAdapter",
    ):
        monkeypatch.setattr(driver, name, forbidden)
    with pytest.raises(driver.PlanPhaseError) as caught:
        driver.rollout_plan_step(runtime.ctx, tmp_path)
    assert caught.value.phase == "assurance prerequisites"
    assert driver.plan_failure(runtime.ctx, caught.value.phase) == 2
    assert (
        "Profiled live plan FAILED — phase: assurance prerequisites. No device write."
        in runtime.annotations[-1]
    )
    assert not runtime.inventory.calls and not runtime.collector.calls
    assert runtime.secrets.reference_calls == runtime.secrets.load_calls == 0


def test_positive_all_compliant_continuation_has_no_execution_admission(
    runtime, driver, tmp_path, monkeypatch
):
    runtime.compliant.update(runtime.inventory.pairs)
    published(runtime, driver, tmp_path)
    for name in (
        "authorize_rollout",
        "reserve_rollout_devices",
        "execute_rollout",
        "ProfiledRolloutAuditStore",
        "validate_profiled_live_host_trust",
        "OpenBaoSecretProvider",
        "NetBoxProfileInventoryProvider",
    ):
        monkeypatch.setattr(driver, name, forbidden)
    assert (
        driver.rollout_deploy_step(
            replace(runtime.ctx, step="profiled-rollout-deploy"), tmp_path
        )
        == 0
    )
    assert "zero write authority" in runtime.annotations[-1]


@pytest.mark.parametrize(
    "damage", ["unblocker", "promotion-bytes", "promotion-digest", "cml", "fields"]
)
def test_protected_rollout_caller_reconstructs_before_activity(
    runtime, driver, tmp_path, monkeypatch, damage
):
    published(runtime, driver, tmp_path)
    driver.rollout_promotion_step(
        replace(runtime.ctx, step="profiled-rollout-promotion"), tmp_path
    )
    monkeypatch.setenv("BUILDKITE_UNBLOCKER_ID", JOB)
    if damage == "unblocker":
        monkeypatch.delenv("BUILDKITE_UNBLOCKER_ID")
    elif damage == "promotion-bytes":
        runtime.metadata[ROLLOUT_PROMOTION_BYTES_METADATA] = "sha256:" + "0" * 64
    elif damage == "promotion-digest":
        runtime.metadata[ROLLOUT_PROMOTION_METADATA] = "sha256:" + "0" * 64
    elif damage == "cml":
        del runtime.metadata[driver.CML_METADATA]
    else:
        import yaml

        path = driver.ROOT / ".buildkite/pipeline.yml"
        graph = yaml.safe_load(path.read_text())
        graph["steps"][-1]["steps"][0]["fields"] = []
        path.write_text(yaml.safe_dump(graph))
    for name in (
        "execute_rollout",
        "ProfiledRolloutAuditStore",
        "validate_profiled_live_host_trust",
        "OpenBaoSecretProvider",
        "NetBoxProfileInventoryProvider",
    ):
        monkeypatch.setattr(driver, name, forbidden)
    assert (
        driver.rollout_deploy_step(
            replace(runtime.ctx, step="profiled-rollout-deploy"), tmp_path
        )
        != 0
    )


def test_deploy_annotation_preserves_authorization_truth(
    runtime, driver, tmp_path, monkeypatch
):
    """Render the protected caller's annotation after real offline authorization."""
    _, _, parent = published(runtime, driver, tmp_path)
    driver.rollout_promotion_step(
        replace(runtime.ctx, step="profiled-rollout-promotion"), tmp_path
    )
    monkeypatch.setenv("BUILDKITE_UNBLOCKER_ID", JOB)
    authorized = []
    original_authorize = driver.authorize_rollout

    def authorize(**inputs):
        result = original_authorize(**inputs)
        authorized.append(result)
        return result

    def stopped(**_inputs):
        assert len(authorized) == 1
        return SimpleNamespace(
            record_id=JOB,
            digest=DIGEST,
            build_id=BUILD,
            source_commit=COMMIT,
            outcome="STOPPED",
            authorization_digest=authorized[0].digest,
            preflight_digest=None,
            children=tuple(c.device for c in parent.children),
            attempted=(),
            successful=(),
            compliant=(),
            stopping_member=None,
            stopping_outcome=None,
            stopping_reason="PREFLIGHT",
            untouched=tuple(c.device.device_identity for c in parent.children),
            final_validation_status=None,
            child_evidence_complete=True,
            evidence_failed=False,
            child_records=(),
        )

    monkeypatch.setattr(driver, "authorize_rollout", authorize)
    monkeypatch.setattr(driver, "execute_rollout", stopped)
    monkeypatch.setattr(driver, "ProfiledRolloutAuditStore", lambda *_a, **_k: None)
    assert (
        driver.rollout_deploy_step(
            replace(runtime.ctx, step="profiled-rollout-deploy"), tmp_path
        )
        == 3
    )
    annotation = runtime.annotations[-1]
    assert "## Rollout execution" in annotation
    assert f"Authorization: `{authorized[0].digest}`" in annotation
    assert "Outcome: **STOPPED**" in annotation
    assert (
        "Frozen rollout facts shown; authority and execution state are reported "
        "by the current workflow step." in annotation
    )
    assert "no rollout authorization or execution exists" not in annotation
    assert "Planning/promotion only" not in annotation
