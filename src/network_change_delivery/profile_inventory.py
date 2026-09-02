"""Parallel B2 profile-aware, read-only NetBox inventory resolution.

This module does not replace or feed the v1 inventory/deployment path. It binds
reviewed B1 profiles to factual NetBox metadata and exposes only a LIVE
read-only target. STAGING projection remains unavailable until B3 supplies an
explicit realization authority.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType
from typing import Annotated, Literal

import httpx
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    model_validator,
)

from network_change_delivery.architecture_contracts import (
    AutomationProfileID,
    CmlRealizationProfileID,
    ManagementBinding,
    ManagementEndpoint,
    ManagementEndpointPurpose,
    ManagementEndpointSet,
    ManagementL3Endpoint,
    ManagementPhysicalAttachment,
    NetworkOS,
    OperationalRole,
    StableInterfaceIdentity,
    get_automation_profile,
)
from network_change_delivery.inventory import (
    InventoryError,
    NetBoxReadOnlyAPI,
)

Slug = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=100,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
    ),
]
NonEmptyString = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]

PROFILED_INVENTORY_TAG = "ncdp-profiled-inventory"
MANAGEMENT_ATTACHMENT_TAG = "ncdp-management-attachment"
MANAGEMENT_LIVE_TAG = "ncdp-management-live"
MANAGEMENT_STAGING_TAG = "ncdp-management-staging"
PROTECTED_INTERFACE_TAG = "ncdp-protected"


class NetBoxPlatformFact(BaseModel):
    """NetBox-owned factual platform identity frozen into B2 inventory."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    object_id: int = Field(ge=1)
    slug: Slug
    name: NonEmptyString


class NetBoxDeviceTypeFact(BaseModel):
    """NetBox-owned factual device-type identity frozen into B2 inventory."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    object_id: int = Field(ge=1)
    slug: Slug
    model: NonEmptyString


class NetBoxRoleFact(BaseModel):
    """NetBox-owned factual role identity, resolved independently of behavior."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    object_id: int = Field(ge=1)
    slug: Slug
    name: NonEmptyString


class ProfileAdmission(BaseModel):
    """One exact Git-reviewed factual-metadata to behavior admission rule."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    platform_slug: Slug
    device_type_slug: Slug
    automation_profile_id: AutomationProfileID
    cml_realization_profile_id: CmlRealizationProfileID


PLATFORM_NETWORK_OS: Mapping[str, NetworkOS] = MappingProxyType(
    {
        "cisco-ios-xe": NetworkOS.IOSXE,
        "cisco-ios": NetworkOS.IOS,
        "juniper-junos": NetworkOS.JUNOS,
    }
)

OPERATIONAL_ROLE_BY_SLUG: Mapping[str, OperationalRole] = MappingProxyType(
    {role.value: role for role in OperationalRole}
)

_PROFILE_ADMISSIONS = (
    ProfileAdmission(
        platform_slug="cisco-ios-xe",
        device_type_slug="c8000v",
        automation_profile_id=AutomationProfileID.CAT8000V_IOSXE,
        cml_realization_profile_id=CmlRealizationProfileID.CAT8000V_17_18_02,
    ),
    ProfileAdmission(
        platform_slug="cisco-ios",
        device_type_slug="iosv-159-3-m12",
        automation_profile_id=AutomationProfileID.IOSV_159_3_M12,
        cml_realization_profile_id=CmlRealizationProfileID.IOSV_159_3_M12,
    ),
    ProfileAdmission(
        platform_slug="cisco-ios",
        device_type_slug="iosvl2-2020",
        automation_profile_id=AutomationProfileID.IOSVL2_2020,
        cml_realization_profile_id=CmlRealizationProfileID.IOSVL2_2020,
    ),
    ProfileAdmission(
        platform_slug="juniper-junos",
        device_type_slug="vjunos-router-lab",
        automation_profile_id=AutomationProfileID.VJUNOS_ROUTER,
        cml_realization_profile_id=(CmlRealizationProfileID.VJUNOS_ROUTER_23_2R1_15),
    ),
)


def _build_admission_catalog() -> Mapping[tuple[str, str], ProfileAdmission]:
    keys = tuple(
        (rule.platform_slug, rule.device_type_slug) for rule in _PROFILE_ADMISSIONS
    )
    profiles = tuple(rule.automation_profile_id for rule in _PROFILE_ADMISSIONS)
    realizations = tuple(
        rule.cml_realization_profile_id for rule in _PROFILE_ADMISSIONS
    )
    if (
        len(keys) != len(set(keys))
        or len(profiles) != len(set(profiles))
        or len(realizations) != len(set(realizations))
        or set(profiles) != set(AutomationProfileID)
        or set(realizations) != set(CmlRealizationProfileID)
    ):
        raise RuntimeError("profile admission catalog is not exact and closed")
    return MappingProxyType(dict(zip(keys, _PROFILE_ADMISSIONS, strict=True)))


PROFILE_ADMISSION_CATALOG = _build_admission_catalog()


def admit_profile(platform_slug: str, device_type_slug: str) -> ProfileAdmission:
    """Select behavior only from one exact reviewed factual metadata pair."""
    network_os = PLATFORM_NETWORK_OS.get(platform_slug)
    if network_os is None:
        raise InventoryError("NetBox platform is not admitted")
    admission = PROFILE_ADMISSION_CATALOG.get((platform_slug, device_type_slug))
    if admission is None:
        raise InventoryError("NetBox platform and device type are not admitted")
    profile = get_automation_profile(admission.automation_profile_id)
    if profile.network_os is not network_os:
        raise InventoryError("NetBox platform and automation profile NOS mismatch")
    return admission


class ProfiledDeviceName(StrEnum):
    """Exact stable logical names in the Git-approved profiled population."""

    CORE_02 = "core-02"
    EDGE_JUNOS_01 = "edge-junos-01"
    TRANSIT_IOS_01 = "transit-ios-01"
    ACCESS_SW_01 = "access-sw-01"


class _ProfiledPopulationMember(BaseModel):
    """One exact Git-admitted logical identity and NetBox subject binding."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    device_identity: str = Field(pattern=r"^netbox:dcim\.device:[1-9][0-9]*$")
    logical_name: ProfiledDeviceName
    operational_role: OperationalRole
    platform_slug: Slug
    device_type_slug: Slug
    network_os: NetworkOS
    automation_profile_id: AutomationProfileID
    cml_realization_profile_id: CmlRealizationProfileID

    @model_validator(mode="after")
    def exact_profile_admission(self) -> _ProfiledPopulationMember:
        admission = admit_profile(self.platform_slug, self.device_type_slug)
        if (
            PLATFORM_NETWORK_OS[self.platform_slug] is not self.network_os
            or admission.automation_profile_id is not self.automation_profile_id
            or admission.cml_realization_profile_id
            is not self.cml_realization_profile_id
        ):
            raise ValueError("profiled population member admission is inconsistent")
        return self


PROFILED_POPULATION_CATALOG: tuple[_ProfiledPopulationMember, ...] = (
    _ProfiledPopulationMember(
        device_identity="netbox:dcim.device:1",
        logical_name=ProfiledDeviceName.CORE_02,
        operational_role=OperationalRole.CORE,
        platform_slug="cisco-ios-xe",
        device_type_slug="c8000v",
        network_os=NetworkOS.IOSXE,
        automation_profile_id=AutomationProfileID.CAT8000V_IOSXE,
        cml_realization_profile_id=CmlRealizationProfileID.CAT8000V_17_18_02,
    ),
    _ProfiledPopulationMember(
        device_identity="netbox:dcim.device:2",
        logical_name=ProfiledDeviceName.EDGE_JUNOS_01,
        operational_role=OperationalRole.EDGE,
        platform_slug="juniper-junos",
        device_type_slug="vjunos-router-lab",
        network_os=NetworkOS.JUNOS,
        automation_profile_id=AutomationProfileID.VJUNOS_ROUTER,
        cml_realization_profile_id=(CmlRealizationProfileID.VJUNOS_ROUTER_23_2R1_15),
    ),
    _ProfiledPopulationMember(
        device_identity="netbox:dcim.device:8",
        logical_name=ProfiledDeviceName.TRANSIT_IOS_01,
        operational_role=OperationalRole.TRANSIT,
        platform_slug="cisco-ios",
        device_type_slug="iosv-159-3-m12",
        network_os=NetworkOS.IOS,
        automation_profile_id=AutomationProfileID.IOSV_159_3_M12,
        cml_realization_profile_id=CmlRealizationProfileID.IOSV_159_3_M12,
    ),
    _ProfiledPopulationMember(
        device_identity="netbox:dcim.device:9",
        logical_name=ProfiledDeviceName.ACCESS_SW_01,
        operational_role=OperationalRole.ACCESS,
        platform_slug="cisco-ios",
        device_type_slug="iosvl2-2020",
        network_os=NetworkOS.IOS,
        automation_profile_id=AutomationProfileID.IOSVL2_2020,
        cml_realization_profile_id=CmlRealizationProfileID.IOSVL2_2020,
    ),
)

PROFILED_POPULATION_BY_NAME: Mapping[ProfiledDeviceName, _ProfiledPopulationMember] = (
    MappingProxyType(
        {member.logical_name: member for member in PROFILED_POPULATION_CATALOG}
    )
)

if len(PROFILED_POPULATION_BY_NAME) != 4:
    raise RuntimeError("profiled population catalog must contain exactly four names")

PROFILED_POPULATION_IDENTITIES = tuple(
    member.device_identity for member in PROFILED_POPULATION_CATALOG
)

if len(PROFILED_POPULATION_IDENTITIES) != len(set(PROFILED_POPULATION_IDENTITIES)):
    raise RuntimeError("profiled population catalog must contain unique identities")


def _expected_profiled_member(logical_name: str) -> _ProfiledPopulationMember:
    try:
        admitted_name = ProfiledDeviceName(logical_name)
    except ValueError:
        raise InventoryError(
            "NetBox profile target name is not in the Git-owned population"
        ) from None
    return PROFILED_POPULATION_BY_NAME[admitted_name]


class ProfileReadOnlyTarget(BaseModel):
    """Narrow non-secret LIVE target accepted by B2 read-only adapters."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal["1"] = "1"
    logical_name: NonEmptyString
    host: NonEmptyString
    port: int = Field(ge=1, le=65535)
    expected_hostname: NonEmptyString
    protected_interfaces: tuple[NonEmptyString, ...]
    automation_profile_id: AutomationProfileID
    network_os: NetworkOS

    @property
    def name(self) -> str:
        """Satisfy the structural read-only connection-target boundary."""
        return self.logical_name

    @model_validator(mode="after")
    def profile_matches_network_os(self) -> ProfileReadOnlyTarget:
        profile = get_automation_profile(self.automation_profile_id)
        if profile.network_os is not self.network_os:
            raise ValueError("read-only target profile and NOS mismatch")
        if self.port not in {
            expectation.port for expectation in profile.readiness_services
        }:
            raise ValueError("read-only target port is not admitted by profile")
        if len(self.protected_interfaces) != len(set(self.protected_interfaces)):
            raise ValueError("protected interface names must be unique")
        try:
            ipaddress.ip_address(self.host)
        except ValueError:
            raise ValueError(
                "read-only target host must be a numeric address"
            ) from None
        return self


class ProfiledInventoryDevice(BaseModel):
    """Immutable versioned B2 resolution of identity, profile, and management."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal["1"] = "1"
    inventory_source: Literal["netbox"] = "netbox"
    device_identity: Annotated[
        str,
        StringConstraints(pattern=r"^netbox:dcim\.device:[1-9][0-9]*$"),
    ]
    logical_name: NonEmptyString
    expected_hostname: NonEmptyString
    platform: NetBoxPlatformFact
    device_type: NetBoxDeviceTypeFact
    role: NetBoxRoleFact
    operational_role: OperationalRole
    network_os: NetworkOS
    automation_profile_id: AutomationProfileID
    cml_realization_profile_id: CmlRealizationProfileID
    management_endpoints: ManagementEndpointSet
    protected_interfaces: tuple[StableInterfaceIdentity, ...]

    @model_validator(mode="after")
    def validate_resolved_contract(self) -> ProfiledInventoryDevice:
        admission = admit_profile(self.platform.slug, self.device_type.slug)
        if (
            admission.automation_profile_id is not self.automation_profile_id
            or admission.cml_realization_profile_id
            is not self.cml_realization_profile_id
        ):
            raise ValueError(
                "resolved profile admission does not match factual metadata"
            )
        if PLATFORM_NETWORK_OS[self.platform.slug] is not self.network_os:
            raise ValueError("resolved NetBox platform and NOS mismatch")
        if OPERATIONAL_ROLE_BY_SLUG.get(self.role.slug) is not self.operational_role:
            raise ValueError("resolved NetBox role does not match operational role")
        if (
            self.management_endpoints.logical_device != self.device_identity
            or self.management_endpoints.automation_profile_id
            is not self.automation_profile_id
        ):
            raise ValueError(
                "resolved management endpoints do not match device profile"
            )
        identities = tuple(item.interface for item in self.protected_interfaces)
        names = tuple(item.name for item in self.protected_interfaces)
        if (
            not identities
            or len(identities) != len(set(identities))
            or len(names) != len(set(names))
            or any(
                item.device != self.device_identity
                for item in self.protected_interfaces
            )
        ):
            raise ValueError("protected stable interfaces are invalid")
        return self

    def live_read_only_target(self) -> ProfileReadOnlyTarget:
        """Project only LIVE; B2 intentionally has no STAGING projection API."""
        endpoint = self.management_endpoints.live.binding.l3_endpoint
        return ProfileReadOnlyTarget(
            logical_name=self.logical_name,
            host=str(endpoint.address.ip),
            port=endpoint.port,
            expected_hostname=self.expected_hostname,
            protected_interfaces=tuple(item.name for item in self.protected_interfaces),
            automation_profile_id=self.automation_profile_id,
            network_os=self.network_os,
        )

    @property
    def inventory_object_id(self) -> str:
        """Expose stable NetBox identity to structural credential providers."""
        return self.device_identity


def _admit_profiled_device(
    device: ProfiledInventoryDevice,
) -> _ProfiledPopulationMember:
    """Compare resolved NetBox facts with the one Git-owned name binding."""
    member = _expected_profiled_member(device.logical_name)
    if (
        device.device_identity != member.device_identity
        or device.logical_name != member.logical_name
        or device.operational_role is not member.operational_role
        or device.platform.slug != member.platform_slug
        or device.device_type.slug != member.device_type_slug
        or device.network_os is not member.network_os
        or device.automation_profile_id is not member.automation_profile_id
        or device.cml_realization_profile_id is not member.cml_realization_profile_id
    ):
        raise InventoryError(
            "NetBox profile target does not match its Git-owned population member"
        )
    return member


def admit_profiled_subject(
    *,
    device_identity: str,
    logical_name: str,
    platform_slug: str,
    network_os: NetworkOS,
    automation_profile_id: AutomationProfileID,
) -> None:
    """Fail closed unless one target is the exact admitted profiled subject."""
    member = _expected_profiled_member(logical_name)
    if (
        device_identity != member.device_identity
        or platform_slug != member.platform_slug
        or network_os is not member.network_os
        or automation_profile_id is not member.automation_profile_id
    ):
        raise InventoryError("profiled target does not match its Git-owned subject")


class ProfiledInventoryPopulation(BaseModel):
    """Immutable deterministic resolution of the exact four-member population."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal["1"] = "1"
    population_tag: Literal["ncdp-profiled-inventory"] = PROFILED_INVENTORY_TAG
    devices: tuple[ProfiledInventoryDevice, ...]

    @model_validator(mode="after")
    def exact_git_approved_population(self) -> ProfiledInventoryPopulation:
        expected_names = tuple(
            member.logical_name for member in PROFILED_POPULATION_CATALOG
        )
        names = tuple(device.logical_name for device in self.devices)
        identities = tuple(device.device_identity for device in self.devices)
        if names != expected_names:
            raise ValueError("profiled inventory population names are not exact")
        if identities != PROFILED_POPULATION_IDENTITIES:
            raise ValueError("profiled inventory population identities are not exact")
        if len(identities) != len(set(identities)):
            raise ValueError("profiled inventory population identities are duplicated")
        for device in self.devices:
            _admit_profiled_device(device)
        return self


def _positive_id(value: object, noun: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise InventoryError(f"NetBox {noun} identity is invalid")
    return value


def _required_string(value: object, noun: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InventoryError(f"NetBox {noun} is invalid")
    return value.strip()


def _active(value: object) -> bool:
    return isinstance(value, dict) and value.get("value") == "active"


def _platform_fact(value: object) -> NetBoxPlatformFact:
    if not isinstance(value, dict):
        raise InventoryError("NetBox platform is missing or invalid")
    try:
        return NetBoxPlatformFact(
            object_id=_positive_id(value.get("id"), "platform"),
            slug=_required_string(value.get("slug"), "platform slug"),
            name=_required_string(value.get("name"), "platform name"),
        )
    except ValueError:
        raise InventoryError("NetBox platform is missing or invalid") from None


def _device_type_fact(value: object) -> NetBoxDeviceTypeFact:
    if not isinstance(value, dict):
        raise InventoryError("NetBox device type is missing or invalid")
    try:
        return NetBoxDeviceTypeFact(
            object_id=_positive_id(value.get("id"), "device type"),
            slug=_required_string(value.get("slug"), "device type slug"),
            model=_required_string(value.get("model"), "device type model"),
        )
    except ValueError:
        raise InventoryError("NetBox device type is missing or invalid") from None


def _role_fact(value: object) -> NetBoxRoleFact:
    if not isinstance(value, dict):
        raise InventoryError("NetBox operational role is missing or invalid")
    try:
        return NetBoxRoleFact(
            object_id=_positive_id(value.get("id"), "role"),
            slug=_required_string(value.get("slug"), "role slug"),
            name=_required_string(value.get("name"), "role name"),
        )
    except ValueError:
        raise InventoryError("NetBox operational role is missing or invalid") from None


class NetBoxProfileInventoryProvider(NetBoxReadOnlyAPI):
    """Resolve full B2 profile identity through NetBox GET requests only."""

    _DEVICE_PATH = "/api/dcim/devices/"
    _INTERFACE_PATH = "/api/dcim/interfaces/"
    _IP_ADDRESS_PATH = "/api/ipam/ip-addresses/"

    def __init__(
        self,
        url: str | None = None,
        token: str | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        super().__init__(url, token, transport=transport)

    def resolve(self, target: str) -> ProfiledInventoryDevice:
        """Resolve one exact Git-owned member from independently factual metadata."""
        _expected_profiled_member(target)
        payload = self._get(
            self._DEVICE_PATH,
            params={
                "name": target,
                "tag": PROFILED_INVENTORY_TAG,
                "limit": 2,
            },
        )
        candidates = self._results(payload)
        exact = [item for item in candidates if item.get("name") == target]
        if not exact:
            raise InventoryError("NetBox profile target not found")
        if len(exact) != 1 or payload.get("count") != 1:
            raise InventoryError("NetBox profile target is ambiguous")
        resolved = self._resolve_device_payload(exact[0])
        _admit_profiled_device(resolved)
        return resolved

    def resolve_profiled_population(self) -> ProfiledInventoryPopulation:
        """Resolve only the exact four Git-approved profiled inventory members."""
        payloads = self._get_all(
            self._DEVICE_PATH,
            params={
                "tag": PROFILED_INVENTORY_TAG,
                "status": "active",
                "ordering": "id",
            },
        )
        if len(payloads) != len(PROFILED_POPULATION_CATALOG):
            raise InventoryError(
                "NetBox profiled population must contain exactly four devices"
            )
        by_name: dict[str, dict[str, object]] = {}
        identities: set[int] = set()
        for device in payloads:
            device_id = _positive_id(device.get("id"), "device")
            name = _required_string(device.get("name"), "device name")
            if device_id in identities:
                raise InventoryError(
                    "NetBox profiled population contains duplicate stable identity"
                )
            if name in by_name:
                raise InventoryError(
                    "NetBox profiled population contains duplicate logical name"
                )
            identities.add(device_id)
            by_name[name] = device
        expected_names = {member.logical_name for member in PROFILED_POPULATION_CATALOG}
        if set(by_name) != expected_names:
            raise InventoryError("NetBox profiled population names are not exact")
        try:
            return ProfiledInventoryPopulation(
                devices=tuple(
                    self._resolve_device_payload(by_name[member.logical_name])
                    for member in PROFILED_POPULATION_CATALOG
                )
            )
        except ValidationError:
            raise InventoryError(
                "NetBox profiled population does not match the Git catalog"
            ) from None

    def _resolve_device_payload(
        self, device: dict[str, object]
    ) -> ProfiledInventoryDevice:
        """Resolve one already-selected factual device payload through GET only."""
        if not _active(device.get("status")):
            raise InventoryError("NetBox profile target is inactive")
        if PROFILED_INVENTORY_TAG not in self._tag_slugs(device.get("tags")):
            raise InventoryError(
                "NetBox profile target is missing ncdp-profiled-inventory tag"
            )

        device_id = _positive_id(device.get("id"), "device")
        logical_name = _required_string(device.get("name"), "device name")
        platform = _platform_fact(device.get("platform"))
        device_type = _device_type_fact(device.get("device_type"))
        role = _role_fact(device.get("role"))
        admission = admit_profile(platform.slug, device_type.slug)
        network_os = PLATFORM_NETWORK_OS[platform.slug]
        operational_role = OPERATIONAL_ROLE_BY_SLUG.get(role.slug)
        if operational_role is None:
            raise InventoryError("NetBox operational role slug is not admitted")

        device_identity = f"netbox:dcim.device:{device_id}"
        interfaces = self._get_all(
            self._INTERFACE_PATH,
            params={"device_id": device_id, "ordering": "id"},
        )
        by_interface_id: dict[int, tuple[StableInterfaceIdentity, set[str]]] = {}
        for item in interfaces:
            interface_id = _positive_id(item.get("id"), "interface")
            name = _required_string(item.get("name"), "interface name")
            owner = item.get("device")
            if (
                not isinstance(owner, dict)
                or owner.get("id") != device_id
                or owner.get("name") != logical_name
            ):
                raise InventoryError("NetBox interface belongs to another device")
            if interface_id in by_interface_id:
                raise InventoryError("NetBox interface identity is duplicated")
            by_interface_id[interface_id] = (
                StableInterfaceIdentity(
                    device=device_identity,
                    interface=f"netbox:dcim.interface:{interface_id}",
                    name=name,
                ),
                self._tag_slugs(item.get("tags")),
            )
        attachments = [
            identity
            for identity, tags in by_interface_id.values()
            if MANAGEMENT_ATTACHMENT_TAG in tags
        ]
        if len(attachments) != 1:
            raise InventoryError(
                "NetBox requires exactly one physical management attachment"
            )
        protected = tuple(
            identity
            for identity, tags in by_interface_id.values()
            if PROTECTED_INTERFACE_TAG in tags
        )
        protected_ids = {identity.interface for identity in protected}
        attachment = attachments[0]
        if attachment.interface not in protected_ids:
            raise InventoryError("physical management attachment is not protected")

        ip_objects = self._get_all(
            self._IP_ADDRESS_PATH,
            params={"device_id": device_id, "ordering": "id"},
        )
        live_candidates = [
            item
            for item in ip_objects
            if MANAGEMENT_LIVE_TAG in self._tag_slugs(item.get("tags"))
        ]
        staging_candidates = [
            item
            for item in ip_objects
            if MANAGEMENT_STAGING_TAG in self._tag_slugs(item.get("tags"))
        ]
        if len(live_candidates) != 1:
            raise InventoryError("NetBox requires exactly one LIVE management IP")
        if len(staging_candidates) != 1:
            raise InventoryError("NetBox requires exactly one STAGING management IP")

        profile = get_automation_profile(admission.automation_profile_id)
        if profile.network_os is not network_os:
            raise InventoryError("NetBox platform and automation profile NOS mismatch")
        if len(profile.readiness_services) != 1:
            raise InventoryError("automation profile management service is ambiguous")
        service = profile.readiness_services[0]

        def binding(ip_object: dict[str, object]) -> ManagementBinding:
            if not _active(ip_object.get("status")):
                raise InventoryError("NetBox management IP is inactive")
            ip_id = _positive_id(ip_object.get("id"), "IP address")
            address = _required_string(ip_object.get("address"), "IP address")
            try:
                parsed_address = ipaddress.IPv4Interface(address)
            except ValueError:
                raise InventoryError("NetBox management IPv4 is invalid") from None
            if ip_object.get("assigned_object_type") != "dcim.interface":
                raise InventoryError("NetBox management IP is not interface-assigned")
            assigned = ip_object.get("assigned_object")
            if not isinstance(assigned, dict):
                raise InventoryError("NetBox management IP assignment is invalid")
            assigned_id = _positive_id(assigned.get("id"), "management L3 interface")
            owner = assigned.get("device")
            if (
                not isinstance(owner, dict)
                or owner.get("id") != device_id
                or owner.get("name") != logical_name
            ):
                raise InventoryError("NetBox management IP belongs to another device")
            entry = by_interface_id.get(assigned_id)
            if entry is None or entry[0].name != assigned.get("name"):
                raise InventoryError("NetBox management IP interface is inconsistent")
            l3_interface = entry[0]
            if l3_interface.interface not in protected_ids:
                raise InventoryError("management L3 interface is not protected")
            return ManagementBinding(
                physical_attachment=ManagementPhysicalAttachment(interface=attachment),
                l3_endpoint=ManagementL3Endpoint(
                    interface=l3_interface,
                    ip_address_identity=f"netbox:ipam.ipaddress:{ip_id}",
                    address=str(parsed_address),
                    service=service.service,
                    port=service.port,
                ),
            )

        live = live_candidates[0]
        staging = staging_candidates[0]
        primary = device.get("primary_ip4")
        if not isinstance(primary, dict):
            raise InventoryError("NetBox primary IPv4 is missing or invalid")
        primary_id = _positive_id(primary.get("id"), "primary IPv4")
        primary_address = _required_string(
            primary.get("address"), "primary IPv4 address"
        )
        if live.get("id") != primary_id or live.get("address") != primary_address:
            raise InventoryError(
                "LIVE management IP does not exactly match primary IPv4"
            )
        if staging.get("id") == primary_id or staging.get("address") == primary_address:
            raise InventoryError("STAGING management IP cannot be primary IPv4")

        try:
            endpoints = ManagementEndpointSet(
                logical_device=device_identity,
                automation_profile_id=admission.automation_profile_id,
                live=ManagementEndpoint(
                    purpose=ManagementEndpointPurpose.LIVE,
                    binding=binding(live),
                ),
                staging=ManagementEndpoint(
                    purpose=ManagementEndpointPurpose.STAGING,
                    binding=binding(staging),
                ),
            )
            return ProfiledInventoryDevice(
                device_identity=device_identity,
                logical_name=logical_name,
                expected_hostname=logical_name,
                platform=platform,
                device_type=device_type,
                role=role,
                operational_role=operational_role,
                network_os=network_os,
                automation_profile_id=admission.automation_profile_id,
                cml_realization_profile_id=admission.cml_realization_profile_id,
                management_endpoints=endpoints,
                protected_interfaces=protected,
            )
        except ValidationError:
            raise InventoryError(
                "NetBox profile inventory contract is inconsistent"
            ) from None
