#!/usr/bin/env python3
"""Same-build schema-v2 personal-lab delivery steps; no status API queries."""

from __future__ import annotations

import html
import logging
import os
import stat
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

import yaml

from network_change_delivery.inventory import InventoryError
from network_change_delivery.models import InterfaceDescriptionIntent
from network_change_delivery.profile_inventory import NetBoxProfileInventoryProvider
from network_change_delivery.profile_read_only_adapter import ProfileReadOnlyAdapter
from network_change_delivery.profiled_execution import ProfiledChangeRecord
from network_change_delivery.profiled_live_host_trust import (
    DEFAULT_PROFILED_LIVE_TRUST_ROOT,
    KNOWN_HOSTS_NAME,
    validate_profiled_live_host_trust,
)
from network_change_delivery.profiled_planning import plan_profiled_change
from network_change_delivery.profiled_promotion import (
    BATFISH_METADATA,
    CHANGE_ID,
    CML_METADATA,
    DESCRIPTION,
    MAIN_KEYS,
    PROMOTION_METADATA,
    VALIDATION_KEYS,
    ProfiledBuildContext,
    authorize,
    digest_bytes,
    promote,
)
from network_change_delivery.secrets import (
    OpenBaoLoginError,
    OpenBaoSecretProvider,
    SecretError,
)

ROOT = Path(__file__).resolve().parents[2]
WRAPPER = ".buildkite/scripts/profiled_delivery.sh"
PROTECTED = {"NCDP_NETBOX_TOKEN", "NCDP_OPENBAO_ROLE_ID", "NCDP_OPENBAO_SECRET_ID"}
PLAN_PHASES = frozenset(
    {
        "commit/context",
        "protected environment",
        "LIVE trust",
        "NetBox inventory",
        "OpenBao login",
        "OpenBao credential read",
        "device read-only preflight",
        "plan publication",
    }
)


class PlanPhaseError(ValueError):
    def __init__(self, phase):
        if phase not in PLAN_PHASES:
            raise ValueError("unknown plan phase")
        self.phase = phase
        super().__init__(phase)


@contextmanager
def plan_boundary(phase):
    try:
        yield
    except Exception:
        raise PlanPhaseError(phase) from None


def plan_failure(context, phase):
    # Never interpolate provider messages, exception repr, or environment values.
    if phase not in PLAN_PHASES:
        phase = "commit/context"
    message = f"Profiled live plan FAILED — phase: {phase}. No device write."
    if context is None:
        print(message, file=sys.stderr)
    else:
        try:
            annotate(context, message, failed=True)
        except Exception:
            print("Plan failure annotation publication failed", file=sys.stderr)
    return 2


def command(args, *, cwd=ROOT, stdin=None, device_authority=False):
    environment = dict(os.environ)
    for key in ("CML2_TOKEN", "NCDP_DEVICE_USERNAME", "NCDP_DEVICE_PASSWORD"):
        environment.pop(key, None)
    if not device_authority:
        for key in PROTECTED:
            environment.pop(key, None)
    return subprocess.run(
        args,
        cwd=cwd,
        env=environment,
        input=stdin,
        capture_output=True,
        text=True,
        check=False,
    )


def checked_command(args, **kwargs):
    result = command(args, **kwargs)
    if result.returncode:
        raise ValueError("profiled delivery helper failed")
    return result.stdout.strip()


def metadata(context, key):
    return checked_command(
        ["buildkite-agent", "meta-data", "get", key, "--build", context.build_id]
    )


def publish_metadata(context, key, value):
    checked_command(
        ["buildkite-agent", "meta-data", "set", key, value, "--job", context.job_id]
    )


def annotate(context, text, *, failed=False):
    print(text)
    checked_command(
        [
            "buildkite-agent",
            "annotate",
            "--context",
            context.step,
            "--style",
            "error" if failed else "info",
        ],
        stdin=text,
    )


def private_directory(path: Path):
    info = path.lstat()
    if (
        not path.is_absolute()
        or not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) != 0o700
        or path.resolve() != path
        or path.is_relative_to(ROOT)
    ):
        raise ValueError("profiled delivery state root rejected")


def read_artifact(path):
    info = path.lstat()
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_nlink != 1
        or not 0 < info.st_size <= 1024 * 1024
    ):
        raise ValueError("profiled artifact rejected")
    return path.read_bytes()


def write_new(path, value):
    descriptor = os.open(
        path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
    )
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(value)
        stream.flush()
        os.fsync(stream.fileno())


def upload(context, directory, name):
    checked_command(
        ["buildkite-agent", "artifact", "upload", name, "--job", context.job_id],
        cwd=directory,
    )


def download(context, directory, name, step):
    path = directory / name
    if path.exists() or path.is_symlink():
        raise ValueError("artifact download collision")
    checked_command(
        [
            "buildkite-agent",
            "artifact",
            "download",
            name,
            ".",
            "--step",
            step,
            "--build",
            context.build_id,
        ],
        cwd=directory,
    )
    return read_artifact(path)


def artifact_name(context, kind):
    return f"profiled-{context.build_id}-{kind}.json"


def prerequisites(context):
    return (
        {
            key: metadata(context, "profiled-validation-" + key)
            for key in VALIDATION_KEYS
        },
        metadata(context, BATFISH_METADATA),
        metadata(context, CML_METADATA),
    )


def verify_human_dependency():
    """Trust the scheduler's unblocker identity only with the exact single block DAG."""
    pipeline = yaml.safe_load((ROOT / ".buildkite/pipeline.yml").read_text())
    steps = pipeline["steps"]
    indexed = {step["key"]: step for step in steps}
    if len(indexed) != len(steps) or [s["key"] for s in steps if "block" in s] != [
        MAIN_KEYS[2]
    ]:
        raise ValueError("human block graph rejected")
    block = indexed[MAIN_KEYS[2]]
    deploy = indexed["profiled-deploy"]
    if (
        block.get("depends_on") != "profiled-promotion"
        or "fields" in block
        or "soft_fail" in block
        or "skip" in block
        or deploy.get("depends_on") != MAIN_KEYS[2]
        or deploy.get("command") != WRAPPER
        or deploy.get("if") != 'build.branch == "main" && build.pull_request.id == null'
    ):
        raise ValueError("human authorization dependency rejected")


def plan_step(context, directory):
    with plan_boundary("commit/context"):
        intent = InterfaceDescriptionIntent.model_validate(
            yaml.safe_load((ROOT / "deployments/live/profiled-demo.yaml").read_text())
        )
    if (
        intent.change_id,
        intent.target,
        intent.interface,
        intent.desired.description,
    ) != (CHANGE_ID, "core-02", "GigabitEthernet2", DESCRIPTION):
        raise PlanPhaseError("commit/context")
    with plan_boundary("LIVE trust"):
        validate_profiled_live_host_trust()
    with plan_boundary("NetBox inventory"):
        inventory = NetBoxProfileInventoryProvider()
    with plan_boundary("protected environment"):
        secrets = OpenBaoSecretProvider()
    try:
        result = plan_profiled_change(
            intent,
            inventory,
            secrets,
            ProfileReadOnlyAdapter(
                known_hosts=DEFAULT_PROFILED_LIVE_TRUST_ROOT / KNOWN_HOSTS_NAME
            ),
        )
    except InventoryError:
        raise PlanPhaseError("NetBox inventory") from None
    except OpenBaoLoginError:
        raise PlanPhaseError("OpenBao login") from None
    except SecretError:
        raise PlanPhaseError("OpenBao credential read") from None
    except Exception:
        raise PlanPhaseError("device read-only preflight") from None
    with plan_boundary("plan publication"):
        return publish_plan(context, directory, intent, result)


def publish_plan(context, directory, intent, result):
    plan = result.plan
    facts = {
        "Change": intent.change_id,
        "Target": intent.target,
        "Device identity": "netbox:dcim.device:1",
        "Automation profile": "cat8000v_iosxe",
        "Interface": intent.interface,
        "Current description": result.state.description,
        "Desired description": intent.desired.description,
        "Transaction strategy": "cisco_targeted_inverse",
        "Plan digest": plan.digest if plan else "none — already compliant",
        "Change required": plan is not None,
    }
    if plan:
        from network_change_delivery.profiled_promotion import admit_demo_plan

        admit_demo_plan(plan)
        name = artifact_name(context, "plan")
        write_new(directory / name, plan.model_dump_json(indent=2).encode() + b"\n")
        upload(context, directory, name)
    annotate(
        context,
        "## Profiled live plan\n\n"
        + "\n".join(
            f"- {key}: {html.escape(str(value))}" for key, value in facts.items()
        ),
    )
    return 0


def promotion_step(context, directory):
    plan_bytes = download(
        context, directory, artifact_name(context, "plan"), "profiled-live-plan"
    )
    value = promote(context, plan_bytes, *prerequisites(context))
    name = artifact_name(context, "promotion")
    write_new(directory / name, value.model_dump_json(indent=2).encode() + b"\n")
    upload(context, directory, name)
    annotate(
        context,
        f"## Promotion · immutable profiled plan\n\n"
        f"Target: {value.target} / {value.device_identity}\n\n"
        f"Plan digest: `{value.plan_digest}`\n\nPromotion digest: `{value.digest}`\n\n"
        "Review this exact build/promotion before human unblock.",
    )
    publish_metadata(context, PROMOTION_METADATA, value.digest)
    return 0


def deploy_step(context, directory):
    try:
        verify_human_dependency()
        plan_bytes = download(
            context, directory, artifact_name(context, "plan"), "profiled-live-plan"
        )
        promotion_bytes = download(
            context,
            directory,
            artifact_name(context, "promotion"),
            "profiled-promotion",
        )
        plan = authorize(
            context,
            promotion_bytes,
            plan_bytes,
            *prerequisites(context),
            metadata(context, PROMOTION_METADATA),
            os.environ.get("BUILDKITE_UNBLOCKER_ID", ""),
        )
        validate_profiled_live_host_trust()
    except Exception:
        annotate(
            context,
            "NO WRITE — authorization failed. Missing or invalid same-build "
            "prerequisites, promotion, approval or LIVE trust; "
            "human unblock cannot override them.",
            failed=True,
        )
        return 2
    report = directory / artifact_name(context, "record")
    # Exactly one invocation. Never retry or turn a real failure into success.
    result = command(
        [
            "uv",
            "run",
            "--frozen",
            "ncdp",
            "profiled-deploy",
            "--plan",
            str(directory / artifact_name(context, "plan")),
            "--approve-digest",
            plan.digest,
            "--report-json",
            str(report),
            "--netbox",
            "--openbao",
            "--live",
        ],
        device_authority=True,
    )
    publication_failed = True
    if report.exists() and report.stat().st_size:
        try:
            record = ProfiledChangeRecord.model_validate_json(read_artifact(report))
            if (
                record.plan_digest != plan.digest
                or record.approval_digest != plan.digest
            ):
                raise ValueError("execution evidence binding rejected")
            upload(context, directory, report.name)
            publication_failed = False
        except Exception:
            publication_failed = True
    try:
        annotate(
            context,
            "Profiled deployment command completed. See typed execution evidence; "
            "no automatic retry. Retained private state is not removed.",
            failed=bool(result.returncode or publication_failed),
        )
    except Exception:
        publication_failed = True
    return result.returncode or (3 if publication_failed else 0)


def evidence_step(context, directory):
    try:
        raw = download(
            context, directory, artifact_name(context, "record"), "profiled-deploy"
        )
    except (ValueError, OSError):
        annotate(
            context,
            "No typed execution record produced.\n\n"
            "Device write not proven/executed by this build. Artifact unavailability "
            "is not proof of absence; inspect retained state before any new attempt.",
        )
        return 2
    record = ProfiledChangeRecord.model_validate_json(raw)
    annotate(
        context,
        "## Deployment evidence\n\n"
        f"Target: {html.escape(record.target)}\n\nPlan: `{record.plan_digest}`\n\n"
        f"Outcome: {record.final_outcome.value}\n\n"
        f"Write attempted: {record.execution.attempted}\n\n"
        f"Recovery attempted: {record.recovery.attempted}\n\n"
        f"Evidence: `{digest_bytes(raw)}` / `{artifact_name(context, 'record')}`",
    )
    return 0


def main():
    logging.disable(logging.CRITICAL)
    os.umask(0o077)
    is_plan = os.environ.get("BUILDKITE_STEP_KEY") == "profiled-live-plan"
    context = None
    phase = "commit/context"
    try:
        context = ProfiledBuildContext.from_environment(os.environ)
        checked_command(["scripts/buildkite/verify_commit.sh"])
        handlers = {
            "profiled-live-plan": plan_step,
            "profiled-promotion": promotion_step,
            "profiled-deploy": deploy_step,
            "profiled-deployment-evidence": evidence_step,
        }
        if context.step not in handlers:
            raise ValueError("unknown profiled command")
        if context.step in {"profiled-live-plan", "profiled-deploy"}:
            phase = "protected environment"
            if is_plan and any(
                not os.environ.get(key)
                for key in (
                    "NCDP_NETBOX_URL",
                    "NCDP_NETBOX_TOKEN",
                    "NCDP_OPENBAO_URL",
                    "NCDP_OPENBAO_ROLE_ID",
                    "NCDP_OPENBAO_SECRET_ID",
                )
            ):
                raise PlanPhaseError(phase)
            if (
                not os.environ.get("NCDP_BUILDKITE_PIPELINE_ID")
                or os.environ.get("BUILDKITE_PIPELINE_ID")
                != os.environ["NCDP_BUILDKITE_PIPELINE_ID"]
            ):
                raise ValueError("deployment pipeline binding rejected")
            root = Path(os.environ["NCDP_PROFILED_DELIVERY_STATE_ROOT"])
            private_directory(root)
            build = root / context.build_id
            build.mkdir(mode=0o700, exist_ok=True)
            private_directory(build)
            directory = build / context.step
            directory.mkdir(mode=0o700)  # create-only; retained even on ambiguity
            return handlers[context.step](context, directory)
        with tempfile.TemporaryDirectory(prefix="ncdp-profiled-delivery-") as temporary:
            return handlers[context.step](context, Path(temporary))
    except Exception as error:
        if is_plan:
            return plan_failure(
                context, error.phase if isinstance(error, PlanPhaseError) else phase
            )
        print(
            "Profiled delivery prerequisite/operation failed; no automatic retry. "
            "Only typed execution evidence can establish a write outcome.",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
