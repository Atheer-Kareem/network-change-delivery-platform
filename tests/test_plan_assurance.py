import json
from pathlib import Path

import pytest
import yaml

from network_change_delivery.assurance import (
    AssuranceObservation,
    FlowResult,
    ParseFileResult,
    ParseSummary,
    prepare_snapshot,
)
from network_change_delivery.plan_assurance import (
    AssuranceOutcome,
    BatfishAssurancePolicy,
    PlanAssuranceError,
    assure_plan,
    load_plan,
    materialize_candidate,
    subject_from_plan,
)

ROOT = Path(__file__).parents[1]


def plan():
    return load_plan(ROOT / "fixtures/batfish/plans/fleet-interface-description.json")


def policy():
    return BatfishAssurancePolicy.model_validate(
        yaml.safe_load((ROOT / "fixtures/batfish/policy.yaml").read_text())
    )


def test_subject_and_policy_digests_are_deterministic() -> None:
    p, pol = plan(), policy()
    assert subject_from_plan(p).plan_digest == p.digest
    assert (
        pol.calculated_digest()
        == "sha256:73abec7fbac0a8c986236c159415a94a9f7c88cc9a18236067f4736e35bcae91"
    )
    assert p.verify_digest()


def test_candidate_matches_reference_fixture() -> None:
    with prepare_snapshot(ROOT / "fixtures/batfish/baseline") as baseline:
        candidate, mutations = materialize_candidate(baseline, plan())
        try:
            assert candidate.manifest.digest == (
                "sha256:38809e5c4169676edb2adb0859cf21cc1401b09788fd9c446730247af1497808"
            )
            assert len(mutations) == 3
            assert (
                "ge-0/0/1 description transit-to-core-03"
                in (candidate.root / "configs/edge-junos-01.cfg").read_text()
            )
        finally:
            candidate.__exit__()


def test_bad_plan_digest_rejected() -> None:
    payload = plan().model_dump(mode="json")
    payload["digest"] = "sha256:" + "0" * 64
    path = ROOT / "fixtures/batfish/plans/.invalid-plan-test.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    try:
        with pytest.raises(PlanAssuranceError):
            load_plan(path)
    finally:
        path.unlink()


def test_assure_plan_provider_result_is_bound() -> None:
    pol = policy()

    class FakeProvider:
        def analyze(self, baseline: Path, candidate: Path, _intent):
            def summary(root: Path) -> ParseSummary:
                files = tuple(
                    ParseFileResult(relative_path=f.relative_path, status="PASSED")
                    for f in __import__(
                        "network_change_delivery.assurance",
                        fromlist=["build_snapshot_manifest"],
                    )
                    .build_snapshot_manifest(root)
                    .files
                )
                return ParseSummary(
                    files=files,
                    nodes=tuple(sorted(pol.expected_nodes)),
                    initialization_issue_count=0,
                )

            flow = FlowResult(
                source_node="core-02",
                source_ip="10.6.2.2",
                destination_ip="10.6.3.3",
                baseline_reachable=True,
                candidate_reachable=True,
            )
            return AssuranceObservation(
                pybatfish_version="2025.7.7.2423",
                batfish_version="2026.07.20.3565",
                baseline=summary(baseline),
                candidate=summary(candidate),
                flows=(flow,),
                differential_changed_flow_count=0,
            )

    record = assure_plan(
        plan(), pol, ROOT / "fixtures/batfish/baseline", FakeProvider()
    )
    assert record.outcome is AssuranceOutcome.PASSED
    assert record.verify_digest()


def test_verifier_rejects_changed_policy_without_provider() -> None:
    pol = policy()

    class FakeProvider:
        def analyze(self, baseline: Path, candidate: Path, _intent):
            from network_change_delivery.assurance import build_snapshot_manifest

            def summary(root: Path) -> ParseSummary:
                manifest = build_snapshot_manifest(root)
                return ParseSummary(
                    files=tuple(
                        ParseFileResult(relative_path=f.relative_path, status="PASSED")
                        for f in manifest.files
                    ),
                    nodes=tuple(sorted(pol.expected_nodes)),
                    initialization_issue_count=0,
                )

            flow = FlowResult(
                source_node="core-02",
                source_ip="10.6.2.2",
                destination_ip="10.6.3.3",
                baseline_reachable=True,
                candidate_reachable=True,
            )
            return AssuranceObservation(
                pybatfish_version="2025.7.7.2423",
                batfish_version="2026.07.20.3565",
                baseline=summary(baseline),
                candidate=summary(candidate),
                flows=(flow,),
                differential_changed_flow_count=0,
            )

    record = assure_plan(
        plan(), pol, ROOT / "fixtures/batfish/baseline", FakeProvider()
    )
    changed = pol.model_copy(update={"require_no_differential_reachability": False})
    from network_change_delivery.plan_assurance import verify_plan_assurance

    assert not verify_plan_assurance(
        plan(), changed, ROOT / "fixtures/batfish/baseline", record
    )


def test_compliant_member_drift_blocks_derivation() -> None:
    payload = plan().model_dump(mode="json")
    member = payload["members"][2]
    member.update(
        classification="COMPLIANT",
        current_description="reviewed-transit-description",
        desired_description="reviewed-transit-description",
        child_plan=None,
    )
    payload["waves"] = []
    from network_change_delivery.models import FleetDeploymentPlan

    fleet = FleetDeploymentPlan.model_validate(
        {**payload, "digest": "sha256:" + "0" * 64}
    ).model_copy(update={"digest": "sha256:" + "0" * 64})
    fleet = fleet.model_copy(update={"digest": fleet.calculated_digest()})
    with (
        prepare_snapshot(ROOT / "fixtures/batfish/baseline") as baseline,
        pytest.raises(PlanAssuranceError),
    ):
        materialize_candidate(baseline, fleet)
