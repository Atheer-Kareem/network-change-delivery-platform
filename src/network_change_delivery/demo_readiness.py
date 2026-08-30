"""Read-only, five-minute readiness report for the personal NCDP demonstration."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from network_change_delivery.audit import AuditFinalOutcome
from network_change_delivery.audit_store import AuditStoreError
from network_change_delivery.configuration_observation import (
    ObservationOverallStatus,
    ObservationRelationship,
)
from network_change_delivery.configuration_observation_store import (
    ConfigurationObservationStore,
)

NETBOX_URL = "http://127.0.0.1:8000/"
GRAFANA_DASHBOARD_URL = (
    "http://127.0.0.1:3000/d/ncdp-management-reachability/ncdp-management-reachability"
)
PROMETHEUS_READY_URL = "http://127.0.0.1:9090/-/ready"
OPENBAO_HEALTH_URL = "http://127.0.0.1:8200/v1/sys/health"
EVIDENCE_VIEWER_URL = "http://127.0.0.1:8765/"
GITHUB_ORIGINS = frozenset(
    {
        "git@github.com:Atheer-Kareem/network-change-delivery-platform.git",
        "https://github.com/Atheer-Kareem/network-change-delivery-platform.git",
    }
)
COMMAND_TIMEOUT_SECONDS = 5.0
HTTP_TIMEOUT_SECONDS = 3.0
MAX_COMMAND_OUTPUT_BYTES = 64 * 1024
MAX_HTTP_BODY_BYTES = 64 * 1024
GIT_COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")


class ReadinessStatus(StrEnum):
    """Bounded status vocabulary for one readiness check."""

    PASS = "PASS"
    FAIL = "FAIL"
    MANUAL = "MANUAL"
    OPTIONAL = "OPTIONAL"


class ReadinessCheck(BaseModel):
    """One bounded, secret-free readiness result."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    status: ReadinessStatus
    name: str = Field(min_length=1, max_length=32)
    summary: str = Field(min_length=1, max_length=240)

    @field_validator("name", "summary")
    @classmethod
    def safe_text(cls, value: str) -> str:
        if any(ord(character) < 32 or ord(character) == 127 for character in value):
            raise ValueError("readiness text contains control characters")
        return value


class DemoReadinessReport(BaseModel):
    """Ordered readiness checks and deterministic overall result."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    checks: tuple[ReadinessCheck, ...] = Field(min_length=1, max_length=32)

    @property
    def exit_code(self) -> int:
        return (
            1 if any(item.status is ReadinessStatus.FAIL for item in self.checks) else 0
        )

    @property
    def outcome(self) -> str:
        if self.exit_code:
            return "NOT READY"
        if any(item.status is ReadinessStatus.MANUAL for item in self.checks):
            return "READY WITH MANUAL CHECKS"
        return "READY"


@dataclass(frozen=True)
class HttpProbeResponse:
    """Bounded HTTP status, headers, and body from one fixed endpoint."""

    status_code: int
    content_type: str
    body: bytes


class CommandRunner(Protocol):
    def __call__(self, arguments: tuple[str, ...], cwd: Path) -> str: ...


class HttpGetter(Protocol):
    def __call__(self, url: str) -> HttpProbeResponse: ...


StoreFactory = Callable[[Path, Path], ConfigurationObservationStore]


@dataclass(frozen=True)
class CanonicalAuditExpectation:
    record_id: UUID
    build_number: int
    change_id: str
    outcome: AuditFinalOutcome


CANONICAL_AUDITS = (
    CanonicalAuditExpectation(
        record_id=UUID("01a04384-f1ea-47ee-b2be-a92192b207fc"),
        build_number=158,
        change_id="CHG-NCDP-10C7-001",
        outcome=AuditFinalOutcome.SUCCEEDED,
    ),
    CanonicalAuditExpectation(
        record_id=UUID("01a05073-2b15-4cf5-a816-51f23c75429d"),
        build_number=263,
        change_id="CHG-SNMP-11C3-CISCO-003",
        outcome=AuditFinalOutcome.AMBIGUOUS,
    ),
    CanonicalAuditExpectation(
        record_id=UUID("01a050b6-6d7d-4294-990a-0f82ed978409"),
        build_number=267,
        change_id="CHG-SNMP-11C3-CISCO-004",
        outcome=AuditFinalOutcome.SUCCEEDED,
    ),
    CanonicalAuditExpectation(
        record_id=UUID("01a0513c-9d87-4faf-8108-9029c5f44c49"),
        build_number=275,
        change_id="CHG-SNMP-11C3-JUNOS-001",
        outcome=AuditFinalOutcome.SUCCEEDED,
    ),
)
CHRONOLOGY_AUDIT_ID = UUID("01a04384-f1ea-47ee-b2be-a92192b207fc")
CHRONOLOGY_OBSERVATION_ID = UUID("0e56e7e0-87cd-4c04-864a-55c88f3c659f")


def _run_command(arguments: tuple[str, ...], cwd: Path) -> str:
    environment = os.environ.copy()
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    try:
        result = subprocess.run(
            arguments,
            cwd=cwd,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=True,
            timeout=COMMAND_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise RuntimeError("local command unavailable") from error
    if len(result.stdout) > MAX_COMMAND_OUTPUT_BYTES:
        raise RuntimeError("local command output exceeded bound")
    try:
        return result.stdout.decode("utf-8").strip()
    except UnicodeDecodeError as error:
        raise RuntimeError("local command output was invalid") from error


def _http_get(url: str) -> HttpProbeResponse:
    try:
        with (
            httpx.Client(
                follow_redirects=False,
                timeout=HTTP_TIMEOUT_SECONDS,
                trust_env=False,
            ) as client,
            client.stream("GET", url) as response,
        ):
            chunks: list[bytes] = []
            size = 0
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > MAX_HTTP_BODY_BYTES:
                    raise RuntimeError("HTTP response exceeded bound")
                chunks.append(chunk)
            return HttpProbeResponse(
                status_code=response.status_code,
                content_type=response.headers.get("content-type", ""),
                body=b"".join(chunks),
            )
    except (httpx.HTTPError, OSError) as error:
        raise RuntimeError("HTTP endpoint unavailable") from error


def _open_store(root: Path, checkout: Path) -> ConfigurationObservationStore:
    return ConfigurationObservationStore(root, checkout=checkout, create=False)


def _check(status: ReadinessStatus, name: str, summary: str) -> ReadinessCheck:
    return ReadinessCheck(status=status, name=name, summary=summary)


def _git_check(checkout: Path, runner: CommandRunner) -> ReadinessCheck:
    try:
        root_text = runner(("git", "rev-parse", "--show-toplevel"), checkout)
        root = Path(root_text)
        if not root.is_absolute() or root.resolve(strict=True) != checkout.resolve(
            strict=True
        ):
            return _check(
                ReadinessStatus.FAIL, "Git checkout", "not at the NCDP repository root"
            )
        origin = runner(("git", "remote", "get-url", "origin"), root)
        if origin not in GITHUB_ORIGINS:
            return _check(
                ReadinessStatus.FAIL, "Git checkout", "repository identity is not NCDP"
            )
        branch = runner(("git", "symbolic-ref", "--short", "HEAD"), root)
        if branch != "main":
            return _check(
                ReadinessStatus.FAIL, "Git checkout", "current branch is not main"
            )
        worktree = runner(
            ("git", "--no-optional-locks", "status", "--porcelain=v1"), root
        )
        if worktree:
            return _check(
                ReadinessStatus.FAIL, "Git checkout", "main worktree is not clean"
            )
        head = runner(("git", "rev-parse", "HEAD"), root)
        upstream = runner(("git", "rev-parse", "origin/main"), root)
        if not GIT_COMMIT_PATTERN.fullmatch(head) or not GIT_COMMIT_PATTERN.fullmatch(
            upstream
        ):
            return _check(
                ReadinessStatus.FAIL, "Git checkout", "local Git identity is invalid"
            )
        if head != upstream:
            return _check(
                ReadinessStatus.FAIL,
                "Git checkout",
                "HEAD does not match local origin/main",
            )
        return _check(ReadinessStatus.PASS, "Git checkout", f"clean main @ {head[:12]}")
    except (OSError, RuntimeError, ValueError):
        return _check(
            ReadinessStatus.FAIL, "Git checkout", "local Git state unavailable"
        )


def _docker_check(checkout: Path, runner: CommandRunner) -> ReadinessCheck:
    try:
        version = runner(("docker", "info", "--format", "{{.ServerVersion}}"), checkout)
        if not version or len(version) > 64:
            raise RuntimeError("Docker response rejected")
        return _check(ReadinessStatus.PASS, "Docker", "engine reachable")
    except RuntimeError:
        return _check(
            ReadinessStatus.FAIL,
            "Docker",
            "engine unavailable; start Docker Desktop manually",
        )


def _simple_http_check(
    getter: HttpGetter,
    *,
    name: str,
    url: str,
    accepted_statuses: frozenset[int],
    success: str,
) -> ReadinessCheck:
    try:
        response = getter(url)
        if response.status_code not in accepted_statuses:
            raise RuntimeError("HTTP status rejected")
        return _check(ReadinessStatus.PASS, name, success)
    except (RuntimeError, ValueError):
        return _check(ReadinessStatus.FAIL, name, "local browser service unavailable")


def _openbao_check(getter: HttpGetter) -> ReadinessCheck:
    try:
        response = getter(OPENBAO_HEALTH_URL)
        if response.status_code not in {200, 429, 472, 473, 501, 503}:
            raise RuntimeError("OpenBao health status rejected")
        payload = json.loads(response.body)
        if not isinstance(payload, dict):
            raise RuntimeError("OpenBao health schema rejected")
        initialized = payload.get("initialized")
        sealed = payload.get("sealed")
        standby = payload.get("standby", False)
        performance_standby = payload.get("performance_standby", False)
        if not all(
            isinstance(value, bool)
            for value in (initialized, sealed, standby, performance_standby)
        ):
            raise RuntimeError("OpenBao health schema rejected")
        if initialized and not sealed and not standby and not performance_standby:
            return _check(
                ReadinessStatus.PASS,
                "OpenBao",
                "reachable / initialized / active / unsealed",
            )
        state = (
            "uninitialized" if not initialized else "sealed" if sealed else "non-active"
        )
        return _check(ReadinessStatus.FAIL, "OpenBao", f"reachable but {state}")
    except (json.JSONDecodeError, RuntimeError, TypeError, ValueError):
        return _check(
            ReadinessStatus.FAIL, "OpenBao", "bounded health endpoint unavailable"
        )


def _audit_checks(
    audit_root: Path, checkout: Path, store_factory: StoreFactory
) -> tuple[ReadinessCheck, ...]:
    try:
        store = store_factory(audit_root, checkout)
    except (AuditStoreError, OSError, ValueError):
        return (
            _check(
                ReadinessStatus.FAIL,
                "Audit evidence",
                "existing read-only evidence store is invalid",
            ),
        )

    checks: list[ReadinessCheck] = []
    records = {}
    for expected in CANONICAL_AUDITS:
        name = f"Audit #{expected.build_number}"
        try:
            record = store.read_record(expected.record_id)
            records[expected.record_id] = record
            if (
                record.buildkite is None
                or record.buildkite.build_number != expected.build_number
                or record.change_id != expected.change_id
                or record.final_outcome is not expected.outcome
            ):
                raise ValueError("canonical audit mismatch")
            checks.append(
                _check(
                    ReadinessStatus.PASS,
                    name,
                    (
                        f"{expected.change_id} · {expected.outcome.value} · "
                        f"{expected.record_id}"
                    ),
                )
            )
        except (AuditStoreError, OSError, ValueError):
            checks.append(
                _check(
                    ReadinessStatus.FAIL,
                    name,
                    "canonical typed record missing or inconsistent",
                )
            )

    try:
        parent = records[CHRONOLOGY_AUDIT_ID]
        observation = store.read_observation_record(CHRONOLOGY_OBSERVATION_ID)
        correlated = store.find_by_parent(CHRONOLOGY_AUDIT_ID)
        if (
            observation.parent_audit.record_id != parent.record_id
            or observation.parent_audit.digest != parent.digest
            or observation.relationship
            is not ObservationRelationship.TEMPORALLY_BRACKETED
            or observation.causality != "NOT_PROVEN"
            or observation.overall_status is not ObservationOverallStatus.SUCCEEDED
            or tuple(item.observation_record_id for item in correlated)
            != (CHRONOLOGY_OBSERVATION_ID,)
        ):
            raise ValueError("canonical chronology mismatch")
        checks.append(
            _check(
                ReadinessStatus.PASS,
                "Chronology #158",
                f"{CHRONOLOGY_OBSERVATION_ID} · TEMPORALLY_BRACKETED · NOT_PROVEN",
            )
        )
    except (AuditStoreError, KeyError, OSError, ValueError):
        checks.append(
            _check(
                ReadinessStatus.FAIL,
                "Chronology #158",
                "canonical PRE/POST observation missing or inconsistent",
            )
        )
    return tuple(checks)


def _viewer_check(getter: HttpGetter) -> ReadinessCheck:
    try:
        response = getter(EVIDENCE_VIEWER_URL)
        if (
            response.status_code == 200
            and "text/html" in response.content_type.casefold()
            and b"NCDP Durable Evidence" in response.body
            and b"READ-ONLY" in response.body
            and b"LOOPBACK ONLY" in response.body
        ):
            return _check(
                ReadinessStatus.PASS, "Evidence viewer", "already running on loopback"
            )
    except (RuntimeError, ValueError):
        pass
    return _check(
        ReadinessStatus.OPTIONAL,
        "Evidence viewer",
        "start before walkthrough with the supplied --audit-root",
    )


def run_demo_readiness(
    audit_root: Path,
    *,
    checkout: Path,
    command_runner: CommandRunner = _run_command,
    http_getter: HttpGetter = _http_get,
    store_factory: StoreFactory = _open_store,
) -> DemoReadinessReport:
    """Run bounded local checks without changing platform or repository state."""

    checks: list[ReadinessCheck] = [
        _git_check(checkout, command_runner),
        _docker_check(checkout, command_runner),
        _simple_http_check(
            http_getter,
            name="NetBox UI",
            url=NETBOX_URL,
            accepted_statuses=frozenset(range(200, 400)),
            success="loopback browser service reachable",
        ),
        _simple_http_check(
            http_getter,
            name="Grafana dashboard",
            url=GRAFANA_DASHBOARD_URL,
            accepted_statuses=frozenset({200}),
            success="NCDP Management Reachability reachable",
        ),
        _simple_http_check(
            http_getter,
            name="Prometheus",
            url=PROMETHEUS_READY_URL,
            accepted_statuses=frozenset({200}),
            success="ready endpoint passed",
        ),
        _openbao_check(http_getter),
    ]
    checks.extend(_audit_checks(audit_root, checkout, store_factory))
    checks.extend(
        (
            _viewer_check(http_getter),
            _check(
                ReadinessStatus.MANUAL,
                "Grafana target health",
                "confirm both management targets are healthy",
            ),
            _check(
                ReadinessStatus.MANUAL,
                "NetBox session",
                "confirm authenticated device pages are available",
            ),
            _check(
                ReadinessStatus.MANUAL,
                "CML NCDP Live",
                "confirm core-02 and edge-junos-01 are BOOTED in the UI",
            ),
            _check(
                ReadinessStatus.MANUAL,
                "Buildkite session",
                "confirm signed in and Builds #281 and #275 are accessible",
            ),
        )
    )
    return DemoReadinessReport(checks=tuple(checks))


def render_report(report: DemoReadinessReport) -> str:
    """Render one compact, deterministic terminal report."""

    lines = ["NCDP Demo Readiness", "-------------------"]
    lines.extend(
        f"{item.status.value:<8} {item.name:<22} {item.summary}"
        for item in report.checks
    )
    lines.extend(("", f"Demo readiness: {report.outcome}"))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Run the read-only readiness report from the current repository root."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit-root", required=True, type=Path)
    arguments = parser.parse_args(argv)
    if not arguments.audit_root.is_absolute() or not arguments.audit_root.exists():
        parser.error("--audit-root must be an absolute existing-store path")
    report = run_demo_readiness(arguments.audit_root, checkout=Path.cwd())
    print(render_report(report))
    return report.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
