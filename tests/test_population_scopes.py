"""Exact declared membership, reusable profiles and independent consumer scopes."""

from copy import deepcopy

import pytest
from profiled_population_fixtures import declared_population
from test_profiled_population import profiled_provider

from network_change_delivery.inventory import InventoryError
from network_change_delivery.observability_targets import targets_from_inventory
from network_change_delivery.profile_inventory import (
    OBSERVABILITY_SCOPE,
    OXIDIZED_COLLECTION_SCOPE,
    ProfiledPopulationDeclaration,
    ProfiledPopulationScope,
)
from network_change_delivery.snmp_profile import snmp_scope_devices


@pytest.mark.parametrize("size", [1, 2, 4, 5])
def test_declared_population_sizes_resolve_canonically(size):
    declaration, scope, provider, _ = declared_population(size)
    population = provider.resolve_profiled_population()
    assert population.declaration == declaration
    assert (
        tuple(d.device_identity for d in population.devices) == declaration.identities
    )
    assert population.project(scope).devices == population.devices
    assert len(targets_from_inventory(provider, scope=scope)) == size
    assert (
        scope.digest
        == ProfiledPopulationScope.model_validate_json(scope.model_dump_json()).digest
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "missing",
        "extra",
        "inactive",
        "duplicate_id",
        "duplicate_name",
        "swapped_identity",
        "role",
        "platform",
        "device_type",
    ],
)
def test_netbox_exact_declaration_failures(mutation):
    declaration, _, _, payloads = declared_population(5)
    if mutation == "missing":
        payloads.pop()
    elif mutation == "extra":
        payloads.append(deepcopy(payloads[-1]))
    elif mutation == "inactive":
        payloads[-1]["status"]["value"] = "offline"
    elif mutation == "duplicate_id":
        payloads[-1]["id"] = payloads[0]["id"]
    elif mutation == "duplicate_name":
        payloads[-1]["name"] = payloads[0]["name"]
    elif mutation == "swapped_identity":
        payloads[-1]["id"], payloads[0]["id"] = payloads[0]["id"], payloads[-1]["id"]
    elif mutation == "role":
        payloads[-1]["role"]["slug"] = "access"
    elif mutation == "platform":
        payloads[-1]["platform"]["slug"] = "cisco-ios-xe"
    else:
        payloads[-1]["device_type"]["slug"] = "c8000v"
    with pytest.raises(InventoryError):
        profiled_provider(
            payloads, declaration=declaration
        ).resolve_profiled_population()


def test_scope_isolation_and_profile_reuse():
    declaration, scope, provider, _ = declared_population(5)
    population = provider.resolve_profiled_population()
    assert (
        declaration.members[-1].automation_profile_id
        == declaration.members[2].automation_profile_id
    )
    assert (
        declaration.members[-1].cml_realization_profile_id
        == declaration.members[2].cml_realization_profile_id
    )
    assert len(population.project(OXIDIZED_COLLECTION_SCOPE).devices) == 4
    assert len(targets_from_inventory(provider, scope=OBSERVABILITY_SCOPE)) == 4
    assert tuple(d.device_identity for d in snmp_scope_devices(population, scope)) == (
        "netbox:dcim.device:1",
        "netbox:dcim.device:2",
    )


@pytest.mark.parametrize("index", [0, 1])
def test_repeated_snmp_profile_naturally_joins_projection(index):
    _, scope, provider, _ = declared_population(5, repeated_profile_index=index)
    selected = snmp_scope_devices(provider.resolve_profiled_population(), scope)
    assert tuple(d.device_identity for d in selected) == (
        "netbox:dcim.device:1",
        "netbox:dcim.device:2",
        "netbox:dcim.device:14",
    )


@pytest.mark.parametrize(
    "change", ["empty", "duplicate", "unknown", "profile", "order"]
)
def test_scope_cannot_claim_unreviewed_membership(change):
    _declaration, scope, _, _ = declared_population(5)
    data = scope.model_dump(mode="json")
    if change == "empty":
        data["members"] = []
    elif change == "duplicate":
        data["members"].append(data["members"][0])
    elif change == "unknown":
        data["members"][-1]["logical_name"] = "undeclared"
    elif change == "profile":
        data["members"][-1]["automation_profile_id"] = "cat8000v_iosxe"
    else:
        data["members"].reverse()
    with pytest.raises(ValueError):
        ProfiledPopulationScope.model_validate(data)
    with pytest.raises(ValueError):
        ProfiledPopulationDeclaration(members=())
