"""Loopback HTTP and presentation-security tests for the evidence viewer."""

from __future__ import annotations

import hashlib
import http.client
import json
import stat
import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import UUID

import pytest
from test_audit_store import plan, record
from test_configuration_observation import unchanged_observation
from test_configuration_observation_store import linked_record
from test_snmp_protected_deployment import snmp_plan

import network_change_delivery.evidence_viewer as viewer_module
from network_change_delivery.audit import (
    AuditArtifactKind,
    BuildkiteCorrelation,
    CredentialProvenance,
    GitCorrelation,
    ProtectedApprovalBoundary,
    StableTargetIdentity,
    canonical_json_bytes,
)
from network_change_delivery.configuration_observation import (
    ObservationRelationship,
    ParentAuditReference,
    observation_record_with_digest,
)
from network_change_delivery.configuration_observation_store import (
    ConfigurationObservationStore,
)
from network_change_delivery.evidence_viewer import (
    GITHUB_REPOSITORY_URL,
    MAX_PRESENTED_RECORDS,
    SECURITY_HEADERS,
    create_server,
)

SECRET_MARKERS = (
    "openbao:kv-v2:ncdp/devices/1/ssh",
    "environment:NCDP_DEVICE_USERNAME/PASSWORD",
    "snmpv3:netbox:dcim.device:1:generation:v1",
    "audit-store-test",
    "managed/netbox-device-1",
)


def _populated_store(
    tmp_path: Path,
) -> tuple[ConfigurationObservationStore, object, object]:
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    root = tmp_path / "audit"
    root.mkdir(mode=0o700)
    writable = ConfigurationObservationStore(root, checkout=checkout)
    reference = writable.persist_artifact(AuditArtifactKind.DEPLOYMENT_PLAN, plan())
    parent = record(
        reference,
        change_id="CHG-<script>alert(1)</script>",
        git=GitCorrelation(
            repository="github:Atheer-Kareem/network-change-delivery-platform",
            commit="a" * 40,
            pull_request=101,
        ),
        buildkite=BuildkiteCorrelation(
            pipeline_id=UUID(int=11),
            build_id=UUID(int=12),
            build_number=275,
            job_id=UUID(int=13),
            step_key="deploy-gate",
        ),
        approval=ProtectedApprovalBoundary(),
        credentials=(
            CredentialProvenance(
                device="netbox:dcim.device:1",
                source="environment",
                reference="environment:NCDP_DEVICE_USERNAME/PASSWORD",
            ),
            CredentialProvenance(
                device="netbox:dcim.device:1",
                source="openbao",
                reference="openbao:kv-v2:ncdp/devices/1/ssh",
            ),
        ),
    )
    writable.persist_record(parent)
    observation = linked_record(
        parent,
        pre_observation=unchanged_observation(hour=0),
        post_observation=unchanged_observation(hour=1),
        relationship=ObservationRelationship.TEMPORALLY_BRACKETED,
    )
    writable.persist_observation_record(observation)
    snmp_reference = writable.persist_artifact(
        AuditArtifactKind.SNMP_PROVISIONING_PLAN, snmp_plan()
    )
    writable.persist_record(
        record(
            snmp_reference,
            record_id=UUID(int=77),
            change_id="CHG-SNMP-VIEWER",
            targets=(StableTargetIdentity(device="netbox:dcim.device:1"),),
            credentials=(
                CredentialProvenance(
                    device="netbox:dcim.device:1",
                    source="openbao",
                    reference="openbao:kv-v2:ncdp/devices/1/ssh",
                ),
                CredentialProvenance(
                    device="netbox:dcim.device:1",
                    source="openbao_snmp",
                    reference="snmpv3:netbox:dcim.device:1:generation:v1",
                ),
            ),
        )
    )
    readonly = ConfigurationObservationStore(root, checkout=checkout, create=False)
    return readonly, parent, observation


@contextmanager
def _running(
    store: ConfigurationObservationStore,
) -> Iterator[tuple[str, object]]:
    server = create_server(store, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        yield base, server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        assert not thread.is_alive()


def _request(
    base: str, path: str, *, method: str = "GET"
) -> tuple[int, dict[str, str], bytes]:
    request = Request(base + path, method=method)
    try:
        response = urlopen(request, timeout=5)
    except HTTPError as error:
        response = error
    with response:
        return response.status, dict(response.headers.items()), response.read()


def _snapshot(root: Path) -> tuple[tuple[object, ...], ...]:
    entries: list[tuple[object, ...]] = []
    for path in sorted((root, *root.rglob("*"))):
        relative = path.relative_to(root).as_posix() if path != root else "."
        metadata = path.lstat()
        if stat.S_ISREG(metadata.st_mode):
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        elif stat.S_ISLNK(metadata.st_mode):
            digest = str(path.readlink())
        else:
            digest = None
        entries.append(
            (
                relative,
                stat.S_IFMT(metadata.st_mode),
                stat.S_IMODE(metadata.st_mode),
                metadata.st_size,
                metadata.st_mtime_ns,
                digest,
            )
        )
    return tuple(entries)


def test_index_and_detail_are_allowlisted_escaped_and_linked(tmp_path: Path) -> None:
    store, parent, observation = _populated_store(tmp_path)
    with _running(store) as (base, _server):
        index_status, index_headers, index_content = _request(base, "/")
        detail_status, detail_headers, detail_content = _request(
            base, f"/records/{parent.record_id}"
        )

    index = index_content.decode()
    detail = detail_content.decode()
    assert index_status == detail_status == 200
    assert "NCDP Durable Evidence" in index
    assert f"maximum {MAX_PRESENTED_RECORDS}" in index
    assert "CHG-&lt;script&gt;alert(1)&lt;/script&gt;" in index
    assert "<script>alert(1)</script>" not in index
    assert "APPROVED" in index
    assert "TEMPORALLY_BRACKETED" in detail
    assert "Causality: " in detail and "NOT_PROVEN" in detail
    assert "Temporal correlation does not prove" in detail
    assert "PRE" in detail and "POST" in detail
    assert str(observation.observation_record_id) in detail
    assert f"{GITHUB_REPOSITORY_URL}/commit/{'a' * 40}" in detail
    assert f"{GITHUB_REPOSITORY_URL}/pull/101" in detail
    assert "/builds/275" in detail
    assert "noopener noreferrer" in detail
    assert "deployment_plan" in detail
    assert parent.artifacts[0].sha256 in detail
    assert parent.artifacts[0].locator not in detail
    for marker in (*SECRET_MARKERS, str(store.root), str(tmp_path / "checkout")):
        assert marker not in index
        assert marker not in detail
    for headers in (index_headers, detail_headers):
        assert headers["Content-Type"] == "text/html; charset=utf-8"
        for name, value in SECURITY_HEADERS.items():
            assert headers[name] == value


def test_get_head_missing_and_all_unsupported_methods_are_bounded(
    tmp_path: Path,
) -> None:
    store, _parent, _observation = _populated_store(tmp_path)
    with _running(store) as (base, _server):
        status, headers, body = _request(base, "/", method="HEAD")
        assert status == 200 and body == b""
        assert int(headers["Content-Length"]) > 0
        for route in (
            "/api",
            "/json",
            "/download",
            "/artifacts",
            "/files",
            "/config",
            "/raw",
            "/retry",
            "/recover",
            "/collect",
            "/deploy",
            "/records/not-a-uuid",
            f"/records/{UUID(int=99)}",
            "/records/AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA",
            "/?search=anything",
        ):
            missing_status, _missing_headers, missing = _request(base, route)
            assert missing_status == 404
            assert b"requested evidence view does not exist" in missing
        for method in ("POST", "PUT", "PATCH", "DELETE", "OPTIONS"):
            method_status, method_headers, method_body = _request(
                base, "/", method=method
            )
            assert method_status == 405
            assert method_headers["Allow"] == "GET, HEAD"
            assert b"read-only viewer" in method_body


def test_every_http_route_is_filesystem_read_only(tmp_path: Path) -> None:
    store, parent, _observation = _populated_store(tmp_path)
    before = _snapshot(store.root)
    with _running(store) as (base, _server):
        routes = (
            ("GET", "/"),
            ("GET", f"/records/{parent.record_id}"),
            ("GET", "/missing"),
            ("POST", "/"),
            ("DELETE", f"/records/{parent.record_id}"),
        )
        for method, route in routes:
            _request(base, route, method=method)
    assert _snapshot(store.root) == before


@pytest.mark.parametrize(
    "corruption",
    ["malformed", "invalid-digest", "unknown-field", "symlink", "oversized"],
)
def test_malformed_tampered_symlinked_and_oversized_records_fail_closed(
    tmp_path: Path, corruption: str
) -> None:
    store, parent, _observation = _populated_store(tmp_path)
    path = store.root / "records" / f"{parent.record_id}.json"
    if corruption == "malformed":
        path.write_bytes(b"{")
    elif corruption == "invalid-digest":
        payload = json.loads(path.read_bytes())
        payload["digest"] = "sha256:" + "f" * 64
        path.write_bytes(canonical_json_bytes(payload))
    elif corruption == "unknown-field":
        payload = json.loads(path.read_bytes())
        payload["arbitrary_json"] = "DO-NOT-RENDER"
        path.write_bytes(canonical_json_bytes(payload))
    elif corruption == "symlink":
        replacement = tmp_path / "replacement.json"
        replacement.write_bytes(path.read_bytes())
        replacement.chmod(0o600)
        path.unlink()
        path.symlink_to(replacement)
    else:
        path.write_bytes(b"x" * (256 * 1024 + 1))

    with _running(store) as (base, _server):
        status, _headers, body = _request(base, "/")
    assert status == 500
    assert b"validation failed closed" in body
    assert b"DO-NOT-RENDER" not in body
    assert str(path).encode() not in body


def test_unexpected_store_entry_fails_closed_without_echo(tmp_path: Path) -> None:
    store, _parent, _observation = _populated_store(tmp_path)
    unexpected = store.root / "records" / "SECRET-UNEXPECTED"
    unexpected.write_text("DO-NOT-RENDER", encoding="utf-8")
    with _running(store) as (base, _server):
        status, _headers, body = _request(base, "/")
    assert status == 500
    assert b"DO-NOT-RENDER" not in body
    assert b"SECRET-UNEXPECTED" not in body


@pytest.mark.parametrize("invalid", ["parent-digest", "target"])
def test_invalid_observation_correlation_fails_closed(
    tmp_path: Path, invalid: str
) -> None:
    store, parent, observation = _populated_store(tmp_path)
    path = (
        store.root / "observation-records" / f"{observation.observation_record_id}.json"
    )
    values = observation.model_dump(mode="python", exclude={"digest"})
    if invalid == "parent-digest":
        values["parent_audit"] = ParentAuditReference(
            record_id=parent.record_id, digest="sha256:" + "f" * 64
        )
    else:
        values["target"] = "netbox:dcim.device:2"
        values["oxidized_node"] = "netbox-device-2"
    invalid_record = observation_record_with_digest(**values)
    path.write_bytes(canonical_json_bytes(invalid_record.model_dump(mode="json")))

    with _running(store) as (base, _server):
        status, _headers, body = _request(base, f"/records/{parent.record_id}")
    assert status == 404
    assert b"parent digest" not in body
    assert b"target is not in parent" not in body
    assert str(path).encode() not in body


def test_server_socket_is_ipv4_loopback_only(tmp_path: Path) -> None:
    store, _parent, _observation = _populated_store(tmp_path)
    server = create_server(store, port=0)
    try:
        assert server.server_address[0] == "127.0.0.1"
        connection = http.client.HTTPConnection(
            server.server_address[0], server.server_address[1]
        )
        connection.close()
    finally:
        server.server_close()


def test_cli_opens_create_false_and_prints_only_loopback_url(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    audit_root = tmp_path / "private-audit"
    checkout = tmp_path / "checkout"
    observed: dict[str, object] = {}

    class FakeStore:
        def __init__(self, root: Path, *, checkout: Path, create: bool = True) -> None:
            observed.update(root=root, checkout=checkout, create=create)

    class FakeServer:
        server_address = ("127.0.0.1", 43123)

        def serve_forever(self) -> None:
            observed["served"] = True

        def server_close(self) -> None:
            observed["closed"] = True

    monkeypatch.setattr(viewer_module, "ConfigurationObservationStore", FakeStore)
    monkeypatch.setattr(viewer_module, "_checkout_root", lambda: checkout)

    def fake_create_server(store: object, *, port: int) -> FakeServer:
        assert isinstance(store, FakeStore)
        assert port == 0
        return FakeServer()

    monkeypatch.setattr(viewer_module, "create_server", fake_create_server)
    monkeypatch.setattr(
        sys,
        "argv",
        ["ncdp-evidence-viewer", "--audit-root", str(audit_root), "--port", "0"],
    )

    assert viewer_module.main() == 0

    assert observed == {
        "root": audit_root,
        "checkout": checkout,
        "create": False,
        "served": True,
        "closed": True,
    }
    output = capsys.readouterr().out
    assert output == "NCDP evidence viewer: http://127.0.0.1:43123\n"
    assert str(audit_root) not in output
