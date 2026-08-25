from pathlib import Path

import pytest

from network_change_delivery.ephemeral_staging import (
    StagingError,
    run_staging_lifecycle,
    validate_recovery_destroy_graph,
)


class Operations:
    def __init__(self, failure: str | None = None) -> None:
        self.failure = failure
        self.calls: list[str] = []
        self.created = False

    @property
    def managed_resources_exist(self) -> bool:
        return self.created

    def _call(self, name: str) -> None:
        self.calls.append(name)
        if self.failure == name:
            raise StagingError(f"{name} failed")

    def admit(self) -> None:
        self._call("admit")

    def create(self, _evidence) -> None:
        self._call("create")
        self.created = True

    def start(self, _evidence) -> None:
        self._call("start")

    def validate(self, _evidence) -> None:
        self._call("validate")

    def destroy(self, _evidence) -> None:
        self._call("destroy")

    def verify_absent(self, _evidence) -> None:
        self._call("verify_absent")

    def retire_state(self, _evidence) -> None:
        self._call("retire_state")
        self.created = False


def test_create_failure_before_resources_does_not_cleanup(tmp_path: Path) -> None:
    operations = Operations("create")
    result = run_staging_lifecycle("run-1", tmp_path / "run", operations)
    assert operations.calls == ["admit", "create"]
    assert result.overall_result == "failed"


def test_validation_failure_triggers_destroy_and_preserves_primary(
    tmp_path: Path,
) -> None:
    operations = Operations("validate")
    result = run_staging_lifecycle("run-1", tmp_path / "run", operations)
    assert operations.calls[-3:] == ["destroy", "verify_absent", "retire_state"]
    assert result.primary_failure == "validate failed"
    assert result.overall_result == "failed"


@pytest.mark.parametrize("failure", ["destroy", "verify_absent"])
def test_cleanup_failure_retains_state(tmp_path: Path, failure: str) -> None:
    operations = Operations(failure)
    result = run_staging_lifecycle("run-1", tmp_path / "run", operations)
    assert "retire_state" not in operations.calls
    assert operations.created
    assert result.cleanup_failure == f"{failure} failed"


def test_cleanup_does_not_overwrite_primary_failure(tmp_path: Path) -> None:
    operations = Operations("validate")

    def failed_destroy(_evidence) -> None:
        operations.calls.append("destroy")
        raise StagingError("destroy failed")

    operations.destroy = failed_destroy
    result = run_staging_lifecycle("run-1", tmp_path / "run", operations)
    assert result.primary_failure == "validate failed"
    assert result.cleanup_failure == "destroy failed"


def test_successful_lifecycle_retires_state(tmp_path: Path) -> None:
    operations = Operations()
    result = run_staging_lifecycle("run-1", tmp_path / "run", operations)
    assert result.overall_result == "passed"
    assert result.state_retirement_outcome == "passed"
    assert not operations.created


def test_duplicate_run_state_fails_closed(tmp_path: Path) -> None:
    run_directory = tmp_path / "run"
    run_directory.mkdir()
    (run_directory / "terraform.tfstate").write_text("{}", encoding="utf-8")
    operations = Operations()
    result = run_staging_lifecycle("run-1", run_directory, operations)
    assert operations.calls == []
    assert result.primary_failure == (
        "run-scoped state already exists; recovery is required"
    )


def test_recovery_accepts_only_exact_delete_subset() -> None:
    expected = {"cml2_lab.twin", "module.twin.cml2_node.core_02"}
    validate_recovery_destroy_graph(
        {"cml2_lab.twin"}, expected, {"cml2_lab.twin": "delete"}
    )
    with pytest.raises(StagingError, match="state addresses"):
        validate_recovery_destroy_graph(
            {"unrelated.resource"}, expected, {"unrelated.resource": "delete"}
        )
    with pytest.raises(StagingError, match="graph is not exact"):
        validate_recovery_destroy_graph(
            {"cml2_lab.twin"}, expected, {"cml2_lab.twin": "update"}
        )
    with pytest.raises(StagingError, match="graph is not exact"):
        validate_recovery_destroy_graph({"cml2_lab.twin"}, expected, {})
