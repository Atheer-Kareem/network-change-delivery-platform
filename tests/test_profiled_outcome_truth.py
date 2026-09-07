"""Offline outcome authority, observations and exact record/plan bindings."""

import json
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from test_profiled_execution import (
    Cisco,
    Collector,
    Inventory,
    Junos,
    Secrets,
    plan,
    writer,
)

from network_change_delivery.architecture_contracts import AutomationProfileID
from network_change_delivery.models import ExecutionResult
from network_change_delivery.profiled_execution import (
    ProfiledChangeRecord,
    execute_profiled_plan,
    verify_profiled_record_plan,
)


def result(disposition="SUCCEEDED", changed=None):
    return ExecutionResult(disposition=disposition, changed=changed, message="bounded")


class Observations(Collector):
    def collect(self, *args):
        value = super().collect(*args)
        if isinstance(value, Exception):
            raise value
        return value


def run_cisco(
    *,
    changed=None,
    execution="SUCCEEDED",
    post="new",
    recovery="SUCCEEDED",
    restored="old",
):
    approved, device, interface, state = plan()
    states = [state]
    states.extend(
        RuntimeError("unavailable")
        if description == "unavailable"
        else state.model_copy(update={"description": description})
        for description in (post, restored)
    )
    cisco = Cisco([result(execution, changed), result(recovery, changed)])
    record = execute_profiled_plan(
        approved,
        approved.digest,
        Inventory(device, interface),
        Secrets(),
        Observations(states),
        writer(cisco),
    )
    verify_profiled_record_plan(record, approved)
    assert ProfiledChangeRecord.model_validate_json(record.model_dump_json()) == record
    return approved, record, cisco


@pytest.mark.parametrize("changed", [True, False, None])
def test_provider_metadata_does_not_decide_success_or_observed_transition(changed):
    _, record, cisco = run_cisco(changed=changed)
    assert record.execution.changed is changed
    assert record.post_validation.changed is True
    assert record.final_outcome.value == "SUCCEEDED"
    assert len(cisco.artifacts) == 1 and not record.recovery.attempted


@pytest.mark.parametrize("metadata", ["false", "true", 0, 1, [], {}, None])
def test_normalized_provider_result_never_coerces_non_booleans(metadata):
    assert result(changed=metadata).changed is None


@pytest.mark.parametrize(
    "post,expected",
    [("old", False), ("new", True), (None, True), ("unavailable", None)],
)
def test_ambiguous_reconciliation_observes_without_overriding_uncertainty(
    post, expected
):
    _, record, cisco = run_cisco(execution="AMBIGUOUS", post=post)
    assert record.post_validation.changed is expected
    assert record.final_outcome.value == "AMBIGUOUS"
    assert len(cisco.artifacts) == 1 and not record.recovery.attempted


def test_noncomparable_identity_is_unknown_not_provider_false():
    approved, device, interface, state = plan()
    for execution in ("SUCCEEDED", "AMBIGUOUS"):
        cisco = Cisco([result(execution, False)])
        record = execute_profiled_plan(
            approved,
            approved.digest,
            Inventory(device, interface),
            Secrets(),
            Collector(
                [
                    state,
                    state.model_copy(
                        update={"observed_hostname": "wrong", "description": "new"}
                    ),
                ]
            ),
            writer(cisco),
        )
        assert record.post_validation.changed is None
        assert record.post_validation.observed_description == "new"
        assert not record.recovery.attempted


@pytest.mark.parametrize(
    "options,outcome",
    [
        ({"execution": "FAILED"}, "EXECUTION_FAILED"),
        ({"post": "unavailable"}, "POST_VALIDATION_FAILED"),
        ({"post": "old"}, "RECOVERED"),
        ({"post": "old", "recovery": "FAILED"}, "RECOVERY_FAILED"),
        ({"post": "old", "recovery": "AMBIGUOUS"}, "RECOVERY_AMBIGUOUS"),
        ({"post": "old", "restored": "unavailable"}, "RECOVERY_FAILED"),
        ({"post": "old", "restored": "wrong"}, "RECOVERY_FAILED"),
    ],
)
def test_cisco_legitimate_failure_and_recovery_matrix(options, outcome):
    _, record, _ = run_cisco(**options)
    assert record.final_outcome.value == outcome
    if record.recovery.attempted:
        assert record.post_validation.changed is False
        assert record.recovery.changed is None


class TransactionJunos(Junos):
    def __init__(self, commit="SUCCEEDED", confirmation="SUCCEEDED", phase=None):
        super().__init__(result(commit), result(confirmation))
        self.phase = phase

    @contextmanager
    def profiled_transaction(self, *_args):
        if self.phase == "entry":
            raise RuntimeError("entry rejected")
        outer = self

        class Transaction:
            close_failed = False

            def prepare(self):
                if outer.phase == "prepare":
                    raise RuntimeError("prepare rejected")
                return SimpleNamespace(diff_sha256="sha256:" + "a" * 64)

            def commit_confirmed(self, minutes):
                assert minutes == 5
                outer.commits += 1
                if outer.phase == "commit":
                    raise RuntimeError("uncertain")
                return outer.result

        yield Transaction()
        if self.phase == "close":
            raise RuntimeError("close failed")


def run_junos(commit="SUCCEEDED", confirmation="SUCCEEDED", phase=None, post="new"):
    approved, device, interface, state = plan(AutomationProfileID.VJUNOS_ROUTER)
    junos = TransactionJunos(commit, confirmation, phase)
    record = execute_profiled_plan(
        approved,
        approved.digest,
        Inventory(device, interface),
        Secrets(),
        Observations(
            [
                state,
                RuntimeError("unavailable")
                if post == "unavailable"
                else state.model_copy(update={"description": post}),
            ]
        ),
        writer(junos=junos),
    )
    verify_profiled_record_plan(record, approved)
    assert not record.recovery.attempted
    return approved, record, junos


@pytest.mark.parametrize(
    "options,outcome,confirms",
    [
        ({}, "SUCCEEDED", 1),
        ({"phase": "entry"}, "BLOCKED", 0),
        ({"phase": "prepare"}, "BLOCKED", 0),
        ({"phase": "commit"}, "AMBIGUOUS", 0),
        ({"commit": "FAILED"}, "EXECUTION_FAILED", 0),
        ({"commit": "AMBIGUOUS"}, "AMBIGUOUS", 0),
        ({"phase": "close"}, "AUTO_ROLLBACK_PENDING", 0),
        ({"post": "old"}, "AUTO_ROLLBACK_PENDING", 0),
        ({"post": "unavailable"}, "AUTO_ROLLBACK_PENDING", 0),
        ({"confirmation": "FAILED"}, "CONFIRMATION_FAILED", 1),
        ({"confirmation": "AMBIGUOUS"}, "CONFIRMATION_AMBIGUOUS", 1),
    ],
)
def test_junos_candidate_commit_observation_and_confirmation_matrix(
    options, outcome, confirms
):
    _, record, junos = run_junos(**options)
    assert record.final_outcome.value == outcome
    assert junos.confirms == confirms and junos.commits <= 1
    if record.post_validation.succeeded is True:
        assert record.post_validation.changed is True
    assert record.execution.changed is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("approval_digest", "sha256:" + "b" * 64),
        ("preflight.attempted", False),
        ("preflight.succeeded", False),
        ("preflight.observed_description", "wrong"),
        ("execution.attempted", False),
        ("execution.succeeded", False),
        ("post_validation.attempted", False),
        ("post_validation.succeeded", False),
        ("post_validation.observed_description", "wrong"),
        ("post_validation.changed", False),
        ("recovery.attempted", True),
        ("recovery.succeeded", True),
        ("final_outcome", "BLOCKED"),
        ("final_outcome", "STALE_PLAN"),
        ("final_outcome", "RECOVERED"),
        ("final_outcome", "COMPLIANT"),
        ("final_outcome", "AUTO_ROLLBACK_PENDING"),
        ("final_outcome", "CONFIRMATION_FAILED"),
        (
            "candidate_validation",
            {"attempted": True, "succeeded": True, "message": "bad"},
        ),
        ("candidate_diff_digest", "sha256:" + "a" * 64),
        ("confirmation", {"attempted": True, "succeeded": True, "message": "bad"}),
    ],
)
def test_contradictory_cisco_records_are_rejected(field, value):
    _, record, _ = run_cisco()
    data = record.model_dump(mode="json")
    path = field.split(".")
    node = data if len(path) == 1 else data[path[0]]
    node[path[-1]] = value
    with pytest.raises(ValueError):
        ProfiledChangeRecord.model_validate(data)


@pytest.mark.parametrize(
    "field,value",
    [
        ("candidate_validation", None),
        ("candidate_diff_digest", None),
        ("candidate_validation.succeeded", False),
        ("confirmation", None),
        ("confirmation.succeeded", False),
        ("confirmation.attempted", False),
        ("final_outcome", "AUTO_ROLLBACK_PENDING"),
        ("recovery.attempted", True),
    ],
)
def test_contradictory_junos_success_records_are_rejected(field, value):
    _, record, _ = run_junos()
    data = record.model_dump(mode="json")
    path = field.split(".")
    node = data if len(path) == 1 else data[path[0]]
    node[path[-1]] = value
    with pytest.raises(ValueError):
        ProfiledChangeRecord.model_validate(data)


@pytest.mark.parametrize(
    "field,value",
    [
        ("change_id", "CHG-OTHER"),
        ("plan_digest", "sha256:" + "b" * 64),
        ("approval_digest", "sha256:" + "b" * 64),
        ("target", "other"),
        ("device_identity", "netbox:dcim.device:2"),
        ("platform_slug", "juniper-junos"),
        ("network_os", "junos"),
        ("automation_profile_id", "vjunos_router"),
        ("operation", "other"),
        ("host", "192.0.2.90"),
        ("port", 2222),
        ("expected_hostname", "other"),
        ("previous_description", "other"),
        ("desired_description", "other"),
        ("credential_source", "environment"),
        ("credential_reference", "other"),
        ("transaction_strategy", "junos_commit_confirmed"),
        (
            "interface",
            {
                "device": "netbox:dcim.device:1",
                "interface": "netbox:dcim.interface:99",
                "name": "GigabitEthernet2",
            },
        ),
    ],
)
def test_record_to_plan_verifies_each_duplicated_binding_even_unvalidated_copies(
    field, value
):
    approved, record, _ = run_cisco()
    with pytest.raises(ValueError):
        verify_profiled_record_plan(record.model_copy(update={field: value}), approved)


@pytest.fixture
def accepted_success_reconstruction():
    """Supplied acceptance facts, not the unavailable original artifact bytes.

    Unspecified fields/timestamp come from synthetic test composition. No claim
    is made to reproduce the historical evidence artifact digest.
    """
    _, record, _ = run_cisco(changed=False)
    data = json.loads(record.model_dump_json())
    data.update(
        change_id="CHG-PROFILED-LAB-DEMO",
        plan_digest="sha256:993da66158218887b0e45f89eed3685dca4181b3026a1f814f598352414256c0",
        approval_digest="sha256:993da66158218887b0e45f89eed3685dca4181b3026a1f814f598352414256c0",
        previous_description="ncdp-pr132-live-core-14b725b",
        desired_description="managed-by-ncdp-profiled-demo",
    )
    data["preflight"]["observed_description"] = data["previous_description"]
    data["post_validation"].update(
        observed_description=data["desired_description"], changed=None
    )
    return json.dumps(data)


def test_accepted_success_with_false_provider_metadata_remains_parseable(
    accepted_success_reconstruction,
):
    record = ProfiledChangeRecord.model_validate_json(accepted_success_reconstruction)
    assert record.final_outcome.value == "SUCCEEDED"
    assert record.execution.changed is False
    assert record.post_validation.changed is None
    assert record.previous_description != record.post_validation.observed_description
