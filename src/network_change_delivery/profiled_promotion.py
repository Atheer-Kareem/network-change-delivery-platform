"""Current schema-v2 personal-lab promotion; no legacy executor or credential use."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from network_change_delivery.architecture_contracts import (
    NetBoxDeviceIdentity,
    Sha256Digest,
)
from network_change_delivery.models import CliBoundString, InterfaceDescriptionIntent
from network_change_delivery.profile_inventory import (
    PROFILED_MANAGED_POPULATION,
    ProfiledLogicalName,
)
from network_change_delivery.profiled_intent import admit_intent_result
from network_change_delivery.profiled_planning import (
    ProfiledDeploymentPlan,
)

VALIDATION_KEYS = (
    "quality-env",
    "quality-committed-diff",
    "quality-ruff-lint",
    "quality-ruff-format",
    "quality-pytest",
    "quality-ansible-lint",
    "quality-package-build",
    "quality-terraform-profiled-staging",
    "quality-snmp-generator",
    "quality-observability-runtime",
    "quality-snmpv3-synthetic",
    "buildkite-definition",
    "ncdp-pipeline-contract",
)
MAIN_KEYS = (
    "profiled-live-plan",
    "profiled-promotion",
    "profiled-human-authorization",
    "profiled-deploy",
    "profiled-deployment-evidence",
)
ROLLOUT_KEYS = ("profiled-rollout-live-plan", "profiled-rollout-promotion")
CANONICAL_REPOSITORIES = {
    "https://github.com/Atheer-Kareem/network-change-delivery-platform.git",
    "git@github.com:Atheer-Kareem/network-change-delivery-platform.git",
}
BATFISH_METADATA = "profiled-batfish-success"
CML_METADATA = "profiled-cml-success"
PROMOTION_METADATA = "profiled-promotion-digest"


def digest_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def checked_digest(value: str) -> str:
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", value):
        raise ValueError("required success digest missing or invalid")
    return value


def checked_uuid(value: str) -> str:
    if str(UUID(value)) != value:
        raise ValueError("Buildkite identity rejected")
    return value


@dataclass(frozen=True)
class ProfiledBuildContext:
    build_id: str
    commit: str
    job_id: str
    step: str

    @classmethod
    def from_environment(cls, environment: Mapping[str, str], *, main: bool = True):
        step = environment.get("BUILDKITE_STEP_KEY", "")
        queue = (
            "ncdp-deploy"
            if step
            in {"profiled-live-plan", "profiled-rollout-live-plan", "profiled-deploy"}
            else "ncdp-validation"
        )
        if (
            environment.get("BUILDKITE_REPO") not in CANONICAL_REPOSITORIES
            or environment.get("BUILDKITE_RETRY_COUNT") != "0"
            or environment.get("BUILDKITE_AGENT_META_DATA_QUEUE") != queue
            or not re.fullmatch(
                r"[0-9a-f]{40}", environment.get("BUILDKITE_COMMIT", "")
            )
            or (
                main
                and (
                    step not in (*MAIN_KEYS, *ROLLOUT_KEYS)
                    or environment.get("BUILDKITE_BRANCH") != "main"
                    or environment.get("BUILDKITE_PULL_REQUEST") != "false"
                    or environment.get("BUILDKITE_PULL_REQUEST_REPO")
                )
            )
            or (not main and step not in VALIDATION_KEYS)
        ):
            raise ValueError("profiled Buildkite context rejected")
        return cls(
            checked_uuid(environment.get("BUILDKITE_BUILD_ID", "")),
            environment["BUILDKITE_COMMIT"],
            checked_uuid(environment.get("BUILDKITE_JOB_ID", "")),
            step,
        )


def validation_receipt(build_id: str, commit: str, step: str) -> str:
    if step not in VALIDATION_KEYS:
        raise ValueError("unknown validation receipt")
    return digest_bytes(f"profiled-validation:{build_id}:{commit}:{step}".encode())


def verify_validation(
    context: ProfiledBuildContext, receipts: Mapping[str, str]
) -> str:
    if set(receipts) != set(VALIDATION_KEYS) or any(
        receipts[key] != validation_receipt(context.build_id, context.commit, key)
        for key in VALIDATION_KEYS
    ):
        raise ValueError("engineering validation prerequisites missing or invalid")
    return digest_bytes(json.dumps(dict(receipts), sort_keys=True).encode())


class ProfiledPromotion(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal["2"] = "2"
    promotion_type: Literal["profiled_buildkite_promotion"] = (
        "profiled_buildkite_promotion"
    )
    build_id: str
    commit: str
    change_id: CliBoundString = Field(max_length=255)
    target: ProfiledLogicalName
    device_identity: NetBoxDeviceIdentity
    plan_digest: Sha256Digest
    plan_artifact_digest: Sha256Digest
    validation_digest: Sha256Digest
    batfish_digest: Sha256Digest
    cml_digest: Sha256Digest
    digest: Sha256Digest

    def calculated_digest(self) -> str:
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
        member = PROFILED_MANAGED_POPULATION.member(self.target)
        if member.device_identity != self.device_identity:
            raise ValueError("promotion population pairing rejected")
        if (
            not re.fullmatch(r"[0-9a-f]{40}", self.commit)
            or self.digest != self.calculated_digest()
        ):
            raise ValueError("profiled promotion binding rejected")
        return self


def promote(
    context: ProfiledBuildContext,
    plan_bytes: bytes,
    receipts: Mapping[str, str],
    batfish: str,
    cml: str,
    *,
    intent: InterfaceDescriptionIntent,
) -> ProfiledPromotion:
    intent = InterfaceDescriptionIntent.model_validate(intent.model_dump())
    plan = ProfiledDeploymentPlan.model_validate_json(plan_bytes)
    admit_intent_result(intent, plan)
    values = {
        "build_id": context.build_id,
        "commit": context.commit,
        "change_id": plan.change_id,
        "target": plan.target,
        "device_identity": plan.device_identity,
        "plan_digest": plan.digest,
        "plan_artifact_digest": digest_bytes(plan_bytes),
        "validation_digest": verify_validation(context, receipts),
        "batfish_digest": checked_digest(batfish),
        "cml_digest": checked_digest(cml),
        "digest": "sha256:" + "0" * 64,
    }
    unsigned = ProfiledPromotion.model_construct(**values)
    values["digest"] = unsigned.calculated_digest()
    return ProfiledPromotion.model_validate(values)


def authorize(
    context: ProfiledBuildContext,
    promotion_bytes: bytes,
    plan_bytes: bytes,
    receipts: Mapping[str, str],
    batfish: str,
    cml: str,
    promoted_digest: str,
    unblocker_id: str,
    *,
    intent: InterfaceDescriptionIntent,
) -> ProfiledDeploymentPlan:
    if context.step != "profiled-deploy":
        raise ValueError("deployment step rejected")
    checked_uuid(unblocker_id)
    promotion = ProfiledPromotion.model_validate_json(promotion_bytes)
    expected = promote(context, plan_bytes, receipts, batfish, cml, intent=intent)
    if promotion != expected or promotion.digest != checked_digest(promoted_digest):
        raise ValueError("same-build promotion authorization rejected")
    return ProfiledDeploymentPlan.model_validate_json(plan_bytes)


PLANNING_METADATA = "profiled-planning-result"


class ProfiledPlanningPublication(BaseModel):
    """Select one successfully published same-build planning result, not authority."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal["2"] = "2"
    build_id: str
    commit: str
    artifact_kind: Literal["plan", "compliance"]
    artifact_digest: Sha256Digest
    result_digest: Sha256Digest

    def verify_context(self, context: ProfiledBuildContext) -> None:
        checked_uuid(self.build_id)
        if self.build_id != context.build_id or self.commit != context.commit:
            raise ValueError("planning publication context rejected")
