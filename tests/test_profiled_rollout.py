"""Offline complete rollout planning; providers expose no writer boundary."""

import ast
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from profiled_population_fixtures import declared_population
from test_profiled_planning import FakeSecrets, observed, profiled_device

from network_change_delivery import profiled_rollout as rollout
from network_change_delivery.architecture_contracts import AutomationProfileID
from network_change_delivery.profile_inventory import (
    PROFILED_MANAGED_POPULATION,
    ProfiledInventoryPopulation,
)

NOW = datetime(2026, 9, 9, tzinfo=UTC)
COMMIT = "a" * 40
PROFILES = tuple(
    member.automation_profile_id for member in PROFILED_MANAGED_POPULATION.members
)


def digest(raw):
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def rehash(model, values):
    values["digest"] = digest(
        json.dumps(
            {key: value for key, value in values.items() if key != "digest"},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    )
    return model.model_validate(values)


class Inventory:
    def __init__(self):
        pairs = [profiled_device(profile) for profile in PROFILES]
        self.population = ProfiledInventoryPopulation(
            devices=tuple(d for d, _ in pairs)
        )
        self.pairs = {
            device.logical_name: (device, interface) for device, interface in pairs
        }
        self.calls = []

    def resolve_profiled_population(self):
        self.calls.append("population")
        return self.population

    def resolve(self, name):
        self.calls.append(name)
        return self.pairs[name][0]

    def resolve_interface(self, device, name):
        self.calls.append(name)
        return self.pairs[device.logical_name][1]


class Authority:
    def __init__(self, permitted=(1, 2, 8, 9)):
        # Explicit test authority, deliberately separate from the real 1/2 role.
        self.permitted = permitted
        self.calls = []

    def admit(self, identity):
        self.calls.append(identity)
        device_id = int(identity.rsplit(":", 1)[1])
        if device_id not in self.permitted:
            raise ValueError("credential availability denied")
        return rollout.RolloutCredentialAdmission(
            authority="offline-reviewed-authority",
            device_identity=identity,
            credential_reference=f"openbao:kv-v2:ncdp/devices/{device_id}/ssh",
            permitted=True,
        )


class Collector:
    def __init__(self, inventory, compliant=()):
        self.inventory = inventory
        self.compliant = compliant
        self.calls = []
        self.fail = None

    def collect(self, target, credentials, interface):
        assert credentials.username == "test-user"
        self.calls.append(target.logical_name)
        if target.logical_name == self.fail:
            raise ValueError("observation unavailable")
        device, stable_interface = self.inventory.pairs[target.logical_name]
        assert interface == stable_interface.name
        return observed(
            device,
            stable_interface,
            description="NEW" if target.logical_name in self.compliant else "previous",
        )


def intent_for(inventory, names=None, **policy):
    return rollout.ProfiledRolloutIntent(
        change_id="CHG-ROLLOUT-OFFLINE-001",
        operation="interface_description",
        members=tuple(
            rollout.ProfiledRolloutMemberIntent(
                target=name,
                interface=inventory.pairs[name][1].name,
                desired={"description": "NEW"},
            )
            for name in (names if names is not None else inventory.pairs)
        ),
        policy=rollout.ProfiledRolloutPolicy(wave_size=1, **policy),
    )


@pytest.fixture
def context():
    inventory = Inventory()
    return SimpleNamespace(
        inventory=inventory,
        authority=Authority(),
        secrets=FakeSecrets(),
        collector=Collector(inventory),
    )


def plan(context, intent=None):
    return rollout.plan_profiled_rollout(
        intent or intent_for(context.inventory),
        context.inventory,
        context.authority,
        context.secrets,
        context.collector,
        source_commit=COMMIT,
        created_at=NOW,
    )


def test_all_four_current_children_and_family_cohorts(context):
    result = plan(context)
    assert isinstance(result, rollout.ProfiledRolloutPlan)
    assert result.canaries == ("netbox:dcim.device:1", "netbox:dcim.device:2")
    assert result.waves == (("netbox:dcim.device:8",), ("netbox:dcim.device:9",))
    assert context.inventory.calls[0] == "population"
    assert context.secrets.load_calls == len(context.authority.calls) == 4
    for child in result.children:
        original = child.artifact_bytes()
        assert child.artifact_digest == digest(original)
        assert child.result().schema_version == "2"
        assert child.result_digest == child.result().digest
    assert (
        rollout.ProfiledRolloutPlan.model_validate_json(result.model_dump_json())
        == result
    )
    assert plan(context) == result


@pytest.mark.parametrize(
    "names", [("core-02", "transit-ios-01"), ("transit-ios-01", "access-sw-01")]
)
def test_two_member_cisco_family_reuse(context, names):
    result = plan(context, intent_for(context.inventory, names))
    assert len(result.canaries) == len(result.waves) == 1
    assert all(
        child.operation_admission.transaction_strategy == "cisco_targeted_inverse"
        for child in result.children
    )


def test_mixed_and_all_compliant_are_positive(context):
    context.collector.compliant = ("core-02", "edge-junos-01")
    mixed = plan(context)
    assert [child.kind for child in mixed.children] == ["COMPLIANT"] * 2 + [
        "DEPLOYABLE"
    ] * 2
    assert mixed.canaries == ("netbox:dcim.device:8",)
    assert mixed.waves == (("netbox:dcim.device:9",),)
    context.collector.compliant = tuple(context.inventory.pairs)
    compliant = plan(context)
    assert isinstance(compliant, rollout.ProfiledRolloutCompliance)
    assert compliant.plan is None
    assert not compliant.promotion_minted
    assert not compliant.execution_attempted
    assert not compliant.recovery_attempted
    assert not compliant.chronology_required
    assert all(child.kind == "COMPLIANT" for child in compliant.children)
    assert compliant.digest != mixed.digest
    with pytest.raises(ValueError):
        rollout.ProfiledRolloutPlan.model_validate_json(compliant.model_dump_json())


def test_unselected_population_change_does_not_change_binding(context):
    intent = intent_for(context.inventory, ("core-02", "edge-junos-01"))
    before = plan(context, intent)
    larger = declared_population(5)[2].resolve_profiled_population()
    context.inventory.population = ProfiledInventoryPopulation(
        declaration=larger.declaration,
        devices=(*context.inventory.population.devices, larger.devices[-1]),
    )
    after = plan(context, intent)
    assert after.model_dump_json() == before.model_dump_json()
    assert after.digest == before.digest


@pytest.mark.parametrize(
    "mutation",
    [
        "empty",
        "duplicate",
        "selector",
        "query",
        "extra",
        "operation",
        "empty-interface",
        "duplicate-canary",
        "unknown-canary",
        "wave-zero",
        "wave-unbounded",
    ],
)
def test_intent_rejects_unreviewed_or_invalid_selection(context, mutation):
    data = intent_for(context.inventory).model_dump(mode="json")
    if mutation == "empty":
        data["members"] = []
    elif mutation == "duplicate":
        data["members"].append(data["members"][0])
    elif mutation == "operation":
        data["operation"] = "vlan"
    elif mutation == "empty-interface":
        data["members"][0]["interface"] = ""
    elif mutation == "duplicate-canary":
        data["policy"]["canaries"] = ["core-02", "core-02"]
    elif mutation == "unknown-canary":
        data["policy"]["canaries"] = ["unknown"]
    elif mutation.startswith("wave-"):
        data["policy"]["wave_size"] = 0 if mutation == "wave-zero" else 101
    else:
        data[mutation] = "arbitrary query"
    with pytest.raises(ValueError):
        rollout.ProfiledRolloutIntent.model_validate(data)


@pytest.mark.parametrize(
    "failure",
    [
        "unknown",
        "device-mismatch",
        "interface-device",
        "interface-name",
        "protected",
        "profile",
        "duplicate-device",
        "duplicate-interface",
        "authority",
        "wrong-authority",
        "no-operation",
    ],
)
def test_member_admission_blocks_whole_population_before_collection(
    context, monkeypatch, failure
):
    intent = intent_for(context.inventory)
    device, interface = context.inventory.pairs["access-sw-01"]
    if failure == "unknown":
        data = intent.model_dump()
        data["members"][-1]["target"] = "unknown"
        intent = rollout.ProfiledRolloutIntent.model_validate(data)
    elif failure in ("device-mismatch", "duplicate-device"):
        context.inventory.pairs["access-sw-01"] = context.inventory.pairs["core-02"]
    elif failure == "profile":
        context.inventory.pairs["access-sw-01"] = (
            device.model_copy(
                update={"automation_profile_id": AutomationProfileID.IOSV_159_3_M12}
            ),
            interface,
        )
    elif failure.startswith("interface-") or failure == "duplicate-interface":
        updates = (
            {"name": "wrong"}
            if failure == "interface-name"
            else {"device": "netbox:dcim.device:1"}
        )
        if failure == "duplicate-interface":
            updates = {"interface": "netbox:dcim.interface:2"}
        context.inventory.pairs["access-sw-01"] = (
            device,
            interface.model_copy(update=updates),
        )
    elif failure == "protected":
        protected = device.protected_interfaces[0]
        context.inventory.pairs["access-sw-01"] = device, protected
        data = intent.model_dump()
        data["members"][-1]["interface"] = protected.name
        intent = rollout.ProfiledRolloutIntent.model_validate(data)
    elif failure == "authority":
        context.authority = Authority((1, 2))
    elif failure == "wrong-authority":
        decision = context.authority.admit("netbox:dcim.device:1")
        monkeypatch.setattr(context.authority, "admit", lambda _: decision)
    else:
        from network_change_delivery import profiled_planning

        monkeypatch.setattr(profiled_planning, "PROFILED_OPERATION_ADMISSIONS", {})
    with pytest.raises(ValueError):
        plan(context, intent)
    assert context.collector.calls == []
    assert context.secrets.load_calls == context.secrets.reference_calls == 0


def test_failed_child_returns_no_partial_parent(context):
    context.collector.fail = "access-sw-01"
    with pytest.raises(ValueError, match="observation unavailable"):
        plan(context)
    assert len(context.collector.calls) == 4


@pytest.mark.parametrize("both", [False, True])
def test_ambiguous_planning_result_cannot_become_parent(context, monkeypatch, both):
    child = plan(context).children[0].result()
    monkeypatch.setattr(
        rollout,
        "plan_profiled_change",
        lambda *_args, **_kwargs: SimpleNamespace(
            plan=child if both else None, compliance=child if both else None
        ),
    )
    with pytest.raises(ValueError, match="exactly one"):
        plan(context)


@pytest.mark.parametrize(
    "mutation",
    [
        "byte",
        "malformed",
        "duplicate-json-key",
        "result-digest",
        "wrong-kind",
        "endpoint",
        "credential",
        "admission",
        "child-semantic",
        "extra",
    ],
)
def test_child_tampering_rejected(context, mutation):
    child = plan(context).children[0]
    data = child.model_dump(mode="json")
    if mutation == "byte":
        data["artifact_json"] += " "
    elif mutation in ("malformed", "duplicate-json-key", "child-semantic"):
        if mutation == "malformed":
            data["artifact_json"] = "{"
        elif mutation == "duplicate-json-key":
            data["artifact_json"] = data["artifact_json"].replace(
                '"schema_version": "2"', '"schema_version": "2", "schema_version": "2"'
            )
        else:
            value = json.loads(data["artifact_json"])
            value["change_id"] = "CHG-DIFFERENT"
            changed = rehash(type(child.result()), value)
            data["artifact_json"] = changed.model_dump_json()
            data["result_digest"] = changed.digest
        data["artifact_digest"] = digest(data["artifact_json"].encode())
    elif mutation == "result-digest":
        data["result_digest"] = "sha256:" + "b" * 64
    elif mutation == "wrong-kind":
        data["kind"] = "COMPLIANT"
    elif mutation == "endpoint":
        data["device"]["expected_hostname"] = "wrong"
    elif mutation == "credential":
        data["credential_admission"]["device_identity"] = "netbox:dcim.device:9"
    elif mutation == "admission":
        data["operation_admission"]["management_port"] = 23
    else:
        data["extra"] = "not allowed"
    if mutation == "child-semantic":
        parent = plan(context).model_dump(mode="json")
        parent["children"][0] = data
        with pytest.raises(ValueError, match="intent and planning result disagree"):
            rehash(rollout.ProfiledRolloutPlan, parent)
    else:
        with pytest.raises(ValueError):
            rollout.ProfiledRolloutChild.model_validate(data)


def test_exact_original_bytes_survive_readback_not_reserialization(context):
    parent = plan(context)
    data = parent.model_dump(mode="json")
    data["children"][0]["artifact_json"] += "\n "
    data["children"][0]["artifact_digest"] = digest(
        data["children"][0]["artifact_json"].encode()
    )
    with pytest.raises(ValueError, match="parent digest"):
        rollout.ProfiledRolloutPlan.model_validate(data)
    revised = rehash(rollout.ProfiledRolloutPlan, data)
    assert revised.children[0].result() == parent.children[0].result()
    assert revised.children[0].artifact_bytes().endswith(b"\n ")
    assert revised.digest != parent.digest
    assert revised.children[0].result_digest == parent.children[0].result_digest


@pytest.mark.parametrize(
    "mutation",
    [
        "omit",
        "duplicate",
        "missing-family",
        "wave-order",
        "canary-order",
        "compliant",
        "member-order",
        "extra",
    ],
)
def test_rehashed_parent_cannot_weaken_frozen_cohorts(context, mutation):
    if mutation == "compliant":
        context.collector.compliant = ("access-sw-01",)
    result = plan(context)
    data = result.model_dump(mode="json")
    if mutation == "omit":
        data["waves"] = data["waves"][:-1]
    elif mutation == "duplicate":
        data["waves"].append(data["waves"][0])
    elif mutation == "missing-family":
        data["canaries"] = data["canaries"][:1]
    elif mutation == "wave-order":
        data["waves"].reverse()
    elif mutation == "canary-order":
        data["canaries"].reverse()
    elif mutation == "compliant":
        data["waves"].append(["netbox:dcim.device:9"])
    elif mutation == "member-order":
        data["children"].reverse()
    else:
        data["selector"] = "all"
    with pytest.raises(ValueError):
        rehash(type(result), data)


def test_reviewed_order_and_explicit_canaries_are_material(context):
    original = plan(context)
    explicit = plan(
        context,
        intent_for(context.inventory, canaries=("transit-ios-01", "edge-junos-01")),
    )
    reordered = plan(
        context, intent_for(context.inventory, tuple(reversed(context.inventory.pairs)))
    )
    assert len({original.digest, explicit.digest, reordered.digest}) == 3
    assert explicit.canaries == ("netbox:dcim.device:8", "netbox:dcim.device:2")
    assert explicit.waves == (("netbox:dcim.device:1",), ("netbox:dcim.device:9",))


@pytest.mark.parametrize(
    "names",
    [("core-02",), ("core-02", "edge-junos-01", "transit-ios-01", "access-sw-01")],
)
def test_explicit_canaries_must_cover_families_and_leave_wave(context, names):
    with pytest.raises(ValueError, match=r"canaries|wave"):
        plan(context, intent_for(context.inventory, canaries=names))


def test_no_write_or_legacy_surface_and_protected_authority_unchanged():
    source = Path(rollout.__file__).read_text()
    tree = ast.parse(source)
    imports = [
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    ]
    assert not any(
        any(
            word in module
            for word in (
                "fleet",
                "execution",
                "write_adapter",
                "promotion",
                "locking",
                "audit_store",
                "buildkite",
            )
        )
        for module in imports
    )
    assert "def deploy" not in source
    assert "def promote" not in source
    from network_change_delivery.openbao_profiled_deploy_config import DEVICE_IDS

    assert DEVICE_IDS == (1, 2)


@pytest.fixture(autouse=True)
def forbid_execution(monkeypatch):
    from network_change_delivery import profiled_execution, profiled_write_adapter

    def forbidden(*_args, **_kwargs):
        pytest.fail("rollout planning invoked a writer/deployer")

    monkeypatch.setattr(profiled_execution, "execute_profiled_plan", forbidden)
    for method in ("execute_cisco", "junos_transaction", "confirm_junos"):
        monkeypatch.setattr(
            profiled_write_adapter.ProfiledWriteAdapter, method, forbidden
        )


@pytest.mark.parametrize(
    "field,value", [("source_commit", "invalid"), ("created_at", datetime(2026, 9, 9))]
)
def test_invalid_parent_inputs_rejected_before_any_provider(context, field, value):
    args = {"source_commit": COMMIT, "created_at": NOW, field: value}
    with pytest.raises(ValueError):
        rollout.plan_profiled_rollout(
            intent_for(context.inventory),
            context.inventory,
            context.authority,
            context.secrets,
            context.collector,
            **args,
        )
    assert not context.inventory.calls
    assert not context.authority.calls
    assert not context.collector.calls


@pytest.mark.parametrize(
    "failure",
    ["missing-interface", "secret-reference", "secret-load", "wrong-observation"],
)
def test_resolution_and_child_provider_failures_produce_no_parent(
    context, monkeypatch, failure
):
    def unavailable(*_args, **_kwargs):
        raise ValueError("provider unavailable")

    if failure == "missing-interface":
        monkeypatch.setattr(context.inventory, "resolve_interface", unavailable)
    elif failure == "secret-reference":
        context.secrets = FakeSecrets(source="environment")
    elif failure == "secret-load":
        monkeypatch.setattr(context.secrets, "load", unavailable)
    else:
        device, interface = context.inventory.pairs["core-02"]
        wrong = observed(device, interface).model_copy(
            update={"observed_hostname": "wrong"}
        )
        monkeypatch.setattr(context.collector, "collect", lambda *_args: wrong)
    with pytest.raises(ValueError):
        plan(context)


def test_missing_compliance_artifact_does_not_mean_compliant(context):
    context.collector.compliant = tuple(context.inventory.pairs)
    result = plan(context)
    data = result.model_dump(mode="json")
    data["children"].pop()
    with pytest.raises(ValueError, match="positively represent every"):
        rehash(rollout.ProfiledRolloutCompliance, data)


def test_cohort_type_changes_require_a_new_parent(context):
    deployable = plan(context)
    context.collector.compliant = ("access-sw-01",)
    mixed = plan(context)
    data = deployable.model_dump(mode="json")
    data["children"][-1] = mixed.children[-1].model_dump(mode="json")
    with pytest.raises(ValueError, match="parent digest"):
        rollout.ProfiledRolloutPlan.model_validate(data)
    with pytest.raises(ValueError, match="cohorts"):
        rehash(rollout.ProfiledRolloutPlan, data)


def test_compliant_explicit_canary_is_rejected(context):
    context.collector.compliant = ("core-02",)
    with pytest.raises(ValueError, match="canaries"):
        plan(
            context,
            intent_for(context.inventory, canaries=("core-02", "edge-junos-01")),
        )


def test_artifacts_and_nested_selection_are_immutable(context):
    result = plan(context)
    with pytest.raises(ValueError, match="frozen"):
        result.source_commit = "b" * 40
    with pytest.raises(ValueError, match="frozen"):
        result.intent.members[0].interface = "other"
    with pytest.raises(ValueError, match="frozen"):
        result.children[0].credential_admission.permitted = False


def test_positive_authority_is_mandatory():
    with pytest.raises(ValueError):
        rollout.RolloutCredentialAdmission(
            authority="offline-authority",
            device_identity="netbox:dcim.device:8",
            credential_reference="openbao:kv-v2:ncdp/devices/8/ssh",
            permitted=False,
        )
