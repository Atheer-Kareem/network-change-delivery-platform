"""Independent complete-population D1 validation, without a writer."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from network_change_delivery.architecture_contracts import Sha256Digest
from network_change_delivery.audit import canonical_json_bytes, sha256_identity
from network_change_delivery.profiled_configuration_observation import _signed
from network_change_delivery.profiled_planning import (
    ProfiledComplianceRecord,
    _validate_credential_reference,
    plan_profiled_change,
)
from network_change_delivery.profiled_rollout import (
    MAX_MEMBERS,
    DeviceIdentity,
    _admit_rollout_members,
    _ResolvedInventory,
)
from network_change_delivery.profiled_rollout_preflight import _LoadedSecret


class ProfiledRolloutFinalValidation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal["1"] = "1"
    record_type: Literal["profiled_rollout_final_validation"] = (
        "profiled_rollout_final_validation"
    )
    parent_digest: Sha256Digest
    authorization_digest: Sha256Digest
    preflight_digest: Sha256Digest
    selected_devices: tuple[DeviceIdentity, ...] = Field(
        min_length=1, max_length=MAX_MEMBERS
    )
    observations: tuple[ProfiledComplianceRecord, ...] = Field(max_length=MAX_MEMBERS)
    status: Literal["PASSED", "FAILED"]
    failure: Literal["ADMISSION", "CREDENTIAL", "OBSERVATION", "D1_MISMATCH"] | None
    digest: Sha256Digest

    def calculated_digest(self):
        return sha256_identity(
            canonical_json_bytes(self.model_dump(mode="json", exclude={"digest"}))
        )

    @model_validator(mode="after")
    def consistent(self):
        observed = tuple(o.device_identity for o in self.observations)
        if (
            len(set(self.selected_devices)) != len(self.selected_devices)
            or observed != self.selected_devices[: len(observed)]
            or self.digest != self.calculated_digest()
            or (
                self.status == "PASSED"
                and (self.failure is not None or observed != self.selected_devices)
            )
            or (self.status == "FAILED" and self.failure is None)
        ):
            raise ValueError("rollout final validation binding rejected")
        return self


def validate_rollout_final_state(
    parent,
    authorization,
    preflight,
    *,
    intent,
    inventory,
    credential_authority,
    secrets,
    collector,
):
    """Re-admit all identities/load all credentials, then positively observe D1.

    The existing child planner owns hostname/interface safety and observation time.
    A positive compliance artifact proves D1; absent artifacts never do.
    """
    observations, loaded = [], []
    phase, failure = "ADMISSION", None
    try:
        if (
            authorization.parent_digest != parent.digest
            or preflight.parent_digest != parent.digest
            or preflight.authorization_digest != authorization.digest
        ):
            raise ValueError("final validation approval binding rejected")
        population, expansion, _, admitted = _admit_rollout_members(
            intent,
            inventory,
            credential_authority,
            expected_targets=tuple(c.device.logical_name for c in parent.children),
        )
        if hasattr(parent, "expansion") and (
            expansion != parent.expansion
            or tuple(
                m
                for m in population.declaration.members
                if m.device_identity in authorization.selected_devices
            )
            != parent.selected_population.members
        ):
            raise ValueError("final population expansion changed")
        if len(admitted) != len(parent.children):
            raise ValueError("final membership changed")
        for child, (_, device, interface, operation, decision) in zip(
            parent.children, admitted, strict=True
        ):
            if (
                device != child.device
                or interface != child.interface
                or operation != child.operation_admission
                or decision != child.credential_admission
            ):
                raise ValueError("final identity/admission changed")
        phase = "CREDENTIAL"
        references = []
        for child, (_, device, _, _, _) in zip(parent.children, admitted, strict=True):
            ref = _validate_credential_reference(device, secrets.reference(device))
            if ref.reference != child.credential_admission.credential_reference:
                raise ValueError("final credential reference changed")
            references.append(ref)
        for (_, device, _, _, _), ref in zip(admitted, references, strict=True):
            loaded.append(_LoadedSecret(device, ref, secrets.load(device)))
        phase = "OBSERVATION"
        for child, (member, device, interface, _, _), credential in zip(
            parent.children, admitted, loaded, strict=True
        ):
            result = plan_profiled_change(
                member.child_intent(parent.intent.change_id),
                _ResolvedInventory(device, interface),
                credential,
                collector,
            )
            if result.plan is not None or not isinstance(
                result.compliance, ProfiledComplianceRecord
            ):
                phase = "D1_MISMATCH"
                raise ValueError("final D1 not proved")
            observed = ProfiledComplianceRecord.model_validate(
                result.compliance.model_dump()
            )
            # The independent intent must still supply the approved desired state.
            if observed.desired_description != child.result().desired_description:
                phase = "D1_MISMATCH"
                raise ValueError("final desired state changed")
            observations.append(observed)
    except Exception:
        failure = phase
    finally:
        loaded.clear()
    return _signed(
        ProfiledRolloutFinalValidation,
        {
            "parent_digest": parent.digest,
            "authorization_digest": authorization.digest,
            "preflight_digest": preflight.digest,
            "selected_devices": tuple(
                c.device.device_identity for c in parent.children
            ),
            "observations": tuple(observations),
            "status": "FAILED" if failure else "PASSED",
            "failure": failure,
        },
    )
