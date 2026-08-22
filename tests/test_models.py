"""Tests for typed intent and immutable planning contracts."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from network_change_delivery.models import (
    CiscoConfigArtifact,
    DesiredDescription,
    InterfaceDescriptionIntent,
    InterfaceState,
    InventoryDevice,
)
from network_change_delivery.workflow import SafetyError, build_plan


def intent(description: str = "managed-by-ncdp") -> InterfaceDescriptionIntent:
    """Build a valid interface-description intent."""
    return InterfaceDescriptionIntent(
        change_id="CHG-001",
        kind="interface_description",
        target="router-1",
        interface="GigabitEthernet2",
        desired=DesiredDescription(description=description),
    )


def device(*, protected: tuple[str, ...] = ()) -> InventoryDevice:
    """Build a supported inventory device."""
    return InventoryDevice(
        name="router-1",
        host="192.0.2.10",
        platform="cisco_iosxe",
        expected_hostname="lab-router",
        protected_interfaces=protected,
    )


def state(
    *,
    interface: str = "GigabitEthernet2",
    hostname: str = "lab-router",
    exists: bool = True,
    description: str | None = "old",
    protected: bool = False,
) -> InterfaceState:
    """Build normalized interface state."""
    return InterfaceState(
        observed_hostname=hostname,
        interface=interface,
        exists=exists,
        description=description,
        protected=protected,
    )


def test_valid_change_parsing() -> None:
    assert intent().kind == "interface_description"


@pytest.mark.parametrize("description", ["", "   "])
def test_empty_description_rejected(description: str) -> None:
    with pytest.raises(ValidationError):
        intent(description)


def test_description_over_240_characters_rejected() -> None:
    with pytest.raises(ValidationError):
        intent("x" * 241)


@pytest.mark.parametrize("description", ["line\nbreak", "line\rbreak", "bad\x00value"])
def test_control_characters_rejected(description: str) -> None:
    with pytest.raises(ValidationError):
        intent(description)


def test_protected_interface_rejected() -> None:
    with pytest.raises(SafetyError, match="protected"):
        build_plan(intent(), device(protected=("GigabitEthernet2",)), state())


def test_management_interface_rejected() -> None:
    change = intent().model_copy(update={"interface": "GigabitEthernet1"})
    with pytest.raises(SafetyError, match="GigabitEthernet1"):
        build_plan(change, device(), state(interface="GigabitEthernet1"))


def test_hostname_identity_mismatch_rejected() -> None:
    with pytest.raises(SafetyError, match="hostname"):
        build_plan(intent(), device(), state(hostname="unexpected"))


def test_missing_interface_rejected() -> None:
    with pytest.raises(SafetyError, match="does not exist"):
        build_plan(intent(), device(), state(exists=False))


def test_interface_identity_mismatch_rejected() -> None:
    with pytest.raises(SafetyError, match="observed interface"):
        build_plan(intent(), device(), state(interface="GigabitEthernet3"))


def test_plan_digest_is_deterministic() -> None:
    created = datetime(2026, 8, 22, tzinfo=UTC)
    first = build_plan(intent(), device(), state(), created_at=created)
    second = build_plan(intent(), device(), state(), created_at=created)
    assert first.digest == second.digest
    assert first.verify_digest()


def test_digest_changes_with_artifact_or_precondition() -> None:
    plan = build_plan(
        intent(),
        device(),
        state(),
        created_at=datetime(2026, 8, 22, tzinfo=UTC),
    )
    changed_artifact = plan.model_copy(
        update={
            "execution_artifact": CiscoConfigArtifact(
                parent=plan.execution_artifact.parent,
                lines=("description changed",),
            )
        }
    )
    changed_precondition = plan.model_copy(
        update={
            "preconditions": plan.preconditions.model_copy(
                update={"current_description": "different"}
            )
        }
    )
    assert changed_artifact.calculated_digest() != plan.digest
    assert changed_precondition.calculated_digest() != plan.digest


@pytest.mark.parametrize(
    "changes",
    [
        {"inventory_source": "netbox"},
        {"inventory_object_id": "netbox:dcim.device:42"},
        {"inventory_interface_object_id": "netbox:dcim.interface:100"},
    ],
)
def test_digest_covers_inventory_provenance(changes: dict[str, object]) -> None:
    approved = build_plan(intent(), device(), state())
    changed = approved.model_copy(update=changes)
    assert changed.calculated_digest() != approved.digest


def test_netbox_interface_identity_is_frozen_into_plan_and_digest() -> None:
    netbox_device = device().model_copy(
        update={
            "inventory_source": "netbox",
            "inventory_object_id": "netbox:dcim.device:42",
            "inventory_interface_object_id": "netbox:dcim.interface:100",
        }
    )
    approved = build_plan(intent(), netbox_device, state())
    assert approved.inventory_interface_object_id == "netbox:dcim.interface:100"
    changed = approved.model_copy(
        update={"inventory_interface_object_id": "netbox:dcim.interface:101"}
    )
    assert changed.calculated_digest() != approved.digest


def test_preview_is_derived_from_exact_artifact() -> None:
    plan = build_plan(intent(), device(), state())
    assert plan.execution_artifact.cli_preview() == (
        "interface GigabitEthernet2\n description managed-by-ncdp"
    )


def test_loaded_plan_cannot_encode_control_bearing_commands() -> None:
    plan = build_plan(intent(), device(), state())
    payload = plan.model_dump(mode="json")
    payload["desired_description"] = "unsafe\ncommand"
    payload["execution_artifact"]["lines"] = ["description unsafe\ncommand"]
    with pytest.raises(ValidationError):
        type(plan).model_validate(payload)


def test_change_intent_rejects_commands_field() -> None:
    payload = intent().model_dump(mode="json")
    payload["commands"] = ["show version"]
    with pytest.raises(ValidationError):
        InterfaceDescriptionIntent.model_validate(payload)


@pytest.mark.parametrize("field", ["change_id", "target", "interface"])
def test_cli_bound_identifiers_reject_control_characters(field: str) -> None:
    payload = intent().model_dump(mode="json")
    payload[field] = "safe\nconfigure terminal"
    with pytest.raises(ValidationError):
        InterfaceDescriptionIntent.model_validate(payload)


def test_unknown_plan_field_is_rejected() -> None:
    approved = build_plan(intent(), device(), state())
    payload = approved.model_dump(mode="json")
    payload["outside_digest"] = "unbound"
    with pytest.raises(ValidationError):
        type(approved).model_validate(payload)


@pytest.mark.parametrize("description", ["unsafe\ncommand", "x" * 241])
def test_unsafe_observed_description_cannot_form_recovery(
    description: str,
) -> None:
    with pytest.raises(SafetyError, match="unsafe for targeted recovery"):
        build_plan(intent(), device(), state(description=description))
