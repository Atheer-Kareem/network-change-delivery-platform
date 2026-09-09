"""Same-build rollout publication/promotion only; no authorization or execution."""

import json
from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from network_change_delivery.architecture_contracts import GitCommit, Sha256Digest
from network_change_delivery.models import CliBoundString
from network_change_delivery.openbao_profiled_deploy_config import (
    ProtectedRolloutCredentialAuthority,
)
from network_change_delivery.profile_inventory import PROFILED_MANAGED_POPULATION
from network_change_delivery.profiled_promotion import (
    ProfiledBuildContext,
    checked_digest,
    checked_uuid,
    digest_bytes,
    verify_validation,
)
from network_change_delivery.profiled_rollout import (
    MAX_MEMBERS,
    DeviceIdentity,
    ProfiledRolloutIntent,
    ProfiledRolloutPlan,
    ProfiledRolloutPlanV2,
    ProfiledRolloutSelectionIntent,
    read_profiled_rollout,
)

ROLLOUT_PLANNING_METADATA = "profiled-rollout-planning-result"
ROLLOUT_PROMOTION_METADATA = "profiled-rollout-promotion-digest"
ROLLOUT_PROMOTION_BYTES_METADATA = "profiled-rollout-promotion-artifact-digest"
PLAN_TYPES = (ProfiledRolloutPlan, ProfiledRolloutPlanV2)


def admit_rollout_result(intent, value, commit):
    """Bind independently loaded reviewed instructions to an exact current parent."""
    model = (
        ProfiledRolloutSelectionIntent
        if isinstance(intent, ProfiledRolloutSelectionIntent)
        else ProfiledRolloutIntent
    )
    intent = model.model_validate(intent.model_dump())
    if isinstance(intent, ProfiledRolloutSelectionIntent) and not intent.selectors:
        intent = ProfiledRolloutIntent(
            change_id=intent.change_id,
            operation=intent.operation,
            members=intent.explicit_members,
            policy=intent.policy,
        )
    if value.source_commit != commit or value.intent != intent:
        raise ValueError("committed rollout intent/source disagrees with parent")
    if (
        isinstance(intent, ProfiledRolloutSelectionIntent)
        and intent.expand(PROFILED_MANAGED_POPULATION) != value.expansion
    ):
        raise ValueError("rollout expansion differs from current Git declaration")
    authority = ProtectedRolloutCredentialAuthority()
    for child in value.children:
        if authority.admit(child.device.device_identity) != child.credential_admission:
            raise ValueError("rollout protected credential admission disagrees")


class RolloutPlanningPublication(BaseModel):
    """A successful publication receipt is selection evidence, never write authority."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal["1"] = "1"
    receipt_type: Literal["profiled_rollout_planning_publication"] = (
        "profiled_rollout_planning_publication"
    )
    build_id: str
    commit: GitCommit
    artifact_kind: Literal["plan", "compliance"]
    parent_schema_version: Literal["1", "2"]
    artifact_digest: Sha256Digest
    result_digest: Sha256Digest

    @model_validator(mode="after")
    def identity(self):
        checked_uuid(self.build_id)
        return self

    def read(self, context, raw, intent):
        if self.build_id != context.build_id or self.commit != context.commit:
            raise ValueError("rollout publication context rejected")
        if digest_bytes(raw) != self.artifact_digest:
            raise ValueError("rollout publication bytes rejected")
        value = read_profiled_rollout(raw)
        if (
            value.schema_version != self.parent_schema_version
            or value.digest != self.result_digest
            or self.artifact_kind
            != ("plan" if isinstance(value, PLAN_TYPES) else "compliance")
        ):
            raise ValueError("rollout publication result rejected")
        admit_rollout_result(intent, value, context.commit)
        return value


class RolloutPromotedChild(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    device_identity: DeviceIdentity
    interface_identity: str = Field(pattern=r"^netbox:dcim\.interface:[1-9][0-9]*$")
    kind: Literal["DEPLOYABLE", "COMPLIANT"]
    artifact_digest: Sha256Digest
    result_digest: Sha256Digest


class ProfiledRolloutPromotion(BaseModel):
    """Distinct rollout schema; cannot be consumed by single-target deployment."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal["1"] = "1"
    promotion_type: Literal["profiled_rollout_promotion"] = "profiled_rollout_promotion"
    build_id: str
    source_commit: GitCommit
    change_id: CliBoundString = Field(max_length=100)
    parent_schema_version: Literal["1", "2"]
    parent_result_type: Literal["profiled_rollout_plan"] = "profiled_rollout_plan"
    parent_digest: Sha256Digest
    parent_artifact_digest: Sha256Digest
    children: tuple[RolloutPromotedChild, ...] = Field(
        min_length=1, max_length=MAX_MEMBERS
    )
    canaries: tuple[DeviceIdentity, ...] = Field(min_length=1, max_length=MAX_MEMBERS)
    waves: tuple[tuple[DeviceIdentity, ...], ...] = Field(max_length=MAX_MEMBERS)
    validation_digest: Sha256Digest
    batfish_digest: Sha256Digest
    cml_digest: Sha256Digest
    digest: Sha256Digest

    def calculated_digest(self):
        return digest_bytes(
            json.dumps(
                self.model_dump(mode="json", exclude={"digest"}),
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        )

    @model_validator(mode="after")
    def verified(self):
        checked_uuid(self.build_id)
        devices = tuple(child.device_identity for child in self.children)
        interfaces = tuple(child.interface_identity for child in self.children)
        deployable = {
            child.device_identity
            for child in self.children
            if child.kind == "DEPLOYABLE"
        }
        cohorts = self.canaries + tuple(
            member for wave in self.waves for member in wave
        )
        if (
            len(devices) != len(set(devices))
            or len(interfaces) != len(set(interfaces))
            or not deployable
            or set(cohorts) != deployable
            or len(cohorts) != len(set(cohorts))
            or any(not wave for wave in self.waves)
            or self.digest != self.calculated_digest()
        ):
            raise ValueError("rollout promotion binding rejected")
        return self


def promote_rollout(
    context: ProfiledBuildContext,
    raw: bytes,
    publication: RolloutPlanningPublication,
    receipts: Mapping[str, str],
    batfish: str,
    cml: str,
    *,
    intent: ProfiledRolloutIntent | ProfiledRolloutSelectionIntent,
) -> ProfiledRolloutPromotion:
    if context.step != "profiled-rollout-promotion":
        raise ValueError("rollout promotion step rejected")
    publication = RolloutPlanningPublication.model_validate(publication.model_dump())
    parent = publication.read(context, raw, intent)
    if not isinstance(parent, PLAN_TYPES):
        raise ValueError("COMPLIANT rollout cannot mint promotion")
    values = {
        "build_id": context.build_id,
        "source_commit": context.commit,
        "change_id": parent.intent.change_id,
        "parent_schema_version": parent.schema_version,
        "parent_digest": parent.digest,
        "parent_artifact_digest": digest_bytes(raw),
        "children": tuple(
            RolloutPromotedChild(
                device_identity=child.device.device_identity,
                interface_identity=child.interface.interface,
                kind=child.kind,
                artifact_digest=child.artifact_digest,
                result_digest=child.result_digest,
            )
            for child in parent.children
        ),
        "canaries": parent.canaries,
        "waves": parent.waves,
        "validation_digest": verify_validation(context, receipts),
        "batfish_digest": checked_digest(batfish),
        "cml_digest": checked_digest(cml),
    }
    unsigned = ProfiledRolloutPromotion.model_construct(**values)
    return ProfiledRolloutPromotion(**values, digest=unsigned.calculated_digest())


def verify_rollout_promotion(raw_promotion, *args, **kwargs):
    """Readback must agree with independently verified parent and prerequisites."""
    value = ProfiledRolloutPromotion.model_validate_json(raw_promotion)
    if value != promote_rollout(*args, **kwargs):
        raise ValueError("rollout promotion readback rejected")
    return value
