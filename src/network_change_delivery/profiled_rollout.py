"""Read-only profiled rollout planning over current schema-v2 child lifecycles.

These artifacts describe planning, not promotion or execution authority. Consumers
must retain caller-owned intent, population and credential-authority boundaries.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Annotated, Literal, Protocol

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    model_validator,
)

from network_change_delivery.architecture_contracts import (
    AutomationProfileID,
    GitCommit,
    NetworkOS,
    OperationalRole,
    Sha256Digest,
    StableInterfaceIdentity,
)
from network_change_delivery.models import (
    CliBoundString,
    DesiredDescription,
    InterfaceDescriptionIntent,
)
from network_change_delivery.profile_inventory import (
    ProfiledInventoryDevice,
    ProfiledInventoryPopulation,
    ProfiledLogicalName,
    ProfiledPopulationDeclaration,
    ProfiledPopulationMember,
    Slug,
    _admit_profiled_device,
)
from network_change_delivery.profiled_intent import admit_intent_result
from network_change_delivery.profiled_planning import (
    ProfiledComplianceRecord,
    ProfiledDeploymentPlan,
    ProfiledOperation,
    ProfiledOperationAdmission,
    ProfiledPlanningCollector,
    ProfiledPlanningInventory,
    ProfiledPlanningSecretProvider,
    _assert_profiled_interface_binding,
    admit_profiled_operation,
    plan_profiled_change,
)

DeviceIdentity = Annotated[str, Field(pattern=r"^netbox:dcim\.device:[1-9][0-9]*$")]
MAX_MEMBERS = 100
MAX_CHILD_BYTES = 128 * 1024


def _digest(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ProfiledRolloutMemberIntent(_Frozen):
    """One reviewed logical target/interface and desired description."""

    target: ProfiledLogicalName
    interface: CliBoundString = Field(max_length=100)
    desired: DesiredDescription

    def child_intent(self, change_id: str) -> InterfaceDescriptionIntent:
        return InterfaceDescriptionIntent(
            change_id=change_id,
            kind="interface_description",
            target=self.target,
            interface=self.interface,
            desired=self.desired,
        )


class ProfiledRolloutPolicy(_Frozen):
    """Explicit canaries, or deterministic first representative per family."""

    wave_size: int = Field(strict=True, ge=1, le=MAX_MEMBERS)
    canaries: tuple[ProfiledLogicalName, ...] | None = Field(
        default=None, max_length=MAX_MEMBERS
    )


class ProfiledRolloutSelector(_Frozen):
    """Closed Git population predicates: OR within, AND across dimensions."""

    operational_roles: tuple[OperationalRole, ...] | None = Field(
        default=None, min_length=1, max_length=len(OperationalRole)
    )
    network_oses: tuple[NetworkOS, ...] | None = Field(
        default=None, min_length=1, max_length=len(NetworkOS)
    )
    automation_profile_ids: tuple[AutomationProfileID, ...] | None = Field(
        default=None, min_length=1, max_length=len(AutomationProfileID)
    )

    def _dimensions(self):
        # Field names and conjunction are code-owned, never selector input.
        return (
            (self.operational_roles, "operational_role"),
            (self.network_oses, "network_os"),
            (self.automation_profile_ids, "automation_profile_id"),
        )

    @model_validator(mode="after")
    def bounded_dimensions(self) -> ProfiledRolloutSelector:
        supplied = [values for values, _ in self._dimensions() if values is not None]
        if not supplied or any(len(values) != len(set(values)) for values in supplied):
            raise ValueError("selector needs nonempty unique closed dimensions")
        return self

    def select(
        self, declaration: ProfiledPopulationDeclaration
    ) -> tuple[ProfiledPopulationMember, ...]:
        """Select declared facts in declaration order; no NetBox query or payload."""
        selected = tuple(
            member
            for member in declaration.members
            if all(
                values is None or getattr(member, field) in values
                for values, field in self._dimensions()
            )
        )
        if not selected:
            raise ValueError("rollout selector matches no declared members")
        return selected


class ProfiledRolloutIntent(_Frozen):
    """Explicit selection only; selectors and queries are intentionally rejected."""

    change_id: CliBoundString = Field(max_length=100)
    operation: Literal["interface_description"]
    members: tuple[ProfiledRolloutMemberIntent, ...] = Field(
        min_length=1, max_length=MAX_MEMBERS
    )
    policy: ProfiledRolloutPolicy

    @model_validator(mode="after")
    def unique_selection(self) -> ProfiledRolloutIntent:
        names = tuple(member.target for member in self.members)
        if len(names) != len(set(names)):
            raise ValueError("rollout targets must be unique")
        canaries = self.policy.canaries
        if canaries is not None and (
            len(canaries) != len(set(canaries)) or not set(canaries) <= set(names)
        ):
            raise ValueError("rollout canaries must be unique selected targets")
        return self


class ProfiledRolloutSelectorClause(_Frozen):
    """A closed WHO predicate with one exact reviewed WHAT payload."""

    selector: ProfiledRolloutSelector
    interface: CliBoundString = Field(max_length=100)
    desired: DesiredDescription


class ProfiledRolloutExpandedMember(ProfiledRolloutMemberIntent):
    """Frozen payload with its exact zero-based instruction source index."""

    source_kind: Literal["explicit", "selector"]
    source_index: int = Field(strict=True, ge=0, lt=MAX_MEMBERS)

    def member_intent(self) -> ProfiledRolloutMemberIntent:
        return ProfiledRolloutMemberIntent(
            target=self.target, interface=self.interface, desired=self.desired
        )


class ProfiledRolloutSelectionIntent(_Frozen):
    """Composable explicit members and ordered closed selector clauses."""

    change_id: CliBoundString = Field(max_length=100)
    operation: Literal["interface_description"]
    explicit_members: tuple[ProfiledRolloutMemberIntent, ...] = Field(
        default=(), max_length=MAX_MEMBERS
    )
    selectors: tuple[ProfiledRolloutSelectorClause, ...] = Field(
        default=(), max_length=MAX_MEMBERS
    )
    policy: ProfiledRolloutPolicy

    @model_validator(mode="after")
    def selection_sources(self) -> ProfiledRolloutSelectionIntent:
        if not self.explicit_members and not self.selectors:
            raise ValueError("rollout requires at least one selection source")
        names = tuple(member.target for member in self.explicit_members)
        if len(names) != len(set(names)):
            raise ValueError("rollout explicit targets must be unique")
        return self

    def expand(
        self, declaration: ProfiledPopulationDeclaration
    ) -> tuple[ProfiledRolloutExpandedMember, ...]:
        expanded = []
        for index, member in enumerate(self.explicit_members):
            declaration.member(member.target)
            expanded.append(
                ProfiledRolloutExpandedMember(
                    **member.model_dump(), source_kind="explicit", source_index=index
                )
            )
        for index, clause in enumerate(self.selectors):
            expanded.extend(
                ProfiledRolloutExpandedMember(
                    source_kind="selector",
                    source_index=index,
                    target=member.logical_name,
                    interface=clause.interface,
                    desired=clause.desired,
                )
                for member in clause.selector.select(declaration)
            )
        names = tuple(member.target for member in expanded)
        if len(names) != len(set(names)):
            raise ValueError("rollout selection sources overlap")
        if len(expanded) > MAX_MEMBERS:
            raise ValueError("rollout expansion exceeds the bounded population")
        return tuple(expanded)

    def explicit_intent(
        self, expansion: tuple[ProfiledRolloutExpandedMember, ...]
    ) -> ProfiledRolloutIntent:
        return ProfiledRolloutIntent(
            change_id=self.change_id,
            operation=self.operation,
            members=tuple(member.member_intent() for member in expansion),
            policy=self.policy,
        )


class RolloutCredentialAdmission(_Frozen):
    """Secret-free decision supplied by an independent credential authority.

    This observation of availability is not a credential or deployment grant.
    The future protected integration must independently revalidate it.
    """

    authority: Slug
    device_identity: DeviceIdentity
    credential_reference: str = Field(max_length=200)
    permitted: Literal[True]

    @model_validator(mode="after")
    def exact_reference(self) -> RolloutCredentialAdmission:
        device_id = self.device_identity.rsplit(":", 1)[1]
        if self.credential_reference != f"openbao:kv-v2:ncdp/devices/{device_id}/ssh":
            raise ValueError("rollout credential authority reference mismatch")
        return self


class RolloutCredentialAuthority(Protocol):
    def admit(self, device_identity: str) -> RolloutCredentialAdmission:
        """Return an exact positive decision, or raise; no inferred permission."""
        ...


class RolloutPlanningInventory(ProfiledPlanningInventory, Protocol):
    def resolve_profiled_population(self) -> ProfiledInventoryPopulation: ...


def _unique_json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate child artifact JSON key")
        result[key] = value
    return result


class ProfiledRolloutChild(_Frozen):
    """Exact original UTF-8 artifact bytes plus resolved selected authority facts."""

    device: ProfiledInventoryDevice
    interface: StableInterfaceIdentity
    operation_admission: ProfiledOperationAdmission
    credential_admission: RolloutCredentialAdmission
    kind: Literal["DEPLOYABLE", "COMPLIANT"]
    artifact_json: str = Field(min_length=1, max_length=MAX_CHILD_BYTES)
    artifact_digest: Sha256Digest
    result_digest: Sha256Digest

    def artifact_bytes(self) -> bytes:
        return self.artifact_json.encode("utf-8")

    def result(self) -> ProfiledDeploymentPlan | ProfiledComplianceRecord:
        raw = self.artifact_bytes()
        if len(raw) > MAX_CHILD_BYTES or _digest(raw) != self.artifact_digest:
            raise ValueError("rollout child artifact bytes rejected")
        value = json.loads(raw, object_pairs_hook=_unique_json_object)
        model = (
            ProfiledDeploymentPlan
            if self.kind == "DEPLOYABLE"
            else ProfiledComplianceRecord
        )
        result = model.model_validate(value)
        if result.digest != self.result_digest:
            raise ValueError("rollout child result digest rejected")
        return result

    @model_validator(mode="after")
    def exact_child(self) -> ProfiledRolloutChild:
        result = self.result()
        device = self.device
        _admit_profiled_device(device)
        target = device.live_read_only_target()
        admission = admit_profiled_operation(
            device, ProfiledOperation.INTERFACE_DESCRIPTION
        )
        if (
            self.operation_admission != admission
            or self.credential_admission.device_identity != device.device_identity
            or self.credential_admission.credential_reference
            != result.credential_reference
            or result.device_identity != device.device_identity
            or result.target != device.logical_name
            or result.interface != self.interface
            or result.platform_slug != device.platform.slug
            or result.automation_profile_id != device.automation_profile_id
            or result.network_os != device.network_os
            or result.host != target.host
            or result.port != target.port
            or result.expected_hostname != device.expected_hostname
        ):
            raise ValueError("rollout child resolved facts disagree")
        _assert_profiled_interface_binding(
            InterfaceDescriptionIntent(
                change_id=result.change_id,
                kind="interface_description",
                target=result.target,
                interface=result.interface.name,
                desired={"description": result.desired_description},
            ),
            device,
            self.interface,
        )
        return self

    @property
    def family(self) -> tuple[str, str]:
        admission = self.operation_admission
        return admission.adapter_family.value, admission.recovery_family.value


def _cohorts(intent, children):
    deployable = tuple(child for child in children if child.kind == "DEPLOYABLE")
    by_name = {child.device.logical_name: child for child in deployable}
    families = {child.family for child in deployable}
    canaries = intent.policy.canaries
    if canaries is None:
        chosen = []
        represented = set()
        for child in deployable:
            if child.family not in represented:
                chosen.append(child.device.logical_name)
                represented.add(child.family)
        canaries = tuple(chosen)
    if (
        not set(canaries) <= set(by_name)
        or len(canaries) != len(set(canaries))
        or {by_name[name].family for name in canaries} != families
    ):
        raise ValueError("rollout canaries must cover deployable families exactly")
    if len(deployable) > len(families) and len(canaries) == len(deployable):
        raise ValueError("rollout must retain a deployable wave when possible")
    remaining = tuple(name for name in by_name if name not in canaries)
    waves = tuple(
        remaining[index : index + intent.policy.wave_size]
        for index in range(0, len(remaining), intent.policy.wave_size)
    )
    identities = {
        child.device.logical_name: child.device.device_identity for child in children
    }
    return (
        tuple(identities[name] for name in canaries),
        tuple(tuple(identities[name] for name in wave) for wave in waves),
    )


class _RolloutResult(_Frozen):
    schema_version: Literal["1"] = "1"
    source_commit: GitCommit
    intent: ProfiledRolloutIntent
    children: tuple[ProfiledRolloutChild, ...] = Field(
        min_length=1, max_length=MAX_MEMBERS
    )
    digest: Sha256Digest

    def calculated_digest(self) -> str:
        return _digest(
            json.dumps(
                self.model_dump(mode="json", exclude={"digest"}),
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        )

    def _member_intents(self) -> tuple[ProfiledRolloutMemberIntent, ...]:
        return self.intent.members

    @model_validator(mode="after")
    def exact_population(self) -> _RolloutResult:
        members = self._member_intents()
        if len(self.children) != len(members):
            raise ValueError("rollout must positively represent every selected member")
        for identities in (
            tuple(child.device.device_identity for child in self.children),
            tuple(child.interface.interface for child in self.children),
        ):
            if len(identities) != len(set(identities)):
                raise ValueError("rollout stable identities must be unique")
        for member, child in zip(members, self.children, strict=True):
            admit_intent_result(
                member.child_intent(self.intent.change_id), child.result()
            )
        if self.digest != self.calculated_digest():
            raise ValueError("rollout parent digest rejected")
        return self


class ProfiledRolloutPlan(_RolloutResult):
    """Planning artifact only; no promotion or execution surface exists here."""

    result_type: Literal["profiled_rollout_plan"] = "profiled_rollout_plan"
    canaries: tuple[DeviceIdentity, ...] = Field(min_length=1)
    waves: tuple[tuple[DeviceIdentity, ...], ...]

    @model_validator(mode="after")
    def exact_cohorts(self) -> ProfiledRolloutPlan:
        if (self.canaries, self.waves) != _cohorts(self.intent, self.children):
            raise ValueError("rollout cohorts differ from frozen policy and children")
        return self


class ProfiledRolloutCompliance(_RolloutResult):
    """All members positively compliant; no plan or write authority."""

    result_type: Literal["profiled_rollout_compliance"] = "profiled_rollout_compliance"
    outcome: Literal["COMPLIANT"] = "COMPLIANT"
    plan: None = None
    promotion_minted: Literal[False] = False
    execution_attempted: Literal[False] = False
    recovery_attempted: Literal[False] = False
    chronology_required: Literal[False] = False

    @model_validator(mode="after")
    def all_compliant(self) -> ProfiledRolloutCompliance:
        if any(child.kind != "COMPLIANT" for child in self.children):
            raise ValueError("rollout compliance requires every child COMPLIANT")
        if _cohorts(self.intent, self.children) != ((), ()):
            raise ValueError("compliance cannot contain write cohorts")
        return self


class _RolloutResultV2(_RolloutResult):
    schema_version: Literal["2"] = "2"
    intent: ProfiledRolloutSelectionIntent
    selected_population: ProfiledPopulationDeclaration
    expansion: tuple[ProfiledRolloutExpandedMember, ...] = Field(
        min_length=1, max_length=MAX_MEMBERS
    )

    def _member_intents(self) -> tuple[ProfiledRolloutMemberIntent, ...]:
        if not self.intent.selectors:
            raise ValueError("selector-capable parent requires selector clauses")
        if set(self.selected_population.identities) != {
            child.device.device_identity for child in self.children
        }:
            raise ValueError("frozen selected population must equal child membership")
        for child in self.children:
            if self.selected_population.member(
                child.device.logical_name
            ) != _admit_profiled_device(child.device):
                raise ValueError("frozen selected population facts disagree")
        # This checks frozen evidence, not complete current external authority.
        # The service must independently expand against the full admitted population.
        expected = self.intent.expand(self.selected_population)
        if expected != self.expansion:
            raise ValueError("rollout expansion provenance or payload rejected")
        return self.intent.explicit_intent(expected).members


class ProfiledRolloutPlanV2(_RolloutResultV2):
    """Selector-capable planning artifact; no promotion/execution authority."""

    result_type: Literal["profiled_rollout_plan"] = "profiled_rollout_plan"
    canaries: tuple[DeviceIdentity, ...] = Field(min_length=1)
    waves: tuple[tuple[DeviceIdentity, ...], ...]

    @model_validator(mode="after")
    def exact_cohorts(self) -> ProfiledRolloutPlanV2:
        if (self.canaries, self.waves) != _cohorts(self.intent, self.children):
            raise ValueError("rollout cohorts differ from frozen policy and children")
        return self


class ProfiledRolloutComplianceV2(_RolloutResultV2):
    """Positive selector-capable compliance, with no write cohorts or authority."""

    result_type: Literal["profiled_rollout_compliance"] = "profiled_rollout_compliance"
    outcome: Literal["COMPLIANT"] = "COMPLIANT"
    plan: None = None
    promotion_minted: Literal[False] = False
    execution_attempted: Literal[False] = False
    recovery_attempted: Literal[False] = False
    chronology_required: Literal[False] = False

    @model_validator(mode="after")
    def all_compliant(self) -> ProfiledRolloutComplianceV2:
        if any(child.kind != "COMPLIANT" for child in self.children):
            raise ValueError("rollout compliance requires every child COMPLIANT")
        if _cohorts(self.intent, self.children) != ((), ()):
            raise ValueError("compliance cannot contain write cohorts")
        return self


ProfiledRolloutPlanningArtifact = (
    ProfiledRolloutPlan
    | ProfiledRolloutCompliance
    | ProfiledRolloutPlanV2
    | ProfiledRolloutComplianceV2
)


def read_profiled_rollout(raw: bytes) -> ProfiledRolloutPlanningArtifact:
    """Dispatch exact version/type pairs; v1 is never interpreted as v2."""
    value = json.loads(raw, object_pairs_hook=_unique_json_object)
    if not isinstance(value, dict):
        raise ValueError("rollout artifact must be an object")
    models = {
        ("1", "profiled_rollout_plan"): ProfiledRolloutPlan,
        ("1", "profiled_rollout_compliance"): ProfiledRolloutCompliance,
        ("2", "profiled_rollout_plan"): ProfiledRolloutPlanV2,
        ("2", "profiled_rollout_compliance"): ProfiledRolloutComplianceV2,
    }
    version, kind = value.get("schema_version"), value.get("result_type")
    if not isinstance(version, str) or not isinstance(kind, str):
        raise ValueError("rollout artifact version/type required")
    model = models.get((version, kind))
    if model is None:
        raise ValueError("unsupported rollout artifact version/type")
    return model.model_validate(value)


class _ResolvedInventory:
    """Use the exact admitted read-only resolution for the existing child planner."""

    def __init__(self, device, interface):
        self.device, self.interface = device, interface

    def resolve(self, target):
        if target != self.device.logical_name:
            raise ValueError("rollout resolved target changed")
        return self.device

    def resolve_interface(self, device, interface_name):
        if device != self.device or interface_name != self.interface.name:
            raise ValueError("rollout resolved interface changed")
        return self.interface


def _admit_rollout_members(
    intent, inventory, credential_authority, *, expected_targets=None
):
    """Resolve the complete population and every selected member without secrets."""
    population = ProfiledInventoryPopulation.model_validate(
        inventory.resolve_profiled_population().model_dump()
    )
    expansion = None
    if isinstance(intent, ProfiledRolloutSelectionIntent):
        expansion = intent.expand(population.declaration)
        planning_intent = intent.explicit_intent(expansion)
    else:
        planning_intent = intent
    if (
        expected_targets is not None
        and tuple(member.target for member in planning_intent.members)
        != expected_targets
    ):
        raise ValueError("stale rollout membership/order")
    by_name = {device.logical_name: device for device in population.devices}
    admitted = []
    identities, interface_ids = set(), set()
    for member in planning_intent.members:
        declared = population.declaration.member(member.target)
        device = ProfiledInventoryDevice.model_validate(
            inventory.resolve(member.target).model_dump()
        )
        if (
            device != by_name[member.target]
            or device.device_identity != declared.device_identity
        ):
            raise ValueError(
                "rollout resolution differs from admitted managed population"
            )
        operation = admit_profiled_operation(
            device, ProfiledOperation.INTERFACE_DESCRIPTION
        )
        interface = StableInterfaceIdentity.model_validate(
            inventory.resolve_interface(device, member.interface).model_dump()
        )
        _assert_profiled_interface_binding(
            member.child_intent(intent.change_id), device, interface
        )
        if device.device_identity in identities or interface.interface in interface_ids:
            raise ValueError("rollout stable identities must be unique")
        identities.add(device.device_identity)
        interface_ids.add(interface.interface)
        authority = RolloutCredentialAdmission.model_validate(
            credential_authority.admit(device.device_identity).model_dump()
        )
        if authority.device_identity != device.device_identity:
            raise ValueError("rollout credential decision is for another device")
        admitted.append((member, device, interface, operation, authority))

    return population, expansion, planning_intent, admitted


def plan_profiled_rollout(
    intent: ProfiledRolloutIntent | ProfiledRolloutSelectionIntent,
    inventory: RolloutPlanningInventory,
    credential_authority: RolloutCredentialAuthority,
    secrets: ProfiledPlanningSecretProvider,
    collector: ProfiledPlanningCollector,
    *,
    source_commit: str,
    created_at: datetime | None = None,
) -> ProfiledRolloutPlanningArtifact:
    """Resolve/admit all members, reuse read-only child planning, then freeze.

    No partial parent is returned or published on any exception. Providers remain
    caller-owned; this module supplies no credentials, transports or writer.
    """
    intent_model = (
        ProfiledRolloutSelectionIntent
        if isinstance(intent, ProfiledRolloutSelectionIntent)
        else ProfiledRolloutIntent
    )
    intent = intent_model.model_validate(intent.model_dump())
    source_commit = TypeAdapter(GitCommit).validate_python(source_commit)
    observation_time = (
        TypeAdapter(AwareDatetime).validate_python(created_at)
        if created_at is not None
        else None
    )
    population, expansion, planning_intent, admitted = _admit_rollout_members(
        intent, inventory, credential_authority
    )

    children = []
    for member, device, interface, operation, authority in admitted:
        result = plan_profiled_change(
            member.child_intent(intent.change_id),
            _ResolvedInventory(device, interface),
            secrets,
            collector,
            created_at=observation_time,
        )
        if (result.plan is None) == (result.compliance is None):
            raise ValueError("rollout child planning must return exactly one result")
        child = result.plan if result.plan is not None else result.compliance
        # This is the original artifact serialization. Retain these bytes verbatim;
        # readers verify them directly, never by reserializing the parsed model.
        raw = child.model_dump_json(indent=2).encode()
        children.append(
            ProfiledRolloutChild(
                device=device,
                interface=interface,
                operation_admission=operation,
                credential_admission=authority,
                kind="DEPLOYABLE" if result.plan is not None else "COMPLIANT",
                artifact_json=raw.decode(),
                artifact_digest=_digest(raw),
                result_digest=child.digest,
            )
        )
    canaries, waves = _cohorts(intent, children)
    model = ProfiledRolloutPlan if canaries else ProfiledRolloutCompliance
    values = {
        "source_commit": source_commit,
        "intent": planning_intent,
        "children": tuple(children),
    }
    if isinstance(intent, ProfiledRolloutSelectionIntent) and intent.selectors:
        model = ProfiledRolloutPlanV2 if canaries else ProfiledRolloutComplianceV2
        selected_ids = {child.device.device_identity for child in children}
        values.update(
            intent=intent,
            expansion=expansion,
            selected_population=ProfiledPopulationDeclaration(
                members=tuple(
                    member
                    for member in population.declaration.members
                    if member.device_identity in selected_ids
                )
            ),
        )
    if canaries:
        values.update(canaries=canaries, waves=waves)
    unsigned = model.model_construct(**values)
    values["digest"] = unsigned.calculated_digest()
    return model.model_validate(values)
