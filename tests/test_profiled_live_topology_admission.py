"""Exact read-only physical topology admission and passive-scope separation."""

from copy import deepcopy
from uuid import NAMESPACE_URL, uuid5

import httpx
import pytest

from network_change_delivery.profile_inventory import population_scope
from network_change_delivery.profiled_live_cml import (
    ACCESS_NODE_ID,
    CORE_NODE_ID,
    CURRENT_LIVE_REALIZATION,
    EXTERNAL_CONNECTOR_ID,
    JUNOS_NODE_ID,
    LIVE_LAB_ID,
    MANAGEMENT_SWITCH_ID,
    TRANSIT_NODE_ID,
    ProfiledLiveCmlError,
    ProfiledLiveCmlOperator,
)

# Accepted LIVE endpoint slots, independent of production catalog serialization.
ACCEPTED_LINKS = (
    (EXTERNAL_CONNECTOR_ID, 0, MANAGEMENT_SWITCH_ID, 3),
    (MANAGEMENT_SWITCH_ID, 4, CORE_NODE_ID, 0),
    (MANAGEMENT_SWITCH_ID, 5, JUNOS_NODE_ID, 0),
    (MANAGEMENT_SWITCH_ID, 6, TRANSIT_NODE_ID, 0),
    (MANAGEMENT_SWITCH_ID, 7, ACCESS_NODE_ID, 0),
    (CORE_NODE_ID, 3, JUNOS_NODE_ID, 1),
    (CORE_NODE_ID, 1, TRANSIT_NODE_ID, 1),
    (JUNOS_NODE_ID, 2, TRANSIT_NODE_ID, 2),
    (CORE_NODE_ID, 2, ACCESS_NODE_ID, 1),
)


def interface_id(node, slot):
    return str(uuid5(NAMESPACE_URL, f"https://cml.invalid/interfaces/{node}/{slot}"))


def operator_fixture(reviewed, mutate=None):
    root = f"/api/v0/labs/{LIVE_LAB_ID}"
    nodes = {
        EXTERNAL_CONNECTOR_ID: {
            "label": "ext-conn-0",
            "node_definition": "external_connector",
        },
        MANAGEMENT_SWITCH_ID: {
            "label": "unmanaged-switch-0",
            "node_definition": "unmanaged_switch",
        },
        **{
            a.cml_node_id: {
                "label": a.cml_label,
                "node_definition": a.node_definition,
                "image_definition": a.image_definition,
                "state": "BOOTED",
            }
            for a in reviewed.anchors
        },
    }
    configs = {
        a.cml_node_id: (
            f"hostname {a.logical_name} {a.management_address}"
            " privilege 15 secret 9 $9$fixture\n no switchport"
        )
        for a in reviewed.anchors
    }
    interfaces = {
        interface_id(node, slot): {"id": interface_id(node, slot), "slot": slot}
        for node in nodes
        for slot in range(10)
    }
    ids = (
        "80587f5c-4e5f-4552-8496-2ab9110f53e3",
        "ec2cac84-32d2-4628-a2a0-d4766f231105",
        "dfa3c1fc-fc56-4935-9c26-71722de48bca",
        "5e171308-9e12-48ec-b968-2218f7aa7a4d",
        "12fd7b69-c1d2-4717-9475-f4a42f0184cd",
        "8eee9cd3-56f5-4d99-a48e-4e4a35bc007a",
        "6613000c-9e14-42a4-bf8f-db00fbfe9982",
        "1482adb5-a013-40ff-bd6e-e8668c47192d",
        "e905d765-862e-438f-8532-c65390eb0483",
    )
    links = {
        identity: {
            "interface_a": interface_id(a, slot_a),
            "interface_b": interface_id(b, slot_b),
        }
        for identity, (a, slot_a, b, slot_b) in zip(ids, ACCEPTED_LINKS, strict=True)
    }
    if mutate:
        mutate(nodes, links)
    requests = []

    def handle(request):
        assert request.method == "GET", "physical admission must remain read-only"
        requests.append(request.url.path)
        path = request.url.path.removeprefix(root)
        if not path:
            result = {"lab_title": "NCDP Live", "state": "STARTED"}
        elif path == "/nodes":
            result = list(nodes)
        elif path == "/links":
            result = list(links)
        elif path.startswith("/links/"):
            result = links[path.removeprefix("/links/")]
        elif path.startswith("/interfaces/"):
            result = interfaces[path.removeprefix("/interfaces/")]
        elif path.endswith("/interfaces"):
            node = path.split("/")[2]
            result = [interface_id(node, slot) for slot in range(10)]
        elif path.endswith("/configuration"):
            result = configs[path.split("/")[2]]
        else:
            result = nodes[path.removeprefix("/nodes/")]
        return httpx.Response(200, json=result)

    return (
        ProfiledLiveCmlOperator(
            httpx.Client(
                base_url="https://cml.invalid", transport=httpx.MockTransport(handle)
            )
        ),
        requests,
    )


def test_exact_reviewed_nine_link_graph_passes():
    reviewed = CURRENT_LIVE_REALIZATION
    assert (
        tuple(
            (a.node_id, a.slot, b.node_id, b.slot)
            for a, b in (link.endpoints for link in reviewed.physical_links)
        )
        == ACCEPTED_LINKS
    )
    operator, requests = operator_fixture(reviewed)
    assert operator.anchor_profiled_live(catalog=reviewed) == reviewed.anchors
    assert len(reviewed.expected_node_ids) == 6
    assert reviewed.expected_link_count == 9
    assert len([p for p in requests if "/links/" in p]) == 9


@pytest.mark.parametrize(
    "case,message",
    [
        ("wrong", "physical topology rejected"),
        ("swapped", "physical topology rejected"),
        ("replaced", "physical topology rejected"),
        ("management-twin", "physical topology rejected"),
        ("missing", "population rejected"),
        ("extra", "population rejected"),
        ("duplicate", "link endpoints were invalid"),
        ("foreign", "population rejected"),
    ],
)
def test_observed_graph_cannot_replace_reviewed_physical_endpoints(case, message):
    def mutate(nodes, links):
        ids = list(links)
        original_nodes = set(nodes)
        if case == "wrong":
            links[ids[-1]]["interface_b"] = interface_id(ACCESS_NODE_ID, 2)
        elif case == "swapped":
            a, b = ids[-2:]
            links[a]["interface_b"], links[b]["interface_b"] = (
                links[b]["interface_b"],
                links[a]["interface_b"],
            )
        elif case == "replaced":
            replaced = links.pop(ids[-1])
            links["replacement"] = replaced | {
                "interface_b": interface_id(ACCESS_NODE_ID, 2)
            }
        elif case == "management-twin":
            for link in links.values():
                for side in ("interface_a", "interface_b"):
                    for before, after in ((3, 0), (4, 1), (5, 2)):
                        if link[side] == interface_id(MANAGEMENT_SWITCH_ID, before):
                            link[side] = interface_id(MANAGEMENT_SWITCH_ID, after)
        elif case == "missing":
            links.pop(ids[-1])
        elif case == "extra":
            links["unreviewed-link"] = {
                "interface_a": interface_id(MANAGEMENT_SWITCH_ID, 8),
                "interface_b": interface_id(ACCESS_NODE_ID, 2),
            }
        elif case == "duplicate":
            links[ids[-1]] = deepcopy(links[ids[-2]])
        else:
            nodes["unreviewed-node"] = {"label": "unreviewed"}
        if case in {"wrong", "swapped", "replaced", "management-twin", "duplicate"}:
            assert len(links) == 9
            assert set(nodes) == original_nodes

    reviewed = CURRENT_LIVE_REALIZATION
    operator, _ = operator_fixture(reviewed, mutate)
    with pytest.raises(ProfiledLiveCmlError, match=message):
        operator.anchor_profiled_live(catalog=reviewed)


def test_passive_projection_is_not_a_smaller_physical_lab():
    full = CURRENT_LIVE_REALIZATION
    selected = full.project(population_scope("passive", full.scope.identities[:2]))
    assert len(selected.anchors) == 2
    assert not selected.physical_links
    operator, requests = operator_fixture(full)
    with pytest.raises(
        ProfiledLiveCmlError, match="full reviewed LIVE physical topology"
    ):
        operator.anchor_profiled_live(catalog=selected)
    assert requests == []
    assert len(operator.anchor_profiled_live(catalog=full)) == 4


@pytest.mark.parametrize("case", ["foreign", "slot", "reused", "missing"])
def test_catalog_cannot_admit_unreviewed_or_inconsistent_physical_facts(case):
    from network_change_delivery.profiled_live_cml import ProfiledLiveRealizationCatalog

    data = CURRENT_LIVE_REALIZATION.model_dump(mode="json")
    if case == "foreign":
        data["physical_links"][0]["endpoints"][0]["node_id"] = (
            "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
        )
    elif case == "slot":
        data["physical_links"][-1]["endpoints"][1]["slot"] = 99
    elif case == "reused":
        data["physical_links"][1]["endpoints"][0]["slot"] = 3
    else:
        data["physical_links"].pop()
    with pytest.raises(ValueError):
        ProfiledLiveRealizationCatalog.model_validate(data)
