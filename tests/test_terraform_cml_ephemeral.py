import hashlib
import re
from pathlib import Path

ROOT = Path(__file__).parents[1]
CML_ROOT = ROOT / "infrastructure/cml"
EPHEMERAL_ROOT = CML_ROOT / "ephemeral"
MODULE_ROOT = CML_ROOT / "modules/twin"


def block(pattern: str, text: str) -> str:
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


def test_root_owned_lab_policy_and_shared_module_boundary() -> None:
    operator = (CML_ROOT / "topology.tf").read_text()
    ephemeral = (EPHEMERAL_ROOT / "topology.tf").read_text()
    operator_lab = block(r'resource\s+"cml2_lab"\s+"twin"\s*\{', operator)
    ephemeral_lab = block(r'resource\s+"cml2_lab"\s+"twin"\s*\{', ephemeral)
    assert "prevent_destroy" not in operator_lab
    assert "prevent_destroy" not in ephemeral_lab
    assert 'source = "./modules/twin"' in operator
    assert 'source = "../modules/twin"' in ephemeral
    assert "NCDP Staging ${var.staging_run_id}" in ephemeral_lab


def test_ephemeral_inputs_backend_and_outputs_are_secret_safe() -> None:
    variables = (EPHEMERAL_ROOT / "variables.tf").read_text()
    for name in (
        "staging_run_id",
        "twin_lifecycle_state",
        "core_02_bootstrap_hostname",
        "core_02_bootstrap_management_cidr",
        "core_02_bootstrap_username",
        "core_02_bootstrap_password",
        "edge_junos_01_bootstrap_hostname",
        "edge_junos_01_bootstrap_management_cidr",
        "edge_junos_01_bootstrap_username",
        "edge_junos_01_bootstrap_password_hash",
    ):
        variable = block(rf'variable\s+"{name}"\s*\{{', variables)
        assert re.search(r"(?m)^\s*default\s*=", variable) is None
    assert "^[a-z0-9][a-z0-9-]{0,39}$" in variables

    versions = (EPHEMERAL_ROOT / "versions.tf").read_text()
    backend = block(r'backend\s+"local"\s*\{', versions)
    assert "path" not in backend
    assert not list(CML_ROOT.rglob("*.tfvars"))
    assert not list(CML_ROOT.rglob("*.tfvars.json"))
    state_files = [
        path
        for path in CML_ROOT.rglob("*.tfstate")
        if ".terraform" not in path.relative_to(CML_ROOT).parts
    ]
    assert not state_files

    outputs = (EPHEMERAL_ROOT / "outputs.tf").read_text()
    assert set(re.findall(r'output\s+"([^"]+)"', outputs)) == {
        "staging_run_id",
        "lab_title",
        "lab_id",
        "node_ids",
        "link_ids",
        "lifecycle_state",
    }
    for forbidden in ("configuration", "username", "password", "verifier", "token"):
        assert forbidden not in outputs.lower()


def test_shared_realization_and_customizer_prerequisite_contract() -> None:
    topology = (MODULE_ROOT / "topology.tf").read_text()
    assert len(re.findall(r'(?m)^resource\s+"cml2_node"', topology)) == 4
    assert len(re.findall(r'(?m)^resource\s+"cml2_link"', topology)) == 4
    assert 'resource "cml2_lifecycle" "twin"' in topology
    assert "cat8000v-17-18-02" in (MODULE_ROOT / "data.tf").read_text()
    assert "vjunos-router-23-2r1-15" in (MODULE_ROOT / "data.tf").read_text()
    assert "bootstrap/cat8000v.tftpl" in topology
    assert "bootstrap/vjunos-router.tftpl" in topology

    expected_template_hashes = {
        "cat8000v.tftpl": (
            "3367be9ae8671104cc9e36c3918ea66578aa4724d5a0913e37e3ec18c22ffea3"
        ),
        "vjunos-router.tftpl": (
            "9a80fe144030ffb24b1c7ae8e0c270f1793a9f9e0a4a5e43b1564417741378c8"
        ),
    }
    for name, digest in expected_template_hashes.items():
        template = (MODULE_ROOT / "bootstrap" / name).read_bytes()
        assert hashlib.sha256(template).hexdigest() == digest

    outputs = (MODULE_ROOT / "outputs.tf").read_text()
    for role in (
        "system_bridge",
        "management_switch",
        "core_02",
        "edge_junos_01",
    ):
        assert re.search(rf"(?m)^\s*{role}\s*=\s*cml2_node\.{role}\.id$", outputs)
    for purpose in (
        "system_bridge_management",
        "management_core_02",
        "management_edge_junos_01",
        "core_02_edge_junos_01",
    ):
        assert re.search(rf"(?m)^\s*{purpose}\s*=\s*cml2_link\.{purpose}\.id$", outputs)

    documentation = "\n".join(
        (ROOT / path).read_text()
        for path in (
            "docs/architecture/ephemeral-cml-staging.md",
            "infrastructure/cml/README.md",
        )
    )
    prerequisite = "CML Configuration Customizer Scripts must already be enabled"
    assert prerequisite in documentation
    assert "must never be uploaded as a Buildkite artifact" in documentation
    assert "retains the exact run state" in documentation
