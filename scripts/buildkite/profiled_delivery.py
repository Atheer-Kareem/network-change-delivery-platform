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
from contextlib import ExitStack, contextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import yaml

from network_change_delivery.audit import AuditArtifactKind as Kind
from network_change_delivery.audit import BuildkiteCorrelation
from network_change_delivery.audit_store import AuditStore
from network_change_delivery.inventory import InventoryError
from network_change_delivery.models import FinalOutcome
from network_change_delivery.openbao_profiled_deploy_config import (
    ProtectedRolloutCredentialAuthority,
)
from network_change_delivery.profile_inventory import NetBoxProfileInventoryProvider
from network_change_delivery.profile_read_only_adapter import ProfileReadOnlyAdapter
from network_change_delivery.profiled_audit import (
    DURABLE_PUBLICATION_METADATA,
    ProfiledDeliveryKind,
    ProfiledDurablePublicationReceipt,
    build_profiled_compliance_audit_record,
    build_profiled_execution_audit_record,
)
from network_change_delivery.profiled_configuration_observation import (
    CHRONOLOGY_METADATA,
    SUCCESS,
    Overall,
    ProfiledChronologyPublicationReceipt,
    _signed,
    build_profiled_observation_record,
    capture_profiled_attempt,
    load_attempt_file,
    persist_attempt_file,
    validate_pre,
)
from network_change_delivery.profiled_configuration_observation_store import (
    ProfiledConfigurationObservationStore,
)
from network_change_delivery.profiled_execution import (
    ProfiledChangeRecord,
    verify_profiled_record_plan,
)
from network_change_delivery.profiled_intent import (
    admit_intent_result,
    load_committed_intent,
)
from network_change_delivery.profiled_live_host_trust import (
    DEFAULT_PROFILED_LIVE_TRUST_ROOT,
    KNOWN_HOSTS_NAME,
    validate_profiled_live_host_trust,
)
from network_change_delivery.profiled_planning import (
    ProfiledComplianceRecord,
    ProfiledDeploymentPlan,
    plan_profiled_change,
)
from network_change_delivery.profiled_promotion import (
    BATFISH_METADATA,
    CML_METADATA,
    MAIN_KEYS,
    PLANNING_METADATA,
    PROMOTION_METADATA,
    VALIDATION_KEYS,
    ProfiledBuildContext,
    ProfiledPlanningPublication,
    ProfiledPromotion,
    authorize,
    checked_digest,
    digest_bytes,
    promote,
    verify_validation,
)
from network_change_delivery.profiled_rollout import (
    plan_profiled_rollout,
    read_profiled_rollout,
)
from network_change_delivery.profiled_rollout_audit import (
    ROLLOUT_DURABLE_METADATA,
    ProfiledRolloutDurablePublicationReceipt,
)
from network_change_delivery.profiled_rollout_audit_store import (
    ProfiledRolloutAuditStore,
)
from network_change_delivery.profiled_rollout_authorization import authorize_rollout
from network_change_delivery.profiled_rollout_execution import execute_rollout
from network_change_delivery.profiled_rollout_intent import (
    load_committed_rollout_intent,
)
from network_change_delivery.profiled_rollout_promotion import (
    PLAN_TYPES,
    ROLLOUT_PLANNING_METADATA,
    ROLLOUT_PROMOTION_BYTES_METADATA,
    ROLLOUT_PROMOTION_METADATA,
    RolloutPlanningPublication,
    admit_rollout_result,
    promote_rollout,
)
from network_change_delivery.profiled_rollout_reservation import reserve_rollout_devices
from network_change_delivery.profiled_write_adapter import ProfiledWriteAdapter
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
        "assurance prerequisites",
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
    environment.pop("NCDP_AUDIT_STORE_ROOT", None)
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
    """Admit exactly two fieldless authority graphs, without arbitrary nesting."""
    pipeline = yaml.safe_load((ROOT / ".buildkite/pipeline.yml").read_text())
    top = pipeline["steps"]
    expected = {
        "runtime-delivery": list(MAIN_KEYS),
        "rollout-runtime-delivery": [
            "profiled-rollout-human-authorization",
            "profiled-rollout-deploy",
        ],
    }
    groups = [s for s in top if "steps" in s]
    if len(groups) != 2 or {g.get("key") for g in groups} != set(expected):
        raise ValueError("human block group rejected")
    steps = [s for s in top if "steps" not in s]
    for group in groups:
        if (
            "group" not in group
            or "skip" in group
            or "if" in group
            or [s.get("key") for s in group["steps"]] != expected[group["key"]]
            or any("steps" in s for s in group["steps"])
        ):
            raise ValueError("human block group rejected")
        steps.extend(group["steps"])
    indexed = {s["key"]: s for s in steps}
    keys = [s["key"] for s in top] + [s["key"] for g in groups for s in g["steps"]]
    if len(keys) != len(set(keys)) or {s["key"] for s in steps if "block" in s} != {
        "profiled-human-authorization",
        "profiled-rollout-human-authorization",
    }:
        raise ValueError("human block graph rejected")
    for prefix in ("profiled", "profiled-rollout"):
        block, deploy = (
            indexed[prefix + "-human-authorization"],
            indexed[prefix + "-deploy"],
        )
        condition = 'build.branch == "main" && build.pull_request.id == null'
        if (
            block.get("depends_on") != prefix + "-promotion"
            or any(k in block for k in ("fields", "soft_fail", "skip"))
            or block.get("if") != condition
            or deploy.get("depends_on") != prefix + "-human-authorization"
            or deploy.get("command") != WRAPPER
            or deploy.get("if") != condition
            or "skip" in deploy
            or deploy.get("agents") != {"queue": "ncdp-deploy"}
            or deploy.get("concurrency") != 1
            or deploy.get("concurrency_group") != "ncdp/profiled-live-delivery"
            or deploy.get("retry", {}).get("automatic") is not False
            or deploy.get("retry", {}).get("manual", {}).get("allowed") is not False
            or (prefix == "profiled-rollout" and "soft_fail" in deploy)
        ):
            raise ValueError("human authorization dependency rejected")


def plan_step(context, directory):
    with plan_boundary("commit/context"):
        intent = load_committed_intent(ROOT)
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
    value = plan if plan is not None else result.compliance
    if value is None or (plan is not None and result.compliance is not None):
        raise ValueError("planning must produce exactly one typed result")
    # Revalidate before publication, even if a caller supplied an unvalidated copy.
    model = ProfiledDeploymentPlan if plan is not None else ProfiledComplianceRecord
    value = model.model_validate(value.model_dump())
    admit_intent_result(intent, value)
    facts = {
        "Change": value.change_id,
        "Target": value.target,
        "Device identity": value.device_identity,
        "Automation profile": value.automation_profile_id.value,
        "Interface": value.interface.name,
        "Interface identity": value.interface.interface,
        "Current description": value.current_description
        if plan
        else value.observed_description,
        "Desired description": value.desired_description,
        "Operation": value.kind if plan else value.operation.value,
        "Plan digest": value.digest if plan else "none — already compliant",
        "Change required": plan is not None,
    }
    if plan is not None:
        facts["Transaction strategy"] = value.operation_admission.transaction_strategy
    kind = "plan" if plan is not None else "compliance"
    name = artifact_name(context, kind)
    raw = value.model_dump_json(indent=2).encode() + b"\n"
    write_new(directory / name, raw)
    upload(context, directory, name)
    annotate(
        context,
        "## Profiled live plan\n\n"
        + "\n".join(
            f"- {key}: {html.escape(str(value))}" for key, value in facts.items()
        ),
    )
    publish_metadata(
        context,
        PLANNING_METADATA,
        ProfiledPlanningPublication(
            build_id=context.build_id,
            commit=context.commit,
            artifact_kind=kind,
            artifact_digest=digest_bytes(raw),
            result_digest=value.digest,
        ).model_dump_json(),
    )
    return 0


def planning_result(context, directory):
    """Require successful publication bound to the independently read Git intent."""
    intent = load_committed_intent(ROOT)
    receipt = ProfiledPlanningPublication.model_validate_json(
        metadata(context, PLANNING_METADATA)
    )
    receipt.verify_context(context)
    raw = download(
        context,
        directory,
        artifact_name(context, receipt.artifact_kind),
        "profiled-live-plan",
    )
    model = (
        ProfiledDeploymentPlan
        if receipt.artifact_kind == "plan"
        else ProfiledComplianceRecord
    )
    value = model.model_validate_json(raw)
    if (
        digest_bytes(raw) != receipt.artifact_digest
        or value.digest != receipt.result_digest
    ):
        raise ValueError("planning publication digest rejected")
    admit_intent_result(intent, value)
    return value, raw


def compliant_annotation(context, value, *, durable="", failed=False):
    annotate(
        context,
        "## Profiled delivery — COMPLIANT\n\n"
        f"Target: {html.escape(value.target)} / {value.device_identity}\n\n"
        "Outcome: COMPLIANT\n\nWrite attempted: False\n\n"
        "Recovery attempted: False\n\nPromotion minted: False\n\n"
        "Configuration chronology: NOT REQUIRED — COMPLIANT\n\n"
        "No deployment plan or execution record exists for this result. "
        "The static human block may remain visible; "
        "unblock grants zero write authority.\n\n"
        "Compliance was established by the planning observation at "
        f"{html.escape(value.observed_at.isoformat())}; downstream continuation does "
        "not perform a fresh device-state check because no write is authorized.\n\n"
        f"Compliance evidence: `{value.digest}`" + durable,
        failed=failed,
    )
    return 3 if failed else 0


def promotion_step(context, directory):
    value, plan_bytes = planning_result(context, directory)
    if isinstance(value, ProfiledComplianceRecord):
        return compliant_annotation(context, value)
    value = promote(
        context, plan_bytes, *prerequisites(context), intent=load_committed_intent(ROOT)
    )
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


def durable_context(context):
    # Validate all required correlation before any device command, without APIs.
    if context.step != "profiled-deploy":
        raise ValueError("durable publication owner rejected")
    pipeline = os.environ["BUILDKITE_PIPELINE_ID"]
    if pipeline != os.environ["NCDP_BUILDKITE_PIPELINE_ID"]:
        raise ValueError("durable pipeline binding rejected")
    correlation = BuildkiteCorrelation(
        pipeline_id=pipeline,
        build_id=context.build_id,
        build_number=os.environ["BUILDKITE_BUILD_NUMBER"],
        job_id=context.job_id,
        step_key=context.step,
    )
    return {
        "context": context,
        "pipeline_id": str(correlation.pipeline_id),
        "build_number": correlation.build_number,
    }


def durable_destination(context, kinds):
    correlation = durable_context(context)
    root = Path(os.environ["NCDP_AUDIT_STORE_ROOT"])
    private_directory(root)
    store = AuditStore(root, checkout=ROOT)
    store.prepare_profiled_publication(UUID(context.job_id), frozenset(kinds))
    return store, correlation


def persist_input(store, kind, value):
    reference = store.persist_artifact(kind, value)
    if store.read_artifact(reference) != value:
        raise ValueError("durable input readback rejected")
    return reference


def publish_durable(context, directory, store, envelope, raw):
    store.persist_profiled_record(envelope, artifact_bytes=raw)
    if store.read_profiled_record(envelope.record_id) != envelope:
        raise ValueError("durable envelope readback rejected")
    receipt = ProfiledDurablePublicationReceipt.from_record(envelope)
    name = artifact_name(context, "durable-publication")
    content = receipt.model_dump_json(indent=2).encode() + b"\n"
    write_new(directory / name, content)
    # Step-scoped artifact plus same-build exact byte hash. Neither is store authority.
    upload(context, directory, name)
    publish_metadata(context, DURABLE_PUBLICATION_METADATA, digest_bytes(content))
    return receipt


def durable_text(receipt):
    return (
        f"\n\nDurable evidence: {receipt.record_id}\n\n"
        f"Durable digest: `{receipt.record_digest}`"
    )


def safe_annotation(context, message, *, failed=True):
    try:
        annotate(context, message, failed=failed)
        return True
    except Exception:
        print(
            "Evidence annotation unavailable; retained state requires review.",
            file=sys.stderr,
        )
        return False


def deploy_compliance(context, directory, value, raw):
    try:
        store, correlation = durable_destination(
            context, {Kind.PROFILED_COMPLIANCE_RECORD}
        )
        reference = persist_input(store, Kind.PROFILED_COMPLIANCE_RECORD, value)
        original = {Kind.PROFILED_COMPLIANCE_RECORD: raw}
        envelope = build_profiled_compliance_audit_record(
            compliance=value,
            references=(reference,),
            artifact_bytes=original,
            generated_at=datetime.now(UTC),
            **correlation,
        )
        receipt = publish_durable(context, directory, store, envelope, original)
    except Exception:
        try:
            compliant_annotation(
                context,
                value,
                durable=(
                    "\n\nDurable publication: NOT ESTABLISHED. "
                    "Planning outcome remains COMPLIANT; no device command occurred."
                ),
                failed=True,
            )
        except Exception:
            print(
                "COMPLIANT planning; durable publication NOT ESTABLISHED; no write.",
                file=sys.stderr,
            )
        return 3
    try:
        return compliant_annotation(context, value, durable=durable_text(receipt))
    except Exception:
        return 3


def deploy_step(context, directory):
    with ExitStack() as reservations:
        return _single_deploy(context, directory, reservations)


def _single_deploy(context, directory, reservations):
    try:
        verify_human_dependency()
        value, plan_bytes = planning_result(context, directory)
        if isinstance(value, ProfiledComplianceRecord):
            return deploy_compliance(context, directory, value, plan_bytes)
        promotion_bytes = download(
            context,
            directory,
            artifact_name(context, "promotion"),
            "profiled-promotion",
        )
        unblocker = os.environ.get("BUILDKITE_UNBLOCKER_ID", "")
        plan = authorize(
            context,
            promotion_bytes,
            plan_bytes,
            *prerequisites(context),
            metadata(context, PROMOTION_METADATA),
            unblocker,
            intent=load_committed_intent(ROOT),
        )
        reservations.enter_context(
            reserve_rollout_devices(
                Path(os.environ["NCDP_PROFILED_DELIVERY_STATE_ROOT"]),
                (plan.device_identity,),
            )
        )
        validate_profiled_live_host_trust()
        promotion = ProfiledPromotion.model_validate_json(promotion_bytes)
        store, correlation = durable_destination(
            context,
            {
                Kind.PROFILED_DEPLOYMENT_PLAN,
                Kind.PROFILED_PROMOTION,
                Kind.PROFILED_CHANGE_RECORD,
            },
        )
        inputs = (
            persist_input(store, Kind.PROFILED_DEPLOYMENT_PLAN, plan),
            persist_input(store, Kind.PROFILED_PROMOTION, promotion),
        )
        chronology_store = ProfiledConfigurationObservationStore(
            store.root, checkout=ROOT
        )
        chronology_store.prepare_profiled_observation_publication(UUID(context.job_id))
        pre_path, post_path = (
            directory / "configuration-pre.json",
            directory / "configuration-post.json",
        )
        pre = capture_profiled_attempt(plan)
        persist_attempt_file(pre_path, pre)
        pre = validate_pre(plan, load_attempt_file(pre_path))
    except Exception:
        safe_annotation(
            context,
            "NO WRITE — deployment prerequisite admission failed. "
            "Missing or invalid same-build prerequisites, promotion, approval, "
            "LIVE trust "
            "or durable inputs / independent PRE chronology; "
            "human unblock cannot override them.",
        )
        return 2
    report = directory / artifact_name(context, "record")
    # Exactly one invocation. Never retry, even if execution or evidence is uncertain.
    try:
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
        returncode = result.returncode
    except Exception:
        # The child may have started. Inspect any report and never replay it.
        returncode = 3
    # First work after the uncertain command boundary: one independent POST attempt.
    chronology_failed = False
    try:
        post = capture_profiled_attempt(plan, expected_before=pre.after_revision)
        persist_attempt_file(post_path, post)
        post = load_attempt_file(post_path)
        chronology_failed = post.status not in SUCCESS
    except Exception:
        chronology_failed = True
    publication_failed = False
    receipt = None
    try:
        raw = read_artifact(report)
        record = ProfiledChangeRecord.model_validate_json(raw)
        verify_profiled_record_plan(record, plan)
    except Exception:
        publication_failed = True
    else:
        # Independent channels: upload failure must not prevent durable evidence.
        try:
            upload(context, directory, report.name)
        except Exception:
            publication_failed = True
        try:
            execution_ref = persist_input(store, Kind.PROFILED_CHANGE_RECORD, record)
            original = {
                Kind.PROFILED_DEPLOYMENT_PLAN: plan_bytes,
                Kind.PROFILED_PROMOTION: promotion_bytes,
                Kind.PROFILED_CHANGE_RECORD: raw,
            }
            envelope = build_profiled_execution_audit_record(
                plan=plan,
                promotion=promotion,
                execution=record,
                references=(*inputs, execution_ref),
                artifact_bytes=original,
                unblocker_id=unblocker,
                generated_at=datetime.now(UTC),
                **correlation,
            )
            receipt = publish_durable(context, directory, store, envelope, original)
        except Exception:
            publication_failed = True
    chronology = None
    if receipt is not None:
        try:
            parent = store.read_profiled_record(receipt.record_id)
            child = build_profiled_observation_record(
                parent,
                load_attempt_file(pre_path),
                load_attempt_file(post_path),
                generated_at=datetime.now(UTC),
            )
            chronology_store.persist_profiled_observation_record(child)
            if (
                chronology_store.read_profiled_observation_record(
                    child.observation_record_id
                )
                != child
            ):
                raise ValueError("chronology readback rejected")
            chronology = ProfiledChronologyPublicationReceipt.from_record(parent, child)
            name = artifact_name(context, "chronology")
            content = chronology.model_dump_json(indent=2).encode() + b"\n"
            write_new(directory / name, content)
            upload(context, directory, name)
            publish_metadata(context, CHRONOLOGY_METADATA, digest_bytes(content))
        except Exception:
            chronology_failed = True
            chronology = None
    else:
        chronology_failed = True
    publication_failed = publication_failed or chronology_failed
    message = (
        "Profiled deployment command completed. No automatic retry; retained private "
        "state and immutable partial artifacts are not removed. "
        "Artifact absence is not proof that no write occurred. "
        "Independently reconcile if needed."
    )
    message += (
        durable_text(receipt)
        if receipt
        else "\n\nDurable publication: NOT ESTABLISHED."
    )
    message += chronology_text(chronology)
    if not safe_annotation(
        context, message, failed=bool(returncode or publication_failed)
    ):
        publication_failed = True
    return returncode or (3 if publication_failed else 0)


def publication_receipt(context, directory, kind, outcome):
    raw = download(
        context,
        directory,
        artifact_name(context, "durable-publication"),
        "profiled-deploy",
    )
    if digest_bytes(raw) != metadata(context, DURABLE_PUBLICATION_METADATA):
        raise ValueError("durable receipt byte binding rejected")
    receipt = ProfiledDurablePublicationReceipt.model_validate_json(raw)
    if (
        str(receipt.build_id) != context.build_id
        or receipt.commit != context.commit
        or receipt.delivery_kind is not kind
        or receipt.final_outcome is not outcome
    ):
        raise ValueError("durable receipt result binding rejected")
    # The exact same-build artifact is fetched only from profiled-deploy. Its
    # trusted publisher supplies the opaque deploy job/record identity, not this job.
    return receipt


def chronology_text(receipt):
    if receipt is None:
        return "\n\nConfiguration chronology: NOT ESTABLISHED"
    return (
        f"\n\nConfiguration chronology: {receipt.overall_status.value}"
        f"\n\nPRE: {receipt.pre_status.value}\n\nPOST: {receipt.post_status.value}"
        f"\n\nRelationship: {receipt.relationship.value}"
        f"\n\nCausality: {receipt.causality}"
        f"\n\nChronology record: {receipt.chronology_record_id}"
        f"\n\nChronology digest: {receipt.chronology_digest}"
    )


def chronology_receipt(context, directory, parent, plan):
    raw = download(
        context, directory, artifact_name(context, "chronology"), "profiled-deploy"
    )
    if digest_bytes(raw) != metadata(context, CHRONOLOGY_METADATA):
        raise ValueError("chronology receipt byte binding rejected")
    receipt = ProfiledChronologyPublicationReceipt.model_validate_json(raw)
    receipt.verify_delivery(context, parent, plan.device_identity)
    return receipt


def evidence_step(context, directory):
    try:
        plan, _plan_bytes = planning_result(context, directory)
        if isinstance(plan, ProfiledComplianceRecord):
            record = None
            kind, outcome = ProfiledDeliveryKind.COMPLIANCE, plan.outcome
        else:
            raw = download(
                context, directory, artifact_name(context, "record"), "profiled-deploy"
            )
            record = ProfiledChangeRecord.model_validate_json(raw)
            verify_profiled_record_plan(record, plan)
            kind, outcome = ProfiledDeliveryKind.EXECUTION, record.final_outcome
    except (ValueError, OSError):
        safe_annotation(
            context,
            "No typed execution record produced or verified, "
            "and no valid compliant result.\n\n"
            "Artifact unavailability is not proof of absence; "
            "inspect retained state before any new attempt.",
        )
        return 2
    receipt = None
    try:
        receipt = publication_receipt(context, directory, kind, FinalOutcome(outcome))
        durable, failed = durable_text(receipt), False
    except Exception:
        durable, failed = (
            (
                "\n\nDurable publication: NOT ESTABLISHED. Receipt absence "
                "does not prove store emptiness or absence of a write."
            ),
            True,
        )
    if record is None:
        try:
            return compliant_annotation(context, plan, durable=durable, failed=failed)
        except Exception:
            return 3
    chronology = None
    try:
        if receipt is None:
            raise ValueError("parent publication unavailable")
        chronology = chronology_receipt(context, directory, receipt, plan)
        failed = failed or chronology.overall_status is not Overall.SUCCEEDED
    except Exception:
        failed = True
    if not safe_annotation(
        context,
        "## Deployment evidence\n\n"
        f"Target: {html.escape(record.target)}\n\nPlan: `{record.plan_digest}`\n\n"
        f"Outcome: {record.final_outcome.value}\n\n"
        f"Write attempted: {record.execution.attempted}\n\n"
        f"Recovery attempted: {record.recovery.attempted}\n\n"
        f"Evidence: `{digest_bytes(raw)}` / `{artifact_name(context, 'record')}`"
        + durable
        + chronology_text(chronology),
        failed=failed,
    ):
        return 3
    return 3 if failed else 0


def rollout_summary(value):
    lines = [
        f"Rollout: {value.intent.change_id}",
        f"Selection count: {len(value.children)}",
    ]
    for child in value.children:
        result = child.result()
        current = (
            result.current_description
            if child.kind == "DEPLOYABLE"
            else result.observed_description
        )
        lines.append(
            f"{result.target} / {result.device_identity} / {result.interface.name} "
            f"({result.interface.interface}): {child.kind}; {current} → "
            f"{result.desired_description}; child digest {result.digest}"
        )
    lines.extend(
        [
            f"Canaries: {getattr(value, 'canaries', ())}",
            f"Waves: {getattr(value, 'waves', ())}",
            f"Parent digest: {value.digest}",
            "Planning/promotion only: no rollout authorization or execution exists.",
        ]
    )
    return "\n".join(f"- {html.escape(line)}" for line in lines)


def rollout_plan_step(context, directory):
    if context.step != "profiled-rollout-live-plan":
        raise ValueError("rollout planning step rejected")
    with plan_boundary("commit/context"):
        intent = load_committed_rollout_intent(ROOT)
    # CML's soft-fail UI must not permit new protected collection without receipts.
    with plan_boundary("assurance prerequisites"):
        receipts, batfish, cml = prerequisites(context)
        verify_validation(context, receipts)
        checked_digest(batfish)
        checked_digest(cml)
    with plan_boundary("LIVE trust"):
        validate_profiled_live_host_trust()
    with plan_boundary("device read-only preflight"):
        value = plan_profiled_rollout(
            intent,
            NetBoxProfileInventoryProvider(),
            ProtectedRolloutCredentialAuthority(),
            OpenBaoSecretProvider(),
            ProfileReadOnlyAdapter(
                known_hosts=DEFAULT_PROFILED_LIVE_TRUST_ROOT / KNOWN_HOSTS_NAME
            ),
            source_commit=context.commit,
        )
    with plan_boundary("plan publication"):
        # Strict dispatch revalidates all original embedded child bytes and digests.
        raw = value.model_dump_json(indent=2).encode() + b"\n"
        value = read_profiled_rollout(raw)
        admit_rollout_result(intent, value, context.commit)
        kind = "plan" if isinstance(value, PLAN_TYPES) else "compliance"
        receipt = RolloutPlanningPublication(
            build_id=context.build_id,
            commit=context.commit,
            artifact_kind=kind,
            parent_schema_version=value.schema_version,
            artifact_digest=digest_bytes(raw),
            result_digest=value.digest,
        )
        name = artifact_name(context, "rollout-" + kind)
        write_new(directory / name, raw)
        upload(context, directory, name)
        annotate(context, "## Rollout planning\n\n" + rollout_summary(value))
        publish_metadata(context, ROLLOUT_PLANNING_METADATA, receipt.model_dump_json())
    return 0


def rollout_promotion_step(context, directory):
    if context.step != "profiled-rollout-promotion":
        raise ValueError("rollout promotion step rejected")
    intent = load_committed_rollout_intent(ROOT)
    receipt = RolloutPlanningPublication.model_validate_json(
        metadata(context, ROLLOUT_PLANNING_METADATA)
    )
    if receipt.build_id != context.build_id or receipt.commit != context.commit:
        raise ValueError("rollout publication context rejected")
    raw = download(
        context,
        directory,
        artifact_name(context, "rollout-" + receipt.artifact_kind),
        "profiled-rollout-live-plan",
    )
    parent = receipt.read(context, raw, intent)
    if not isinstance(parent, PLAN_TYPES):
        annotate(
            context, "## Rollout COMPLIANT · no promotion\n\n" + rollout_summary(parent)
        )
        return 0
    value = promote_rollout(
        context, raw, receipt, *prerequisites(context), intent=intent
    )
    name = artifact_name(context, "rollout-promotion")
    promotion_raw = value.model_dump_json(indent=2).encode() + b"\n"
    write_new(directory / name, promotion_raw)
    upload(context, directory, name)
    annotate(
        context,
        "## Rollout promotion · no execution authority\n\n"
        + rollout_summary(parent)
        + f"\n\nPromotion digest: `{value.digest}`",
    )
    publish_metadata(
        context, ROLLOUT_PROMOTION_BYTES_METADATA, digest_bytes(promotion_raw)
    )
    publish_metadata(context, ROLLOUT_PROMOTION_METADATA, value.digest)
    return 0


def rollout_deploy_step(context, directory):
    record = None
    try:
        if context.step != "profiled-rollout-deploy":
            raise ValueError("rollout deploy context rejected")
        verify_human_dependency()
        intent = load_committed_rollout_intent(ROOT)
        publication = RolloutPlanningPublication.model_validate_json(
            metadata(context, ROLLOUT_PLANNING_METADATA)
        )
        raw = download(
            context,
            directory,
            artifact_name(context, "rollout-" + publication.artifact_kind),
            "profiled-rollout-live-plan",
        )
        parent = publication.read(context, raw, intent)
        if not isinstance(parent, PLAN_TYPES):
            annotate(
                context,
                "## Rollout COMPLIANT · zero write authority\n\n"
                + rollout_summary(parent),
            )
            return 0
        promotion_raw = download(
            context,
            directory,
            artifact_name(context, "rollout-promotion"),
            "profiled-rollout-promotion",
        )
        receipts, batfish, cml = prerequisites(context)
        inputs = {
            "context": context,
            "parent_bytes": raw,
            "publication": publication,
            "promotion_bytes": promotion_raw,
            "receipts": receipts,
            "batfish": batfish,
            "cml": cml,
            "promotion_digest": metadata(context, ROLLOUT_PROMOTION_METADATA),
            "promotion_artifact_digest": metadata(
                context, ROLLOUT_PROMOTION_BYTES_METADATA
            ),
            "unblocker_id": os.environ.get("BUILDKITE_UNBLOCKER_ID", ""),
            "intent": intent,
        }
        # Authenticate frozen facts before trust or constructing providers.
        authorize_rollout(**inputs)
        pipeline_id = os.environ["BUILDKITE_PIPELINE_ID"]
        if pipeline_id != os.environ["NCDP_BUILDKITE_PIPELINE_ID"]:
            raise ValueError("rollout pipeline binding rejected")
        UUID(pipeline_id)
        build_number = int(os.environ["BUILDKITE_BUILD_NUMBER"])
        if build_number <= 0:
            raise ValueError("rollout build number rejected")
        store = ProfiledRolloutAuditStore(
            Path(os.environ["NCDP_AUDIT_STORE_ROOT"]), checkout=ROOT
        )
        validate_profiled_live_host_trust()
        trust = DEFAULT_PROFILED_LIVE_TRUST_ROOT / KNOWN_HOSTS_NAME
        record = execute_rollout(
            **inputs,
            store=store,
            state_root=Path(os.environ["NCDP_PROFILED_DELIVERY_STATE_ROOT"]),
            directory=directory,
            pipeline_id=pipeline_id,
            build_number=build_number,
            inventory=NetBoxProfileInventoryProvider(),
            credential_authority=ProtectedRolloutCredentialAuthority(),
            secrets=OpenBaoSecretProvider(),
            collector=ProfileReadOnlyAdapter(known_hosts=trust),
            writer_factory=lambda: ProfiledWriteAdapter(known_hosts=trust),
        )
        receipt = _signed(
            ProfiledRolloutDurablePublicationReceipt,
            {
                "record_id": record.record_id,
                "record_digest": record.digest,
                "build_id": record.build_id,
                "source_commit": record.source_commit,
                "outcome": record.outcome,
            },
        )
        name = artifact_name(context, "rollout-durable-publication")
        content = receipt.model_dump_json(indent=2).encode() + b"\n"
        write_new(directory / name, content)
        upload(context, directory, name)
        publish_metadata(context, ROLLOUT_DURABLE_METADATA, receipt.model_dump_json())
        rows = [
            "## Rollout execution",
            f"Outcome: **{record.outcome}**",
            f"Authorization: `{record.authorization_digest}`",
            f"Preflight: `{record.preflight_digest}`",
            rollout_summary(parent),
            "Reserved population: "
            f"`{tuple(c.device_identity for c in record.children)}`",
            f"Attempted: `{record.attempted}`; successful: `{record.successful}`; "
            f"compliant: `{record.compliant}`",
            f"Stopping member/outcome: `{record.stopping_member}` / "
            f"`{record.stopping_outcome or record.stopping_reason}`",
            f"Untouched: `{record.untouched}`; "
            f"final validation: `{record.final_validation_status}`",
            f"Durable parent: `{record.record_id}` / `{record.digest}`",
            "Chronology causality: NOT_PROVEN. No command replay performed.",
        ]
        from network_change_delivery.profiled_rollout_audit import (
            ProfiledRolloutChildAuditRecord,
        )

        for ref in record.child_records:
            child = store.read_rollout_record(
                ProfiledRolloutChildAuditRecord, ref.record_id
            )
            rows.append(
                f"`{child.child.device_identity}`: `{child.final_outcome}`; "
                f"execution `{child.execution_digest}`; "
                f"PRE/POST `{child.pre_status}` / `{child.post_status}`"
            )
        annotate(context, "\n\n".join(rows), failed=record.outcome != "SUCCEEDED")
        return 0 if record.outcome == "SUCCEEDED" else 3
    except Exception:
        safe_annotation(
            context,
            "Rollout admission/execution/publication failed. "
            "DEVICE OUTCOME MAY BE KNOWN/UNKNOWN FROM CHILD EVIDENCE; "
            + (
                "DURABLE ROLLOUT PARENT NOT ESTABLISHED. "
                if record is None
                else (
                    f"Durable parent readback established: {record.record_id} / "
                    f"{record.digest}; subsequent publication failed. "
                )
            )
            + "Inspect retained private evidence; "
            "NO COMMAND REPLAY PERFORMED. No automatic resume.",
        )
        return 3


def main():
    logging.disable(logging.CRITICAL)
    os.umask(0o077)
    is_plan = os.environ.get("BUILDKITE_STEP_KEY") in {
        "profiled-live-plan",
        "profiled-rollout-live-plan",
    }
    context = None
    phase = "commit/context"
    try:
        context = ProfiledBuildContext.from_environment(os.environ)
        checked_command(["scripts/buildkite/verify_commit.sh"])
        handlers = {
            "profiled-live-plan": plan_step,
            "profiled-rollout-live-plan": rollout_plan_step,
            "profiled-rollout-promotion": rollout_promotion_step,
            "profiled-rollout-deploy": rollout_deploy_step,
            "profiled-promotion": promotion_step,
            "profiled-deploy": deploy_step,
            "profiled-deployment-evidence": evidence_step,
        }
        if context.step not in handlers:
            raise ValueError("unknown profiled command")
        if context.step in {
            "profiled-live-plan",
            "profiled-rollout-live-plan",
            "profiled-deploy",
            "profiled-rollout-deploy",
        }:
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
            "Only valid typed planning or execution evidence can establish an outcome.",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
