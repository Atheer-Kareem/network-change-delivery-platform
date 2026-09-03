"""Parallel profiled planning contracts for the interface-description write vertical."""

from __future__ import annotations

import hashlib
import ipaddress
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from network_change_delivery.architecture_contracts import (
    AdapterFamily,
    AutomationProfileID,
    CollectorFamily,
    ManagementService,
    NetworkOS,
    NonEmptyString,
    RecoveryFamily,
    RendererFamily,
    Sha256Digest,
    StableInterfaceIdentity,
    TransportFamily,
    get_automation_profile,
)
from network_change_delivery.models import (
    CiscoConfigArtifact,
    CliBoundString,
    DesiredDescription,
    InterfaceDescriptionIntent,
    InterfaceState,
    JunosConfigArtifact,
    render_junos_interface_description,
    validate_ios_description,
)
from network_change_delivery.profile_inventory import (
    ProfileReadOnlyTarget,
    ProfiledInventoryDevice,
    admit_profiled_subject,
)
from network_change_delivery.secrets import CredentialReference, DeviceCredentials


class ProfiledPlanningError(ValueError):
    """Fail-closed profiled planning error without secret or provider content."""


class ProfiledOperation(StrEnum):
    """Closed write-operation vocabulary admitted independently per profile."""

    INTERFACE_DESCRIPTION = "interface_description"


class ProfiledOperationAdmission(BaseModel):
    """One complete profile-local lifecycle contract for a writable operation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["1"] = "1"
    operation: ProfiledOperation
    automation_profile_id: AutomationProfileID
    network_os: NetworkOS
    transport_family: TransportFamily
    adapter_family: AdapterFamily
    renderer_family: RendererFamily
    collector_family: CollectorFamily
    recovery_family: RecoveryFamily
    management_service: ManagementService
    management_port: int = Field(ge=1, le=65535)
    transaction_strategy: Literal["cisco_targeted_inverse", "junos_commit_confirmed"]
    confirmed_timeout_minutes: Literal[5] | None = None
    confirmation_operation: Literal["confirm_previous_commit"] | None = None

    @model_validator(mode="after")
    def exact_profile_lifecycle(self) -> ProfiledOperationAdmission:
        profile = get_automation_profile(self.automation_profile_id)
        if len(profile.readiness_services) != 1:
            raise ValueError("profiled operation management service is ambiguous")
        service = profile.readiness_services[0]
        if (
            profile.network_os is not self.network_os
            or profile.transport_family is not self.transport_family
            or profile.adapter_family is not self.adapter_family
            or profile.renderer_family is not self.renderer_family
            or profile.collector_family is not self.collector_family
            or profile.recovery_family is not self.recovery_family
            or service.service is not self.management_service
            or service.port != self.management_port
        ):
            raise ValueError("profiled operation admission disagrees with profile")
        if self.operation is not ProfiledOperation.INTERFACE_DESCRIPTION:
            raise ValueError("profiled write operation is unsupported")
        if self.recovery_family is RecoveryFamily.CISCO_TARGETED_INVERSE:
            if (
                self.transaction_strategy != "cisco_targeted_inverse"
                or self.confirmed_timeout_minutes is not None
                or self.confirmation_operation is not None
                or self.management_service is not ManagementService.SSH
            ):
                raise ValueError("profiled Cisco operation lifecycle is invalid")
        elif self.recovery_family is RecoveryFamily.JUNOS_COMMIT_CONFIRMED:
            if (
                self.transaction_strategy != "junos_commit_confirmed"
                or self.confirmed_timeout_minutes != 5
                or self.confirmation_operation != "confirm_previous_commit"
                or self.management_service is not ManagementService.NETCONF
            ):
                raise ValueError("profiled Junos operation lifecycle is invalid")
        else:
            raise ValueError("profiled operation recovery family is unsupported")
        return self


def _operation_admission(
    profile_id: AutomationProfileID,
) -> ProfiledOperationAdmission:
    profile = get_automation_profile(profile_id)
    if len(profile.readiness_services) != 1:
        raise RuntimeError("profiled write profile management service is ambiguous")
    service = profile.readiness_services[0]
    if profile.recovery_family is RecoveryFamily.CISCO_TARGETED_INVERSE:
        strategy = "cisco_targeted_inverse"
        timeout = None
        confirmation = None
    elif profile.recovery_family is RecoveryFamily.JUNOS_COMMIT_CONFIRMED:
        strategy = "junos_commit_confirmed"
        timeout = 5
        confirmation = "confirm_previous_commit"
    else:
        raise RuntimeError("profiled write profile recovery family is unsupported")
    return ProfiledOperationAdmission(
        operation=ProfiledOperation.INTERFACE_DESCRIPTION,
        automation_profile_id=profile_id,
        network_os=profile.network_os,
        transport_family=profile.transport_family,
        adapter_family=profile.adapter_family,
        renderer_family=profile.renderer_family,
        collector_family=profile.collector_family,
        recovery_family=profile.recovery_family,
        management_service=service.service,
        management_port=service.port,
        transaction_strategy=strategy,
        confirmed_timeout_minutes=timeout,
        confirmation_operation=confirmation,
    )


PROFILED_OPERATION_ADMISSIONS: Mapping[
    tuple[AutomationProfileID, ProfiledOperation], ProfiledOperationAdmission
] = MappingProxyType(
    {
        (
            AutomationProfileID.CAT8000V_IOSXE,
            ProfiledOperation.INTERFACE_DESCRIPTION,
        ): _operation_admission(AutomationProfileID.CAT8000V_IOSXE),
        (
            AutomationProfileID.VJUNOS_ROUTER,
            ProfiledOperation.INTERFACE_DESCRIPTION,
        ): _operation_admission(AutomationProfileID.VJUNOS_ROUTER),
    }
)

if {
    profile_id
    for profile_id, operation in PROFILED_OPERATION_ADMISSIONS
    if operation is ProfiledOperation.INTERFACE_DESCRIPTION
} != {
    AutomationProfileID.CAT8000V_IOSXE,
    AutomationProfileID.VJUNOS_ROUTER,
}:
    raise RuntimeError("profiled interface-description admission is not exact")


def admit_profiled_operation(
    device: ProfiledInventoryDevice,
    operation: ProfiledOperation,
) -> ProfiledOperationAdmission:
    """Admit an operation only after exact profiled subject validation."""
    admit_profiled_subject(
        device_identity=device.device_identity,
        logical_name=device.logical_name,
        platform_slug=device.platform.slug,
        network_os=device.network_os,
        automation_profile_id=device.automation_profile_id,
    )
    admission = PROFILED_OPERATION_ADMISSIONS.get(
        (device.automation_profile_id, operation)
    )
    if admission is None:
        raise ProfiledPlanningError(
            "profiled target does not admit the requested write operation"
        )
    target = device.live_read_only_target()
    if target.port != admission.management_port:
        raise ProfiledPlanningError("profiled operation endpoint binding is invalid")
    return admission


class ProfiledPlanPreconditions(BaseModel):
    """Relevant observed state frozen into a profiled plan."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    observed_hostname: NonEmptyString
    interface_exists: bool
    interface_protected: bool
    current_description: str | None


class ProfiledDeploymentPlan(BaseModel):
    """Schema-v2 profiled immutable plan; no executor consumes it yet."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["2"] = "2"
    plan_type: Literal["profiled_deployment_plan"] = "profiled_deployment_plan"
    change_id: CliBoundString
    kind: Literal["interface_description"]
    target: CliBoundString
    inventory_source: Literal["netbox"] = "netbox"
    device_identity: NonEmptyString
    interface: StableInterfaceIdentity
    platform_slug: NonEmptyString
    network_os: NetworkOS
    automation_profile_id: AutomationProfileID
    credential_source: Literal["openbao"]
    credential_reference: NonEmptyString
    host: NonEmptyString
    port: int = Field(ge=1, le=65535)
    expected_hostname: NonEmptyString
    current_description: str | None
    desired_description: str
    operation_admission: ProfiledOperationAdmission
    execution_artifact: CiscoConfigArtifact | JunosConfigArtifact
    recovery_artifact: CiscoConfigArtifact | None
    preconditions: ProfiledPlanPreconditions
    created_at: datetime
    digest: Sha256Digest

    @model_validator(mode="after")
    def exact_profiled_plan(self) -> ProfiledDeploymentPlan:
        admit_profiled_subject(
            device_identity=self.device_identity,
            logical_name=self.target,
            platform_slug=self.platform_slug,
            network_os=self.network_os,
            automation_profile_id=self.automation_profile_id,
        )
        if (
            self.interface.device != self.device_identity
            or self.expected_hostname != self.target
            or self.preconditions.observed_hostname != self.expected_hostname
            or not self.preconditions.interface_exists
            or self.preconditions.interface_protected
            or self.preconditions.current_description != self.current_description
        ):
            raise ValueError("profiled plan identity or preconditions are inconsistent")
        try:
            ipaddress.ip_address(self.host)
        except ValueError:
            raise ValueError("profiled plan host must be a numeric address") from None

        expected_admission = PROFILED_OPERATION_ADMISSIONS.get(
            (
                self.automation_profile_id,
                ProfiledOperation.INTERFACE_DESCRIPTION,
            )
        )
        if (
            expected_admission is None
            or self.operation_admission != expected_admission
            or self.port != expected_admission.management_port
        ):
            raise ValueError("profiled plan operation admission is invalid")

        device_id = self.device_identity.rsplit(":", 1)[1]
        expected_credential = f"openbao:kv-v2:ncdp/devices/{device_id}/ssh"
        if self.credential_reference != expected_credential:
            raise ValueError("profiled plan credential binding is invalid")

        DesiredDescription(description=self.desired_description)
        if self.current_description is not None:
            validate_ios_description(self.current_description)

        if expected_admission.renderer_family is RendererFamily.JUNOS_XML:
            expected_execution: CiscoConfigArtifact | JunosConfigArtifact = (
                JunosConfigArtifact(
                    interface=self.interface.name,
                    description=self.desired_description,
                    xml=render_junos_interface_description(
                        self.interface.name, self.desired_description
                    ),
                )
            )
            if (
                self.execution_artifact != expected_execution
                or self.recovery_artifact is not None
            ):
                raise ValueError("profiled Junos artifacts are invalid")
        elif expected_admission.renderer_family is RendererFamily.CISCO_IOS:
            parent = f"interface {self.interface.name}"
            expected_execution = CiscoConfigArtifact(
                parent=parent,
                lines=(f"description {self.desired_description}",),
            )
            recovery_line = (
                f"description {self.current_description}"
                if self.current_description is not None
                else "no description"
            )
            expected_recovery = CiscoConfigArtifact(
                parent=parent,
                lines=(recovery_line,),
            )
            if (
                self.execution_artifact != expected_execution
                or self.recovery_artifact != expected_recovery
            ):
                raise ValueError("profiled Cisco artifacts are invalid")
        else:
            raise ValueError("profiled plan renderer family is unsupported")

        if self.digest != self.calculated_digest():
            raise ValueError("profiled plan digest rejected")
        return self

    def digest_input(self) -> bytes:
        value = self.model_dump(mode="json", exclude={"digest"})
        return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()

    def calculated_digest(self) -> str:
        return f"sha256:{hashlib.sha256(self.digest_input()).hexdigest()}"

    def verify_digest(self) -> bool:
        return self.digest == self.calculated_digest()


@dataclass(frozen=True)
class ProfiledPlanningResult:
    """Either one deployable profiled plan or an already-compliant result."""

    plan: ProfiledDeploymentPlan | None
    state: InterfaceState
    credential: CredentialReference
    message: str


class ProfiledPlanningInventory(Protocol):
    def resolve(self, target: str) -> ProfiledInventoryDevice: ...

    def resolve_interface(
        self,
        device: ProfiledInventoryDevice,
        interface_name: str,
    ) -> StableInterfaceIdentity: ...


class ProfiledPlanningSecretProvider(Protocol):
    def reference(self, device: ProfiledInventoryDevice) -> CredentialReference: ...

    def load(self, device: ProfiledInventoryDevice) -> DeviceCredentials: ...


class ProfiledPlanningCollector(Protocol):
    def collect(
        self,
        target: ProfileReadOnlyTarget,
        credentials: DeviceCredentials,
        interface: str,
    ) -> InterfaceState: ...


def _normalized_interface(name: str) -> str:
    return "".join(name.split()).casefold()


def _assert_profiled_target_binding(
    intent: InterfaceDescriptionIntent,
    device: ProfiledInventoryDevice,
) -> None:
    if device.logical_name != intent.target:
        raise ProfiledPlanningError("profiled planning target identity rejected")


def _assert_profiled_interface_binding(
    intent: InterfaceDescriptionIntent,
    device: ProfiledInventoryDevice,
    interface: StableInterfaceIdentity,
) -> None:
    if interface.device != device.device_identity or interface.name != intent.interface:
        raise ProfiledPlanningError("profiled interface identity rejected")
    requested = _normalized_interface(interface.name)
    protected_ids = {item.interface for item in device.protected_interfaces}
    protected_names = {
        _normalized_interface(item.name) for item in device.protected_interfaces
    }
    if interface.interface in protected_ids or requested in protected_names:
        raise ProfiledPlanningError(
            "requested interface is protected by inventory policy"
        )


def _assert_profiled_safe_state(
    intent: InterfaceDescriptionIntent,
    device: ProfiledInventoryDevice,
    interface: StableInterfaceIdentity,
    state: InterfaceState,
) -> None:
    _assert_profiled_target_binding(intent, device)
    admit_profiled_operation(device, ProfiledOperation.INTERFACE_DESCRIPTION)
    _assert_profiled_interface_binding(intent, device, interface)
    if (
        state.observed_hostname != device.expected_hostname
        or state.interface != intent.interface
        or not state.exists
    ):
        raise ProfiledPlanningError("profiled planning observation identity rejected")
    if state.protected:
        raise ProfiledPlanningError(
            "requested interface is protected by inventory policy"
        )


def _validate_credential_reference(
    device: ProfiledInventoryDevice,
    credential: CredentialReference,
) -> CredentialReference:
    device_id = device.device_identity.rsplit(":", 1)[1]
    expected = f"openbao:kv-v2:ncdp/devices/{device_id}/ssh"
    if credential.source != "openbao" or credential.reference != expected:
        raise ProfiledPlanningError("profiled credential binding rejected")
    return credential


def build_profiled_plan(
    intent: InterfaceDescriptionIntent,
    device: ProfiledInventoryDevice,
    interface: StableInterfaceIdentity,
    state: InterfaceState,
    *,
    credential: CredentialReference,
    created_at: datetime | None = None,
) -> ProfiledDeploymentPlan:
    """Build schema-v2 profiled plan from fresh, already-collected state."""
    admission = admit_profiled_operation(
        device, ProfiledOperation.INTERFACE_DESCRIPTION
    )
    _assert_profiled_safe_state(intent, device, interface, state)
    _validate_credential_reference(device, credential)
    if state.description is not None:
        try:
            DesiredDescription(description=state.description)
        except ValueError as error:
            raise ProfiledPlanningError(
                "observed description is unsafe for targeted recovery"
            ) from error
    if state.description == intent.desired.description:
        raise ProfiledPlanningError("interface is already compliant")

    if admission.renderer_family is RendererFamily.JUNOS_XML:
        execution: CiscoConfigArtifact | JunosConfigArtifact = JunosConfigArtifact(
            interface=interface.name,
            description=intent.desired.description,
            xml=render_junos_interface_description(
                interface.name, intent.desired.description
            ),
        )
        recovery = None
    elif admission.renderer_family is RendererFamily.CISCO_IOS:
        parent = f"interface {interface.name}"
        execution = CiscoConfigArtifact(
            parent=parent,
            lines=(f"description {intent.desired.description}",),
        )
        recovery_line = (
            f"description {state.description}"
            if state.description is not None
            else "no description"
        )
        recovery = CiscoConfigArtifact(parent=parent, lines=(recovery_line,))
    else:
        raise ProfiledPlanningError("profiled renderer family is unsupported")

    target = device.live_read_only_target()
    values = {
        "schema_version": "2",
        "plan_type": "profiled_deployment_plan",
        "change_id": intent.change_id,
        "kind": intent.kind,
        "target": device.logical_name,
        "inventory_source": "netbox",
        "device_identity": device.device_identity,
        "interface": interface,
        "platform_slug": device.platform.slug,
        "network_os": device.network_os,
        "automation_profile_id": device.automation_profile_id,
        "credential_source": credential.source,
        "credential_reference": credential.reference,
        "host": target.host,
        "port": target.port,
        "expected_hostname": device.expected_hostname,
        "current_description": state.description,
        "desired_description": intent.desired.description,
        "operation_admission": admission,
        "execution_artifact": execution,
        "recovery_artifact": recovery,
        "preconditions": ProfiledPlanPreconditions(
            observed_hostname=state.observed_hostname,
            interface_exists=state.exists,
            interface_protected=state.protected,
            current_description=state.description,
        ),
        "created_at": created_at or datetime.now(UTC),
        "digest": "sha256:" + "0" * 64,
    }
    unsigned = ProfiledDeploymentPlan.model_construct(**values)
    values["digest"] = unsigned.calculated_digest()
    return ProfiledDeploymentPlan.model_validate(values)


def plan_profiled_change(
    intent: InterfaceDescriptionIntent,
    inventory: ProfiledPlanningInventory,
    secrets: ProfiledPlanningSecretProvider,
    collector: ProfiledPlanningCollector,
    *,
    created_at: datetime | None = None,
) -> ProfiledPlanningResult:
    """Resolve exact profile identity, then collect without write authority."""
    device = inventory.resolve(intent.target)
    _assert_profiled_target_binding(intent, device)

    # Operation admission deliberately precedes interface lookup, credential routing,
    # secret retrieval, and network transport.
    admit_profiled_operation(device, ProfiledOperation.INTERFACE_DESCRIPTION)

    interface = inventory.resolve_interface(device, intent.interface)
    _assert_profiled_interface_binding(intent, device, interface)

    credential = _validate_credential_reference(device, secrets.reference(device))
    credentials = secrets.load(device)
    state = collector.collect(
        device.live_read_only_target(),
        credentials,
        intent.interface,
    )
    _assert_profiled_safe_state(intent, device, interface, state)

    if state.description == intent.desired.description:
        return ProfiledPlanningResult(
            plan=None,
            state=state,
            credential=credential,
            message="interface is already compliant; no profiled plan produced",
        )

    return ProfiledPlanningResult(
        plan=build_profiled_plan(
            intent,
            device,
            interface,
            state,
            credential=credential,
            created_at=created_at,
        ),
        state=state,
        credential=credential,
        message="profiled immutable plan created",
    )
