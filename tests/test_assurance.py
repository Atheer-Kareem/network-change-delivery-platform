from pathlib import Path

import pytest
from pydantic import ValidationError

from network_change_delivery.assurance import (
    AssuranceObservation,
    AssuranceOutcome,
    BatfishAssuranceIntent,
    CriticalFlow,
    FlowResult,
    ParseFileResult,
    ParseSummary,
    build_snapshot_manifest,
    evaluate_assurance,
)


def intent() -> BatfishAssuranceIntent:
    return BatfishAssuranceIntent(
        subject_digest="sha256:" + "1" * 64,
        expected_nodes=("core-02", "edge-junos-01", "core-03"),
        critical_flows=(
            CriticalFlow(
                source_node="core-02",
                source_ip="10.6.2.2",
                destination_ip="10.6.3.3",
            ),
        ),
    )


def observation(changed: int = 0, *, init: int = 0) -> AssuranceObservation:
    parse = ParseSummary(
        nodes=("core-02", "edge-junos-01", "core-03"),
        files=(ParseFileResult(relative_path="core.cfg", status="PASSED"),),
        initialization_issue_count=init,
    )
    return AssuranceObservation(
        pybatfish_version="test",
        batfish_version="server-test",
        baseline=parse,
        candidate=parse,
        flows=(
            FlowResult(
                source_node="core-02",
                source_ip="10.6.2.2",
                destination_ip="10.6.3.3",
                baseline_reachable=True,
                candidate_reachable=changed == 0,
            ),
        ),
        differential_changed_flow_count=changed,
    )


def manifests(tmp_path: Path):
    for state in ("baseline", "candidate"):
        configs = tmp_path / state / "configs"
        configs.mkdir(parents=True)
        (configs / "core.cfg").write_text("hostname core\n", encoding="utf-8")
    return (
        build_snapshot_manifest(tmp_path / "baseline"),
        build_snapshot_manifest(tmp_path / "candidate"),
    )


def test_manifest_is_deterministic_and_content_sensitive(tmp_path: Path) -> None:
    first, second = manifests(tmp_path)
    assert first.digest == second.digest
    (tmp_path / "candidate" / "configs" / "core.cfg").write_text(
        "hostname changed\n", encoding="utf-8"
    )
    assert build_snapshot_manifest(tmp_path / "candidate").digest != first.digest


def test_manifest_rejects_symlink_and_empty_snapshot(tmp_path: Path) -> None:
    empty = tmp_path / "empty" / "configs"
    empty.mkdir(parents=True)
    with pytest.raises(ValueError, match="empty"):
        build_snapshot_manifest(tmp_path / "empty")
    root = tmp_path / "links" / "configs"
    root.mkdir(parents=True)
    target = root / "real"
    target.write_text("hostname x\n", encoding="utf-8")
    (root / "link").symlink_to(target)
    with pytest.raises(ValueError, match="symlink"):
        build_snapshot_manifest(tmp_path / "links")


def test_manifest_count_and_size_boundaries(tmp_path: Path) -> None:
    root = tmp_path / "bounded" / "configs"
    root.mkdir(parents=True)
    for index in range(128):
        (root / f"{index:03d}.cfg").write_text("x", encoding="utf-8")
    assert len(build_snapshot_manifest(tmp_path / "bounded").files) == 128
    (root / "128.cfg").write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="bounded"):
        build_snapshot_manifest(tmp_path / "bounded")

    sized = tmp_path / "sized" / "configs"
    sized.mkdir(parents=True)
    (sized / "exact.cfg").write_bytes(b"x" * (4 * 1024 * 1024))
    assert (
        build_snapshot_manifest(tmp_path / "sized").files[0].size_bytes
        == 4 * 1024 * 1024
    )
    (sized / "over.cfg").write_bytes(b"x")
    with pytest.raises(ValueError, match="bounded"):
        build_snapshot_manifest(tmp_path / "sized")


def test_policy_passes_good_candidate(tmp_path: Path) -> None:
    baseline, candidate = manifests(tmp_path)
    result = evaluate_assurance(intent(), baseline, candidate, observation())
    assert result.outcome is AssuranceOutcome.PASSED
    assert result.differential_changed_flow_count == 0


def test_policy_fails_disruptive_candidate(tmp_path: Path) -> None:
    baseline, candidate = manifests(tmp_path)
    result = evaluate_assurance(intent(), baseline, candidate, observation(1))
    assert result.outcome is AssuranceOutcome.FAILED


def test_policy_fails_initialization_issue(tmp_path: Path) -> None:
    baseline, candidate = manifests(tmp_path)
    result = evaluate_assurance(intent(), baseline, candidate, observation(init=1))
    assert result.outcome is AssuranceOutcome.FAILED


def test_evidence_contains_no_configuration_content(tmp_path: Path) -> None:
    baseline, candidate = manifests(tmp_path)
    result = evaluate_assurance(intent(), baseline, candidate, observation())
    dumped = result.model_dump_json()
    assert "hostname core" not in dumped
    assert "raw" not in dumped


@pytest.mark.parametrize(
    "changes",
    [
        {"expected_nodes": ()},
        {"expected_nodes": ("core-02", "core-02")},
        {"critical_flows": ()},
        {
            "critical_flows": (
                CriticalFlow(
                    source_node="missing",
                    source_ip="10.0.0.1",
                    destination_ip="10.0.0.2",
                ),
            )
        },
        {
            "critical_flows": (
                CriticalFlow(
                    source_node="core-02",
                    source_ip="not-an-ip",
                    destination_ip="10.0.0.2",
                ),
            )
        },
    ],
)
def test_intent_contract_rejects_invalid_inputs(changes: dict) -> None:
    with pytest.raises(ValidationError):
        BatfishAssuranceIntent.model_validate(
            intent().model_copy(update=changes).model_dump()
        )


def test_policy_rejects_missing_parse_file(tmp_path: Path) -> None:
    baseline, candidate = manifests(tmp_path)
    observed = observation()
    observed = observed.model_copy(
        update={
            "baseline": observed.baseline.model_copy(update={"files": ()}),
        }
    )
    result = evaluate_assurance(intent(), baseline, candidate, observed)
    assert result.outcome is AssuranceOutcome.FAILED


def test_policy_rejects_missing_flow_observation(tmp_path: Path) -> None:
    baseline, candidate = manifests(tmp_path)
    observed = observation().model_copy(update={"flows": ()})
    result = evaluate_assurance(intent(), baseline, candidate, observed)
    assert result.outcome is AssuranceOutcome.FAILED
