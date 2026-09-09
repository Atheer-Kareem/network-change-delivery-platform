"""Pure frozen rollout authorization; no scheduler, reservation or device access."""

import json
from dataclasses import replace
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from network_change_delivery.architecture_contracts import GitCommit, Sha256Digest
from network_change_delivery.models import CliBoundString
from network_change_delivery.profiled_promotion import checked_uuid, digest_bytes
from network_change_delivery.profiled_rollout import MAX_MEMBERS, DeviceIdentity
from network_change_delivery.profiled_rollout_promotion import (
    RolloutPlanningPublication,
    verify_rollout_promotion,
)


class ProfiledRolloutAuthorization(BaseModel):
    """Human provenance for an already-frozen promotion, never a target selector.

    Fields are derived by authorize_rollout, not collected from human input.
    Self-digest/readback consistency alone does not authenticate the unblocker.
    The future protected caller must establish scheduler provenance independently.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal["1"] = "1"
    authorization_type: Literal["profiled_rollout_authorization"] = (
        "profiled_rollout_authorization"
    )
    build_id: str
    source_commit: GitCommit
    change_id: CliBoundString = Field(max_length=100)
    parent_digest: Sha256Digest
    parent_artifact_digest: Sha256Digest
    promotion_digest: Sha256Digest
    promotion_artifact_digest: Sha256Digest
    selected_devices: tuple[DeviceIdentity, ...] = Field(
        min_length=1, max_length=MAX_MEMBERS
    )
    canaries: tuple[DeviceIdentity, ...] = Field(min_length=1, max_length=MAX_MEMBERS)
    waves: tuple[tuple[DeviceIdentity, ...], ...] = Field(max_length=MAX_MEMBERS)
    unblocker_id: str
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
        checked_uuid(self.unblocker_id)
        cohorts = self.canaries + tuple(
            member for wave in self.waves for member in wave
        )
        if (
            len(self.selected_devices) != len(set(self.selected_devices))
            or len(cohorts) != len(set(cohorts))
            or not set(cohorts).issubset(self.selected_devices)
            or any(not wave for wave in self.waves)
            or self.digest != self.calculated_digest()
        ):
            raise ValueError("rollout authorization binding rejected")
        return self


def authorize_rollout(
    context,
    parent_bytes: bytes,
    publication: RolloutPlanningPublication,
    promotion_bytes: bytes,
    receipts,
    batfish: str,
    cml: str,
    promotion_digest: str,
    promotion_artifact_digest: str,
    unblocker_id: str,
    *,
    intent,
) -> ProfiledRolloutAuthorization:
    """Reconstruct authority inputs before binding the fieldless human provenance.

    Context supplies identity, not admission of any new runtime step. The future
    protected wrapper still owns canonical checkout and scheduler checks.
    """
    checked_uuid(unblocker_id)
    checked_uuid(context.build_id)
    checked_uuid(context.job_id)
    if digest_bytes(promotion_bytes) != promotion_artifact_digest:
        raise ValueError("rollout promotion artifact metadata rejected")
    # Reuse the exact existing mint/readback contract, with its promotion context.
    # This verifies publication, parent/intent/current expansion/static authority,
    # original bytes and every same-build prerequisite; parsing alone is not enough.
    promotion = verify_rollout_promotion(
        promotion_bytes,
        replace(context, step="profiled-rollout-promotion"),
        parent_bytes,
        publication,
        receipts,
        batfish,
        cml,
        intent=intent,
    )
    if promotion.digest != promotion_digest:
        raise ValueError("rollout promotion semantic metadata rejected")
    values = {
        "build_id": promotion.build_id,
        "source_commit": promotion.source_commit,
        "change_id": promotion.change_id,
        "parent_digest": promotion.parent_digest,
        "parent_artifact_digest": promotion.parent_artifact_digest,
        "promotion_digest": promotion.digest,
        "promotion_artifact_digest": promotion_artifact_digest,
        "selected_devices": tuple(
            child.device_identity for child in promotion.children
        ),
        "canaries": promotion.canaries,
        "waves": promotion.waves,
        "unblocker_id": unblocker_id,
    }
    unsigned = ProfiledRolloutAuthorization.model_construct(**values)
    return ProfiledRolloutAuthorization(**values, digest=unsigned.calculated_digest())
