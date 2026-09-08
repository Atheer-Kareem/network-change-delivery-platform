"""Composable reviewed selection, versioned byte truth; offline providers only."""

import hashlib
import json
from functools import partial

import pytest
from profiled_population_fixtures import declared_population
from test_profiled_rollout import Authority, intent_for, plan, rehash
from test_profiled_rollout import context as context
from test_profiled_rollout import forbid_execution as forbid_execution

from network_change_delivery import profiled_rollout as rollout
from network_change_delivery.architecture_contracts import (
    AutomationProfileID,
    NetworkOS,
    OperationalRole,
)
from network_change_delivery.profile_inventory import (
    PROFILED_MANAGED_POPULATION,
    ProfiledInventoryPopulation,
    ProfiledPopulationDeclaration,
)

IOS_NAMES = ("transit-ios-01", "access-sw-01")


def clause(selector=None, interface="GigabitEthernet0/1", description="NEW"):
    return rollout.ProfiledRolloutSelectorClause(
        selector=selector if selector is not None else {"network_oses": ["ios"]},
        interface=interface,
        desired={"description": description},
    )


def selected_intent(context, selector=None, *, explicit=(), clauses=None, **policy):
    return rollout.ProfiledRolloutSelectionIntent(
        change_id="CHG-ROLLOUT-OFFLINE-001",
        operation="interface_description",
        explicit_members=intent_for(context.inventory, explicit).members
        if explicit
        else (),
        selectors=(clause(selector),) if clauses is None else clauses,
        policy=rollout.ProfiledRolloutPolicy(wave_size=1, **policy),
    )


def assert_no_child_activity(context):
    assert context.secrets.reference_calls == context.secrets.load_calls == 0
    assert context.collector.calls == []
    # Every test also installs writer/deployer traps through forbid_execution.


@pytest.mark.parametrize(
    "compliant,parent_digest,byte_digest",
    [
        (
            False,
            "sha256:3c19e4d5139ca6e79b5b4cf5947e314724f1d62ef44406bbe91ea816807643da",
            "fdf2c91aaf967092f97caf772066864bb78e14fced82d02d61be011dd1b6a3ce",
        ),
        (
            True,
            "sha256:334c926f4888a03acb515e8381d33c4f72a9545bf4d6b1a0174bfd6c1d4787ac",
            "5bc59705818cfb36cf4b8e340f42eddfdcf966d5cac1e8aedc0c8a061ea8fc18",
        ),
    ],
)
def test_increment1_exact_v1_bytes_digest_and_dispatch(
    context, compliant, parent_digest, byte_digest
):
    # Golden hashes captured from merged Increment 1 (97e8749).
    names = ("core-02", "edge-junos-01")
    if compliant:
        context.collector.compliant = names
    original_intent = intent_for(context.inventory, names)
    result = plan(context, original_intent)
    raw = result.model_dump_json().encode()
    assert result.schema_version == "1"
    assert result.digest == parent_digest
    assert hashlib.sha256(raw).hexdigest() == byte_digest
    assert rollout.read_profiled_rollout(raw) == result
    assert type(rollout.read_profiled_rollout(raw)) is type(result)
    assert rollout.read_profiled_rollout(raw).model_dump_json().encode() == raw
    # New explicit-only source API still emits the exact old artifact.
    assert (
        plan(context, selected_intent(context, explicit=names, clauses=()))
        .model_dump_json()
        .encode()
        == raw
    )
    for field, value in (
        ("selector", None),
        ("selectors", []),
        ("explicit_members", []),
    ):
        with pytest.raises(ValueError, match="extra_forbidden"):
            rollout.ProfiledRolloutIntent.model_validate(
                {**original_intent.model_dump(), field: value}
            )


@pytest.mark.parametrize(
    "selector,names",
    [
        ({"operational_roles": ["core"]}, ("core-02",)),
        ({"network_oses": ["ios"]}, IOS_NAMES),
        ({"automation_profile_ids": ["iosv_159_3_m12"]}, ("transit-ios-01",)),
        ({"operational_roles": ["access", "transit"]}, IOS_NAMES),
        (
            {"network_oses": ["iosxe"], "operational_roles": ["core", "edge"]},
            ("core-02",),
        ),
        (
            {"network_oses": ["ios"], "operational_roles": ["transit", "access"]},
            IOS_NAMES,
        ),
        (
            {
                "automation_profile_ids": ["iosv_159_3_m12"],
                "operational_roles": ["transit", "access"],
            },
            ("transit-ios-01",),
        ),
    ],
)
def test_closed_or_and_and_filtered_alternatives(context, selector, names):
    interface = context.inventory.pairs[names[0]][1].name
    intent = selected_intent(context, clauses=(clause(selector, interface),))
    assert (
        tuple(
            m.logical_name
            for m in intent.selectors[0].selector.select(PROFILED_MANAGED_POPULATION)
        )
        == names
    )
    result = plan(context, intent)
    assert tuple(c.device.logical_name for c in result.children) == names
    assert tuple(e.target for e in result.expansion) == names
    assert result == plan(context, intent)
    assert rollout.read_profiled_rollout(result.model_dump_json().encode()) == result


def test_selector_fields_are_frozen_existing_enums():
    selector = rollout.ProfiledRolloutSelector(
        operational_roles=["transit"],
        network_oses=["ios"],
        automation_profile_ids=["iosv_159_3_m12"],
    )
    assert selector.operational_roles == (OperationalRole.TRANSIT,)
    assert selector.network_oses == (NetworkOS.IOS,)
    assert selector.automation_profile_ids == (AutomationProfileID.IOSV_159_3_M12,)
    with pytest.raises(ValueError, match="frozen"):
        selector.network_oses = (NetworkOS.JUNOS,)


def test_multiple_clauses_supply_distinct_exact_payloads(context):
    intent = selected_intent(
        context,
        clauses=(
            clause({"network_oses": ["junos"]}, "ge-0/0/0", "JUNOS-REVIEWED"),
            clause(description="IOS-REVIEWED"),
        ),
    )
    result = plan(context, intent)
    assert tuple(e.target for e in result.expansion) == ("edge-junos-01", *IOS_NAMES)
    assert [e.source_index for e in result.expansion] == [0, 1, 1]
    assert [c.result().desired_description for c in result.children] == [
        "JUNOS-REVIEWED",
        "IOS-REVIEWED",
        "IOS-REVIEWED",
    ]
    assert [c.interface.name for c in result.children] == [
        "ge-0/0/0",
        "GigabitEthernet0/1",
        "GigabitEthernet0/1",
    ]
    assert result.canaries == ("netbox:dcim.device:2", "netbox:dcim.device:8")
    assert result.waves == (("netbox:dcim.device:9",),)


def test_explicit_first_reviewed_order_then_clauses_and_git_order(context):
    intent = selected_intent(context, explicit=("edge-junos-01", "core-02"))
    result = plan(context, intent)
    assert tuple(e.target for e in result.expansion) == (
        "edge-junos-01",
        "core-02",
        *IOS_NAMES,
    )
    assert [(e.source_kind, e.source_index) for e in result.expansion] == [
        ("explicit", 0),
        ("explicit", 1),
        ("selector", 0),
        ("selector", 0),
    ]
    assert rollout.read_profiled_rollout(result.model_dump_json().encode()) == result


def test_canaries_can_reference_expanded_members(context):
    result = plan(
        context,
        selected_intent(
            context,
            explicit=("core-02", "edge-junos-01"),
            canaries=("transit-ios-01", "edge-junos-01"),
        ),
    )
    assert result.canaries == ("netbox:dcim.device:8", "netbox:dcim.device:2")
    assert result.waves == (("netbox:dcim.device:1",), ("netbox:dcim.device:9",))


@pytest.mark.parametrize("compliant", [(), ("transit-ios-01",), IOS_NAMES])
def test_v2_deployable_mixed_compliant_exact_dispatch(context, compliant):
    context.collector.compliant = compliant
    result = plan(context, selected_intent(context))
    assert result.schema_version == "2"
    assert [c.kind for c in result.children] == [
        "COMPLIANT" if n in compliant else "DEPLOYABLE" for n in IOS_NAMES
    ]
    expected = (
        rollout.ProfiledRolloutComplianceV2
        if compliant == IOS_NAMES
        else rollout.ProfiledRolloutPlanV2
    )
    assert type(result) is expected
    assert (
        type(rollout.read_profiled_rollout(result.model_dump_json().encode()))
        is expected
    )
    explicit = plan(context, intent_for(context.inventory, IOS_NAMES))
    assert explicit.children == result.children
    if compliant == IOS_NAMES:
        assert result.plan is None
        assert not any(
            (
                result.promotion_minted,
                result.execution_attempted,
                result.recovery_attempted,
                result.chronology_required,
            )
        )
    else:
        assert (result.canaries, result.waves) == (explicit.canaries, explicit.waves)
    v1_model = (
        rollout.ProfiledRolloutCompliance
        if compliant == IOS_NAMES
        else rollout.ProfiledRolloutPlan
    )
    with pytest.raises(ValueError):
        v1_model.model_validate_json(result.model_dump_json())
    data = result.model_dump(mode="json")
    data["schema_version"] = "1"
    with pytest.raises(ValueError):
        rollout.read_profiled_rollout(json.dumps(data).encode())


def test_same_members_different_instructions_change_digest(context):
    results = [
        plan(context, selected_intent(context, selector))
        for selector in (
            {"network_oses": ["ios"]},
            {"operational_roles": ["transit", "access"]},
            {"operational_roles": ["access", "transit"]},
        )
    ]
    results.append(plan(context, intent_for(context.inventory, IOS_NAMES)))
    assert len({r.digest for r in results}) == 4
    assert all(r.children == results[0].children for r in results)


@pytest.mark.parametrize(
    "failure",
    [
        "none",
        "explicit-duplicate",
        "explicit-selector",
        "selector-selector",
        "zero-match",
    ],
)
def test_selection_errors_precede_all_member_and_credential_activity(context, failure):
    with pytest.raises(ValueError):
        if failure == "none":
            intent = selected_intent(context, clauses=())
        elif failure == "explicit-duplicate":
            intent = selected_intent(context).model_dump()
            member = intent_for(context.inventory, IOS_NAMES).members[0].model_dump()
            intent["explicit_members"] = [member, member]
            intent = rollout.ProfiledRolloutSelectionIntent.model_validate(intent)
        elif failure == "explicit-selector":
            intent = selected_intent(context, explicit=(IOS_NAMES[0],))
        elif failure == "selector-selector":
            intent = selected_intent(context, clauses=(clause(), clause()))
        else:
            intent = selected_intent(
                context, {"network_oses": ["ios"], "operational_roles": ["core"]}
            )
        plan(context, intent)
    assert context.inventory.calls in ([], ["population"])
    assert not context.authority.calls
    assert_no_child_activity(context)


@pytest.mark.parametrize("field", ["interface", "desired", "selector"])
def test_clause_requires_reviewed_payload(context, field):
    data = clause().model_dump()
    data.pop(field)
    with pytest.raises(ValueError):
        rollout.ProfiledRolloutSelectorClause.model_validate(data)
    assert_no_child_activity(context)


@pytest.mark.parametrize(
    "failure",
    [
        "malformed-population",
        "identity",
        "credential",
        "operation",
        "protected",
        "missing-interface",
        "child",
    ],
)
def test_expansion_preserves_whole_population_admission(context, monkeypatch, failure):
    intent = selected_intent(context)
    if failure == "malformed-population":
        p = context.inventory.population
        context.inventory.population = p.model_copy(update={"devices": p.devices[:-1]})
    elif failure == "identity":
        context.inventory.pairs[IOS_NAMES[0]] = context.inventory.pairs["core-02"]
    elif failure == "credential":
        context.authority = Authority(
            (1, 2, 8)
        )  # last member denies ALL child activity
    elif failure == "operation":
        from network_change_delivery import profiled_planning

        monkeypatch.setattr(profiled_planning, "PROFILED_OPERATION_ADMISSIONS", {})
    elif failure == "protected":
        device, _ = context.inventory.pairs[IOS_NAMES[0]]
        context.inventory.pairs[IOS_NAMES[0]] = device, device.protected_interfaces[0]
        intent = selected_intent(
            context, clauses=(clause(interface="GigabitEthernet0/0"),)
        )
    elif failure == "missing-interface":
        original = context.inventory.resolve_interface

        def missing_interface(device, name):
            if device.logical_name == IOS_NAMES[-1]:
                raise ValueError("selected interface does not exist")
            return original(device, name)

        monkeypatch.setattr(context.inventory, "resolve_interface", missing_interface)
    else:
        context.collector.fail = IOS_NAMES[-1]
    with pytest.raises(ValueError):
        plan(context, intent)
    if failure != "child":
        assert_no_child_activity(context)
    else:
        assert context.collector.calls == list(IOS_NAMES)


@pytest.mark.parametrize(
    "mutation",
    [
        "source-kind",
        "source-index",
        "target",
        "interface",
        "desired",
        "order",
        "payload",
        "missing-child",
        "population-extra",
    ],
)
def test_rehashed_v2_provenance_payload_and_membership_tampering(context, mutation):
    result = plan(context, selected_intent(context))
    data = result.model_dump(mode="json")
    if mutation == "source-kind":
        data["expansion"][0]["source_kind"] = "explicit"
    elif mutation == "source-index":
        data["expansion"][0]["source_index"] = 1
    elif mutation == "target":
        data["expansion"][0]["target"] = "core-02"
    elif mutation == "interface":
        data["expansion"][0]["interface"] = "GigabitEthernet0/2"
    elif mutation == "desired":
        data["expansion"][0]["desired"]["description"] = "OTHER"
    elif mutation == "order":
        data["expansion"].reverse()
    elif mutation == "payload":
        data["intent"]["selectors"][0]["desired"]["description"] = "OTHER"
    elif mutation == "missing-child":
        data["children"].pop()
    else:
        data["selected_population"]["members"].append(
            PROFILED_MANAGED_POPULATION.members[0].model_dump(mode="json")
        )
    with pytest.raises(ValueError):
        rehash(type(result), data)


@pytest.mark.parametrize(
    "raw",
    [
        b"null",
        b"[]",
        b"{",
        b"{}",
        b'{"schema_version":"3","result_type":"profiled_rollout_plan"}',
        b'{"schema_version":2,"result_type":"profiled_rollout_plan"}',
        b'{"schema_version":"1","schema_version":"2"}',
    ],
)
def test_version_dispatch_fails_closed(raw):
    with pytest.raises(ValueError):
        rollout.read_profiled_rollout(raw)


def test_declaration_order_is_not_alphabetical(context):
    p = context.inventory.population
    context.inventory.population = ProfiledInventoryPopulation(
        declaration=ProfiledPopulationDeclaration(
            members=tuple(reversed(p.declaration.members))
        ),
        devices=tuple(reversed(p.devices)),
    )
    result = plan(context, selected_intent(context))
    assert tuple(e.target for e in result.expansion) == tuple(reversed(IOS_NAMES))
    assert result.canaries == ("netbox:dcim.device:9",)
    assert result.waves == (("netbox:dcim.device:8",),)


@pytest.mark.parametrize("matching", [False, True])
def test_git_population_growth_requires_new_parent_only_when_matching(
    context, monkeypatch, matching
):
    from network_change_delivery import profiled_planning

    intent = selected_intent(context)
    before = plan(context, intent)
    larger = declared_population(5, repeated_profile_index=2 if matching else 0)[
        2
    ].resolve_profiled_population()
    future = larger.devices[-1]
    context.inventory.population = ProfiledInventoryPopulation(
        declaration=larger.declaration,
        devices=(*context.inventory.population.devices, future),
    )
    if matching:
        # Simulate a reviewed future Git declaration through the unchanged exact
        # child validators; never weaken profile admission or infer credentials.
        monkeypatch.setattr(
            profiled_planning,
            "admit_profiled_subject",
            partial(
                profiled_planning.admit_profiled_subject, declaration=larger.declaration
            ),
        )
        monkeypatch.setattr(
            rollout,
            "_admit_profiled_device",
            partial(rollout._admit_profiled_device, declaration=larger.declaration),
        )
        original_interface = context.inventory.pairs[IOS_NAMES[0]][1]
        future_interface = original_interface.model_copy(
            update={
                "device": future.device_identity,
                "interface": "netbox:dcim.interface:9914",
            }
        )
        context.inventory.pairs[future.logical_name] = future, future_interface
        context.authority = Authority((1, 2, 8, 9, 14))
    after = plan(context, intent)
    if matching:
        assert len(after.children) == 3
        assert after.expansion[-1].target == future.logical_name
        assert after.expansion[-1].interface == "GigabitEthernet0/1"
        assert after.expansion[-1].desired.description == "NEW"
        assert after.digest != before.digest
        assert rollout.read_profiled_rollout(after.model_dump_json().encode()) == after
    else:
        assert after.model_dump_json() == before.model_dump_json()


def test_netbox_only_device_cannot_create_membership(context):
    before = plan(context, selected_intent(context))
    larger = declared_population(5, repeated_profile_index=2)[
        2
    ].resolve_profiled_population()
    context.inventory.pairs[larger.devices[-1].logical_name] = (
        larger.devices[-1],
        context.inventory.pairs[IOS_NAMES[0]][1],
    )
    assert plan(context, selected_intent(context)) == before
    p = context.inventory.population
    context.inventory.population = p.model_copy(
        update={"devices": (*p.devices, larger.devices[-1])}
    )
    context.secrets.reference_calls = context.secrets.load_calls = 0
    context.collector.calls.clear()
    with pytest.raises(ValueError):
        plan(context, selected_intent(context))
    assert_no_child_activity(context)


def test_protected_credential_scope_unchanged():
    from network_change_delivery.openbao_profiled_deploy_config import DEVICE_IDS

    assert DEVICE_IDS == (1, 2)


@pytest.mark.parametrize(
    "selector",
    [
        {},
        {"network_oses": None},
        {"operational_roles": []},
        {"network_oses": []},
        {"automation_profile_ids": []},
        {"operational_roles": ["transit", "transit"]},
        {"network_oses": ["ios", "ios"]},
        {"automation_profile_ids": ["iosvl2_2020", "iosvl2_2020"]},
        {"operational_roles": ["unknown"]},
        {"network_oses": ["linux"]},
        {"automation_profile_ids": ["all-cisco"]},
        {"network_oses": "ios"},
        {"network_oses": ["ios"], "query": "all"},
        {"regex": "ios.*"},
        {"glob": "*"},
        {"expression": "device.role == core"},
        {"netbox_filters": {"tag": "managed"}},
        {"platform_slug": "cisco-ios"},
        {"device_type_slug": "iosvl2-2020"},
        {"network_oses": ["ios"], "match_mode": "ANY"},
        {"NOT": {"network_oses": ["junos"]}},
        {"network_oses": ["${NCDP_NETWORK_OS}"]},
    ],
)
def test_invalid_selector_rejected_before_any_provider(context, selector):
    with pytest.raises(ValueError):
        selected_intent(context, selector)
    assert not context.inventory.calls
    assert not context.authority.calls
    assert_no_child_activity(context)


def test_selector_default_path_preserves_child_timestamp_ownership(
    context, monkeypatch
):
    from test_profiled_rollout import COMMIT

    context.collector.compliant = IOS_NAMES
    original = rollout.plan_profiled_change
    observations = []

    def child(*args, **kwargs):
        assert kwargs["created_at"] is None
        result = original(*args, **kwargs)
        assert len(context.collector.calls) == len(observations) + 1
        observations.append(result.compliance.observed_at)
        return result

    monkeypatch.setattr(rollout, "plan_profiled_change", child)
    result = rollout.plan_profiled_rollout(
        selected_intent(context),
        context.inventory,
        context.authority,
        context.secrets,
        context.collector,
        source_commit=COMMIT,
    )
    assert [child.result().observed_at for child in result.children] == observations
    assert len(observations) == 2
    assert observations[0] < observations[1]
