"""Offline, secret-free SNMPv3 telemetry identity and state contracts."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from network_change_delivery.audit import (
    NetBoxDeviceIdentity,
    NetBoxInterfaceIdentity,
    Sha256,
    canonical_json_bytes,
    sha256_identity,
)

MAX_EXPECTED_INTERFACES_PER_DEVICE = 64
MAX_OBSERVED_INTERFACES_PER_DEVICE = 512
MAX_SNMP_TARGETS = 16

SnmpName = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$",
    ),
]
SnmpAuthSelector = Annotated[
    str,
    StringConstraints(min_length=3, max_length=64, pattern=r"^[a-z][a-z0-9_]+$"),
]
SnmpCredentialReferenceValue = Annotated[
    str,
    StringConstraints(
        min_length=32,
        max_length=160,
        pattern=(
            r"^snmpv3:netbox:dcim\.device:[1-9][0-9]*:generation:"
            r"[a-z0-9][a-z0-9._-]{0,31}$"
        ),
    ),
]


class SnmpContractError(ValueError):
    """Bounded normalization failure without provider or interface content."""

    def __init__(self, failure: SnmpFailureClassification) -> None:
        self.failure = failure
        super().__init__(f"SNMP interface normalization failed: {failure.value}")


class SnmpFailureClassification(StrEnum):
    """Closed failure reasons shared by offline target and mapping contracts."""

    INVENTORY_POPULATION_REJECTED = "INVENTORY_POPULATION_REJECTED"
    INVENTORY_PAGINATION_REJECTED = "INVENTORY_PAGINATION_REJECTED"
    INVENTORY_RELATIONSHIP_REJECTED = "INVENTORY_RELATIONSHIP_REJECTED"
    INVENTORY_DUPLICATE_ID = "INVENTORY_DUPLICATE_ID"
    INVENTORY_DUPLICATE_NAME = "INVENTORY_DUPLICATE_NAME"
    OBSERVED_POPULATION_REJECTED = "OBSERVED_POPULATION_REJECTED"
    OBSERVED_DUPLICATE_INDEX = "OBSERVED_DUPLICATE_INDEX"
    OBSERVED_NAME_AMBIGUOUS = "OBSERVED_NAME_AMBIGUOUS"
    EXPECTED_INTERFACE_MISSING = "EXPECTED_INTERFACE_MISSING"
    CREDENTIAL_UNAVAILABLE = "CREDENTIAL_UNAVAILABLE"
    REALIZATION_REJECTED = "REALIZATION_REJECTED"
    PUBLICATION_FAILED = "PUBLICATION_FAILED"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"


class SnmpTargetState(StrEnum):
    """Independent SNMP state; it has no effect on 11A readiness."""

    ACTIVE = "ACTIVE"
    DEGRADED = "DEGRADED"
    RETIRED = "RETIRED"
    FAILED = "FAILED"
    AMBIGUOUS = "AMBIGUOUS"


class SnmpCredentialReference(BaseModel):
    """Provider-independent, non-secret versioned credential routing."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    device: NetBoxDeviceIdentity
    reference: SnmpCredentialReferenceValue
    auth_selector: SnmpAuthSelector

    @model_validator(mode="after")
    def reference_matches_device(self) -> SnmpCredentialReference:
        device_id = self.device.removeprefix("netbox:dcim.device:")
        expected = f"snmpv3:netbox:dcim.device:{device_id}:generation:"
        if not self.reference.startswith(expected):
            raise ValueError("SNMP credential reference device mismatch")
        return self


class SnmpTargetIdentity(BaseModel):
    """One admitted logical device and its non-secret SNMP auth route."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    device: NetBoxDeviceIdentity
    device_name: SnmpName
    platform: Literal["cisco_iosxe", "junos"]
    credential: SnmpCredentialReference

    @model_validator(mode="after")
    def credential_matches_device(self) -> SnmpTargetIdentity:
        if self.credential.device != self.device:
            raise ValueError("SNMP target credential device mismatch")
        return self


class ExpectedSnmpInterface(BaseModel):
    """One bounded NetBox-modeled interface eligible for exact matching."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    device: NetBoxDeviceIdentity
    inventory_object_id: NetBoxInterfaceIdentity
    name: SnmpName


class ExpectedSnmpInterfacePopulation(BaseModel):
    """One device's modeled interfaces plus explicit pagination completion."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    device: NetBoxDeviceIdentity
    pagination_complete: bool
    interfaces: tuple[ExpectedSnmpInterface, ...] = Field(
        min_length=1, max_length=MAX_EXPECTED_INTERFACES_PER_DEVICE
    )


class ObservedSnmpInterface(BaseModel):
    """Transient SNMP row used only to resolve stable NetBox identity."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    if_index: int = Field(ge=1, le=2_147_483_647)
    if_name: SnmpName


class NormalizedSnmpInterface(BaseModel):
    """Stable managed identity with one transient current ifIndex observation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    device: NetBoxDeviceIdentity
    inventory_object_id: NetBoxInterfaceIdentity
    interface_name: SnmpName
    observed_if_index: int = Field(ge=1, le=2_147_483_647)


class SnmpInterfaceMapping(BaseModel):
    """Complete exact mapping for one device and one observation generation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["1"] = "1"
    device: NetBoxDeviceIdentity
    interfaces: tuple[NormalizedSnmpInterface, ...] = Field(
        min_length=1, max_length=MAX_EXPECTED_INTERFACES_PER_DEVICE
    )
    unmanaged_observed_count: int = Field(ge=0, le=MAX_OBSERVED_INTERFACES_PER_DEVICE)
    digest: Sha256

    @model_validator(mode="after")
    def mapping_is_complete_and_ordered(self) -> SnmpInterfaceMapping:
        if any(item.device != self.device for item in self.interfaces):
            raise ValueError("SNMP interface mapping device mismatch")
        identities = [item.inventory_object_id for item in self.interfaces]
        if identities != sorted(identities, key=_identity_number) or len(
            identities
        ) != len(set(identities)):
            raise ValueError("SNMP interface mapping identity rejected")
        if self.digest != self.calculated_digest():
            raise ValueError("SNMP interface mapping digest rejected")
        return self

    def calculated_digest(self) -> str:
        return sha256_identity(
            canonical_json_bytes(self.model_dump(mode="json", exclude={"digest"}))
        )


class SnmpDeviceTargetStatus(BaseModel):
    """One expected device's explicit SNMP-only eligibility state."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    device: NetBoxDeviceIdentity
    state: SnmpTargetState
    failure: SnmpFailureClassification | None = None
    interface_mapping_digest: Sha256 | None = None

    @model_validator(mode="after")
    def coherent_state(self) -> SnmpDeviceTargetStatus:
        if self.state is SnmpTargetState.ACTIVE:
            if self.failure is not None or self.interface_mapping_digest is None:
                raise ValueError("active SNMP device state rejected")
        elif self.state is SnmpTargetState.RETIRED:
            if self.failure is not None or self.interface_mapping_digest is not None:
                raise ValueError("retired SNMP device state rejected")
        elif self.failure is None:
            raise ValueError("inactive SNMP device state requires failure")
        return self


class SnmpTargetGeneration(BaseModel):
    """Digest-bound expected SNMP population, independent from 11A targets."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["1"] = "1"
    state: SnmpTargetState
    devices: tuple[SnmpDeviceTargetStatus, ...] = Field(
        min_length=1, max_length=MAX_SNMP_TARGETS
    )
    digest: Sha256

    @model_validator(mode="after")
    def coherent_population(self) -> SnmpTargetGeneration:
        identities = [item.device for item in self.devices]
        if identities != sorted(identities, key=_identity_number) or len(
            identities
        ) != len(set(identities)):
            raise ValueError("SNMP target population rejected")
        if self.state is not derive_target_state(self.devices):
            raise ValueError("SNMP target generation state rejected")
        if self.digest != self.calculated_digest():
            raise ValueError("SNMP target generation digest rejected")
        return self

    def calculated_digest(self) -> str:
        return sha256_identity(
            canonical_json_bytes(self.model_dump(mode="json", exclude={"digest"}))
        )


class SnmpReadiness(BaseModel):
    """Minimal separate readiness pointer without changing 11A's schema."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["1"] = "1"
    service_contract: Literal["11C"] = "11C"
    state: SnmpTargetState
    target_generation_digest: Sha256


def _identity_number(value: str) -> int:
    return int(value.rsplit(":", 1)[1])


def _raise(failure: SnmpFailureClassification) -> None:
    raise SnmpContractError(failure)


def normalize_interfaces(
    expected_population: ExpectedSnmpInterfacePopulation,
    observed: tuple[ObservedSnmpInterface, ...],
) -> SnmpInterfaceMapping:
    """Resolve exact ifName matches without promoting SNMP-only rows."""
    device = expected_population.device
    expected = expected_population.interfaces
    if not expected_population.pagination_complete:
        _raise(SnmpFailureClassification.INVENTORY_PAGINATION_REJECTED)
    if not expected or len(expected) > MAX_EXPECTED_INTERFACES_PER_DEVICE:
        _raise(SnmpFailureClassification.INVENTORY_POPULATION_REJECTED)
    if not observed or len(observed) > MAX_OBSERVED_INTERFACES_PER_DEVICE:
        _raise(SnmpFailureClassification.OBSERVED_POPULATION_REJECTED)
    expected_ids = [item.inventory_object_id for item in expected]
    expected_names = [item.name for item in expected]
    observed_indexes = [item.if_index for item in observed]
    observed_names = [item.if_name for item in observed]
    if any(item.device != device for item in expected):
        _raise(SnmpFailureClassification.INVENTORY_RELATIONSHIP_REJECTED)
    if len(expected_ids) != len(set(expected_ids)):
        _raise(SnmpFailureClassification.INVENTORY_DUPLICATE_ID)
    if len(expected_names) != len(set(expected_names)):
        _raise(SnmpFailureClassification.INVENTORY_DUPLICATE_NAME)
    if len(observed_indexes) != len(set(observed_indexes)):
        _raise(SnmpFailureClassification.OBSERVED_DUPLICATE_INDEX)
    if len(observed_names) != len(set(observed_names)):
        _raise(SnmpFailureClassification.OBSERVED_NAME_AMBIGUOUS)
    rows = {item.if_name: item for item in observed}
    normalized: list[NormalizedSnmpInterface] = []
    for interface in expected:
        row = rows.get(interface.name)
        if row is None:
            _raise(SnmpFailureClassification.EXPECTED_INTERFACE_MISSING)
        normalized.append(
            NormalizedSnmpInterface(
                device=device,
                inventory_object_id=interface.inventory_object_id,
                interface_name=interface.name,
                observed_if_index=row.if_index,
            )
        )
    normalized.sort(key=lambda item: _identity_number(item.inventory_object_id))
    unsigned = SnmpInterfaceMapping.model_construct(
        schema_version="1",
        device=device,
        interfaces=tuple(normalized),
        unmanaged_observed_count=len(observed) - len(normalized),
        digest="sha256:" + "0" * 64,
    )
    return SnmpInterfaceMapping.model_validate(
        {
            **unsigned.model_dump(mode="json", exclude={"digest"}),
            "digest": unsigned.calculated_digest(),
        }
    )


def derive_target_state(
    devices: tuple[SnmpDeviceTargetStatus, ...],
) -> SnmpTargetState:
    """Derive honest aggregate state without coupling to TCP readiness."""
    states = {item.state for item in devices}
    if SnmpTargetState.AMBIGUOUS in states:
        return SnmpTargetState.AMBIGUOUS
    if states == {SnmpTargetState.ACTIVE}:
        return SnmpTargetState.ACTIVE
    if states == {SnmpTargetState.RETIRED}:
        return SnmpTargetState.RETIRED
    if SnmpTargetState.ACTIVE in states or SnmpTargetState.DEGRADED in states:
        return SnmpTargetState.DEGRADED
    return SnmpTargetState.FAILED


def target_generation_with_digest(
    devices: tuple[SnmpDeviceTargetStatus, ...],
) -> SnmpTargetGeneration:
    """Construct one canonical generation with its derived state and digest."""
    ordered = tuple(sorted(devices, key=lambda item: _identity_number(item.device)))
    unsigned = SnmpTargetGeneration.model_construct(
        schema_version="1",
        state=derive_target_state(ordered),
        devices=ordered,
        digest="sha256:" + "0" * 64,
    )
    return SnmpTargetGeneration.model_validate(
        {
            **unsigned.model_dump(mode="json", exclude={"digest"}),
            "digest": unsigned.calculated_digest(),
        }
    )
