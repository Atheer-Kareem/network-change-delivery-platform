import hashlib
import re
from pathlib import Path

ROOT = Path(__file__).parents[1]
CML_ROOT = ROOT / "infrastructure/cml"
EPHEMERAL_ROOT = CML_ROOT / "ephemeral"
MODULE_ROOT = CML_ROOT / "modules/managed-pair"


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


def test_root_owned_lab_policy_and_managed_pair_boundary() -> None:
    operator = (CML_ROOT / "topology.tf").read_text()
    ephemeral = (EPHEMERAL_ROOT / "topology.tf").read_text()
    operator_lab = block(r'resource\s+"cml2_lab"\s+"twin"\s*\{', operator)
    ephemeral_lab = block(r'resource\s+"cml2_lab"\s+"staging"\s*\{', ephemeral)
    assert "prevent_destroy" not in operator_lab
    assert "prevent_destroy" not in ephemeral_lab
    assert 'source = "./modules/twin"' in operator
    assert 'source = "../modules/managed-pair"' in ephemeral
    assert 'module "managed_pair"' in ephemeral
    assert "NCDP Staging ${var.staging_run_id}" in ephemeral_lab
    assert "not live/reference or a brownfield topology clone" in ephemeral_lab


def test_ephemeral_inputs_backend_and_outputs_are_secret_safe() -> None:
    variables = (EPHEMERAL_ROOT / "variables.tf").read_text()
    for name in (
        "staging_run_id",
        "lifecycle_state",
        "cisco_bootstrap_hostname",
        "cisco_bootstrap_management_cidr",
        "cisco_bootstrap_username",
        "cisco_bootstrap_password",
        "junos_bootstrap_hostname",
        "junos_bootstrap_management_cidr",
        "junos_bootstrap_username",
        "junos_bootstrap_password_hash",
    ):
        variable = block(rf'variable\s+"{name}"\s*\{{', variables)
        assert re.search(r"(?m)^\s*default\s*=", variable) is None
    assert "^[a-z0-9][a-z0-9-]{0,39}$" in variables

    versions = (EPHEMERAL_ROOT / "versions.tf").read_text()
    backend = block(r'backend\s+"local"\s*\{', versions)
    assert "path" not in backend
    assert not list(CML_ROOT.rglob("*.tfvars"))
    assert not list(CML_ROOT.rglob("*.tfvars.json"))
    assert not [
        path
        for path in CML_ROOT.rglob("*.tfstate")
        if ".terraform" not in path.relative_to(CML_ROOT).parts
    ]

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


def test_managed_pair_exact_graph_and_no_core_03() -> None:
    topology = (MODULE_ROOT / "topology.tf").read_text()
    node_names = set(re.findall(r'(?m)^resource\s+"cml2_node"\s+"([^"]+)"', topology))
    link_names = set(re.findall(r'(?m)^resource\s+"cml2_link"\s+"([^"]+)"', topology))
    lifecycle_names = set(
        re.findall(r'(?m)^resource\s+"cml2_lifecycle"\s+"([^"]+)"', topology)
    )
    assert node_names == {"system_bridge", "management_switch", "cisco", "junos"}
    assert link_names == {
        "system_bridge_management",
        "management_cisco",
        "management_junos",
        "cisco_junos",
    }
    assert lifecycle_names == {"managed_pair"}
    assert 1 + len(node_names) + len(link_names) + len(lifecycle_names) == 10
    assert "core_03" not in topology
    assert "core-03" not in topology

    lifecycle = block(r'resource\s+"cml2_lifecycle"\s+"managed_pair"\s*\{', topology)
    for role in node_names:
        assert f"cml2_node.{role}.id" in lifecycle
        assert f"cml2_node.{role}.generation" in lifecycle
    assert len(re.findall(r"cml2_link\.[a-z_]+,", lifecycle)) == 4


def test_managed_pair_bootstrap_outputs_and_images() -> None:
    topology = (MODULE_ROOT / "topology.tf").read_text()
    assert "cat8000v-17-18-02" in (MODULE_ROOT / "data.tf").read_text()
    assert "vjunos-router-23-2r1-15" in (MODULE_ROOT / "data.tf").read_text()
    assert "bootstrap/cat8000v.tftpl" in topology
    assert "bootstrap/vjunos-router.tftpl" in topology
    assert "cat8000v-unmanaged.tftpl" not in topology

    expected_template_hashes = {
        "cat8000v.tftpl": (
            "c7f2bd6fed987fd9ba8fa8e0d2361b79f7848ca4a71d343d969bc6235ed12e32"
        ),
        "vjunos-router.tftpl": (
            "76c61083d844683329851c80d789b46f105a27ddf803bfd601cac021b821fdff"
        ),
    }
    assert {path.name for path in (MODULE_ROOT / "bootstrap").iterdir()} == set(
        expected_template_hashes
    )
    for name, digest in expected_template_hashes.items():
        actual = hashlib.sha256(
            (MODULE_ROOT / "bootstrap" / name).read_bytes()
        ).hexdigest()
        assert actual == digest

    outputs = (MODULE_ROOT / "outputs.tf").read_text()
    for role in ("system_bridge", "management_switch", "cisco", "junos"):
        assert re.search(rf"(?m)^\s*{role}\s*=\s*cml2_node\.{role}\.id$", outputs)
    for purpose in (
        "system_bridge_management",
        "management_cisco",
        "management_junos",
        "cisco_junos",
    ):
        assert re.search(rf"(?m)^\s*{purpose}\s*=\s*cml2_link\.{purpose}\.id$", outputs)
    assert "core_03" not in outputs


def test_managed_pair_validation_and_customizer_prerequisite_contract() -> None:
    variables = (MODULE_ROOT / "variables.tf").read_text()
    assert "must be a valid IOS hostname" in variables
    assert "must be a valid IPv4 CIDR" in variables
    assert "must be non-empty and contain no whitespace" in variables
    assert "must be a SHA-512-crypt verifier" in variables

    documentation = "\n".join(
        (ROOT / path).read_text()
        for path in (
            "docs/architecture/ephemeral-cml-staging.md",
            "infrastructure/cml/README.md",
        )
    )
    assert (
        "CML Configuration Customizer Scripts must already be enabled" in documentation
    )
    assert "must never be uploaded as a Buildkite artifact" in documentation
    assert "retains the exact run state" in documentation
