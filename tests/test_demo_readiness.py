"""Read-only demonstration-readiness reporting and failure-boundary tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from test_audit_store import plan, record, store_snapshot
from test_configuration_observation import unchanged_observation
from test_configuration_observation_store import linked_record

import network_change_delivery.demo_readiness as readiness_module
from network_change_delivery.audit import (
    AuditArtifactKind,
    AuditFinalOutcome,
    BuildkiteCorrelation,
    CredentialProvenance,
    canonical_json_bytes,
)
from network_change_delivery.configuration_observation import (
    ObservationRelationship,
)
from network_change_delivery.configuration_observation_store import (
    ConfigurationObservationStore,
)
from network_change_delivery.demo_readiness import (
    CANONICAL_AUDITS,
    CHRONOLOGY_OBSERVATION_ID,
    EVIDENCE_VIEWER_URL,
    GRAFANA_DASHBOARD_URL,
    NETBOX_URL,
    OPENBAO_HEALTH_URL,
    PROMETHEUS_READY_URL,
    DemoReadinessReport,
    HttpProbeResponse,
    ReadinessCheck,
    ReadinessStatus,
    render_report,
    run_demo_readiness,
)

HEAD = "c" * 40
SECRET_MARKER = "DO-NOT-RENDER-openbao:kv-v2:ncdp/devices/1/ssh"
CREDENTIAL_REFERENCE = "openbao:kv-v2:ncdp/devices/1/ssh"


class FakeRunner:
    def __init__(
        self,
        checkout: Path,
        *,
        branch: str = "main",
        worktree: str = "",
        head: str = HEAD,
        upstream: str = HEAD,
        docker: str | Exception = "28.4.0",
    ) -> None:
        self.checkout = checkout
        self.calls: list[tuple[str, ...]] = []
        self.values: dict[tuple[str, ...], str | Exception] = {
            ("git", "rev-parse", "--show-toplevel"): str(checkout),
            ("git", "remote", "get-url", "origin"): (
                "https://github.com/Atheer-Kareem/network-change-delivery-platform.git"
            ),
            ("git", "symbolic-ref", "--short", "HEAD"): branch,
            (
                "git",
                "--no-optional-locks",
                "status",
                "--porcelain=v1",
            ): worktree,
            ("git", "rev-parse", "HEAD"): head,
            ("git", "rev-parse", "origin/main"): upstream,
            ("docker", "info", "--format", "{{.ServerVersion}}"): docker,
        }

    def __call__(self, arguments: tuple[str, ...], cwd: Path) -> str:
        assert cwd == self.checkout
        self.calls.append(arguments)
        value = self.values[arguments]
        if isinstance(value, Exception):
            raise value
        return value


class FakeHttp:
    def __init__(self, *, viewer: bool = True) -> None:
        self.calls: list[str] = []
        self.values: dict[str, HttpProbeResponse | Exception] = {
            NETBOX_URL: HttpProbeResponse(302, "text/html", b""),
            GRAFANA_DASHBOARD_URL: HttpProbeResponse(200, "text/html", b"grafana"),
            PROMETHEUS_READY_URL: HttpProbeResponse(200, "text/plain", b"ready"),
            OPENBAO_HEALTH_URL: HttpProbeResponse(
                200,
                "application/json",
                json.dumps(
                    {
                        "initialized": True,
                        "sealed": False,
                        "standby": False,
                        "performance_standby": False,
                    }
                ).encode(),
            ),
            EVIDENCE_VIEWER_URL: (
                HttpProbeResponse(
                    200,
                    "text/html; charset=utf-8",
                    b"NCDP Durable Evidence READ-ONLY LOOPBACK ONLY",
                )
                if viewer
                else RuntimeError("not running")
            ),
        }

    def __call__(self, url: str) -> HttpProbeResponse:
        self.calls.append(url)
        value = self.values[url]
        if isinstance(value, Exception):
            raise value
        return value


def _buildkite(build_number: int) -> BuildkiteCorrelation:
    return BuildkiteCorrelation(
        pipeline_id=UUID(int=10),
        build_id=UUID(int=build_number),
        build_number=build_number,
        job_id=UUID(int=build_number + 1000),
        step_key="deploy-gate",
    )


def canonical_store(
    tmp_path: Path,
    *,
    missing_build: int | None = None,
    wrong_outcome_build: int | None = None,
    observation: str = "valid",
) -> tuple[ConfigurationObservationStore, object | None]:
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    root = tmp_path / "audit"
    root.mkdir(mode=0o700)
    writable = ConfigurationObservationStore(root, checkout=checkout)
    reference = writable.persist_artifact(AuditArtifactKind.DEPLOYMENT_PLAN, plan())
    chronology_parent = None
    for index, expected in enumerate(CANONICAL_AUDITS):
        if expected.build_number == missing_build:
            continue
        outcome = (
            AuditFinalOutcome.FAILED
            if expected.build_number == wrong_outcome_build
            else expected.outcome
        )
        approved = record(
            reference,
            record_id=expected.record_id,
            generated_at=datetime(2026, 8, 27, index + 1, tzinfo=UTC),
            change_id=expected.change_id,
            buildkite=_buildkite(expected.build_number),
            credentials=(
                CredentialProvenance(
                    device="netbox:dcim.device:1",
                    source="openbao",
                    reference=CREDENTIAL_REFERENCE,
                ),
            ),
            final_outcome=outcome,
        )
        writable.persist_record(approved)
        if expected.build_number == 158:
            chronology_parent = approved
    if chronology_parent is not None and observation != "missing":
        values: dict[str, object] = {
            "observation_record_id": CHRONOLOGY_OBSERVATION_ID,
        }
        if observation in {"valid", "causality"}:
            values.update(
                pre_observation=unchanged_observation(hour=0),
                post_observation=unchanged_observation(hour=1),
                relationship=ObservationRelationship.TEMPORALLY_BRACKETED,
            )
        approved_observation = linked_record(chronology_parent, **values)
        destination = writable.persist_observation_record(approved_observation)
        if observation == "causality":
            payload = approved_observation.model_dump(mode="json")
            payload["causality"] = "PROVEN"
            destination.write_bytes(canonical_json_bytes(payload))
    return (
        ConfigurationObservationStore(root, checkout=checkout, create=False),
        chronology_parent,
    )


def _run(
    tmp_path: Path,
    store: ConfigurationObservationStore,
    *,
    runner: FakeRunner | None = None,
    http: FakeHttp | None = None,
) -> tuple[DemoReadinessReport, FakeRunner, FakeHttp]:
    checkout = tmp_path / "checkout"
    selected_runner = runner or FakeRunner(checkout)
    selected_http = http or FakeHttp()
    report = run_demo_readiness(
        store.root,
        checkout=checkout,
        command_runner=selected_runner,
        http_getter=selected_http,
        store_factory=lambda root, context: ConfigurationObservationStore(
            root, checkout=context, create=False
        ),
    )
    return report, selected_runner, selected_http


def test_status_rendering_and_exit_codes_are_deterministic() -> None:
    ready = DemoReadinessReport(
        checks=(
            ReadinessCheck(status="PASS", name="Automated", summary="passed"),
            ReadinessCheck(status="OPTIONAL", name="Viewer", summary="start it"),
            ReadinessCheck(status="MANUAL", name="Session", summary="verify it"),
        )
    )
    assert ready.exit_code == 0
    assert ready.outcome == "READY WITH MANUAL CHECKS"
    assert render_report(ready) == (
        "NCDP Demo Readiness\n"
        "-------------------\n"
        "PASS     Automated              passed\n"
        "OPTIONAL Viewer                 start it\n"
        "MANUAL   Session                verify it\n\n"
        "Demo readiness: READY WITH MANUAL CHECKS"
    )
    failed = DemoReadinessReport(
        checks=(ReadinessCheck(status="FAIL", name="Required", summary="failed"),)
    )
    assert failed.exit_code == 1
    assert failed.outcome == "NOT READY"


def test_all_automated_checks_pass_without_mutation_or_privileged_calls(
    tmp_path: Path,
) -> None:
    store, _parent = canonical_store(tmp_path)
    before = store_snapshot(store.root)

    report, runner, http = _run(tmp_path, store)

    assert report.exit_code == 0
    assert report.outcome == "READY WITH MANUAL CHECKS"
    assert [item.status for item in report.checks] == [
        ReadinessStatus.PASS,
        ReadinessStatus.PASS,
        ReadinessStatus.PASS,
        ReadinessStatus.PASS,
        ReadinessStatus.PASS,
        ReadinessStatus.PASS,
        ReadinessStatus.PASS,
        ReadinessStatus.PASS,
        ReadinessStatus.PASS,
        ReadinessStatus.PASS,
        ReadinessStatus.PASS,
        ReadinessStatus.PASS,
        ReadinessStatus.MANUAL,
        ReadinessStatus.MANUAL,
        ReadinessStatus.MANUAL,
        ReadinessStatus.MANUAL,
    ]
    assert store_snapshot(store.root) == before
    assert CREDENTIAL_REFERENCE not in render_report(report)
    assert str(store.root) not in render_report(report)
    assert str(tmp_path / "checkout") not in render_report(report)
    assert set(http.calls) == {
        NETBOX_URL,
        GRAFANA_DASHBOARD_URL,
        PROMETHEUS_READY_URL,
        OPENBAO_HEALTH_URL,
        EVIDENCE_VIEWER_URL,
    }
    assert all("cml" not in url.casefold() for url in http.calls)
    assert all("buildkite" not in url.casefold() for url in http.calls)
    assert all("api/" not in url or url == OPENBAO_HEALTH_URL for url in http.calls)
    assert ("docker", "info", "--format", "{{.ServerVersion}}") in runner.calls
    assert not any(
        "fetch" in arguments or "pull" in arguments for arguments in runner.calls
    )


@pytest.mark.parametrize(
    ("runner_changes", "expected"),
    [
        ({"branch": "feature"}, "current branch is not main"),
        ({"worktree": " M README.md"}, "main worktree is not clean"),
        ({"upstream": "d" * 40}, "HEAD does not match local origin/main"),
    ],
)
def test_git_dirty_wrong_branch_and_local_ref_mismatch_fail(
    tmp_path: Path, runner_changes: dict[str, str], expected: str
) -> None:
    store, _parent = canonical_store(tmp_path)
    runner = FakeRunner(tmp_path / "checkout", **runner_changes)

    report, _runner, _http = _run(tmp_path, store, runner=runner)

    check = next(item for item in report.checks if item.name == "Git checkout")
    assert check.status is ReadinessStatus.FAIL
    assert check.summary == expected
    assert report.exit_code == 1


def test_missing_docker_is_normalized_without_exception_detail(tmp_path: Path) -> None:
    store, _parent = canonical_store(tmp_path)
    runner = FakeRunner(tmp_path / "checkout", docker=RuntimeError(SECRET_MARKER))

    report, _runner, _http = _run(tmp_path, store, runner=runner)

    check = next(item for item in report.checks if item.name == "Docker")
    assert check.status is ReadinessStatus.FAIL
    assert "start Docker Desktop manually" in check.summary
    assert SECRET_MARKER not in render_report(report)


@pytest.mark.parametrize(
    ("url", "name"),
    [
        (NETBOX_URL, "NetBox UI"),
        (GRAFANA_DASHBOARD_URL, "Grafana dashboard"),
        (PROMETHEUS_READY_URL, "Prometheus"),
    ],
)
def test_http_timeout_and_failure_are_bounded(
    tmp_path: Path, url: str, name: str
) -> None:
    store, _parent = canonical_store(tmp_path)
    http = FakeHttp()
    http.values[url] = RuntimeError(SECRET_MARKER)

    report, _runner, _http = _run(tmp_path, store, http=http)

    check = next(item for item in report.checks if item.name == name)
    assert check.status is ReadinessStatus.FAIL
    assert check.summary == "local browser service unavailable"
    assert SECRET_MARKER not in render_report(report)


@pytest.mark.parametrize(
    ("status", "payload", "expected"),
    [
        (503, {"initialized": True, "sealed": True}, "sealed"),
        (429, {"initialized": True, "sealed": False, "standby": True}, "non-active"),
        (501, {"initialized": False, "sealed": True}, "uninitialized"),
    ],
)
def test_openbao_sealed_nonactive_and_uninitialized_fail_safely(
    tmp_path: Path, status: int, payload: dict[str, bool], expected: str
) -> None:
    store, _parent = canonical_store(tmp_path)
    http = FakeHttp()
    http.values[OPENBAO_HEALTH_URL] = HttpProbeResponse(
        status, "application/json", json.dumps(payload).encode()
    )

    report, _runner, _http = _run(tmp_path, store, http=http)

    check = next(item for item in report.checks if item.name == "OpenBao")
    assert check.status is ReadinessStatus.FAIL
    assert expected in check.summary


@pytest.mark.parametrize(
    ("store_changes", "failed_name"),
    [
        ({"missing_build": 275}, "Audit #275"),
        ({"wrong_outcome_build": 267}, "Audit #267"),
        ({"observation": "missing"}, "Chronology #158"),
        ({"observation": "post-only"}, "Chronology #158"),
        ({"observation": "causality"}, "Chronology #158"),
    ],
)
def test_missing_wrong_outcome_and_invalid_chronology_fail(
    tmp_path: Path, store_changes: dict[str, object], failed_name: str
) -> None:
    store, _parent = canonical_store(tmp_path, **store_changes)

    report, _runner, _http = _run(tmp_path, store)

    check = next(item for item in report.checks if item.name == failed_name)
    assert check.status is ReadinessStatus.FAIL
    assert report.exit_code == 1


def test_tampered_canonical_audit_fails_without_raw_detail(tmp_path: Path) -> None:
    store, _parent = canonical_store(tmp_path)
    target = store.root / "records" / f"{CANONICAL_AUDITS[0].record_id}.json"
    payload = json.loads(target.read_bytes())
    payload["digest"] = "sha256:" + "f" * 64
    target.write_bytes(canonical_json_bytes(payload))

    report, _runner, _http = _run(tmp_path, store)

    check = next(item for item in report.checks if item.name == "Audit #158")
    assert check.status is ReadinessStatus.FAIL
    assert "digest" not in check.summary.casefold()
    assert str(store.root) not in render_report(report)


def test_absent_viewer_is_optional_and_does_not_fail_readiness(tmp_path: Path) -> None:
    store, _parent = canonical_store(tmp_path)
    report, _runner, _http = _run(tmp_path, store, http=FakeHttp(viewer=False))

    viewer = next(item for item in report.checks if item.name == "Evidence viewer")
    assert viewer.status is ReadinessStatus.OPTIONAL
    assert report.exit_code == 0
    assert str(store.root) not in render_report(report)


def test_missing_store_fails_without_creating_it(tmp_path: Path) -> None:
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    missing = tmp_path / "missing-audit"

    report = run_demo_readiness(
        missing,
        checkout=checkout,
        command_runner=FakeRunner(checkout),
        http_getter=FakeHttp(),
    )

    audit = next(item for item in report.checks if item.name == "Audit evidence")
    assert audit.status is ReadinessStatus.FAIL
    assert not missing.exists()


def test_main_exit_codes_and_invocation_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def report_ready(*_args: object, **_kwargs: object) -> DemoReadinessReport:
        return ready

    def report_failed(*_args: object, **_kwargs: object) -> DemoReadinessReport:
        return failed

    audit_root = tmp_path / "audit"
    audit_root.mkdir()
    ready = DemoReadinessReport(
        checks=(ReadinessCheck(status="PASS", name="Required", summary="passed"),)
    )
    monkeypatch.setattr(readiness_module, "run_demo_readiness", report_ready)
    assert readiness_module.main(["--audit-root", str(audit_root)]) == 0
    assert "Demo readiness: READY" in capsys.readouterr().out

    failed = DemoReadinessReport(
        checks=(ReadinessCheck(status="FAIL", name="Required", summary="failed"),)
    )
    monkeypatch.setattr(readiness_module, "run_demo_readiness", report_failed)
    assert readiness_module.main(["--audit-root", str(audit_root)]) == 1

    with pytest.raises(SystemExit) as caught:
        readiness_module.main(["--audit-root", "relative"])
    assert caught.value.code == 2
