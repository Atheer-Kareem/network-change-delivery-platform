from __future__ import annotations

import fcntl
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from network_change_delivery.oxidized_controller import (
    CollectionOutcome,
    OxidizedControlError,
    OxidizedController,
    read_collection_ready,
    validate_loopback_api_url,
)
from network_change_delivery.oxidized_service import publish_readiness

CONTAINER = "a" * 64
TRUST_DIGEST = "b" * 64


@pytest.fixture(autouse=True)
def accepted_host_trust(monkeypatch: pytest.MonkeyPatch) -> None:
    def trust(_path: Path) -> SimpleNamespace:
        return SimpleNamespace(known_hosts_sha256=TRUST_DIGEST)

    monkeypatch.setattr(
        "network_change_delivery.oxidized_service.validate_host_trust", trust
    )
    monkeypatch.setattr(
        "network_change_delivery.oxidized_controller.validate_host_trust", trust
    )


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1:8888",
        "http://localhost:8888",
        "http://0.0.0.0:8888",
        "http://192.0.2.1:8888",
        "http://127.0.0.1:8888/path",
    ],
)
def test_only_exact_loopback_api_is_accepted(url: str) -> None:
    with pytest.raises(OxidizedControlError, match="endpoint rejected"):
        validate_loopback_api_url(url)
    assert validate_loopback_api_url("http://127.0.0.1:8888") == url.replace(
        url, "http://127.0.0.1:8888"
    )


def test_readiness_missing_stale_wrong_container_and_wrong_nodes_fail(
    tmp_path: Path,
) -> None:
    path = tmp_path / "ready.json"
    now = datetime.now(UTC)
    with pytest.raises(OxidizedControlError):
        read_collection_ready(path, CONTAINER, now=now)
    path.write_text(
        json.dumps(
            {
                "schema_version": "2",
                "refreshed_at": (now - timedelta(minutes=20)).isoformat(),
                "expires_at": (now - timedelta(minutes=5)).isoformat(),
                "nodes": ["netbox-device-1", "netbox-device-2"],
                "container_id": CONTAINER,
                "service_contract": "10C-6",
                "host_trust_sha256": TRUST_DIGEST,
            }
        )
    )
    path.chmod(0o600)
    with pytest.raises(OxidizedControlError):
        read_collection_ready(path, CONTAINER, now=now)
    publish_readiness(path, CONTAINER, now=now)
    with pytest.raises(OxidizedControlError):
        read_collection_ready(path, "b" * 64, now=now)


def nodes(last1=None):
    return [
        {
            "name": "netbox-device-1",
            "group": "managed",
            "status": "never" if last1 is None else last1["status"],
            "last": last1,
        },
        {
            "name": "netbox-device-2",
            "group": "managed",
            "status": "never",
            "last": None,
        },
    ]


def test_http_200_alone_never_proves_completion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = tmp_path / "runtime"
    runtime.mkdir(mode=0o700)
    ready = runtime / "ready.json"
    publish_readiness(ready, CONTAINER)
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.method == "PUT":
            return httpx.Response(200, json=["ok"])
        return httpx.Response(200, json=nodes())

    ticks = iter([0.0, 0.0, 2.0])
    monkeypatch.setattr(
        "network_change_delivery.oxidized_controller.time.monotonic",
        lambda: next(ticks),
    )
    monkeypatch.setattr(
        "network_change_delivery.oxidized_controller.time.sleep", lambda _value: None
    )
    controller = OxidizedController(
        "http://127.0.0.1:8888",
        ready,
        tmp_path / "locks",
        CONTAINER,
        transport=httpx.MockTransport(handler),
    )
    result = controller.collect("netbox-device-1", deadline_seconds=1)
    assert result.outcome is CollectionOutcome.COLLECTION_TIMED_OUT
    assert calls == [
        ("GET", "/nodes.json"),
        ("PUT", "/node/next/netbox-device-1.json"),
        ("GET", "/nodes.json"),
    ]


def test_new_completed_job_is_accepted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = tmp_path / "runtime"
    runtime.mkdir(mode=0o700)
    ready = runtime / "ready.json"
    publish_readiness(ready, CONTAINER)
    requested = datetime.now(UTC) + timedelta(seconds=1)
    responses = iter(
        [
            nodes(),
            nodes(None),
            nodes(
                {
                    "start": requested.isoformat(),
                    "end": (requested + timedelta(seconds=1)).isoformat(),
                    "status": "success",
                }
            ),
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json=["ok"] if request.method == "PUT" else next(responses)
        )

    monkeypatch.setattr(
        "network_change_delivery.oxidized_controller.time.sleep", lambda _value: None
    )
    controller = OxidizedController(
        "http://127.0.0.1:8888",
        ready,
        tmp_path / "locks",
        CONTAINER,
        transport=httpx.MockTransport(handler),
    )
    assert (
        controller.collect("netbox-device-1", deadline_seconds=10).outcome
        is CollectionOutcome.SUCCEEDED
    )


def test_exact_oxidized_web_utc_timestamp_is_accepted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = tmp_path / "runtime"
    runtime.mkdir(mode=0o700)
    ready = runtime / "ready.json"
    publish_readiness(ready, CONTAINER)
    started = datetime.now(UTC) + timedelta(seconds=1)
    upstream = {
        "start": started.strftime("%Y-%m-%d %H:%M:%S UTC"),
        "end": (started + timedelta(seconds=1)).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "status": "success",
    }
    responses = iter([nodes(), nodes(upstream)])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json=["ok"] if request.method == "PUT" else next(responses)
        )

    monkeypatch.setattr(
        "network_change_delivery.oxidized_controller.time.sleep", lambda _value: None
    )
    result = OxidizedController(
        "http://127.0.0.1:8888",
        ready,
        tmp_path / "locks",
        CONTAINER,
        transport=httpx.MockTransport(handler),
    ).collect("netbox-device-1", deadline_seconds=10)
    assert result.outcome is CollectionOutcome.SUCCEEDED
    assert result.upstream_started_at == started.replace(microsecond=0)


def test_whole_second_upstream_timestamp_is_accepted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = tmp_path / "runtime"
    runtime.mkdir(mode=0o700)
    ready = runtime / "ready.json"
    publish_readiness(ready, CONTAINER)
    started = datetime.now(UTC).replace(microsecond=0)
    responses = iter(
        [
            nodes(),
            nodes(
                {
                    "start": started.isoformat(),
                    "end": (started + timedelta(seconds=1)).isoformat(),
                    "status": "success",
                }
            ),
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json=["ok"] if request.method == "PUT" else next(responses)
        )

    monkeypatch.setattr(
        "network_change_delivery.oxidized_controller.time.sleep", lambda _value: None
    )
    result = OxidizedController(
        "http://127.0.0.1:8888",
        ready,
        tmp_path / "locks",
        CONTAINER,
        transport=httpx.MockTransport(handler),
    ).collect("netbox-device-1", deadline_seconds=10)
    assert result.outcome is CollectionOutcome.SUCCEEDED


@pytest.mark.parametrize("status", ["no_connection", "timelimit", "fail"])
def test_terminal_failure_is_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, status: str
) -> None:
    runtime = tmp_path / "runtime"
    runtime.mkdir(mode=0o700)
    ready = runtime / "ready.json"
    publish_readiness(ready, CONTAINER)
    started = datetime.now(UTC) + timedelta(milliseconds=1)
    responses = iter(
        [
            nodes(),
            nodes(
                {
                    "start": started.isoformat(),
                    "end": (started + timedelta(seconds=1)).isoformat(),
                    "status": status,
                }
            ),
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json=["ok"] if request.method == "PUT" else next(responses)
        )

    monkeypatch.setattr(
        "network_change_delivery.oxidized_controller.time.sleep", lambda _value: None
    )
    result = OxidizedController(
        "http://127.0.0.1:8888",
        ready,
        tmp_path / "locks",
        CONTAINER,
        transport=httpx.MockTransport(handler),
    ).collect("netbox-device-1", deadline_seconds=10)
    assert result.outcome is CollectionOutcome.COLLECTION_FAILED
    assert result.upstream_status == status


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(302, headers={"Location": "http://127.0.0.1:9999"}),
        httpx.Response(200, content=b"not-json"),
        httpx.Response(200, content=b"[" + b" " * 65536 + b"]"),
        httpx.Response(200, json=[*nodes(), {"name": "netbox-device-3"}]),
    ],
)
def test_api_redirect_malformed_oversized_and_extra_node_fail_closed(
    tmp_path: Path, response: httpx.Response
) -> None:
    runtime = tmp_path / "runtime"
    runtime.mkdir(mode=0o700)
    ready = runtime / "ready.json"
    publish_readiness(ready, CONTAINER)
    controller = OxidizedController(
        "http://127.0.0.1:8888",
        ready,
        tmp_path / "locks",
        CONTAINER,
        transport=httpx.MockTransport(lambda _request: response),
    )
    with pytest.raises(OxidizedControlError) as caught:
        controller.collect("netbox-device-1")
    assert "private" not in str(caught.value)


def test_existing_local_lock_returns_concurrent_without_api(
    tmp_path: Path,
) -> None:
    lock_root = tmp_path / "locks"
    lock_root.mkdir(mode=0o700)
    lock_path = lock_root / "netbox-device-1.lock"
    descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        controller = OxidizedController(
            "http://127.0.0.1:8888",
            tmp_path / "missing",
            lock_root,
            CONTAINER,
            transport=httpx.MockTransport(
                lambda _request: pytest.fail("API must not be called")
            ),
        )
        assert (
            controller.collect("netbox-device-1").outcome
            is CollectionOutcome.CONCURRENT_COLLECTION
        )
    finally:
        os.close(descriptor)


@pytest.mark.parametrize("node", ["netbox-device-3", "../x", "anything"])
def test_arbitrary_nodes_rejected(tmp_path: Path, node: str) -> None:
    controller = OxidizedController(
        "http://127.0.0.1:8888",
        tmp_path / "ready",
        tmp_path / "locks",
        CONTAINER,
        transport=httpx.MockTransport(lambda _: httpx.Response(500)),
    )
    with pytest.raises(OxidizedControlError, match="request rejected"):
        controller.collect(node)
