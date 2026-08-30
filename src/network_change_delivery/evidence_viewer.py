"""Loopback-only, read-only browser presentation for durable NCDP evidence."""

# The server-rendered HTML/CSS remains inline by design; readable template lines can
# exceed Python's source line limit without changing the bounded response surface.
# ruff: noqa: E501

from __future__ import annotations

import argparse
import html
import subprocess
from dataclasses import dataclass
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

from network_change_delivery.audit import ChangeAuditRecord
from network_change_delivery.audit_store import AuditStoreError
from network_change_delivery.configuration_observation import (
    ConfigurationObservationRecord,
    OxidizedObservation,
    OxidizedRevision,
)
from network_change_delivery.configuration_observation_store import (
    ConfigurationObservationStore,
)

LOOPBACK_ADDRESS = "127.0.0.1"
DEFAULT_PORT = 8765
MAX_PRESENTED_RECORDS = 50
GITHUB_REPOSITORY_IDENTITY = "github:Atheer-Kareem/network-change-delivery-platform"
GITHUB_REPOSITORY_URL = (
    "https://github.com/Atheer-Kareem/network-change-delivery-platform"
)
BUILDKITE_PIPELINE_URL = (
    "https://buildkite.com/atheer-kareem/network-change-delivery-platform"
)

SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": (
        "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; "
        "form-action 'none'; frame-ancestors 'none'"
    ),
}


@dataclass(frozen=True)
class TargetPresentation:
    """Allowlisted stable target identity."""

    device: str
    interface: str | None


@dataclass(frozen=True)
class ArtifactPresentation:
    """Allowlisted artifact integrity identity without a locator."""

    kind: str
    digest: str
    schema_version: str


@dataclass(frozen=True)
class RevisionPresentation:
    """Allowlisted metadata-only observed-configuration revision."""

    commit: str
    blob: str
    collected_at: datetime


@dataclass(frozen=True)
class AttemptPresentation:
    """Allowlisted PRE or POST observation fields."""

    label: str
    status: str
    requested_at: datetime
    completed_at: datetime | None
    failure_category: str | None
    before_revision: RevisionPresentation | None
    after_revision: RevisionPresentation | None


@dataclass(frozen=True)
class ObservationPresentation:
    """Allowlisted configuration-observation correlation."""

    record_id: UUID
    generated_at: datetime
    digest: str
    target: str
    repository: str
    relationship: str
    causality: str
    overall_status: str
    attempts: tuple[AttemptPresentation, ...]


@dataclass(frozen=True)
class RecordSummaryPresentation:
    """Allowlisted audit index entry."""

    record_id: UUID
    generated_at: datetime
    change_id: str
    final_outcome: str
    build_number: int | None
    commit: str
    targets: tuple[TargetPresentation, ...]
    approved: bool


@dataclass(frozen=True)
class RecordDetailPresentation:
    """Allowlisted audit detail without credential or locator material."""

    record_id: UUID
    generated_at: datetime
    digest: str
    change_id: str
    final_outcome: str
    repository: str
    commit: str
    pull_request: int | None
    build_number: int | None
    step_key: str | None
    approved: bool
    targets: tuple[TargetPresentation, ...]
    artifacts: tuple[ArtifactPresentation, ...]
    observations: tuple[ObservationPresentation, ...]


def _target_presentations(record: ChangeAuditRecord) -> tuple[TargetPresentation, ...]:
    return tuple(
        TargetPresentation(device=item.device, interface=item.interface)
        for item in record.targets
    )


def _summary(record: ChangeAuditRecord) -> RecordSummaryPresentation:
    return RecordSummaryPresentation(
        record_id=record.record_id,
        generated_at=record.generated_at,
        change_id=record.change_id,
        final_outcome=str(record.final_outcome),
        build_number=(record.buildkite.build_number if record.buildkite else None),
        commit=record.git.commit,
        targets=_target_presentations(record),
        approved=record.approval is not None,
    )


def _revision(value: OxidizedRevision | None) -> RevisionPresentation | None:
    if value is None:
        return None
    return RevisionPresentation(
        commit=value.commit,
        blob=value.blob,
        collected_at=value.collected_at,
    )


def _attempt(label: str, value: OxidizedObservation) -> AttemptPresentation:
    return AttemptPresentation(
        label=label,
        status=str(value.status),
        requested_at=value.requested_at,
        completed_at=value.completed_at,
        failure_category=(
            str(value.failure_category) if value.failure_category is not None else None
        ),
        before_revision=_revision(value.before_revision),
        after_revision=_revision(value.after_revision),
    )


def _observation(value: ConfigurationObservationRecord) -> ObservationPresentation:
    attempts: list[AttemptPresentation] = []
    if value.pre_observation is not None:
        attempts.append(_attempt("PRE", value.pre_observation))
    if value.post_observation is not None:
        attempts.append(_attempt("POST", value.post_observation))
    return ObservationPresentation(
        record_id=value.observation_record_id,
        generated_at=value.generated_at,
        digest=value.digest,
        target=value.target,
        repository=value.repository,
        relationship=str(value.relationship),
        causality=value.causality,
        overall_status=str(value.overall_status),
        attempts=tuple(attempts),
    )


def _detail(
    record: ChangeAuditRecord,
    observations: tuple[ConfigurationObservationRecord, ...],
) -> RecordDetailPresentation:
    return RecordDetailPresentation(
        record_id=record.record_id,
        generated_at=record.generated_at,
        digest=record.digest,
        change_id=record.change_id,
        final_outcome=str(record.final_outcome),
        repository=record.git.repository,
        commit=record.git.commit,
        pull_request=record.git.pull_request,
        build_number=(record.buildkite.build_number if record.buildkite else None),
        step_key=(record.buildkite.step_key if record.buildkite else None),
        approved=record.approval is not None,
        targets=_target_presentations(record),
        artifacts=tuple(
            ArtifactPresentation(
                kind=str(item.kind),
                digest=item.sha256,
                schema_version=item.schema_version,
            )
            for item in record.artifacts
        ),
        observations=tuple(_observation(item) for item in observations),
    )


def _escape(value: object) -> str:
    return html.escape(str(value), quote=True)


def _timestamp(value: datetime | None) -> str:
    if value is None:
        return "NOT RECORDED"
    return value.isoformat().replace("+00:00", "Z")


def _index_timestamp(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%SZ")


def _badge(value: str, *, emphasis: str | None = None) -> str:
    css = emphasis or value.casefold().replace("_", "-")
    return f'<span class="badge badge-{_escape(css)}">{_escape(value)}</span>'


def _page(title: str, body: str) -> bytes:
    content = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_escape(title)}</title>
  <style>
    :root {{ color-scheme: dark; font-family: -apple-system, BlinkMacSystemFont,
      "Segoe UI", sans-serif; background: #09111f; color: #e5edf8; }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; background: #09111f; line-height: 1.45; }}
    header {{ padding: 2rem max(1.25rem, calc((100% - 1120px)/2));
      background: linear-gradient(135deg, #10213b, #0b1628); border-bottom: 1px solid #29415f; }}
    header h1 {{ margin: 0 0 .35rem; font-size: 1.85rem; }}
    header p {{ margin: 0; color: #a9bbd1; }}
    main {{ max-width: 1120px; margin: 0 auto; padding: 1.4rem 1.25rem 3rem; }}
    a {{ color: #75b9ff; text-decoration-thickness: 1px; }}
    a:hover {{ color: #b8dcff; }}
    .boundary {{ display: inline-block; margin-top: .8rem; padding: .32rem .62rem;
      border: 1px solid #2e7d6b; border-radius: 999px; color: #7ee2c6; font-size: .82rem;
      font-weight: 700; letter-spacing: .04em; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
      gap: 1rem; }}
    .card, section {{ background: #101c2e; border: 1px solid #283d57; border-radius: 12px;
      padding: 1rem; margin-bottom: 1rem; box-shadow: 0 8px 24px rgba(0,0,0,.16); }}
    .card h2, section h2 {{ margin: 0 0 .7rem; font-size: 1.12rem; }}
    .meta {{ color: #a9bbd1; font-size: .9rem; }}
    .mono {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace; overflow-wrap: anywhere; }}
    .badge {{ display: inline-block; padding: .22rem .48rem; border-radius: 6px;
      background: #263c58; font-size: .78rem; font-weight: 750; letter-spacing: .025em; }}
    .badge-succeeded, .badge-approved, .badge-changed, .badge-unchanged {{ background:#174c3b; color:#8ff0ca; }}
    .badge-failed, .badge-ambiguous, .badge-blocked {{ background:#5a2730; color:#ffb4c0; }}
    .badge-no-write, .badge-not-recorded, .badge-partial {{ background:#4d421c; color:#f7dd81; }}
    .badge-causality {{ background:#543c16; color:#ffd981; border:1px solid #967329; }}
    dl {{ display:grid; grid-template-columns:minmax(145px, .38fr) 1fr; gap:.45rem .9rem; margin:0; }}
    dt {{ color:#91a7c0; }} dd {{ margin:0; overflow-wrap:anywhere; }}
    table {{ width:100%; border-collapse:collapse; }} th,td {{ text-align:left; vertical-align:top;
      padding:.55rem .5rem; border-bottom:1px solid #29415f; }} th {{ color:#9eb2c9; font-size:.82rem; }}
    .callout {{ border-left:4px solid #d6a83b; background:#2a2415; padding:.8rem 1rem;
      margin:.8rem 0; border-radius:6px; }}
    .attempt {{ border:1px solid #344b67; border-radius:9px; padding:.8rem; margin-top:.7rem; }}
    .attempt h3 {{ margin:0 0 .6rem; }}
    .back {{ display:inline-block; margin-bottom:1rem; }}
    @media (max-width: 650px) {{ dl {{ grid-template-columns:1fr; }} dt {{ margin-top:.35rem; }} }}
  </style>
</head>
<body>
<header>
  <h1>NCDP Durable Evidence</h1>
  <p>Validated correlation across reviewed intent, protected delivery, and observed configuration metadata.</p>
  <span class="boundary">READ-ONLY · LOOPBACK ONLY · DURABLE AUDIT AUTHORITY</span>
</header>
<main>{body}</main>
</body>
</html>
"""
    return content.encode("utf-8")


def _targets(values: tuple[TargetPresentation, ...]) -> str:
    rows = []
    for value in values:
        identity = _escape(value.device)
        if value.interface is not None:
            identity += f'<br><span class="meta mono">{_escape(value.interface)}</span>'
        rows.append(identity)
    return "<br>".join(rows)


def render_index(values: tuple[RecordSummaryPresentation, ...]) -> bytes:
    cards: list[str] = []
    for value in values:
        approval = (
            _badge("APPROVED", emphasis="approved")
            if value.approved
            else _badge("NOT RECORDED", emphasis="not-recorded")
        )
        build = (
            str(value.build_number)
            if value.build_number is not None
            else "NOT RECORDED"
        )
        cards.append(
            f"""<article class="card">
  <h2><a href="/records/{value.record_id}">{_escape(value.change_id)}</a></h2>
  <p>{_badge(value.final_outcome)} {approval}</p>
  <dl>
    <dt>Generated</dt><dd>{_escape(_index_timestamp(value.generated_at))}</dd>
    <dt>Buildkite build</dt><dd>{_escape(build)}</dd>
    <dt>Git commit</dt><dd class="mono">{_escape(value.commit[:12])}</dd>
    <dt>Targets</dt><dd class="mono">{_targets(value.targets)}</dd>
  </dl>
</article>"""
        )
    if not cards:
        cards.append(
            '<section><h2>No durable evidence records</h2><p class="meta">The existing store is valid and currently empty.</p></section>'
        )
    body = (
        f'<p class="meta">Newest validated records · maximum {MAX_PRESENTED_RECORDS}</p><div class="grid">'
        + "".join(cards)
        + "</div>"
    )
    return _page("NCDP Durable Evidence", body)


def _external_link(url: str, label: object) -> str:
    return (
        f'<a href="{_escape(url)}" rel="noopener noreferrer" target="_blank">'
        f"{_escape(label)}</a>"
    )


def _revision_block(label: str, value: RevisionPresentation | None) -> str:
    if value is None:
        return f'<h4>{_escape(label)}</h4><p class="meta">NOT RECORDED</p>'
    return f"""<h4>{_escape(label)}</h4>
<dl>
  <dt>Commit object</dt><dd class="mono">{_escape(value.commit)}</dd>
  <dt>Blob object</dt><dd class="mono">{_escape(value.blob)}</dd>
  <dt>Collected</dt><dd>{_escape(_timestamp(value.collected_at))}</dd>
</dl>"""


def _attempt_block(value: AttemptPresentation) -> str:
    failure = ""
    if value.failure_category is not None:
        failure = (
            f"\n    <dt>Failure category</dt><dd>{_escape(value.failure_category)}</dd>"
        )
    return f"""<div class="attempt">
  <h3>{_escape(value.label)} · {_badge(value.status)}</h3>
  <dl>
    <dt>Requested</dt><dd>{_escape(_timestamp(value.requested_at))}</dd>
    <dt>Completed</dt><dd>{_escape(_timestamp(value.completed_at))}</dd>{failure}
  </dl>
  <div class="grid">
    <div>{_revision_block("Before revision", value.before_revision)}</div>
    <div>{_revision_block("After revision", value.after_revision)}</div>
  </div>
</div>"""


def _observation_block(value: ObservationPresentation) -> str:
    attempts = "".join(_attempt_block(item) for item in value.attempts)
    return f"""<section>
  <h2>Configuration observation · {_badge(value.overall_status)}</h2>
  <div class="callout"><strong>Causality: {_badge(value.causality, emphasis="causality")}</strong><br>
    Temporal correlation does not prove that this delivery caused the observed revision.</div>
  <dl>
    <dt>Observation record</dt><dd class="mono">{_escape(value.record_id)}</dd>
    <dt>Generated</dt><dd>{_escape(_timestamp(value.generated_at))}</dd>
    <dt>Digest</dt><dd class="mono">{_escape(value.digest)}</dd>
    <dt>Target</dt><dd class="mono">{_escape(value.target)}</dd>
    <dt>Repository identity</dt><dd class="mono">{_escape(value.repository)}</dd>
    <dt>Relationship</dt><dd>{_badge(value.relationship)}</dd>
  </dl>
  {attempts}
</section>"""


def render_record(value: RecordDetailPresentation) -> bytes:
    commit = _escape(value.commit)
    repository = _escape(value.repository)
    pull_request = "NOT RECORDED"
    if value.repository == GITHUB_REPOSITORY_IDENTITY:
        commit = _external_link(
            f"{GITHUB_REPOSITORY_URL}/commit/{value.commit}", value.commit
        )
        if value.pull_request is not None:
            pull_request = _external_link(
                f"{GITHUB_REPOSITORY_URL}/pull/{value.pull_request}",
                f"#{value.pull_request}",
            )
    elif value.pull_request is not None:
        pull_request = f"#{value.pull_request}"
    build = "NOT RECORDED"
    if value.build_number is not None:
        build = _external_link(
            f"{BUILDKITE_PIPELINE_URL}/builds/{value.build_number}",
            f"Build #{value.build_number}",
        )
    approval = (
        _badge("APPROVED", emphasis="approved")
        if value.approved
        else _badge("NOT RECORDED", emphasis="not-recorded")
    )
    target_rows = "".join(
        f'<tr><td class="mono">{_escape(item.device)}</td><td class="mono">{_escape(item.interface or "NOT RECORDED")}</td></tr>'
        for item in value.targets
    )
    artifact_rows = "".join(
        f'<tr><td>{_escape(item.kind)}</td><td>{_escape(item.schema_version)}</td><td class="mono">{_escape(item.digest)}</td></tr>'
        for item in value.artifacts
    )
    observations = "".join(_observation_block(item) for item in value.observations)
    if not observations:
        observations = '<section><h2>Configuration observations</h2><p class="meta">No correlated configuration-observation record.</p></section>'
    body = f"""<a class="back" href="/">← All durable evidence</a>
<section>
  <h2>Audit identity · {_badge(value.final_outcome)}</h2>
  <dl>
    <dt>Record ID</dt><dd class="mono">{_escape(value.record_id)}</dd>
    <dt>Generated</dt><dd>{_escape(_timestamp(value.generated_at))}</dd>
    <dt>Audit digest</dt><dd class="mono">{_escape(value.digest)}</dd>
    <dt>Change ID</dt><dd>{_escape(value.change_id)}</dd>
  </dl>
</section>
<div class="grid">
  <section><h2>Reviewed Git identity</h2><dl>
    <dt>Repository</dt><dd class="mono">{repository}</dd>
    <dt>Commit</dt><dd class="mono">{commit}</dd>
    <dt>Pull request</dt><dd>{pull_request}</dd>
  </dl></section>
  <section><h2>Protected delivery</h2><dl>
    <dt>Buildkite</dt><dd>{build}</dd>
    <dt>Step</dt><dd class="mono">{_escape(value.step_key or "NOT RECORDED")}</dd>
    <dt>Approval</dt><dd>{approval}</dd>
  </dl></section>
</div>
<section><h2>Stable targets</h2><table><thead><tr><th>Device identity</th><th>Interface identity</th></tr></thead><tbody>{target_rows}</tbody></table></section>
<section><h2>Bound artifact integrity</h2><table><thead><tr><th>Kind</th><th>Schema</th><th>Digest</th></tr></thead><tbody>{artifact_rows}</tbody></table></section>
{observations}
"""
    return _page(f"NCDP Evidence · {value.change_id}", body)


def _error_page(status: HTTPStatus) -> bytes:
    message = {
        HTTPStatus.NOT_FOUND: "The requested evidence view does not exist.",
        HTTPStatus.METHOD_NOT_ALLOWED: "This read-only viewer accepts GET and HEAD only.",
        HTTPStatus.INTERNAL_SERVER_ERROR: "Durable evidence validation failed closed.",
    }[status]
    return _page(
        status.phrase,
        f"<section><h2>{status.value} · {_escape(status.phrase)}</h2><p>{_escape(message)}</p></section>",
    )


class EvidenceViewerApplication:
    """Read-only request application over one validated existing store."""

    def __init__(self, store: ConfigurationObservationStore) -> None:
        self.store = store

    def get(self, route: str) -> tuple[HTTPStatus, bytes]:
        parsed = urlsplit(route)
        if parsed.query or parsed.fragment:
            return HTTPStatus.NOT_FOUND, _error_page(HTTPStatus.NOT_FOUND)
        if parsed.path == "/":
            records = sorted(
                self.store.iter_records(),
                key=lambda item: (item.generated_at, str(item.record_id)),
                reverse=True,
            )[:MAX_PRESENTED_RECORDS]
            return HTTPStatus.OK, render_index(
                tuple(_summary(item) for item in records)
            )
        prefix = "/records/"
        if parsed.path.startswith(prefix) and parsed.path.count("/") == 2:
            identity = parsed.path.removeprefix(prefix)
            try:
                record_id = UUID(identity)
            except ValueError:
                return HTTPStatus.NOT_FOUND, _error_page(HTTPStatus.NOT_FOUND)
            if identity != str(record_id):
                return HTTPStatus.NOT_FOUND, _error_page(HTTPStatus.NOT_FOUND)
            try:
                record = self.store.read_record(record_id)
                observations = self.store.find_by_parent(record_id)
            except AuditStoreError:
                return HTTPStatus.NOT_FOUND, _error_page(HTTPStatus.NOT_FOUND)
            return HTTPStatus.OK, render_record(_detail(record, observations))
        return HTTPStatus.NOT_FOUND, _error_page(HTTPStatus.NOT_FOUND)


class EvidenceViewerServer(ThreadingHTTPServer):
    """Threaded loopback server with bounded shutdown behavior."""

    daemon_threads = True


def create_server(
    store: ConfigurationObservationStore, *, port: int = DEFAULT_PORT
) -> EvidenceViewerServer:
    """Create a loopback-only HTTP server for an already-open read-only store."""

    if not 0 <= port <= 65535:
        raise ValueError("viewer port is invalid")
    application = EvidenceViewerApplication(store)

    class Handler(BaseHTTPRequestHandler):
        server_version = "NCDPEvidenceViewer/1"
        sys_version = ""

        def _send(
            self, status: HTTPStatus, content: bytes, *, head: bool = False
        ) -> None:
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            for name, value in SECURITY_HEADERS.items():
                self.send_header(name, value)
            self.send_header("Content-Length", str(len(content)))
            if status is HTTPStatus.METHOD_NOT_ALLOWED:
                self.send_header("Allow", "GET, HEAD")
            self.end_headers()
            if not head:
                self.wfile.write(content)

        def _read(self, *, head: bool = False) -> None:
            try:
                status, content = application.get(self.path)
            except AuditStoreError:
                status = HTTPStatus.INTERNAL_SERVER_ERROR
                content = _error_page(status)
            self._send(status, content, head=head)

        def do_GET(self) -> None:
            self._read()

        def do_HEAD(self) -> None:
            self._read(head=True)

        def _reject_method(self) -> None:
            self._send(
                HTTPStatus.METHOD_NOT_ALLOWED,
                _error_page(HTTPStatus.METHOD_NOT_ALLOWED),
            )

        def do_POST(self) -> None:
            self._reject_method()

        def do_PUT(self) -> None:
            self._reject_method()

        def do_PATCH(self) -> None:
            self._reject_method()

        def do_DELETE(self) -> None:
            self._reject_method()

        def do_OPTIONS(self) -> None:
            self._reject_method()

        def log_message(self, _format: str, *_arguments: object) -> None:
            return

    return EvidenceViewerServer((LOOPBACK_ADDRESS, port), Handler)


def _checkout_root() -> Path:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise ValueError("unable to establish repository checkout root") from error
    root = Path(result.stdout.strip())
    if not root.is_absolute() or not root.is_dir():
        raise ValueError("unable to establish repository checkout root")
    return root


def main() -> int:
    """Run the foreground, loopback-only durable-evidence viewer."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit-root", required=True, type=Path)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    arguments = parser.parse_args()
    store = ConfigurationObservationStore(
        arguments.audit_root, checkout=_checkout_root(), create=False
    )
    server = create_server(store, port=arguments.port)
    actual_port = int(server.server_address[1])
    print(f"NCDP evidence viewer: http://{LOOPBACK_ADDRESS}:{actual_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
