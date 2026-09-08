"""Closed selector WHO agrees exactly with reviewed WHAT; no runtime providers."""

import hashlib

import pytest
from profiled_population_fixtures import declared_population
from test_profiled_rollout import (
    Authority,
    intent_for,
    plan,
    rehash,
)
from test_profiled_rollout import (
    context as context,
)
from test_profiled_rollout import (
    forbid_execution as forbid_execution,
)

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


def selected_intent(context, selector=None, names=IOS_NAMES):
    values = intent_for(context.inventory, names).model_dump()
    values["selector"] = selector if selector is not None else {"network_oses": ["ios"]}
    return rollout.ProfiledRolloutIntent.model_validate(values)


def assert_no_child_activity(context):
    assert context.secrets.reference_calls == context.secrets.load_calls == 0
    assert context.collector.calls == []
    # Writer/deployer methods are traps in every test through forbid_execution.


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
def test_increment1_explicit_artifact_bytes_and_digests_unchanged(
    context, compliant, parent_digest, byte_digest
):
    # Captured by running merged 97e8749 before introducing the selector field.
    names = ("core-02", "edge-junos-01")
    if compliant:
        context.collector.compliant = names
    intent = intent_for(context.inventory, names)
    explicit_none = rollout.ProfiledRolloutIntent.model_validate(
        {**intent.model_dump(), "selector": None}
    )
    assert explicit_none == intent
    assert "selector" not in intent.model_dump()
    result = plan(context, intent)
    original_bytes = result.model_dump_json().encode()
    assert result.digest == parent_digest
    assert hashlib.sha256(original_bytes).hexdigest() == byte_digest
    assert type(result).model_validate_json(original_bytes) == result
    assert plan(context, explicit_none).model_dump_json().encode() == original_bytes


@pytest.mark.parametrize(
    "selector,names",
    [
        ({"operational_roles": ["core"]}, ("core-02",)),
        ({"network_oses": ["ios"]}, IOS_NAMES),
        ({"automation_profile_ids": ["iosv_159_3_m12"]}, ("transit-ios-01",)),
        ({"operational_roles": ["access", "transit"]}, IOS_NAMES),
        ({"network_oses": ["junos", "iosxe"]}, ("core-02", "edge-junos-01")),
        (
            {"automation_profile_ids": ["iosv_159_3_m12", "cat8000v_iosxe"]},
            ("core-02", "transit-ios-01"),
        ),
        (
            {"network_oses": ["ios"], "operational_roles": ["transit", "access"]},
            IOS_NAMES,
        ),
        (
            {
                "network_oses": ["ios"],
                "operational_roles": ["access", "transit"],
                "automation_profile_ids": ["iosvl2_2020", "iosv_159_3_m12"],
            },
            IOS_NAMES,
        ),
    ],
)
def test_closed_dimensions_fixed_or_and_declaration_order(context, selector, names):
    intent = selected_intent(context, selector, names)
    assert (
        tuple(
            m.logical_name for m in intent.selector.select(PROFILED_MANAGED_POPULATION)
        )
        == names
    )
    result = plan(context, intent)
    assert tuple(c.device.logical_name for c in result.children) == names
    assert result.intent.selector == intent.selector
    assert "selector" in result.model_dump()["intent"]
    assert result == plan(context, intent)
    assert type(result).model_validate_json(result.model_dump_json()) == result


def test_selector_fields_use_existing_closed_enums():
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


@pytest.mark.parametrize("compliant", [(), ("transit-ios-01",), IOS_NAMES])
def test_selector_preserves_deployable_mixed_and_positive_compliance(
    context, compliant
):
    context.collector.compliant = compliant
    intent = selected_intent(context)
    result = plan(context, intent)
    assert [child.kind for child in result.children] == [
        "COMPLIANT" if name in compliant else "DEPLOYABLE" for name in IOS_NAMES
    ]
    if compliant == IOS_NAMES:
        assert isinstance(result, rollout.ProfiledRolloutCompliance)
        assert result.plan is None
        assert not result.promotion_minted
        assert not result.execution_attempted
        assert not result.recovery_attempted
        assert not result.chronology_required
    else:
        assert isinstance(result, rollout.ProfiledRolloutPlan)
        explicit = plan(context, intent_for(context.inventory, IOS_NAMES))
        assert (result.canaries, result.waves) == (explicit.canaries, explicit.waves)
        assert result.children == explicit.children


def test_same_current_members_different_reviewed_selection_rules_change_digest(context):
    rules = [
        None,
        {"network_oses": ["ios"]},
        {"operational_roles": ["transit", "access"]},
        {"automation_profile_ids": ["iosv_159_3_m12", "iosvl2_2020"]},
        {"network_oses": ["ios"], "operational_roles": ["transit", "access"]},
        {"operational_roles": ["access", "transit"]},
    ]
    results = [
        plan(
            context,
            selected_intent(context, rule)
            if rule is not None
            else intent_for(context.inventory, IOS_NAMES),
        )
        for rule in rules
    ]
    assert len({result.digest for result in results}) == len(rules)
    assert all(result.children == results[0].children for result in results)
    assert all(
        (result.canaries, result.waves) == (results[0].canaries, results[0].waves)
        for result in results
    )
    changed = results[1].model_dump(mode="json")
    changed["intent"]["selector"] = rollout.ProfiledRolloutSelector.model_validate(
        rules[2]
    ).model_dump(mode="json")
    with pytest.raises(ValueError, match="parent digest"):
        rollout.ProfiledRolloutPlan.model_validate(changed)
    assert rehash(rollout.ProfiledRolloutPlan, changed).digest == results[2].digest


@pytest.mark.parametrize("matching", [False, True])
def test_population_growth_never_invents_reviewed_payload(context, matching):
    intent = selected_intent(context)
    before = plan(context, intent)
    larger = declared_population(5, repeated_profile_index=2 if matching else 0)[
        2
    ].resolve_profiled_population()
    context.inventory.population = ProfiledInventoryPopulation(
        declaration=larger.declaration,
        devices=(*context.inventory.population.devices, larger.devices[-1]),
    )
    context.inventory.calls.clear()
    context.authority.calls.clear()
    context.secrets.reference_calls = context.secrets.load_calls = 0
    context.collector.calls.clear()
    if matching:
        with pytest.raises(ValueError, match="selector and reviewed member sequence"):
            plan(context, intent)
        assert context.inventory.calls == ["population"]
        assert not context.authority.calls
        assert_no_child_activity(context)
    else:
        after = plan(context, intent)
        assert after.digest == before.digest
        assert after.model_dump_json() == before.model_dump_json()


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


@pytest.mark.parametrize(
    "selector",
    [
        {"network_oses": ["ios"], "operational_roles": ["core"]},
        {
            "operational_roles": ["transit", "access"],
            "automation_profile_ids": ["iosv_159_3_m12"],
        },
        {"network_oses": ["ios", "iosxe"], "operational_roles": ["transit"]},
        {
            "automation_profile_ids": ["iosv_159_3_m12", "iosvl2_2020"],
            "operational_roles": ["transit"],
        },
    ],
)
def test_contradictions_and_nonparticipating_values_rejected(context, selector):
    with pytest.raises(ValueError, match=r"matches no|nonparticipating"):
        plan(context, selected_intent(context, selector))
    assert context.inventory.calls == ["population"]
    assert not context.authority.calls
    assert_no_child_activity(context)


def test_stale_profile_value_absent_from_declared_population(context):
    current = context.inventory.population
    context.inventory.population = ProfiledInventoryPopulation(
        declaration=ProfiledPopulationDeclaration(
            members=current.declaration.members[:2]
        ),
        devices=current.devices[:2],
    )
    with pytest.raises(ValueError, match="matches no"):
        plan(
            context,
            selected_intent(context, {"automation_profile_ids": ["iosv_159_3_m12"]}),
        )
    assert context.inventory.calls == ["population"]
    assert not context.authority.calls
    assert_no_child_activity(context)


@pytest.mark.parametrize(
    "names", [("transit-ios-01",), ("core-02", *IOS_NAMES), tuple(reversed(IOS_NAMES))]
)
def test_selector_payload_missing_extra_or_wrong_order_fails_before_members(
    context, names
):
    with pytest.raises(ValueError, match="selector and reviewed member sequence"):
        plan(context, selected_intent(context, names=names))
    assert context.inventory.calls == ["population"]
    assert not context.authority.calls
    assert_no_child_activity(context)


def test_selector_cannot_create_operation_payloads(context):
    data = selected_intent(context).model_dump()
    for field in ("members",):
        missing = {key: value for key, value in data.items() if key != field}
        with pytest.raises(ValueError):
            rollout.ProfiledRolloutIntent.model_validate(missing)
    for field in ("interface", "desired"):
        data = selected_intent(context).model_dump()
        data["members"][0].pop(field)
        with pytest.raises(ValueError):
            rollout.ProfiledRolloutIntent.model_validate(data)
    assert_no_child_activity(context)


@pytest.mark.parametrize(
    "failure",
    [
        "malformed-population",
        "identity",
        "credential",
        "operation",
        "protected",
        "child",
    ],
)
def test_selector_does_not_bypass_existing_admission(context, monkeypatch, failure):
    intent = selected_intent(context)
    if failure == "malformed-population":
        population = context.inventory.population
        context.inventory.population = population.model_copy(
            update={"devices": population.devices[:-1]}
        )
    elif failure == "identity":
        context.inventory.pairs[IOS_NAMES[0]] = context.inventory.pairs["core-02"]
    elif failure == "credential":
        context.authority = Authority((1, 2))
    elif failure == "operation":
        from network_change_delivery import profiled_planning

        monkeypatch.setattr(profiled_planning, "PROFILED_OPERATION_ADMISSIONS", {})
    elif failure == "protected":
        device, _ = context.inventory.pairs[IOS_NAMES[0]]
        context.inventory.pairs[IOS_NAMES[0]] = device, device.protected_interfaces[0]
        intent = selected_intent(context)
    else:
        context.collector.fail = IOS_NAMES[-1]
    with pytest.raises(ValueError):
        plan(context, intent)
    if failure != "child":
        assert_no_child_activity(context)
    else:
        assert context.collector.calls == list(IOS_NAMES)


def test_rehashed_selector_contradicting_frozen_children_rejected(context):
    result = plan(context, selected_intent(context))
    data = result.model_dump(mode="json")
    data["intent"]["selector"] = rollout.ProfiledRolloutSelector(
        network_oses=["junos"]
    ).model_dump(mode="json")
    with pytest.raises(ValueError, match="matches no"):
        rehash(rollout.ProfiledRolloutPlan, data)


def test_selector_all_compliant_cannot_hide_missing_artifact(context):
    context.collector.compliant = IOS_NAMES
    result = plan(context, selected_intent(context))
    data = result.model_dump(mode="json")
    data["children"].pop()
    with pytest.raises(ValueError, match="positively represent every"):
        rehash(rollout.ProfiledRolloutCompliance, data)


def test_protected_credential_scope_remains_exact():
    from network_change_delivery.openbao_profiled_deploy_config import DEVICE_IDS

    assert DEVICE_IDS == (1, 2)


def test_declaration_order_is_authority_even_when_it_is_not_alphabetical(context):
    original = context.inventory.population
    context.inventory.population = ProfiledInventoryPopulation(
        declaration=ProfiledPopulationDeclaration(
            members=tuple(reversed(original.declaration.members))
        ),
        devices=tuple(reversed(original.devices)),
    )
    names = tuple(reversed(IOS_NAMES))
    result = plan(context, selected_intent(context, names=names))
    assert tuple(child.device.logical_name for child in result.children) == names
    assert context.inventory.calls == [
        "population",
        names[0],
        context.inventory.pairs[names[0]][1].name,
        names[1],
        context.inventory.pairs[names[1]][1].name,
    ]
    assert result.canaries == ("netbox:dcim.device:9",)
    assert result.waves == (("netbox:dcim.device:8",),)


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
