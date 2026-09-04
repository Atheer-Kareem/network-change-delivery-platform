"""Fake-only fencing tests for the profiled Terraform staging runtime."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

from network_change_delivery.profiled_staging import (
    PROFILED_STAGING_TERRAFORM_ADDRESSES,
    ProfiledStagingAmbiguousError,
    ProfiledStagingError,
    terraform_managed_state_addresses,
    terraform_profiled_device_variables,
    validate_destroy_only_plan,
    write_recovery_inputs,
)
from network_change_delivery.secrets import DeviceCredentials

ROOT = Path(__file__).parents[1]


def load_script(name: str) -> ModuleType:
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def operations(tmp_path: Path):
    module = load_script("run_profiled_cml_staging")
    value = module.LocalTerraformOperations.__new__(module.LocalTerraformOperations)
    value._run_id = "run-001"
    value._run_directory = tmp_path
    value._state_path = tmp_path / "terraform.tfstate"
    value._recovery_inputs = tmp_path / "recovery-inputs.tfvars.json"
    value._owned_lab_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    return value


def test_start_uses_one_inspected_saved_plan(tmp_path: Path) -> None:
    value = operations(tmp_path)
    calls: list[tuple[str, ...]] = []
    value._var_file_arguments = lambda: ["-var-file=recovery-inputs.tfvars.json"]
    value._planned_actions = lambda _plan: {"cml2_lifecycle.profiled_staging": "update"}
    value._secure_file = lambda _path: None
    value._terraform = lambda arguments, **_kwargs: calls.append(tuple(arguments))
    value._apply_start()
    assert len(calls) == 2
    assert calls[0][0] == "plan"
    assert "-out" in calls[0]
    assert calls[1][0] == "apply"
    assert "-auto-approve" not in {item for call in calls for item in call}


def test_state_authority_excludes_data_sources_and_rejects_unknown_managed() -> None:
    payload = {
        "values": {
            "root_module": {
                "resources": [
                    {"mode": "data", "address": "data.cml2_system.controller"},
                    {"mode": "managed", "address": "cml2_lab.profiled_staging"},
                ]
            }
        }
    }
    assert terraform_managed_state_addresses(payload) == {"cml2_lab.profiled_staging"}
    state = terraform_managed_state_addresses(payload)
    with pytest.raises(ProfiledStagingError):
        validate_destroy_only_plan(state | {"unknown.resource"}, {})


def test_start_rejects_unexpected_change_before_apply(tmp_path: Path) -> None:
    value = operations(tmp_path)
    calls: list[tuple[str, ...]] = []
    value._var_file_arguments = lambda: ["-var-file=recovery-inputs.tfvars.json"]
    value._planned_actions = lambda _plan: {
        "cml2_lifecycle.profiled_staging": "update",
        "cml2_node.system_bridge": "update",
    }
    value._secure_file = lambda _path: None
    value._terraform = lambda arguments, **_kwargs: calls.append(tuple(arguments))
    with pytest.raises(ProfiledStagingError, match="START plan"):
        value._apply_start()
    assert len(calls) == 1


@pytest.mark.parametrize("complete", [True, False])
def test_destroy_applies_exact_saved_delete_plan_once(
    tmp_path: Path, complete: bool
) -> None:
    value = operations(tmp_path)
    state = set(PROFILED_STAGING_TERRAFORM_ADDRESSES)
    if not complete:
        state = set(tuple(state)[:4])
    calls: list[tuple[str, ...]] = []
    value._state_addresses = lambda: state
    value._var_file_arguments = lambda: ["-var-file=recovery-inputs.tfvars.json"]
    value._planned_actions = lambda _plan: dict.fromkeys(state, "delete")
    value._secure_file = lambda _path: None
    value._terraform = lambda arguments, **_kwargs: calls.append(tuple(arguments))
    value.destroy_owned(require_complete=complete)
    assert [call[0] for call in calls] == ["plan", "apply"]
    assert "-destroy" in calls[0]
    assert "-auto-approve" not in {item for call in calls for item in call}


def test_complete_destroy_rejects_partial_state(tmp_path: Path) -> None:
    value = operations(tmp_path)
    state = set(tuple(PROFILED_STAGING_TERRAFORM_ADDRESSES)[:4])
    calls: list[tuple[str, ...]] = []
    value._state_addresses = lambda: state
    value._var_file_arguments = lambda: ["-var-file=recovery-inputs.tfvars.json"]
    value._planned_actions = lambda _plan: dict.fromkeys(state, "delete")
    value._secure_file = lambda _path: None
    value._terraform = lambda arguments, **_kwargs: calls.append(tuple(arguments))
    with pytest.raises(ProfiledStagingError, match="not complete"):
        value.destroy_owned(require_complete=True)
    assert [call[0] for call in calls] == ["plan"]


def test_uncertain_destroy_is_reconciled_without_replay(tmp_path: Path) -> None:
    value = operations(tmp_path)
    state_reads = iter((set(PROFILED_STAGING_TERRAFORM_ADDRESSES), set()))
    value._state_addresses = lambda: next(state_reads)
    value._var_file_arguments = lambda: ["-var-file=recovery-inputs.tfvars.json"]
    value._planned_actions = lambda _plan: dict.fromkeys(
        PROFILED_STAGING_TERRAFORM_ADDRESSES, "delete"
    )
    value._secure_file = lambda _path: None
    calls: list[tuple[str, ...]] = []

    def terraform(arguments, **_kwargs):
        calls.append(tuple(arguments))
        if arguments[0] == "apply":
            raise ProfiledStagingAmbiguousError("uncertain destroy")

    value._terraform = terraform
    value._lab_is_absent = lambda: True
    value.destroy_owned(require_complete=True)
    assert [call[0] for call in calls].count("apply") == 1


def test_recovery_is_variable_file_bound_and_has_no_openbao_dependency() -> None:
    source = (ROOT / "scripts/recover_profiled_cml_staging.py").read_text(
        encoding="utf-8"
    )
    assert "recovery-inputs.tfvars.json" in source
    assert "-var-file=" in source
    assert "load_recovery_inputs" in source
    assert "OpenBao" not in source
    assert "SecretProvider" not in source
    assert 'terraform", "destroy' not in source


def test_recovery_executes_exact_retained_subset_without_openbao(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from test_profiled_realization import inventory_devices

    module = load_script("recover_profiled_cml_staging")
    run = tmp_path / "run-001"
    run.mkdir(mode=0o700)
    state_path = run / "terraform.tfstate"
    state_path.write_text("{}", encoding="utf-8")
    state_path.chmod(0o600)
    devices = inventory_devices()
    credentials = {
        str(device.logical_name): DeviceCredentials(
            username="operator", password="unused"
        )
        for device in devices
    }
    verifiers = {
        "core-02": "$9$ncdpCoreSalt1$abcdefghijklmnop",
        "edge-junos-01": "$6$ncdpJunosSalt$abcdefghijklmnop",
        "transit-ios-01": "$9$ncdpTransitSalt$abcdefghijklmnop",
        "access-sw-01": "$9$ncdpAccessSalt1$abcdefghijklmnop",
    }
    values = terraform_profiled_device_variables(devices, credentials, verifiers)
    for name, address in {
        "core_02": "192.168.4.30/24",
        "edge_junos_01": "192.168.4.40/24",
        "transit_ios_01": "192.168.4.31/24",
        "access_sw_01": "192.168.4.32/24",
    }.items():
        values[name]["management_cidr"] = address
    input_path = run / module.RECOVERY_INPUTS_NAME
    write_recovery_inputs(
        input_path,
        {
            "staging_run_id": "run-001",
            "lifecycle_state": "DEFINED_ON_CORE",
            "devices": values,
        },
    )
    retained = set(tuple(PROFILED_STAGING_TERRAFORM_ADDRESSES)[:4])
    state_reads = iter((retained, set()))
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(module, "_state_addresses", lambda _run: next(state_reads))
    monkeypatch.setattr(
        module,
        "_destroy_actions",
        lambda _run, _plan: dict.fromkeys(retained, "delete"),
    )
    monkeypatch.setattr(
        module,
        "_lab_binding",
        lambda _run: (
            "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            "NCDP Staging run-001",
        ),
    )
    monkeypatch.setattr(module, "_verify_absence", lambda _lab_id: None)
    monkeypatch.setattr(
        module,
        "_terraform",
        lambda _run, arguments, **_kwargs: calls.append(tuple(arguments)) or "",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "recover_profiled_cml_staging.py",
            "--run-id",
            "run-001",
            "--run-directory",
            str(run),
            "--execute",
        ],
    )
    assert module.main() == 0
    assert any(call[0] == "init" for call in calls)
    assert any(call[0] == "apply" for call in calls)
    assert not state_path.exists()
    assert not input_path.exists()


def test_runtime_has_no_write_adapter_or_unfenced_terraform_mutation() -> None:
    source = (ROOT / "scripts/run_profiled_cml_staging.py").read_text(encoding="utf-8")
    for forbidden in (
        "ProfiledWriteAdapter",
        "execute_profiled_plan",
        'terraform", "destroy',
        "-auto-approve",
    ):
        assert forbidden not in source
    assert "validate_start_only_plan" in source
    assert "validate_destroy_only_plan" in source
