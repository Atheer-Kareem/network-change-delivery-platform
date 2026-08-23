import re
from pathlib import Path

ROOT = Path(__file__).parents[1]
TF_ROOT = ROOT / "infrastructure/cml"
TOPOLOGY = (TF_ROOT / "topology.tf").read_text()


def balanced_body(pattern: str, text: str) -> str:
    match = re.search(pattern, text)
    assert match is not None
    start = match.end()
    depth = 1
    for index in range(start, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[start:index]
    raise AssertionError("unterminated HCL block")


def resource_block(resource_type: str, name: str) -> str:
    return balanced_body(
        rf'resource\s+"{re.escape(resource_type)}"\s+"{re.escape(name)}"\s*\{{',
        TOPOLOGY,
    )


def assignment(body: str, name: str) -> str:
    match = re.search(rf"(?m)^\s*{re.escape(name)}\s*=\s*([^\n]+)", body)
    assert match is not None
    return match.group(1).strip()


def test_exact_resource_type_counts_and_no_structural_escape_hatches() -> None:
    resources = re.findall(r'(?m)^resource\s+"([^"]+)"\s+"[^"]+"\s*\{', TOPOLOGY)
    assert resources.count("cml2_lab") == 1
    assert resources.count("cml2_node") == 5
    assert resources.count("cml2_link") == 6
    assert resources.count("cml2_lifecycle") == 1
    assert len(resources) == 13
    all_hcl = "\n".join(path.read_text() for path in TF_ROOT.glob("*.tf"))
    for forbidden in ("module", "import", "moved", "removed"):
        assert re.search(rf"(?m)^\s*{forbidden}\s+", all_hcl) is None


def test_exact_node_contract_and_fail_closed_discovery() -> None:
    expected = {
        "system_bridge": ("system-bridge", "external_connector", None, None, None),
        "management_switch": (
            "management-switch",
            "unmanaged_switch",
            None,
            None,
            None,
        ),
        "core_02": ("core-02", "cat8000v", "accepted_cat8000v_images", "1", "4096"),
        "edge_junos_01": (
            "edge-junos-01",
            "vjunos-router",
            "accepted_vjunos_images",
            "4",
            "6144",
        ),
        "core_03": ("core-03", "cat8000v", "accepted_cat8000v_images", "1", "4096"),
    }
    for name, (label, nodedef, image_local, cpus, ram) in expected.items():
        body = resource_block("cml2_node", name)
        assert assignment(body, "label") == f'"{label}"'
        assert assignment(body, "nodedefinition") == f'"{nodedef}"'
        if image_local:
            assert f"local.{image_local}" in body
            assert assignment(body, "cpus") == cpus
            assert assignment(body, "ram") == ram

    bridge = resource_block("cml2_node", "system_bridge")
    assert assignment(bridge, "configuration") == (
        "one(local.system_bridge_matches).device_name"
    )
    assert "length(local.system_bridge_matches) == 1" in bridge
    assert "length(local.accepted_cat8000v_images) == 1" in resource_block(
        "cml2_node", "core_02"
    )
    assert "length(local.accepted_vjunos_images) == 1" in resource_block(
        "cml2_node", "edge_junos_01"
    )


def test_router_nodes_have_no_configuration_and_no_management_addresses() -> None:
    for name in ("core_02", "edge_junos_01", "core_03"):
        body = resource_block("cml2_node", name)
        assert re.search(r"(?m)^\s*configurations?\s*=", body) is None
    all_hcl = "\n".join(path.read_text() for path in TF_ROOT.glob("*.tf"))
    for address in ("192.168.4.14", "192.168.4.15", "192.168.4.20"):
        assert address not in all_hcl


def test_exact_link_slots_and_reserved_interfaces_remain_unlinked() -> None:
    expected = {
        "system_bridge_management": ("system_bridge", 0, "management_switch", 0),
        "management_core_02": ("management_switch", 1, "core_02", 0),
        "management_edge_junos_01": (
            "management_switch",
            2,
            "edge_junos_01",
            0,
        ),
        "management_core_03": ("management_switch", 3, "core_03", 0),
        "core_02_edge_junos_01": ("core_02", 3, "edge_junos_01", 1),
        "edge_junos_01_core_03": ("edge_junos_01", 2, "core_03", 2),
    }
    endpoints = set()
    for name, (node_a, slot_a, node_b, slot_b) in expected.items():
        body = resource_block("cml2_link", name)
        assert assignment(body, "node_a") == f"cml2_node.{node_a}.id"
        assert assignment(body, "slot_a") == str(slot_a)
        assert assignment(body, "node_b") == f"cml2_node.{node_b}.id"
        assert assignment(body, "slot_b") == str(slot_b)
        endpoints.update(((node_a, slot_a), (node_b, slot_b)))
    assert not endpoints.intersection(
        {("core_02", 1), ("core_02", 2), ("edge_junos_01", 3), ("core_03", 1)}
    )


def test_safe_lifecycle_contract_and_increment_guard() -> None:
    variables = (TF_ROOT / "variables.tf").read_text()
    variable = balanced_body(r'variable\s+"twin_lifecycle_state"\s*\{', variables)
    assert re.search(r"(?m)^\s*default\s*=", variable) is None
    allowed = re.search(r"contains\(\s*\[([^]]+)]", variable, re.DOTALL)
    assert allowed is not None
    assert re.findall(r'"([A-Z_]+)"', allowed.group(1)) == [
        "DEFINED_ON_CORE",
        "STARTED",
        "STOPPED",
    ]
    assert not list(TF_ROOT.rglob("*.tfvars"))

    lifecycle = resource_block("cml2_lifecycle", "twin")
    assert assignment(lifecycle, "state") == "var.twin_lifecycle_state"
    assert re.search(r'(?m)^\s*state\s*=\s*"STARTED"', TOPOLOGY) is None
    assert assignment(lifecycle, "wait") == "true"
    assert assignment(lifecycle, "start_remaining") == "false"
    assert (
        'stages          = ["terraform-stage-infra", "terraform-stage-router"]'
        in lifecycle
    )
    for name in (
        "system_bridge",
        "management_switch",
        "core_02",
        "edge_junos_01",
        "core_03",
    ):
        trigger = f'"${{cml2_node.{name}.id}}:${{cml2_node.{name}.generation}}"'
        assert trigger in lifecycle
    for forbidden in ("configs", "named_configs", "topology", "elements"):
        assert re.search(rf"(?m)^\s*{forbidden}\s*=", lifecycle) is None

    lab = resource_block("cml2_lab", "twin")
    assert "prevent_destroy = true" in lab


def test_defined_on_core_is_creation_or_reset_not_stopped_steady_state() -> None:
    readme = (TF_ROOT / "README.md").read_text()
    assert "first creation requires explicit `DEFINED_ON_CORE`" in readme
    assert "reset/wipe semantic" in readme
    assert "steady-state stop" in readme
