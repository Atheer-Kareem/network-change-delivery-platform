"""Checkout-independent authority contracts for protected CML staging."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
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
from network_change_delivery.secrets import CredentialReference, SecretError

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
    environment: Literal["staging"]
    status: Literal["staged"]
    role_slug: Literal["ncdp-staging"]
    platform_slug: Literal["cisco-ios-xe", "juniper-junos"]
    management_interface: str
    management_ip: str
    live_homolog_id: int
    live_homolog_name: str
    openbao_role: str
    credential_reference: str


class CMLAuthority(BaseModel):
    """Exact controller and realization exclusions for staging."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    controller_identity: str = Field(min_length=1, max_length=255)
    controller_url: str
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
        return self


class ProtectedStagingManifest(BaseModel):
    """Installed, immutable staging authority; checkout copies are not authority."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal[1] = 1
    source_commit: str
    bundle_digest: str
    controller_artifact_digest: str
    file_digests: dict[str, str]
    cisco: StagingTargetAuthority
    junos: StagingTargetAuthority
    live_deny_device_ids: tuple[int, ...]
    live_deny_management_ips: tuple[str, ...]
    cml: CMLAuthority
    terraform_addresses: tuple[str, ...]
    lifecycle_update_address: str

    _EXPECTED: ClassVar[dict[str, dict[str, object]]] = {
        "cisco": {
            "device_id": 6,
            "name": "stg-core-02",
            "platform_slug": "cisco-ios-xe",
            "management_interface": "GigabitEthernet1",
            "management_ip": "192.168.4.30",
            "live_homolog_id": 1,
            "live_homolog_name": "core-02",
            "openbao_role": "ncdp-buildkite-staging-device-6",
            "credential_reference": "openbao:kv-v2:ncdp/devices/6/ssh",
        },
        "junos": {
            "device_id": 7,
            "name": "stg-edge-junos-01",
            "platform_slug": "juniper-junos",
            "management_interface": "fxp0",
            "management_ip": "192.168.4.31",
            "live_homolog_id": 2,
            "live_homolog_name": "edge-junos-01",
            "openbao_role": "ncdp-buildkite-staging-device-7",
            "credential_reference": "openbao:kv-v2:ncdp/devices/7/ssh",
        },
    }

    @model_validator(mode="after")
    def exact_authority(self) -> ProtectedStagingManifest:
        if not _SHA1.fullmatch(self.source_commit):
            raise ValueError("protected source commit is invalid")
        for digest in (
            self.bundle_digest,
            self.controller_artifact_digest,
            *self.file_digests.values(),
        ):
            if not _SHA256.fullmatch(digest):
                raise ValueError("protected bundle digest is invalid")
        if not self.file_digests or any(
            Path(name).is_absolute() or ".." in Path(name).parts
            for name in self.file_digests
        ):
            raise ValueError("protected file inventory is invalid")
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
    live_homolog_id: Literal[1, 2]
    credential_reference: str
    openbao_role: str


class ProtectedStagingInventoryResolver:
    """Resolve exact staging IDs without weakening the live inventory provider."""

    _DEVICE_PATH = "/api/dcim/devices/{device_id}/"
    _INTERFACE_PATH = "/api/dcim/interfaces/"

    def __init__(
        self,
        manifest: ProtectedStagingManifest,
        url: str,
        staging_reader_token: str,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not staging_reader_token:
            raise InventoryError("protected NetBox staging reader missing")
        self._manifest = manifest
        base_url = url.rstrip("/")
        if NetBoxURL.validate(base_url) != base_url:
            raise InventoryError("protected NetBox URL rejected")
        self._client = httpx.Client(
            base_url=base_url,
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
        targets = tuple(
            self._resolve_target(authority, live[authority.live_homolog_id])
            for authority in (self._manifest.cisco, self._manifest.junos)
        )
        if len({target.live_homolog_id for target in targets}) != 2:
            raise InventoryError("protected staging homolog mapping is ambiguous")
        for authority in (self._manifest.cisco, self._manifest.junos):
            self._validate_unique_reverse_homolog(authority)
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
            or live_fields.get("ncdp_environment") != "live"
            or live_fields.get("ncdp_live_homolog") is not None
        ):
            raise InventoryError("protected live homolog authority changed")
        staging_type = self._nested_value(device, "device_type", "id")
        live_type = self._nested_value(live, "device_type", "id")
        if (
            not isinstance(staging_type, int)
            or isinstance(staging_type, bool)
            or staging_type != live_type
        ):
            raise InventoryError("protected staging device type changed")
        primary = self._nested_value(device, "primary_ip4", "address")
        try:
            host = str(ipaddress.IPv4Interface(str(primary)).ip)
        except ValueError:
            raise InventoryError("protected staging primary IPv4 invalid") from None
        if host != authority.management_ip or host in LIVE_DENY_IPS:
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
        return ProtectedStagingTarget(
            device_id=authority.device_id,
            name=authority.name,
            host=host,
            platform="cisco_iosxe"
            if authority.platform_slug == "cisco-ios-xe"
            else "junos",
            management_interface=authority.management_interface,
            interface_id=interface_id,
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
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not credentials.username or not credentials.password:
            raise ProtectedStagingError("protected CML credentials missing")
        self._authority = authority
        self._credentials = credentials
        self._client = httpx.Client(
            base_url=authority.controller_url,
            timeout=httpx.Timeout(10.0, connect=5.0),
            follow_redirects=False,
            verify=True,
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


class OIDCCommandRunner(Protocol):
    def __call__(self, arguments: Sequence[str]) -> str: ...


def request_staging_oidc_jwt(runner: OIDCCommandRunner) -> BuildkiteOIDCJWT:
    """Request exactly one audience-bound JWT and retain it only in memory."""
    value = runner(
        (
            "buildkite-agent",
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
) -> Path:
    """Verify an external, private, exact-file protected installation."""
    if not bundle_root.is_absolute() or bundle_root.is_symlink():
        raise ProtectedStagingError("protected bundle root is invalid")
    root = bundle_root.resolve(strict=True)
    checkout = checkout_root.resolve(strict=True)
    if root == checkout or root.is_relative_to(checkout):
        raise ProtectedStagingError("protected bundle must be outside checkout")
    metadata = root.stat(follow_symlinks=False)
    expected_uid = os.getuid() if owner_uid is None else owner_uid
    if metadata.st_uid != expected_uid or stat.S_IMODE(metadata.st_mode) & 0o077:
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
        if digest != expected_digest:
            raise ProtectedStagingError("protected bundle digest mismatch")
        observed[relative] = digest
    allowed_generated = {"authority-manifest.json", "bundle-files.json"}
    actual_files = {
        str(path.relative_to(root))
        for path in root.rglob("*")
        if path.is_file() or path.is_symlink()
    }
    if actual_files - set(manifest.file_digests) - allowed_generated:
        raise ProtectedStagingError("protected bundle contains unexpected files")
    combined = hashlib.sha256(
        json.dumps(observed, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if combined != manifest.bundle_digest:
        raise ProtectedStagingError("protected bundle digest mismatch")
    return root


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


class TerraformCommandRunner(Protocol):
    def run(
        self, arguments: Sequence[str], *, cwd: Path, environment: Mapping[str, str]
    ) -> tuple[str, ...]: ...


class SubprocessTerraformRunner:
    """Execute Terraform without exposing raw JSON or inheriting ambient secrets."""

    def run(
        self, arguments: Sequence[str], *, cwd: Path, environment: Mapping[str, str]
    ) -> tuple[str, ...]:
        result = subprocess.run(
            ["terraform", *arguments],
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

    def initialize(self) -> None:
        """Initialize only the fixed protected root and fixed run state path."""
        data_directory = Path(self._environment["TF_DATA_DIR"])
        data_directory.mkdir(mode=0o700)
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
