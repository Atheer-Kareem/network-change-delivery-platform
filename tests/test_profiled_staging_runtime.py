"""Fake-only fencing tests for the profiled Terraform staging runtime."""

from __future__ import annotations

import importlib.util
import sys
from itertools import pairwise
from pathlib import Path
from types import ModuleType

import pytest

from network_change_delivery.profiled_staging import (
    PROFILED_STAGING_TERRAFORM_ADDRESSES,
    ProfiledStagingAmbiguousError,
    ProfiledStagingError,
    ProfiledStagingReadinessOutcome,
    retire_profiled_staging_run_directory,
    terraform_managed_state_addresses,
    terraform_profiled_device_variables,
    validate_destroy_only_plan,
    validate_profiled_staging_evidence_path,
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
    value._state_backup_path = tmp_path / "terraform.tfstate.backup"
    value._recovery_inputs = tmp_path / "recovery-inputs.tfvars.json"
    value._owned_lab_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    return value


def _write_valid_recovery_inputs(run: Path, run_id: str) -> Path:
    from test_profiled_realization import inventory_devices

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
    path = run / "recovery-inputs.tfvars.json"
    write_recovery_inputs(
        path,
        {
            "staging_run_id": run_id,
            "lifecycle_state": "DEFINED_ON_CORE",
            "devices": values,
        },
    )
    return path


def _readiness_operations(tmp_path: Path):
    from test_profiled_realization import inventory_devices

    module = load_script("run_profiled_cml_staging")
    value = module.LocalTerraformOperations.__new__(module.LocalTerraformOperations)
    value._run_id = "run-001"
    value._run_directory = tmp_path
    value._devices = inventory_devices()
    value._readiness = {}
    value._readiness_results = {}
    value.readiness_evidence = ()
    value.readiness_deadline_seconds = 180
    node_ids = {
        str(device.logical_name).replace("-", "_"): f"node-{device.logical_name}"
        for device in value._devices
    }
    return module, value, node_ids


class _Connection:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, duration: float) -> None:
        self.now += duration


class _NodeReader:
    def __init__(
        self,
        *,
        fail_for: str | None = None,
        state: str = "BOOTED",
    ) -> None:
        self.fail_for = fail_for
        self.state = state
        self.closed = False

    def item(self, _lab_id: str, _kind: str, node_id: str):
        if self.fail_for and self.fail_for in node_id:
            raise ProfiledStagingError("bounded diagnostic failure")
        return {"state": self.state}

    def close(self) -> None:
        self.closed = True


def _patch_readiness_observations(
    monkeypatch: pytest.MonkeyPatch,
    module: ModuleType,
    value,
    clock: _Clock,
    *,
    state_at,
    ready_at: dict[str, float],
) -> list[float]:
    observations: list[float] = []
    address_names = {
        str(device.management_endpoints.staging.binding.l3_endpoint.address.ip): str(
            device.logical_name
        )
        for device in value._devices
    }
    monkeypatch.setattr(module.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(module.time, "sleep", clock.sleep)

    def observe(devices, _node_ids, _lab_id):
        observations.append(clock.now)
        return {
            str(device.logical_name): state_at(str(device.logical_name), clock.now)
            for device in devices
        }

    def connect(target, **_kwargs):
        name = address_names[target[0]]
        if clock.now >= ready_at.get(name, float("inf")):
            return _Connection()
        raise ConnectionRefusedError

    monkeypatch.setattr(value, "_observe_readiness_node_states", observe)
    monkeypatch.setattr(module.socket, "create_connection", connect)
    return observations


def test_partial_ready_transitional_device_extends_at_normal_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module, value, node_ids = _readiness_operations(tmp_path)
    clock = _Clock()
    observations = _patch_readiness_observations(
        monkeypatch,
        module,
        value,
        clock,
        state_at=lambda name, _now: "STARTED" if name == "transit-ios-01" else "BOOTED",
        ready_at={
            "core-02": 0,
            "edge-junos-01": 0,
            "access-sw-01": 0,
        },
    )

    with pytest.raises(ProfiledStagingError, match="readiness timed out"):
        value._wait_readiness(node_ids, "lab-001")

    by_name = {item.logical_name: item for item in value.readiness_evidence}
    assert by_name["transit-ios-01"].outcome is (
        ProfiledStagingReadinessOutcome.TIMED_OUT
    )
    assert by_name["transit-ios-01"].cml_node_state == "STARTED"
    assert by_name["transit-ios-01"].first_booted_seconds is None
    assert by_name["transit-ios-01"].elapsed_seconds == 300
    assert value.readiness_deadline_seconds == 300
    assert clock.now == 300
    assert observations[:4] == [0, 10, 20, 30]
    assert all(
        later - earlier == module._READINESS_STATE_POLL_SECONDS
        for earlier, later in pairwise(observations)
    )


def test_all_unresolved_transitional_population_extends_to_absolute_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module, value, node_ids = _readiness_operations(tmp_path)
    clock = _Clock()
    _patch_readiness_observations(
        monkeypatch,
        module,
        value,
        clock,
        state_at=lambda _name, _now: "BOOTING",
        ready_at={},
    )

    with pytest.raises(ProfiledStagingError, match="readiness timed out"):
        value._wait_readiness(node_ids, "lab-001")

    assert value.readiness_deadline_seconds == 300
    assert clock.now == 300
    assert all(
        item.outcome is ProfiledStagingReadinessOutcome.TIMED_OUT
        and item.cml_node_state == "BOOTING"
        and item.first_booted_seconds is None
        for item in value.readiness_evidence
    )


def test_post_boot_grace_from_175_expires_at_235(
    tmp_path: Path,
) -> None:
    module, value, _node_ids = _readiness_operations(tmp_path)
    transit = {value._devices[2]}
    states = {"transit-ios-01": "BOOTED"}
    first_booted = {"transit-ios-01": 175.0}

    assert value._extension_is_admitted(transit, states, first_booted, 180)
    assert not value._post_boot_grace_expired(transit, states, first_booted, 234.999)
    assert value._post_boot_grace_expired(transit, states, first_booted, 235)
    assert module._POST_BOOT_SERVICE_GRACE_SECONDS == 60


def test_device_booted_since_100_gets_full_normal_window_without_extension(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module, value, node_ids = _readiness_operations(tmp_path)
    clock = _Clock()
    _patch_readiness_observations(
        monkeypatch,
        module,
        value,
        clock,
        state_at=lambda name, now: (
            "BOOTED" if name != "transit-ios-01" or now >= 100 else "STARTED"
        ),
        ready_at={
            "core-02": 0,
            "edge-junos-01": 0,
            "access-sw-01": 0,
        },
    )

    with pytest.raises(ProfiledStagingError, match="readiness timed out"):
        value._wait_readiness(node_ids, "lab-001")

    transit = {item.logical_name: item for item in value.readiness_evidence}[
        "transit-ios-01"
    ]
    assert transit.first_booted_seconds == 100
    assert transit.elapsed_seconds == 180
    assert transit.cml_node_state == "BOOTED"
    assert value.readiness_deadline_seconds == 180


def test_booted_from_start_never_shortens_normal_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module, value, node_ids = _readiness_operations(tmp_path)
    clock = _Clock()
    _patch_readiness_observations(
        monkeypatch,
        module,
        value,
        clock,
        state_at=lambda _name, _now: "BOOTED",
        ready_at={
            "core-02": 0,
            "edge-junos-01": 0,
            "access-sw-01": 0,
        },
    )

    with pytest.raises(ProfiledStagingError, match="readiness timed out"):
        value._wait_readiness(node_ids, "lab-001")

    transit = {item.logical_name: item for item in value.readiness_evidence}[
        "transit-ios-01"
    ]
    assert transit.first_booted_seconds == 0
    assert transit.elapsed_seconds == 180
    assert transit.cml_node_state == "BOOTED"
    assert value.readiness_deadline_seconds == 180
    assert clock.now == 180


def test_partial_ready_device_booted_at_180_can_become_ready_at_195(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module, value, node_ids = _readiness_operations(tmp_path)
    clock = _Clock()
    _patch_readiness_observations(
        monkeypatch,
        module,
        value,
        clock,
        state_at=lambda name, now: (
            "BOOTED" if name != "transit-ios-01" or now >= 180 else "STARTED"
        ),
        ready_at={
            "core-02": 0,
            "edge-junos-01": 0,
            "access-sw-01": 0,
            "transit-ios-01": 195,
        },
    )

    observed = value._wait_readiness(node_ids, "lab-001")

    transit = {item.logical_name: item for item in value.readiness_evidence}[
        "transit-ios-01"
    ]
    assert len(observed) == 4
    assert transit.outcome is ProfiledStagingReadinessOutcome.READY
    assert transit.elapsed_seconds == 195
    assert transit.first_booted_seconds == 180
    assert transit.cml_node_state == "BOOTED"
    assert value.readiness_deadline_seconds == 300


def test_partial_ready_device_booted_at_180_times_out_after_grace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module, value, node_ids = _readiness_operations(tmp_path)
    clock = _Clock()
    _patch_readiness_observations(
        monkeypatch,
        module,
        value,
        clock,
        state_at=lambda name, now: (
            "BOOTED" if name != "transit-ios-01" or now >= 180 else "STARTED"
        ),
        ready_at={
            "core-02": 0,
            "edge-junos-01": 0,
            "access-sw-01": 0,
        },
    )

    with pytest.raises(ProfiledStagingError, match="readiness timed out"):
        value._wait_readiness(node_ids, "lab-001")

    transit = {item.logical_name: item for item in value.readiness_evidence}[
        "transit-ios-01"
    ]
    assert transit.outcome is ProfiledStagingReadinessOutcome.TIMED_OUT
    assert transit.elapsed_seconds == 240
    assert transit.first_booted_seconds == 180
    assert transit.cml_node_state == "BOOTED"
    assert value.readiness_deadline_seconds == 300


def test_device_booted_at_280_is_capped_by_absolute_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module, value, node_ids = _readiness_operations(tmp_path)
    clock = _Clock()
    _patch_readiness_observations(
        monkeypatch,
        module,
        value,
        clock,
        state_at=lambda name, now: (
            "BOOTED" if name != "transit-ios-01" or now >= 280 else "STARTED"
        ),
        ready_at={
            "core-02": 0,
            "edge-junos-01": 0,
            "access-sw-01": 0,
        },
    )

    with pytest.raises(ProfiledStagingError, match="readiness timed out"):
        value._wait_readiness(node_ids, "lab-001")

    transit = {item.logical_name: item for item in value.readiness_evidence}[
        "transit-ios-01"
    ]
    assert transit.first_booted_seconds == 280
    assert transit.elapsed_seconds == 300
    assert value.readiness_deadline_seconds == 300


def test_unknown_state_at_normal_deadline_does_not_reuse_stale_transition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module, value, node_ids = _readiness_operations(tmp_path)
    clock = _Clock()
    _patch_readiness_observations(
        monkeypatch,
        module,
        value,
        clock,
        state_at=lambda name, now: (
            ("STARTED" if now < 180 else None) if name == "transit-ios-01" else "BOOTED"
        ),
        ready_at={
            "core-02": 0,
            "edge-junos-01": 0,
            "access-sw-01": 0,
        },
    )

    with pytest.raises(ProfiledStagingError, match="readiness timed out"):
        value._wait_readiness(node_ids, "lab-001")

    transit = {item.logical_name: item for item in value.readiness_evidence}[
        "transit-ios-01"
    ]
    assert transit.cml_node_state is None
    assert transit.first_booted_seconds is None
    assert transit.elapsed_seconds == 180
    assert value.readiness_deadline_seconds == 180
    assert clock.now == 180


def test_unknown_cml_state_does_not_grant_extension(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module, value, node_ids = _readiness_operations(tmp_path)
    clock = _Clock()
    _patch_readiness_observations(
        monkeypatch,
        module,
        value,
        clock,
        state_at=lambda _name, _now: None,
        ready_at={
            "core-02": 0,
            "edge-junos-01": 0,
            "access-sw-01": 0,
        },
    )

    with pytest.raises(ProfiledStagingError, match="readiness timed out"):
        value._wait_readiness(node_ids, "lab-001")

    transit = {item.logical_name: item for item in value.readiness_evidence}[
        "transit-ios-01"
    ]
    assert transit.cml_node_state is None
    assert transit.first_booted_seconds is None
    assert transit.elapsed_seconds == 180
    assert value.readiness_deadline_seconds == 180


def test_cml_observation_failure_does_not_invent_boot_progress(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module, value, node_ids = _readiness_operations(tmp_path)
    reader = _NodeReader(fail_for="transit-ios-01", state="BOOTED")
    monkeypatch.setattr(
        module.ProfiledStagingCmlReader,
        "from_environment",
        staticmethod(lambda: reader),
    )

    states = value._observe_readiness_node_states(
        set(value._devices), node_ids, "lab-001"
    )

    assert states["transit-ios-01"] is None
    assert all(
        state == "BOOTED" for name, state in states.items() if name != "transit-ios-01"
    )
    assert reader.closed is True


def test_all_four_ready_before_normal_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module, value, node_ids = _readiness_operations(tmp_path)
    clock = _Clock()
    _patch_readiness_observations(
        monkeypatch,
        module,
        value,
        clock,
        state_at=lambda _name, _now: "BOOTED",
        ready_at={
            "core-02": 5,
            "edge-junos-01": 5,
            "transit-ios-01": 5,
            "access-sw-01": 5,
        },
    )

    observed = value._wait_readiness(node_ids, "lab-001")

    assert len(observed) == 4
    assert value.readiness_deadline_seconds == 180
    assert all(
        item.outcome is ProfiledStagingReadinessOutcome.READY
        and item.elapsed_seconds == 5
        and item.readiness_evidence is not None
        and item.first_booted_seconds == 0
        for item in value.readiness_evidence
    )


def test_production_readiness_deadlines_are_180_and_300_seconds() -> None:
    module = load_script("run_profiled_cml_staging")
    assert module._READINESS_NORMAL_TIMEOUT_SECONDS == 180
    assert module._READINESS_MAX_TIMEOUT_SECONDS == 300
    assert module._READINESS_STATE_POLL_SECONDS == 10
    assert module._POST_BOOT_SERVICE_GRACE_SECONDS == 60
    assert not hasattr(module, "_READINESS_TIMEOUT_SECONDS")
    assert "900" not in (ROOT / "scripts/run_profiled_cml_staging.py").read_text()


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


def test_real_terraform_1_15_empty_state_shape_has_no_managed_resources() -> None:
    assert terraform_managed_state_addresses({"format_version": "1.0"}) == set()


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"format_version": "1.1"},
        {"format_version": "1.0", "unexpected": None},
        {"format_version": "1.0", "values": None},
        {"values": {}},
    ],
)
def test_malformed_empty_state_lookalike_is_rejected(payload: object) -> None:
    with pytest.raises(ProfiledStagingError, match="Terraform state rejected"):
        terraform_managed_state_addresses(payload)


def test_empty_state_is_observation_not_destructive_authority() -> None:
    state = terraform_managed_state_addresses({"format_version": "1.0"})
    with pytest.raises(ProfiledStagingError, match="state is not admitted"):
        validate_destroy_only_plan(state, {})


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


def test_uncertain_destroy_with_malformed_state_remains_ambiguous(
    tmp_path: Path,
) -> None:
    value = operations(tmp_path)
    first = True

    def state_addresses():
        nonlocal first
        if first:
            first = False
            return set(PROFILED_STAGING_TERRAFORM_ADDRESSES)
        raise ProfiledStagingError("profiled staging Terraform state rejected")

    value._state_addresses = state_addresses
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
    with pytest.raises(ProfiledStagingAmbiguousError, match="outcome is ambiguous"):
        value.destroy_owned(require_complete=True)
    assert [call[0] for call in calls].count("apply") == 1


def test_valid_empty_state_and_absent_lab_permit_state_retirement(
    tmp_path: Path,
) -> None:
    run = tmp_path / "run-001"
    run.mkdir(mode=0o700)
    run.chmod(0o700)
    value = operations(run)
    _write_valid_recovery_inputs(run, "run-001")
    for name in (
        "terraform.tfstate",
        "terraform.tfstate.backup",
        "create.tfplan",
        "start.tfplan",
        "destroy.tfplan",
    ):
        (run / name).write_text("retained", encoding="utf-8")
    (run / "terraform-data/providers").mkdir(parents=True)
    (run / "terraform-data/providers/cache").write_text("cache", encoding="utf-8")
    (run / "trust").mkdir()
    (run / "trust/known_hosts").write_text("public-key", encoding="utf-8")
    acceptance = tmp_path / "acceptance/profiled-staging-evidence.json"
    acceptance.parent.mkdir()
    acceptance.write_text("historical evidence", encoding="utf-8")
    value._state_addresses = lambda: terraform_managed_state_addresses(
        {"format_version": "1.0"}
    )
    value._lab_is_absent = lambda: True

    value.verify_absent()
    value.retire_state()

    assert not run.exists()
    assert tmp_path.exists()
    assert acceptance.read_text(encoding="utf-8") == "historical evidence"


@pytest.mark.parametrize("remaining", [True, False])
def test_run_directory_retirement_requires_empty_state_and_cml_absence(
    tmp_path: Path, remaining: bool
) -> None:
    run = tmp_path / "run-001"
    run.mkdir(mode=0o700)
    run.chmod(0o700)
    value = operations(run)
    _write_valid_recovery_inputs(run, "run-001")
    value._state_addresses = lambda: (
        {"cml2_lab.profiled_staging"} if remaining else set()
    )
    value._lab_is_absent = lambda: remaining

    with pytest.raises(
        ProfiledStagingError,
        match=("Terraform state remains" if remaining else "absence cannot be proven"),
    ):
        value.retire_state()
    assert run.is_dir()


def test_exact_run_directory_retirement_rejects_wrong_or_unsafe_identity(
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir(mode=0o700)
    outside.chmod(0o700)
    wrong = outside / "wrong-name"
    wrong.mkdir(mode=0o700)
    wrong.chmod(0o700)
    with pytest.raises(ProfiledStagingError, match="run identity"):
        retire_profiled_staging_run_directory(wrong, "run-001", tmp_path / "checkout")
    assert wrong.is_dir()

    target = outside / "target"
    target.mkdir(mode=0o700)
    target.chmod(0o700)
    symlink = outside / "run-001"
    symlink.symlink_to(target, target_is_directory=True)
    with pytest.raises(ProfiledStagingError, match="run directory"):
        retire_profiled_staging_run_directory(symlink, "run-001", tmp_path / "checkout")
    assert target.is_dir()

    checkout = tmp_path / "checkout"
    checkout.mkdir(mode=0o700)
    checkout.chmod(0o700)
    inside = checkout / "run-001"
    inside.mkdir(mode=0o700)
    inside.chmod(0o700)
    with pytest.raises(ProfiledStagingError, match="run directory"):
        retire_profiled_staging_run_directory(inside, "run-001", checkout)
    assert checkout.is_dir()
    assert inside.is_dir()


def test_acceptance_evidence_must_remain_outside_disposable_run(
    tmp_path: Path,
) -> None:
    run = tmp_path / "run-001"
    run.mkdir(mode=0o700)
    run.chmod(0o700)
    acceptance = tmp_path / "acceptance"
    acceptance.mkdir(mode=0o700)
    acceptance.chmod(0o700)
    outside = acceptance / "evidence.json"
    assert validate_profiled_staging_evidence_path(outside, run) == outside
    with pytest.raises(ProfiledStagingError, match="evidence path"):
        validate_profiled_staging_evidence_path(run / "evidence.json", run)


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
