"""Read-only desired-state vertical for the exact B4-4 ACL security policy."""

from __future__ import annotations

import ipaddress
import os
import re
import uuid
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from network_change_delivery.ansible_adapter import (
    AclReadScope,
    AnsibleRunnerCiscoAdapter,
    ProviderError,
)
from network_change_delivery.architecture_contracts import (
    AutomationProfileID,
    ManagedField,
    ManagedOwnershipEnvelope,
    ManagedScopeIdentity,
    ManagedScopeKind,
    ManagedVertical,
    Sha256Digest,
    StableInterfaceIdentity,
)
from network_change_delivery.assurance import (
    AssuranceOutcome,
    AssuranceProviderError,
    InvariantResult,
    PreparedSnapshot,
    prepare_snapshot_with_layer1,
    prepare_snapshot_with_layer1_from_bytes,
)
from network_change_delivery.audit import canonical_json_bytes, sha256_identity
from network_change_delivery.ospf_triangle import OspfDesiredState, OspfTriangleIntent
from network_change_delivery.profile_inventory import (
    ProfiledInventoryDevice,
    ProfiledInventoryPopulation,
)
from network_change_delivery.reference_data_plane import (
    ACCEPTED_REFERENCE_ALLOCATION_DIGEST,
    ReferenceDataPlaneAllocation,
    reference_allocation_digest,
)
from network_change_delivery.reference_vlan_service import (
    ACCEPTED_VLAN_SERVICE_ALLOCATION_DIGEST,
    ReferenceVlanServiceAllocation,
    vlan_service_allocation_digest,
)
from network_change_delivery.routed_underlay import (
    ACCEPTED_ROUTED_UNDERLAY_D1_DIGEST,
    RoutedUnderlayDesiredState,
    RoutedUnderlayIntent,
)
from network_change_delivery.secrets import DeviceCredentials
from network_change_delivery.vlan_service import (
    ACCEPTED_VLAN_CANDIDATE_DIGEST,
    ACCEPTED_VLAN_D1_DIGEST,
    ASSURANCE_FIXTURE_HOSTS,
    MANAGED_NETWORK_NODES,
    MODELED_NODES,
    VLAN_COMBINED_INVARIANTS,
    BatfishVlanAdapter,
    VlanBatfishObservation,
    VlanDesiredState,
    VlanServiceIntent,
    VlanTrace,
    build_vlan_candidate_snapshot,
    evaluate_vlan_assurance,
)

ACL_POLICY_IDENTITY = "git:policy:users-servers-https"
ACL_NAME = "NCDP-SERVERS-PROTECT-OUT"
ACL_TARGET_DEVICE = "netbox:dcim.device:1"
ACL_TARGET_INTERFACE_IDENTITY = "netbox:dcim.interface:22"
ACL_TARGET_INTERFACE_NAME = "GigabitEthernet3.20"
ACL_USERS_PREFIX_IDENTITY = "netbox:ipam.prefix:6"
ACL_SERVERS_PREFIX_IDENTITY = "netbox:ipam.prefix:7"
OSPF_D1_DIGEST = (
    "sha256:55f5718089228eb4e9f3badebca036135461c10b3c4312184462b5468d463182"
)
ACCEPTED_ACL_D1_DIGEST = (
    "sha256:e4b8c5485d87476b4132351f5a9059bd7f9603a5205966834e9220ab70349b0d"
)
ACCEPTED_ACL_CANDIDATE_DIGEST = (
    "sha256:afa5422fdd6c230693fda6c7ae05648251fbdc5468f0e5c415b236eb3506be36"
)
ACL_SHARED_INVARIANTS = VLAN_COMBINED_INVARIANTS[:26]
ACL_SECURITY_INVARIANTS = (
    "acl_accepted_b4_3_baseline",
    "acl_exact_policy",
    "acl_exact_attachment",
    "acl_exact_rule_order",
    "acl_default_permit",
    "acl_management_excluded",
    "acl_baseline_https_open",
    "acl_https_preserved",
    "acl_baseline_ssh_open",
    "acl_ssh_blocked",
    "acl_baseline_icmp_open",
    "acl_icmp_blocked",
    "acl_reverse_direction_preserved",
    "acl_gateways_preserved",
)
ACL_COMBINED_INVARIANTS = (*ACL_SHARED_INVARIANTS, *ACL_SECURITY_INVARIANTS)


class AclAction(StrEnum):
    PERMIT = "permit"
    DENY = "deny"


class AclProtocol(StrEnum):
    IP = "ip"
    TCP = "tcp"


class AclDirection(StrEnum):
    OUT = "out"


class AclAddressMatch(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    prefix_identity: str | None = None
    prefix: ipaddress.IPv4Network | None = None
    any: bool = False

    @model_validator(mode="after")
    def exact_shape(self) -> AclAddressMatch:
        if self.any != (self.prefix_identity is None and self.prefix is None):
            raise ValueError("ACL address match is ambiguous")
        if not self.any and not self.prefix_identity:
            raise ValueError("ACL prefix identity is missing")
        return self


class AclRuleIntent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    sequence: Literal[10, 20, 30]
    action: AclAction
    protocol: AclProtocol
    source: AclAddressMatch
    destination: AclAddressMatch
    destination_port: Literal[443] | None = None

    @model_validator(mode="after")
    def port_matches_protocol(self) -> AclRuleIntent:
        if (self.destination_port is not None) != (self.protocol is AclProtocol.TCP):
            raise ValueError("ACL destination port does not match protocol")
        return self


class AclAttachmentIntent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    device_identity: Literal["netbox:dcim.device:1"] = ACL_TARGET_DEVICE
    interface: StableInterfaceIdentity
    direction: Literal[AclDirection.OUT] = AclDirection.OUT


def _expected_rules(vlan: ReferenceVlanServiceAllocation) -> tuple[AclRuleIntent, ...]:
    users, servers = vlan.gateways
    return (
        AclRuleIntent(
            sequence=10,
            action=AclAction.PERMIT,
            protocol=AclProtocol.TCP,
            source=AclAddressMatch(
                prefix_identity=users.prefix_identity, prefix=users.prefix
            ),
            destination=AclAddressMatch(
                prefix_identity=servers.prefix_identity, prefix=servers.prefix
            ),
            destination_port=443,
        ),
        AclRuleIntent(
            sequence=20,
            action=AclAction.DENY,
            protocol=AclProtocol.IP,
            source=AclAddressMatch(
                prefix_identity=users.prefix_identity, prefix=users.prefix
            ),
            destination=AclAddressMatch(
                prefix_identity=servers.prefix_identity, prefix=servers.prefix
            ),
        ),
        AclRuleIntent(
            sequence=30,
            action=AclAction.PERMIT,
            protocol=AclProtocol.IP,
            source=AclAddressMatch(any=True),
            destination=AclAddressMatch(any=True),
        ),
    )


class AclSecurityIntent(BaseModel):
    """Exact Git-owned USERS-to-SERVERS policy over accepted NetBox facts."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal["1"] = "1"
    source_data_plane: ReferenceDataPlaneAllocation
    source_vlan_service: ReferenceVlanServiceAllocation
    vlan_d1_dependency: Literal[ACCEPTED_VLAN_D1_DIGEST]
    policy_identity: Literal["git:policy:users-servers-https"] = ACL_POLICY_IDENTITY
    policy_name: Literal["NCDP-SERVERS-PROTECT-OUT"] = ACL_NAME
    rules: tuple[AclRuleIntent, AclRuleIntent, AclRuleIntent]
    attachment: AclAttachmentIntent

    @classmethod
    def from_allocations(
        cls,
        data_plane: ReferenceDataPlaneAllocation,
        vlan: ReferenceVlanServiceAllocation,
        vlan_desired: VlanDesiredState,
    ) -> AclSecurityIntent:
        return cls(
            source_data_plane=data_plane,
            source_vlan_service=vlan,
            vlan_d1_dependency=vlan_desired.digest,
            rules=_expected_rules(vlan),
            attachment=AclAttachmentIntent(
                interface=vlan.gateways[1].gateway_interface
            ),
        )

    @model_validator(mode="after")
    def exact_policy(self) -> AclSecurityIntent:
        if (
            reference_allocation_digest(self.source_data_plane)
            != ACCEPTED_REFERENCE_ALLOCATION_DIGEST
            or vlan_service_allocation_digest(self.source_vlan_service)
            != ACCEPTED_VLAN_SERVICE_ALLOCATION_DIGEST
            or self.vlan_d1_dependency != ACCEPTED_VLAN_D1_DIGEST
            or self.rules != _expected_rules(self.source_vlan_service)
            or self.attachment.interface
            != self.source_vlan_service.gateways[1].gateway_interface
            or self.attachment.interface.interface != ACL_TARGET_INTERFACE_IDENTITY
        ):
            raise ValueError("ACL intent is detached from accepted authority")
        return self


class AclDesiredState(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal["1"] = "1"
    source_data_plane_digest: Literal[ACCEPTED_REFERENCE_ALLOCATION_DIGEST]
    source_vlan_service_digest: Literal[ACCEPTED_VLAN_SERVICE_ALLOCATION_DIGEST]
    vlan_d1_dependency: Literal[ACCEPTED_VLAN_D1_DIGEST]
    policy_identity: Literal["git:policy:users-servers-https"]
    policy_name: Literal["NCDP-SERVERS-PROTECT-OUT"]
    rules: tuple[AclRuleIntent, AclRuleIntent, AclRuleIntent]
    attachment: AclAttachmentIntent
    effective_default_action: Literal[AclAction.PERMIT] = AclAction.PERMIT
    digest: Sha256Digest

    def calculated_digest(self) -> str:
        return sha256_identity(
            canonical_json_bytes(self.model_dump(mode="json", exclude={"digest"}))
        )

    @model_validator(mode="after")
    def exact_desired(self) -> AclDesiredState:
        if (
            self.digest != self.calculated_digest()
            or self.digest != ACCEPTED_ACL_D1_DIGEST
        ):
            raise ValueError("ACL desired-state digest is invalid")
        return self


def build_acl_desired_state(intent: AclSecurityIntent) -> AclDesiredState:
    unsigned = AclDesiredState.model_construct(
        schema_version="1",
        source_data_plane_digest=reference_allocation_digest(intent.source_data_plane),
        source_vlan_service_digest=vlan_service_allocation_digest(
            intent.source_vlan_service
        ),
        vlan_d1_dependency=intent.vlan_d1_dependency,
        policy_identity=intent.policy_identity,
        policy_name=intent.policy_name,
        rules=intent.rules,
        attachment=intent.attachment,
        effective_default_action=AclAction.PERMIT,
        digest="sha256:" + "0" * 64,
    )
    return AclDesiredState.model_validate(
        unsigned.model_copy(update={"digest": unsigned.calculated_digest()})
    )


def build_acl_ownership_envelope(intent: AclSecurityIntent) -> ManagedOwnershipEnvelope:
    return ManagedOwnershipEnvelope(
        vertical=ManagedVertical.ACL,
        envelope_version=1,
        targets=(ACL_TARGET_DEVICE,),
        scope=(
            ManagedScopeIdentity(
                kind=ManagedScopeKind.DEVICE, identity=ACL_TARGET_DEVICE
            ),
            ManagedScopeIdentity(
                kind=ManagedScopeKind.INTERFACE,
                identity=intent.attachment.interface.interface,
            ),
            ManagedScopeIdentity(
                kind=ManagedScopeKind.PREFIX, identity=ACL_USERS_PREFIX_IDENTITY
            ),
            ManagedScopeIdentity(
                kind=ManagedScopeKind.PREFIX, identity=ACL_SERVERS_PREFIX_IDENTITY
            ),
            ManagedScopeIdentity(
                kind=ManagedScopeKind.POLICY, identity=ACL_POLICY_IDENTITY
            ),
        ),
        normalized_fields=(
            ManagedField.ACL_RULE_SEMANTICS,
            ManagedField.ACL_RULE_ORDER,
            ManagedField.ACL_ATTACHMENT,
            ManagedField.ACL_DIRECTION,
            ManagedField.ACL_DEFAULT_ACTION,
        ),
    )


class ObservedAclAttachment(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    interface_name: str
    acl_name: str
    direction: Literal["in", "out"]


class AclObservation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal["1"] = "1"
    observed_at: datetime
    policy_present: bool
    reserved_acl_names: tuple[str, ...] = ()
    rules: tuple[AclRuleIntent, ...] = ()
    attachments: tuple[ObservedAclAttachment, ...] = ()

    @model_validator(mode="after")
    def absent_or_exact(self) -> AclObservation:
        absent = (
            not self.policy_present
            and not self.reserved_acl_names
            and not self.rules
            and not self.attachments
        )
        exact = (
            self.policy_present
            and self.reserved_acl_names == (ACL_NAME,)
            and tuple(item.sequence for item in self.rules) == (10, 20, 30)
            and self.attachments
            == (
                ObservedAclAttachment(
                    interface_name=ACL_TARGET_INTERFACE_NAME,
                    acl_name=ACL_NAME,
                    direction="out",
                ),
            )
        )
        if not (absent or exact):
            raise ValueError("ACL observation conflicts with managed namespace")
        return self

    def managed_state_digest(self) -> str:
        return sha256_identity(
            canonical_json_bytes(self.model_dump(mode="json", exclude={"observed_at"}))
        )


def _rule_cli(rule: AclRuleIntent) -> str:
    def address(value: AclAddressMatch) -> str:
        if value.any:
            return "any"
        assert value.prefix is not None
        return f"{value.prefix.network_address} {value.prefix.hostmask}"

    result = (
        f"{rule.sequence} {rule.action.value} {rule.protocol.value} "
        f"{address(rule.source)} {address(rule.destination)}"
    )
    if rule.destination_port is not None:
        result += f" eq {rule.destination_port}"
    return result


def parse_acl_observation(
    intent: AclSecurityIntent, raw: tuple[str, ...]
) -> AclObservation:
    if len(raw) != 4 or any("% Invalid input" in item for item in raw):
        raise ProviderError("ACL read-only result was incomplete")
    names_raw, policy_raw, service_interfaces_raw, attachment_map_raw = raw
    names = tuple(
        sorted(
            set(
                re.findall(
                    r"^ip access-list extended (NCDP-[A-Z0-9-]+)\s*$",
                    names_raw,
                    re.MULTILINE,
                )
            )
        )
    )
    if set(names) - {ACL_NAME}:
        raise ProviderError("another reserved NCDP ACL exists")
    expected_lines = tuple(_rule_cli(rule) for rule in intent.rules)
    normalized_lines = tuple(
        line.strip()
        for line in policy_raw.splitlines()
        if line.strip()
        and line.strip() != f"ip access-list extended {ACL_NAME}"
        and line.strip() != "!"
    )
    if normalized_lines and normalized_lines != expected_lines:
        raise ProviderError("managed ACL rule state conflicts")
    if bool(policy_raw.strip()) != bool(names):
        raise ProviderError("managed ACL namespace is ambiguous")

    attachments: list[ObservedAclAttachment] = []
    sections = re.split(r"(?=^interface )", service_interfaces_raw, flags=re.MULTILINE)
    for section in sections:
        header = re.match(r"^interface (\S+)", section)
        if not header:
            continue
        interface = header.group(1)
        for acl_name, direction in re.findall(
            r"^\s*ip access-group (\S+) (in|out)\s*$", section, re.MULTILINE
        ):
            if interface in {"GigabitEthernet3.10", ACL_TARGET_INTERFACE_NAME}:
                attachments.append(
                    ObservedAclAttachment(
                        interface_name=interface,
                        acl_name=acl_name,
                        direction=direction,
                    )
                )
    mapped_interfaces = tuple(
        match.group(1)
        for match in re.finditer(
            rf"^interface (\S+)(?:(?!^interface ).)*^\s*ip access-group "
            rf"{ACL_NAME} (?:in|out)\s*$",
            attachment_map_raw,
            re.MULTILINE | re.DOTALL,
        )
    )
    if mapped_interfaces and set(mapped_interfaces) != {ACL_TARGET_INTERFACE_NAME}:
        raise ProviderError("managed ACL is attached to another interface")
    try:
        return AclObservation(
            observed_at=datetime.now(UTC),
            policy_present=bool(names),
            reserved_acl_names=names,
            rules=intent.rules if normalized_lines else (),
            attachments=tuple(attachments),
        )
    except ValueError:
        raise ProviderError(
            "ACL observation conflicts with managed namespace"
        ) from None


class AclCiscoReadOnlyCollector(Protocol):
    def collect_acl_read_only(
        self,
        target: object,
        credentials: DeviceCredentials,
        scope: AclReadScope,
        *,
        ssh_type: Literal["paramiko"],
    ) -> tuple[str, ...]: ...


class ProfileAclReadOnlyAdapter:
    """Exact profile-bound ACL collector with no write surface."""

    def __init__(
        self,
        *,
        known_hosts: Path | None = None,
        cisco: AclCiscoReadOnlyCollector | None = None,
    ) -> None:
        self._cisco = cisco or AnsibleRunnerCiscoAdapter(known_hosts=known_hosts)

    def collect(
        self,
        device: ProfiledInventoryDevice,
        credentials: DeviceCredentials,
        intent: AclSecurityIntent,
    ) -> AclObservation:
        if (
            device.logical_name != "core-02"
            or device.automation_profile_id is not AutomationProfileID.CAT8000V_IOSXE
        ):
            raise ProviderError("profile is not admitted for ACL observation")
        raw = self._cisco.collect_acl_read_only(
            device.live_read_only_target(),
            credentials,
            AclReadScope.SECURITY_POLICY,
            ssh_type="paramiko",
        )
        return parse_acl_observation(intent, raw)


class AclSecretProvider(Protocol):
    def load(self, device: ProfiledInventoryDevice) -> DeviceCredentials: ...


def collect_acl_observation(
    intent: AclSecurityIntent,
    devices: ProfiledInventoryPopulation,
    secrets: AclSecretProvider,
    adapter: ProfileAclReadOnlyAdapter | None = None,
) -> AclObservation:
    by_name = {item.logical_name: item for item in devices.devices}
    if set(by_name) != set(MANAGED_NETWORK_NODES):
        raise ProviderError("profiled ACL inventory population is not exact")
    core = by_name["core-02"]
    return (adapter or ProfileAclReadOnlyAdapter()).collect(
        core, secrets.load(core), intent
    )


class AclRenderedTarget(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    device_identity: Literal["netbox:dcim.device:1"] = ACL_TARGET_DEVICE
    logical_name: Literal["core-02"] = "core-02"
    automation_profile_id: Literal[AutomationProfileID.CAT8000V_IOSXE] = (
        AutomationProfileID.CAT8000V_IOSXE
    )
    observed_managed_state_digest: Sha256Digest
    proposed_acl_digest: Sha256Digest
    no_op: bool
    payload: str

    @model_validator(mode="after")
    def no_op_matches_payload(self) -> AclRenderedTarget:
        if self.no_op != (self.payload == ""):
            raise ValueError("ACL rendered target no-op state is inconsistent")
        return self


def _desired_cli(desired: AclDesiredState) -> str:
    lines = [f"ip access-list extended {desired.policy_name}"]
    lines.extend(f" {_rule_cli(rule)}" for rule in desired.rules)
    lines.extend(
        (
            f"interface {desired.attachment.interface.name}",
            f" ip access-group {desired.policy_name} "
            f"{desired.attachment.direction.value}",
        )
    )
    return "\n".join(lines) + "\n"


def render_acl_changes(
    intent: AclSecurityIntent,
    observation: AclObservation,
    desired: AclDesiredState,
) -> AclRenderedTarget:
    if desired != build_acl_desired_state(intent):
        raise ValueError("ACL desired state is detached from intent")
    if observation.policy_present and (
        observation.rules != desired.rules
        or observation.attachments
        != (
            ObservedAclAttachment(
                interface_name=ACL_TARGET_INTERFACE_NAME,
                acl_name=ACL_NAME,
                direction="out",
            ),
        )
    ):
        raise ValueError("observed ACL is not exactly the proposed managed state")
    exact = observation.policy_present
    return AclRenderedTarget(
        observed_managed_state_digest=observation.managed_state_digest(),
        proposed_acl_digest=desired.digest,
        no_op=exact,
        payload="" if exact else _desired_cli(desired),
    )


def build_acl_candidate_snapshot(
    underlay_intent: RoutedUnderlayIntent,
    underlay_desired: RoutedUnderlayDesiredState,
    ospf_intent: OspfTriangleIntent,
    ospf_desired: OspfDesiredState,
    vlan_intent: VlanServiceIntent,
    vlan_desired: VlanDesiredState,
    acl_intent: AclSecurityIntent,
    acl_desired: AclDesiredState,
) -> PreparedSnapshot:
    if acl_desired != build_acl_desired_state(acl_intent):
        raise ValueError("ACL candidate is detached from intent")
    with build_vlan_candidate_snapshot(
        underlay_intent,
        underlay_desired,
        ospf_intent,
        ospf_desired,
        vlan_intent,
        vlan_desired,
    ) as base:
        if base.manifest.digest != ACCEPTED_VLAN_CANDIDATE_DIGEST:
            raise ValueError("ACL baseline candidate digest is not accepted")
        files = [
            (item.relative_path, (base.root / item.relative_path).read_bytes())
            for item in base.manifest.files
        ]
    for index, (relative, content) in enumerate(files):
        if relative == "configs/core-02.cfg":
            files[index] = (relative, content + _desired_cli(acl_desired).encode())
            break
    else:
        raise ValueError("ACL candidate core configuration is missing")
    prepared = prepare_snapshot_with_layer1_from_bytes(files)
    if prepared.manifest.digest != ACCEPTED_ACL_CANDIDATE_DIGEST:
        prepared.__exit__()
        raise ValueError("ACL candidate digest changed")
    return prepared


class AclSecurityFlow(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    name: Literal[
        "users_https",
        "users_ssh",
        "users_icmp",
        "servers_to_users",
        "users_gateway",
        "servers_gateway",
    ]
    reported_trace_count: int = Field(ge=0, le=32)
    traces: tuple[VlanTrace, ...] = Field(max_length=32)

    @model_validator(mode="after")
    def complete(self) -> AclSecurityFlow:
        if self.reported_trace_count != len(self.traces):
            raise ValueError("Batfish ACL trace collection was truncated")
        return self


class BatfishAclLine(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    filter_name: str
    line_index: int = Field(ge=0)
    line: str
    action: Literal["PERMIT", "DENY"]


class BatfishAclAttachment(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    interface: str
    incoming_filter: str | None = None
    outgoing_filter: str | None = None


class AclSecurityBatfishObservation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    baseline_vlan: VlanBatfishObservation
    secured_vlan: VlanBatfishObservation
    baseline_flows: tuple[AclSecurityFlow, ...]
    secured_flows: tuple[AclSecurityFlow, ...]
    acl_lines: tuple[BatfishAclLine, ...]
    acl_attachments: tuple[BatfishAclAttachment, ...]


class AclSecurityAssuranceEvidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    generated_at: datetime
    routed_underlay_digest: Literal[ACCEPTED_ROUTED_UNDERLAY_D1_DIGEST]
    ospf_digest: Literal[OSPF_D1_DIGEST]
    vlan_digest: Literal[ACCEPTED_VLAN_D1_DIGEST]
    acl_digest: Sha256Digest
    behavioral_baseline_candidate_digest: Literal[ACCEPTED_VLAN_CANDIDATE_DIGEST]
    secured_candidate_digest: Sha256Digest
    pybatfish_version: str
    batfish_version: str
    managed_network_nodes: tuple[str, ...]
    assurance_fixture_hosts: tuple[str, ...]
    modeled_nodes: tuple[str, ...]
    ospf_router_count: int
    ospf_adjacency_count: int
    vlan_count: int
    vlan_gateway_count: int
    infrastructure_layer1_edge_count: int
    assurance_fixture_edge_count: int
    total_layer1_edge_count: int
    acl_policy_count: int
    acl_rule_count: int
    acl_attachment_count: int
    baseline_flows: tuple[AclSecurityFlow, ...]
    secured_flows: tuple[AclSecurityFlow, ...]
    invariants: tuple[InvariantResult, ...]
    outcome: AssuranceOutcome

    @model_validator(mode="after")
    def consistent(self) -> AclSecurityAssuranceEvidence:
        expected_flow_names = (
            "users_https",
            "users_ssh",
            "users_icmp",
            "servers_to_users",
            "users_gateway",
            "servers_gateway",
        )
        expected = (
            AssuranceOutcome.PASSED
            if self.invariants and all(item.passed for item in self.invariants)
            else AssuranceOutcome.FAILED
        )
        if (
            self.acl_digest != ACCEPTED_ACL_D1_DIGEST
            or self.secured_candidate_digest != ACCEPTED_ACL_CANDIDATE_DIGEST
            or self.behavioral_baseline_candidate_digest
            != ACCEPTED_VLAN_CANDIDATE_DIGEST
            or self.managed_network_nodes != MANAGED_NETWORK_NODES
            or self.assurance_fixture_hosts != ASSURANCE_FIXTURE_HOSTS
            or self.modeled_nodes != MODELED_NODES
            or (self.ospf_router_count, self.ospf_adjacency_count) != (3, 3)
            or (self.vlan_count, self.vlan_gateway_count) != (2, 2)
            or (
                self.infrastructure_layer1_edge_count,
                self.assurance_fixture_edge_count,
                self.total_layer1_edge_count,
            )
            != (4, 2, 6)
            or (self.acl_policy_count, self.acl_rule_count, self.acl_attachment_count)
            != (1, 3, 1)
            or tuple(item.name for item in self.baseline_flows) != expected_flow_names
            or tuple(item.name for item in self.secured_flows) != expected_flow_names
            or tuple(item.name for item in self.invariants) != ACL_COMBINED_INVARIANTS
            or self.outcome is not expected
        ):
            raise ValueError("ACL assurance evidence is inconsistent")
        return self


class AclSecurityAssuranceProvider(Protocol):
    def analyze(
        self, baseline_candidate: Path, secured_candidate: Path
    ) -> AclSecurityBatfishObservation: ...


def _flow_rows(session: object, snapshot: str) -> tuple[AclSecurityFlow, ...]:
    definitions = (
        (
            "users_https",
            "assurance-users-probe",
            {
                "srcIps": "10.60.10.100",
                "dstIps": "10.60.20.100",
                "ipProtocols": "TCP",
                "dstPorts": "443",
            },
        ),
        (
            "users_ssh",
            "assurance-users-probe",
            {
                "srcIps": "10.60.10.100",
                "dstIps": "10.60.20.100",
                "ipProtocols": "TCP",
                "dstPorts": "22",
            },
        ),
        (
            "users_icmp",
            "assurance-users-probe",
            {"srcIps": "10.60.10.100", "dstIps": "10.60.20.100", "ipProtocols": "ICMP"},
        ),
        (
            "servers_to_users",
            "assurance-servers-probe",
            {
                "srcIps": "10.60.20.100",
                "dstIps": "10.60.10.100",
                "ipProtocols": "TCP",
                "dstPorts": "443",
            },
        ),
        (
            "users_gateway",
            "assurance-users-probe",
            {"srcIps": "10.60.10.100", "dstIps": "10.60.10.1", "ipProtocols": "ICMP"},
        ),
        (
            "servers_gateway",
            "assurance-servers-probe",
            {"srcIps": "10.60.20.100", "dstIps": "10.60.20.1", "ipProtocols": "ICMP"},
        ),
    )
    result = []
    for name, start, headers in definitions:
        rows = (
            session.q.traceroute(startLocation=start, headers=headers, maxTraces=32)
            .answer(snapshot=snapshot)
            .frame()
        )
        count = 0
        traces = []
        for _, row in rows.iterrows():
            try:
                count += int(row.get("TraceCount"))
            except (TypeError, ValueError, OverflowError):
                raise AssuranceProviderError(
                    "Batfish ACL trace count is invalid"
                ) from None
            for trace in row.get("Traces", ()):
                nodes = tuple(str(hop.node) for hop in trace.hops)
                if not nodes:
                    raise AssuranceProviderError(
                        "Batfish ACL trace has no modeled path"
                    )
                traces.append(
                    VlanTrace(
                        disposition=str(trace.disposition).upper(),
                        nodes=nodes,
                        final_node=nodes[-1],
                    )
                )
        result.append(
            AclSecurityFlow(name=name, reported_trace_count=count, traces=tuple(traces))
        )
    return tuple(result)


class BatfishAclSecurityAdapter:
    """Pinned differential Batfish analyzer for the exact B4-4 policy."""

    def __init__(self, host: str | None = None) -> None:
        self.host = host or os.environ.get("NCDP_BATFISH_HOST", "127.0.0.1")

    def analyze(
        self, baseline_candidate: Path, secured_candidate: Path
    ) -> AclSecurityBatfishObservation:
        try:
            from pybatfish.client.session import Session
        except ImportError:
            raise AssuranceProviderError(
                "Batfish provider dependency unavailable"
            ) from None
        baseline_vlan = BatfishVlanAdapter(self.host).analyze(baseline_candidate)
        secured_vlan = BatfishVlanAdapter(self.host).analyze(secured_candidate)
        try:
            session = Session(host=self.host, port=9996)
            with prepare_snapshot_with_layer1(baseline_candidate) as baseline:
                baseline_name = "ncdp-b4-acl-baseline-" + uuid.uuid4().hex
                session.init_snapshot(
                    str(baseline.root), name=baseline_name, overwrite=False
                )
                baseline_flows = _flow_rows(session, baseline_name)
            with prepare_snapshot_with_layer1(secured_candidate) as secured:
                secured_name = "ncdp-b4-acl-secured-" + uuid.uuid4().hex
                session.init_snapshot(
                    str(secured.root), name=secured_name, overwrite=False
                )
                secured_flows = _flow_rows(session, secured_name)
                interface_rows = (
                    session.q.interfaceProperties(nodes="core-02")
                    .answer(snapshot=secured_name)
                    .frame()
                    .reset_index()
                )
                attachments = []
                for _, row in interface_rows.iterrows():
                    mapping = {str(key).casefold(): value for key, value in row.items()}
                    interface = str(mapping.get("interface", ""))
                    match = re.fullmatch(r"core-02\[([^\]]+)\]", interface)
                    if not match:
                        continue
                    incoming = str(mapping.get("incoming_filter_name", "") or "")
                    outgoing = str(mapping.get("outgoing_filter_name", "") or "")
                    if ACL_NAME in {incoming, outgoing}:
                        attachments.append(
                            BatfishAclAttachment(
                                interface=match.group(1),
                                incoming_filter=incoming or None,
                                outgoing_filter=outgoing or None,
                            )
                        )
                line_rows = (
                    session.q.findMatchingFilterLines(
                        nodes="core-02", filters="/^NCDP-/", headers={}
                    )
                    .answer(snapshot=secured_name)
                    .frame()
                    .reset_index()
                )
                lines = tuple(
                    BatfishAclLine(
                        filter_name=str(row.get("Filter")),
                        line_index=int(row.get("Line_Index")),
                        line=str(row.get("Line")),
                        action=str(row.get("Action")).upper(),
                    )
                    for _, row in line_rows.iterrows()
                )
            return AclSecurityBatfishObservation(
                baseline_vlan=baseline_vlan,
                secured_vlan=secured_vlan,
                baseline_flows=baseline_flows,
                secured_flows=secured_flows,
                acl_lines=lines,
                acl_attachments=tuple(attachments),
            )
        except AssuranceProviderError:
            raise
        except Exception as error:
            raise AssuranceProviderError(
                "Batfish ACL security analysis failed"
            ) from error


def _flow_exact(
    flows: tuple[AclSecurityFlow, ...],
    name: str,
    disposition: str,
    final_node: str,
    *,
    core: bool,
) -> bool:
    flow = next((item for item in flows if item.name == name), None)
    return bool(
        flow
        and flow.traces
        and all(
            trace.disposition == disposition
            and trace.final_node == final_node
            and (("core-02" in trace.nodes) if core else True)
            and not {"edge-junos-01", "transit-ios-01"}.intersection(trace.nodes)
            for trace in flow.traces
        )
    )


def evaluate_acl_security_assurance(
    underlay: RoutedUnderlayDesiredState,
    ospf: OspfDesiredState,
    vlan: VlanDesiredState,
    acl: AclDesiredState,
    baseline_digest: str,
    secured_digest: str,
    observation: AclSecurityBatfishObservation,
) -> AclSecurityAssuranceEvidence:
    baseline = evaluate_vlan_assurance(
        underlay, ospf, vlan, baseline_digest, observation.baseline_vlan
    )
    secured_vlan = evaluate_vlan_assurance(
        underlay, ospf, vlan, ACCEPTED_VLAN_CANDIDATE_DIGEST, observation.secured_vlan
    )
    shared = tuple(
        item for item in secured_vlan.invariants if item.name in ACL_SHARED_INVARIANTS
    )
    expected_lines = tuple(_rule_cli(rule) for rule in acl.rules)
    observed_lines = tuple(item.line for item in observation.acl_lines)
    observed_actions = tuple(item.action for item in observation.acl_lines)
    attachment_exact = observation.acl_attachments == (
        BatfishAclAttachment(
            interface=ACL_TARGET_INTERFACE_NAME,
            outgoing_filter=ACL_NAME,
        ),
    )
    security = (
        InvariantResult(
            name="acl_accepted_b4_3_baseline",
            passed=baseline.outcome is AssuranceOutcome.PASSED
            and baseline.candidate_snapshot_digest == ACCEPTED_VLAN_CANDIDATE_DIGEST,
            detail="accepted B4-3 29/29 behavioral baseline is preserved",
        ),
        InvariantResult(
            name="acl_exact_policy",
            passed={item.filter_name for item in observation.acl_lines} == {ACL_NAME}
            and len(observation.acl_lines) == 3,
            detail="exact one named ACL is modeled on core-02",
        ),
        InvariantResult(
            name="acl_exact_attachment",
            passed=attachment_exact,
            detail="ACL is attached only outbound on core Gi3.20",
        ),
        InvariantResult(
            name="acl_exact_rule_order",
            passed=tuple(item.line_index for item in observation.acl_lines) == (0, 1, 2)
            and observed_lines == expected_lines,
            detail="ACL rules and order exactly match D1",
        ),
        InvariantResult(
            name="acl_default_permit",
            passed=observed_actions == ("PERMIT", "DENY", "PERMIT")
            and observed_lines[-1:] == ("30 permit ip any any",),
            detail="effective catchall remains permit ip any any",
        ),
        InvariantResult(
            name="acl_management_excluded",
            passed=all(
                item.interface != "GigabitEthernet1"
                for item in observation.acl_attachments
            ),
            detail="management interface has no managed ACL",
        ),
        InvariantResult(
            name="acl_baseline_https_open",
            passed=_flow_exact(
                observation.baseline_flows,
                "users_https",
                "ACCEPTED",
                "assurance-servers-probe",
                core=True,
            ),
            detail="B4-3 baseline permits USERS HTTPS to SERVERS",
        ),
        InvariantResult(
            name="acl_https_preserved",
            passed=_flow_exact(
                observation.secured_flows,
                "users_https",
                "ACCEPTED",
                "assurance-servers-probe",
                core=True,
            ),
            detail="secured candidate preserves USERS HTTPS to SERVERS",
        ),
        InvariantResult(
            name="acl_baseline_ssh_open",
            passed=_flow_exact(
                observation.baseline_flows,
                "users_ssh",
                "ACCEPTED",
                "assurance-servers-probe",
                core=True,
            ),
            detail="B4-3 baseline permits USERS SSH to SERVERS",
        ),
        InvariantResult(
            name="acl_ssh_blocked",
            passed=_flow_exact(
                observation.secured_flows,
                "users_ssh",
                "DENIED_OUT",
                "core-02",
                core=True,
            ),
            detail="secured candidate denies USERS SSH outbound at core",
        ),
        InvariantResult(
            name="acl_baseline_icmp_open",
            passed=_flow_exact(
                observation.baseline_flows,
                "users_icmp",
                "ACCEPTED",
                "assurance-servers-probe",
                core=True,
            ),
            detail="B4-3 baseline permits USERS ICMP to SERVERS",
        ),
        InvariantResult(
            name="acl_icmp_blocked",
            passed=_flow_exact(
                observation.secured_flows,
                "users_icmp",
                "DENIED_OUT",
                "core-02",
                core=True,
            ),
            detail="secured candidate denies USERS ICMP outbound at core",
        ),
        InvariantResult(
            name="acl_reverse_direction_preserved",
            passed=_flow_exact(
                observation.baseline_flows,
                "servers_to_users",
                "ACCEPTED",
                "assurance-users-probe",
                core=True,
            )
            and _flow_exact(
                observation.secured_flows,
                "servers_to_users",
                "ACCEPTED",
                "assurance-users-probe",
                core=True,
            ),
            detail="SERVERS-to-USERS remains permitted in both candidates",
        ),
        InvariantResult(
            name="acl_gateways_preserved",
            passed=all(
                _flow_exact(
                    observation.secured_flows, name, "ACCEPTED", "core-02", core=False
                )
                for name in ("users_gateway", "servers_gateway")
            ),
            detail="both local VLAN gateways remain reachable",
        ),
    )
    invariants = (*shared, *security)
    outcome = (
        AssuranceOutcome.PASSED
        if all(item.passed for item in invariants)
        else AssuranceOutcome.FAILED
    )
    return AclSecurityAssuranceEvidence(
        generated_at=datetime.now(UTC),
        routed_underlay_digest=underlay.digest,
        ospf_digest=ospf.digest,
        vlan_digest=vlan.digest,
        acl_digest=acl.digest,
        behavioral_baseline_candidate_digest=baseline_digest,
        secured_candidate_digest=secured_digest,
        pybatfish_version=observation.secured_vlan.ospf.underlay.pybatfish_version,
        batfish_version=observation.secured_vlan.ospf.underlay.batfish_version,
        managed_network_nodes=observation.secured_vlan.ospf.underlay.candidate_parse.nodes,
        assurance_fixture_hosts=ASSURANCE_FIXTURE_HOSTS,
        modeled_nodes=observation.secured_vlan.modeled_nodes,
        ospf_router_count=len(observation.secured_vlan.ospf.processes),
        ospf_adjacency_count=len(observation.secured_vlan.ospf.edges),
        vlan_count=2,
        vlan_gateway_count=2,
        infrastructure_layer1_edge_count=4,
        assurance_fixture_edge_count=2,
        total_layer1_edge_count=len(observation.secured_vlan.layer1_edges),
        acl_policy_count=1,
        acl_rule_count=len(observation.acl_lines),
        acl_attachment_count=len(observation.acl_attachments),
        baseline_flows=observation.baseline_flows,
        secured_flows=observation.secured_flows,
        invariants=invariants,
        outcome=outcome,
    )


def assure_acl_security_candidate(
    underlay_intent: RoutedUnderlayIntent,
    underlay_desired: RoutedUnderlayDesiredState,
    ospf_intent: OspfTriangleIntent,
    ospf_desired: OspfDesiredState,
    vlan_intent: VlanServiceIntent,
    vlan_desired: VlanDesiredState,
    acl_intent: AclSecurityIntent,
    acl_desired: AclDesiredState,
    provider: AclSecurityAssuranceProvider | None = None,
) -> AclSecurityAssuranceEvidence:
    with (
        build_vlan_candidate_snapshot(
            underlay_intent,
            underlay_desired,
            ospf_intent,
            ospf_desired,
            vlan_intent,
            vlan_desired,
        ) as baseline,
        build_acl_candidate_snapshot(
            underlay_intent,
            underlay_desired,
            ospf_intent,
            ospf_desired,
            vlan_intent,
            vlan_desired,
            acl_intent,
            acl_desired,
        ) as secured,
    ):
        observed = (provider or BatfishAclSecurityAdapter()).analyze(
            baseline.root, secured.root
        )
        return evaluate_acl_security_assurance(
            underlay_desired,
            ospf_desired,
            vlan_desired,
            acl_desired,
            baseline.manifest.digest,
            secured.manifest.digest,
            observed,
        )


class AclSecurityProposalEvidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal["1"] = "1"
    source_data_plane_digest: Literal[ACCEPTED_REFERENCE_ALLOCATION_DIGEST]
    source_vlan_service_digest: Literal[ACCEPTED_VLAN_SERVICE_ALLOCATION_DIGEST]
    vlan_d1_dependency: Literal[ACCEPTED_VLAN_D1_DIGEST]
    intent: AclSecurityIntent
    ownership_envelope: ManagedOwnershipEnvelope
    current_observation: AclObservation
    current_managed_digest: Sha256Digest
    proposed_desired_state: AclDesiredState
    rendered_target: AclRenderedTarget
    behavioral_baseline_candidate_digest: Literal[ACCEPTED_VLAN_CANDIDATE_DIGEST]
    combined_assurance: AclSecurityAssuranceEvidence
    device_writes: Literal[0] = 0

    @model_validator(mode="after")
    def bound(self) -> AclSecurityProposalEvidence:
        if (
            self.ownership_envelope != build_acl_ownership_envelope(self.intent)
            or self.current_managed_digest
            != self.current_observation.managed_state_digest()
            or self.proposed_desired_state != build_acl_desired_state(self.intent)
            or self.rendered_target
            != render_acl_changes(
                self.intent, self.current_observation, self.proposed_desired_state
            )
            or self.combined_assurance.outcome is not AssuranceOutcome.PASSED
            or self.combined_assurance.acl_digest != self.proposed_desired_state.digest
            or self.combined_assurance.behavioral_baseline_candidate_digest
            != ACCEPTED_VLAN_CANDIDATE_DIGEST
            or self.combined_assurance.managed_network_nodes != MANAGED_NETWORK_NODES
            or self.combined_assurance.assurance_fixture_hosts
            != ASSURANCE_FIXTURE_HOSTS
            or self.combined_assurance.modeled_nodes != MODELED_NODES
            or (
                self.combined_assurance.acl_policy_count,
                self.combined_assurance.acl_rule_count,
                self.combined_assurance.acl_attachment_count,
            )
            != (1, 3, 1)
        ):
            raise ValueError("ACL proposal evidence is inconsistent")
        return self


def build_acl_proposal_evidence(
    intent: AclSecurityIntent,
    observation: AclObservation,
    desired: AclDesiredState,
    assurance: AclSecurityAssuranceEvidence,
) -> AclSecurityProposalEvidence:
    return AclSecurityProposalEvidence(
        source_data_plane_digest=reference_allocation_digest(intent.source_data_plane),
        source_vlan_service_digest=vlan_service_allocation_digest(
            intent.source_vlan_service
        ),
        vlan_d1_dependency=intent.vlan_d1_dependency,
        intent=intent,
        ownership_envelope=build_acl_ownership_envelope(intent),
        current_observation=observation,
        current_managed_digest=observation.managed_state_digest(),
        proposed_desired_state=desired,
        rendered_target=render_acl_changes(intent, observation, desired),
        behavioral_baseline_candidate_digest=ACCEPTED_VLAN_CANDIDATE_DIGEST,
        combined_assurance=assurance,
    )
