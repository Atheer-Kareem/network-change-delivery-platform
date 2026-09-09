"""Offline authorization and fresh preflight; every execution boundary is trapped."""

import ast
import inspect
from dataclasses import replace
from types import SimpleNamespace

import pytest
from profiled_population_fixtures import declared_population
from test_profiled_planning import FakeSecrets
from test_profiled_rollout import COMMIT, NOW, Collector, Inventory, intent_for, rehash
from test_profiled_rollout_delivery import no_execution  # noqa: F401

from network_change_delivery import profiled_planning
from network_change_delivery import profiled_rollout_authorization as authorization
from network_change_delivery import profiled_rollout_preflight as preflight
from network_change_delivery import profiled_rollout_reservation as reservation
from network_change_delivery.architecture_contracts import (
    AutomationProfileID,
    NetworkOS,
)
from network_change_delivery.openbao_profiled_deploy_config import (
    DEVICE_IDS,
    ProtectedRolloutCredentialAuthority,
)
from network_change_delivery.profile_inventory import ProfiledInventoryPopulation
from network_change_delivery.profiled_planning import PROFILED_OPERATION_ADMISSIONS
from network_change_delivery.profiled_promotion import (
    VALIDATION_KEYS,
    ProfiledBuildContext,
    digest_bytes,
    validation_receipt,
)
from network_change_delivery.profiled_rollout import (
    ProfiledRolloutSelectionIntent,
    ProfiledRolloutSelector,
    ProfiledRolloutSelectorClause,
    plan_profiled_rollout,
)
from network_change_delivery.profiled_rollout_promotion import (
    RolloutPlanningPublication,
    promote_rollout,
)
from network_change_delivery.secrets import CredentialReference

BUILD = "00000000-0000-4000-8000-000000000001"
JOB = "00000000-0000-4000-8000-000000000002"
HUMAN = "00000000-0000-4000-8000-000000000003"
SUCCESS = "sha256:" + "a" * 64


def fixture(compliant=(), *, selectors=True):
    inventory = Inventory()
    explicit = intent_for(inventory)
    intent = (
        ProfiledRolloutSelectionIntent(
            change_id=explicit.change_id,
            operation=explicit.operation,
            selectors=tuple(
                ProfiledRolloutSelectorClause(
                    selector=ProfiledRolloutSelector(
                        automation_profile_ids=(device.automation_profile_id,)
                    ),
                    interface=interface.name,
                    desired={"description": "NEW"},
                )
                for device, interface in inventory.pairs.values()
            ),
            policy=explicit.policy,
        )
        if selectors
        else explicit
    )
    authority = ProtectedRolloutCredentialAuthority()
    collector = Collector(inventory, compliant=compliant)
    parent = plan_profiled_rollout(
        intent,
        inventory,
        authority,
        FakeSecrets(),
        collector,
        source_commit=COMMIT,
        created_at=NOW,
    )
    raw = parent.model_dump_json(indent=2).encode() + b"\n"
    context = ProfiledBuildContext(BUILD, COMMIT, JOB, "profiled-rollout-promotion")
    publication = RolloutPlanningPublication(
        build_id=BUILD,
        commit=COMMIT,
        artifact_kind="plan"
        if parent.result_type == "profiled_rollout_plan"
        else "compliance",
        parent_schema_version=parent.schema_version,
        artifact_digest=digest_bytes(raw),
        result_digest=parent.digest,
    )
    receipts = {k: validation_receipt(BUILD, COMMIT, k) for k in VALIDATION_KEYS}
    promotion = None
    if publication.artifact_kind == "plan":
        promotion = promote_rollout(
            context, raw, publication, receipts, SUCCESS, SUCCESS, intent=intent
        )
    args = {
        "context": context,
        "parent_bytes": raw,
        "publication": publication,
        "promotion_bytes": promotion.model_dump_json(indent=2).encode() + b"\n"
        if promotion
        else b"{}",
        "receipts": receipts,
        "batfish": SUCCESS,
        "cml": SUCCESS,
        "promotion_digest": promotion.digest if promotion else SUCCESS,
        "unblocker_id": HUMAN,
        "intent": intent,
    }
    args["promotion_artifact_digest"] = digest_bytes(args["promotion_bytes"])
    return SimpleNamespace(
        inventory=inventory,
        collector=collector,
        authority=authority,
        parent=parent,
        promotion=promotion,
        args=args,
    )


def fresh(f, **kwargs):
    auth = kwargs.pop("authorization", None) or authorization.authorize_rollout(
        **f.args
    )
    args = {
        k: v
        for k, v in f.args.items()
        if k not in ("promotion_digest", "promotion_artifact_digest", "unblocker_id")
    }
    args.update(
        authorization=auth,
        inventory=f.inventory,
        credential_authority=f.authority,
        secrets=FakeSecrets(),
        collector=f.collector,
    )
    args.update(kwargs)
    return preflight.preflight_profiled_rollout(**args)


def test_authorization_reconstructs_exact_promotion_and_is_fieldless(monkeypatch):
    f = fixture()
    calls = []
    original = authorization.verify_rollout_promotion

    def verify(*args, **kwargs):
        calls.append(True)
        return original(*args, **kwargs)

    monkeypatch.setattr(authorization, "verify_rollout_promotion", verify)
    monkeypatch.setattr(
        reservation,
        "reserve_rollout_devices",
        lambda *_: pytest.fail("authorization reserved devices"),
    )
    f.inventory.resolve_profiled_population = lambda: pytest.fail(
        "authorization queried inventory"
    )
    a = authorization.authorize_rollout(**f.args)
    assert len(calls) == 1
    assert a == authorization.authorize_rollout(**f.args)
    assert a == type(a).model_validate_json(a.model_dump_json())
    assert a.selected_devices == tuple(f"netbox:dcim.device:{i}" for i in (1, 2, 8, 9))
    assert a.canaries == f.parent.canaries and a.waves == f.parent.waves
    other = authorization.authorize_rollout(**{**f.args, "unblocker_id": JOB})
    assert other.digest != a.digest
    assert other.model_dump(exclude={"digest", "unblocker_id"}) == a.model_dump(
        exclude={"digest", "unblocker_id"}
    )
    assert DEVICE_IDS == (1, 2, 8, 9)


@pytest.mark.parametrize(
    "field",
    [
        "target",
        "interface",
        "desired_description",
        "profile",
        "device_id",
        "credential_scope",
        "comment",
        "options",
    ],
)
def test_no_human_fields(field):
    a = authorization.authorize_rollout(**fixture().args)
    with pytest.raises(ValueError):
        type(a).model_validate({**a.model_dump(), field: "arbitrary"})


@pytest.mark.parametrize(
    "damage",
    [
        "build",
        "commit",
        "parent_bytes",
        "parent_digest",
        "promotion_bytes",
        "promotion_digest",
        "promotion_artifact_digest",
        "receipt",
        "batfish",
        "cml",
        "intent",
        "selector",
        "unblocker_missing",
        "unblocker_invalid",
    ],
)
def test_authorization_rejects_detached_inputs(damage):
    f = fixture()
    a = f.args.copy()
    if damage == "build":
        a["context"] = replace(a["context"], build_id=JOB)
    elif damage == "commit":
        a["context"] = replace(a["context"], commit="b" * 40)
    elif damage == "parent_bytes":
        a["parent_bytes"] += b" "
    elif damage == "parent_digest":
        a["publication"] = a["publication"].model_copy(
            update={"result_digest": SUCCESS}
        )
    elif damage == "promotion_bytes":
        a["promotion_bytes"] += b" "
    elif damage in ("promotion_digest", "promotion_artifact_digest", "batfish", "cml"):
        a[damage] = "sha256:" + "b" * 64
    elif damage == "receipt":
        a["receipts"] = {
            k: v for k, v in a["receipts"].items() if k != VALIDATION_KEYS[-1]
        }
    elif damage == "intent":
        a["intent"] = a["intent"].model_copy(update={"change_id": "CHG-ALTERED"})
    elif damage == "selector":
        a["intent"] = a["intent"].model_copy(
            update={"selectors": tuple(reversed(a["intent"].selectors))}
        )
    elif damage == "unblocker_missing":
        a["unblocker_id"] = ""
    elif damage == "unblocker_invalid":
        a["unblocker_id"] = "not-a-uuid"
    with pytest.raises(ValueError):
        authorization.authorize_rollout(**a)


@pytest.mark.parametrize(
    "field",
    [
        "parent_digest",
        "parent_artifact_digest",
        "validation_digest",
        "batfish_digest",
        "cml_digest",
        "child_artifact",
        "child_result",
        "children_order",
        "canaries",
        "waves",
    ],
)
def test_validly_rehashed_detached_promotion_never_authorizes(field):
    f = fixture()
    v = f.promotion.model_dump(mode="json")
    if field.startswith("child_"):
        v["children"][0][
            "artifact_digest" if field == "child_artifact" else "result_digest"
        ] = SUCCESS
    elif field == "children_order":
        v["children"].reverse()
    elif field in ("canaries", "waves"):
        v[field].reverse()
    else:
        v[field] = "sha256:" + "b" * 64
    detached = rehash(type(f.promotion), v)
    assert detached.digest == detached.calculated_digest() and detached != f.promotion
    raw = detached.model_dump_json().encode()
    with pytest.raises(ValueError, match="readback"):
        authorization.authorize_rollout(
            **{
                **f.args,
                "promotion_bytes": raw,
                "promotion_digest": detached.digest,
                "promotion_artifact_digest": digest_bytes(raw),
            }
        )


def test_all_compliant_has_no_authorization_or_preflight():
    f = fixture(compliant=tuple(Inventory().pairs))
    with pytest.raises(ValueError):
        authorization.authorize_rollout(**f.args)
    good = fixture()
    auth = authorization.authorize_rollout(**good.args)
    f.inventory.resolve_profiled_population = lambda: pytest.fail(
        "compliance accessed provider"
    )
    with pytest.raises(ValueError):
        fresh(f, authorization=auth)


@pytest.mark.parametrize("compliant", [(), ("access-sw-01",)])
@pytest.mark.parametrize("selectors", [True, False])
def test_fresh_basis_accepts_new_timestamps_complete_admission(compliant, selectors):
    f = fixture(compliant, selectors=selectors)
    events = []

    class Authority:
        def admit(self, identity):
            events.append("admit")
            return f.authority.admit(identity)

    class Secrets(FakeSecrets):
        def reference(self, device):
            assert events.count("admit") == 4
            events.append("reference")
            return super().reference(device)

        def load(self, device):
            assert events.count("reference") == 4
            events.append("load")
            return super().load(device)

    original = f.collector.collect

    def collect(*args):
        assert events.count("load") == 4
        events.append("observe")
        return original(*args)

    f.collector.collect = collect
    result = fresh(f, credential_authority=Authority(), secrets=Secrets())
    assert result.schema_version == "1" and not result.execution_attempted
    assert (
        len(result.children) == 4
        and events == ["admit"] * 4 + ["reference"] * 4 + ["load"] * 4 + ["observe"] * 4
    )
    assert result == type(result).model_validate_json(result.model_dump_json())
    for child, approved in zip(result.children, f.parent.children, strict=True):
        assert child.observed_at > NOW
        assert child.approved_artifact_digest == digest_bytes(approved.artifact_bytes())
        assert child.kind == approved.kind
    assert len({c.device.automation_profile_id for c in f.parent.children}) == 4


@pytest.mark.parametrize(
    "damage",
    [
        "new_member",
        "removed_member",
        "order",
        "stable_device",
        "stable_interface",
        "interface_name",
        "protected",
        "profile",
        "nos",
        "endpoint",
        "hostname",
        "operation",
        "credential_authority",
        "credential_reference",
        "secret_unavailable",
    ],
)
def test_whole_admission_failure_precedes_any_collection(damage, monkeypatch):
    f = fixture()
    secrets = FakeSecrets()
    name = "access-sw-01"
    device, interface = f.inventory.pairs[name]
    if damage in ("new_member", "removed_member"):
        population = declared_population(5 if damage == "new_member" else 3)[
            2
        ].resolve_profiled_population()
        # Preserve the original selected fixture facts; only membership changes.
        current = f.inventory.population
        f.inventory.population = ProfiledInventoryPopulation(
            declaration=population.declaration,
            devices=(*current.devices, population.devices[-1])
            if damage == "new_member"
            else current.devices[:3],
        )
    elif damage == "order":
        declaration = f.inventory.population.declaration
        f.inventory.population = f.inventory.population.model_copy(
            update={
                "declaration": declaration.model_copy(
                    update={"members": tuple(reversed(declaration.members))}
                )
            }
        )
    elif damage == "stable_interface":
        f.inventory.pairs[name] = (
            device,
            interface.model_copy(update={"interface": "netbox:dcim.interface:999"}),
        )
    elif damage == "interface_name":
        f.inventory.pairs[name] = (
            device,
            interface.model_copy(update={"name": "GigabitEthernet0/2"}),
        )
    elif damage == "operation":
        key = next(
            k
            for k in PROFILED_OPERATION_ADMISSIONS
            if k[0] == device.automation_profile_id
        )
        monkeypatch.setattr(
            profiled_planning,
            "PROFILED_OPERATION_ADMISSIONS",
            {k: v for k, v in PROFILED_OPERATION_ADMISSIONS.items() if k != key},
        )
    elif damage == "credential_authority":
        original = f.authority.admit

        def admit(identity):
            if identity == device.device_identity:
                raise ValueError("permission absent")
            return original(identity)

        f.authority.admit = admit
    elif damage == "credential_reference":
        original = secrets.reference
        secrets.reference = lambda d: (
            CredentialReference("openbao", "openbao:kv-v2:ncdp/devices/999/ssh")
            if d == device
            else original(d)
        )
    elif damage == "secret_unavailable":
        original = secrets.load

        def load(d):
            if d == device:
                raise ValueError("secret unavailable")
            return original(d)

        secrets.load = load
    else:
        changes = {
            "stable_device": {"device_identity": "netbox:dcim.device:999"},
            "protected": {
                "protected_interfaces": (*device.protected_interfaces, interface)
            },
            "profile": {"automation_profile_id": AutomationProfileID.IOSV_159_3_M12},
            "nos": {"network_os": NetworkOS.IOSXE},
            "hostname": {"expected_hostname": "different"},
        }
        if damage == "endpoint":
            endpoint = device.management_endpoints.live
            l3 = endpoint.binding.l3_endpoint.model_copy(
                update={"address": "192.0.2.99/24"}
            )
            endpoint = endpoint.model_copy(
                update={
                    "binding": endpoint.binding.model_copy(update={"l3_endpoint": l3})
                }
            )
            changes[damage] = {
                "management_endpoints": device.management_endpoints.model_copy(
                    update={"live": endpoint}
                )
            }
        changed = device.model_copy(update=changes[damage])
        f.inventory.pairs[name] = (changed, interface)
        f.inventory.population = f.inventory.population.model_copy(
            update={
                "devices": tuple(
                    changed if d == device else d
                    for d in f.inventory.population.devices
                )
            }
        )
    f.collector.collect = lambda *_: pytest.fail(
        "collection began after failed admission"
    )
    with pytest.raises(ValueError):
        fresh(f, secrets=secrets)
    if damage != "secret_unavailable":
        assert secrets.load_calls == 0


@pytest.mark.parametrize(
    "damage",
    [
        "deployable_to_compliant",
        "compliant_to_deployable",
        "description",
        "hostname",
        "interface",
        "missing",
        "protected",
        "collection_failure",
        "desired",
    ],
)
def test_observed_basis_changes_produce_no_positive_preflight(damage):
    f = fixture(
        compliant=("access-sw-01",) if damage == "compliant_to_deployable" else ()
    )
    if damage == "deployable_to_compliant":
        f.collector.compliant = ("access-sw-01",)
    elif damage == "compliant_to_deployable":
        f.collector.compliant = ()
    elif damage == "collection_failure":
        f.collector.fail = "access-sw-01"
    elif damage == "desired":
        old = f.args["intent"]
        clause = old.selectors[-1].model_copy(
            update={
                "desired": old.selectors[-1].desired.model_copy(
                    update={"description": "CHANGED"}
                )
            }
        )
        f.args["intent"] = old.model_copy(
            update={"selectors": (*old.selectors[:-1], clause)}
        )
    else:
        original = f.collector.collect

        def collect(*args):
            state = original(*args)
            if args[0].logical_name == "access-sw-01":
                key = {
                    "description": "description",
                    "hostname": "observed_hostname",
                    "interface": "interface",
                    "missing": "exists",
                    "protected": "protected",
                }[damage]
                state = state.model_copy(
                    update={
                        key: False
                        if damage == "missing"
                        else True
                        if damage == "protected"
                        else "different"
                    }
                )
            return state

        f.collector.collect = collect
    with pytest.raises(ValueError):
        fresh(f)


def test_preflight_rejects_tampered_authorization_before_provider():
    f = fixture()
    a = authorization.authorize_rollout(**f.args)
    values = a.model_dump(mode="json")
    values["selected_devices"].reverse()
    tampered = rehash(type(a), values)
    f.inventory.resolve_profiled_population = lambda: pytest.fail(
        "provider before authorization"
    )
    with pytest.raises(ValueError):
        fresh(f, authorization=tampered)


def test_no_execution_import_or_surface_and_original_child_bytes():
    for module in (authorization, preflight, reservation):
        tree = ast.parse(inspect.getsource(module))
        imports = [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
        assert not any(
            "execution" in (n or "")
            or "write_adapter" in (n or "")
            or "audit_store" in (n or "")
            or "chronology" in (n or "")
            for n in imports
        )
    f = fixture()
    before = tuple(c.artifact_bytes() for c in f.parent.children)
    fresh(f)
    assert tuple(c.artifact_bytes() for c in f.parent.children) == before


@pytest.mark.parametrize(
    "damage", ["expansion", "child_artifact", "child_result", "canaries", "waves"]
)
def test_authorization_rejects_parent_semantic_tampering(damage):
    f = fixture()
    values = f.parent.model_dump(mode="json")
    if damage == "expansion":
        values["expansion"].reverse()
    elif damage == "child_artifact":
        values["children"][0]["artifact_digest"] = SUCCESS
    elif damage == "child_result":
        values["children"][0]["result_digest"] = SUCCESS
    else:
        values[damage].reverse()
    import json

    values["digest"] = digest_bytes(
        json.dumps(
            {k: v for k, v in values.items() if k != "digest"},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    )
    raw = json.dumps(values).encode()
    publication = f.args["publication"].model_copy(
        update={"artifact_digest": digest_bytes(raw), "result_digest": values["digest"]}
    )
    with pytest.raises(ValueError):
        authorization.authorize_rollout(
            **{**f.args, "parent_bytes": raw, "publication": publication}
        )


def test_verified_authorization_is_required_even_when_promotion_self_digest_is_valid(
    monkeypatch,
):
    f = fixture()

    def reject(*_a, **_kw):
        raise ValueError("independent reconstruction required")

    monkeypatch.setattr(authorization, "verify_rollout_promotion", reject)
    with pytest.raises(ValueError, match="reconstruction"):
        authorization.authorize_rollout(**f.args)


def test_preflight_never_returns_ambiguous_child_result(monkeypatch):
    f = fixture()
    monkeypatch.setattr(
        preflight,
        "plan_profiled_change",
        lambda *_a, **_kw: SimpleNamespace(plan=None, compliance=None),
    )
    with pytest.raises(ValueError, match="ambiguous"):
        fresh(f)


def test_mixed_reservation_contains_compliant_members(tmp_path):
    f = fixture(compliant=("access-sw-01",))
    a = authorization.authorize_rollout(**f.args)
    tmp_path.chmod(0o700)
    with (
        reservation.reserve_rollout_devices(tmp_path, a.selected_devices),
        pytest.raises(ValueError),
        reservation.reserve_rollout_devices(tmp_path, ("netbox:dcim.device:9",)),
    ):
        pass


def test_preflight_rejects_missing_credential_before_collection():
    f = fixture()
    secrets = FakeSecrets()
    secrets.load = lambda _device: None
    f.collector.collect = lambda *_: pytest.fail("collection without credential")
    with pytest.raises(ValueError, match="availability"):
        fresh(f, secrets=secrets)


def test_preflight_rejects_invalid_fresh_result_digest(monkeypatch):
    f = fixture()
    bad = f.parent.children[0].result().model_copy(update={"digest": SUCCESS})
    monkeypatch.setattr(
        preflight,
        "plan_profiled_change",
        lambda *_a, **_kw: SimpleNamespace(plan=bad, compliance=None),
    )
    with pytest.raises(ValueError):
        fresh(f)
