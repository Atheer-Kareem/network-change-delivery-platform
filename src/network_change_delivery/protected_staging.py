"""Checkout-independent authority contracts for protected CML staging."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
import ssl
import stat
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from typing import ClassVar, Literal, Protocol
from urllib.parse import urlparse
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator

from network_change_delivery.buildkite_identity import (
    BuildkiteOIDCJWT,
    read_buildkite_oidc_jwt,
)
from network_change_delivery.inventory import InventoryError
from network_change_delivery.secrets import (
    CredentialReference,
    SecretError,
    validate_openbao_url,
)

EXPECTED_TERRAFORM_ADDRESSES = frozenset(
    {
        "cml2_lab.staging",
        "module.managed_pair.cml2_node.system_bridge",
        "module.managed_pair.cml2_node.management_switch",
        "module.managed_pair.cml2_node.cisco",
        "module.managed_pair.cml2_node.junos",
        "module.managed_pair.cml2_link.system_bridge_management",
        "module.managed_pair.cml2_link.management_cisco",
        "module.managed_pair.cml2_link.management_junos",
        "module.managed_pair.cml2_link.cisco_junos",
        "module.managed_pair.cml2_lifecycle.managed_pair",
    }
)
LIFECYCLE_ADDRESS = "module.managed_pair.cml2_lifecycle.managed_pair"
BROWNFIELD_LAB_UUID = "09605569-0468-4fc4-8684-beb5a1342b9c"
LIVE_DENY_IDS = frozenset({1, 2, 3})
LIVE_DENY_IPS = frozenset({"192.168.4.14", "192.168.4.15", "192.168.4.20"})
STAGING_IDS = frozenset({6, 7})
_SHA1 = re.compile(r"[0-9a-f]{40}")
_SHA256 = re.compile(r"[0-9a-f]{64}")


class ProtectedStagingError(RuntimeError):
    """Sanitized failure at the protected staging boundary."""


class StagingTargetAuthority(BaseModel):
    """One exact NetBox staging identity and its canonical live homolog."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    device_id: int
    name: str
    site_id: int
    device_type_id: int
    environment: Literal["staging"]
    status: Literal["staged"]
    role_slug: Literal["ncdp-staging"]
    platform_slug: Literal["cisco-ios-xe", "juniper-junos"]
    management_interface: str
    management_interface_id: int
    management_interface_type: Literal["1000base-t"]
    management_interface_enabled: Literal[True]
    management_interface_mgmt_only: Literal[False]
    management_ip_address_id: int
    management_cidr: str
    management_ip: str
    live_homolog_id: int
    live_homolog_name: str
    live_primary_cidr: str
    openbao_role: str
    credential_reference: str


class CMLAuthority(BaseModel):
    """Exact controller and realization exclusions for staging."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    controller_identity: str = Field(min_length=1, max_length=255)
    controller_url: str
    ca_pem_sha256: str
    connector_label: Literal["System Bridge"] = "System Bridge"
    cat8000v_image: Literal["cat8000v-17-18-02"] = "cat8000v-17-18-02"
    vjunos_image: Literal["vjunos-router-23-2r1-15"] = "vjunos-router-23-2r1-15"
    denied_lab_uuids: tuple[str, ...] = (BROWNFIELD_LAB_UUID,)

    @model_validator(mode="after")
    def validate_controller(self) -> CMLAuthority:
        parsed = urlparse(self.controller_url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError("protected CML controller URL is invalid")
        if (
            parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise ValueError("protected CML controller URL is invalid")
        if self.denied_lab_uuids != (BROWNFIELD_LAB_UUID,):
            raise ValueError("brownfield CML denial authority changed")
        if not _SHA256.fullmatch(self.ca_pem_sha256):
            raise ValueError("protected CML CA digest is invalid")
        return self


class ServiceIdentityAuthority(BaseModel):
    """Exact non-root principal permitted to execute protected staging."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    service_uid: int = Field(gt=0)
    service_gid: int = Field(gt=0)
    immutable_owner_uid: Literal[0] = 0
    supplementary_gids: tuple[int, ...] = ()

    @model_validator(mode="after")
    def validate_identity(self) -> ServiceIdentityAuthority:
        if self.service_uid == 501 or self.service_gid == 501:
            raise ValueError("protected service identity overlaps validation")
        if self.supplementary_gids:
            raise ValueError("protected service supplementary groups are forbidden")
        return self


class ExecutionToolAuthority(BaseModel):
    """Digest and version authority for one protected execution tool."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    path: str
    sha256: str
    version: str = Field(min_length=1, max_length=255)
    system_protected: bool = False

    @model_validator(mode="after")
    def validate_tool(self) -> ExecutionToolAuthority:
        if not Path(self.path).is_absolute() or not _SHA256.fullmatch(self.sha256):
            raise ValueError("protected execution tool authority is invalid")
        return self


class NativeDependencyAuthority(BaseModel):
    """One exact root-owned native dependency tree admitted at installation."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    name: Literal["libssh", "openssl"]
    version: str = Field(min_length=1, max_length=255)
    root: str
    inventory_sha256: str

    @model_validator(mode="after")
    def validate_native_dependency(self) -> NativeDependencyAuthority:
        if not Path(self.root).is_absolute() or not _SHA256.fullmatch(
            self.inventory_sha256
        ):
            raise ValueError("protected native dependency authority is invalid")
        return self


class ProtectedStagingManifest(BaseModel):
    """Installed, immutable staging authority; checkout copies are not authority."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal[4] = 4
    service_identity: ServiceIdentityAuthority
    buildkite_pipeline_id: UUID
    source_commit: str
    netbox_url: str
    openbao_url: str
    source_bundle_digest: str
    source_inventory_sha256: str
    runtime_inventory_sha256: str
    runtime_digest: str
    python_version: Literal["3.12"] = "3.12"
    python_interpreter_path: str
    python_interpreter_sha256: str
    project_wheel_sha256: str
    production_requirements_sha256: str
    uv: ExecutionToolAuthority
    buildkite_agent: ExecutionToolAuthority
    terraform: ExecutionToolAuthority
    openssl: ExecutionToolAuthority
    ssh_keyscan: ExecutionToolAuthority
    ssh_keygen: ExecutionToolAuthority
    ansible_collections_root: str
    ansible_collections: dict[str, str]
    ansible_inventory_sha256: str
    native_dependencies: tuple[NativeDependencyAuthority, ...]
    protected_native_files: dict[str, str]
    native_dependency_admission_sha256: str
    build_sdk_identity: str
    controller_entrypoint: Literal["bin/ncdp-protected-staging-controller"] = (
        "bin/ncdp-protected-staging-controller"
    )
    controller_artifact_digest: str
    file_digests: dict[str, str]
    cisco: StagingTargetAuthority
    junos: StagingTargetAuthority
    live_deny_device_ids: tuple[int, ...]
    live_deny_management_ips: tuple[str, ...]
    cml: CMLAuthority
    terraform_addresses: tuple[str, ...]
    lifecycle_update_address: str

    @property
    def bundle_digest(self) -> str:
        """Compatibility name for run metadata; authority is the source digest."""
        return self.source_bundle_digest

    _EXPECTED: ClassVar[dict[str, dict[str, object]]] = {
        "cisco": {
            "device_id": 6,
            "name": "stg-core-02",
            "site_id": 1,
            "device_type_id": 1,
            "platform_slug": "cisco-ios-xe",
            "management_interface": "GigabitEthernet1",
            "management_interface_id": 9,
            "management_interface_type": "1000base-t",
            "management_interface_enabled": True,
            "management_interface_mgmt_only": False,
            "management_ip_address_id": 9,
            "management_cidr": "192.168.4.30/24",
            "management_ip": "192.168.4.30",
            "live_homolog_id": 1,
            "live_homolog_name": "core-02",
            "live_primary_cidr": "192.168.4.14/24",
            "openbao_role": "ncdp-buildkite-staging-device-6",
            "credential_reference": "openbao:kv-v2:ncdp/devices/6/ssh",
        },
        "junos": {
            "device_id": 7,
            "name": "stg-edge-junos-01",
            "site_id": 1,
            "device_type_id": 2,
            "platform_slug": "juniper-junos",
            "management_interface": "fxp0",
            "management_interface_id": 10,
            "management_interface_type": "1000base-t",
            "management_interface_enabled": True,
            "management_interface_mgmt_only": False,
            "management_ip_address_id": 10,
            "management_cidr": "192.168.4.31/24",
            "management_ip": "192.168.4.31",
            "live_homolog_id": 2,
            "live_homolog_name": "edge-junos-01",
            "live_primary_cidr": "192.168.4.20/24",
            "openbao_role": "ncdp-buildkite-staging-device-7",
            "credential_reference": "openbao:kv-v2:ncdp/devices/7/ssh",
        },
    }

    @model_validator(mode="after")
    def exact_authority(self) -> ProtectedStagingManifest:
        try:
            if NetBoxURL.validate(self.netbox_url) != self.netbox_url.rstrip("/"):
                raise ValueError("protected NetBox endpoint is invalid")
            if validate_openbao_url(self.openbao_url) != self.openbao_url.rstrip("/"):
                raise ValueError("protected OpenBao endpoint is invalid")
        except (InventoryError, SecretError):
            raise ValueError("protected endpoint authority is invalid") from None
        if not _SHA1.fullmatch(self.source_commit):
            raise ValueError("protected source commit is invalid")
        for digest in (
            self.source_bundle_digest,
            self.source_inventory_sha256,
            self.runtime_inventory_sha256,
            self.runtime_digest,
            self.project_wheel_sha256,
            self.production_requirements_sha256,
            self.ansible_inventory_sha256,
            self.native_dependency_admission_sha256,
            self.python_interpreter_sha256,
            self.controller_artifact_digest,
            *self.file_digests.values(),
            *self.protected_native_files.values(),
        ):
            if not _SHA256.fullmatch(digest):
                raise ValueError("protected bundle digest is invalid")
        if not self.file_digests or any(
            Path(name).is_absolute() or ".." in Path(name).parts
            for name in self.file_digests
        ):
            raise ValueError("protected file inventory is invalid")
        if not Path(self.python_interpreter_path).is_absolute():
            raise ValueError("protected Python interpreter authority is invalid")
        expected_collections = {
            "ansible.netcommon": "8.6.0",
            "ansible.utils": "6.1.0",
            "cisco.ios": "11.4.2",
        }
        if (
            not Path(self.ansible_collections_root).is_absolute()
            or self.ansible_collections != expected_collections
            or {dependency.name for dependency in self.native_dependencies}
            != {"libssh", "openssl"}
            or not self.protected_native_files
            or any(not Path(path).is_absolute() for path in self.protected_native_files)
            or not self.build_sdk_identity
        ):
            raise ValueError("protected runtime dependency authority changed")
        controller_path = "src/network_change_delivery/protected_staging_controller.py"
        if self.file_digests.get(controller_path) != self.controller_artifact_digest:
            raise ValueError("protected controller artifact digest changed")
        for role in ("cisco", "junos"):
            target = getattr(self, role)
            expected = self._EXPECTED[role]
            if any(
                getattr(target, field) != value for field, value in expected.items()
            ):
                raise ValueError("protected staging identity changed")
        if self.cisco.device_id == self.junos.device_id:
            raise ValueError("duplicate staging identity")
        if {self.cisco.device_id, self.junos.device_id} & set(
            self.live_deny_device_ids
        ):
            raise ValueError("staging and live identities overlap")
        if tuple(sorted(self.live_deny_device_ids)) != (1, 2, 3):
            raise ValueError("live device denial authority changed")
        try:
            staging_ips = {
                str(ipaddress.IPv4Address(self.cisco.management_ip)),
                str(ipaddress.IPv4Address(self.junos.management_ip)),
            }
            denied_ips = {
                str(ipaddress.IPv4Address(value))
                for value in self.live_deny_management_ips
            }
        except ValueError:
            raise ValueError("protected management address is invalid") from None
        if denied_ips != LIVE_DENY_IPS or staging_ips & denied_ips:
            raise ValueError("staging and live management authority overlaps")
        if set(self.terraform_addresses) != EXPECTED_TERRAFORM_ADDRESSES or len(
            self.terraform_addresses
        ) != len(EXPECTED_TERRAFORM_ADDRESSES):
            raise ValueError("protected Terraform graph changed")
        if self.lifecycle_update_address != LIFECYCLE_ADDRESS:
            raise ValueError("protected Terraform lifecycle authority changed")
        return self

    @property
    def digest(self) -> str:
        payload = json.dumps(
            self.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        ).encode()
        return hashlib.sha256(payload).hexdigest()


class ProtectedStagingTarget(BaseModel):
    """Read-only, independently admitted staging target."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    device_id: Literal[6, 7]
    name: str
    host: str
    platform: Literal["cisco_iosxe", "junos"]
    management_interface: str
    interface_id: int
    management_cidr: str
    ip_address_id: int
    live_homolog_id: Literal[1, 2]
    credential_reference: str
    openbao_role: str


class ProtectedStagingInventoryResolver:
    """Resolve exact staging IDs without weakening the live inventory provider."""

    _DEVICE_PATH = "/api/dcim/devices/{device_id}/"
    _INTERFACE_PATH = "/api/dcim/interfaces/"
    _IP_ADDRESS_PATH = "/api/ipam/ip-addresses/{ip_address_id}/"

    def __init__(
        self,
        manifest: ProtectedStagingManifest,
        staging_reader_token: str,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not staging_reader_token:
            raise InventoryError("protected NetBox staging reader missing")
        self._manifest = manifest
        self._client = httpx.Client(
            base_url=manifest.netbox_url,
            headers={"Authorization": f"Bearer {staging_reader_token}"},
            timeout=httpx.Timeout(5.0, connect=3.0),
            follow_redirects=False,
            verify=True,
            trust_env=False,
            transport=transport,
        )

    def resolve(self) -> tuple[ProtectedStagingTarget, ProtectedStagingTarget]:
        live = {
            target.live_homolog_id: self._device(target.live_homolog_id)
            for target in (self._manifest.cisco, self._manifest.junos)
        }
        for authority in (self._manifest.cisco, self._manifest.junos):
            self._validate_unique_reverse_homolog(authority)
        targets = tuple(
            self._resolve_target(authority, live[authority.live_homolog_id])
            for authority in (self._manifest.cisco, self._manifest.junos)
        )
        if len({target.live_homolog_id for target in targets}) != 2:
            raise InventoryError("protected staging homolog mapping is ambiguous")
        return targets

    def _validate_unique_reverse_homolog(
        self, authority: StagingTargetAuthority
    ) -> None:
        response = self._client.get(
            self._DEVICE_PATH.removesuffix("{device_id}/"),
            params={
                "cf_ncdp_live_homolog": authority.live_homolog_id,
                "limit": 2,
            },
        )
        if response.status_code != 200:
            raise InventoryError("protected staging reverse homolog unavailable")
        try:
            payload = response.json()
        except ValueError:
            raise InventoryError(
                "protected staging reverse homolog response invalid"
            ) from None
        if not isinstance(payload, dict):
            raise InventoryError("protected staging reverse homolog response invalid")
        results = payload.get("results")
        if (
            payload.get("count") != 1
            or payload.get("next") is not None
            or not isinstance(results, list)
            or len(results) != 1
            or not isinstance(results[0], dict)
            or results[0].get("id") != authority.device_id
        ):
            raise InventoryError("protected staging reverse homolog is ambiguous")

    def _device(self, device_id: int) -> dict[str, object]:
        response = self._client.get(self._DEVICE_PATH.format(device_id=device_id))
        if response.status_code in {401, 403}:
            raise InventoryError("protected NetBox reader unauthorized")
        if response.status_code != 200:
            raise InventoryError("protected NetBox device identity unavailable")
        try:
            payload = response.json()
        except ValueError:
            raise InventoryError("protected NetBox response invalid") from None
        if not isinstance(payload, dict) or payload.get("id") != device_id:
            raise InventoryError("protected NetBox device identity changed")
        return payload

    @staticmethod
    def _nested_value(payload: Mapping[str, object], field: str, key: str) -> object:
        value = payload.get(field)
        if not isinstance(value, Mapping):
            raise InventoryError(f"protected NetBox {field} invalid")
        return value.get(key)

    @staticmethod
    def _custom_fields(payload: Mapping[str, object]) -> Mapping[str, object]:
        fields = payload.get("custom_fields")
        if not isinstance(fields, Mapping) or not {
            "ncdp_environment",
            "ncdp_live_homolog",
        }.issubset(fields):
            raise InventoryError("protected NetBox custom fields invalid")
        return fields

    @staticmethod
    def _homolog_id(value: object) -> int:
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        if isinstance(value, Mapping) and set(value) >= {"id"}:
            object_id = value.get("id")
            if isinstance(object_id, int) and not isinstance(object_id, bool):
                return object_id
        raise InventoryError("protected NetBox homolog representation invalid")

    def _resolve_target(
        self,
        authority: StagingTargetAuthority,
        live: Mapping[str, object],
    ) -> ProtectedStagingTarget:
        device = self._device(authority.device_id)
        if device.get("name") != authority.name:
            raise InventoryError("protected staging device name changed")
        if self._nested_value(device, "status", "value") != authority.status:
            raise InventoryError("protected staging device status changed")
        if self._nested_value(device, "role", "slug") != authority.role_slug:
            raise InventoryError("protected staging device role changed")
        if self._nested_value(device, "platform", "slug") != authority.platform_slug:
            raise InventoryError("protected staging device platform changed")
        if self._nested_value(device, "site", "id") != authority.site_id:
            raise InventoryError("protected staging device site changed")
        if self._nested_value(device, "device_type", "id") != authority.device_type_id:
            raise InventoryError("protected staging device type changed")
        tags = device.get("tags")
        if not isinstance(tags, list) or tags:
            raise InventoryError("protected staging device tags invalid")
        fields = self._custom_fields(device)
        if fields.get("ncdp_environment") != authority.environment:
            raise InventoryError("protected staging environment changed")
        homolog_id = self._homolog_id(fields.get("ncdp_live_homolog"))
        if homolog_id != authority.live_homolog_id or homolog_id == authority.device_id:
            raise InventoryError("protected staging homolog changed")
        live_fields = self._custom_fields(live)
        if (
            live.get("name") != authority.live_homolog_name
            or self._nested_value(live, "status", "value") != "active"
            or self._nested_value(live, "platform", "slug") != authority.platform_slug
            or self._nested_value(live, "device_type", "id") != authority.device_type_id
            or self._nested_value(live, "primary_ip4", "address")
            != authority.live_primary_cidr
            or live_fields.get("ncdp_environment") != "live"
            or live_fields.get("ncdp_live_homolog") is not None
        ):
            raise InventoryError("protected live homolog authority changed")
        primary = self._nested_value(device, "primary_ip4", "address")
        primary_id = self._nested_value(device, "primary_ip4", "id")
        try:
            host = str(ipaddress.IPv4Interface(str(primary)).ip)
        except ValueError:
            raise InventoryError("protected staging primary IPv4 invalid") from None
        if (
            host != authority.management_ip
            or str(primary) != authority.management_cidr
            or primary_id != authority.management_ip_address_id
            or host in LIVE_DENY_IPS
        ):
            raise InventoryError("protected staging management address changed")
        response = self._client.get(
            self._INTERFACE_PATH,
            params={
                "device_id": authority.device_id,
                "name": authority.management_interface,
                "limit": 2,
            },
        )
        try:
            result = response.json()
        except ValueError:
            raise InventoryError(
                "protected staging interface response invalid"
            ) from None
        if not isinstance(result, dict):
            raise InventoryError("protected staging interface response invalid")
        interfaces = result.get("results")
        if (
            response.status_code != 200
            or result.get("count") != 1
            or result.get("next") is not None
            or not isinstance(interfaces, list)
            or len(interfaces) != 1
            or not isinstance(interfaces[0], dict)
            or interfaces[0].get("name") != authority.management_interface
            or interfaces[0].get("id") != authority.management_interface_id
            or self._nested_value(interfaces[0], "type", "value")
            != authority.management_interface_type
            or interfaces[0].get("enabled") is not True
            or interfaces[0].get("mgmt_only") is not False
            or interfaces[0].get("tags") != []
        ):
            raise InventoryError("protected staging management interface ambiguous")
        interface_id = interfaces[0].get("id")
        if not isinstance(interface_id, int) or isinstance(interface_id, bool):
            raise InventoryError("protected staging interface identity invalid")
        interface_device = interfaces[0].get("device")
        if interface_device is not None and (
            not isinstance(interface_device, Mapping)
            or interface_device.get("id") != authority.device_id
        ):
            raise InventoryError("protected staging interface device changed")
        ip_response = self._client.get(
            self._IP_ADDRESS_PATH.format(
                ip_address_id=authority.management_ip_address_id
            )
        )
        if ip_response.status_code != 200:
            raise InventoryError("protected staging IP address unavailable")
        try:
            ip_payload = ip_response.json()
        except ValueError:
            raise InventoryError("protected staging IP address invalid") from None
        if (
            not isinstance(ip_payload, dict)
            or ip_payload.get("id") != authority.management_ip_address_id
            or ip_payload.get("address") != authority.management_cidr
            or self._nested_value(ip_payload, "status", "value") != "active"
            or ip_payload.get("assigned_object_type") != "dcim.interface"
            or self._nested_value(ip_payload, "assigned_object", "id")
            != authority.management_interface_id
        ):
            raise InventoryError("protected staging IP address changed")
        return ProtectedStagingTarget(
            device_id=authority.device_id,
            name=authority.name,
            host=host,
            platform="cisco_iosxe"
            if authority.platform_slug == "cisco-ios-xe"
            else "junos",
            management_interface=authority.management_interface,
            interface_id=interface_id,
            management_cidr=authority.management_cidr,
            ip_address_id=authority.management_ip_address_id,
            live_homolog_id=authority.live_homolog_id,
            credential_reference=authority.credential_reference,
            openbao_role=authority.openbao_role,
        )


class NetBoxURL:
    """Strict URL policy independent of ambient inventory configuration."""

    @staticmethod
    def validate(value: str) -> str:
        parsed = urlparse(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise InventoryError("protected NetBox URL rejected")
        if parsed.scheme == "http" and parsed.hostname not in {
            "127.0.0.1",
            "::1",
            "localhost",
        }:
            raise InventoryError("protected NetBox URL rejected")
        return value.rstrip("/")


class ProtectedStagingSecretAuthority:
    """Derive only the two B2-authoritative staging capabilities."""

    _VALUES: ClassVar[dict[int, tuple[str, str]]] = {
        6: (
            "ncdp-buildkite-staging-device-6",
            "openbao:kv-v2:ncdp/devices/6/ssh",
        ),
        7: (
            "ncdp-buildkite-staging-device-7",
            "openbao:kv-v2:ncdp/devices/7/ssh",
        ),
    }

    @classmethod
    def resolve(cls, device_id: int) -> tuple[str, CredentialReference]:
        if device_id not in cls._VALUES:
            raise SecretError("protected staging secret identity rejected")
        role, reference = cls._VALUES[device_id]
        return role, CredentialReference("openbao", reference)

    @classmethod
    def validate_target(cls, target: ProtectedStagingTarget) -> None:
        role, reference = cls.resolve(target.device_id)
        if (
            target.openbao_role != role
            or target.credential_reference != reference.reference
        ):
            raise SecretError("protected staging secret authority changed")


@dataclass(frozen=True, repr=False)
class ProtectedCMLCredentials:
    """CML login material loaded only by the installed controller."""

    username: str
    password: str

    def __repr__(self) -> str:
        return "ProtectedCMLCredentials(<redacted>)"


class ProtectedCMLClient:
    """CML staging client with no ambient or caller-selected target authority."""

    def __init__(
        self,
        authority: CMLAuthority,
        credentials: ProtectedCMLCredentials,
        *,
        ssl_context: ssl.SSLContext | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not credentials.username or not credentials.password:
            raise ProtectedStagingError("protected CML credentials missing")
        self._authority = authority
        self._credentials = credentials
        if ssl_context is None and transport is None:
            raise ProtectedStagingError("protected CML TLS authority missing")
        self._client = httpx.Client(
            base_url=authority.controller_url,
            timeout=httpx.Timeout(10.0, connect=5.0),
            follow_redirects=False,
            verify=ssl_context if ssl_context is not None else True,
            trust_env=False,
            transport=transport,
        )
        self._token: str | None = None

    def authenticate(self) -> None:
        response = self._client.post(
            "/api/v0/authenticate",
            json={
                "username": self._credentials.username,
                "password": self._credentials.password,
            },
        )
        if response.status_code != 200:
            raise ProtectedStagingError("protected CML authentication failed")
        try:
            payload = response.json()
        except ValueError:
            raise ProtectedStagingError("protected CML authentication failed") from None
        token = payload if isinstance(payload, str) else None
        if isinstance(payload, dict):
            token = payload.get("token")
        if not isinstance(token, str) or not token:
            raise ProtectedStagingError("protected CML authentication failed")
        self._token = token

    def labs(self) -> tuple[CMLLabObservation, ...]:
        if self._token is None:
            raise ProtectedStagingError("protected CML client is not authenticated")
        response = self._client.get(
            "/api/v0/labs", headers={"Authorization": f"Bearer {self._token}"}
        )
        if response.status_code != 200:
            raise ProtectedStagingError("protected CML lab admission failed")
        try:
            payload = response.json()
        except ValueError:
            raise ProtectedStagingError("protected CML lab admission failed") from None
        if not isinstance(payload, list) or any(
            not isinstance(item, str) for item in payload
        ):
            raise ProtectedStagingError("protected CML lab admission failed")
        if len(payload) != len(set(payload)):
            raise ProtectedStagingError("protected CML lab admission failed")
        observations: list[CMLLabObservation] = []
        for lab_id in payload:
            try:
                UUID(lab_id)
            except ValueError:
                raise ProtectedStagingError(
                    "protected CML lab admission failed"
                ) from None
            detail_response = self._client.get(
                f"/api/v0/labs/{lab_id}",
                headers={"Authorization": f"Bearer {self._token}"},
            )
            if detail_response.status_code != 200:
                raise ProtectedStagingError("protected CML lab admission failed")
            try:
                detail = detail_response.json()
            except ValueError:
                raise ProtectedStagingError(
                    "protected CML lab admission failed"
                ) from None
            if not isinstance(detail, dict):
                raise ProtectedStagingError("protected CML lab admission failed")
            returned_id = detail.get("id", detail.get("lab_id"))
            if returned_id is not None and returned_id != lab_id:
                raise ProtectedStagingError("protected CML lab admission failed")
            title = detail.get("lab_title", detail.get("title"))
            if not isinstance(title, str) or not title:
                raise ProtectedStagingError("protected CML lab admission failed")
            observations.append(CMLLabObservation(lab_id, title))
        return tuple(observations)

    def close(self) -> None:
        self._token = None
        self._client.close()

    @property
    def bearer(self) -> str:
        """Expose the in-memory bearer only to protected Terraform composition."""
        if self._token is None:
            raise ProtectedStagingError("protected CML client is not authenticated")
        return self._token

    def lab_structure(
        self, lab_id: UUID
    ) -> tuple[dict[str, dict[str, object]], tuple[str, ...]]:
        """Read sanitized node metadata and link identities for one admitted lab."""
        if self._token is None:
            raise ProtectedStagingError("protected CML client is not authenticated")
        headers = {"Authorization": f"Bearer {self._token}"}
        base = f"/api/v0/labs/{lab_id}"
        node_response = self._client.get(f"{base}/nodes", headers=headers)
        link_response = self._client.get(f"{base}/links", headers=headers)
        if node_response.status_code != 200 or link_response.status_code != 200:
            raise ProtectedStagingError("protected CML realization unavailable")
        try:
            node_ids = node_response.json()
            link_ids = link_response.json()
        except ValueError:
            raise ProtectedStagingError("protected CML realization invalid") from None
        if (
            not isinstance(node_ids, list)
            or not isinstance(link_ids, list)
            or any(not isinstance(value, str) for value in (*node_ids, *link_ids))
            or len(node_ids) != len(set(node_ids))
            or len(link_ids) != len(set(link_ids))
        ):
            raise ProtectedStagingError("protected CML realization invalid")
        nodes: dict[str, dict[str, object]] = {}
        for node_id in node_ids:
            try:
                UUID(node_id)
            except ValueError:
                raise ProtectedStagingError(
                    "protected CML realization invalid"
                ) from None
            response = self._client.get(f"{base}/nodes/{node_id}", headers=headers)
            if response.status_code != 200:
                raise ProtectedStagingError("protected CML realization unavailable")
            try:
                node = response.json()
            except ValueError:
                raise ProtectedStagingError(
                    "protected CML realization invalid"
                ) from None
            if not isinstance(node, dict):
                raise ProtectedStagingError("protected CML realization invalid")
            nodes[node_id] = {
                key: node.get(key)
                for key in (
                    "id",
                    "label",
                    "node_definition",
                    "image_definition",
                    "state",
                )
            }
        for link_id in link_ids:
            try:
                UUID(link_id)
            except ValueError:
                raise ProtectedStagingError(
                    "protected CML realization invalid"
                ) from None
        return nodes, tuple(link_ids)


class OIDCCommandRunner(Protocol):
    def __call__(self, arguments: Sequence[str]) -> str: ...


def request_staging_oidc_jwt(
    runner: OIDCCommandRunner, buildkite_agent: Path
) -> BuildkiteOIDCJWT:
    """Request exactly one audience-bound JWT and retain it only in memory."""
    value = runner(
        (
            str(buildkite_agent),
            "oidc",
            "request-token",
            "--audience",
            "urn:ncdp:openbao:staging",
            "--lifetime",
            "300",
            "--subject-claim",
            "pipeline_id",
            "--claim",
            "build_id",
        )
    )
    return read_buildkite_oidc_jwt(StringIO(value))


@dataclass(frozen=True)
class CMLLabObservation:
    lab_id: str
    title: str


def admit_cml_labs(
    manifest: ProtectedStagingManifest,
    run_id: str,
    labs: Sequence[CMLLabObservation],
) -> None:
    """Reject foreign, duplicate, or brownfield staging ownership."""
    expected_title = f"NCDP Staging {run_id}"
    for lab in labs:
        try:
            UUID(lab.lab_id)
        except ValueError:
            raise ProtectedStagingError("CML lab identity is invalid") from None
        if lab.lab_id in manifest.cml.denied_lab_uuids:
            continue
        if lab.title == expected_title or lab.title.startswith("NCDP Staging "):
            raise ProtectedStagingError("existing CML staging realization is ambiguous")


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_protected_bundle(
    bundle_root: Path,
    checkout_root: Path,
    manifest: ProtectedStagingManifest,
    *,
    owner_uid: int | None = None,
    service_identity: ServiceIdentityAuthority | None = None,
) -> Path:
    """Verify an external, private, exact-file protected installation."""
    if not bundle_root.is_absolute() or bundle_root.is_symlink():
        raise ProtectedStagingError("protected bundle root is invalid")
    root = bundle_root.resolve(strict=True)
    checkout = checkout_root.resolve(strict=True)
    if root == checkout or root.is_relative_to(checkout):
        raise ProtectedStagingError("protected bundle must be outside checkout")
    metadata = root.stat(follow_symlinks=False)
    expected_uid = (
        service_identity.immutable_owner_uid
        if service_identity is not None
        else os.getuid()
        if owner_uid is None
        else owner_uid
    )
    expected_gid = (
        service_identity.service_gid if service_identity is not None else None
    )
    accepted_modes = {0o550, 0o750} if service_identity is not None else {0o700}
    if (
        metadata.st_uid != expected_uid
        or (expected_gid is not None and metadata.st_gid != expected_gid)
        or stat.S_IMODE(metadata.st_mode) not in accepted_modes
    ):
        raise ProtectedStagingError("protected bundle ownership or mode is invalid")
    observed: dict[str, str] = {}
    for relative, expected_digest in manifest.file_digests.items():
        path = root / relative
        if (
            path.is_symlink()
            or not path.is_file()
            or not path.resolve().is_relative_to(root)
        ):
            raise ProtectedStagingError("protected bundle file is invalid")
        digest = _file_sha256(path)
        file_metadata = path.stat(follow_symlinks=False)
        if service_identity is not None and (
            file_metadata.st_uid != service_identity.immutable_owner_uid
            or file_metadata.st_gid != service_identity.service_gid
            or stat.S_IMODE(file_metadata.st_mode) != 0o440
        ):
            raise ProtectedStagingError("protected bundle file ownership is invalid")
        if digest != expected_digest:
            raise ProtectedStagingError("protected bundle digest mismatch")
        observed[relative] = digest
    actual_files = {
        str(path.relative_to(root))
        for path in root.rglob("*")
        if path.is_file() or path.is_symlink()
    }
    if actual_files != set(manifest.file_digests):
        raise ProtectedStagingError("protected bundle contains unexpected files")
    if service_identity is not None:
        for directory in (path for path in root.rglob("*") if path.is_dir()):
            directory_metadata = directory.stat(follow_symlinks=False)
            if (
                directory.is_symlink()
                or directory_metadata.st_uid != service_identity.immutable_owner_uid
                or directory_metadata.st_gid != service_identity.service_gid
                or stat.S_IMODE(directory_metadata.st_mode) != 0o550
            ):
                raise ProtectedStagingError(
                    "protected bundle directory ownership is invalid"
                )
    combined = hashlib.sha256(
        json.dumps(observed, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if combined != manifest.source_bundle_digest:
        raise ProtectedStagingError("protected bundle digest mismatch")
    return root


def validate_runtime_inventory(
    runtime_root: Path,
    checkout_root: Path,
    manifest: ProtectedStagingManifest,
    inventory_path: Path,
    *,
    owner_uid: int | None = None,
    service_identity: ServiceIdentityAuthority | None = None,
) -> Path:
    """Verify every file/symlink in the installed executable runtime."""
    if not runtime_root.is_absolute() or runtime_root.is_symlink():
        raise ProtectedStagingError("protected runtime root is invalid")
    root = runtime_root.resolve(strict=True)
    checkout = checkout_root.resolve(strict=True)
    if root == checkout or root.is_relative_to(checkout):
        raise ProtectedStagingError("protected runtime must be outside checkout")
    expected_uid = (
        service_identity.immutable_owner_uid
        if service_identity is not None
        else os.getuid()
        if owner_uid is None
        else owner_uid
    )
    expected_gid = (
        service_identity.service_gid if service_identity is not None else None
    )
    metadata = root.stat(follow_symlinks=False)
    if (
        metadata.st_uid != expected_uid
        or (expected_gid is not None and metadata.st_gid != expected_gid)
        or stat.S_IMODE(metadata.st_mode)
        not in ({0o550, 0o750} if service_identity is not None else {0o700})
    ):
        raise ProtectedStagingError("protected runtime ownership or mode is invalid")
    if inventory_path.is_symlink() or not inventory_path.is_file():
        raise ProtectedStagingError("protected runtime inventory is invalid")
    inventory_metadata = inventory_path.stat(follow_symlinks=False)
    if (
        inventory_metadata.st_uid != expected_uid
        or (expected_gid is not None and inventory_metadata.st_gid != expected_gid)
        or stat.S_IMODE(inventory_metadata.st_mode)
        not in ({0o440} if service_identity is not None else {0o600})
    ):
        raise ProtectedStagingError("protected runtime inventory is invalid")
    raw = inventory_path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != manifest.runtime_inventory_sha256:
        raise ProtectedStagingError("protected runtime inventory digest mismatch")
    try:
        inventory = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ProtectedStagingError("protected runtime inventory is invalid") from None
    if not isinstance(inventory, dict) or not inventory:
        raise ProtectedStagingError("protected runtime inventory is invalid")
    observed: dict[str, dict[str, object]] = {}
    for relative, expected in inventory.items():
        if (
            not isinstance(relative, str)
            or relative.startswith("/")
            or ".." in Path(relative).parts
            or not isinstance(expected, dict)
        ):
            raise ProtectedStagingError("protected runtime inventory is invalid")
        path = root / relative
        mode = (
            stat.S_IMODE(path.lstat().st_mode)
            if path.exists() or path.is_symlink()
            else -1
        )
        if expected.get("type") == "file":
            if path.is_symlink() or not path.is_file():
                raise ProtectedStagingError("protected runtime file is invalid")
            actual = {"type": "file", "mode": mode, "sha256": _file_sha256(path)}
            file_metadata = path.stat(follow_symlinks=False)
            if service_identity is not None and (
                file_metadata.st_uid != service_identity.immutable_owner_uid
                or file_metadata.st_gid != service_identity.service_gid
                or mode & 0o022
            ):
                raise ProtectedStagingError("protected runtime ownership is invalid")
        elif expected.get("type") == "symlink":
            if not path.is_symlink():
                raise ProtectedStagingError("protected runtime symlink is invalid")
            target = str(path.readlink())
            resolved = path.resolve(strict=True)
            actual = {"type": "symlink", "mode": mode, "target": target}
            # Do not resolve the final symlink: this checks its lexical boundary.
            lexical = Path(os.path.abspath(path.parent / target))  # noqa: PTH100
            if not lexical.is_relative_to(root):
                if (
                    relative != "bin/python"
                    or str(resolved) != manifest.python_interpreter_path
                    or _file_sha256(resolved) != manifest.python_interpreter_sha256
                ):
                    raise ProtectedStagingError(
                        "protected runtime symlink escapes runtime"
                    )
                actual["target_sha256"] = _file_sha256(resolved)
        else:
            raise ProtectedStagingError("protected runtime inventory is invalid")
        if actual != expected:
            raise ProtectedStagingError("protected runtime content mismatch")
        observed[relative] = actual
    actual_objects = {
        str(path.relative_to(root))
        for path in root.rglob("*")
        if path.is_file() or path.is_symlink()
    }
    if actual_objects != set(inventory):
        raise ProtectedStagingError("protected runtime contains unexpected files")
    if service_identity is not None:
        for directory in (path for path in root.rglob("*") if path.is_dir()):
            directory_metadata = directory.stat(follow_symlinks=False)
            if (
                directory.is_symlink()
                or directory_metadata.st_uid != service_identity.immutable_owner_uid
                or directory_metadata.st_gid != service_identity.service_gid
                or stat.S_IMODE(directory_metadata.st_mode) != 0o550
            ):
                raise ProtectedStagingError(
                    "protected runtime directory ownership is invalid"
                )
    combined = hashlib.sha256(
        json.dumps(observed, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if combined != manifest.runtime_digest:
        raise ProtectedStagingError("protected runtime digest mismatch")
    entrypoint = root / manifest.controller_entrypoint
    if entrypoint.is_symlink() or not entrypoint.is_file():
        raise ProtectedStagingError("protected controller entrypoint is invalid")
    return root


def validate_runtime_artifacts(
    install_root: Path,
    manifest: ProtectedStagingManifest,
    *,
    service_identity: ServiceIdentityAuthority | None = None,
) -> None:
    """Bind retained wheel and frozen production requirements to the manifest."""
    wheels = tuple((install_root / "artifacts/wheels").glob("*.whl"))
    requirements = install_root / "artifacts/production-requirements.txt"
    if (
        len(wheels) != 1
        or wheels[0].is_symlink()
        or _file_sha256(wheels[0]) != manifest.project_wheel_sha256
        or requirements.is_symlink()
        or not requirements.is_file()
        or _file_sha256(requirements) != manifest.production_requirements_sha256
    ):
        raise ProtectedStagingError("protected runtime artifacts mismatch")
    if service_identity is not None:
        for path in (*wheels, requirements):
            metadata = path.stat(follow_symlinks=False)
            if (
                metadata.st_uid != service_identity.immutable_owner_uid
                or metadata.st_gid != service_identity.service_gid
                or stat.S_IMODE(metadata.st_mode) != 0o440
            ):
                raise ProtectedStagingError(
                    "protected runtime artifact ownership invalid"
                )


def validate_state_root(
    root: Path, checkout_root: Path, *, owner_uid: int | None = None
) -> Path:
    """Require an agent-owned private state root outside checkout."""
    if not root.is_absolute() or root.is_symlink() or not root.is_dir():
        raise ProtectedStagingError("protected staging state root is invalid")
    resolved = root.resolve(strict=True)
    checkout = checkout_root.resolve(strict=True)
    metadata = root.stat(follow_symlinks=False)
    expected_uid = os.getuid() if owner_uid is None else owner_uid
    if (
        resolved == checkout
        or resolved.is_relative_to(checkout)
        or metadata.st_uid != expected_uid
        or stat.S_IMODE(metadata.st_mode) & 0o077
    ):
        raise ProtectedStagingError("protected staging state root is invalid")
    return resolved


def parse_structural_plan(lines: Sequence[str]) -> dict[str, str]:
    """Extract addresses/actions without retaining or rendering values."""
    changes: dict[str, str] = {}
    for line in lines:
        try:
            event = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            raise ProtectedStagingError("Terraform plan stream is invalid") from None
        if not isinstance(event, dict) or event.get("type") != "planned_change":
            continue
        change = event.get("change")
        resource = change.get("resource") if isinstance(change, dict) else None
        address = resource.get("addr") if isinstance(resource, dict) else None
        action = change.get("action") if isinstance(change, dict) else None
        if (
            not isinstance(address, str)
            or not isinstance(action, str)
            or address in changes
        ):
            raise ProtectedStagingError("Terraform plan stream is invalid")
        changes[address] = action
    return changes


def validate_plan(
    phase: Literal["create", "start", "destroy"], changes: Mapping[str, str]
) -> None:
    """Require the exact approved graph for each mutable phase."""
    expected = (
        dict.fromkeys(EXPECTED_TERRAFORM_ADDRESSES, "create")
        if phase == "create"
        else dict.fromkeys(EXPECTED_TERRAFORM_ADDRESSES, "delete")
        if phase == "destroy"
        else {LIFECYCLE_ADDRESS: "update"}
    )
    if dict(changes) != expected:
        raise ProtectedStagingError(f"Terraform {phase} plan graph rejected")


def validate_cleanup_authority(
    state_addresses: set[str], recorded_lab_id: str, manifest: ProtectedStagingManifest
) -> None:
    """Bound cleanup to one known disposable graph and never brownfield."""
    if recorded_lab_id in manifest.cml.denied_lab_uuids:
        raise ProtectedStagingError("brownfield CML lab cleanup rejected")
    try:
        UUID(recorded_lab_id)
    except ValueError:
        raise ProtectedStagingError("recorded staging lab identity invalid") from None
    if not state_addresses or not state_addresses.issubset(
        EXPECTED_TERRAFORM_ADDRESSES
    ):
        raise ProtectedStagingError("protected cleanup graph rejected")


def validate_cleanup_plan(
    state_addresses: set[str], planned_changes: Mapping[str, str]
) -> None:
    """Require cleanup to delete exactly the admitted retained state subset."""
    if not state_addresses or not state_addresses.issubset(
        EXPECTED_TERRAFORM_ADDRESSES
    ):
        raise ProtectedStagingError("protected cleanup graph rejected")
    if set(planned_changes) != state_addresses or any(
        action != "delete" for action in planned_changes.values()
    ):
        raise ProtectedStagingError("protected cleanup plan rejected")


class ProtectedTerraformOutputs(BaseModel):
    """Exact structural outputs accepted from the protected staging root."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    staging_run_id: str
    lab_title: str
    lab_id: UUID
    node_ids: dict[str, UUID]
    link_ids: dict[str, UUID]
    lifecycle_state: Literal["DEFINED_ON_CORE", "STARTED", "STOPPED"]

    @model_validator(mode="after")
    def exact_structure(self) -> ProtectedTerraformOutputs:
        if set(self.node_ids) != {
            "system_bridge",
            "management_switch",
            "cisco",
            "junos",
        }:
            raise ValueError("protected Terraform node outputs changed")
        if set(self.link_ids) != {
            "system_bridge_management",
            "management_cisco",
            "management_junos",
            "cisco_junos",
        }:
            raise ValueError("protected Terraform link outputs changed")
        if str(self.lab_id) == BROWNFIELD_LAB_UUID:
            raise ValueError("brownfield lab output rejected")
        if self.lab_title != f"NCDP Staging {self.staging_run_id}":
            raise ValueError("protected Terraform lab title changed")
        return self


class TerraformCommandRunner(Protocol):
    def run(
        self, arguments: Sequence[str], *, cwd: Path, environment: Mapping[str, str]
    ) -> tuple[str, ...]: ...


class SubprocessTerraformRunner:
    """Execute Terraform without exposing raw JSON or inheriting ambient secrets."""

    def __init__(self, executable: Path) -> None:
        if not executable.is_absolute():
            raise ProtectedStagingError("protected Terraform executable rejected")
        self._executable = executable

    def run(
        self, arguments: Sequence[str], *, cwd: Path, environment: Mapping[str, str]
    ) -> tuple[str, ...]:
        result = subprocess.run(
            [str(self._executable), *arguments],
            cwd=cwd,
            env=dict(environment),
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise ProtectedStagingError("protected Terraform command failed")
        return tuple(result.stdout.splitlines())


class ProtectedTerraformExecutor:
    """Bind an exact structurally approved saved plan to its apply."""

    def __init__(
        self,
        bundle_root: Path,
        state_directory: Path,
        runner: TerraformCommandRunner,
        environment: Mapping[str, str],
    ) -> None:
        terraform_root = bundle_root / "infrastructure/cml/ephemeral"
        if (
            bundle_root.is_symlink()
            or not bundle_root.is_absolute()
            or terraform_root.is_symlink()
            or not terraform_root.is_dir()
            or not terraform_root.resolve().is_relative_to(bundle_root.resolve())
        ):
            raise ProtectedStagingError("protected Terraform root is invalid")
        if (
            not state_directory.is_absolute()
            or state_directory.is_symlink()
            or not state_directory.is_dir()
            or stat.S_IMODE(state_directory.stat().st_mode) & 0o077
        ):
            raise ProtectedStagingError("protected Terraform state directory invalid")
        self._terraform_root = terraform_root
        self._state_directory = state_directory
        self._runner = runner
        self._environment = {
            **dict(environment),
            "TF_DATA_DIR": str(state_directory / "terraform-data"),
        }

    def set_lifecycle_state(self, state: Literal["DEFINED_ON_CORE", "STARTED"]) -> None:
        """Change only the protected lifecycle input between admitted phases."""
        self._environment["TF_VAR_lifecycle_state"] = state

    def initialize(self) -> None:
        """Initialize only the fixed protected root and fixed run state path."""
        data_directory = Path(self._environment["TF_DATA_DIR"])
        data_directory.mkdir(mode=0o700, exist_ok=True)
        if (
            data_directory.is_symlink()
            or stat.S_IMODE(data_directory.stat().st_mode) & 0o077
        ):
            raise ProtectedStagingError("protected Terraform data directory invalid")
        state = self._state_directory / "terraform.tfstate"
        self._runner.run(
            (
                "init",
                "-input=false",
                "-lockfile=readonly",
                f"-backend-config=path={state}",
            ),
            cwd=self._terraform_root,
            environment=self._environment,
        )

    def execute(self, phase: Literal["create", "start", "destroy"]) -> None:
        plan = self._state_directory / f"{phase}.tfplan"
        if plan.exists() or plan.is_symlink():
            raise ProtectedStagingError("protected Terraform plan path is occupied")
        descriptor = os.open(plan, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(descriptor)
        try:
            arguments = ["plan", "-json", "-input=false", f"-out={plan}"]
            if phase == "destroy":
                arguments.append("-destroy")
            lines = self._runner.run(
                arguments, cwd=self._terraform_root, environment=self._environment
            )
            validate_plan(phase, parse_structural_plan(lines))
            if stat.S_IMODE(plan.stat().st_mode) != 0o600:
                raise ProtectedStagingError("protected Terraform plan mode changed")
            self._runner.run(
                ["apply", "-json", "-input=false", str(plan)],
                cwd=self._terraform_root,
                environment=self._environment,
            )
            state = self._state_directory / "terraform.tfstate"
            if state.exists():
                if state.is_symlink():
                    raise ProtectedStagingError("protected Terraform state invalid")
                state.chmod(0o600)
        finally:
            if plan.exists() and not plan.is_symlink():
                plan.unlink()

    def state_addresses(self) -> set[str]:
        """Read only structural state addresses from the fixed backend."""
        state = self._state_directory / "terraform.tfstate"
        data = Path(self._environment["TF_DATA_DIR"])
        if not state.exists() and not data.exists():
            return set()
        lines = self._runner.run(
            ["state", "list"],
            cwd=self._terraform_root,
            environment=self._environment,
        )
        addresses = {line.strip() for line in lines if line.strip()}
        if any(
            any(character in address for character in "\r\n\x00")
            for address in addresses
        ):
            raise ProtectedStagingError("protected Terraform state invalid")
        return addresses

    def cleanup_retained(self) -> bool:
        """Destroy an exact valid partial state; reject any foreign address."""
        state_addresses = self.state_addresses()
        if not state_addresses:
            return False
        if not state_addresses.issubset(EXPECTED_TERRAFORM_ADDRESSES):
            raise ProtectedStagingError("protected cleanup graph rejected")
        plan = self._state_directory / "cleanup.tfplan"
        if plan.exists() or plan.is_symlink():
            raise ProtectedStagingError("protected Terraform plan path is occupied")
        descriptor = os.open(plan, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(descriptor)
        try:
            lines = self._runner.run(
                ["plan", "-json", "-input=false", f"-out={plan}", "-destroy"],
                cwd=self._terraform_root,
                environment=self._environment,
            )
            validate_cleanup_plan(state_addresses, parse_structural_plan(lines))
            self._runner.run(
                ["apply", "-json", "-input=false", str(plan)],
                cwd=self._terraform_root,
                environment=self._environment,
            )
            return True
        finally:
            if plan.exists() and not plan.is_symlink():
                plan.unlink()

    def outputs(self, run_id: str) -> ProtectedTerraformOutputs:
        """Parse exact allowlisted output values without emitting raw JSON."""
        lines = self._runner.run(
            ["output", "-json"],
            cwd=self._terraform_root,
            environment=self._environment,
        )
        try:
            raw = json.loads("\n".join(lines))
        except json.JSONDecodeError:
            raise ProtectedStagingError("protected Terraform outputs invalid") from None
        expected = {
            "staging_run_id",
            "lab_title",
            "lab_id",
            "node_ids",
            "link_ids",
            "lifecycle_state",
        }
        if not isinstance(raw, dict) or set(raw) != expected:
            raise ProtectedStagingError("protected Terraform outputs invalid")
        values: dict[str, object] = {}
        for key in expected:
            item = raw.get(key)
            if not isinstance(item, dict) or set(item) < {"value"}:
                raise ProtectedStagingError("protected Terraform outputs invalid")
            values[key] = item["value"]
        try:
            outputs = ProtectedTerraformOutputs.model_validate(values)
        except ValueError:
            raise ProtectedStagingError("protected Terraform outputs invalid") from None
        if outputs.staging_run_id != run_id:
            raise ProtectedStagingError("protected Terraform run identity changed")
        return outputs


class ProtectedStagingEvidence(BaseModel):
    """Explicit allowlist for future sanitized staging evidence."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal[1] = 1
    pipeline_id: str
    build_id: str
    source_commit: str
    protected_bundle_digest: str
    manifest_digest: str
    run_id: str
    staging_device_ids: tuple[Literal[6, 7], Literal[6, 7]]
    homolog_ids: tuple[Literal[1, 2], Literal[1, 2]]
    management_ips: tuple[str, str]
    credential_references: tuple[str, str]
    lab_id: str | None = None
    node_ids: dict[str, str] = Field(default_factory=dict)
    link_ids: dict[str, str] = Field(default_factory=dict)
    terraform_actions: dict[str, int] = Field(default_factory=dict)
    readiness_outcome: str = "not_attempted"
    validation_outcome: str = "not_attempted"
    cleanup_outcome: str = "not_attempted"
    absence_outcome: str = "not_attempted"
    failure_code: str | None = None
    duration_seconds: float | None = None

    @model_validator(mode="after")
    def exact_public_authority(self) -> ProtectedStagingEvidence:
        if self.staging_device_ids != (6, 7) or self.homolog_ids != (1, 2):
            raise ValueError("protected evidence identity changed")
        if self.management_ips != ("192.168.4.30", "192.168.4.31"):
            raise ValueError("protected evidence management authority changed")
        if self.credential_references != (
            "openbao:kv-v2:ncdp/devices/6/ssh",
            "openbao:kv-v2:ncdp/devices/7/ssh",
        ):
            raise ValueError("protected evidence credential authority changed")
        return self

    def safe_dict(self) -> dict[str, object]:
        return self.model_dump(mode="json")
