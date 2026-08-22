"""Offline promotion bundles for the Buildkite deployment-gate boundary."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from network_change_delivery.assurance import prepare_snapshot
from network_change_delivery.models import DeploymentPlan, FleetDeploymentPlan
from network_change_delivery.plan_assurance import (
    BatfishAssurancePolicy,
    PlanAssuranceRecord,
    verify_plan_assurance,
)

GitSha = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{40}$")]
Sha256 = Annotated[str, StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$")]


class PromotionError(ValueError):
    """Bounded promotion validation failure."""


class PromotedArtifact(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    logical_name: str
    relative_path: str
    sha256: Sha256
    size_bytes: int = Field(ge=0)


class DeploymentPromotionManifest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal["1"] = "1"
    git_commit: GitSha
    plan_digest: Sha256
    assurance_record_digest: Sha256
    policy_digest: Sha256
    baseline_snapshot_digest: Sha256
    candidate_snapshot_digest: Sha256
    artifacts: tuple[PromotedArtifact, ...]
    generated_at: datetime
    digest: Sha256

    @model_validator(mode="after")
    def validate_manifest(self) -> DeploymentPromotionManifest:
        if len({a.logical_name for a in self.artifacts}) != len(self.artifacts):
            raise ValueError("promotion artifact logical names must be unique")
        if len({a.relative_path for a in self.artifacts}) != len(self.artifacts):
            raise ValueError("promotion artifact paths must be unique")
        for artifact in self.artifacts:
            path = PurePosixPath(artifact.relative_path)
            if (
                path.is_absolute()
                or path.as_posix() != artifact.relative_path
                or any(part in {"", ".", ".."} for part in path.parts)
            ):
                raise ValueError("promotion artifact path is not canonical")
        if tuple(self.artifacts) != tuple(
            sorted(self.artifacts, key=lambda a: (a.logical_name, a.relative_path))
        ):
            raise ValueError("promotion artifacts must be deterministically ordered")
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


def _sha(path: Path) -> tuple[str, int]:
    if path.is_symlink() or not path.is_file():
        raise PromotionError("promotion artifact must be a regular file")
    data = path.read_bytes()
    return "sha256:" + hashlib.sha256(data).hexdigest(), len(data)


def _write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        offset = 0
        while offset < len(data):
            written = os.write(fd, data[offset:])
            if written <= 0:
                raise OSError("promotion write made no progress")
            offset += written
        os.fsync(fd)
    finally:
        os.close(fd)


def _load_plan_bytes(data: bytes) -> DeploymentPlan | FleetDeploymentPlan:
    payload = json.loads(data)
    plan = (
        FleetDeploymentPlan.model_validate(payload)
        if "members" in payload
        else DeploymentPlan.model_validate(payload)
    )
    if not plan.verify_digest():
        raise PromotionError("promotion plan digest verification failed")
    return plan


def _policy(path: Path) -> BatfishAssurancePolicy:
    try:
        return BatfishAssurancePolicy.model_validate(
            yaml.safe_load(path.read_text(encoding="utf-8"))
        )
    except Exception as exc:
        raise PromotionError("invalid assurance policy") from exc


def _artifact(logical: str, root: Path, relative: str) -> PromotedArtifact:
    digest, size = _sha(root / relative)
    return PromotedArtifact(
        logical_name=logical, relative_path=relative, sha256=digest, size_bytes=size
    )


def create_promotion_bundle(
    plan_path: Path,
    policy_path: Path,
    baseline_path: Path,
    assurance_path: Path,
    git_commit: str,
    destination: Path,
) -> DeploymentPromotionManifest:
    if destination.exists() or destination.is_symlink():
        raise PromotionError("promotion destination already exists")
    plan_bytes = plan_path.read_bytes()
    policy_bytes = policy_path.read_bytes()
    assurance_bytes = assurance_path.read_bytes()
    plan = _load_plan_bytes(plan_bytes)
    try:
        policy = BatfishAssurancePolicy.model_validate(yaml.safe_load(policy_bytes))
    except Exception as exc:
        raise PromotionError("invalid assurance policy") from exc
    try:
        record = PlanAssuranceRecord.model_validate_json(assurance_bytes)
    except Exception as exc:
        raise PromotionError("invalid assurance record") from exc
    if not record.verify_digest() or record.outcome.value != "PASSED":
        raise PromotionError("assurance record is not a valid PASSED record")
    if not verify_plan_assurance(plan, policy, baseline_path, record):
        raise PromotionError("assurance record does not verify for plan and baseline")
    with prepare_snapshot(baseline_path) as baseline:
        if record.baseline_snapshot_digest != baseline.manifest.digest:
            raise PromotionError("assurance baseline digest mismatch")
        destination.mkdir(mode=0o700)
        try:
            (destination / "baseline").mkdir(mode=0o700)
            (destination / "baseline/configs").mkdir(mode=0o700)
            _write_bytes(destination / "plan.json", plan_bytes)
            _write_bytes(destination / "policy.yaml", policy_bytes)
            _write_bytes(destination / "assurance.json", assurance_bytes)
            for entry in baseline.manifest.files:
                target = destination / "baseline/configs" / entry.relative_path
                target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                _write_bytes(
                    target,
                    (baseline.root / "configs" / entry.relative_path).read_bytes(),
                )
            artifacts = [
                _artifact("plan", destination, "plan.json"),
                _artifact("policy", destination, "policy.yaml"),
                _artifact("plan_assurance_record", destination, "assurance.json"),
            ]
            artifacts.extend(
                _artifact(
                    f"baseline:{entry.relative_path}",
                    destination,
                    f"baseline/configs/{entry.relative_path}",
                )
                for entry in baseline.manifest.files
            )
            manifest = DeploymentPromotionManifest(
                git_commit=git_commit,
                plan_digest=plan.digest,
                assurance_record_digest=record.digest,
                policy_digest=policy.calculated_digest(),
                baseline_snapshot_digest=baseline.manifest.digest,
                candidate_snapshot_digest=record.candidate_snapshot_digest,
                artifacts=tuple(
                    sorted(artifacts, key=lambda a: (a.logical_name, a.relative_path))
                ),
                generated_at=datetime.now(UTC),
                digest="sha256:" + "0" * 64,
            )
            manifest = manifest.model_copy(
                update={"digest": manifest.calculated_digest()}
            )
            manifest_path = destination / "manifest.json"
            _write_bytes(
                manifest_path, (manifest.model_dump_json(indent=2) + "\n").encode()
            )
            if (
                verify_promotion_bundle(destination, git_commit).digest
                != manifest.digest
            ):
                raise PromotionError("created promotion failed internal verification")
            return manifest
        except Exception:
            shutil.rmtree(destination, ignore_errors=True)
            raise


def verify_promotion_bundle(
    promotion: Path, expected_git_commit: str
) -> DeploymentPromotionManifest:
    if promotion.is_symlink() or not promotion.is_dir():
        raise PromotionError("promotion directory is invalid")
    try:
        manifest = DeploymentPromotionManifest.model_validate_json(
            (promotion / "manifest.json").read_text(encoding="utf-8")
        )
    except Exception as exc:
        raise PromotionError("invalid promotion manifest") from exc
    if not manifest.verify_digest() or manifest.git_commit != expected_git_commit:
        raise PromotionError("promotion manifest binding failed")
    expected = {"manifest.json"} | {a.relative_path for a in manifest.artifacts}
    expected_dirs = {"baseline", "baseline/configs"}
    expected_dirs.update(
        str(Path(a.relative_path).parent)
        for a in manifest.artifacts
        if a.relative_path.startswith("baseline/")
    )
    actual: set[str] = set()
    for path in promotion.rglob("*"):
        rel = path.relative_to(promotion).as_posix()
        if path.is_symlink():
            raise PromotionError("promotion contains an invalid file")
        if path.is_dir():
            if rel not in expected_dirs:
                raise PromotionError("promotion contains an unexpected directory")
            continue
        if not stat.S_ISREG(path.stat().st_mode):
            raise PromotionError("promotion contains an invalid file")
        if path.is_file():
            actual.add(rel)
    if actual != expected:
        raise PromotionError("promotion artifact set mismatch")
    for artifact in manifest.artifacts:
        digest, size = _sha(promotion / artifact.relative_path)
        if digest != artifact.sha256 or size != artifact.size_bytes:
            raise PromotionError("promotion artifact digest mismatch")
    plan = _load_plan_bytes((promotion / "plan.json").read_bytes())
    policy = _policy(promotion / "policy.yaml")
    record = PlanAssuranceRecord.model_validate_json(
        (promotion / "assurance.json").read_text(encoding="utf-8")
    )
    if not record.verify_digest() or not verify_plan_assurance(
        plan, policy, promotion / "baseline", record
    ):
        raise PromotionError("promotion assurance verification failed")
    checks = {
        manifest.plan_digest == plan.digest,
        manifest.policy_digest == policy.calculated_digest(),
        manifest.assurance_record_digest == record.digest,
        manifest.baseline_snapshot_digest == record.baseline_snapshot_digest,
        manifest.candidate_snapshot_digest == record.candidate_snapshot_digest,
    }
    if not all(checks):
        raise PromotionError("promotion binding digest mismatch")
    return manifest
