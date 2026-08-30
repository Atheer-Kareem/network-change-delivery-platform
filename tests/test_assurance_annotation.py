"""Contracts for the allowlisted Buildkite assurance presentation."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from network_change_delivery.assurance import (
    AssuranceObservation,
    AssuranceProviderError,
    FlowResult,
    ParseFileResult,
    ParseSummary,
    build_snapshot_manifest,
)
from network_change_delivery.plan_assurance import (
    AssuranceOutcome,
    BatfishAssurancePolicy,
    assure_plan,
    load_plan,
)

ROOT = Path(__file__).parents[1]
INPUTS = ROOT / "deployments/live/promotion"

_SPEC = importlib.util.spec_from_file_location(
    "render_assurance_annotation",
    ROOT / "scripts/buildkite/render_assurance_annotation.py",
)
assert _SPEC and _SPEC.loader
_RENDERER = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_RENDERER)


def _policy() -> BatfishAssurancePolicy:
    return BatfishAssurancePolicy.model_validate(
        yaml.safe_load((INPUTS / "policy.yaml").read_text(encoding="utf-8"))
    )


class _Provider:
    def __init__(self, *, reverse_reachable: bool = True) -> None:
        self.reverse_reachable = reverse_reachable

    def analyze(self, baseline: Path, candidate: Path, intent):
        def summary(root: Path) -> ParseSummary:
            manifest = build_snapshot_manifest(root)
            return ParseSummary(
                files=tuple(
                    ParseFileResult(relative_path=item.relative_path, status="PASSED")
                    for item in manifest.files
                ),
                nodes=tuple(sorted(intent.expected_nodes)),
                initialization_issue_count=0,
            )

        return AssuranceObservation(
            pybatfish_version="safe-version",
            batfish_version="safe-version",
            service_identity="secret-provider-detail",
            baseline=summary(baseline),
            candidate=summary(candidate),
            flows=tuple(
                FlowResult(
                    source_node=flow.source_node,
                    source_ip=flow.source_ip,
                    destination_ip=flow.destination_ip,
                    baseline_reachable=True,
                    candidate_reachable=(
                        self.reverse_reachable
                        if flow.source_node == "edge-junos-01"
                        else True
                    ),
                )
                for flow in intent.critical_flows
            ),
            differential_changed_flow_count=0,
        )


def _record(*, reverse_reachable: bool = True):
    return assure_plan(
        load_plan(INPUTS / "plan.json"),
        _policy(),
        INPUTS / "baseline",
        _Provider(reverse_reachable=reverse_reachable),
    )


def test_annotation_contains_only_reviewable_allowlisted_assurance_fields() -> None:
    record = _record()
    assert record.outcome is AssuranceOutcome.PASSED

    rendered = _RENDERER.render_annotation(record)

    for value in (
        "PASSED",
        record.subject.change_id,
        record.subject.plan_digest,
        record.policy_digest,
        record.digest,
        record.baseline_snapshot_digest,
        record.candidate_snapshot_digest,
        "core-02",
        "edge-junos-01",
        "10.6.12.1",
        "10.6.12.2",
        "Differential changed-flow count",
        "critical_flow:core-02:10.6.12.2",
        "critical_flow:edge-junos-01:10.6.12.1",
    ):
        assert value in rendered

    serialized = record.model_dump_json()
    assert "secret-provider-detail" in serialized
    assert "secret-provider-detail" not in rendered
    assert "safe-version" not in rendered
    assert "ncdp_snmp_d2_v1" in serialized
    assert "ncdp_snmp_d2_v1" not in rendered
    assert "candidate_derivation" not in rendered
    assert "failure_reason" not in rendered
    assert "detail" not in rendered
    for baseline in sorted((INPUTS / "baseline/configs").iterdir()):
        assert baseline.read_text(encoding="utf-8") not in rendered


def test_annotation_represents_failed_flow_invariant_without_raw_detail() -> None:
    record = _record(reverse_reachable=False)
    assert record.outcome is AssuranceOutcome.FAILED

    rendered = _RENDERER.render_annotation(record)

    assert "**Outcome:** `FAILED`" in rendered
    assert (
        "`edge-junos-01` | `10.6.12.2` | `10.6.12.1` | **PASS** | **FAIL**" in rendered
    )
    assert "**FAIL** — `critical_flow:edge-junos-01:10.6.12.1`" in rendered
    assert "critical flow is reachable in both snapshots" not in rendered


def test_annotation_omits_blocked_provider_failure_reason() -> None:
    class BlockedProvider:
        def analyze(self, *_):
            raise AssuranceProviderError("raw provider token-like failure")

    record = assure_plan(
        load_plan(INPUTS / "plan.json"),
        _policy(),
        INPUTS / "baseline",
        BlockedProvider(),
    )
    assert record.outcome is AssuranceOutcome.BLOCKED

    rendered = _RENDERER.render_annotation(record)

    assert "**Outcome:** `BLOCKED`" in rendered
    assert "raw provider token-like failure" not in rendered
    assert "No analyzed invariant results were available." in rendered


def test_loader_rejects_malformed_tampered_and_symlinked_evidence(
    tmp_path: Path,
) -> None:
    malformed = tmp_path / "malformed.json"
    malformed.write_text("{}", encoding="utf-8")
    with pytest.raises(ValidationError):
        _RENDERER.load_record(malformed)

    record = _record()
    tampered = tmp_path / "tampered.json"
    tampered.write_text(
        record.model_copy(update={"digest": "sha256:" + "0" * 64}).model_dump_json(),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="digest verification"):
        _RENDERER.load_record(tampered)

    valid = tmp_path / "valid.json"
    valid.write_text(record.model_dump_json(), encoding="utf-8")
    link = tmp_path / "evidence-link.json"
    link.symlink_to(valid)
    with pytest.raises(ValueError, match="symlink"):
        _RENDERER.load_record(link)
