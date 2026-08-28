from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from network_change_delivery.observability_realization import (
    ADMISSION_TTL,
    CmlRealizationAuthority,
    ObservabilityRealizationError,
    publish_admission,
    read_admission,
    retire_admission,
)

LAB = "11111111-1111-1111-1111-111111111111"
LEGACY = "09605569-0468-4fc4-8684-beb5a1342b9c"
CORE = "22222222-2222-2222-2222-222222222222"
JUNOS = "33333333-3333-3333-3333-333333333333"


def transport(
    *,
    staging: bool = False,
    legacy_running: bool = False,
    booted: bool = True,
    foreign_conflict: bool = False,
    configuration_shape: str = "endpoint-string",
    list_payload: object | None = None,
):
    foreign = "55555555-5555-5555-5555-555555555555"
    labs = (
        [LAB, LEGACY]
        + (["44444444-4444-4444-4444-444444444444"] if staging else [])
        + ([foreign] if foreign_conflict else [])
    )

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/v0/authenticate":
            return httpx.Response(200, json="private-token")
        if path == "/api/v0/labs":
            return httpx.Response(200, json=labs)
        if path == f"/api/v0/labs/{LAB}":
            return httpx.Response(200, json={"lab_title": "NCDP Terraform Twin"})
        if path == f"/api/v0/labs/{LEGACY}":
            return httpx.Response(200, json={"lab_title": "legacy"})
        if staging and path.endswith("44444444-4444-4444-4444-444444444444"):
            return httpx.Response(200, json={"lab_title": "NCDP Staging test"})
        if foreign_conflict and path == f"/api/v0/labs/{foreign}":
            return httpx.Response(200, json={"lab_title": "foreign"})
        if foreign_conflict and path == f"/api/v0/labs/{foreign}/nodes":
            return httpx.Response(200, json=["foreign-node"])
        if foreign_conflict and path == f"/api/v0/labs/{foreign}/nodes/foreign-node":
            return httpx.Response(200, json={"state": "BOOTED"})
        if foreign_conflict and path == (
            f"/api/v0/labs/{foreign}/nodes/foreign-node/configuration"
        ):
            return httpx.Response(200, json="foreign 192.168.4.14")
        if path == f"/api/v0/labs/{LEGACY}/nodes":
            return httpx.Response(200, json=["legacy-node"])
        if path == f"/api/v0/labs/{LEGACY}/nodes/legacy-node":
            return httpx.Response(
                200, json={"state": "BOOTED" if legacy_running else "STOPPED"}
            )
        if path == f"/api/v0/labs/{LAB}/nodes":
            return httpx.Response(200, json=[CORE, JUNOS])
        if path == f"/api/v0/labs/{LAB}/nodes/{CORE}":
            payload = {
                "label": "core-02",
                "node_definition": "cat8000v",
                "image_definition": "cat8000v-17-18-02",
                "state": "BOOTED" if booted else "STOPPED",
            }
            if configuration_shape == "node-list":
                payload["configuration"] = (
                    [{"content": "hostname core-02 192.168.4.14"}]
                    if list_payload is None
                    else list_payload
                )
            if configuration_shape == "node-string":
                payload["configuration"] = "hostname core-02 192.168.4.14"
            return httpx.Response(200, json=payload)
        if path == f"/api/v0/labs/{LAB}/nodes/{JUNOS}":
            payload = {
                "label": "edge-junos-01",
                "node_definition": "vjunos-router",
                "image_definition": "vjunos-router-23-2r1-15",
                "state": "BOOTED" if booted else "STOPPED",
            }
            if configuration_shape == "node-list":
                payload["configuration"] = (
                    [{"content": "host-name edge-junos-01 192.168.4.20"}]
                    if list_payload is None
                    else list_payload
                )
            if configuration_shape == "node-string":
                payload["configuration"] = "host-name edge-junos-01 192.168.4.20"
            return httpx.Response(200, json=payload)
        if path == f"/api/v0/labs/{LAB}/nodes/{CORE}/configuration":
            if configuration_shape in {"node-list", "node-string"}:
                return httpx.Response(404)
            if configuration_shape == "endpoint-list":
                return httpx.Response(
                    200, json=[{"content": "hostname core-02 192.168.4.14"}]
                )
            if configuration_shape == "endpoint-dict":
                return httpx.Response(
                    200, json={"configuration": "hostname core-02 192.168.4.14"}
                )
            if configuration_shape == "endpoint-juniper-dict":
                return httpx.Response(
                    200,
                    json={"config/juniper.conf": "hostname core-02 192.168.4.14"},
                )
            return httpx.Response(200, json="hostname core-02 192.168.4.14")
        if path == f"/api/v0/labs/{LAB}/nodes/{JUNOS}/configuration":
            if configuration_shape in {"node-list", "node-string"}:
                return httpx.Response(404)
            if configuration_shape == "endpoint-list":
                return httpx.Response(
                    200,
                    json=[{"content": "host-name edge-junos-01 192.168.4.20"}],
                )
            if configuration_shape == "endpoint-dict":
                return httpx.Response(
                    200,
                    json={"configuration": "host-name edge-junos-01 192.168.4.20"},
                )
            if configuration_shape == "endpoint-juniper-dict":
                return httpx.Response(
                    200,
                    json={
                        "config/juniper.conf": "host-name edge-junos-01 192.168.4.20"
                    },
                )
            return httpx.Response(200, json="host-name edge-junos-01 192.168.4.20")
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def authority(**kwargs) -> CmlRealizationAuthority:
    return CmlRealizationAuthority(
        "https://cml.example",
        "-----BEGIN CERTIFICATE-----\ninvalid-for-mock\n-----END CERTIFICATE-----",
        "private-user",
        "private-password",
        transport=transport(**kwargs),
    )


@pytest.fixture(autouse=True)
def mock_tls(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "network_change_delivery.observability_realization.ssl.create_default_context",
        lambda **_kwargs: True,
    )


def admit(client: CmlRealizationAuthority, now=None):
    return client.admit(
        LAB,
        {
            "netbox:dcim.device:1": CORE,
            "netbox:dcim.device:2": JUNOS,
        },
        now=now,
    )


def test_exact_realization_admission_is_digest_bound_and_private(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 8, 28, tzinfo=UTC)
    client = authority()
    record = admit(client, now)
    client.close()
    assert record.expires_at == now + ADMISSION_TTL
    assert [item.cml_node_id for item in record.nodes] == [CORE, JUNOS]
    root = tmp_path / "external" / "observability"
    path = publish_admission(root, record)
    assert read_admission(root, now=now) == record
    assert path.stat().st_mode & 0o777 == 0o600
    assert "private" not in json.dumps(record.model_dump(mode="json"))


@pytest.mark.parametrize(
    "configuration_shape",
    (
        "endpoint-string",
        "endpoint-dict",
        "endpoint-juniper-dict",
        "endpoint-list",
        "node-string",
        "node-list",
    ),
)
def test_supported_stored_configuration_shapes_admit_exact_realization(
    configuration_shape: str,
) -> None:
    client = authority(configuration_shape=configuration_shape)
    record = admit(client)
    client.close()
    assert [node.cml_node_id for node in record.nodes] == [CORE, JUNOS]


@pytest.mark.parametrize(
    "payload",
    (
        [],
        [{"content": "marker"}, {"content": "duplicate"}],
        [{"content": "marker"}, {"other": "malformed"}],
        ["not-an-entry"],
        [{}],
        [{"content": None}],
        [{"content": 22}],
        [{"content": ""}],
        [{"content": {"nested": "value"}}],
    ),
)
def test_ambiguous_or_malformed_list_configuration_fails_closed(
    payload: object,
) -> None:
    client = authority(configuration_shape="node-list", list_payload=payload)
    with pytest.raises(ObservabilityRealizationError, match="Day-0 identity"):
        admit(client)
    client.close()


def test_oversized_configuration_response_fails_closed() -> None:
    oversized = "x" * (2 * 1024 * 1024 + 1)
    fallback = transport()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v0/authenticate":
            return httpx.Response(200, json="private-token")
        if request.url.path.endswith(f"/{CORE}/configuration"):
            return httpx.Response(200, json=oversized)
        return fallback.handle_request(request)

    client = CmlRealizationAuthority(
        "https://cml.example",
        "-----BEGIN CERTIFICATE-----\ninvalid-for-mock\n-----END CERTIFICATE-----",
        "private-user",
        "private-password",
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(ObservabilityRealizationError, match="Day-0 identity"):
        admit(client)
    client.close()


@pytest.mark.parametrize("fallback_shape", ("alternate-suffix", "node"))
def test_oversized_configuration_cannot_be_bypassed_by_valid_fallback(
    fallback_shape: str,
) -> None:
    oversized = "x" * (2 * 1024 * 1024 + 1)
    fallback = transport()

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/v0/authenticate":
            return httpx.Response(200, json="private-token")
        if path.endswith(f"/{CORE}/configuration"):
            return httpx.Response(200, json=oversized)
        if fallback_shape == "alternate-suffix" and path.endswith(
            f"/{CORE}/configurations"
        ):
            return httpx.Response(200, json="hostname core-02 192.168.4.14")
        if fallback_shape == "node" and path.endswith(f"/nodes/{CORE}"):
            response = fallback.handle_request(request)
            payload = response.json()
            payload["configuration"] = "hostname core-02 192.168.4.14"
            return httpx.Response(200, json=payload)
        return fallback.handle_request(request)

    client = CmlRealizationAuthority(
        "https://cml.example",
        "-----BEGIN CERTIFICATE-----\ninvalid-for-mock\n-----END CERTIFICATE-----",
        "private-user",
        "private-password",
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(ObservabilityRealizationError, match="Day-0 identity"):
        admit(client)
    client.close()


@pytest.mark.parametrize(
    "kwargs,match",
    [
        ({"staging": True}, "staging"),
        ({"legacy_running": True}, "legacy"),
        ({"booted": False}, "node admission"),
        ({"foreign_conflict": True}, "address ownership"),
    ],
)
def test_staging_legacy_and_unbooted_ambiguity_fail_closed(kwargs, match) -> None:
    client = authority(**kwargs)
    with pytest.raises(ObservabilityRealizationError, match=match):
        admit(client)
    client.close()


def test_wrong_node_identity_fails_closed() -> None:
    client = authority()
    with pytest.raises(ObservabilityRealizationError, match="node identity"):
        client.admit(
            LAB,
            {
                "netbox:dcim.device:1": "55555555-5555-5555-5555-555555555555",
                "netbox:dcim.device:2": JUNOS,
            },
        )
    client.close()


def test_expired_or_tampered_admission_rejected(tmp_path: Path) -> None:
    now = datetime(2026, 8, 28, tzinfo=UTC)
    client = authority()
    record = admit(client, now)
    client.close()
    root = tmp_path / "external" / "observability"
    path = publish_admission(root, record)
    with pytest.raises(ObservabilityRealizationError, match="expired"):
        read_admission(root, now=now + timedelta(minutes=16))
    payload = json.loads(path.read_text())
    payload["lab_id"] = "99999999-9999-9999-9999-999999999999"
    path.write_text(json.dumps(payload))
    path.chmod(0o600)
    with pytest.raises(ObservabilityRealizationError, match="rejected"):
        read_admission(root, now=now)


def test_retirement_removes_only_realization_authority(tmp_path: Path) -> None:
    now = datetime(2026, 8, 28, tzinfo=UTC)
    client = authority()
    record = admit(client, now)
    client.close()
    root = tmp_path / "external" / "observability"
    publish_admission(root, record)
    retire_admission(root)
    assert not (root / "operator/realization.json").exists()


def test_transport_and_errors_do_not_expose_credentials() -> None:
    with pytest.raises(ObservabilityRealizationError) as caught:
        CmlRealizationAuthority(
            "http://cml.example", "cert", "private-user", "private-password"
        )
    assert "private" not in str(caught.value)
