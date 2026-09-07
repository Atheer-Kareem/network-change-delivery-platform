"""Allowlisted mixed-family viewer routes over synthetic temporary evidence only."""

from dataclasses import replace
from datetime import timedelta
from uuid import UUID

import pytest
from profiled_audit_fixtures import NOW, bundle
from test_audit_store import plan, store_snapshot
from test_audit_store import record as legacy_record
from test_evidence_viewer import _request, _running
from test_profiled_audit import rehash

from network_change_delivery.audit import AuditArtifactKind as Kind
from network_change_delivery.configuration_observation_store import (
    ConfigurationObservationStore,
)
from network_change_delivery.evidence_viewer import (
    MAX_PRESENTED_RECORDS,
    SECURITY_HEADERS,
    EvidenceViewerApplication,
    _profiled_detail,
    render_record,
)
from network_change_delivery.profiled_audit import ProfiledDeliveryAuditRecord


@pytest.fixture
def mixed_store(tmp_path):
    checkout, root = tmp_path / "checkout", tmp_path / "audit"
    checkout.mkdir()
    root.mkdir(mode=0o700)
    store = ConfigurationObservationStore(root, checkout=checkout)
    current, raw, _ = bundle(store)
    store.persist_profiled_record(current, artifact_bytes=raw)
    compliant, raw, _ = bundle(store, compliant=True, record_id=UUID(int=98))
    data = compliant.model_dump(mode="json")
    data["generated_at"] = (
        (NOW + timedelta(minutes=1)).isoformat().replace("+00:00", "Z")
    )
    compliant = ProfiledDeliveryAuditRecord.model_validate(rehash(data))
    store.persist_profiled_record(compliant, artifact_bytes=raw)
    # The same UUID intentionally exists in different record families.
    historical = legacy_record(
        store.persist_artifact(Kind.DEPLOYMENT_PLAN, plan()),
        record_id=current.record_id,
        change_id="CHG-HISTORICAL",
    )
    store.persist_record(historical)
    return (
        ConfigurationObservationStore(root, checkout=checkout, create=False),
        current,
        compliant,
        historical,
    )


def test_mixed_index_sorts_by_time_and_routes_same_uuid_unambiguously(mixed_store):
    store, current, compliant, historical = mixed_store
    app = EvidenceViewerApplication(store)
    status, content = app.get("/")
    page = content.decode()
    assert status == 200
    assert (
        "Current profiled delivery" in page and "Historical protected delivery" in page
    )
    paths = [
        f"/profiled-records/{compliant.record_id}",
        f"/profiled-records/{current.record_id}",
        f"/records/{historical.record_id}",
    ]
    assert [page.index(path) for path in paths] == sorted(
        page.index(path) for path in paths
    )
    current_page = app.get(paths[1])[1].decode()
    old_page = app.get(paths[2])[1].decode()
    assert (
        "Current profiled delivery" in current_page
        and "Historical protected delivery" not in current_page
    )
    assert "CHG-HISTORICAL" in old_page and "Current profiled delivery" not in old_page
    assert (
        "Current PRE/write/POST delivery correlation not connected yet." in current_page
    )
    assert "No correlated configuration-observation record." in old_page


@pytest.mark.parametrize("compliance", [False, True])
def test_current_detail_allowlist_and_http_security(mixed_store, compliance):
    store, execution, compliant, _ = mixed_store
    value = compliant if compliance else execution
    before = store_snapshot(store.root)
    with _running(store) as (base, _server):
        status, headers, body = _request(base, f"/profiled-records/{value.record_id}")
        assert status == 200
        for name, expected in SECURITY_HEADERS.items():
            assert headers[name] == expected
        page = body.decode()
        for text in (
            str(value.record_id),
            value.git.repository,
            value.git.commit,
            str(value.buildkite.build_id),
            str(value.buildkite.job_id),
            "profiled-deploy",
            value.planning_result_digest,
        ):
            assert text in page
        for ref in value.artifacts:
            assert ref.kind.value in page and ref.sha256 in page
            assert ref.locator not in page
        for digest in value.byte_digests_by_kind().values():
            assert digest in page
        for forbidden in (
            value.credential.reference,
            "credential_reference",
            "credentials",
            str(store.root),
            "192.168.4.",
            "managed-by-ncdp-profiled-demo",
            "previous",
            "configuration_lines",
            "unblocker_id",
        ):
            assert forbidden not in page
        if compliance:
            assert "NOT REQUIRED — COMPLIANT" in page
            assert (
                "profiled_promotion" not in page
                and "profiled_change_record" not in page
            )
            assert "profiled-human-authorization" not in page
        else:
            assert "APPROVED" in page and "profiled-human-authorization" in page
            assert value.authorization.promotion_digest in page
            for digest in value.assurance.model_dump().values():
                assert digest in page
        status, headers, body = _request(
            base, f"/profiled-records/{value.record_id}", method="HEAD"
        )
        assert status == 200 and body == b"" and headers["Cache-Control"] == "no-store"
        assert (
            _request(base, f"/profiled-records/{value.record_id}", method="POST")[0]
            == 405
        )
        for path in (
            value.artifacts[0].locator,
            f"profiled-records/{value.record_id}.json",
            "profiled-artifact-bytes/test.json",
            f"profiled-records/{value.record_id}?raw=true",
        ):
            assert _request(base, "/" + path)[0] == 404
    assert store_snapshot(store.root) == before


def test_profiled_rendering_escapes_untrusted_metadata(mixed_store):
    _, current, _, _ = mixed_store
    detail = replace(_profiled_detail(current), change_id='<script>alert("x")</script>')
    page = render_record(detail).decode()
    assert "<script>" not in page and "&lt;script&gt;" in page
    assert "openbao:" not in page and "artifacts/" not in page


def test_combined_index_limit_applies_to_both_families(mixed_store, monkeypatch):
    store, current, compliant, historical = mixed_store
    monkeypatch.setattr(
        store, "iter_records", lambda: (historical,) * MAX_PRESENTED_RECORDS
    )
    monkeypatch.setattr(
        store,
        "iter_profiled_records",
        lambda: (current, compliant) * MAX_PRESENTED_RECORDS,
    )
    page = EvidenceViewerApplication(store).get("/")[1].decode()
    assert page.count('<article class="card">') == MAX_PRESENTED_RECORDS


def test_current_detail_does_not_load_historical_chronology(mixed_store, monkeypatch):
    store, current, _, _ = mixed_store
    monkeypatch.setattr(
        store,
        "find_by_parent",
        lambda *_a: pytest.fail("historical chronology must not attach"),
    )
    assert (
        EvidenceViewerApplication(store).get(f"/profiled-records/{current.record_id}")[
            0
        ]
        == 200
    )


def test_invalid_current_artifact_fails_closed_without_leaking_path(mixed_store):
    store, current, _, _ = mixed_store
    (store.root / current.artifacts[0].locator).unlink()
    with _running(store) as (base, _server):
        status, _, body = _request(base, f"/profiled-records/{current.record_id}")
        assert status == 404 and str(store.root).encode() not in body
        status, headers, body = _request(base, "/")
        assert status == 500 and headers["Cache-Control"] == "no-store"
        assert b"failed closed" in body and str(store.root).encode() not in body
