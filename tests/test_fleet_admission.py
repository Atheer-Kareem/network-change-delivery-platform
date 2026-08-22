"""Process-local stable-device fleet admission tests."""

from __future__ import annotations

from threading import Event, Thread

import pytest
from test_fleet import (
    DESIRED,
    FleetCollector,
    FleetInventory,
    FleetSecrets,
    make_plan,
    selected_four,
)
from test_fleet_execution import PhaseCollector, RecordingDeployer

from network_change_delivery.fleet import ProcessLocalFleetAdmission, deploy_fleet
from network_change_delivery.models import FinalOutcome, FleetFinalOutcome


def identities(plan) -> tuple[str, ...]:
    return tuple(member.inventory_object_id for member in plan.members)


class ContactInventory(FleetInventory):
    def __init__(self) -> None:
        super().__init__(selected_four())
        self.contacts = 0

    def resolve_fleet(self, selector):
        self.contacts += 1
        return super().resolve_fleet(selector)

    def resolve(self, target, interface=None):
        self.contacts += 1
        return super().resolve(target, interface)


def test_conflicting_rollout_blocks_before_any_provider_or_child_contact() -> None:
    plan = make_plan().plan
    assert plan is not None
    controller = ProcessLocalFleetAdmission()
    entered = Event()
    finish = Event()
    first_result = []

    class HoldingDeployer(RecordingDeployer):
        def __call__(self, *args, **kwargs):
            entered.set()
            assert finish.wait(timeout=5)
            return super().__call__(*args, **kwargs)

    def first_rollout() -> None:
        first_result.append(
            deploy_fleet(
                plan,
                plan.digest,
                FleetInventory(selected_four()),
                FleetSecrets(),
                PhaseCollector(
                    {item[0].name: "old" for item in selected_four()},
                    len(plan.members),
                ),
                object(),
                child_deployer=HoldingDeployer(),
                admission=controller,
            )
        )

    thread = Thread(target=first_rollout)
    thread.start()
    assert entered.wait(timeout=5)
    inventory = ContactInventory()
    secrets = FleetSecrets()
    collector = FleetCollector({})
    deployer = RecordingDeployer()
    blocked = deploy_fleet(
        plan,
        plan.digest,
        inventory,
        secrets,
        collector,
        object(),
        child_deployer=deployer,
        admission=controller,
    )
    assert blocked.final_outcome is FleetFinalOutcome.BLOCKED
    assert blocked.preflight.message == "process-local fleet target admission blocked"
    assert inventory.contacts == 0
    assert secrets.loads == 0
    assert collector.calls == []
    assert deployer.calls == []
    finish.set()
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert first_result[0].final_outcome is FleetFinalOutcome.SUCCEEDED


def test_device_identity_conflicts_across_interfaces_and_compliant_members() -> None:
    plan = make_plan(
        {
            **{item[0].name: "old" for item in selected_four()},
            "router-13": DESIRED,
        }
    ).plan
    assert plan is not None
    compliant = next(
        member for member in plan.members if member.current_description == DESIRED
    )
    controller = ProcessLocalFleetAdmission()
    lease = controller.acquire((compliant.inventory_object_id,))
    assert lease is not None
    try:
        blocked = deploy_fleet(
            plan,
            plan.digest,
            ContactInventory(),
            FleetSecrets(),
            FleetCollector({}),
            object(),
            child_deployer=RecordingDeployer(),
            admission=controller,
        )
        assert blocked.final_outcome is FleetFinalOutcome.BLOCKED
    finally:
        lease.release()
        lease.release()
    first = controller.acquire(("netbox:dcim.device:900",))
    assert first is not None
    assert controller.acquire(("netbox:dcim.device:900",)) is None
    first.release()


def test_disjoint_device_sets_are_admitted_independently() -> None:
    controller = ProcessLocalFleetAdmission()
    first = controller.acquire(("netbox:dcim.device:1", "netbox:dcim.device:2"))
    second = controller.acquire(("netbox:dcim.device:3",))
    assert first is not None
    assert second is not None
    first.release()
    second.release()


@pytest.mark.parametrize(
    ("case", "expected"),
    [
        ("succeeded", FleetFinalOutcome.SUCCEEDED),
        ("blocked", FleetFinalOutcome.BLOCKED),
        ("stopped", FleetFinalOutcome.STOPPED),
        ("partial", FleetFinalOutcome.PARTIAL),
        ("final_validation", FleetFinalOutcome.FINAL_VALIDATION_FAILED),
    ],
)
def test_lease_releases_after_every_typed_exit(
    case: str, expected: FleetFinalOutcome
) -> None:
    plan = make_plan().plan
    assert plan is not None
    descriptions = {item[0].name: "old" for item in selected_four()}
    outcomes = None
    collector = PhaseCollector(descriptions, len(plan.members))
    if case == "blocked":
        descriptions["router-13"] = "changed-after-approval"
        collector = FleetCollector(descriptions)
    elif case == "stopped":
        outcomes = {"router-10": FinalOutcome.AMBIGUOUS}
    elif case == "partial":
        outcomes = {"router-11": FinalOutcome.RECOVERED}
    elif case == "final_validation":

        class DriftCollector(PhaseCollector):
            def collect(self, device, credentials, interface):
                state = super().collect(device, credentials, interface)
                if len(self.calls) > self.member_count and device.name == "router-13":
                    return state.model_copy(update={"description": "drifted"})
                return state

        collector = DriftCollector(descriptions, len(plan.members))
    controller = ProcessLocalFleetAdmission()
    result = deploy_fleet(
        plan,
        plan.digest,
        FleetInventory(selected_four()),
        FleetSecrets(),
        collector,
        object(),
        child_deployer=RecordingDeployer(outcomes),
        admission=controller,
    )
    assert result.final_outcome is expected
    subsequent = controller.acquire(identities(plan))
    assert subsequent is not None
    subsequent.release()


def test_lease_releases_when_unexpected_child_exception_escapes() -> None:
    plan = make_plan().plan
    assert plan is not None
    controller = ProcessLocalFleetAdmission()

    def unexpected(*_args, **_kwargs):
        raise LookupError("injected unexpected failure")

    with pytest.raises(LookupError, match="injected unexpected failure"):
        deploy_fleet(
            plan,
            plan.digest,
            FleetInventory(selected_four()),
            FleetSecrets(),
            FleetCollector({item[0].name: "old" for item in selected_four()}),
            object(),
            child_deployer=unexpected,
            admission=controller,
        )
    subsequent = controller.acquire(identities(plan))
    assert subsequent is not None
    subsequent.release()
