from pathlib import Path

import pytest
from pydantic import ValidationError

from network_change_delivery.assurance import (
    AssuranceEvidence,
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


def test_parse_summary_rejects_duplicate_identities() -> None:
    with pytest.raises(ValidationError, match="parse file identities"):
        ParseSummary(
            files=(
                ParseFileResult(relative_path="a.cfg", status="PASSED"),
                ParseFileResult(relative_path="a.cfg", status="PASSED"),
            ),
            nodes=("core-02",),
            initialization_issue_count=0,
        )
    with pytest.raises(ValidationError, match="node identities"):
        ParseSummary(
            files=(ParseFileResult(relative_path="a.cfg", status="PASSED"),),
            nodes=("core-02", "core-02"),
            initialization_issue_count=0,
        )


def test_evidence_semantics_reject_contradictory_outcomes(tmp_path: Path) -> None:
    baseline, candidate = manifests(tmp_path)
    good = evaluate_assurance(intent(), baseline, candidate, observation())
    with pytest.raises(ValidationError):
        AssuranceEvidence.model_validate(
            good.model_copy(
                update={"outcome": AssuranceOutcome.PASSED, "invariants": ()}
            ).model_dump()
        )
    with pytest.raises(ValidationError):
        AssuranceEvidence.model_validate(
            good.model_copy(
                update={"outcome": AssuranceOutcome.BLOCKED, "failure_reason": None}
            ).model_dump()
        )


def test_short_reads_are_assembled(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import network_change_delivery.assurance as assurance

    root = tmp_path / "snap" / "configs"
    root.mkdir(parents=True)
    payload = b"hostname short-read\n"
    (root / "node.cfg").write_bytes(payload)
    original = assurance.os.read

    def short_read(fd: int, count: int) -> bytes:
        return original(fd, min(count, 2))

    monkeypatch.setattr(assurance.os, "read", short_read)
    assert build_snapshot_manifest(tmp_path / "snap").files[0].size_bytes == len(
        payload
    )


def test_short_writes_are_assembled(monkeypatch: pytest.MonkeyPatch) -> None:
    import network_change_delivery.assurance as assurance

    original = assurance.os.write

    def short_write(fd: int, data: bytes) -> int:
        return original(fd, data[:2])

    monkeypatch.setattr(assurance.os, "write", short_write)
    with assurance.prepare_snapshot_from_bytes(
        (("node.cfg", b"hostname node\n"),)
    ) as prepared:
        assert (prepared.root / "configs/node.cfg").read_bytes() == b"hostname node\n"


def test_zero_progress_write_fails_and_cleans(monkeypatch: pytest.MonkeyPatch) -> None:
    import network_change_delivery.assurance as assurance

    monkeypatch.setattr(assurance.os, "write", lambda _fd, _data: 0)
    with pytest.raises(OSError, match="no progress"):
        assurance.prepare_snapshot_from_bytes((("node.cfg", b"hostname node\n"),))


def test_write_failure_cleans_staging(monkeypatch: pytest.MonkeyPatch) -> None:
    import network_change_delivery.assurance as assurance

    created: list[Path] = []
    original_mkdtemp = assurance.tempfile.mkdtemp

    def capture(*args: object, **kwargs: object) -> str:
        path = original_mkdtemp(*args, **kwargs)
        created.append(Path(path))
        return path

    monkeypatch.setattr(assurance.tempfile, "mkdtemp", capture)

    def fail_write(_fd: int, _data: bytes) -> int:
        raise OSError("write failed")

    monkeypatch.setattr(assurance.os, "write", fail_write)
    with pytest.raises(OSError, match="write failed"):
        assurance.prepare_snapshot_from_bytes((("node.cfg", b"hostname node\n"),))
    assert created and not created[0].exists()
