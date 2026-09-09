"""Fresh whole-population read-only admission; never executes a child plan."""

import json
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from network_change_delivery.architecture_contracts import (
    NetBoxInterfaceIdentity,
    Sha256Digest,
)
from network_change_delivery.profiled_planning import (
    ProfiledDeploymentPlan,
    _validate_credential_reference,
    plan_profiled_change,
)
from network_change_delivery.profiled_promotion import digest_bytes
from network_change_delivery.profiled_rollout import (
    MAX_MEMBERS,
    DeviceIdentity,
    ProfiledRolloutSelectionIntent,
    _admit_rollout_members,
    _ResolvedInventory,
    read_profiled_rollout,
)
from network_change_delivery.profiled_rollout_authorization import (
    ProfiledRolloutAuthorization,
    authorize_rollout,
)
from network_change_delivery.secrets import DeviceCredentials


def execution_basis(result):
    """All child execution semantics except observation time and its self-digest."""
    return result.model_dump(
        mode="json", exclude={"digest", "created_at", "observed_at"}
    )


class RolloutPreflightChild(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    device_identity: DeviceIdentity
    interface_identity: NetBoxInterfaceIdentity
    kind: Literal["DEPLOYABLE", "COMPLIANT"]
    approved_artifact_digest: Sha256Digest
    approved_result_digest: Sha256Digest
    execution_basis_digest: Sha256Digest
    observed_at: AwareDatetime


class ProfiledRolloutPreflight(BaseModel):
    """Positive fresh evidence; not promotion, authorization or execution permission."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal["1"] = "1"
    record_type: Literal["profiled_rollout_preflight"] = "profiled_rollout_preflight"
    outcome: Literal["PASSED"] = "PASSED"
    execution_attempted: Literal[False] = False
    parent_digest: Sha256Digest
    promotion_digest: Sha256Digest
    authorization_digest: Sha256Digest
    children: tuple[RolloutPreflightChild, ...] = Field(
        min_length=1, max_length=MAX_MEMBERS
    )
    digest: Sha256Digest

    def calculated_digest(self):
        return digest_bytes(
            json.dumps(
                self.model_dump(mode="json", exclude={"digest"}),
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        )

    @model_validator(mode="after")
    def verified(self):
        devices = [child.device_identity for child in self.children]
        interfaces = [child.interface_identity for child in self.children]
        if (
            len(set(devices)) != len(devices)
            or len(set(interfaces)) != len(interfaces)
            or not any(child.kind == "DEPLOYABLE" for child in self.children)
            or self.digest != self.calculated_digest()
        ):
            raise ValueError("rollout preflight binding rejected")
        return self


class _LoadedSecret:
    """Reuse a caller-owned credential loaded during complete availability checks."""

    def __init__(self, device, reference, credentials):
        if (
            not isinstance(credentials, DeviceCredentials)
            or not credentials.username
            or not credentials.password
        ):
            raise ValueError("rollout credential availability rejected")
        self.device, self._reference, self._credentials = device, reference, credentials

    def reference(self, device):
        if device != self.device:
            raise ValueError("preflight credential target changed")
        return self._reference

    def load(self, device):
        if device != self.device:
            raise ValueError("preflight credential target changed")
        return self._credentials


def preflight_profiled_rollout(
    context,
    parent_bytes,
    publication,
    promotion_bytes,
    authorization: ProfiledRolloutAuthorization,
    receipts,
    batfish,
    cml,
    *,
    intent,
    inventory,
    credential_authority,
    secrets,
    collector,
) -> ProfiledRolloutPreflight:
    """Revalidate frozen approval before any provider; admit/load all before observe.

    No lock is acquired here. Future execution must reserve all selected devices
    after human authorization, retain child JIT validation, and pass each original
    child.artifact_bytes() forward without reserializing it.
    """
    authorization = ProfiledRolloutAuthorization.model_validate(
        authorization.model_dump()
    )
    expected = authorize_rollout(
        context,
        parent_bytes,
        publication,
        promotion_bytes,
        receipts,
        batfish,
        cml,
        authorization.promotion_digest,
        authorization.promotion_artifact_digest,
        authorization.unblocker_id,
        intent=intent,
    )
    if authorization != expected:
        raise ValueError("preflight authorization disagrees with approved inputs")
    parent = read_profiled_rollout(parent_bytes)
    population, expansion, _, admitted = _admit_rollout_members(
        intent,
        inventory,
        credential_authority,
        expected_targets=tuple(child.device.logical_name for child in parent.children),
    )
    if isinstance(parent.intent, ProfiledRolloutSelectionIntent):
        if expansion != parent.expansion:
            raise ValueError("stale rollout expansion/order")
        selected = {child.device.device_identity for child in parent.children}
        if (
            tuple(
                m
                for m in population.declaration.members
                if m.device_identity in selected
            )
            != parent.selected_population.members
        ):
            raise ValueError("stale rollout selected declaration")
    if len(admitted) != len(parent.children):
        raise ValueError("stale rollout membership")
    for child, (_, device, interface, operation, decision) in zip(
        parent.children, admitted, strict=True
    ):
        if (
            device != child.device
            or interface != child.interface
            or operation != child.operation_admission
            or decision != child.credential_admission
        ):
            raise ValueError(
                "stale rollout identity/profile/operation/credential basis"
            )

    # Resolve every exact reference, then load every credential, before collection.
    references = []
    for child, (_, device, _, _, _) in zip(parent.children, admitted, strict=True):
        reference = _validate_credential_reference(device, secrets.reference(device))
        if reference.reference != child.credential_admission.credential_reference:
            raise ValueError("stale rollout credential reference")
        references.append(reference)
    loaded = []
    try:
        for (_, device, _, _, _), reference in zip(admitted, references, strict=True):
            loaded.append(_LoadedSecret(device, reference, secrets.load(device)))
        observed = []
        for child, (member, device, interface, _, _), credentials in zip(
            parent.children, admitted, loaded, strict=True
        ):
            fresh = plan_profiled_change(
                member.child_intent(parent.intent.change_id),
                _ResolvedInventory(device, interface),
                credentials,
                collector,
                created_at=None,
            )
            if (fresh.plan is None) == (fresh.compliance is None):
                raise ValueError("preflight child result is ambiguous")
            result = fresh.plan if fresh.plan is not None else fresh.compliance
            approved = child.result()
            if type(result) is not type(approved):
                raise ValueError("stale rollout child classification")
            result = type(result).model_validate(result.model_dump())
            if execution_basis(result) != execution_basis(approved):
                raise ValueError("stale rollout child execution basis/classification")
            observed.append(
                RolloutPreflightChild(
                    device_identity=device.device_identity,
                    interface_identity=interface.interface,
                    kind=child.kind,
                    approved_artifact_digest=child.artifact_digest,
                    approved_result_digest=child.result_digest,
                    execution_basis_digest=digest_bytes(
                        json.dumps(
                            execution_basis(result),
                            sort_keys=True,
                            separators=(",", ":"),
                        ).encode()
                    ),
                    observed_at=result.created_at
                    if isinstance(result, ProfiledDeploymentPlan)
                    else result.observed_at,
                )
            )
    finally:
        loaded.clear()
    values = {
        "parent_digest": parent.digest,
        "promotion_digest": authorization.promotion_digest,
        "authorization_digest": authorization.digest,
        "children": tuple(observed),
    }
    unsigned = ProfiledRolloutPreflight.model_construct(**values)
    return ProfiledRolloutPreflight(**values, digest=unsigned.calculated_digest())
