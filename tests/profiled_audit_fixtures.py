"""Synthetic offline artifacts and temporary stores; never current runtime evidence."""

from datetime import UTC, datetime
from uuid import UUID

from test_profiled_execution import Cisco, Collector, Inventory, Junos, Secrets, writer
from test_profiled_planning import (
    FakeCollector,
    FakeInventory,
    FakeSecrets,
    observed,
    profiled_device,
)

from network_change_delivery.architecture_contracts import AutomationProfileID
from network_change_delivery.audit import (
    AuditArtifactKind as Kind,
)
from network_change_delivery.audit import (
    BuildkiteCorrelation,
    CredentialProvenance,
    GitCorrelation,
    StableTargetIdentity,
    sha256_identity,
)
from network_change_delivery.models import ExecutionResult, InterfaceDescriptionIntent
from network_change_delivery.profiled_audit import (
    PROFILED_REPOSITORY,
    ProfiledArtifactByteDigests,
    ProfiledAssuranceCorrelation,
    ProfiledHumanAuthorization,
    profiled_audit_record_with_digest,
)
from network_change_delivery.profiled_execution import execute_profiled_plan
from network_change_delivery.profiled_planning import plan_profiled_change
from network_change_delivery.profiled_promotion import (
    CHANGE_ID,
    DESCRIPTION,
    VALIDATION_KEYS,
    ProfiledBuildContext,
    promote,
    validation_receipt,
)

NOW = datetime(2026, 9, 9, 12, tzinfo=UTC)
BUILD = UUID("11111111-1111-4111-8111-111111111111")
JOB = UUID("22222222-2222-4222-8222-222222222222")
PIPELINE = UUID("33333333-3333-4333-8333-333333333333")
RECORD = UUID("44444444-4444-4444-8444-444444444444")
COMMIT = "a" * 40
ASSURANCE = "sha256:" + "b" * 64


def raw_bytes(model):
    return model.model_dump_json(indent=2).encode() + b"\n"


def planning_result(profile=AutomationProfileID.CAT8000V_IOSXE, *, compliant=False):
    device, interface = profiled_device(profile)
    intent = InterfaceDescriptionIntent(
        kind="interface_description",
        change_id=CHANGE_ID,
        target=device.logical_name,
        interface=interface.name,
        desired={"description": DESCRIPTION},
    )
    state = observed(device, interface).model_copy(
        update={"description": DESCRIPTION if compliant else "previous"}
    )
    result = plan_profiled_change(
        intent,
        FakeInventory(device, interface),
        FakeSecrets(),
        FakeCollector(state),
        created_at=NOW,
    )
    return result, device, interface, state


def execution_pair(profile=AutomationProfileID.CAT8000V_IOSXE):
    result, device, interface, state = planning_result(profile)
    plan = result.plan
    success = ExecutionResult(
        disposition="SUCCEEDED", changed=None, message="bounded fixture"
    )
    record = execute_profiled_plan(
        plan,
        plan.digest,
        Inventory(device, interface),
        Secrets(),
        Collector([state, state.model_copy(update={"description": DESCRIPTION})]),
        writer(Cisco([success]), Junos(success, success)),
        now=lambda: NOW,
    )
    return plan, record


def execution_artifacts(profile=AutomationProfileID.CAT8000V_IOSXE):
    plan, record = execution_pair(profile)
    context = ProfiledBuildContext(str(BUILD), COMMIT, str(JOB), "profiled-deploy")
    promotion = promote(
        context,
        raw_bytes(plan),
        {key: validation_receipt(str(BUILD), COMMIT, key) for key in VALIDATION_KEYS},
        ASSURANCE,
        ASSURANCE,
    )
    return {
        Kind.PROFILED_DEPLOYMENT_PLAN: plan,
        Kind.PROFILED_PROMOTION: promotion,
        Kind.PROFILED_CHANGE_RECORD: record,
    }


def bundle(
    store,
    *,
    compliant=False,
    profile=AutomationProfileID.CAT8000V_IOSXE,
    record_id=RECORD,
):
    if compliant:
        result, *_ = planning_result(profile, compliant=True)
        artifacts = {Kind.PROFILED_COMPLIANCE_RECORD: result.compliance}
        planning = result.compliance
    else:
        artifacts = execution_artifacts(profile)
        planning = artifacts[Kind.PROFILED_DEPLOYMENT_PLAN]
    raw = {kind: raw_bytes(value) for kind, value in artifacts.items()}
    refs = tuple(
        store.persist_artifact(kind, artifacts[kind])
        for kind in sorted(artifacts, key=str)
    )
    promotion = artifacts.get(Kind.PROFILED_PROMOTION)
    audit = profiled_audit_record_with_digest(
        record_id=record_id,
        generated_at=NOW,
        change_id=planning.change_id,
        git=GitCorrelation(repository=PROFILED_REPOSITORY, commit=COMMIT),
        buildkite=BuildkiteCorrelation(
            pipeline_id=PIPELINE,
            build_id=BUILD,
            build_number=42,
            job_id=JOB,
            step_key="profiled-deploy",
        ),
        target=StableTargetIdentity(
            device=planning.device_identity, interface=planning.interface.interface
        ),
        credential=CredentialProvenance(
            device=planning.device_identity,
            source=planning.credential_source,
            reference=planning.credential_reference,
        ),
        delivery_kind="COMPLIANCE" if compliant else "EXECUTION",
        final_outcome="COMPLIANT"
        if compliant
        else artifacts[Kind.PROFILED_CHANGE_RECORD].final_outcome,
        artifacts=refs,
        planning_result_digest=planning.digest,
        artifact_bytes=ProfiledArtifactByteDigests(
            planning=sha256_identity(raw_bytes(planning)),
            promotion=sha256_identity(raw[Kind.PROFILED_PROMOTION])
            if promotion
            else None,
            execution=sha256_identity(raw[Kind.PROFILED_CHANGE_RECORD])
            if promotion
            else None,
        ),
        authorization=ProfiledHumanAuthorization(
            unblocker_id=UUID(int=77), promotion_digest=promotion.digest
        )
        if promotion
        else None,
        assurance=ProfiledAssuranceCorrelation(
            validation_digest=promotion.validation_digest,
            batfish_digest=promotion.batfish_digest,
            cml_digest=promotion.cml_digest,
        )
        if promotion
        else None,
    )
    return audit, raw, artifacts
