"""Offline safety tests for sequential fleet execution and honest evidence."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError
from test_fleet import (
    CREATED,
    DESIRED,
    FleetCollector,
    FleetInventory,
    FleetSecrets,
    device,
    fleet_intent,
    make_plan,
    selected_four,
)

from network_change_delivery.fleet import deploy_fleet, plan_fleet
from network_change_delivery.models import (
    ChangeRecord,
    FinalOutcome,
    FleetChangeRecord,
    FleetFinalOutcome,
    FleetMemberClassification,
    StageResult,
)
from network_change_delivery.secrets import DeviceCredentials


def stage(message: str = "bounded") -> StageResult:
    return StageResult(message=message)


def child_record(plan, outcome: FinalOutcome) -> ChangeRecord:
    return ChangeRecord(
        generated_at=CREATED,
        change_id=plan.change_id,
        plan_digest=plan.digest,
        target=plan.target,
        inventory_source=plan.inventory_source,
        inventory_object_id=plan.inventory_object_id,
        inventory_interface_object_id=plan.inventory_interface_object_id,
        credential_source=plan.credential_source,
        credential_reference=plan.credential_reference,
        host=plan.host,
        port=plan.port,
        expected_hostname=plan.expected_hostname,
        platform=plan.platform,
        interface=plan.interface,
        previous_description=plan.current_description,
        desired_description=plan.desired_description,
        approval_digest=plan.digest,
        preflight=stage(),
        execution=stage(),
        post_validation=stage(),
        recovery=stage(),
        transaction_strategy=plan.transaction_strategy,
        final_outcome=outcome,
        provider="offline-test",
    )


class PhaseCollector(FleetCollector):
    """Return approved state for preflight and desired state for final validation."""

    def __init__(self, initial: dict[str, str | None], member_count: int) -> None:
        super().__init__(initial)
        self.member_count = member_count

    def collect(self, device, credentials: DeviceCredentials, interface: str):
        if len(self.calls) >= self.member_count:
            self.descriptions[device.name] = DESIRED
        return super().collect(device, credentials, interface)


class RecordingDeployer:
    def __init__(
        self,
        outcomes: dict[str, FinalOutcome] | None = None,
    ) -> None:
        self.outcomes = outcomes or {}
        self.calls: list[str] = []

    def __call__(
        self,
        plan,
        approval_digest,
        inventory,
        secrets,
        collector,
        executor,
        *,
        now,
    ) -> ChangeRecord:
        del inventory, secrets, collector, executor, now
        assert approval_digest == plan.digest
        self.calls.append(plan.target)
        outcome = self.outcomes.get(plan.target, FinalOutcome.SUCCEEDED)
        return child_record(plan, outcome)


def execute(
    *,
    descriptions: dict[str, str | None] | None = None,
    outcomes: dict[str, FinalOutcome] | None = None,
    approval_digest: str | None = None,
    collector=None,
):
    plan = make_plan(descriptions).plan
    assert plan is not None
    initial = descriptions or {item[0].name: "old" for item in selected_four()}
    collector = collector or PhaseCollector(dict(initial), len(plan.members))
    deployer = RecordingDeployer(outcomes)
    record = deploy_fleet(
        plan,
        approval_digest or plan.digest,
        FleetInventory(selected_four()),
        FleetSecrets(),
        collector,
        object(),
        now=lambda: datetime(2026, 8, 24, tzinfo=UTC),
        child_deployer=deployer,
    )
    return plan, record, deployer, collector


def test_success_uses_exact_canary_then_wave_order_and_validates_every_member() -> None:
    plan, record, deployer, collector = execute()
    assert deployer.calls == ["router-10", "router-11", "router-12", "router-13"]
    assert record.final_outcome is FleetFinalOutcome.SUCCEEDED
    attempted = sorted(
        (member for member in record.members if member.attempted),
        key=lambda member: member.attempt_sequence or 0,
    )
    assert [member.attempt_sequence for member in attempted] == [1, 2, 3, 4]
    assert [member.inventory_object_id for member in attempted] == [
        *plan.canaries,
        *plan.waves[0],
    ]
    assert all(
        member.child_record is not None
        and member.child_record.plan_digest == member.child_plan_digest
        for member in attempted
    )
    assert record.preflight.succeeded
    assert record.final_validation.succeeded
    assert len(record.final_validation.members) == len(plan.members)
    assert len(collector.calls) == len(plan.members) * 2


def test_compliant_members_are_preserved_without_child_deployment() -> None:
    descriptions = {item[0].name: "old" for item in selected_four()}
    descriptions["router-13"] = DESIRED
    _plan, record, deployer, _collector = execute(descriptions=descriptions)
    compliant = next(
        member
        for member in record.members
        if member.classification is FleetMemberClassification.COMPLIANT
    )
    assert compliant.target == "router-13"
    assert not compliant.attempted
    assert compliant.child_record is None
    assert compliant.child_plan_digest is None
    assert compliant.target not in deployer.calls


@pytest.mark.parametrize(
    "outcome", [item for item in FinalOutcome if item is not FinalOutcome.SUCCEEDED]
)
def test_every_non_success_child_outcome_stops_later_exposure(
    outcome: FinalOutcome,
) -> None:
    _plan, record, deployer, _collector = execute(outcomes={"router-11": outcome})
    assert deployer.calls == ["router-10", "router-11"]
    assert record.final_outcome is FleetFinalOutcome.PARTIAL
    assert record.stop_child_outcome is outcome
    assert sum(member.attempted for member in record.members) == 2
    assert all(
        not member.attempted
        for member in record.members
        if member.target in {"router-12", "router-13"}
    )
    assert not record.final_validation.attempted


@pytest.mark.parametrize(
    ("target", "expected_calls", "outcome"),
    [
        ("router-10", ["router-10"], FleetFinalOutcome.STOPPED),
        ("router-11", ["router-10", "router-11"], FleetFinalOutcome.PARTIAL),
        (
            "router-12",
            ["router-10", "router-11", "router-12"],
            FleetFinalOutcome.PARTIAL,
        ),
        (
            "router-13",
            ["router-10", "router-11", "router-12", "router-13"],
            FleetFinalOutcome.PARTIAL,
        ),
    ],
)
def test_stop_positions_attempt_once_and_never_retry_or_continue(
    target: str, expected_calls: list[str], outcome: FleetFinalOutcome
) -> None:
    _plan, record, deployer, _collector = execute(
        outcomes={target: FinalOutcome.AMBIGUOUS}
    )
    assert deployer.calls == expected_calls
    assert deployer.calls.count(target) == 1
    assert record.final_outcome is outcome
    assert record.stop_member_identity == next(
        member.inventory_object_id
        for member in record.members
        if member.target == target
    )
    assert sum(member.attempted for member in record.members) == len(expected_calls)


@pytest.mark.parametrize(
    ("wave_size", "expected_waves"),
    [(3, 1), (1, 3)],
)
def test_middle_of_wave_and_later_wave_stops_are_exact(
    wave_size: int,
    expected_waves: int,
) -> None:
    selected = (*selected_four(), device(14, "cisco_iosxe"))
    descriptions = {item[0].name: "old" for item in selected}
    plan = plan_fleet(
        fleet_intent(wave_size=wave_size),
        FleetInventory(selected),
        FleetSecrets(),
        FleetCollector(descriptions),
        created_at=CREATED,
    ).plan
    assert plan is not None
    assert len(plan.waves) == expected_waves
    deployer = RecordingDeployer({"router-13": FinalOutcome.RECOVERED})
    record = deploy_fleet(
        plan,
        plan.digest,
        FleetInventory(selected),
        FleetSecrets(),
        PhaseCollector(descriptions, len(plan.members)),
        object(),
        child_deployer=deployer,
    )
    assert deployer.calls == ["router-10", "router-11", "router-12", "router-13"]
    assert record.final_outcome is FleetFinalOutcome.PARTIAL
    assert record.stop_child_outcome is FinalOutcome.RECOVERED
    assert not next(
        member for member in record.members if member.target == "router-14"
    ).attempted


@pytest.mark.parametrize("approval", ["sha256:" + "f" * 64, "not-a-digest"])
def test_wrong_approval_blocks_before_any_child_attempt(approval: str) -> None:
    _plan, record, deployer, collector = execute(approval_digest=approval)
    assert record.final_outcome is FleetFinalOutcome.BLOCKED
    assert not record.preflight.succeeded
    assert deployer.calls == []
    assert collector.calls == []
    assert not any(member.attempted for member in record.members)


def test_invalid_fleet_digest_blocks_before_any_child_attempt() -> None:
    plan = make_plan().plan
    assert plan is not None
    plan = plan.model_copy(update={"digest": "sha256:" + "f" * 64})
    deployer = RecordingDeployer()
    collector = FleetCollector({item[0].name: "old" for item in selected_four()})
    record = deploy_fleet(
        plan,
        plan.digest,
        FleetInventory(selected_four()),
        FleetSecrets(),
        collector,
        object(),
        child_deployer=deployer,
    )
    assert record.final_outcome is FleetFinalOutcome.BLOCKED
    assert deployer.calls == []
    assert collector.calls == []


def test_complete_preflight_final_member_failure_has_zero_child_attempts() -> None:
    plan = make_plan().plan
    assert plan is not None
    descriptions = {item[0].name: "old" for item in selected_four()}
    descriptions["router-13"] = "jit-drift-secret-free"
    deployer = RecordingDeployer()
    collector = FleetCollector(descriptions)
    record = deploy_fleet(
        plan,
        plan.digest,
        FleetInventory(selected_four()),
        FleetSecrets(),
        collector,
        object(),
        child_deployer=deployer,
    )
    assert record.final_outcome is FleetFinalOutcome.BLOCKED
    assert deployer.calls == []
    assert collector.calls == ["router-10", "router-11", "router-12", "router-13"]


def test_membership_drift_blocks_complete_fleet_before_child_attempts() -> None:
    plan = make_plan().plan
    assert plan is not None
    deployer = RecordingDeployer()
    record = deploy_fleet(
        plan,
        plan.digest,
        FleetInventory(selected_four()[:-1]),
        FleetSecrets(),
        FleetCollector({}),
        object(),
        child_deployer=deployer,
    )
    assert record.final_outcome is FleetFinalOutcome.BLOCKED
    assert deployer.calls == []
    assert record.preflight.members == ()
    assert "membership" in record.preflight.message


def test_secret_bearing_preflight_exception_is_bounded_in_fleet_record() -> None:
    plan = make_plan().plan
    assert plan is not None

    class SecretCollector(FleetCollector):
        def collect(self, device, credentials, interface):
            if device.name == "router-13":
                raise RuntimeError("raw-fleet-provider-secret")
            return super().collect(device, credentials, interface)

    deployer = RecordingDeployer()
    record = deploy_fleet(
        plan,
        plan.digest,
        FleetInventory(selected_four()),
        FleetSecrets(),
        SecretCollector({item[0].name: "old" for item in selected_four()}),
        object(),
        child_deployer=deployer,
    )
    serialized = record.model_dump_json()
    assert record.final_outcome is FleetFinalOutcome.BLOCKED
    assert deployer.calls == []
    assert "raw-fleet-provider-secret" not in serialized
    assert "fleet-secret" not in serialized


def test_jit_child_stale_plan_is_preserved_and_stops_next_member() -> None:
    _plan, record, deployer, _collector = execute(
        outcomes={"router-12": FinalOutcome.STALE_PLAN}
    )
    assert deployer.calls == ["router-10", "router-11", "router-12"]
    stopped = next(member for member in record.members if member.target == "router-12")
    assert stopped.child_record is not None
    assert stopped.child_record.final_outcome is FinalOutcome.STALE_PLAN
    assert record.final_outcome is FleetFinalOutcome.PARTIAL
    assert not next(
        member for member in record.members if member.target == "router-13"
    ).attempted


@pytest.mark.parametrize("drift", ["written", "compliant", "membership"])
def test_final_validation_failure_preserves_child_successes_and_does_no_more_writes(
    drift: str,
) -> None:
    descriptions = {item[0].name: "old" for item in selected_four()}
    if drift == "compliant":
        descriptions["router-13"] = DESIRED
    plan = make_plan(descriptions).plan
    assert plan is not None

    class DriftCollector(PhaseCollector):
        def collect(self, device, credentials, interface):
            state = super().collect(device, credentials, interface)
            if len(self.calls) > self.member_count and device.name in {
                "router-10",
                "router-13",
            }:
                return state.model_copy(update={"description": "drifted"})
            return state

    inventory = FleetInventory(selected_four())
    if drift == "membership":
        calls = 0
        original = inventory.resolve_fleet

        def changed_selector(selector):
            nonlocal calls
            calls += 1
            selected = original(selector)
            return selected if calls == 1 else selected[:-1]

        inventory.resolve_fleet = changed_selector  # type: ignore[method-assign]
    collector = DriftCollector(dict(descriptions), len(plan.members))
    deployer = RecordingDeployer()
    record = deploy_fleet(
        plan,
        plan.digest,
        inventory,
        FleetSecrets(),
        collector,
        object(),
        child_deployer=deployer,
    )
    assert record.final_outcome is FleetFinalOutcome.FINAL_VALIDATION_FAILED
    assert all(
        member.child_record is None
        or member.child_record.final_outcome is FinalOutcome.SUCCEEDED
        for member in record.members
    )
    assert len(deployer.calls) == len(plan.canaries) + sum(map(len, plan.waves))


@pytest.mark.parametrize(
    "mutation",
    [
        "wrong_digest",
        "wrong_target",
        "skipped_with_record",
        "compliant_attempted",
        "duplicate_sequence",
        "out_of_order",
        "success_with_skipped",
        "partial_without_success",
        "blocked_with_attempt",
    ],
)
def test_fleet_change_record_rejects_tampered_evidence(mutation: str) -> None:
    descriptions = {item[0].name: "old" for item in selected_four()}
    descriptions["router-13"] = DESIRED
    _plan, record, _deployer, _collector = execute(descriptions=descriptions)
    payload = record.model_dump(mode="json")
    deployable = [
        index
        for index, item in enumerate(payload["members"])
        if item["child_plan_digest"]
    ]
    compliant = next(
        index
        for index, item in enumerate(payload["members"])
        if not item["child_plan_digest"]
    )
    if mutation == "wrong_digest":
        payload["members"][deployable[0]]["child_plan_digest"] = "sha256:" + "f" * 64
    elif mutation == "wrong_target":
        payload["members"][deployable[0]]["target"] = "wrong-target"
    elif mutation == "skipped_with_record":
        item = payload["members"][deployable[-1]]
        item["attempted"] = False
    elif mutation == "compliant_attempted":
        payload["members"][compliant]["attempted"] = True
        payload["members"][compliant]["attempt_sequence"] = 99
    elif mutation == "duplicate_sequence":
        payload["members"][deployable[1]]["attempt_sequence"] = 1
    elif mutation == "out_of_order":
        first = payload["members"][deployable[0]]["attempt_sequence"]
        payload["members"][deployable[0]]["attempt_sequence"] = payload["members"][
            deployable[1]
        ]["attempt_sequence"]
        payload["members"][deployable[1]]["attempt_sequence"] = first
    elif mutation == "success_with_skipped":
        payload["members"][deployable[-1]]["attempted"] = False
        payload["members"][deployable[-1]]["attempt_sequence"] = None
        payload["members"][deployable[-1]]["child_record"] = None
    elif mutation == "partial_without_success":
        payload["final_outcome"] = "PARTIAL"
        payload["members"][deployable[0]]["child_record"]["final_outcome"] = "AMBIGUOUS"
        for index in deployable[1:]:
            payload["members"][index]["attempted"] = False
            payload["members"][index]["attempt_sequence"] = None
            payload["members"][index]["child_record"] = None
        payload["stop_member_identity"] = payload["members"][deployable[0]][
            "inventory_object_id"
        ]
        payload["stop_child_outcome"] = "AMBIGUOUS"
        payload["final_validation"] = {
            "attempted": False,
            "succeeded": None,
            "members": [],
            "message": "not attempted",
        }
    else:
        payload["final_outcome"] = "BLOCKED"
        payload["final_validation"] = {
            "attempted": False,
            "succeeded": None,
            "members": [],
            "message": "not attempted",
        }
    with pytest.raises(ValidationError):
        FleetChangeRecord.model_validate(payload)


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_preflight",
        "duplicate_preflight",
        "wrong_preflight_target",
        "wrong_preflight_identity",
        "wrong_preflight_classification",
        "reordered_preflight",
        "missing_final",
        "duplicate_final",
        "wrong_final_identity",
        "wrong_final_classification",
        "reordered_final",
        "one_member_final",
    ],
)
def test_fleet_record_binds_read_only_evidence_to_complete_frozen_plan(
    mutation: str,
) -> None:
    _plan, record, _deployer, _collector = execute()
    payload = record.model_dump(mode="json")
    if mutation == "missing_preflight":
        payload["preflight"]["members"].pop()
    elif mutation == "duplicate_preflight":
        payload["preflight"]["members"][-1] = payload["preflight"]["members"][0]
    elif mutation == "wrong_preflight_target":
        payload["preflight"]["members"][0]["target"] = "wrong-target"
    elif mutation == "wrong_preflight_identity":
        payload["preflight"]["members"][0]["inventory_object_id"] = (
            "netbox:dcim.device:999"
        )
    elif mutation == "wrong_preflight_classification":
        payload["preflight"]["members"][0]["classification"] = "COMPLIANT"
    elif mutation == "reordered_preflight":
        payload["preflight"]["members"].reverse()
    elif mutation == "missing_final":
        payload["final_validation"]["members"].pop()
    elif mutation == "duplicate_final":
        payload["final_validation"]["members"][-1] = payload["final_validation"][
            "members"
        ][0]
    elif mutation == "wrong_final_identity":
        payload["final_validation"]["members"][0]["inventory_interface_object_id"] = (
            "netbox:dcim.interface:999"
        )
    elif mutation == "wrong_final_classification":
        payload["final_validation"]["members"][0]["classification"] = "COMPLIANT"
    elif mutation == "reordered_final":
        payload["final_validation"]["members"].reverse()
    else:
        payload["final_validation"]["members"] = payload["final_validation"]["members"][
            :1
        ]
    with pytest.raises(ValidationError):
        FleetChangeRecord.model_validate(payload)


@pytest.mark.parametrize(
    ("field", "tampered"),
    [
        ("change_id", "CHG-WRONG"),
        ("plan_digest", "sha256:" + "f" * 64),
        ("approval_digest", "sha256:" + "f" * 64),
        ("target", "wrong-target"),
        ("inventory_source", "local_yaml"),
        ("inventory_object_id", "netbox:dcim.device:999"),
        ("inventory_interface_object_id", "netbox:dcim.interface:999"),
        ("credential_source", "environment"),
        ("credential_reference", "environment:NCDP_DEVICE_USERNAME/PASSWORD"),
        ("host", "192.0.2.250"),
        ("port", 2222),
        ("expected_hostname", "wrong-hostname"),
        ("platform", "junos"),
        ("interface", "wrong-interface"),
        ("previous_description", "wrong-previous"),
        ("desired_description", "wrong-desired"),
        ("transaction_strategy", "junos_commit_confirmed"),
    ],
)
def test_fleet_record_binds_every_child_authorization_field(
    field: str,
    tampered: object,
) -> None:
    _plan, record, _deployer, _collector = execute()
    payload = record.model_dump(mode="json")
    attempted = next(member for member in payload["members"] if member["attempted"])
    attempted["child_record"][field] = tampered
    with pytest.raises(ValidationError):
        FleetChangeRecord.model_validate(payload)


def test_failed_member_preflight_cannot_omit_frozen_members() -> None:
    plan = make_plan().plan
    assert plan is not None
    descriptions = {item[0].name: "old" for item in selected_four()}
    descriptions["router-13"] = "changed-after-approval"
    record = deploy_fleet(
        plan,
        plan.digest,
        FleetInventory(selected_four()),
        FleetSecrets(),
        FleetCollector(descriptions),
        object(),
        child_deployer=RecordingDeployer(),
    )
    assert record.final_outcome is FleetFinalOutcome.BLOCKED
    assert len(record.preflight.members) == len(plan.members)
    payload = record.model_dump(mode="json")
    payload["preflight"]["members"].pop(0)
    with pytest.raises(ValidationError, match="does not cover frozen fleet"):
        FleetChangeRecord.model_validate(payload)


def test_failed_member_final_validation_cannot_omit_frozen_members() -> None:
    _plan, record, _deployer, _collector = execute()
    payload = record.model_dump(mode="json")
    payload["final_outcome"] = "FINAL_VALIDATION_FAILED"
    payload["final_validation"]["succeeded"] = False
    payload["final_validation"]["members"][0]["succeeded"] = False
    valid_failure = FleetChangeRecord.model_validate(payload)
    assert valid_failure.final_outcome is FleetFinalOutcome.FINAL_VALIDATION_FAILED
    payload["final_validation"]["members"].pop()
    with pytest.raises(ValidationError, match="does not cover frozen fleet"):
        FleetChangeRecord.model_validate(payload)
