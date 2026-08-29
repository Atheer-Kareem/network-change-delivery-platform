"""Single-attempt protected workflow for one typed SNMPv3 provisioning plan."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol

from network_change_delivery.models import (
    ExecutionDisposition,
    ExecutionResult,
    InventoryDevice,
)
from network_change_delivery.secrets import DeviceCredentials, SecretError
from network_change_delivery.snmp_credentials import SnmpProvisioningCredentials
from network_change_delivery.snmp_provisioning import (
    SecretRenderedArtifact,
    SnmpOwnedObjectState,
    SnmpOwnedStateDisposition,
    SnmpProvisioningOutcome,
    SnmpProvisioningPlan,
    SnmpProvisioningRecord,
    SnmpProvisioningStage,
    cisco_recovery_commands,
    render_cisco_provisioning,
    render_junos_provisioning,
)


class SnmpCredentialSource(Protocol):
    def load(self) -> SnmpProvisioningCredentials: ...


class SnmpProvisioningAdapter(Protocol):
    def preflight(
        self,
        device: InventoryDevice,
        credentials: DeviceCredentials,
        plan: SnmpProvisioningPlan,
    ) -> SnmpOwnedObjectState: ...

    def execute_cisco(
        self,
        device: InventoryDevice,
        credentials: DeviceCredentials,
        artifact: SecretRenderedArtifact,
    ) -> ExecutionResult: ...

    def execute_junos_confirmed(
        self,
        device: InventoryDevice,
        credentials: DeviceCredentials,
        artifact: SecretRenderedArtifact,
        minutes: int,
    ) -> ExecutionResult: ...

    def post_validate(
        self,
        device: InventoryDevice,
        credentials: DeviceCredentials,
        plan: SnmpProvisioningPlan,
    ) -> SnmpOwnedObjectState: ...

    def recover_cisco(
        self,
        device: InventoryDevice,
        credentials: DeviceCredentials,
        plan: SnmpProvisioningPlan,
        commands: tuple[str, ...],
    ) -> ExecutionResult: ...

    def confirm_junos(
        self, device: InventoryDevice, credentials: DeviceCredentials
    ) -> ExecutionResult: ...


def _stage(
    message: str,
    *,
    attempted: bool = False,
    succeeded: bool | None = None,
    disposition: SnmpOwnedStateDisposition | None = None,
) -> SnmpProvisioningStage:
    return SnmpProvisioningStage(
        message=message,
        attempted=attempted,
        succeeded=succeeded,
        disposition=disposition,
    )


def _record(
    plan: SnmpProvisioningPlan,
    outcome: SnmpProvisioningOutcome,
    *,
    preflight: SnmpProvisioningStage,
    execution: SnmpProvisioningStage | None = None,
    post: SnmpProvisioningStage | None = None,
    recovery: SnmpProvisioningStage | None = None,
    now: Callable[[], datetime],
) -> SnmpProvisioningRecord:
    return SnmpProvisioningRecord(
        generated_at=now(),
        change_id=plan.change_id,
        plan_digest=plan.digest,
        approval_digest=plan.digest,
        device=plan.inventory_object_id,
        platform=plan.platform,
        generation=plan.generation,
        username=plan.username,
        credential_reference=plan.snmp_credential.reference,
        view_name=plan.view_name,
        group_name=plan.group_name,
        oid_closure_digest=plan.oid_closure_digest,
        preflight=preflight,
        execution=execution or _stage("execution not attempted"),
        post_validation=post or _stage("post-validation not attempted"),
        recovery=recovery or _stage("recovery not attempted"),
        final_outcome=outcome,
    )


def _exact_post_state(state: SnmpOwnedObjectState, plan: SnmpProvisioningPlan) -> bool:
    return (
        state.observed_hostname == plan.expected_hostname
        and state.local_engine_id_present
        and state.view is SnmpOwnedStateDisposition.EXACT_NCDP_STATE
        and state.group is SnmpOwnedStateDisposition.EXACT_NCDP_STATE
        and state.user is SnmpOwnedStateDisposition.EXACT_NCDP_STATE
    )


def deploy_snmp_provisioning_plan(
    plan: SnmpProvisioningPlan,
    approval_digest: str,
    device: InventoryDevice,
    connection_credentials: DeviceCredentials,
    snmp_credentials: SnmpCredentialSource,
    adapter: SnmpProvisioningAdapter,
    prewrite_gate: Callable[[], None],
    *,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> SnmpProvisioningRecord:
    """Execute once; acquire SNMP secrets only after fresh preflight and audit gate."""
    blocked = _stage("pre-write verification blocked", attempted=True, succeeded=False)
    if (
        not plan.verify_digest()
        or approval_digest != plan.digest
        or device.inventory_object_id != plan.inventory_object_id
        or device.platform != plan.platform
        or device.host != plan.host
        or device.port != plan.port
    ):
        return _record(
            plan, SnmpProvisioningOutcome.BLOCKED, preflight=blocked, now=now
        )
    try:
        state = adapter.preflight(device, connection_credentials, plan)
    except (OSError, RuntimeError, ValueError):
        return _record(
            plan, SnmpProvisioningOutcome.BLOCKED, preflight=blocked, now=now
        )
    if state != plan.preconditions or not state.safe_to_create:
        return _record(
            plan,
            SnmpProvisioningOutcome.BLOCKED,
            preflight=_stage(
                "fresh owned-name state no longer matches the approved absent state",
                attempted=True,
                succeeded=False,
                disposition=SnmpOwnedStateDisposition.CONFLICT,
            ),
            now=now,
        )
    preflight = _stage(
        "fresh identity, engine, and absent owned names verified",
        attempted=True,
        succeeded=True,
        disposition=SnmpOwnedStateDisposition.ABSENT,
    )
    try:
        prewrite_gate()
    except (OSError, RuntimeError, ValueError):
        return _record(
            plan, SnmpProvisioningOutcome.BLOCKED, preflight=preflight, now=now
        )
    try:
        runtime_credentials = snmp_credentials.load()
    except SecretError:
        return _record(
            plan, SnmpProvisioningOutcome.BLOCKED, preflight=preflight, now=now
        )
    artifact = (
        render_junos_provisioning(plan, runtime_credentials)
        if plan.platform == "junos"
        else render_cisco_provisioning(plan, runtime_credentials)
    )
    try:
        result = (
            adapter.execute_junos_confirmed(
                device,
                connection_credentials,
                artifact,
                plan.confirmed_timeout_minutes or 0,
            )
            if plan.platform == "junos"
            else adapter.execute_cisco(device, connection_credentials, artifact)
        )
    finally:
        del artifact
        del runtime_credentials
    execution = _stage(
        result.message,
        attempted=True,
        succeeded=result.disposition is ExecutionDisposition.SUCCEEDED,
    )
    if result.disposition is ExecutionDisposition.AMBIGUOUS:
        return _record(
            plan,
            SnmpProvisioningOutcome.AMBIGUOUS,
            preflight=preflight,
            execution=execution,
            now=now,
        )
    if result.disposition is ExecutionDisposition.FAILED:
        return _record(
            plan,
            SnmpProvisioningOutcome.EXECUTION_FAILED,
            preflight=preflight,
            execution=execution,
            now=now,
        )
    try:
        observed = adapter.post_validate(device, connection_credentials, plan)
    except (OSError, RuntimeError, ValueError):
        observed = None
    if observed is not None and _exact_post_state(observed, plan):
        post = _stage(
            "fresh normalized owned state matches the approved contract",
            attempted=True,
            succeeded=True,
            disposition=SnmpOwnedStateDisposition.EXACT_NCDP_STATE,
        )
        if plan.platform == "junos":
            confirmed = adapter.confirm_junos(device, connection_credentials)
            if confirmed.disposition is not ExecutionDisposition.SUCCEEDED:
                outcome = (
                    SnmpProvisioningOutcome.CONFIRMATION_AMBIGUOUS
                    if confirmed.disposition is ExecutionDisposition.AMBIGUOUS
                    else SnmpProvisioningOutcome.CONFIRMATION_FAILED
                )
                return _record(
                    plan,
                    outcome,
                    preflight=preflight,
                    execution=execution,
                    post=post,
                    recovery=_stage(
                        confirmed.message,
                        attempted=True,
                        succeeded=False,
                    ),
                    now=now,
                )
        return _record(
            plan,
            SnmpProvisioningOutcome.SUCCEEDED,
            preflight=preflight,
            execution=execution,
            post=post,
            now=now,
        )
    post = _stage(
        "fresh normalized owned state did not match the approved contract",
        attempted=True,
        succeeded=False,
        disposition=SnmpOwnedStateDisposition.CONFLICT,
    )
    if plan.platform == "junos":
        return _record(
            plan,
            SnmpProvisioningOutcome.AUTO_ROLLBACK_PENDING,
            preflight=preflight,
            execution=execution,
            post=post,
            now=now,
        )
    recovered = adapter.recover_cisco(
        device, connection_credentials, plan, cisco_recovery_commands(plan)
    )
    recovery = _stage(
        recovered.message,
        attempted=True,
        succeeded=recovered.disposition is ExecutionDisposition.SUCCEEDED,
    )
    if recovered.disposition is not ExecutionDisposition.SUCCEEDED:
        return _record(
            plan,
            SnmpProvisioningOutcome.RECOVERY_FAILED,
            preflight=preflight,
            execution=execution,
            post=post,
            recovery=recovery,
            now=now,
        )
    try:
        final = adapter.post_validate(device, connection_credentials, plan)
    except (OSError, RuntimeError, ValueError):
        final = None
    absent = final is not None and final.safe_to_create
    return _record(
        plan,
        (
            SnmpProvisioningOutcome.RECOVERED
            if absent
            else SnmpProvisioningOutcome.RECOVERY_FAILED
        ),
        preflight=preflight,
        execution=execution,
        post=post,
        recovery=recovery.model_copy(
            update={
                "succeeded": absent,
                "message": (
                    "exact owned objects absent after recovery"
                    if absent
                    else "owned-object absence not proven after recovery"
                ),
            }
        ),
        now=now,
    )
