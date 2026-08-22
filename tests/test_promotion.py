from pathlib import Path

import pytest
import yaml

from network_change_delivery.assurance import (
    AssuranceObservation,
    FlowResult,
    ParseFileResult,
    ParseSummary,
    build_snapshot_manifest,
)
from network_change_delivery.plan_assurance import assure_plan, load_plan
from network_change_delivery.promotion import (
    MAX_SOURCE_BYTES,
    PromotionError,
    _read_source,
    create_promotion_bundle,
    verify_promotion_bundle,
)

ROOT = Path(__file__).parents[1]
PLAN = ROOT / "fixtures/batfish/plans/fleet-interface-description.json"
POLICY = ROOT / "fixtures/batfish/policy.yaml"
BASELINE = ROOT / "fixtures/batfish/baseline"


def _record():
    plan = load_plan(PLAN)
    policy = __import__(
        "network_change_delivery.plan_assurance", fromlist=["BatfishAssurancePolicy"]
    ).BatfishAssurancePolicy.model_validate(yaml.safe_load(POLICY.read_text()))

    class Provider:
        def analyze(self, baseline, candidate, _intent):
            def summary(root):
                manifest = build_snapshot_manifest(root)
                return ParseSummary(
                    files=tuple(
                        ParseFileResult(relative_path=f.relative_path, status="PASSED")
                        for f in manifest.files
                    ),
                    nodes=tuple(sorted(policy.expected_nodes)),
                    initialization_issue_count=0,
                )

            return AssuranceObservation(
                pybatfish_version="2025.7.7.2423",
                batfish_version="2026.07.20.3565",
                baseline=summary(baseline),
                candidate=summary(candidate),
                flows=(
                    FlowResult(
                        source_node="core-02",
                        source_ip="10.6.2.2",
                        destination_ip="10.6.3.3",
                        baseline_reachable=True,
                        candidate_reachable=True,
                    ),
                ),
                differential_changed_flow_count=0,
            )

    return assure_plan(plan, policy, BASELINE, Provider())


def test_promotion_bundle_and_tamper_checks(tmp_path: Path) -> None:
    assurance = tmp_path / "assurance.json"
    assurance.write_text(_record().model_dump_json(), encoding="utf-8")
    destination = tmp_path / "promotion"
    manifest = create_promotion_bundle(
        PLAN, POLICY, BASELINE, assurance, "a" * 40, destination
    )
    assert manifest.verify_digest()
    assert destination.stat().st_mode & 0o777 == 0o700
    for path in destination.rglob("*"):
        if path.is_file():
            assert path.stat().st_mode & 0o777 == 0o600
    assert verify_promotion_bundle(destination, "a" * 40).digest == manifest.digest
    with pytest.raises(PromotionError):
        verify_promotion_bundle(destination, "b" * 40)
    (destination / "extra.txt").write_text("x", encoding="utf-8")
    with pytest.raises(PromotionError):
        verify_promotion_bundle(destination, "a" * 40)


def test_extra_directory_rejected(tmp_path: Path) -> None:
    assurance = tmp_path / "assurance.json"
    assurance.write_text(_record().model_dump_json(), encoding="utf-8")
    destination = tmp_path / "promotion"
    create_promotion_bundle(PLAN, POLICY, BASELINE, assurance, "a" * 40, destination)
    (destination / "unexpected").mkdir()
    with pytest.raises(PromotionError):
        verify_promotion_bundle(destination, "a" * 40)


def test_existing_destination_rejected(tmp_path: Path) -> None:
    assurance = tmp_path / "assurance.json"
    assurance.write_text(_record().model_dump_json(), encoding="utf-8")
    destination = tmp_path / "promotion"
    destination.mkdir()
    with pytest.raises(PromotionError):
        create_promotion_bundle(
            PLAN, POLICY, BASELINE, assurance, "a" * 40, destination
        )


@pytest.mark.parametrize("name", ["plan.json", "policy.yaml", "assurance.json"])
def test_source_symlink_rejected(tmp_path: Path, name: str) -> None:
    target = tmp_path / "target"
    target.write_bytes(b"{}")
    link = tmp_path / name
    link.symlink_to(target)
    with pytest.raises(PromotionError):
        _read_source(link)


def test_source_size_limit_and_overflow(tmp_path: Path) -> None:
    exact = tmp_path / "exact"
    exact.write_bytes(b"x" * MAX_SOURCE_BYTES)
    assert len(_read_source(exact)) == MAX_SOURCE_BYTES
    over = tmp_path / "over"
    over.write_bytes(b"x" * (MAX_SOURCE_BYTES + 1))
    with pytest.raises(PromotionError, match="exceeds bounded"):
        _read_source(over)


def test_malformed_plan_is_bounded_error(tmp_path: Path) -> None:
    bad = tmp_path / "bad-plan.json"
    bad.write_text("not-json", encoding="utf-8")
    from network_change_delivery.promotion import _load_plan_bytes

    with pytest.raises(PromotionError, match="invalid promotion plan"):
        _load_plan_bytes(_read_source(bad))
