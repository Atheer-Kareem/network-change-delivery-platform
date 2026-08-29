from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from network_change_delivery.observability_targets import ObservabilityReady
from network_change_delivery.snmp_telemetry import (
    MAX_EXPECTED_INTERFACES_PER_DEVICE,
    MAX_OBSERVED_INTERFACES_PER_DEVICE,
    ExpectedSnmpInterface,
    ExpectedSnmpInterfacePopulation,
    ObservedSnmpInterface,
    SnmpContractError,
    SnmpCredentialReference,
    SnmpDeviceTargetStatus,
    SnmpFailureClassification,
    SnmpReadiness,
    SnmpTargetIdentity,
    SnmpTargetState,
    normalize_interfaces,
    target_generation_with_digest,
)

DEVICE_1 = "netbox:dcim.device:1"
DEVICE_2 = "netbox:dcim.device:2"
MAPPING_DIGEST = "sha256:" + "a" * 64


def expected(identity: int, name: str, device: str = DEVICE_1) -> ExpectedSnmpInterface:
    return ExpectedSnmpInterface(
        device=device,
        inventory_object_id=f"netbox:dcim.interface:{identity}",
        name=name,
    )


def observed(index: int, name: str) -> ObservedSnmpInterface:
    return ObservedSnmpInterface(if_index=index, if_name=name)


def population(
    interfaces: tuple[ExpectedSnmpInterface, ...],
    *,
    device: str = DEVICE_1,
    pagination_complete: bool = True,
) -> ExpectedSnmpInterfacePopulation:
    return ExpectedSnmpInterfacePopulation(
        device=device,
        pagination_complete=pagination_complete,
        interfaces=interfaces,
    )


def credential(device: str = DEVICE_1) -> SnmpCredentialReference:
    number = device.rsplit(":", 1)[1]
    return SnmpCredentialReference(
        device=device,
        reference=f"snmpv3:netbox:dcim.device:{number}:generation:v1",
        auth_selector=f"ncdp_snmp_device_{number}_v1",
    )


def status(
    device: str,
    state: SnmpTargetState,
    failure: SnmpFailureClassification | None = None,
) -> SnmpDeviceTargetStatus:
    return SnmpDeviceTargetStatus(
        device=device,
        state=state,
        failure=failure,
        interface_mapping_digest=(
            MAPPING_DIGEST if state is SnmpTargetState.ACTIVE else None
        ),
    )


def test_exact_ifname_mapping_uses_netbox_identity_and_ignores_snmp_only_rows() -> None:
    mapping = normalize_interfaces(
        population((expected(2, "GigabitEthernet2"), expected(1, "GigabitEthernet1"))),
        (
            observed(10, "GigabitEthernet1"),
            observed(20, "GigabitEthernet2"),
            observed(99, "Null0"),
        ),
    )
    assert [item.inventory_object_id for item in mapping.interfaces] == [
        "netbox:dcim.interface:1",
        "netbox:dcim.interface:2",
    ]
    assert [item.observed_if_index for item in mapping.interfaces] == [10, 20]
    assert all(item.device == DEVICE_1 for item in mapping.interfaces)
    assert mapping.unmanaged_observed_count == 1
    assert "Null0" not in mapping.model_dump_json()


def test_ifindex_change_does_not_change_durable_interface_identity() -> None:
    expected_interfaces = population(
        (expected(3, "fxp0", DEVICE_2), expected(4, "ge-0/0/1", DEVICE_2)),
        device=DEVICE_2,
    )
    first = normalize_interfaces(
        expected_interfaces,
        (observed(1, "fxp0"), observed(534, "ge-0/0/1")),
    )
    second = normalize_interfaces(
        expected_interfaces,
        (observed(7, "fxp0"), observed(900, "ge-0/0/1")),
    )
    assert [item.inventory_object_id for item in first.interfaces] == [
        item.inventory_object_id for item in second.interfaces
    ]
    assert [item.interface_name for item in first.interfaces] == [
        item.interface_name for item in second.interfaces
    ]
    assert first.digest != second.digest


@pytest.mark.parametrize(
    ("expected_interfaces", "observed_interfaces", "failure"),
    [
        (
            (expected(1, "GigabitEthernet1"),),
            (observed(1, "GigabitEthernet2"),),
            SnmpFailureClassification.EXPECTED_INTERFACE_MISSING,
        ),
        (
            (expected(1, "GigabitEthernet1"), expected(1, "GigabitEthernet2")),
            (observed(1, "GigabitEthernet1"), observed(2, "GigabitEthernet2")),
            SnmpFailureClassification.INVENTORY_DUPLICATE_ID,
        ),
        (
            (expected(1, "GigabitEthernet1"), expected(2, "GigabitEthernet1")),
            (observed(1, "GigabitEthernet1"),),
            SnmpFailureClassification.INVENTORY_DUPLICATE_NAME,
        ),
        (
            (expected(1, "GigabitEthernet1"),),
            (observed(1, "GigabitEthernet1"), observed(1, "Null0")),
            SnmpFailureClassification.OBSERVED_DUPLICATE_INDEX,
        ),
        (
            (expected(1, "GigabitEthernet1"),),
            (observed(1, "GigabitEthernet1"), observed(2, "GigabitEthernet1")),
            SnmpFailureClassification.OBSERVED_NAME_AMBIGUOUS,
        ),
    ],
)
def test_missing_duplicate_ambiguous_and_fuzzy_identity_fail_closed(
    expected_interfaces: tuple[ExpectedSnmpInterface, ...],
    observed_interfaces: tuple[ObservedSnmpInterface, ...],
    failure: SnmpFailureClassification,
) -> None:
    with pytest.raises(SnmpContractError) as caught:
        normalize_interfaces(population(expected_interfaces), observed_interfaces)
    assert caught.value.failure is failure
    assert "GigabitEthernet" not in str(caught.value)


def test_population_limits_are_fail_closed() -> None:
    too_many_expected = tuple(
        expected(index, f"Ethernet{index}")
        for index in range(1, MAX_EXPECTED_INTERFACES_PER_DEVICE + 2)
    )
    with pytest.raises(ValidationError, match="at most 64 items"):
        population(too_many_expected)
    too_many_observed = tuple(
        observed(index, f"Ethernet{index}")
        for index in range(1, MAX_OBSERVED_INTERFACES_PER_DEVICE + 2)
    )
    with pytest.raises(SnmpContractError) as observed_error:
        normalize_interfaces(population((expected(1, "Ethernet1"),)), too_many_observed)
    assert (
        observed_error.value.failure
        is SnmpFailureClassification.OBSERVED_POPULATION_REJECTED
    )


@pytest.mark.parametrize(
    ("expected_population", "failure"),
    [
        (
            population((expected(1, "Ethernet1"),), pagination_complete=False),
            SnmpFailureClassification.INVENTORY_PAGINATION_REJECTED,
        ),
        (
            population((expected(1, "Ethernet1", DEVICE_2),)),
            SnmpFailureClassification.INVENTORY_RELATIONSHIP_REJECTED,
        ),
    ],
)
def test_incomplete_pagination_and_wrong_device_relationship_fail_closed(
    expected_population: ExpectedSnmpInterfacePopulation,
    failure: SnmpFailureClassification,
) -> None:
    with pytest.raises(SnmpContractError) as caught:
        normalize_interfaces(expected_population, (observed(1, "Ethernet1"),))
    assert caught.value.failure is failure


def test_credential_reference_and_target_are_nonsecret_and_device_bound() -> None:
    route = credential()
    target = SnmpTargetIdentity(
        device=DEVICE_1,
        device_name="core-02",
        platform="cisco_iosxe",
        credential=route,
    )
    assert target.credential.auth_selector == "ncdp_snmp_device_1_v1"
    with pytest.raises(ValidationError, match="device mismatch"):
        SnmpCredentialReference(
            device=DEVICE_2,
            reference=route.reference,
            auth_selector="ncdp_snmp_device_2_v1",
        )
    with pytest.raises(ValidationError, match="device mismatch"):
        target.model_copy(update={"credential": credential(DEVICE_2)}).model_validate(
            target.model_copy(update={"credential": credential(DEVICE_2)})
        )


@pytest.mark.parametrize("field", ["auth_password", "privacy_password", "password"])
def test_contracts_reject_secret_value_fields(field: str) -> None:
    values = credential().model_dump()
    values[field] = "not-a-real-secret"
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        SnmpCredentialReference.model_validate(values)


def test_serialized_contract_has_only_nonsecret_routes() -> None:
    content = credential().model_dump_json()
    assert json.loads(content) == {
        "device": DEVICE_1,
        "reference": "snmpv3:netbox:dcim.device:1:generation:v1",
        "auth_selector": "ncdp_snmp_device_1_v1",
    }
    for forbidden in ("auth_password", "privacy_password", "ssh_password"):
        assert forbidden not in content.casefold()


def test_generation_derives_active_degraded_retired_failed_and_ambiguous() -> None:
    active = status(DEVICE_1, SnmpTargetState.ACTIVE)
    active_2 = status(DEVICE_2, SnmpTargetState.ACTIVE)
    assert (
        target_generation_with_digest((active_2, active)).state
        is SnmpTargetState.ACTIVE
    )
    degraded = status(
        DEVICE_2,
        SnmpTargetState.DEGRADED,
        SnmpFailureClassification.CREDENTIAL_UNAVAILABLE,
    )
    assert (
        target_generation_with_digest((active, degraded)).state
        is SnmpTargetState.DEGRADED
    )
    retired = status(DEVICE_1, SnmpTargetState.RETIRED)
    assert target_generation_with_digest((retired,)).state is SnmpTargetState.RETIRED
    failed = status(
        DEVICE_1,
        SnmpTargetState.FAILED,
        SnmpFailureClassification.SERVICE_UNAVAILABLE,
    )
    assert target_generation_with_digest((failed,)).state is SnmpTargetState.FAILED
    ambiguous = status(
        DEVICE_1,
        SnmpTargetState.AMBIGUOUS,
        SnmpFailureClassification.OBSERVED_NAME_AMBIGUOUS,
    )
    assert (
        target_generation_with_digest((active_2, ambiguous)).state
        is SnmpTargetState.AMBIGUOUS
    )


def test_generation_is_ordered_digest_bound_and_separate_from_11a() -> None:
    generation = target_generation_with_digest(
        (
            status(DEVICE_2, SnmpTargetState.ACTIVE),
            status(DEVICE_1, SnmpTargetState.ACTIVE),
        )
    )
    assert [item.device for item in generation.devices] == [DEVICE_1, DEVICE_2]
    assert generation.digest == generation.calculated_digest()
    readiness = SnmpReadiness(
        state=generation.state, target_generation_digest=generation.digest
    )
    assert readiness.service_contract == "11C"
    assert ObservabilityReady.model_fields["service_contract"].default == "11A"
    with pytest.raises(ValidationError, match="digest rejected"):
        generation.model_copy(update={"digest": "sha256:" + "f" * 64}).model_validate(
            generation.model_copy(update={"digest": "sha256:" + "f" * 64})
        )
