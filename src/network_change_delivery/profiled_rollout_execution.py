"""Sequential frozen rollout coordination over the existing child transaction.

No retry, resume, cross-device recovery or cohort recomputation exists here.
The protected caller must establish the fieldless scheduler provenance first.
"""

import os
from datetime import UTC, datetime
from uuid import UUID

from network_change_delivery.audit import AuditArtifactKind as Kind
from network_change_delivery.audit import canonical_json_bytes, sha256_identity
from network_change_delivery.models import FinalOutcome
from network_change_delivery.profiled_configuration_observation import (
    SUCCESS,
    _signed,
    capture_profiled_attempt,
    overall_status,
    persist_attempt_file,
    validate_pre,
)
from network_change_delivery.profiled_execution import (
    execute_profiled_plan,
    verify_profiled_record_plan,
)
from network_change_delivery.profiled_planning import ProfiledDeploymentPlan
from network_change_delivery.profiled_rollout import read_profiled_rollout
from network_change_delivery.profiled_rollout_audit import (
    ProfiledRolloutAuditRecord,
    ProfiledRolloutChildAuditRecord,
    ProfiledRolloutChronologyRecord,
    RecordReference,
    RolloutChildBinding,
    RolloutOutcome,
    child_record_id,
    chronology_record_id,
)
from network_change_delivery.profiled_rollout_authorization import authorize_rollout
from network_change_delivery.profiled_rollout_final_validation import (
    validate_rollout_final_state,
)
from network_change_delivery.profiled_rollout_preflight import (
    preflight_profiled_rollout,
)
from network_change_delivery.profiled_rollout_reservation import reserve_rollout_devices


def binding(child):
    return RolloutChildBinding(
        device_identity=child.device.device_identity,
        interface_identity=child.interface.interface,
        kind=child.kind,
        artifact_digest=child.artifact_digest,
        result_digest=child.result_digest,
    )


def execute_rollout(
    *,
    context,
    parent_bytes,
    publication,
    promotion_bytes,
    receipts,
    batfish,
    cml,
    promotion_digest,
    promotion_artifact_digest,
    unblocker_id,
    intent,
    store,
    state_root,
    directory,
    pipeline_id,
    build_number,
    inventory,
    credential_authority,
    secrets,
    collector,
    writer_factory,
):
    """Reconstruct authorization; persist readiness; reserve; preflight; execute.

    Providers must be read-only until the one existing child executor is entered.
    The factory creates no writer until the complete population preflight passes.
    Exceptions from publication propagate to a nonzero protected caller. Private
    attempt files and immutable store fragments remain; no command is replayed.
    """
    auth = authorize_rollout(
        context,
        parent_bytes,
        publication,
        promotion_bytes,
        receipts,
        batfish,
        cml,
        promotion_digest,
        promotion_artifact_digest,
        unblocker_id,
        intent=intent,
    )
    parent = read_profiled_rollout(parent_bytes)
    record_id = UUID(context.job_id)
    store.prepare_rollout(record_id, parent)
    store.put_bytes("parent", parent_bytes)
    store.put_bytes("promotion", promotion_bytes)
    store.put_model("authorization", auth)
    # Every approved child is retained, including compliant/untouched children.
    for child in parent.children:
        store.put_bytes("child", child.artifact_bytes())
        kind = (
            Kind.PROFILED_DEPLOYMENT_PLAN
            if child.kind == "DEPLOYABLE"
            else Kind.PROFILED_COMPLIANCE_RECORD
        )
        reference = store.persist_artifact(kind, child.result())
        if store.read_artifact(reference) != child.result():
            raise ValueError("rollout approved child canonical readback failed")
    with reserve_rollout_devices(state_root, auth.selected_devices):
        return _reserved(
            context=context,
            parent=parent,
            parent_bytes=parent_bytes,
            publication=publication,
            promotion_bytes=promotion_bytes,
            auth=auth,
            receipts=receipts,
            batfish=batfish,
            cml=cml,
            intent=intent,
            store=store,
            directory=directory,
            pipeline_id=pipeline_id,
            build_number=build_number,
            inventory=inventory,
            credential_authority=credential_authority,
            secrets=secrets,
            collector=collector,
            writer_factory=writer_factory,
        )


def _reserved(
    *,
    context,
    parent,
    parent_bytes,
    publication,
    promotion_bytes,
    auth,
    receipts,
    batfish,
    cml,
    intent,
    store,
    directory,
    pipeline_id,
    build_number,
    inventory,
    credential_authority,
    secrets,
    collector,
    writer_factory,
):
    record_id = UUID(context.job_id)
    preflight = final = None
    attempted, successful, child_refs, chronology_refs = [], [], [], []
    stop_member = stop_outcome = reason = None
    try:
        preflight = preflight_profiled_rollout(
            context,
            parent_bytes,
            publication,
            promotion_bytes,
            auth,
            receipts,
            batfish,
            cml,
            intent=intent,
            inventory=inventory,
            credential_authority=credential_authority,
            secrets=secrets,
            collector=collector,
        )
        store.put_model("preflight", preflight)
    except Exception:
        reason = "PREFLIGHT"
    cohorts = [(d, "CANARY", 0) for d in parent.canaries] + [
        (d, "WAVE", i) for i, wave in enumerate(parent.waves) for d in wave
    ]
    children = {c.device.device_identity: c for c in parent.children}
    for order, (identity, cohort_kind, cohort_index) in enumerate(cohorts):
        if reason:
            break
        child = children[identity]
        pre = post = execution = None
        child_id = child_record_id(record_id, identity)
        # Read only the approved original bytes. No model reserialization here.
        raw = child.artifact_bytes()
        plan = ProfiledDeploymentPlan.model_validate_json(raw)
        if (
            sha256_identity(raw) != child.artifact_digest
            or plan.digest != child.result_digest
            or plan != child.result()
        ):
            raise ValueError("approved child original bytes rejected")
        try:
            pre = validate_pre(plan, capture_profiled_attempt(plan))
            persist_attempt_file(directory / f"{child_id}-pre.json", pre)
        except Exception:
            reason, stop_member = "PRE_CHRONOLOGY", identity
            break
        # Mark possible execution before entering the child boundary. An escaping
        # exception cannot establish that no write occurred.
        attempted.append(identity)
        try:
            execution = execute_profiled_plan(
                plan, plan.digest, inventory, secrets, collector, writer_factory()
            )
            verify_profiled_record_plan(execution, plan)
            if execution.final_outcome == FinalOutcome.SUCCEEDED:
                successful.append(identity)
            else:
                reason, stop_member, stop_outcome = (
                    "CHILD_NON_SUCCESS",
                    identity,
                    execution.final_outcome,
                )
        except Exception:
            execution = None
            reason, stop_member = "CHILD_EXECUTION_UNCERTAIN", identity
        try:
            post = capture_profiled_attempt(plan, expected_before=pre.after_revision)
            persist_attempt_file(directory / f"{child_id}-post.json", post)
            if post.status not in SUCCESS:
                reason, stop_member = (
                    (
                        "CHILD_EXECUTION_UNCERTAIN"
                        if reason == "CHILD_EXECUTION_UNCERTAIN"
                        else "CHILD_EVIDENCE"
                    ),
                    identity,
                )
        except Exception:
            reason, stop_member = (
                (
                    "CHILD_EXECUTION_UNCERTAIN"
                    if reason == "CHILD_EXECUTION_UNCERTAIN"
                    else "CHILD_EVIDENCE"
                ),
                identity,
            )
        try:
            execution_digest = None
            if execution is not None:
                execution_raw = canonical_json_bytes(execution.model_dump(mode="json"))
                # Private evidence survives a durable-store failure.
                fd = os.open(
                    directory / f"{child_id}-execution.json",
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                    0o600,
                )
                with os.fdopen(fd, "wb") as stream:
                    stream.write(execution_raw)
                    stream.flush()
                    os.fsync(stream.fileno())
                execution_digest = store.put_bytes("execution", execution_raw)
                ref = store.persist_artifact(Kind.PROFILED_CHANGE_RECORD, execution)
                if store.read_artifact(ref) != execution:
                    raise ValueError("child execution canonical readback failed")
            audit = _signed(
                ProfiledRolloutChildAuditRecord,
                {
                    "record_id": child_id,
                    "parent_record_id": record_id,
                    "build_id": UUID(context.build_id),
                    "job_id": record_id,
                    "source_commit": context.commit,
                    "parent_digest": parent.digest,
                    "promotion_digest": auth.promotion_digest,
                    "authorization_digest": auth.digest,
                    "preflight_digest": preflight.digest,
                    "child": binding(child),
                    "cohort_kind": cohort_kind,
                    "cohort_index": cohort_index,
                    "execution_order": order,
                    "execution_attempted": True,
                    "execution_digest": execution_digest,
                    "final_outcome": execution.final_outcome if execution else None,
                    "pre_status": pre.status.value,
                    "post_status": post.status.value if post else None,
                },
            )
            store.persist_rollout_record(audit)
            child_ref = RecordReference(record_id=child_id, digest=audit.digest)
            child_refs.append(child_ref)
            if post is not None:
                chronology = _signed(
                    ProfiledRolloutChronologyRecord,
                    {
                        "record_id": chronology_record_id(child_id),
                        "child_audit": child_ref,
                        "device_identity": identity,
                        "pre": pre,
                        "post": post,
                        "overall_status": overall_status(post.status).value,
                    },
                )
                store.persist_rollout_record(chronology)
                chronology_refs.append(
                    RecordReference(
                        record_id=chronology.record_id, digest=chronology.digest
                    )
                )
        except Exception:
            reason, stop_member = (
                (
                    "CHILD_EXECUTION_UNCERTAIN"
                    if reason == "CHILD_EXECUTION_UNCERTAIN"
                    else "CHILD_EVIDENCE"
                ),
                identity,
            )
    if reason is None:
        final = validate_rollout_final_state(
            parent,
            auth,
            preflight,
            intent=intent,
            inventory=inventory,
            credential_authority=credential_authority,
            secrets=secrets,
            collector=collector,
        )
        try:
            store.put_model("final", final)
        except Exception:
            final = None
            reason = "CHILD_EVIDENCE"
        else:
            if final.status != "PASSED":
                reason = "FINAL_VALIDATION"
    outcome = (
        RolloutOutcome.SUCCEEDED
        if reason is None
        else RolloutOutcome.FINAL_VALIDATION_FAILED
        if reason == "FINAL_VALIDATION"
        else RolloutOutcome.PARTIAL
        if successful
        else RolloutOutcome.STOPPED
    )
    record = _signed(
        ProfiledRolloutAuditRecord,
        {
            "record_id": record_id,
            "pipeline_id": UUID(pipeline_id),
            "build_id": UUID(context.build_id),
            "build_number": build_number,
            "job_id": record_id,
            "source_commit": context.commit,
            "generated_at": datetime.now(UTC),
            "change_id": parent.intent.change_id,
            "parent_digest": parent.digest,
            "parent_artifact_digest": auth.parent_artifact_digest,
            "promotion_digest": auth.promotion_digest,
            "promotion_artifact_digest": auth.promotion_artifact_digest,
            "authorization_digest": auth.digest,
            "unblocker_id": UUID(auth.unblocker_id),
            "preflight_digest": preflight.digest if preflight else None,
            "children": tuple(binding(c) for c in parent.children),
            "canaries": parent.canaries,
            "waves": parent.waves,
            "child_records": tuple(child_refs),
            "chronology_records": tuple(chronology_refs),
            "compliant": tuple(
                c.device.device_identity
                for c in parent.children
                if c.kind == "COMPLIANT"
            ),
            "attempted": tuple(attempted),
            "successful": tuple(successful),
            "untouched": tuple(
                c.device.device_identity
                for c in parent.children
                if c.kind == "DEPLOYABLE" and c.device.device_identity not in attempted
            ),
            "stopping_member": stop_member,
            "stopping_reason": reason,
            "stopping_outcome": stop_outcome,
            "completed_canaries": tuple(d for d in parent.canaries if d in successful),
            "completed_waves": tuple(
                w for w in parent.waves if all(d in successful for d in w)
            ),
            "remaining_waves": tuple(
                w for w in parent.waves if not all(d in successful for d in w)
            ),
            "final_validation_digest": final.digest if final else None,
            "final_validation_status": final.status if final else None,
            "outcome": outcome,
        },
    )
    store.persist_rollout_record(record)
    return record
