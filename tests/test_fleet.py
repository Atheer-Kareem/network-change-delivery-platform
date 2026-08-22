"""Safety-focused fleet planning and complete read-only preflight tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from network_change_delivery.fleet import plan_fleet, preflight_fleet
from network_change_delivery.models import (
    DesiredDescription,
    FleetDeploymentPlan,
    FleetInterfaceDescriptionIntent,
    FleetMemberClassification,
    FleetRolloutPolicy,
    InterfaceState,
    InventoryDevice,
    NetBoxFleetSelector,
)
from network_change_delivery.secrets import CredentialReference, DeviceCredentials

CREATED = datetime(2026, 8, 23, tzinfo=UTC)
DESIRED = "managed-by-network-change-delivery-platform"


def fleet_intent(*, wave_size: int = 2) -> FleetInterfaceDescriptionIntent:
    return FleetInterfaceDescriptionIntent(
        change_id="CHG-FLEET-001",
        kind="interface_description",
        selector=NetBoxFleetSelector(
            device_tag="fleet-edge", interface_tag="fleet-uplink"
        ),
        desired=DesiredDescription(description=DESIRED),
        rollout=FleetRolloutPolicy(wave_size=wave_size),
    )


def device(
    object_id: int,
    platform: str,
    *,
    host: str | None = None,
    interface_id: int | None = None,
) -> tuple[InventoryDevice, str]:
    target = f"router-{object_id}"
    interface = "GigabitEthernet2" if platform == "cisco_iosxe" else "ge-0/0/1"
    return (
        InventoryDevice(
            name=target,
            host=host or f"192.0.2.{object_id}",
            port=22 if platform == "cisco_iosxe" else 830,
            platform=platform,
            expected_hostname=target,
            inventory_source="netbox",
            inventory_object_id=f"netbox:dcim.device:{object_id}",
            inventory_interface_object_id=(
                f"netbox:dcim.interface:{interface_id or object_id + 100}"
            ),
        ),
        interface,
    )


class FleetInventory:
    def __init__(
        self,
        selected: tuple[tuple[InventoryDevice, str], ...],
        *,
        resolved: dict[str, InventoryDevice] | None = None,
    ) -> None:
        self.selected = selected
        self.resolved = resolved or {item[0].name: item[0] for item in selected}

    def resolve_fleet(
        self, _selector: NetBoxFleetSelector
    ) -> tuple[tuple[InventoryDevice, str], ...]:
        return self.selected

    def resolve(self, target: str, interface: str | None = None) -> InventoryDevice:
        assert interface is not None
        return self.resolved[target]


class FleetSecrets:
    def __init__(self, *, drift_target: str | None = None) -> None:
        self.drift_target = drift_target
        self.loads = 0

    def reference(self, device: InventoryDevice) -> CredentialReference:
        reference = f"openbao:kv-v2:ncdp/devices/{device.inventory_object_id}/ssh"
        if device.name == self.drift_target:
            reference += "-changed"
        return CredentialReference("openbao", reference)

    def load(self, _device: InventoryDevice) -> DeviceCredentials:
        self.loads += 1
        return DeviceCredentials(username="fleet-test-user", password="fleet-secret")


class FleetCollector:
    def __init__(
        self,
        descriptions: dict[str, str | None],
        *,
        overrides: dict[str, InterfaceState] | None = None,
    ) -> None:
        self.descriptions = descriptions
        self.overrides = overrides or {}
        self.calls: list[str] = []

    def collect(
        self,
        device: InventoryDevice,
        _credentials: DeviceCredentials,
        interface: str,
    ) -> InterfaceState:
        self.calls.append(device.name)
        if device.name in self.overrides:
            return self.overrides[device.name]
        return InterfaceState(
            observed_hostname=device.expected_hostname,
            interface=interface,
            exists=True,
            description=self.descriptions[device.name],
            protected=False,
        )


def selected_four() -> tuple[tuple[InventoryDevice, str], ...]:
    return (
        device(13, "junos"),
        device(10, "cisco_iosxe"),
        device(12, "cisco_iosxe"),
        device(11, "junos"),
    )


def make_plan(descriptions: dict[str, str | None] | None = None, *, wave_size: int = 2):
    selected = selected_four()
    descriptions = descriptions or {item[0].name: "old" for item in selected}
    return plan_fleet(
        fleet_intent(wave_size=wave_size),
        FleetInventory(selected),
        FleetSecrets(),
        FleetCollector(descriptions),
        created_at=CREATED,
    )


def test_mixed_vendor_planning_freezes_valid_child_plans() -> None:
    result = make_plan()
    assert result.plan is not None
    assert [member.inventory_object_id for member in result.members] == [
        "netbox:dcim.device:10",
        "netbox:dcim.device:11",
        "netbox:dcim.device:12",
        "netbox:dcim.device:13",
    ]
    assert {member.platform for member in result.members} == {"cisco_iosxe", "junos"}
    assert all(
        member.child_plan is not None and member.child_plan.verify_digest()
        for member in result.members
    )
    assert result.plan.verify_digest()


def test_deterministic_representative_canaries_and_waves_ignore_api_order() -> None:
    first = make_plan().plan
    selected = tuple(reversed(selected_four()))
    second = plan_fleet(
        fleet_intent(),
        FleetInventory(selected),
        FleetSecrets(),
        FleetCollector({item[0].name: "old" for item in selected}),
        created_at=CREATED,
    ).plan
    assert first is not None and second is not None
    assert first.canaries == (
        "netbox:dcim.device:10",
        "netbox:dcim.device:11",
    )
    assert first.waves == (("netbox:dcim.device:12", "netbox:dcim.device:13"),)
    assert first.canaries == second.canaries
    assert first.waves == second.waves
    assert first.digest == second.digest


def test_cohorts_are_disjoint_and_cover_each_deployable_once() -> None:
    plan = make_plan(wave_size=1).plan
    assert plan is not None
    cohort_ids = [*plan.canaries, *(item for wave in plan.waves for item in wave)]
    deployable = [
        member.inventory_object_id
        for member in plan.members
        if member.classification is FleetMemberClassification.DEPLOYABLE
    ]
    assert len(cohort_ids) == len(set(cohort_ids))
    assert set(cohort_ids) == set(deployable)
    assert all(len(wave) == 1 for wave in plan.waves)


def test_partial_compliance_is_frozen_but_excluded_from_cohorts() -> None:
    descriptions = {item[0].name: "old" for item in selected_four()}
    descriptions["router-10"] = DESIRED
    plan = make_plan(descriptions).plan
    assert plan is not None
    compliant = plan.members[0]
    assert compliant.classification is FleetMemberClassification.COMPLIANT
    assert compliant.child_plan is None
    assert compliant.inventory_object_id not in plan.canaries
    assert all(compliant.inventory_object_id not in wave for wave in plan.waves)
    assert plan.canaries == (
        "netbox:dcim.device:12",
        "netbox:dcim.device:11",
    )


def test_platform_with_only_compliant_members_requires_no_canary() -> None:
    descriptions = {
        item[0].name: (DESIRED if item[0].platform == "junos" else "old")
        for item in selected_four()
    }
    plan = make_plan(descriptions).plan
    assert plan is not None
    assert plan.canaries == ("netbox:dcim.device:10",)


def test_all_compliant_fleet_has_observations_but_no_artifact() -> None:
    result = make_plan({item[0].name: DESIRED for item in selected_four()})
    assert result.plan is None
    assert len(result.members) == 4
    assert all(
        member.classification is FleetMemberClassification.COMPLIANT
        and member.child_plan is None
        for member in result.members
    )
    assert result.message == (
        "fleet is already compliant; no deployable artifact produced"
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "membership",
        "device_id",
        "child",
        "canary",
        "wave_order",
        "rollout",
    ],
)
def test_fleet_digest_transitively_binds_full_plan(mutation: str) -> None:
    plan = make_plan().plan
    assert plan is not None
    if mutation == "membership":
        changed = plan.model_copy(update={"members": plan.members[:-1]})
    elif mutation == "device_id":
        member = plan.members[0].model_copy(
            update={"inventory_object_id": "netbox:dcim.device:999"}
        )
        changed = plan.model_copy(update={"members": (member, *plan.members[1:])})
    elif mutation == "child":
        member = plan.members[0]
        assert member.child_plan is not None
        child = member.child_plan.model_copy(update={"current_description": "changed"})
        changed_member = member.model_copy(update={"child_plan": child})
        changed = plan.model_copy(
            update={"members": (changed_member, *plan.members[1:])}
        )
    elif mutation == "canary":
        changed = plan.model_copy(update={"canaries": tuple(reversed(plan.canaries))})
    elif mutation == "wave_order":
        changed = plan.model_copy(update={"waves": (tuple(reversed(plan.waves[0])),)})
    else:
        changed = plan.model_copy(update={"rollout": FleetRolloutPolicy(wave_size=1)})
    assert changed.calculated_digest() != plan.digest


def test_loaded_plan_rejects_duplicate_identity_and_invalid_cohorts() -> None:
    plan = make_plan().plan
    assert plan is not None
    payload = plan.model_dump(mode="json")
    payload["members"][1] = payload["members"][0]
    with pytest.raises(ValidationError, match="must be unique"):
        FleetDeploymentPlan.model_validate(payload)

    payload = plan.model_dump(mode="json")
    payload["waves"][0].append(payload["canaries"][0])
    with pytest.raises(ValidationError, match="multiple cohorts"):
        FleetDeploymentPlan.model_validate(payload)

    payload = plan.model_dump(mode="json")
    payload["waves"][0].reverse()
    with pytest.raises(ValidationError, match="wave order"):
        FleetDeploymentPlan.model_validate(payload)

    payload = plan.model_dump(mode="json")
    payload["rollout"]["wave_size"] = 1
    with pytest.raises(ValidationError, match="wave size"):
        FleetDeploymentPlan.model_validate(payload)


def test_complete_fleet_preflight_succeeds_for_deployable_and_compliant() -> None:
    descriptions = {item[0].name: "old" for item in selected_four()}
    descriptions["router-13"] = DESIRED
    plan = make_plan(descriptions).plan
    assert plan is not None
    result = preflight_fleet(
        plan,
        FleetInventory(selected_four()),
        FleetSecrets(),
        FleetCollector(descriptions),
        approval_digest=plan.digest,
    )
    assert result.succeeded
    assert len(result.members) == 4
    assert all(member.succeeded for member in result.members)


def test_selector_membership_drift_blocks_before_credential_load() -> None:
    plan = make_plan().plan
    assert plan is not None
    secrets = FleetSecrets()
    result = preflight_fleet(
        plan,
        FleetInventory(selected_four()[:-1]),
        secrets,
        FleetCollector({}),
    )
    assert not result.succeeded
    assert "membership" in result.message
    assert secrets.loads == 0


@pytest.mark.parametrize("drift", ["endpoint", "platform", "credential"])
def test_binding_drift_blocks_complete_preflight(drift: str) -> None:
    plan = make_plan().plan
    assert plan is not None
    selected = selected_four()
    resolved = {item[0].name: item[0] for item in selected}
    target = "router-13"
    if drift == "endpoint":
        resolved[target] = resolved[target].model_copy(update={"host": "192.0.2.250"})
    elif drift == "platform":
        resolved[target] = resolved[target].model_copy(
            update={"platform": "cisco_iosxe", "port": 22}
        )
    secrets = FleetSecrets(drift_target=target if drift == "credential" else None)
    descriptions = {item[0].name: "old" for item in selected}
    result = preflight_fleet(
        plan,
        FleetInventory(selected, resolved=resolved),
        secrets,
        FleetCollector(descriptions),
    )
    assert not result.succeeded
    failed = next(member for member in result.members if member.target == target)
    assert not failed.succeeded


def test_final_member_precondition_drift_has_no_execution_boundary() -> None:
    plan = make_plan().plan
    assert plan is not None
    descriptions = {item[0].name: "old" for item in selected_four()}
    descriptions["router-13"] = "changed-after-approval"
    collector = FleetCollector(descriptions)
    result = preflight_fleet(
        plan,
        FleetInventory(selected_four()),
        FleetSecrets(),
        collector,
    )
    assert not result.succeeded
    assert collector.calls == ["router-10", "router-11", "router-12", "router-13"]
    assert result.members[-1].message == "approved child preconditions have changed"
    assert "executor" not in preflight_fleet.__annotations__


def test_compliant_member_becoming_noncompliant_blocks() -> None:
    descriptions = {item[0].name: "old" for item in selected_four()}
    descriptions["router-13"] = DESIRED
    plan = make_plan(descriptions).plan
    assert plan is not None
    descriptions["router-13"] = "drifted"
    result = preflight_fleet(
        plan,
        FleetInventory(selected_four()),
        FleetSecrets(),
        FleetCollector(descriptions),
    )
    assert not result.succeeded
    failed = next(member for member in result.members if member.target == "router-13")
    assert failed.message == "compliant member is no longer compliant"


def test_preflight_errors_and_evidence_are_secret_safe() -> None:
    plan = make_plan().plan
    assert plan is not None

    class SecretFailureCollector(FleetCollector):
        def collect(
            self,
            device: InventoryDevice,
            credentials: DeviceCredentials,
            interface: str,
        ) -> InterfaceState:
            if device.name == "router-13":
                raise RuntimeError("fleet-secret raw provider detail")
            return super().collect(device, credentials, interface)

    result = preflight_fleet(
        plan,
        FleetInventory(selected_four()),
        FleetSecrets(),
        SecretFailureCollector({item[0].name: "old" for item in selected_four()}),
    )
    serialized = result.model_dump_json()
    assert not result.succeeded
    assert "fleet-secret" not in serialized
    assert "fleet-test-user" not in serialized
