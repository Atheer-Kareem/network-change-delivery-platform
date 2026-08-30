"""Contracts for the allowlisted ephemeral-CML staging annotation."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from network_change_delivery.ephemeral_staging import StagingEvidence

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts/buildkite/render_staging_annotation.py"
SPEC = importlib.util.spec_from_file_location("render_staging_annotation", SCRIPT)
assert SPEC and SPEC.loader
renderer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(renderer)


def evidence(**changes: object) -> StagingEvidence:
    value = StagingEvidence(
        schema_version="2",
        staging_run_id="bk-79c012df-23bf-49b3-a6dd-f28799c4bb24",
        orchestrator="buildkite",
        pipeline_id="01a02ab4-2472-4726-be31-dbf4f216210f",
        build_id="79c012df-23bf-49b3-a6dd-f28799c4bb24",
        build_commit="a" * 40,
        build_branch="feature/staging",
        step_key="cml-staging",
        job_id="66051b16-7d3d-4c10-a81d-ec7bb630231d",
        lab_id="11111111-2222-3333-4444-555555555555",
        node_ids={
            "system_bridge": "node-system",
            "management_switch": "node-management",
            "core_02": "node-core-secret-like-id",
            "edge_junos_01": "node-edge-secret-like-id",
        },
        link_ids={
            "system_bridge_management": "link-system-management-secret-like-id",
            "management_core_02": "link-management-core-secret-like-id",
            "management_edge_junos_01": "link-management-edge-secret-like-id",
            "core_02_edge_junos_01": "link-core-edge-secret-like-id",
        },
        creation_outcome="passed",
        readiness_outcome="passed",
        readiness_seconds={"core_02": 124.2, "edge_junos_01": 188.7},
        readiness_checks={
            role: {
                "arp": "passed",
                "icmp": "passed",
                "tcp22": "passed",
                "tcp830": "passed",
            }
            for role in ("core_02", "edge_junos_01")
        },
        node_states={"core_02": "STARTED", "edge_junos_01": "STARTED"},
        netbox_device_ids={
            "core_02": "netbox:dcim.device:1",
            "edge_junos_01": "netbox:dcim.device:2",
        },
        credential_references={
            "core_02": "openbao:kv-v2:ncdp/devices/1/ssh",
            "edge_junos_01": "openbao:kv-v2:ncdp/devices/2/ssh",
        },
        ncdp_validation_outcome="passed",
        ncdp_validation_attempts={"core_02": 1, "edge_junos_01": 2},
        destroy_outcome="passed",
        absence_verification_outcome="passed",
        state_retirement_outcome="passed",
        overall_result="passed",
    )
    for name, replacement in changes.items():
        setattr(value, name, replacement)
    return value


def parsed(value: StagingEvidence):
    return renderer.StagingAnnotationEvidence.model_validate(value.safe_dict())


def test_success_annotation_contains_only_allowlisted_staging_truth() -> None:
    value = evidence()
    rendered = renderer.render_annotation(parsed(value))

    for expected in (
        "Ephemeral CML staging",
        "PASSED",
        value.staging_run_id,
        value.build_commit,
        value.lab_id,
        "system_bridge, management_switch, core_02, edge_junos_01",
        "core_02 / core-02",
        "edge_junos_01 / edge-junos-01",
        "192.168.4.30",
        "192.168.4.40",
        "124.2",
        "188.7",
        "GigabitEthernet2",
        "ge-0/0/2",
        "READ-ONLY",
        "nodes=4; links=4",
        "PRIMARY FAILURE: **NONE**",
        "CLEANUP FAILURE: **NONE**",
    ):
        assert expected in rendered

    serialized = json.dumps(value.safe_dict())
    for omitted in (
        "openbao:kv-v2:ncdp/devices/1/ssh",
        "openbao:kv-v2:ncdp/devices/2/ssh",
        "node-core-secret-like-id",
        "node-edge-secret-like-id",
        "link-system-management-secret-like-id",
        "link-management-core-secret-like-id",
        "link-management-edge-secret-like-id",
        "link-core-edge-secret-like-id",
        "netbox:dcim.device:1",
        "STARTED",
    ):
        assert omitted in serialized
        assert omitted not in rendered


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        (
            "node_ids",
            {
                "system_bridge": "node-system",
                "management_switch": "node-management",
                "core_02": "node-core",
            },
        ),
        ("link_ids", {"core_02_edge_junos_01": "link-core-edge"}),
        ("readiness_seconds", {"core_02": 124.2}),
        (
            "readiness_checks",
            {
                "core_02": {
                    "arp": "passed",
                    "icmp": "passed",
                    "tcp22": "passed",
                    "tcp830": "passed",
                }
            },
        ),
        ("ncdp_validation_attempts", {"core_02": 1}),
        ("primary_failure", "sanitized primary failure"),
        ("cleanup_failure", "sanitized cleanup failure"),
    ],
)
def test_passed_evidence_requires_complete_success_observations(
    field: str, replacement: object
) -> None:
    with pytest.raises(ValidationError, match="passed staging evidence is incomplete"):
        parsed(evidence(**{field: replacement}))


def test_failed_evidence_allows_partial_known_topology() -> None:
    value = evidence(
        overall_result="failed",
        link_ids={"core_02_edge_junos_01": "link-core-edge"},
        readiness_seconds={"core_02": 124.2},
        readiness_checks={
            "core_02": {
                "arp": "passed",
                "icmp": "passed",
                "tcp22": "passed",
                "tcp830": "passed",
            }
        },
        ncdp_validation_attempts={"core_02": 1},
        primary_failure="sanitized primary failure",
    )

    assert parsed(value).overall_result == "failed"


def test_unknown_link_role_is_rejected_for_failed_evidence() -> None:
    with pytest.raises(ValidationError, match="unknown link role"):
        parsed(
            evidence(
                overall_result="failed",
                link_ids={"unexpected_link": "unexpected-link-id"},
            )
        )


def test_readiness_presentation_allows_final_probe_duration_only() -> None:
    within_allowance = renderer.READINESS_OPERATION_TIMEOUT_SECONDS + (
        renderer.READINESS_FINAL_PROBE_ALLOWANCE_SECONDS / 2
    )
    value = evidence(
        readiness_seconds={
            "core_02": within_allowance,
            "edge_junos_01": 188.7,
        }
    )
    assert parsed(value).readiness_seconds["core_02"] == within_allowance

    excessive = renderer.MAX_READINESS_PRESENTATION_SECONDS + 0.1
    with pytest.raises(ValidationError, match="readiness duration"):
        parsed(
            evidence(
                readiness_seconds={
                    "core_02": excessive,
                    "edge_junos_01": 188.7,
                }
            )
        )


@pytest.mark.parametrize(
    ("primary", "cleanup", "primary_status", "cleanup_status"),
    [
        ("unsafe primary provider detail", None, "PRESENT", "NONE"),
        (None, "unsafe cleanup provider detail", "NONE", "PRESENT"),
        (
            "unsafe primary provider detail",
            "unsafe cleanup provider detail",
            "PRESENT",
            "PRESENT",
        ),
    ],
)
def test_failure_annotation_classifies_without_rendering_raw_text(
    primary: str | None,
    cleanup: str | None,
    primary_status: str,
    cleanup_status: str,
) -> None:
    value = evidence(
        overall_result="failed",
        primary_failure=primary,
        cleanup_failure=cleanup,
    )
    rendered = renderer.render_annotation(parsed(value))

    assert f"PRIMARY FAILURE: **{primary_status}**" in rendered
    assert f"CLEANUP FAILURE: **{cleanup_status}**" in rendered
    assert "unsafe primary provider detail" not in rendered
    assert "unsafe cleanup provider detail" not in rendered


def test_failure_annotation_omits_long_provider_text_without_rejecting_evidence() -> (
    None
):
    raw_failure = "provider-detail-" * 100
    rendered = renderer.render_annotation(
        parsed(
            evidence(
                overall_result="failed",
                primary_failure=raw_failure,
            )
        )
    )

    assert "PRIMARY FAILURE: **PRESENT**" in rendered
    assert raw_failure not in rendered


def test_markdown_sensitive_values_are_encoded() -> None:
    assert renderer._safe("value|`<tag>\nnext") == ("value&#124;&#96;&lt;tag&gt; next")


def test_loader_rejects_malformed_extra_oversized_and_symlinked_evidence(
    tmp_path: Path,
) -> None:
    malformed = tmp_path / "malformed.json"
    malformed.write_text("{}", encoding="utf-8")
    with pytest.raises(ValidationError):
        renderer.load_evidence(malformed)

    extra = tmp_path / "extra.json"
    payload = evidence().safe_dict() | {
        "day0_configuration": "password secret raw configuration"
    }
    extra.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValidationError):
        renderer.load_evidence(extra)

    oversized = tmp_path / "oversized.json"
    oversized.write_bytes(b" " * (renderer.MAX_EVIDENCE_BYTES + 1))
    with pytest.raises(ValueError, match="presentation limit"):
        renderer.load_evidence(oversized)

    valid = tmp_path / "valid.json"
    valid.write_text(json.dumps(evidence().safe_dict()), encoding="utf-8")
    link = tmp_path / "evidence-link.json"
    link.symlink_to(valid)
    with pytest.raises(ValueError, match="symlink"):
        renderer.load_evidence(link)
