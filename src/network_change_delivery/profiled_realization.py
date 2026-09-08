"""Current profiled contracts for CML realization and host trust.

These types bind realization identity, host trust, and run-scoped STAGING
read-only projection. This module contains no CML client, credential, device
command, persistence, or write authority.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal, Protocol

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    IPvAnyAddress,
    StringConstraints,
    model_validator,
)

from network_change_delivery.architecture_contracts import (
    AutomationProfileID,
    CmlRealizationProfileID,
    ManagementEndpoint,
    ManagementEndpointPurpose,
    NetBoxDeviceIdentity,
    OperationalRole,
    Sha256Digest,
    get_automation_profile,
)
from network_change_delivery.profile_inventory import (
    LIVE_REALIZATION_SCOPE,
    PROFILE_ADMISSION_CATALOG,
    PROFILED_MANAGED_POPULATION,
    STAGING_REALIZATION_SCOPE,
    ProfiledInventoryDevice,
    ProfiledLogicalName,
    ProfiledPopulationDeclaration,
    ProfiledPopulationScope,
    ProfileReadOnlyTarget,
)

CmlUUID = Annotated[
    str,
    StringConstraints(pattern=r"^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$"),
]
StableReferenceIdentity = Annotated[
    str,
    StringConstraints(
        min_length=3,
        max_length=200,
        pattern=r"^[a-z][a-z0-9._:/-]*$",
    ),
]
StagingRunID = Annotated[
    str,
    StringConstraints(
        min_length=3,
        max_length=100,
        pattern=r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$",
    ),
]
NonEmptyString = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
HostKeyFingerprint = Annotated[
    str, StringConstraints(pattern=r"^SHA256:[A-Za-z0-9+/]{43}$")
]


class ProfiledRealizationError(ValueError):
    """Bounded failure to admit or project a profiled realization."""


class RealizationEnvironment(StrEnum):
    """Closed realization environments; logical device identity is shared."""

    LIVE = "LIVE"
    STAGING = "STAGING"


class RealizationLifecycleState(StrEnum):
    """Small lifecycle vocabulary without becoming a workflow engine."""

    PREPARING = "PREPARING"
    READY = "READY"
    CLEANING = "CLEANING"
    RETIRED = "RETIRED"
    FAILED = "FAILED"
    AMBIGUOUS = "AMBIGUOUS"


class SSHHostKeyType(StrEnum):
    """Closed server public-key types accepted by trust admission."""

    SSH_RSA = "ssh-rsa"
    SSH_ED25519 = "ssh-ed25519"
    ECDSA_SHA2_NISTP256 = "ecdsa-sha2-nistp256"
    ECDSA_SHA2_NISTP384 = "ecdsa-sha2-nistp384"
    ECDSA_SHA2_NISTP521 = "ecdsa-sha2-nistp521"


class EvidenceReference(BaseModel):
    """Secret-free durable identity and digest for independently held evidence."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    identity: StableReferenceIdentity
    digest: Sha256Digest


class _ScopedBinding(Protocol):
    logical_name: ProfiledLogicalName
    device_identity: str
    cml_node_id: str


def _validate_times(admitted_at: datetime, expires_at: datetime) -> None:
    if expires_at <= admitted_at:
        raise ValueError("realization expiration must follow admission")


def _validate_profile_pairing(
    *,
    automation_profile_id: AutomationProfileID,
    cml_realization_profile_id: CmlRealizationProfileID,
) -> None:
    # Instance membership is verified against the aggregate's exact scope.
    if not any(
        rule.automation_profile_id is automation_profile_id
        and rule.cml_realization_profile_id is cml_realization_profile_id
        for rule in PROFILE_ADMISSION_CATALOG.values()
    ):
        raise ValueError("realized device does not match the Git profile catalog")


def _validate_management_endpoint(
    *,
    device_identity: NetBoxDeviceIdentity,
    automation_profile_id: AutomationProfileID,
    endpoint: ManagementEndpoint,
) -> None:
    binding = endpoint.binding
    if (
        binding.physical_attachment.interface.device != device_identity
        or binding.l3_endpoint.interface.device != device_identity
    ):
        raise ValueError("realized management binding has the wrong stable device")
    profile = get_automation_profile(automation_profile_id)
    admitted = {
        (expectation.service, expectation.port)
        for expectation in profile.readiness_services
    }
    if (binding.l3_endpoint.service, binding.l3_endpoint.port) not in admitted:
        raise ValueError("realized management service is not profile-admitted")


def _validate_scope(
    devices: tuple[_ScopedBinding, ...], scope: ProfiledPopulationScope
) -> None:
    scope.require_bindings(devices)
    nodes = tuple(device.cml_node_id for device in devices)
    if len(nodes) != len(set(nodes)):
        raise ValueError("profiled realization CML node identities are duplicated")
    for device, member in zip(devices, scope.members, strict=True):
        if (
            hasattr(device, "operational_role")
            and device.operational_role is not member.operational_role
        ):
            raise ValueError("realized device role does not match the Git catalog")


class ProfiledRealizedDevice(BaseModel):
    """One secret-free stable-device to exact CML-node realization binding."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    declaration: ProfiledPopulationDeclaration = PROFILED_MANAGED_POPULATION
    device_identity: NetBoxDeviceIdentity
    logical_name: ProfiledLogicalName
    operational_role: OperationalRole
    automation_profile_id: AutomationProfileID
    cml_realization_profile_id: CmlRealizationProfileID
    cml_node_id: CmlUUID
    lifecycle_state: RealizationLifecycleState
    readiness_evidence: EvidenceReference
    management_endpoint: ManagementEndpoint

    @model_validator(mode="after")
    def exact_identity_and_profile(self) -> ProfiledRealizedDevice:
        member = self.declaration.member(self.logical_name)
        if (
            self.device_identity,
            self.automation_profile_id,
            self.cml_realization_profile_id,
        ) != (
            member.device_identity,
            member.automation_profile_id,
            member.cml_realization_profile_id,
        ):
            raise ValueError("realized device does not match the Git profile catalog")
        if (
            hasattr(self, "operational_role")
            and self.operational_role is not member.operational_role
        ):
            raise ValueError("realized device role does not match the Git catalog")
        _validate_profile_pairing(
            automation_profile_id=self.automation_profile_id,
            cml_realization_profile_id=self.cml_realization_profile_id,
        )
        _validate_management_endpoint(
            device_identity=self.device_identity,
            automation_profile_id=self.automation_profile_id,
            endpoint=self.management_endpoint,
        )
        return self


class PersistentProfiledRealization(BaseModel):
    """Persistent LIVE realization bound to an exact reviewed scope."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal["1"] = "1"
    environment: Literal[RealizationEnvironment.LIVE] = RealizationEnvironment.LIVE
    realization_identity: StableReferenceIdentity
    cml_lab_id: CmlUUID
    cml_lab_title: NonEmptyString
    lifecycle_state: RealizationLifecycleState
    admitted_at: AwareDatetime
    expires_at: AwareDatetime
    admission_evidence: EvidenceReference
    scope: ProfiledPopulationScope = LIVE_REALIZATION_SCOPE
    devices: tuple[ProfiledRealizedDevice, ...]

    @model_validator(mode="after")
    def exact_live_realization(self) -> PersistentProfiledRealization:
        _validate_times(self.admitted_at, self.expires_at)
        _validate_scope(self.devices, self.scope)
        if any(
            device.management_endpoint.purpose is not ManagementEndpointPurpose.LIVE
            for device in self.devices
        ):
            raise ValueError("persistent realization requires LIVE management")
        if self.lifecycle_state is RealizationLifecycleState.READY and any(
            device.lifecycle_state is not RealizationLifecycleState.READY
            for device in self.devices
        ):
            raise ValueError("READY persistent realization requires READY devices")
        return self


class CmlAnchoredHostTrustRecord(BaseModel):
    """Fingerprint metadata inseparable from CML and stable device identity."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal["1"] = "1"
    environment: RealizationEnvironment
    realization_identity: StableReferenceIdentity
    cml_lab_id: CmlUUID
    cml_node_id: CmlUUID
    declaration: ProfiledPopulationDeclaration = PROFILED_MANAGED_POPULATION
    device_identity: NetBoxDeviceIdentity
    logical_name: ProfiledLogicalName
    management_address: IPvAnyAddress
    management_port: int = Field(ge=1, le=65535)
    automation_profile_id: AutomationProfileID
    cml_realization_profile_id: CmlRealizationProfileID
    host_key_type: SSHHostKeyType
    host_key_fingerprint: HostKeyFingerprint
    cml_anchor_evidence: EvidenceReference
    admitted_at: AwareDatetime
    trust_generation: EvidenceReference

    @model_validator(mode="after")
    def exact_realization_bound_trust(self) -> CmlAnchoredHostTrustRecord:
        member = self.declaration.member(self.logical_name)
        if (
            self.device_identity,
            self.automation_profile_id,
            self.cml_realization_profile_id,
        ) != (
            member.device_identity,
            member.automation_profile_id,
            member.cml_realization_profile_id,
        ):
            raise ValueError("realized device does not match the Git profile catalog")
        if (
            hasattr(self, "operational_role")
            and self.operational_role is not member.operational_role
        ):
            raise ValueError("realized device role does not match the Git catalog")
        _validate_profile_pairing(
            automation_profile_id=self.automation_profile_id,
            cml_realization_profile_id=self.cml_realization_profile_id,
        )
        profile = get_automation_profile(self.automation_profile_id)
        if self.management_port not in {
            expectation.port for expectation in profile.readiness_services
        }:
            raise ValueError("host trust port is not admitted by its profile")
        return self


class CmlAnchoredHostTrustGeneration(BaseModel):
    """Scope-bound trust metadata generation without public-key blobs."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal["1"] = "1"
    environment: RealizationEnvironment
    realization_identity: StableReferenceIdentity
    cml_lab_id: CmlUUID
    admitted_at: AwareDatetime
    expires_at: AwareDatetime
    generation_evidence: EvidenceReference
    scope: ProfiledPopulationScope = LIVE_REALIZATION_SCOPE
    records: tuple[CmlAnchoredHostTrustRecord, ...]

    @model_validator(mode="after")
    def exact_trust_generation(self) -> CmlAnchoredHostTrustGeneration:
        _validate_times(self.admitted_at, self.expires_at)
        _validate_scope(self.records, self.scope)
        for record in self.records:
            if (
                record.environment is not self.environment
                or record.realization_identity != self.realization_identity
                or record.cml_lab_id != self.cml_lab_id
                or record.trust_generation != self.generation_evidence
            ):
                raise ValueError("host trust record is detached from its generation")
        return self


class StagingRealizedDevice(BaseModel):
    """One exact STAGING binding with readiness and trust evidence references."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    declaration: ProfiledPopulationDeclaration = PROFILED_MANAGED_POPULATION
    device_identity: NetBoxDeviceIdentity
    logical_name: ProfiledLogicalName
    operational_role: OperationalRole
    automation_profile_id: AutomationProfileID
    cml_realization_profile_id: CmlRealizationProfileID
    cml_node_id: CmlUUID
    staging_endpoint: ManagementEndpoint
    readiness_evidence: EvidenceReference
    trust_evidence: EvidenceReference | None = None

    @model_validator(mode="after")
    def exact_staging_binding(self) -> StagingRealizedDevice:
        member = self.declaration.member(self.logical_name)
        if (
            self.device_identity,
            self.automation_profile_id,
            self.cml_realization_profile_id,
        ) != (
            member.device_identity,
            member.automation_profile_id,
            member.cml_realization_profile_id,
        ):
            raise ValueError("realized device does not match the Git profile catalog")
        if (
            hasattr(self, "operational_role")
            and self.operational_role is not member.operational_role
        ):
            raise ValueError("realized device role does not match the Git catalog")
        _validate_profile_pairing(
            automation_profile_id=self.automation_profile_id,
            cml_realization_profile_id=self.cml_realization_profile_id,
        )
        _validate_management_endpoint(
            device_identity=self.device_identity,
            automation_profile_id=self.automation_profile_id,
            endpoint=self.staging_endpoint,
        )
        if self.staging_endpoint.purpose is not ManagementEndpointPurpose.STAGING:
            raise ValueError("staging realized device requires STAGING purpose")
        return self


class StagingRealizationContext(BaseModel):
    """Run-scoped authority that alone may project a STAGING read-only target."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal["1"] = "1"
    environment: Literal[RealizationEnvironment.STAGING] = (
        RealizationEnvironment.STAGING
    )
    staging_run_id: StagingRunID
    cml_lab_id: CmlUUID
    cml_lab_title: NonEmptyString
    lifecycle_state: RealizationLifecycleState
    admitted_at: AwareDatetime
    expires_at: AwareDatetime
    topology_evidence: EvidenceReference
    scope: ProfiledPopulationScope = STAGING_REALIZATION_SCOPE
    devices: tuple[StagingRealizedDevice, ...]

    @model_validator(mode="after")
    def exact_staging_context(self) -> StagingRealizationContext:
        _validate_times(self.admitted_at, self.expires_at)
        _validate_scope(self.devices, self.scope)
        if self.cml_lab_title != f"NCDP Staging {self.staging_run_id}":
            raise ValueError("staging lab title is not bound to its run identity")
        if self.lifecycle_state is RealizationLifecycleState.READY and any(
            device.trust_evidence is None for device in self.devices
        ):
            raise ValueError("READY staging realization requires exact trust evidence")
        return self

    def staging_read_only_target(
        self, profiled_device: ProfiledInventoryDevice
    ) -> ProfileReadOnlyTarget:
        """Project only an exact, fresh, READY STAGING realization binding."""
        now = datetime.now(UTC)
        if self.lifecycle_state is not RealizationLifecycleState.READY:
            raise ProfiledRealizationError("staging realization is not READY")
        if self.admitted_at > now or self.expires_at <= now:
            raise ProfiledRealizationError("staging realization admission is not fresh")
        matches = tuple(
            device
            for device in self.devices
            if device.device_identity == profiled_device.device_identity
        )
        if len(matches) != 1:
            raise ProfiledRealizationError(
                "staging realization does not contain the exact stable device"
            )
        realized = matches[0]
        if (
            realized.logical_name != profiled_device.logical_name
            or realized.automation_profile_id
            is not profiled_device.automation_profile_id
            or realized.cml_realization_profile_id
            is not profiled_device.cml_realization_profile_id
            or realized.staging_endpoint != profiled_device.management_endpoints.staging
        ):
            raise ProfiledRealizationError(
                "staging realization binding does not match profiled inventory"
            )
        endpoint = realized.staging_endpoint.binding.l3_endpoint
        return ProfileReadOnlyTarget(
            logical_name=profiled_device.logical_name,
            host=str(endpoint.address.ip),
            port=endpoint.port,
            expected_hostname=profiled_device.expected_hostname,
            protected_interfaces=tuple(
                interface.name for interface in profiled_device.protected_interfaces
            ),
            automation_profile_id=profiled_device.automation_profile_id,
            network_os=profiled_device.network_os,
        )
