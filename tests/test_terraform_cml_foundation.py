import re
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]
TF_ROOT = ROOT / "infrastructure/cml"
MODULE_ROOT = TF_ROOT / "modules/twin"
EPHEMERAL_ROOT = TF_ROOT / "ephemeral"


def test_exact_toolchain_and_backend_contract() -> None:
    versions = (TF_ROOT / "versions.tf").read_text()
    assert 'required_version = "= 1.15.8"' in versions
    assert 'source  = "CiscoDevNet/cml2"' in versions
    assert 'version = "= 0.9.3-beta1"' in versions
    backend = re.search(r'backend\s+"local"\s*\{([^}]*)\}', versions, re.DOTALL)
    assert backend is not None
    assert "path" not in backend.group(1)


def test_managed_resource_allow_list_and_provider_security() -> None:
    text = "\n".join(path.read_text() for path in sorted(TF_ROOT.rglob("*.tf")))
    assert not list(TF_ROOT.rglob("*.tfvars"))
    resources = re.findall(r'(?m)^resource\s+"([^"]+)"\s+"([^"]+)"\s*\{', text)
    assert resources.count(("cml2_lab", "twin")) == 2
    assert set(resources) == {
        ("cml2_lab", "twin"),
        ("cml2_node", "system_bridge"),
        ("cml2_node", "management_switch"),
        ("cml2_node", "core_02"),
        ("cml2_node", "edge_junos_01"),
        ("cml2_node", "core_03"),
        ("cml2_link", "system_bridge_management"),
        ("cml2_link", "management_core_02"),
        ("cml2_link", "management_edge_junos_01"),
        ("cml2_link", "management_core_03"),
        ("cml2_link", "core_02_edge_junos_01"),
        ("cml2_link", "edge_junos_01_core_03"),
        ("cml2_lifecycle", "twin"),
    }
    for block in ("import", "moved", "removed"):
        assert re.search(rf"(?m)^\s*{block}\s+", text) is None

    provider = "\n".join(
        path.read_text()
        for path in (TF_ROOT / "provider.tf", EPHEMERAL_ROOT / "provider.tf")
    )
    for credential in (
        "address",
        "token",
        "username",
        "password",
        "cacert",
        "request_headers",
        "token_cache_file",
    ):
        assert re.search(rf"(?m)^\s*{credential}\s*=", provider) is None
    assert re.search(r"(?m)^\s*skip_verify\s*=\s*false$", provider)
    assert re.search(r"(?m)^\s*token_cache\s*=\s*false$", provider)
    assert "use_cache" not in provider


def test_data_source_and_fail_closed_selection_contract() -> None:
    data = (MODULE_ROOT / "data.tf").read_text()
    outputs = (MODULE_ROOT / "outputs.tf").read_text()
    assert 'data "cml2_system" "controller"' in data
    assert 'data "cml2_connector" "system_bridge"' in data
    assert 'label = "System Bridge"' in data
    assert data.count('data "cml2_images"') == 2
    assert 'nodedefinition = "cat8000v"' in data
    assert 'nodedefinition = "vjunos-router"' in data
    assert 'image.id == "cat8000v-17-18-02"' in data
    assert 'image.id == "vjunos-router-23-2r1-15"' in data
    module_text = "\n".join(path.read_text() for path in MODULE_ROOT.glob("*.tf"))
    assert "bridge0" not in module_text
    assert "virbr0" not in module_text
    assert outputs.count("precondition {") == 3
    assert "length(local.system_bridge_matches) == 1" in outputs
    assert "length(local.accepted_cat8000v_images) == 1" in outputs
    assert "length(local.accepted_vjunos_images) == 1" in outputs


def test_lock_and_ignore_contract() -> None:
    for root in (TF_ROOT, EPHEMERAL_ROOT):
        lock = (root / ".terraform.lock.hcl").read_text()
        assert 'version     = "0.9.3-beta1"' in lock
        assert 'constraints = "0.9.3-beta1"' in lock
        assert lock.count('provider "registry.terraform.io/ciscodevnet/cml2"') == 1
    gitignore = (ROOT / ".gitignore").read_text()
    assert ".terraform.lock.hcl" not in gitignore
    dockerignore = (ROOT / ".dockerignore").read_text()
    assert "**/.terraform" in dockerignore


def test_buildkite_terraform_contract_and_existing_gates() -> None:
    pipeline = yaml.safe_load((ROOT / ".buildkite/pipeline.yml").read_text())
    steps = {step["key"]: step for step in pipeline["steps"]}
    quality = {step["key"]: step for step in steps["quality"]["steps"]}
    terraform = quality["quality-terraform-cml"]
    command = terraform["command"]
    assert (
        "hashicorp/terraform:1.15.8@"
        "sha256:7ae513256f7ce67879e218ae8593d6fbe216ec9e123abe6c94e4e10704857963"
        in command
    )
    assert terraform["agents"]["queue"] == "ncdp-validation"
    assert "${PWD}:/workspace:ro" in command
    assert "TF_DATA_DIR=/tmp/terraform-data-operator" in command
    assert "TF_DATA_DIR=/tmp/terraform-data-ephemeral" in command
    assert "-backend=false" in command
    assert "-lockfile=readonly" in command
    assert "terraform -chdir=infrastructure/cml validate" in command
    assert "terraform -chdir=infrastructure/cml/ephemeral validate" in command
    assert "CML2_" not in command
    assert not re.search(r"terraform[^\n]*(plan|apply|import|destroy)", command)
    protected = steps["protected-delivery"]
    assert 'build.branch == "main"' in protected["if"]
    assert "build.pull_request.id == null" in protected["if"]
    protected_steps = {step["key"]: step for step in protected["steps"]}
    assert protected_steps["deploy-gate"]["agents"]["queue"] == "ncdp-deploy"
