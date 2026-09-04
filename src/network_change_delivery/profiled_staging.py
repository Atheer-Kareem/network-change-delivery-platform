"""Profiled exact-four disposable CML staging lifecycle.

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
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from ipaddress import IPv4Address
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from network_change_delivery.architecture_contracts import (
    CML_REALIZATION_PROFILE_CATALOG,
    AutomationProfileID,
    CmlRealizationProfileID,
    ManagementService,
    NetBoxDeviceIdentity,
    NonEmptyString,
    Sha256Digest,
    StableInterfaceIdentity,
    get_automation_profile,
)
from network_change_delivery.profile_inventory import (
    PROFILED_POPULATION_CATALOG,
    NetBoxProfileInventoryProvider,
    ProfiledInventoryDevice,
)
from network_change_delivery.profile_read_only_adapter import ProfileReadOnlyAdapter
from network_change_delivery.profiled_realization import (
    EvidenceReference,
    StagingRealizationContext,
)
from network_change_delivery.secrets import DeviceCredentials

PROFILED_STAGING_DEVICE_NAMES = tuple(
    member.logical_name for member in PROFILED_POPULATION_CATALOG
)
PROFILED_STAGING_RESOURCE_COUNT = 17
PROFILED_STAGING_NODE_COUNT = 6
PROFILED_STAGING_LINK_COUNT = 9
PROFILED_STAGING_TERRAFORM_ADDRESSES = frozenset(
    {
        "cml2_lab.profiled_staging",
        "cml2_node.system_bridge",
        "cml2_node.management_switch",
        'cml2_node.device["core_02"]',
        'cml2_node.device["edge_junos_01"]',
        'cml2_node.device["transit_ios_01"]',
        'cml2_node.device["access_sw_01"]',
        "cml2_link.system_bridge_management",
        "cml2_link.management_core",
        "cml2_link.management_junos",
        "cml2_link.management_transit",
        "cml2_link.management_access",
        "cml2_link.core_junos",
        "cml2_link.core_transit",
        "cml2_link.junos_transit",
        "cml2_link.core_access",
        "cml2_lifecycle.profiled_staging",
    }
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

    @model_validator(mode="after")
    def evidence_matches_outcome(self) -> ProfiledStagingReadinessEvidence:
        if (self.outcome is ProfiledStagingReadinessOutcome.READY) != (
            self.readiness_evidence is not None
        ):
            raise ValueError("profiled staging readiness evidence rejected")
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


class ProfiledStagingEvidence(BaseModel):
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
    readiness: tuple[ProfiledStagingReadinessEvidence, ...] = ()
    devices: tuple[ProfiledStagingDeviceEvidence, ...] = ()
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
    def exact_four_when_ready(self) -> ProfiledStagingEvidence:
        if self.schema_version != "2" or not self.lab_title.startswith("NCDP Staging "):
            raise ValueError("profiled staging evidence identity rejected")
        if (
            self.devices
            and tuple(item.logical_name for item in self.devices)
            != PROFILED_STAGING_DEVICE_NAMES
        ):
            raise ValueError("profiled staging evidence population rejected")
        readiness_names = tuple(item.logical_name for item in self.readiness)
        if readiness_names != tuple(
            name for name in PROFILED_STAGING_DEVICE_NAMES if name in readiness_names
        ) or len(set(readiness_names)) != len(readiness_names):
            raise ValueError("profiled staging readiness population rejected")
        if self.final_outcome is ProfiledStagingOutcome.SUCCEEDED and (
            readiness_names != PROFILED_STAGING_DEVICE_NAMES
            or any(
                item.outcome is not ProfiledStagingReadinessOutcome.READY
                for item in self.readiness
            )
        ):
            raise ValueError("profiled staging successful readiness rejected")
        return self


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
) -> None:
    """Require each reviewed CML data link to match one exact NetBox cable."""
    by_name = {str(device.logical_name): device for device in devices}
    if tuple(by_name) != PROFILED_STAGING_DEVICE_NAMES:
        raise ProfiledStagingError("profiled staging topology population rejected")
    for left, right in profiled_staging_topology().values():
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
) -> dict[str, object]:
    """Build sensitive Day-0 inputs from exact profiled staging authority."""
    if tuple(item.logical_name for item in devices) != PROFILED_STAGING_DEVICE_NAMES:
        raise ProfiledStagingError("profiled staging population rejected")
    values: dict[str, object] = {}
    for device in devices:
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
        }
    return values


def validate_profiled_staging_population(
    inventory: NetBoxProfileInventoryProvider,
) -> tuple[ProfiledInventoryDevice, ...]:
    """Resolve the sole exact-four staging population via GET-only inventory."""
    population = inventory.resolve_profiled_population()
    if (
        tuple(item.logical_name for item in population.devices)
        != PROFILED_STAGING_DEVICE_NAMES
    ):
        raise ProfiledStagingError("profiled staging population rejected")
    return population.devices


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
    evidence: ProfiledStagingEvidence = field(init=False)

    def __post_init__(self) -> None:
        self.evidence = ProfiledStagingEvidence(
            staging_run_id=self.run_id,
            orchestrator=self.orchestrator,
            lab_title=f"NCDP Staging {self.run_id}",
        )

    def run(self) -> ProfiledStagingEvidence:
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
            create_outcome = "succeeded"
            devices = self.operations.validate(context)
            read_only = "succeeded"
        except Exception as error:
            primary_error = error
            primary = str(error)
        finally:
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
            devices=devices or getattr(self.operations, "device_evidence", ()),
            trust_generation=(
                context.devices[0].trust_evidence
                if context
                else getattr(self.operations, "trust_generation", None)
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
) -> None:
    """Permit only exact deletion of a known nonempty full graph or subset."""
    if not state_addresses or not state_addresses.issubset(
        PROFILED_STAGING_TERRAFORM_ADDRESSES
    ):
        raise ProfiledStagingError("profiled staging retained state is not admitted")
    if require_complete and state_addresses != PROFILED_STAGING_TERRAFORM_ADDRESSES:
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


def load_recovery_inputs(path: Path, run_id: str) -> dict[str, object]:
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
        or set(payload) != {"staging_run_id", "lifecycle_state", "devices"}
        or payload["staging_run_id"] != run_id
        or payload["lifecycle_state"] != "DEFINED_ON_CORE"
        or not isinstance(payload["devices"], dict)
        or set(payload["devices"])
        != {"core_02", "edge_junos_01", "transit_ios_01", "access_sw_01"}
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
    }
    expected = {
        "core_02": ("core-02", "192.168.4.30/24", 22, "$9$"),
        "edge_junos_01": ("edge-junos-01", "192.168.4.40/24", 830, "$6$"),
        "transit_ios_01": ("transit-ios-01", "192.168.4.31/24", 22, "$9$"),
        "access_sw_01": ("access-sw-01", "192.168.4.32/24", 22, "$9$"),
    }
    for name, item in payload["devices"].items():
        hostname, address, port, verifier_prefix = expected[name]
        if (
            not isinstance(item, dict)
            or set(item) != device_fields
            or item.get("hostname") != hostname
            or item.get("management_cidr") != address
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
        management = {
            "core-02": "GigabitEthernet1",
            "edge-junos-01": "fxp0",
            "transit-ios-01": "GigabitEthernet0/0",
            "access-sw-01": "GigabitEthernet0/0",
        }[str(device.logical_name)]
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
        required_physical = {
            normalized(f"GigabitEthernet0/{index}") for index in range(4)
        }
        if (
            not states
            or {state.observed_hostname for state in states}
            != {device.expected_hostname}
            or normalized(management) not in names
            or management_state is None
            or expected_address not in management_state.ipv4_addresses
            or (
                str(device.logical_name) in {"transit-ios-01", "access-sw-01"}
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
