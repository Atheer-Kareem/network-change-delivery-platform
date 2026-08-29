"""Typed, secret-free SNMPv3 device-provisioning contract."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal
from xml.etree import ElementTree

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from network_change_delivery.audit import NetBoxDeviceIdentity, Sha256
from network_change_delivery.models import InventoryDevice
from network_change_delivery.snmp_credentials import (
    SNMP_AUTH_PROTOCOL,
    SNMP_PRIVACY_PROTOCOL,
    SNMP_SECURITY_LEVEL,
    SnmpProvisioningCredentials,
    snmp_username,
    validate_snmp_generation,
)
from network_change_delivery.snmp_mib import (
    APPROVED_DEVICE_VIEW_OIDS,
    validate_device_view_oids,
)
from network_change_delivery.snmp_telemetry import SnmpCredentialReference

BoundedName = Annotated[
    str,
    StringConstraints(min_length=1, max_length=32, pattern=r"^[A-Za-z][A-Za-z0-9_-]*$"),
]
ChangeId = Annotated[
    str,
    StringConstraints(
        min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$"
    ),
]

NCDP_SNMP_VIEW = "NCDP_IFMIB"
NCDP_SNMP_GROUP = "NCDP_SNMP_RO"


class SnmpProvisioningError(ValueError):
    """Bounded provisioning contract failure without raw provider output."""


class SnmpOwnedStateDisposition(StrEnum):
    ABSENT = "ABSENT"
    EXACT_NCDP_STATE = "EXACT_NCDP_STATE"
    CONFLICT = "CONFLICT"
    FOREIGN = "FOREIGN"


class SnmpProvisioningOutcome(StrEnum):
    BLOCKED = "BLOCKED"
    SUCCEEDED = "SUCCEEDED"
    EXECUTION_FAILED = "EXECUTION_FAILED"
    AMBIGUOUS = "AMBIGUOUS"
    POST_VALIDATION_FAILED = "POST_VALIDATION_FAILED"
    RECOVERED = "RECOVERED"
    RECOVERY_FAILED = "RECOVERY_FAILED"
    AUTO_ROLLBACK_PENDING = "AUTO_ROLLBACK_PENDING"
    CONFIRMATION_FAILED = "CONFIRMATION_FAILED"
    CONFIRMATION_AMBIGUOUS = "CONFIRMATION_AMBIGUOUS"


class SnmpV3InterfaceTelemetryIntent(BaseModel):
    """One device's exact NCDP-owned read-only SNMPv3 desired state."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal["1"] = "1"
    change_id: ChangeId
    kind: Literal["snmpv3_interface_telemetry"] = "snmpv3_interface_telemetry"
    target: BoundedName
    device: NetBoxDeviceIdentity
    platform: Literal["cisco_iosxe", "junos"]
    generation: Literal["v1"] = "v1"
    username: BoundedName
    credential: SnmpCredentialReference
    security_level: Literal["authPriv"] = SNMP_SECURITY_LEVEL
    authentication_protocol: Literal["SHA256"] = SNMP_AUTH_PROTOCOL
    privacy_protocol: Literal["AES128"] = SNMP_PRIVACY_PROTOCOL
    view_name: Literal["NCDP_IFMIB"] = NCDP_SNMP_VIEW
    group_name: Literal["NCDP_SNMP_RO"] = NCDP_SNMP_GROUP
    device_view_oids: tuple[str, ...] = tuple(sorted(APPROVED_DEVICE_VIEW_OIDS))

    @model_validator(mode="after")
    def exact_contract(self) -> SnmpV3InterfaceTelemetryIntent:
        generation = validate_snmp_generation(self.generation)
        device_id = int(self.device.removeprefix("netbox:dcim.device:"))
        if device_id not in {1, 2} or self.username != snmp_username(
            device_id, generation
        ):
            raise ValueError("SNMP provisioning username rejected")
        if self.credential.device != self.device:
            raise ValueError("SNMP provisioning credential device mismatch")
        expected_reference = (
            f"snmpv3:netbox:dcim.device:{device_id}:generation:{generation}"
        )
        if (
            self.credential.reference != expected_reference
            or self.credential.auth_selector != f"device_{device_id}_{generation}"
        ):
            raise ValueError("SNMP provisioning credential reference rejected")
        validate_device_view_oids(frozenset(self.device_view_oids))
        return self


class SnmpOwnedObjectState(BaseModel):
    """Normalized targeted preflight without configuration or key material."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    observed_hostname: str = Field(min_length=1, max_length=128)
    local_engine_id_present: bool
    view: SnmpOwnedStateDisposition
    group: SnmpOwnedStateDisposition
    user: SnmpOwnedStateDisposition
    foreign_objects_present: bool = False

    @property
    def safe_to_create(self) -> bool:
        return (
            self.local_engine_id_present
            and self.view is SnmpOwnedStateDisposition.ABSENT
            and self.group is SnmpOwnedStateDisposition.ABSENT
            and self.user is SnmpOwnedStateDisposition.ABSENT
        )


class SnmpProvisioningPlan(BaseModel):
    """Immutable sibling plan for one protected SNMP provisioning attempt."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal["1"] = "1"
    plan_type: Literal["snmp_provisioning_plan"] = "snmp_provisioning_plan"
    change_id: ChangeId
    kind: Literal["snmpv3_interface_telemetry"] = "snmpv3_interface_telemetry"
    target: BoundedName
    inventory_source: Literal["netbox"] = "netbox"
    inventory_object_id: NetBoxDeviceIdentity
    platform: Literal["cisco_iosxe", "junos"]
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(ge=1, le=65535)
    expected_hostname: str = Field(min_length=1, max_length=128)
    connection_credential_reference: str = Field(min_length=1, max_length=255)
    snmp_credential: SnmpCredentialReference
    generation: Literal["v1"]
    username: BoundedName
    security_level: Literal["authPriv"] = SNMP_SECURITY_LEVEL
    authentication_protocol: Literal["SHA256"] = SNMP_AUTH_PROTOCOL
    privacy_protocol: Literal["AES128"] = SNMP_PRIVACY_PROTOCOL
    view_name: Literal["NCDP_IFMIB"] = NCDP_SNMP_VIEW
    group_name: Literal["NCDP_SNMP_RO"] = NCDP_SNMP_GROUP
    device_view_oids: tuple[str, ...]
    oid_closure_digest: Sha256
    transaction_strategy: Literal["cisco_targeted_inverse", "junos_commit_confirmed"]
    confirmed_timeout_minutes: Literal[5] | None = None
    preconditions: SnmpOwnedObjectState
    created_at: datetime
    digest: Sha256

    @model_validator(mode="after")
    def exact_contract(self) -> SnmpProvisioningPlan:
        intent = SnmpV3InterfaceTelemetryIntent(
            change_id=self.change_id,
            target=self.target,
            device=self.inventory_object_id,
            platform=self.platform,
            generation=self.generation,
            username=self.username,
            credential=self.snmp_credential,
            device_view_oids=self.device_view_oids,
        )
        del intent
        device_id = self.inventory_object_id.removeprefix("netbox:dcim.device:")
        expected_connection = f"openbao:kv-v2:ncdp/devices/{device_id}/ssh"
        if self.connection_credential_reference != expected_connection:
            raise ValueError("SNMP plan connection authority rejected")
        if self.platform == "junos":
            if (
                self.port != 830
                or self.transaction_strategy != "junos_commit_confirmed"
                or self.confirmed_timeout_minutes != 5
            ):
                raise ValueError("SNMP Junos transaction contract rejected")
        elif (
            self.port != 22
            or self.transaction_strategy != "cisco_targeted_inverse"
            or self.confirmed_timeout_minutes is not None
        ):
            raise ValueError("SNMP Cisco transaction contract rejected")
        if not self.preconditions.safe_to_create:
            raise ValueError("SNMP plan requires absent owned objects")
        if self.preconditions.observed_hostname != self.expected_hostname:
            raise ValueError("SNMP plan hostname precondition rejected")
        if self.oid_closure_digest != oid_closure_digest(self.device_view_oids):
            raise ValueError("SNMP plan OID closure digest rejected")
        if self.digest != self.calculated_digest():
            raise ValueError("SNMP plan digest rejected")
        return self

    def digest_input(self) -> bytes:
        return json.dumps(
            self.model_dump(mode="json", exclude={"digest"}),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()

    def calculated_digest(self) -> str:
        return "sha256:" + hashlib.sha256(self.digest_input()).hexdigest()

    def verify_digest(self) -> bool:
        return self.digest == self.calculated_digest()


def oid_closure_digest(oids: tuple[str, ...]) -> str:
    validate_device_view_oids(frozenset(oids))
    return (
        "sha256:"
        + hashlib.sha256(
            json.dumps(list(oids), separators=(",", ":")).encode()
        ).hexdigest()
    )


def build_snmp_provisioning_plan(
    intent: SnmpV3InterfaceTelemetryIntent,
    device: InventoryDevice,
    preflight: SnmpOwnedObjectState,
    *,
    created_at: datetime | None = None,
) -> SnmpProvisioningPlan:
    """Bind one exact absent-state preflight to a secret-free reviewed plan."""
    if (
        device.inventory_source != "netbox"
        or device.inventory_object_id != intent.device
        or device.platform != intent.platform
        or device.name != intent.target
        or device.expected_hostname != preflight.observed_hostname
    ):
        raise SnmpProvisioningError("SNMP plan inventory identity rejected")
    values = {
        "change_id": intent.change_id,
        "target": intent.target,
        "inventory_object_id": intent.device,
        "platform": intent.platform,
        "host": device.host,
        "port": device.port,
        "expected_hostname": device.expected_hostname,
        "connection_credential_reference": (
            f"openbao:kv-v2:ncdp/devices/"
            f"{intent.device.removeprefix('netbox:dcim.device:')}/ssh"
        ),
        "snmp_credential": intent.credential,
        "generation": intent.generation,
        "username": intent.username,
        "device_view_oids": intent.device_view_oids,
        "oid_closure_digest": oid_closure_digest(intent.device_view_oids),
        "transaction_strategy": (
            "junos_commit_confirmed"
            if intent.platform == "junos"
            else "cisco_targeted_inverse"
        ),
        "confirmed_timeout_minutes": 5 if intent.platform == "junos" else None,
        "preconditions": preflight,
        "created_at": created_at or datetime.now(UTC),
        "digest": "sha256:" + "0" * 64,
    }
    unsigned = SnmpProvisioningPlan.model_construct(**values)
    values["digest"] = unsigned.calculated_digest()
    return SnmpProvisioningPlan.model_validate(values)


@dataclass(frozen=True, repr=False)
class SecretRenderedArtifact:
    """In-memory write artifact whose representation cannot expose passphrases."""

    platform: Literal["cisco_iosxe", "junos"]
    plan: SnmpProvisioningPlan
    payload: tuple[str, ...] | str

    def __repr__(self) -> str:
        return f"SecretRenderedArtifact(platform={self.platform!r}, payload=<redacted>)"


def render_cisco_provisioning(
    plan: SnmpProvisioningPlan, credentials: SnmpProvisioningCredentials
) -> SecretRenderedArtifact:
    if plan.platform != "cisco_iosxe" or credentials.username != plan.username:
        raise SnmpProvisioningError("Cisco SNMP runtime identity rejected")
    commands = (
        *(
            f"snmp-server view {plan.view_name} {oid} included"
            for oid in plan.device_view_oids
        ),
        f"snmp-server group {plan.group_name} v3 priv read {plan.view_name}",
        (
            f"snmp-server user {plan.username} {plan.group_name} v3 auth sha-2 256 "
            f"{credentials.authentication_secret} priv aes 128 "
            f"{credentials.privacy_secret}"
        ),
    )
    return SecretRenderedArtifact("cisco_iosxe", plan, commands)


def cisco_recovery_commands(plan: SnmpProvisioningPlan) -> tuple[str, ...]:
    """Remove only exact plan-owned objects, dependency-first."""
    if plan.platform != "cisco_iosxe":
        raise SnmpProvisioningError("Cisco SNMP recovery plan rejected")
    return (
        f"no snmp-server user {plan.username} {plan.group_name} v3",
        f"no snmp-server group {plan.group_name} v3 priv",
        *(
            f"no snmp-server view {plan.view_name} {oid} included"
            for oid in reversed(plan.device_view_oids)
        ),
    )


def render_junos_provisioning(
    plan: SnmpProvisioningPlan, credentials: SnmpProvisioningCredentials
) -> SecretRenderedArtifact:
    if plan.platform != "junos" or credentials.username != plan.username:
        raise SnmpProvisioningError("Junos SNMP runtime identity rejected")
    configuration = ElementTree.Element("configuration")
    snmp = ElementTree.SubElement(configuration, "snmp")
    view = ElementTree.SubElement(snmp, "view")
    ElementTree.SubElement(view, "name").text = plan.view_name
    for oid in plan.device_view_oids:
        entry = ElementTree.SubElement(view, "oid")
        ElementTree.SubElement(entry, "name").text = oid
        ElementTree.SubElement(entry, "include")
    v3 = ElementTree.SubElement(snmp, "v3")
    usm = ElementTree.SubElement(v3, "usm")
    local = ElementTree.SubElement(usm, "local-engine")
    user = ElementTree.SubElement(local, "user")
    ElementTree.SubElement(user, "name").text = plan.username
    authentication = ElementTree.SubElement(user, "authentication-sha256")
    ElementTree.SubElement(
        authentication, "authentication-password"
    ).text = credentials.authentication_secret
    privacy = ElementTree.SubElement(user, "privacy-aes128")
    ElementTree.SubElement(
        privacy, "privacy-password"
    ).text = credentials.privacy_secret
    vacm = ElementTree.SubElement(v3, "vacm")
    mapping = ElementTree.SubElement(vacm, "security-to-group")
    model = ElementTree.SubElement(mapping, "security-model")
    ElementTree.SubElement(model, "name").text = "usm"
    security_name = ElementTree.SubElement(model, "security-name")
    ElementTree.SubElement(security_name, "name").text = plan.username
    ElementTree.SubElement(security_name, "group").text = plan.group_name
    access = ElementTree.SubElement(vacm, "access")
    group = ElementTree.SubElement(access, "group")
    ElementTree.SubElement(group, "name").text = plan.group_name
    context = ElementTree.SubElement(group, "default-context-prefix")
    access_model = ElementTree.SubElement(context, "security-model")
    ElementTree.SubElement(access_model, "name").text = "usm"
    level = ElementTree.SubElement(access_model, "security-level")
    ElementTree.SubElement(level, "name").text = "privacy"
    ElementTree.SubElement(level, "context-match").text = "exact"
    ElementTree.SubElement(level, "read-view").text = plan.view_name
    return SecretRenderedArtifact(
        "junos", plan, ElementTree.tostring(configuration, encoding="unicode")
    )


def junos_recovery_xml(plan: SnmpProvisioningPlan) -> str:
    """Delete only exact user mapping, access group, and view names."""
    if plan.platform != "junos":
        raise SnmpProvisioningError("Junos SNMP recovery plan rejected")
    configuration = ElementTree.Element("configuration")
    snmp = ElementTree.SubElement(configuration, "snmp")
    for name in ("view", "v3"):
        ElementTree.SubElement(snmp, name)
    view = snmp.find("view")
    assert view is not None
    view.set("delete", "delete")
    ElementTree.SubElement(view, "name").text = plan.view_name
    v3 = snmp.find("v3")
    assert v3 is not None
    usm = ElementTree.SubElement(v3, "usm")
    local = ElementTree.SubElement(usm, "local-engine")
    user = ElementTree.SubElement(local, "user", {"delete": "delete"})
    ElementTree.SubElement(user, "name").text = plan.username
    vacm = ElementTree.SubElement(v3, "vacm")
    mapping = ElementTree.SubElement(vacm, "security-to-group")
    model = ElementTree.SubElement(mapping, "security-model")
    ElementTree.SubElement(model, "name").text = "usm"
    security = ElementTree.SubElement(model, "security-name", {"delete": "delete"})
    ElementTree.SubElement(security, "name").text = plan.username
    access = ElementTree.SubElement(vacm, "access")
    group = ElementTree.SubElement(access, "group", {"delete": "delete"})
    ElementTree.SubElement(group, "name").text = plan.group_name
    return ElementTree.tostring(configuration, encoding="unicode")


class SnmpProvisioningStage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    attempted: bool = False
    succeeded: bool | None = None
    disposition: SnmpOwnedStateDisposition | None = None
    message: str = Field(min_length=1, max_length=256)


class SnmpProvisioningRecord(BaseModel):
    """Bounded non-secret evidence for one protected provisioning attempt."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal["1"] = "1"
    generated_at: datetime
    change_id: ChangeId
    plan_digest: Sha256
    approval_digest: Sha256
    device: NetBoxDeviceIdentity
    platform: Literal["cisco_iosxe", "junos"]
    generation: str
    username: BoundedName
    credential_reference: str
    view_name: BoundedName
    group_name: BoundedName
    oid_closure_digest: Sha256
    preflight: SnmpProvisioningStage
    execution: SnmpProvisioningStage
    post_validation: SnmpProvisioningStage
    recovery: SnmpProvisioningStage
    final_outcome: SnmpProvisioningOutcome

    @model_validator(mode="after")
    def no_secret_field_names(self) -> SnmpProvisioningRecord:
        serialized = self.model_dump_json().casefold()
        for field in (
            "authentication_secret",
            "privacy_secret",
            "password",
            "localized",
        ):
            if field in serialized:
                raise ValueError("SNMP provisioning evidence contains forbidden field")
        return self


SnmpPreflightSubject = SnmpV3InterfaceTelemetryIntent | SnmpProvisioningPlan


def cisco_preflight_commands(plan: SnmpPreflightSubject) -> tuple[str, ...]:
    """Return only bounded read commands needed for owned-name inspection."""
    if plan.platform != "cisco_iosxe":
        raise SnmpProvisioningError("Cisco SNMP preflight plan rejected")
    return (
        "show snmp engineID",
        "show snmp view",
        "show snmp group",
        f"show snmp user {plan.username}",
    )


def parse_cisco_snmp_state(
    plan: SnmpPreflightSubject,
    *,
    observed_hostname: str,
    engine_output: str,
    view_output: str,
    group_output: str,
    user_output: str,
) -> SnmpOwnedObjectState:
    """Immediately reduce targeted IOS output to secret-free owned-name facts."""
    if plan.platform != "cisco_iosxe":
        raise SnmpProvisioningError("Cisco SNMP preflight plan rejected")
    engine = bool(re.search(r"(?im)^\s*(?:Local )?SNMP engineID\s*:", engine_output))
    symbolic_oids = {
        "sysUpTime": "1.3.6.1.2.1.1.3",
        "ifNumber": "1.3.6.1.2.1.2.1",
        "ifTableLastChange": "1.3.6.1.2.1.31.1.5",
        "ifIndex": "1.3.6.1.2.1.2.2.1.1",
        "ifName": "1.3.6.1.2.1.31.1.1.1.1",
        "ifCounterDiscontinuityTime": "1.3.6.1.2.1.31.1.1.1.19",
        "ifAdminStatus": "1.3.6.1.2.1.2.2.1.7",
        "ifOperStatus": "1.3.6.1.2.1.2.2.1.8",
        "ifHighSpeed": "1.3.6.1.2.1.31.1.1.1.15",
        "ifHCInOctets": "1.3.6.1.2.1.31.1.1.1.6",
        "ifHCOutOctets": "1.3.6.1.2.1.31.1.1.1.10",
        "ifInErrors": "1.3.6.1.2.1.2.2.1.14",
        "ifOutErrors": "1.3.6.1.2.1.2.2.1.20",
        "ifInDiscards": "1.3.6.1.2.1.2.2.1.13",
        "ifOutDiscards": "1.3.6.1.2.1.2.2.1.19",
    }
    symbol_to_oid = {name.casefold(): oid for name, oid in symbolic_oids.items()}
    symbol_to_oid.update(
        {
            f"SNMPv2-MIB::{name}".casefold(): oid
            for name, oid in symbolic_oids.items()
            if name in {"sysUpTime"}
        }
    )
    symbol_to_oid.update(
        {
            f"IF-MIB::{name}".casefold(): oid
            for name, oid in symbolic_oids.items()
            if name not in {"sysUpTime"}
        }
    )

    def canonical_oid(value: str) -> str | None:
        if re.fullmatch(r"[0-9]+(?:\.[0-9]+)*", value):
            return value
        return symbol_to_oid.get(value.casefold())

    view_oids: list[str] = []
    view_named = False
    in_view = False
    for line in view_output.splitlines():
        header = re.match(r"^\s*View name:\s*(\S+)\s*$", line, re.IGNORECASE)
        if header:
            in_view = header.group(1) == plan.view_name
            view_named |= in_view
            continue
        match = re.match(
            rf"^\s*(?:{re.escape(plan.view_name)}\s+)?(\S+)\s+(?:-\s+)?(included|excluded)\b",
            line,
            re.IGNORECASE,
        )
        if not match or (not in_view and not line.lstrip().startswith(plan.view_name)):
            continue
        if line.lstrip().startswith(plan.view_name):
            view_named = True
        value = canonical_oid(match.group(1))
        view_oids.append(
            value
            if value is not None and match.group(2).lower() == "included"
            else "<invalid>"
        )
    view_lines = set(view_oids)
    view_valid = len(view_oids) == len(view_lines) and "<invalid>" not in view_lines
    if not view_named:
        view = SnmpOwnedStateDisposition.ABSENT
    elif view_valid and view_lines == set(plan.device_view_oids):
        view = SnmpOwnedStateDisposition.EXACT_NCDP_STATE
    else:
        view = SnmpOwnedStateDisposition.CONFLICT
    group_blocks = re.findall(
        rf"(?ims)groupname:\s*{re.escape(plan.group_name)}\b(.*?)(?=\ngroupname:|\Z)",
        group_output,
    )
    if not group_blocks:
        group = SnmpOwnedStateDisposition.ABSENT
    elif len(group_blocks) != 1:
        group = SnmpOwnedStateDisposition.CONFLICT
    else:
        block = group_blocks[0]
        exact = (
            re.search(r"security model:\s*v3\s+priv\b", block, re.IGNORECASE)
            and re.search(
                rf"readview\s*:\s*{re.escape(plan.view_name)}\b", block, re.IGNORECASE
            )
            and not re.search(r"writeview\s*:\s*(?!<no|none|$)\S", block, re.IGNORECASE)
            and not re.search(
                r"notifyview\s*:\s*(?!<no|none|$)\S", block, re.IGNORECASE
            )
        )
        group = (
            SnmpOwnedStateDisposition.EXACT_NCDP_STATE
            if exact
            else SnmpOwnedStateDisposition.CONFLICT
        )
    user_blocks = re.findall(
        rf"(?ims)User name:\s*{re.escape(plan.username)}\s*(.*?)(?=\nUser name:|\Z)",
        user_output,
    )
    if not user_blocks:
        user = SnmpOwnedStateDisposition.ABSENT
    elif len(user_blocks) != 1:
        user = SnmpOwnedStateDisposition.CONFLICT
    else:
        block = user_blocks[0]
        exact = (
            re.search(
                r"Authentication Protocol:\s*(?:SHA-2\s*256|SHA256)\b",
                block,
                re.IGNORECASE,
            )
            and re.search(r"Privacy Protocol:\s*AES128\b", block, re.IGNORECASE)
            and re.search(
                rf"Group-name:\s*{re.escape(plan.group_name)}\b", block, re.IGNORECASE
            )
        )
        user = (
            SnmpOwnedStateDisposition.EXACT_NCDP_STATE
            if exact
            else SnmpOwnedStateDisposition.CONFLICT
        )
    return SnmpOwnedObjectState(
        observed_hostname=observed_hostname,
        local_engine_id_present=engine,
        view=view,
        group=group,
        user=user,
        foreign_objects_present=False,
    )


def junos_snmp_filter(plan: SnmpPreflightSubject) -> str:
    """Target only the three deterministic owned names plus local engine identity."""
    if plan.platform != "junos":
        raise SnmpProvisioningError("Junos SNMP preflight plan rejected")
    configuration = ElementTree.Element("configuration")
    snmp = ElementTree.SubElement(configuration, "snmp")
    ElementTree.SubElement(snmp, "engine-id")
    view = ElementTree.SubElement(snmp, "view")
    ElementTree.SubElement(view, "name").text = plan.view_name
    v3 = ElementTree.SubElement(snmp, "v3")
    usm = ElementTree.SubElement(v3, "usm")
    local = ElementTree.SubElement(usm, "local-engine")
    user = ElementTree.SubElement(local, "user")
    ElementTree.SubElement(user, "name").text = plan.username
    vacm = ElementTree.SubElement(v3, "vacm")
    mapping = ElementTree.SubElement(vacm, "security-to-group")
    model = ElementTree.SubElement(mapping, "security-model")
    ElementTree.SubElement(model, "name").text = "usm"
    security = ElementTree.SubElement(model, "security-name")
    ElementTree.SubElement(security, "name").text = plan.username
    access = ElementTree.SubElement(vacm, "access")
    group = ElementTree.SubElement(access, "group")
    ElementTree.SubElement(group, "name").text = plan.group_name
    return ElementTree.tostring(configuration, encoding="unicode")


def parse_junos_snmp_state(
    plan: SnmpPreflightSubject,
    *,
    observed_hostname: str,
    local_engine_id_present: bool,
    configuration_xml: str,
) -> SnmpOwnedObjectState:
    """Discard localized-key XML after reducing it to bounded normalized facts."""
    if plan.platform != "junos":
        raise SnmpProvisioningError("Junos SNMP preflight plan rejected")
    try:
        root = ElementTree.fromstring(configuration_xml)
    except ElementTree.ParseError:
        raise SnmpProvisioningError("Junos SNMP preflight response rejected") from None
    snmp = next(
        (element for element in root.iter() if _local_name(element.tag) == "snmp"), None
    )
    if snmp is None:
        return SnmpOwnedObjectState(
            observed_hostname=observed_hostname,
            local_engine_id_present=local_engine_id_present,
            view="ABSENT",
            group="ABSENT",
            user="ABSENT",
        )
    views = [
        element
        for element in snmp
        if _local_name(element.tag) == "view"
        and _child_value(element, "name") == plan.view_name
    ]
    if not views:
        view = SnmpOwnedStateDisposition.ABSENT
    elif len(views) != 1:
        view = SnmpOwnedStateDisposition.CONFLICT
    else:
        entries = {
            _child_value(element, "name")
            for element in views[0]
            if _local_name(element.tag) == "oid"
        }
        view = (
            SnmpOwnedStateDisposition.EXACT_NCDP_STATE
            if entries == set(plan.device_view_oids)
            else SnmpOwnedStateDisposition.CONFLICT
        )
    users = [
        element
        for element in snmp.iter()
        if _local_name(element.tag) == "user"
        and _child_value(element, "name") == plan.username
    ]
    if not users:
        user = SnmpOwnedStateDisposition.ABSENT
    elif len(users) != 1:
        user = SnmpOwnedStateDisposition.CONFLICT
    else:
        tags = {_local_name(element.tag) for element in users[0].iter()}
        user = (
            SnmpOwnedStateDisposition.EXACT_NCDP_STATE
            if {"authentication-sha256", "privacy-aes128"}.issubset(tags)
            else SnmpOwnedStateDisposition.CONFLICT
        )
    access_groups = [
        element
        for element in snmp.iter()
        if _local_name(element.tag) == "group"
        and _child_value(element, "name") == plan.group_name
    ]
    mappings = [
        element
        for element in snmp.iter()
        if _local_name(element.tag) == "security-name"
        and _child_value(element, "name") == plan.username
    ]
    if not access_groups and not mappings:
        group = SnmpOwnedStateDisposition.ABSENT
    elif len(access_groups) != 1 or len(mappings) != 1:
        group = SnmpOwnedStateDisposition.CONFLICT
    else:
        access = access_groups[0]
        levels = [
            element
            for element in access.iter()
            if _local_name(element.tag) == "security-level"
        ]
        exact = (
            len(levels) == 1
            and _child_value(levels[0], "name") == "privacy"
            and _child_value(levels[0], "read-view") == plan.view_name
            and not any(
                _local_name(element.tag) in {"write-view", "notify-view"}
                for element in levels[0].iter()
            )
            and _child_value(mappings[0], "group") == plan.group_name
        )
        group = (
            SnmpOwnedStateDisposition.EXACT_NCDP_STATE
            if exact
            else SnmpOwnedStateDisposition.CONFLICT
        )
    return SnmpOwnedObjectState(
        observed_hostname=observed_hostname,
        local_engine_id_present=local_engine_id_present,
        view=view,
        group=group,
        user=user,
        foreign_objects_present=False,
    )


def _local_name(tag: object) -> str:
    return str(tag).rsplit("}", 1)[-1]


def _child_value(element: ElementTree.Element, name: str) -> str | None:
    for child in element:
        if _local_name(child.tag) == name and child.text and child.text.strip():
            return child.text.strip()
    return None
