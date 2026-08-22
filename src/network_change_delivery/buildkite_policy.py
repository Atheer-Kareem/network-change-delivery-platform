"""Bounded, non-authenticating Buildkite deployment-gate context checks."""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, model_validator


class BuildkiteDeploymentContext(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    commit: str
    branch: str
    pull_request: str = ""
    pipeline_id: str
    build_id: str
    build_number: str
    job_id: str
    step_key: str
    queue_key: str

    @model_validator(mode="after")
    def validate_context(self) -> BuildkiteDeploymentContext:
        if self.branch != "main" or self.pull_request not in {"", "false", "0"}:
            raise ValueError("deployment gate requires a non-PR main build")
        if not re.fullmatch(r"[0-9a-f]{40}", self.commit):
            raise ValueError("Buildkite commit must be a lowercase SHA-1")
        if self.step_key != "deploy-gate" or self.queue_key != "ncdp-deploy":
            raise ValueError("deployment gate step or queue is invalid")
        if any(
            not value
            for value in (
                self.pipeline_id,
                self.build_id,
                self.build_number,
                self.job_id,
            )
        ):
            raise ValueError("Buildkite identifiers are required")
        return self


def validate_buildkite_deployment_context(
    context: BuildkiteDeploymentContext,
) -> BuildkiteDeploymentContext:
    return BuildkiteDeploymentContext.model_validate(context)


def compare_approved_digests(
    plan: str,
    assurance: str,
    promotion: str,
    *,
    approved_plan: str,
    approved_assurance: str,
    approved_promotion: str,
) -> None:
    if (plan, assurance, promotion) != (
        approved_plan,
        approved_assurance,
        approved_promotion,
    ):
        raise ValueError("approved promotion digests do not match")
