import re
from pathlib import Path

ROOT = Path(__file__).parents[1]
TF_ROOT = ROOT / "infrastructure/cml"
MODULE_ROOT = TF_ROOT / "modules/twin"
EPHEMERAL_ROOT = TF_ROOT / "ephemeral"
ROOT_TOPOLOGY = (TF_ROOT / "topology.tf").read_text()
TOPOLOGY = (MODULE_ROOT / "topology.tf").read_text()


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
    assert resources.count("cml2_node") == 5
    assert resources.count("cml2_link") == 6
    assert resources.count("cml2_lifecycle") == 1
    assert len(resources) == 12
    assert ROOT_TOPOLOGY.count('resource "cml2_lab" "twin"') == 1
    assert ROOT_TOPOLOGY.count('module "twin"') == 1
    ephemeral = (EPHEMERAL_ROOT / "topology.tf").read_text()
    assert ephemeral.count('resource "cml2_lab" "twin"') == 1
    assert ephemeral.count('module "twin"') == 1
    all_hcl = "\n".join(path.read_text() for path in TF_ROOT.rglob("*.tf"))
    for forbidden in ("import", "moved", "removed"):
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


def test_router_day0_templates_are_sensitive_and_narrow() -> None:
    core_02 = resource_block("cml2_node", "core_02")
    assert assignment(core_02, "configuration").startswith("sensitive(templatefile(")
    assert "bootstrap/cat8000v.tftpl" in core_02
    for variable in (
        "core_02_bootstrap_hostname",
        "core_02_bootstrap_management_cidr",
        "core_02_bootstrap_username",
        "core_02_bootstrap_password",
    ):
        assert f"var.{variable}" in core_02

    edge = resource_block("cml2_node", "edge_junos_01")
    assert assignment(edge, "configuration").startswith("sensitive(templatefile(")
    assert "bootstrap/vjunos-router.tftpl" in edge
    for variable in (
        "edge_junos_01_bootstrap_hostname",
        "edge_junos_01_bootstrap_management_cidr",
        "edge_junos_01_bootstrap_username",
        "edge_junos_01_bootstrap_password_hash",
    ):
        assert f"var.{variable}" in edge

    core_03 = resource_block("cml2_node", "core_03")
    assert "bootstrap/cat8000v-unmanaged.tftpl" in core_03
    assert re.search(r"(?m)^\s*configurations\s*=", core_03) is None
    for forbidden in ("username", "password", "secret", "community"):
        assert forbidden not in core_03.lower()

    bootstrap = (MODULE_ROOT / "bootstrap/cat8000v-unmanaged.tftpl").read_text()
    assert "hostname core-03" in bootstrap
    assert "platform console serial" in bootstrap
    for forbidden in ("username", "password", "secret", "ip address", "netconf"):
        assert forbidden not in bootstrap.lower()

    bridge = resource_block("cml2_node", "system_bridge")
    assert assignment(bridge, "configuration") == (
        "one(local.system_bridge_matches).device_name"
    )
    management_switch = resource_block("cml2_node", "management_switch")
    assert re.search(r"(?m)^\s*configurations?\s*=", management_switch) is None

    all_hcl = "\n".join(path.read_text() for path in TF_ROOT.rglob("*.tf"))
    for address in ("192.168.4.14", "192.168.4.15", "192.168.4.20"):
        assert address not in all_hcl

    template = (MODULE_ROOT / "bootstrap/cat8000v.tftpl").read_text()
    assert "interface GigabitEthernet1" in template
    assert "netconf-yang" in template
    assert "GigabitEthernet2" not in template
    assert "description" not in template
    assert "192.168.4.14" not in template

    junos_template = (MODULE_ROOT / "bootstrap/vjunos-router.tftpl").read_text()
    assert "root-login deny" in junos_template
    assert "ssh-ed25519" in junos_template
    assert "class super-user" in junos_template
    assert 'encrypted-password "${password_hash}"' in junos_template
    assert "netconf" in junos_template
    assert "fxp0" in junos_template
    for forbidden in (
        "ge-0/0/",
        "description",
        "static",
        "protocols",
        "ciscoCML",
        "192.168.4.20",
    ):
        assert forbidden not in junos_template


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
    variables = (MODULE_ROOT / "variables.tf").read_text()
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

    operator_lab = balanced_body(r'resource\s+"cml2_lab"\s+"twin"\s*\{', ROOT_TOPOLOGY)
    ephemeral_lab = balanced_body(
        r'resource\s+"cml2_lab"\s+"twin"\s*\{',
        (EPHEMERAL_ROOT / "topology.tf").read_text(),
    )
    assert "prevent_destroy" not in operator_lab
    assert "prevent_destroy" not in ephemeral_lab


def test_ephemeral_run_identity_and_required_inputs_fail_closed() -> None:
    variables = (EPHEMERAL_ROOT / "variables.tf").read_text()
    run_id = balanced_body(r'variable\s+"staging_run_id"\s*\{', variables)
    assert re.search(r"(?m)^\s*default\s*=", run_id) is None
    assert "{0,39}" in run_id
    for name in (
        "twin_lifecycle_state",
        "core_02_bootstrap_username",
        "core_02_bootstrap_password",
        "edge_junos_01_bootstrap_username",
        "edge_junos_01_bootstrap_password_hash",
    ):
        body = balanced_body(rf'variable\s+"{name}"\s*\{{', variables)
        assert re.search(r"(?m)^\s*default\s*=", body) is None

    versions = (EPHEMERAL_ROOT / "versions.tf").read_text()
    backend = balanced_body(r'backend\s+"local"\s*\{', versions)
    assert "path" not in backend
    assert "/Users/" not in "\n".join(
        path.read_text() for path in EPHEMERAL_ROOT.rglob("*") if path.is_file()
    )


def test_defined_on_core_is_creation_or_reset_not_stopped_steady_state() -> None:
    readme = (TF_ROOT / "README.md").read_text()
    assert "first creation requires explicit `DEFINED_ON_CORE`" in readme
    assert "reset/wipe semantic" in readme
    assert "steady-state stop" in readme
