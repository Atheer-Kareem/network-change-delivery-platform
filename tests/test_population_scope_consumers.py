"""Synthetic scope exactness across realization and passive consumer boundaries."""

import json
from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
import pytest
from profiled_population_fixtures import declared_population
from test_profiled_realization import persistent, staging_context, trust_generation

from network_change_delivery.profile_inventory import (
    oxidized_scope_nodes,
    population_scope,
)
from network_change_delivery.profiled_realization import (
    CmlAnchoredHostTrustGeneration,
    CmlAnchoredHostTrustRecord,
    ProfiledRealizedDevice,
    StagingRealizedDevice,
)
from network_change_delivery.profiled_staging import (
    CURRENT_STAGING_TOPOLOGY,
    ProfiledStagingEvidenceV2,
    ProfiledStagingLink,
    ProfiledStagingTopology,
    read_profiled_staging_evidence,
    staging_interface_name,
    staging_terraform_addresses,
    terraform_profiled_device_variables,
)
from network_change_delivery.profiled_staging_cml import staging_link_slots
from network_change_delivery.secrets import DeviceCredentials


@pytest.mark.parametrize("size", [1, 2, 4, 5])
def test_realization_and_trust_are_exact_scope_bound(size):
    declaration, scope, provider, _ = declared_population(size)
    devices = provider.resolve_profiled_population().devices
    prototypes = (persistent(), staging_context(), trust_generation())
    for prototype in prototypes:
        key = (
            "records"
            if isinstance(prototype, CmlAnchoredHostTrustGeneration)
            else "devices"
        )
        originals = getattr(prototype, key)
        children = []
        for index, device in enumerate(devices):
            template = next(
                d
                for d in originals
                if d.automation_profile_id == device.automation_profile_id
            )
            values = template.model_dump(mode="python") | {
                "device_identity": device.device_identity,
                "logical_name": device.logical_name,
                "cml_node_id": f"10000000-0000-4000-8000-{index + 1:012d}",
            }
            if isinstance(template, ProfiledRealizedDevice):
                values["management_endpoint"] = device.management_endpoints.live
            elif isinstance(template, StagingRealizedDevice):
                values["staging_endpoint"] = device.management_endpoints.staging
            elif isinstance(template, CmlAnchoredHostTrustRecord):
                values["management_address"] = (
                    device.management_endpoints.live.binding.l3_endpoint.address.ip
                )
            children.append(type(template).model_validate(values))
        values = prototype.model_dump(mode="python") | {
            "scope": scope,
            key: tuple(children),
        }
        admitted = type(prototype).model_validate(values)
        assert len(getattr(admitted, key)) == size
        for invalid in ((), tuple(children[:-1]), (*children, children[-1])):
            with pytest.raises(ValueError):
                type(prototype).model_validate(values | {key: invalid})
        wrong = population_scope(
            "other-scope", (scope.identities[0],), declaration=declaration
        )
        if size > 1:
            with pytest.raises(ValueError):
                type(prototype).model_validate(values | {"scope": wrong})


@pytest.mark.parametrize("size", [1, 2, 5])
def test_scoped_terraform_graph_management_and_topology(size):
    _, scope, provider, _ = declared_population(size)
    devices = provider.resolve_profiled_population().devices
    # No service data links are implied by managed membership.
    topology = ProfiledStagingTopology(scope=scope, links=())
    addresses = staging_terraform_addresses(scope, topology)
    assert len(addresses) == 2 * size + 5
    credentials = {
        d.logical_name: DeviceCredentials(username="synthetic", password="unused")
        for d in devices
    }
    verifiers = {
        d.logical_name: (
            "$6$salt$hash" if d.network_os.value == "junos" else "$9$salt$hash"
        )
        for d in devices
    }
    variables = terraform_profiled_device_variables(
        devices, credentials, verifiers, scope=scope
    )
    assert tuple(variables) == tuple(d.logical_name.replace("-", "_") for d in devices)
    assert tuple(v["management_switch_slot"] for v in variables.values()) == tuple(
        range(1, size + 1)
    )
    assert len({(v["layout_x"], v["layout_y"]) for v in variables.values()}) == size
    slots = staging_link_slots(devices, topology)
    assert len(slots) == size + 1
    assert all(v["management_slot"] == 0 for v in variables.values())
    with pytest.raises(ValueError):
        ProfiledStagingTopology(
            scope=scope,
            links=(
                ProfiledStagingLink(
                    identity="foreign",
                    endpoints=(
                        f"{devices[0].logical_name}:GigabitEthernet2",
                        "not-admitted:GigabitEthernet1",
                    ),
                ),
            ),
        )
    assert (
        CURRENT_STAGING_TOPOLOGY.digest
        == "sha256:764405fa9a44d7c42ae402ec2fa1d03c2b7dd9ba0916954e03c7a7d5baf68064"
    )


@pytest.mark.parametrize("size", [1, 2, 5])
def test_oxidized_scope_controls_source_readiness_and_api(tmp_path, monkeypatch, size):
    from test_oxidized_source import Secrets

    from network_change_delivery.oxidized_controller import (
        OxidizedControlError,
        OxidizedController,
        read_collection_ready,
    )
    from network_change_delivery.oxidized_service import publish_readiness
    from network_change_delivery.oxidized_source import materialize_oxidized_source

    _, scope, provider, _ = declared_population(size)
    source = materialize_oxidized_source(
        provider, Secrets(), tmp_path / "source", scope=scope
    )
    names = oxidized_scope_nodes(scope)
    assert tuple(row["name"] for row in json.loads(source.path.read_bytes())) == names

    def trust(_):
        return SimpleNamespace(known_hosts_sha256="b" * 64)

    monkeypatch.setattr(
        "network_change_delivery.oxidized_service.validate_host_trust", trust
    )
    monkeypatch.setattr(
        "network_change_delivery.oxidized_controller.validate_host_trust", trust
    )
    runtime = tmp_path / "runtime"
    runtime.mkdir(mode=0o700)
    marker_path = runtime / "ready.json"
    marker = publish_readiness(marker_path, "a" * 64, scope=scope)
    assert read_collection_ready(marker_path, "a" * 64, scope=scope) == marker
    other = population_scope(
        "wrong", scope.identities[:1], declaration=provider.declaration
    )
    if size > 1:
        with pytest.raises(OxidizedControlError):
            read_collection_ready(marker_path, "a" * 64, scope=other)
    base = [
        {"name": n, "group": "managed", "status": "never", "last": None} for n in names
    ]
    for mutation in ("valid", "missing", "extra", "duplicate", "group"):
        payload = [dict(n) for n in base]
        if mutation == "missing":
            payload.pop()
        elif mutation == "extra":
            payload.append(dict(base[0], name="netbox-device-999"))
        elif mutation == "duplicate":
            payload.append(dict(base[0]))
        elif mutation == "group":
            payload[-1]["group"] = "unreviewed"
        controller = OxidizedController(
            "http://127.0.0.1:8888",
            marker_path,
            tmp_path / "locks",
            "a" * 64,
            scope=scope,
            transport=httpx.MockTransport(
                lambda _, payload=payload: httpx.Response(200, json=payload)
            ),
        )
        try:
            if mutation == "valid":
                assert tuple(controller._nodes()) == names
            else:
                with pytest.raises(OxidizedControlError):
                    controller._nodes()
            with pytest.raises(OxidizedControlError):
                controller.collect("netbox-device-999")
        finally:
            controller._client.close()


@pytest.mark.parametrize("size", [1, 2, 5])
def test_observability_generation_and_readiness_exact_scope(tmp_path, size):
    from network_change_delivery.observability_service import (
        publish_readiness,
        read_readiness,
    )
    from network_change_delivery.observability_targets import (
        TargetGeneration,
        TargetGenerationState,
        publish_generation,
        read_generation,
        targets_from_inventory,
    )

    _, scope, provider, _ = declared_population(size)
    targets = targets_from_inventory(provider, scope=scope)
    now = datetime.now(UTC)
    root = tmp_path / "observability"
    realization = SimpleNamespace(
        lab_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", digest="sha256:" + "b" * 64
    )
    generation = publish_generation(
        root,
        state=TargetGenerationState.ACTIVE,
        targets=targets,
        realization=realization,
        scope=scope,
        now=now,
    )
    assert read_generation(root, scope=scope) == generation
    kwargs = {
        "prometheus_container_id": "c" * 64,
        "blackbox_container_id": "d" * 64,
        "source_commit": "e" * 40,
        "now": now,
        "scope": scope,
    }
    marker = publish_readiness(root, generation, **kwargs)
    assert read_readiness(root, generation, **kwargs) == marker
    assert marker.targets == scope.identities
    for invalid in (targets[:-1], (*targets, targets[0])):
        data = generation.model_dump(mode="python") | {"targets": invalid}
        # Rehash so rejection proves membership rather than a stale digest.
        unsigned = generation.model_copy(update={"targets": invalid})
        with pytest.raises(ValueError, match="active target generation rejected"):
            TargetGeneration.model_validate(
                data | {"digest": unsigned.calculated_digest()}
            )


def test_historical_staging_v2_remains_exact_and_distinct():
    original = (
        b'{"schema_version":"2","staging_run_id":"historical-run",'
        b'"orchestrator":"local","lab_title":"NCDP Staging historical-run",'
        b'"transit_recycle_outcome":"succeeded","transit_recycle_evidence":{'
        b'"identity":"staging-transit-recycle:historical-run:transit-ios-01",'
        b'"digest":"sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
        b'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}}\n'
    )
    record = read_profiled_staging_evidence(original)
    assert isinstance(record, ProfiledStagingEvidenceV2)
    assert record.transit_recycle_outcome == "succeeded"
    assert record.schema_version == "2"
    assert "recycles" not in record.model_dump()
    assert "scope" not in record.model_dump()
    assert original.endswith(b"\n")


def test_current_staging_has_no_recycle_subjects():
    from network_change_delivery.architecture_contracts import (
        CML_REALIZATION_PROFILE_CATALOG,
        CmlBootPolicy,
    )
    from network_change_delivery.profile_inventory import STAGING_REALIZATION_SCOPE

    subjects = tuple(
        member
        for member in STAGING_REALIZATION_SCOPE.members
        if CML_REALIZATION_PROFILE_CATALOG[
            member.staging_cml_realization_profile_id
            or member.cml_realization_profile_id
        ].boot_policy
        is CmlBootPolicy.IOSV_PERSISTENCE_RECYCLE
    )
    assert subjects == ()


def test_read_only_scopes_never_grant_write_authority():
    from network_change_delivery.architecture_contracts import AutomationProfileID
    from network_change_delivery.profile_inventory import (
        LIVE_REALIZATION_SCOPE,
        OBSERVABILITY_SCOPE,
        OXIDIZED_COLLECTION_SCOPE,
        PROFILED_MANAGED_POPULATION,
        STAGING_REALIZATION_SCOPE,
    )
    from network_change_delivery.profiled_planning import (
        PROFILED_OPERATION_ADMISSIONS,
        ProfiledOperation,
        admit_profiled_operation,
    )
    from network_change_delivery.profiled_promotion import ProfiledPromotion

    _, scope, provider, _ = declared_population(5)
    population = provider.resolve_profiled_population()
    assert ProfiledPromotion.model_fields["device_identity"].is_required()
    assert ProfiledPromotion.model_fields["target"].is_required()
    assert {profile for profile, _ in PROFILED_OPERATION_ADMISSIONS} == {
        AutomationProfileID.CAT8000V_IOSXE,
        AutomationProfileID.VJUNOS_ROUTER,
        AutomationProfileID.IOSV_159_3_M12,
        AutomationProfileID.IOSVL2_2020,
    }
    original = dict(PROFILED_OPERATION_ADMISSIONS)
    for selected in (
        scope,
        LIVE_REALIZATION_SCOPE,
        STAGING_REALIZATION_SCOPE,
        OXIDIZED_COLLECTION_SCOPE,
        OBSERVABILITY_SCOPE,
    ):
        for device in population.project(selected).devices:
            if device.logical_name not in {
                m.logical_name for m in PROFILED_MANAGED_POPULATION.members
            }:
                with pytest.raises(ValueError):
                    admit_profiled_operation(
                        device, ProfiledOperation.INTERFACE_DESCRIPTION
                    )
                continue
            admission = admit_profiled_operation(
                device, ProfiledOperation.INTERFACE_DESCRIPTION
            )
            assert (
                admission
                == original[
                    (
                        device.automation_profile_id,
                        ProfiledOperation.INTERFACE_DESCRIPTION,
                    )
                ]
            )
        assert dict(PROFILED_OPERATION_ADMISSIONS) == original
    from network_change_delivery.openbao_profiled_deploy_config import DEVICE_IDS

    assert DEVICE_IDS == (
        1,
        2,
        8,
        9,
    )  # passive scopes cannot expand protected credential authority


def test_service_subjects_stay_bounded_when_population_grows():
    from test_routed_underlay import desired, observation, reference_allocation

    from network_change_delivery.profile_inventory import (
        ACL_SERVICE_SCOPE,
        OSPF_SERVICE_SCOPE,
        ROUTED_SERVICE_SCOPE,
        VLAN_SERVICE_SCOPE,
    )
    from network_change_delivery.routed_underlay import (
        RoutedUnderlayIntent,
        render_routed_underlay,
    )

    _, _, provider, _ = declared_population(5)
    population = provider.resolve_profiled_population()
    assert tuple(
        len(population.project(s).devices)
        for s in (
            ROUTED_SERVICE_SCOPE,
            OSPF_SERVICE_SCOPE,
            VLAN_SERVICE_SCOPE,
            ACL_SERVICE_SCOPE,
        )
    ) == (3, 3, 2, 1)
    # The real rendering path receives a larger admitted managed population.
    rendered = render_routed_underlay(
        RoutedUnderlayIntent.from_reference_allocation(reference_allocation()),
        observation(),
        desired(),
        population,
    )
    assert "synthetic-14" not in str(rendered)
    from test_reference_routing_identity import (
        fixture_payloads,
    )
    from test_reference_routing_identity import (
        provider as router_provider,
    )

    payload = fixture_payloads()
    before = router_provider(payload).resolve_routing_identities()
    payload["devices"].append(
        {"id": 14, "name": "synthetic-14", "primary_ip4": {"id": 1014}}
    )
    assert router_provider(payload).resolve_routing_identities() == before


@pytest.mark.parametrize("size", [1, 2, 5])
def test_live_known_hosts_generation_requires_reviewed_realization_scope(
    tmp_path, size
):
    import hashlib

    from test_profiled_live_host_trust import key, material

    from network_change_delivery.architecture_contracts import (
        CML_REALIZATION_PROFILE_CATALOG,
    )
    from network_change_delivery.profiled_live_cml import (
        LIVE_LAB_ID,
        ProfiledLiveAnchor,
        ProfiledLiveRealizationCatalog,
    )
    from network_change_delivery.profiled_live_host_trust import (
        ProfiledLiveHostTrustError,
        publish_profiled_live_host_trust,
        validate_profiled_live_host_trust,
    )
    from network_change_delivery.profiled_realization import EvidenceReference

    _declaration, scope, provider, _ = declared_population(size)
    devices = provider.resolve_profiled_population().devices
    anchors = tuple(
        ProfiledLiveAnchor(
            logical_name=d.logical_name,
            device_id=int(d.device_identity.rsplit(":", 1)[1]),
            cml_node_id=f"10000000-0000-4000-8000-{index + 1:012d}",
            cml_label=d.logical_name,
            node_definition=CML_REALIZATION_PROFILE_CATALOG[
                d.cml_realization_profile_id
            ].node_definition,
            image_definition=CML_REALIZATION_PROFILE_CATALOG[
                d.cml_realization_profile_id
            ].image_definition,
            management_address=d.live_read_only_target().host,
            management_port=d.live_read_only_target().port,
            automation_profile_id=d.automation_profile_id,
            cml_realization_profile_id=d.cml_realization_profile_id,
        )
        for index, d in enumerate(devices)
    )
    catalog = ProfiledLiveRealizationCatalog(
        scope=scope, anchors=anchors, data_links=()
    )
    known = "".join(
        f"{a.management_address} ssh-rsa {key(str(a.device_id))[0]}\n" for a in anchors
    ).encode()
    ref = EvidenceReference(
        identity="profiled-live-trust:known-hosts",
        digest="sha256:" + hashlib.sha256(known).hexdigest(),
    )
    _, prototype = material()
    records = []
    for anchor in anchors:
        original = next(
            r
            for r in prototype.records
            if r.automation_profile_id == anchor.automation_profile_id
        )
        records.append(
            CmlAnchoredHostTrustRecord.model_validate(
                original.model_dump()
                | {
                    "device_identity": f"netbox:dcim.device:{anchor.device_id}",
                    "logical_name": anchor.logical_name,
                    "cml_node_id": anchor.cml_node_id,
                    "management_address": anchor.management_address,
                    "host_key_fingerprint": key(str(anchor.device_id))[1],
                    "trust_generation": ref,
                }
            )
        )
    generation = CmlAnchoredHostTrustGeneration.model_validate(
        prototype.model_dump()
        | {
            "scope": scope,
            "records": tuple(records),
            "generation_evidence": ref,
            "cml_lab_id": LIVE_LAB_ID,
        }
    )
    root = tmp_path / "trust"
    assert (
        publish_profiled_live_host_trust(known, generation, root, catalog=catalog)
        == generation
    )
    assert validate_profiled_live_host_trust(root, catalog=catalog) == generation
    # An alternate scope never replaces the expected current LIVE authority.
    with pytest.raises(ProfiledLiveHostTrustError):
        validate_profiled_live_host_trust(root)


@pytest.mark.parametrize("size", [1, 2, 5])
def test_same_cml_admission_and_lab_start_code_accepts_scoped_graph(size):
    from network_change_delivery.architecture_contracts import (
        CML_REALIZATION_PROFILE_CATALOG,
    )
    from network_change_delivery.profiled_staging_cml import (
        ProfiledStagingCmlLabStarter,
        admit_created_realization,
    )

    _, scope, provider, _ = declared_population(size)
    devices = provider.resolve_profiled_population().devices
    topology = ProfiledStagingTopology(scope=scope, links=())
    links = staging_link_slots(devices, topology)
    lab_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    nodes = {"system_bridge": "system", "management_switch": "switch"} | {
        d.logical_name.replace("-", "_"): d.logical_name for d in devices
    }
    by_id = {d.logical_name: d for d in devices}
    link_ids = {key: f"link-{key}" for key in links}
    slots = {
        key: {slot: f"{key}-{slot}" for slot in range(max(size + 1, 4))}
        for key in nodes
    }

    class Reader:
        def lab(self, _):
            return {
                "id": lab_id,
                "lab_title": "NCDP Staging scoped-graph",
                "state": "DEFINED_ON_CORE",
            }

        def ids(self, _, kind):
            return tuple(nodes.values() if kind == "nodes" else link_ids.values())

        def item(self, _, kind, identity):
            if kind == "links":
                key = next(k for k, v in link_ids.items() if v == identity)
                (a, x), (b, y) = links[key]
                return {"interface_a": slots[a][x], "interface_b": slots[b][y]}
            if identity in {"system", "switch"}:
                return {
                    "id": identity,
                    "label": "system-bridge"
                    if identity == "system"
                    else "management-switch",
                    "node_definition": "external_connector"
                    if identity == "system"
                    else "unmanaged_switch",
                    "state": "DEFINED_ON_CORE",
                }
            device = by_id[identity]
            profile = CML_REALIZATION_PROFILE_CATALOG[
                device.effective_staging_cml_realization_profile_id
            ]
            return {
                "id": identity,
                "label": identity,
                "node_definition": profile.node_definition,
                "image_definition": profile.image_definition,
                "state": "DEFINED_ON_CORE",
            }

        def interfaces(self, _, identity):
            return slots[next(k for k, v in nodes.items() if v == identity)]

        def configuration(self, _, identity):
            d = by_id[identity]
            binding = d.management_endpoints.staging.binding
            return (
                f"hostname {d.expected_hostname}\ninterface "
                f"{
                    staging_interface_name(
                        d, binding.physical_attachment.interface.name
                    )
                }\n"
                f" address {binding.l3_endpoint.address.ip}\n no switchport\n"
            )

    reader = Reader()
    observed = admit_created_realization(
        reader,
        "scoped-graph",
        {"lab_id": lab_id, "node_ids": nodes, "link_ids": link_ids},
        devices,
        topology=topology,
    )
    assert len(observed.node_ids) == size + 2
    assert len(observed.link_ids) == size + 1
    calls = []

    def respond(request):
        calls.append((request.method, request.url.path))
        return httpx.Response(204)

    starter = ProfiledStagingCmlLabStarter(
        httpx.Client(
            base_url="https://cml.invalid", transport=httpx.MockTransport(respond)
        )
    )
    starter._reader = reader
    try:
        evidence = starter.start(
            run_id="scoped-graph", observed=observed, devices=devices
        )
    finally:
        starter.close()
    assert evidence.identity == "staging-lab-start:scoped-graph"
    assert calls == [("PUT", f"/api/v0/labs/{lab_id}/start")]


def test_topology_rejects_physical_alias_duplicate_and_management_links():
    _, scope, provider, _ = declared_population(5)
    for endpoints in (
        ("core-02:GigabitEthernet1", "synthetic-14:Gi0/1"),
        ("core-02:GigabitEthernet3", "transit-ios-01:Gi0/1"),
    ):
        links = (
            ProfiledStagingLink(
                identity="one",
                endpoints=(
                    "core-02:GigabitEthernet2",
                    "transit-ios-01:GigabitEthernet0/1",
                ),
            ),
            ProfiledStagingLink(identity="two", endpoints=endpoints),
        )
        with pytest.raises(
            ValueError, match=r"physical endpoint reused|resolved management slot"
        ):
            staging_link_slots(
                provider.resolve_profiled_population().devices,
                ProfiledStagingTopology(scope=scope, links=links),
            )


@pytest.mark.parametrize("name", ["system-bridge", "management-switch"])
def test_staging_scope_rejects_infrastructure_output_key_collision(name):
    from network_change_delivery.profile_inventory import ProfiledPopulationDeclaration

    declaration, _, _, _ = declared_population(1)
    member = type(declaration.members[0]).model_validate(
        declaration.members[0].model_dump() | {"logical_name": name}
    )
    declaration = ProfiledPopulationDeclaration(members=(member,))
    scope = population_scope(
        "reserved-key", declaration.identities, declaration=declaration
    )
    with pytest.raises(ValueError, match="collides with infrastructure"):
        ProfiledStagingTopology(scope=scope, links=())


@pytest.mark.parametrize("key", ["system_bridge_management", "management_core_02"])
def test_staging_topology_rejects_infrastructure_link_output_key_collision(key):
    _, scope, _, _ = declared_population(2)
    link = ProfiledStagingLink(
        identity=key,
        endpoints=("core-02:GigabitEthernet2", "edge-junos-01:ge-0/0/0"),
    )
    with pytest.raises(ValueError, match="duplicate link"):
        ProfiledStagingTopology(scope=scope, links=(link,))
