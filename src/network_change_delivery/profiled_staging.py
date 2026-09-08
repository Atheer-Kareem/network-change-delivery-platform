"""Profiled scope-bound disposable CML staging lifecycle.

This module deliberately contains no deployment, candidate application, or B5
acceptance authority.  It composes only profiled inventory, realization-bound
read-only targets, strict run-scoped trust, and Terraform's disposable graph.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import time
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import StrEnum
from ipaddress import IPv4Address
from pathlib import Path
from typing import Annotated, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from network_change_delivery.architecture_contracts import (
    CML_REALIZATION_PROFILE_CATALOG,
    AutomationProfileID,
    CmlBootPolicy,
    CmlRealizationProfileID,
    ManagementService,
    NetBoxDeviceIdentity,
    NonEmptyString,
    Sha256Digest,
    StableInterfaceIdentity,
    get_automation_profile,
)
from network_change_delivery.profile_inventory import (
    STAGING_REALIZATION_SCOPE,
    NetBoxProfileInventoryProvider,
    ProfiledInventoryDevice,
    ProfiledLogicalName,
    ProfiledPopulationScope,
)
from network_change_delivery.profile_read_only_adapter import ProfileReadOnlyAdapter
from network_change_delivery.profiled_realization import (
    EvidenceReference,
    StagingRealizationContext,
)
from network_change_delivery.secrets import DeviceCredentials

PROFILED_STAGING_DEVICE_NAMES = tuple(
    m.logical_name for m in STAGING_REALIZATION_SCOPE.members
)


class ProfiledStagingError(RuntimeError):
    """Sanitized failure for one disposable profiled staging run."""


class ProfiledStagingAmbiguousError(ProfiledStagingError):
    """A mutating Terraform boundary crossed without a provable result."""


class ProfiledStagingOutcome(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CLEANUP_FAILED = "CLEANUP_FAILED"
    AMBIGUOUS = "AMBIGUOUS"


class ProfiledStagingReadinessOutcome(StrEnum):
    """Bounded profile-service readiness result for one staged device."""

    READY = "READY"
    TIMED_OUT = "TIMED_OUT"


class ProfiledStagingReadinessEvidence(BaseModel):
    """One incremental, secret-free staging readiness observation."""

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)
    device_identity: NetBoxDeviceIdentity
    logical_name: NonEmptyString
    automation_profile_id: AutomationProfileID
    cml_realization_profile_id: CmlRealizationProfileID
    cml_node_id: NonEmptyString
    management_address: IPv4Address
    readiness_service: ManagementService
    readiness_port: int = Field(ge=1, le=65535)
    outcome: ProfiledStagingReadinessOutcome
    elapsed_seconds: float = Field(ge=0, le=7200)
    readiness_evidence: EvidenceReference | None = None
    cml_node_state: str | None = Field(
        default=None,
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9._-]+$",
    )
    first_booted_seconds: float | None = Field(default=None, ge=0, le=7200)

    @model_validator(mode="after")
    def evidence_matches_outcome(self) -> ProfiledStagingReadinessEvidence:
        if (self.outcome is ProfiledStagingReadinessOutcome.READY) != (
            self.readiness_evidence is not None
        ):
            raise ValueError("profiled staging readiness evidence rejected")
        if (
            self.first_booted_seconds is not None
            and self.first_booted_seconds > self.elapsed_seconds
        ):
            raise ValueError("profiled staging readiness chronology rejected")
        return self


class ProfiledStagingDeviceEvidence(BaseModel):
    """One secret-free device validation result."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    device_identity: str
    logical_name: str
    automation_profile_id: AutomationProfileID
    cml_realization_profile_id: CmlRealizationProfileID
    cml_node_id: str
    readiness_evidence: EvidenceReference
    readiness_seconds: float = Field(ge=0, le=7200)
    readiness_service: str
    readiness_port: int = Field(ge=1, le=65535)
    read_only_collection: str
    observed_hostname: str | None = None
    interface_count: int | None = Field(default=None, ge=1, le=4096)


HistoricalStagingTimingPhase = Literal[
    "lifecycle_total",
    "create",
    "start",
    "transit_first_boot",
    "transit_persistence",
    "transit_stop",
    "transit_second_boot",
    "readiness",
    "read_only",
    "cleanup",
]


StagingTimingPhase = Literal[
    "lifecycle_total",
    "create",
    "start",
    "recycle_first_boot",
    "recycle_persistence",
    "recycle_stop",
    "recycle_second_boot",
    "readiness",
    "read_only",
    "cleanup",
]


@contextmanager
def record_staging_duration(timings: dict[str, float], phase: StagingTimingPhase):
    """Record only a closed phase and monotonic duration, including failures."""
    started = time.monotonic()
    try:
        yield
    finally:
        timings[phase] = round(time.monotonic() - started, 3)


class ProfiledStagingEvidenceV2(BaseModel):
    """Schema-v2, secret-free evidence for one profiled staging lifecycle."""

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)
    schema_version: Literal["2"] = "2"
    staging_run_id: str
    orchestrator: str
    source_commit: str | None = None
    build_id: str | None = None
    lab_id: str | None = None
    lab_title: str
    topology_digest: Sha256Digest | None = None
    context_digest: Sha256Digest | None = None
    trust_generation: EvidenceReference | None = None
    transit_recycle_outcome: Literal[
        "not_attempted",
        "attempted",
        "succeeded",
    ] = "not_attempted"
    transit_recycle_evidence: EvidenceReference | None = None
    lab_start_evidence: EvidenceReference | None = None
    readiness_deadline_seconds: Literal[180, 300] = 180
    readiness: tuple[ProfiledStagingReadinessEvidence, ...] = ()
    devices: tuple[ProfiledStagingDeviceEvidence, ...] = ()
    # Optional diagnostic durations retain compatibility with existing v2 bytes.
    # lifecycle_total includes admission and cleanup; nested phases overlap it.
    timings_seconds: dict[
        HistoricalStagingTimingPhase, Annotated[float, Field(ge=0, allow_inf_nan=False)]
    ] = Field(default_factory=dict)
    create_outcome: str = "not_attempted"
    start_outcome: str = "not_attempted"
    read_only_outcome: str = "not_attempted"
    destroy_outcome: str = "not_attempted"
    absence_verification: str = "not_attempted"
    state_retirement: str = "not_attempted"
    primary_failure: str | None = None
    cleanup_failure: str | None = None
    final_outcome: ProfiledStagingOutcome = ProfiledStagingOutcome.FAILED

    @model_validator(mode="after")
    def exact_four_when_ready(self) -> ProfiledStagingEvidenceV2:
        # Optional for historical v2 bytes; present references must be exact.
        if self.lab_start_evidence is not None and (
            self.lab_start_evidence.identity
            != f"staging-lab-start:{self.staging_run_id}"
            or self.start_outcome != "succeeded"
        ):
            raise ValueError("profiled staging lab start evidence rejected")
        if self.schema_version != "2" or not self.lab_title.startswith("NCDP Staging "):
            raise ValueError("profiled staging evidence identity rejected")
        if self.devices and tuple(item.logical_name for item in self.devices) != (
            "core-02",
            "edge-junos-01",
            "transit-ios-01",
            "access-sw-01",
        ):
            raise ValueError("profiled staging evidence population rejected")
        readiness_names = tuple(item.logical_name for item in self.readiness)
        if readiness_names != tuple(
            name
            for name in ("core-02", "edge-junos-01", "transit-ios-01", "access-sw-01")
            if name in readiness_names
        ) or len(set(readiness_names)) != len(readiness_names):
            raise ValueError("profiled staging readiness population rejected")
        expected_recycle_identity = (
            f"staging-transit-recycle:{self.staging_run_id}:transit-ios-01"
        )
        if self.transit_recycle_evidence is not None and (
            self.transit_recycle_evidence.identity != expected_recycle_identity
        ):
            raise ValueError(
                "profiled staging transit recycle evidence identity rejected"
            )
        if (self.transit_recycle_outcome == "succeeded") != (
            self.transit_recycle_evidence is not None
        ):
            raise ValueError(
                "profiled staging transit recycle evidence outcome rejected"
            )

        if self.final_outcome is ProfiledStagingOutcome.SUCCEEDED:
            if readiness_names != (
                "core-02",
                "edge-junos-01",
                "transit-ios-01",
                "access-sw-01",
            ) or any(
                item.outcome is not ProfiledStagingReadinessOutcome.READY
                for item in self.readiness
            ):
                raise ValueError("profiled staging successful readiness rejected")
            if (
                self.transit_recycle_outcome != "succeeded"
                or self.transit_recycle_evidence is None
            ):
                raise ValueError("profiled staging successful transit recycle rejected")
        return self


class ProfiledStagingRecycleEvidence(BaseModel):
    """One scoped profile-required recycle, including bounded incomplete attempts."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    device_identity: NetBoxDeviceIdentity
    logical_name: ProfiledLogicalName
    policy: Literal[CmlBootPolicy.IOSV_PERSISTENCE_RECYCLE] = (
        CmlBootPolicy.IOSV_PERSISTENCE_RECYCLE
    )
    outcome: Literal["not_attempted", "attempted", "succeeded"] = "not_attempted"
    evidence: EvidenceReference | None = None

    @model_validator(mode="after")
    def coherent(self):
        if (self.outcome == "succeeded") != (self.evidence is not None):
            raise ValueError("recycle evidence outcome rejected")
        return self


class ProfiledStagingEvidence(BaseModel):
    """Current schema-v3 scope-bound staging evidence; v2 remains historical."""

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)
    schema_version: Literal["3"] = "3"
    scope: ProfiledPopulationScope = STAGING_REALIZATION_SCOPE
    staging_run_id: str
    orchestrator: str
    source_commit: str | None = None
    build_id: str | None = None
    lab_id: str | None = None
    lab_title: str
    topology_digest: Sha256Digest | None = None
    context_digest: Sha256Digest | None = None
    trust_generation: EvidenceReference | None = None
    recycles: tuple[ProfiledStagingRecycleEvidence, ...] = ()
    lab_start_evidence: EvidenceReference | None = None
    readiness_deadline_seconds: Literal[180, 300] = 180
    readiness: tuple[ProfiledStagingReadinessEvidence, ...] = ()
    devices: tuple[ProfiledStagingDeviceEvidence, ...] = ()
    # Optional diagnostic durations aggregate the selected profile-recycle subjects.
    # lifecycle_total includes admission and cleanup; nested phases overlap it.
    timings_seconds: dict[
        StagingTimingPhase, Annotated[float, Field(ge=0, allow_inf_nan=False)]
    ] = Field(default_factory=dict)
    create_outcome: str = "not_attempted"
    start_outcome: str = "not_attempted"
    read_only_outcome: str = "not_attempted"
    destroy_outcome: str = "not_attempted"
    absence_verification: str = "not_attempted"
    state_retirement: str = "not_attempted"
    primary_failure: str | None = None
    cleanup_failure: str | None = None
    final_outcome: ProfiledStagingOutcome = ProfiledStagingOutcome.FAILED

    @model_validator(mode="after")
    def exact_scope_when_ready(self):
        if self.lab_title != f"NCDP Staging {self.staging_run_id}":
            raise ValueError("profiled staging evidence identity rejected")
        names = tuple(m.logical_name for m in self.scope.members)
        ready_names = tuple(d.logical_name for d in self.readiness)
        if ready_names != tuple(n for n in names if n in ready_names) or len(
            ready_names
        ) != len(set(ready_names)):
            raise ValueError("profiled staging readiness population rejected")
        for d in (*self.readiness, *self.devices):
            member = self.scope.declaration.member(d.logical_name)
            if member not in self.scope.members or (
                d.device_identity,
                d.automation_profile_id,
                d.cml_realization_profile_id,
            ) != (
                member.device_identity,
                member.automation_profile_id,
                member.cml_realization_profile_id,
            ):
                raise ValueError("profiled staging evidence binding rejected")
        if self.devices and tuple(d.logical_name for d in self.devices) != names:
            raise ValueError("profiled staging evidence population rejected")
        subjects = tuple(
            m
            for m in self.scope.members
            if CML_REALIZATION_PROFILE_CATALOG[m.cml_realization_profile_id].boot_policy
            is CmlBootPolicy.IOSV_PERSISTENCE_RECYCLE
        )
        if tuple(r.device_identity for r in self.recycles) != tuple(
            m.device_identity for m in subjects[: len(self.recycles)]
        ):
            raise ValueError("profiled staging recycle scope rejected")
        for r, m in zip(self.recycles, subjects, strict=False):
            if r.logical_name != m.logical_name or (
                r.evidence is not None
                and r.evidence.identity
                != f"staging-profile-recycle:{self.staging_run_id}:{m.logical_name}"
            ):
                raise ValueError("profiled staging recycle identity rejected")
        if self.lab_start_evidence is not None and (
            self.lab_start_evidence.identity
            != f"staging-lab-start:{self.staging_run_id}"
            or self.start_outcome != "succeeded"
        ):
            raise ValueError("profiled staging lab start evidence rejected")
        if self.final_outcome is ProfiledStagingOutcome.SUCCEEDED:
            if ready_names != names or any(
                d.outcome is not ProfiledStagingReadinessOutcome.READY
                for d in self.readiness
            ):
                raise ValueError("profiled staging successful readiness rejected")
            if len(self.recycles) != len(subjects) or any(
                r.outcome != "succeeded" for r in self.recycles
            ):
                raise ValueError("profiled staging successful recycle rejected")
        return self


def read_profiled_staging_evidence(
    content: bytes,
) -> ProfiledStagingEvidence | ProfiledStagingEvidenceV2:
    """Exact version dispatch; historical transit evidence is never rewritten."""
    value = json.loads(content)
    if value.get("schema_version") == "2":
        return ProfiledStagingEvidenceV2.model_validate(value)
    return ProfiledStagingEvidence.model_validate(value)


def _sha256(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def profiled_staging_topology() -> dict[str, tuple[str, str]]:
    """Return the four reviewed device-side physical relationships."""
    return {
        "core_edge": ("core-02:GigabitEthernet4", "edge-junos-01:ge-0/0/0"),
        "core_transit": (
            "core-02:GigabitEthernet2",
            "transit-ios-01:GigabitEthernet0/1",
        ),
        "edge_transit": (
            "edge-junos-01:ge-0/0/1",
            "transit-ios-01:GigabitEthernet0/2",
        ),
        "core_access": (
            "core-02:GigabitEthernet3",
            "access-sw-01:GigabitEthernet0/1",
        ),
    }


def topology_digest() -> str:
    return _sha256(profiled_staging_topology())


def realization_interface_slot(profile, name: str) -> int:
    def normalized(value):
        return re.sub(r"^gi(?=\d)", "gigabitethernet", value.casefold())

    matches = tuple(
        s.cml_slot
        for s in profile.physical_interface_slots
        if normalized(s.interface_name) == normalized(name)
    )
    if len(matches) != 1:
        raise ValueError("staging topology interface not profile-admitted")
    return matches[0]


class ProfiledStagingLink(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    identity: str = Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=100)
    endpoints: tuple[str, str]


class ProfiledStagingTopology(BaseModel):
    """Reviewed physical subjects and ports; Terraform does not choose membership."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    scope: ProfiledPopulationScope = STAGING_REALIZATION_SCOPE
    links: tuple[ProfiledStagingLink, ...]

    @model_validator(mode="after")
    def exact_endpoints(self):
        device_keys = {m.logical_name.replace("-", "_") for m in self.scope.members}
        if device_keys & {"system_bridge", "management_switch"}:
            raise ValueError("staging device key collides with infrastructure")
        seen = set()
        identities = {"system_bridge_management"} | {
            f"management_{key}" for key in device_keys
        }
        for link in self.links:
            if link.identity in identities:
                raise ValueError("staging topology duplicate link")
            identities.add(link.identity)
            nodes = []
            for endpoint in link.endpoints:
                name, sep, interface = endpoint.partition(":")
                member = next(
                    (m for m in self.scope.members if m.logical_name == name), None
                )
                if not sep or member is None:
                    raise ValueError(
                        "staging topology endpoint outside scope or duplicate"
                    )
                profile = CML_REALIZATION_PROFILE_CATALOG[
                    member.cml_realization_profile_id
                ]
                slot = realization_interface_slot(profile, interface)
                if (name, slot) in seen or slot == profile.physical_interface_slots[
                    0
                ].cml_slot:
                    raise ValueError("staging topology physical endpoint reused")
                seen.add((name, slot))
                nodes.append(name)
            if nodes[0] == nodes[1]:
                raise ValueError("staging topology self link rejected")
        return self

    @property
    def digest(self):
        return _sha256({link.identity: link.endpoints for link in self.links})

    def terraform_links(self):
        by_name = {m.logical_name: m for m in self.scope.members}
        links = {}
        for link in self.links:
            values = {}
            for side, endpoint in zip(("a", "b"), link.endpoints, strict=True):
                name, interface = endpoint.split(":", 1)
                profile = CML_REALIZATION_PROFILE_CATALOG[
                    by_name[name].cml_realization_profile_id
                ]
                slot = realization_interface_slot(profile, interface)
                values[f"node_{side}"] = name.replace("-", "_")
                values[f"slot_{side}"] = slot
            links[link.identity] = values
        return links


CURRENT_STAGING_TOPOLOGY = ProfiledStagingTopology(
    links=tuple(
        ProfiledStagingLink(identity=k, endpoints=v)
        for k, v in profiled_staging_topology().items()
    )
)


def staging_terraform_addresses(
    scope: ProfiledPopulationScope = STAGING_REALIZATION_SCOPE,
    topology: ProfiledStagingTopology = CURRENT_STAGING_TOPOLOGY,
) -> frozenset[str]:
    if topology.scope != scope:
        raise ValueError("staging topology scope rejected")
    infrastructure = {
        "cml2_lab.profiled_staging",
        "cml2_node.system_bridge",
        "cml2_node.management_switch",
        "cml2_link.system_bridge_management",
        "cml2_lifecycle.profiled_staging",
    }
    return frozenset(
        infrastructure
        | {
            f'cml2_node.device["{m.logical_name.replace("-", "_")}"]'
            for m in scope.members
        }
        | {
            f'cml2_link.management["{m.logical_name.replace("-", "_")}"]'
            for m in scope.members
        }
        | {f'cml2_link.data["{link.identity}"]' for link in topology.links}
    )


PROFILED_STAGING_TERRAFORM_ADDRESSES = staging_terraform_addresses()
PROFILED_STAGING_RESOURCE_COUNT = len(PROFILED_STAGING_TERRAFORM_ADDRESSES)
PROFILED_STAGING_NODE_COUNT = len(STAGING_REALIZATION_SCOPE.members) + 2
PROFILED_STAGING_LINK_COUNT = (
    len(STAGING_REALIZATION_SCOPE.members) + 1 + len(CURRENT_STAGING_TOPOLOGY.links)
)


class ProfiledTopologyResolver(Protocol):
    """GET-only physical topology authority required before CML creation."""

    def resolve_interface(
        self, device: ProfiledInventoryDevice, interface_name: str
    ) -> StableInterfaceIdentity: ...

    def resolve_cabled_peer(
        self, interface: StableInterfaceIdentity
    ) -> StableInterfaceIdentity: ...


def validate_profiled_staging_physical_topology(
    inventory: ProfiledTopologyResolver,
    devices: tuple[ProfiledInventoryDevice, ...],
    *,
    topology: ProfiledStagingTopology = CURRENT_STAGING_TOPOLOGY,
) -> None:
    """Require each reviewed CML data link to match one exact NetBox cable."""
    by_name = {str(device.logical_name): device for device in devices}
    topology.scope.require_bindings(devices)
    for link in topology.links:
        left, right = link.endpoints
        left_device, left_name = left.split(":", maxsplit=1)
        right_device, right_name = right.split(":", maxsplit=1)
        resolved_left = inventory.resolve_interface(by_name[left_device], left_name)
        resolved_right = inventory.resolve_interface(by_name[right_device], right_name)
        if (
            inventory.resolve_cabled_peer(resolved_left) != resolved_right
            or inventory.resolve_cabled_peer(resolved_right) != resolved_left
        ):
            raise ProfiledStagingError("profiled staging physical topology rejected")


def terraform_profiled_device_variables(
    devices: tuple[ProfiledInventoryDevice, ...],
    credentials: dict[str, DeviceCredentials],
    password_verifiers: dict[str, str],
    *,
    scope: ProfiledPopulationScope = STAGING_REALIZATION_SCOPE,
) -> dict[str, object]:
    """Build sensitive Day-0 inputs from exact profiled staging authority."""
    scope.require_bindings(devices)
    values: dict[str, object] = {}
    for index, device in enumerate(devices):
        profile = CML_REALIZATION_PROFILE_CATALOG[device.cml_realization_profile_id]
        endpoint = device.management_endpoints.staging.binding.l3_endpoint
        credential = credentials.get(str(device.logical_name))
        verifier = password_verifiers.get(str(device.logical_name))
        if credential is None or verifier is None:
            raise ProfiledStagingError("profiled staging bootstrap authority rejected")
        if device.automation_profile_id.value.startswith(("cat8000v", "iosv")):
            accepted_verifier = bool(
                re.fullmatch(r"\$9\$[A-Za-z0-9./]+\$[A-Za-z0-9./]+", verifier)
            )
        else:
            accepted_verifier = bool(re.fullmatch(r"\$6\$[A-Za-z0-9./$]+", verifier))
        if not accepted_verifier:
            raise ProfiledStagingError("profiled staging bootstrap verifier rejected")
        values[str(device.logical_name).replace("-", "_")] = {
            "hostname": device.expected_hostname,
            "management_cidr": (
                str(device.management_endpoints.staging.binding.l3_endpoint.address)
            ),
            "username": credential.username,
            "password_verifier": verifier,
            "node_definition": profile.node_definition,
            "image_definition": profile.image_definition,
            "cpu_cores": profile.resources.cpu_cores,
            "ram_mb": profile.resources.ram_mb,
            "management_port": endpoint.port,
            "bootstrap_profile": profile.bootstrap_profile.value,
            "management_slot": realization_interface_slot(
                profile,
                device.management_endpoints.staging.binding.physical_attachment.interface.name,
            ),
            "management_switch_slot": index + 1,
            "layout_x": 100 + (index % 2) * 300,
            "layout_y": -400 + (index // 2) * 500,
        }
    return values


def validate_profiled_staging_population(
    inventory: NetBoxProfileInventoryProvider,
    *,
    scope: ProfiledPopulationScope = STAGING_REALIZATION_SCOPE,
) -> tuple[ProfiledInventoryDevice, ...]:
    """Resolve complete managed authority, then project the reviewed staging scope."""
    return inventory.resolve_profiled_population().project(scope).devices


def validate_management_only_bootstrap(value: str) -> None:
    """Reject historical/B4 configuration from stored disposable Day-0 text."""
    forbidden = (
        "10.6.12.",
        "router ospf",
        "vlan ",
        "switchport trunk",
        "access-list",
        "snmp-server",
        "description ",
        "policy-options",
        "protocols ospf",
    )
    lowered = value.lower()
    if any(item in lowered for item in forbidden):
        raise ProfiledStagingError("profiled staging Day-0 is not management-only")


class StagingOperations(Protocol):
    """Narrow side-effect boundary for the disposable Terraform lifecycle."""

    @property
    def managed_resources_exist(self) -> bool: ...

    def admit(self) -> None: ...
    def create(self) -> StagingRealizationContext: ...
    def validate(
        self, context: StagingRealizationContext
    ) -> tuple[ProfiledStagingDeviceEvidence, ...]: ...
    def destroy_owned(self, *, require_complete: bool) -> None: ...
    def verify_absent(self) -> None: ...
    def retire_state(self) -> None: ...


@dataclass
class ProfiledStagingLifecycle:
    """One-shot create/validate/destroy policy preserving primary/cleanup facts."""

    run_id: str
    orchestrator: str
    operations: StagingOperations
    scope: ProfiledPopulationScope = STAGING_REALIZATION_SCOPE
    evidence: ProfiledStagingEvidence = field(init=False)

    def __post_init__(self) -> None:
        self.evidence = ProfiledStagingEvidence(
            staging_run_id=self.run_id,
            scope=self.scope,
            orchestrator=self.orchestrator,
            lab_title=f"NCDP Staging {self.run_id}",
        )

    def run(self) -> ProfiledStagingEvidence:
        started = time.monotonic()
        timings: dict[str, float] = {}
        primary: str | None = None
        cleanup: str | None = None
        primary_error: Exception | None = None
        cleanup_error: Exception | None = None
        context: StagingRealizationContext | None = None
        devices: tuple[ProfiledStagingDeviceEvidence, ...] = ()
        create_outcome = "not_attempted"
        destroy_outcome = "not_attempted"
        absence = "not_attempted"
        retirement = "not_attempted"
        read_only = "not_attempted"
        try:
            self.operations.admit()
            create_outcome = "attempted"
            context = self.operations.create()
            if context.scope != self.scope:
                raise ProfiledStagingError("staging realization scope rejected")
            create_outcome = "succeeded"
            with record_staging_duration(timings, "read_only"):
                devices = self.operations.validate(context)
            read_only = "succeeded"
        except Exception as error:
            primary_error = error
            primary = str(error)
        finally:
            cleanup_started = time.monotonic()
            owned = False
            try:
                owned = self.operations.managed_resources_exist
            except Exception as error:
                cleanup_error = error
                cleanup = str(error)
            if context is not None and not owned and cleanup is None:
                cleanup_error = ProfiledStagingAmbiguousError(
                    "profiled staging ownership disappeared before cleanup"
                )
                cleanup = str(cleanup_error)
            if owned:
                try:
                    self.operations.destroy_owned(require_complete=context is not None)
                    destroy_outcome = "succeeded"
                    self.operations.verify_absent()
                    absence = "succeeded"
                    self.operations.retire_state()
                    retirement = "succeeded"
                except Exception as error:
                    cleanup_error = error
                    cleanup = str(error)
            timings["cleanup"] = round(time.monotonic() - cleanup_started, 3)
        timings["lifecycle_total"] = round(time.monotonic() - started, 3)
        ambiguous = isinstance(
            primary_error, ProfiledStagingAmbiguousError
        ) or isinstance(cleanup_error, ProfiledStagingAmbiguousError)
        outcome = (
            ProfiledStagingOutcome.SUCCEEDED
            if primary is None and cleanup is None
            else (
                ProfiledStagingOutcome.AMBIGUOUS
                if ambiguous
                else (
                    ProfiledStagingOutcome.CLEANUP_FAILED
                    if cleanup
                    else ProfiledStagingOutcome.FAILED
                )
            )
        )
        self.evidence = ProfiledStagingEvidence(
            staging_run_id=self.run_id,
            scope=self.scope,
            orchestrator=self.orchestrator,
            source_commit=getattr(self.operations, "source_commit", None),
            lab_id=(
                context.cml_lab_id
                if context
                else getattr(self.operations, "owned_lab_id", None)
            ),
            lab_title=f"NCDP Staging {self.run_id}",
            topology_digest=(
                context.topology_evidence.digest
                if context
                else getattr(self.operations, "topology_digest", None)
            ),
            context_digest=(
                _sha256(context.model_dump(mode="json")) if context else None
            ),
            readiness=getattr(self.operations, "readiness_evidence", ()),
            lab_start_evidence=getattr(self.operations, "lab_start_evidence", None),
            timings_seconds=getattr(self.operations, "timings_seconds", {}) | timings,
            devices=devices or getattr(self.operations, "device_evidence", ()),
            trust_generation=(
                context.devices[0].trust_evidence
                if context
                else getattr(self.operations, "trust_generation", None)
            ),
            recycles=getattr(self.operations, "recycles", ()),
            readiness_deadline_seconds=getattr(
                self.operations, "readiness_deadline_seconds", 180
            ),
            create_outcome=getattr(self.operations, "create_stage", create_outcome),
            start_outcome=getattr(
                self.operations,
                "start_stage",
                "succeeded" if context else "not_completed",
            ),
            read_only_outcome=read_only,
            destroy_outcome=destroy_outcome,
            absence_verification=absence,
            state_retirement=retirement,
            primary_failure=primary,
            cleanup_failure=cleanup,
            final_outcome=outcome,
        )
        return self.evidence


def validate_private_run_directory(path: Path, checkout: Path) -> Path:
    """Require an owner-only run directory outside the checkout before recovery."""
    if not path.is_absolute() or path.is_symlink() or not path.is_dir():
        raise ProfiledStagingError("profiled staging run directory rejected")
    resolved = path.resolve(strict=True)
    if resolved == checkout.resolve() or resolved.is_relative_to(checkout.resolve()):
        raise ProfiledStagingError("profiled staging run directory rejected")
    metadata = path.stat(follow_symlinks=False)
    if metadata.st_uid != os.getuid() or stat.S_IMODE(metadata.st_mode) != 0o700:
        raise ProfiledStagingError("profiled staging run directory rejected")
    return resolved


def retire_profiled_staging_run_directory(
    path: Path,
    run_id: str,
    checkout: Path,
) -> None:
    """Remove only one exact, privately admitted staging run directory."""
    run = validate_private_run_directory(path, checkout)
    if (
        run.name != run_id
        or not re.fullmatch(r"[a-z0-9]+(?:[._-][a-z0-9]+)*", run_id)
        or len(run_id) > 128
    ):
        raise ProfiledStagingError("profiled staging run identity rejected")
    load_recovery_inputs(run / "recovery-inputs.tfvars.json", run_id)
    shutil.rmtree(run)


def validate_profiled_staging_evidence_path(path: Path, run: Path) -> Path:
    """Require final lifecycle evidence to live outside its disposable run."""
    if not path.is_absolute() or path.is_symlink():
        raise ProfiledStagingError("profiled staging evidence path rejected")
    try:
        candidate = path.parent.resolve(strict=True) / path.name
    except OSError:
        raise ProfiledStagingError("profiled staging evidence path rejected") from None
    if candidate == run or candidate.is_relative_to(run):
        raise ProfiledStagingError("profiled staging evidence path rejected")
    return candidate


def validate_retained_state_file(path: Path) -> Path:
    """Require retained Terraform state to be one bounded owner-only inode."""
    metadata = path.lstat()
    if (
        path.is_symlink()
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or metadata.st_size > 16 * 1024 * 1024
    ):
        raise ProfiledStagingError("profiled staging retained state rejected")
    return path


def validate_destroy_only_plan(
    state_addresses: set[str],
    planned_actions: dict[str, str],
    *,
    require_complete: bool = False,
    expected_addresses: frozenset[str] = PROFILED_STAGING_TERRAFORM_ADDRESSES,
) -> None:
    """Permit only exact deletion of a known nonempty full graph or subset."""
    if not state_addresses or not state_addresses.issubset(expected_addresses):
        raise ProfiledStagingError("profiled staging retained state is not admitted")
    if require_complete and state_addresses != expected_addresses:
        raise ProfiledStagingError("profiled staging retained state is not complete")
    if set(planned_actions) != state_addresses or set(planned_actions.values()) != {
        "delete"
    }:
        raise ProfiledStagingError("profiled staging recovery is not destroy-only")


def validate_start_only_plan(planned_actions: dict[str, str]) -> None:
    """Require the saved START plan to update only the lifecycle resource."""
    if planned_actions != {"cml2_lifecycle.profiled_staging": "update"}:
        raise ProfiledStagingError("profiled staging START plan rejected")


def terraform_managed_state_addresses(payload: object) -> set[str]:
    """Extract only managed-resource addresses from bounded Terraform state JSON."""
    if payload == {"format_version": "1.0"}:
        return set()
    try:
        root = payload["values"]["root_module"]  # type: ignore[index]
    except (KeyError, TypeError):
        raise ProfiledStagingError(
            "profiled staging Terraform state rejected"
        ) from None
    addresses: set[str] = set()
    pending = [root]
    while pending:
        module = pending.pop()
        if not isinstance(module, dict):
            raise ProfiledStagingError("profiled staging Terraform state rejected")
        resources = module.get("resources", [])
        children = module.get("child_modules", [])
        if not isinstance(resources, list) or not isinstance(children, list):
            raise ProfiledStagingError("profiled staging Terraform state rejected")
        pending.extend(children)
        for resource in resources:
            if not isinstance(resource, dict):
                raise ProfiledStagingError("profiled staging Terraform state rejected")
            if resource.get("mode") == "data":
                continue
            address = resource.get("address")
            if not isinstance(address, str) or address in addresses:
                raise ProfiledStagingError("profiled staging Terraform state rejected")
            addresses.add(address)
    return addresses


def write_recovery_inputs(path: Path, payload: dict[str, object]) -> None:
    """Persist exact destroy inputs create-only in one private regular inode."""
    if path.exists() or path.is_symlink():
        raise ProfiledStagingError("profiled staging recovery inputs already exist")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    try:
        encoded = (
            json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
        ).encode()
        os.write(descriptor, encoded)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def load_recovery_inputs(
    path: Path,
    run_id: str,
    *,
    scope: ProfiledPopulationScope = STAGING_REALIZATION_SCOPE,
    topology: ProfiledStagingTopology = CURRENT_STAGING_TOPOLOGY,
) -> dict[str, object]:
    """Validate one private, secret-verifier-only retained Terraform input file."""
    metadata = path.lstat()
    if (
        path.is_symlink()
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or metadata.st_size > 128 * 1024
    ):
        raise ProfiledStagingError("profiled staging recovery inputs rejected")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise ProfiledStagingError(
            "profiled staging recovery inputs rejected"
        ) from None
    if (
        not isinstance(payload, dict)
        or set(payload)
        != {"staging_run_id", "lifecycle_state", "devices", "data_links"}
        or payload["staging_run_id"] != run_id
        or payload["lifecycle_state"] != "DEFINED_ON_CORE"
        or not isinstance(payload["devices"], dict)
        or set(payload["devices"])
        != {m.logical_name.replace("-", "_") for m in scope.members}
        or topology.scope != scope
        or payload["data_links"] != topology.terraform_links()
    ):
        raise ProfiledStagingError("profiled staging recovery inputs rejected")
    forbidden = ("token", "role_id", "secret_id", "plaintext", "bao_token")
    lowered = path.read_text(encoding="utf-8").lower()
    if any(item in lowered for item in forbidden):
        raise ProfiledStagingError("profiled staging recovery inputs rejected")
    device_fields = {
        "hostname",
        "management_cidr",
        "username",
        "password_verifier",
        "node_definition",
        "image_definition",
        "cpu_cores",
        "ram_mb",
        "management_port",
        "bootstrap_profile",
        "management_slot",
        "management_switch_slot",
        "layout_x",
        "layout_y",
    }
    expected = {m.logical_name.replace("-", "_"): m for m in scope.members}
    for name, item in payload["devices"].items():
        member = expected[name]
        profile = CML_REALIZATION_PROFILE_CATALOG[member.cml_realization_profile_id]
        hostname = member.logical_name
        service = get_automation_profile(
            member.automation_profile_id
        ).readiness_services[0]
        port = service.port
        verifier_prefix = (
            "$6$"
            if member.automation_profile_id is AutomationProfileID.VJUNOS_ROUTER
            else "$9$"
        )
        from ipaddress import IPv4Interface

        try:
            IPv4Interface(item.get("management_cidr"))
        except (ValueError, TypeError, AttributeError):
            raise ProfiledStagingError(
                "profiled staging recovery inputs rejected"
            ) from None
        if (
            not isinstance(item, dict)
            or set(item) != device_fields
            or item.get("hostname") != hostname
            or item.get("node_definition") != profile.node_definition
            or item.get("image_definition") != profile.image_definition
            or item.get("cpu_cores") != profile.resources.cpu_cores
            or item.get("ram_mb") != profile.resources.ram_mb
            or item.get("bootstrap_profile") != profile.bootstrap_profile.value
            or item.get("management_slot")
            != profile.physical_interface_slots[0].cml_slot
            or item.get("management_switch_slot") != tuple(expected).index(name) + 1
            or item.get("management_port") != port
            or not isinstance(item.get("username"), str)
            or not item["username"]
            or not isinstance(item.get("password_verifier"), str)
            or not item["password_verifier"].startswith(verifier_prefix)
        ):
            raise ProfiledStagingError("profiled staging recovery inputs rejected")
    return payload


def validate_read_only_collection(
    context: StagingRealizationContext,
    devices: tuple[ProfiledInventoryDevice, ...],
    credentials: dict[str, DeviceCredentials],
    adapter: ProfileReadOnlyAdapter,
    readiness: dict[str, tuple[float, EvidenceReference]],
    on_evidence: Callable[[tuple[ProfiledStagingDeviceEvidence, ...]], None]
    | None = None,
) -> tuple[ProfiledStagingDeviceEvidence, ...]:
    """Collect exact profiled staging state without invoking any write surface."""
    outcomes: list[ProfiledStagingDeviceEvidence] = []
    for device in devices:
        target = context.staging_read_only_target(device)
        states = adapter.discover(target, credentials[str(device.logical_name)])

        def normalized(name: str) -> str:
            return re.sub(r"^gi(?=\d)", "gigabitethernet", name.casefold())

        names = {normalized(state.interface) for state in states}
        management = (
            device.management_endpoints.staging.binding.l3_endpoint.interface.name
        )
        management_state = next(
            (
                state
                for state in states
                if normalized(state.interface) == normalized(management)
            ),
            None,
        )
        expected_address = str(
            device.management_endpoints.staging.binding.l3_endpoint.address
        )
        realization_profile = CML_REALIZATION_PROFILE_CATALOG[
            device.cml_realization_profile_id
        ]
        required_physical = {
            normalized(slot.interface_name)
            for slot in realization_profile.physical_interface_slots
        }
        if (
            not states
            or {state.observed_hostname for state in states}
            != {device.expected_hostname}
            or normalized(management) not in names
            or management_state is None
            or expected_address not in management_state.ipv4_addresses
            or (
                device.automation_profile_id
                in {AutomationProfileID.IOSV_159_3_M12, AutomationProfileID.IOSVL2_2020}
                and not required_physical.issubset(names)
            )
        ):
            raise ProfiledStagingError("profiled staging read-only validation rejected")
        profile = get_automation_profile(device.automation_profile_id)
        service = profile.readiness_services[0]
        realized = next(
            item
            for item in context.devices
            if item.device_identity == device.device_identity
        )
        readiness_seconds, readiness_evidence = readiness[str(device.logical_name)]
        outcomes.append(
            ProfiledStagingDeviceEvidence(
                device_identity=device.device_identity,
                logical_name=device.logical_name,
                automation_profile_id=device.automation_profile_id,
                cml_realization_profile_id=device.cml_realization_profile_id,
                cml_node_id=realized.cml_node_id,
                readiness_seconds=readiness_seconds,
                readiness_evidence=readiness_evidence,
                readiness_service=service.service.value,
                readiness_port=service.port,
                read_only_collection="succeeded",
                observed_hostname=device.expected_hostname,
                interface_count=len(states),
            )
        )
        if on_evidence is not None:
            on_evidence(tuple(outcomes))
    return tuple(outcomes)
