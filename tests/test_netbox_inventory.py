"""NetBox inventory adapter tests at the real HTTP boundary."""

from __future__ import annotations

import json

import httpx
import pytest

import network_change_delivery.inventory as inventory_module
from network_change_delivery.inventory import InventoryError, NetBoxInventoryProvider

TOKEN = "opaque-test-token"


def test_http_client_disables_environment_proxy_trust(monkeypatch) -> None:
    options: dict[str, object] = {}

    def client_spy(**kwargs: object) -> object:
        options.update(kwargs)
        return object()

    monkeypatch.setattr(inventory_module.httpx, "Client", client_spy)
    NetBoxInventoryProvider("https://netbox.example", TOKEN)
    assert options["trust_env"] is False
    assert options["verify"] is True
    assert options["follow_redirects"] is False


def device(**changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "id": 42,
        "name": "core-02",
        "status": {"value": "active"},
        "tags": [{"slug": "ncdp-managed"}],
        "platform": {"slug": "cisco-ios-xe"},
        "primary_ip4": {"address": "192.168.4.14/24"},
    }
    value.update(changes)
    return value


def page(results: list[object], *, count: int | None = None, next_: object = None):
    return {
        "count": len(results) if count is None else count,
        "next": next_,
        "results": results,
    }


def provider(
    device_payload: dict[str, object] | None = None,
    interface_payload: dict[str, object] | None = None,
    *,
    requested_interface_payload: dict[str, object] | None = None,
    handler=None,
    url: str = "https://netbox.example",
) -> NetBoxInventoryProvider:
    if handler is None:

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/dcim/devices/":
                return httpx.Response(200, json=device_payload or page([device()]))
            if "name" in request.url.params:
                return httpx.Response(
                    200,
                    json=requested_interface_payload
                    or page([{"id": 100, "name": "GigabitEthernet2"}]),
                )
            return httpx.Response(
                200,
                json=interface_payload or page([{"name": " GigabitEthernet1 "}]),
            )

    return NetBoxInventoryProvider(url, TOKEN, transport=httpx.MockTransport(handler))


def test_exact_active_managed_device_resolves_with_provenance() -> None:
    resolved = provider().resolve("core-02")
    assert resolved.host == "192.168.4.14"
    assert resolved.port == 22
    assert resolved.platform == "cisco_iosxe"
    assert resolved.expected_hostname == "core-02"
    assert resolved.inventory_source == "netbox"
    assert resolved.inventory_object_id == "netbox:dcim.device:42"
    assert resolved.inventory_interface_object_id is None
    assert resolved.protected_interfaces == ("GigabitEthernet1",)


def test_exact_requested_interface_resolves_with_stable_identity() -> None:
    resolved = provider().resolve("core-02", "GigabitEthernet2")
    assert resolved.inventory_interface_object_id == "netbox:dcim.interface:100"
    assert resolved.protected_interfaces == ("GigabitEthernet1",)


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (page([]), "interface not found"),
        (
            page(
                [
                    {"id": 100, "name": "GigabitEthernet2"},
                    {"id": 101, "name": "GigabitEthernet2"},
                ],
                count=2,
            ),
            "interface is ambiguous",
        ),
        (page([{"id": "bad", "name": "GigabitEthernet2"}]), "identity is invalid"),
        (page([{"name": "GigabitEthernet2"}]), "identity is invalid"),
    ],
)
def test_requested_interface_identity_fails_closed(
    payload: dict[str, object], message: str
) -> None:
    with pytest.raises(InventoryError, match=message):
        provider(requested_interface_payload=payload).resolve(
            "core-02", "GigabitEthernet2"
        )


def test_requested_protected_interface_remains_protected() -> None:
    protected = page([{"name": "GigabitEthernet2"}])
    resolved = provider(interface_payload=protected).resolve(
        "core-02", "GigabitEthernet2"
    )
    assert resolved.protected_interfaces == ("GigabitEthernet2",)


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (page([]), "target not found"),
        (page([device(), device(id=43)], count=2), "ambiguous"),
        (page([device(status={"value": "offline"})]), "inactive"),
        (page([device(tags=[])]), "missing ncdp-managed"),
        (page([device(platform={"slug": "junos"})]), "unsupported or missing"),
        (page([device(platform=None)]), "unsupported or missing"),
        (page([device(primary_ip4=None)]), "missing or invalid primary"),
        (page([device(primary_ip4={"address": "bad"})]), "missing or invalid primary"),
    ],
)
def test_ineligible_device_fails_closed(
    payload: dict[str, object], message: str
) -> None:
    with pytest.raises(InventoryError, match=message):
        provider(payload).resolve("core-02")


def test_protected_interfaces_are_normalized_deduplicated_and_sorted() -> None:
    interfaces = page(
        [
            {"name": " GigabitEthernet2 "},
            {"name": "GigabitEthernet1"},
            {"name": "GigabitEthernet2"},
        ]
    )
    assert provider(interface_payload=interfaces).resolve(
        "core-02"
    ).protected_interfaces == ("GigabitEthernet1", "GigabitEthernet2")


@pytest.mark.parametrize(
    "payload",
    [page([{"name": "GigabitEthernet1"}], count=2), page([], next_="next")],
)
def test_protection_pagination_cannot_be_truncated(payload: dict[str, object]) -> None:
    with pytest.raises(InventoryError, match="protection data is incomplete"):
        provider(interface_payload=payload).resolve("core-02")


def test_malformed_protection_shape_is_incomplete() -> None:
    with pytest.raises(InventoryError, match="protection data is incomplete"):
        provider(interface_payload={"count": 1, "results": "bad"}).resolve("core-02")


def test_v2_bearer_auth_and_query_parameter_apis_are_used() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if "devices" in request.url.path:
            payload = page([device()])
        elif "name" in request.url.params:
            payload = page([{"id": 100, "name": "GigabitEthernet2"}])
        else:
            payload = page([])
        return httpx.Response(200, json=payload)

    provider(handler=handler).resolve("core-02", "GigabitEthernet2")
    assert all(
        request.headers["Authorization"] == f"Bearer {TOKEN}" for request in requests
    )
    assert requests[0].url.params["name"] == "core-02"
    assert requests[1].url.params["device_id"] == "42"
    assert requests[1].url.params["name"] == "GigabitEthernet2"
    assert requests[1].url.params["limit"] == "2"
    assert requests[2].url.params["device_id"] == "42"
    assert requests[2].url.params["tag"] == "ncdp-protected"


@pytest.mark.parametrize("status", [401, 403])
def test_authentication_errors_are_bounded_and_secret_free(status: int) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, content=TOKEN.encode())

    with pytest.raises(InventoryError) as caught:
        provider(handler=handler).resolve("core-02")
    assert str(caught.value) == "NetBox authentication or authorization failed"
    assert TOKEN not in str(caught.value)
    assert TOKEN not in repr(caught.value)


@pytest.mark.parametrize("error", [httpx.ConnectError(TOKEN), httpx.ReadTimeout(TOKEN)])
def test_unavailable_and_timeout_errors_are_bounded(error: Exception) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if isinstance(error, httpx.RequestError):
            error.request = request
        raise error

    with pytest.raises(InventoryError) as caught:
        provider(handler=handler).resolve("core-02")
    assert str(caught.value) == "NetBox unavailable or timed out"
    assert TOKEN not in repr(caught.value)


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, content=b"not-json"),
        httpx.Response(200, json=[]),
        httpx.Response(200, json={"count": 1, "results": "bad"}),
    ],
)
def test_malformed_json_or_shape_is_bounded(response: httpx.Response) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return response

    with pytest.raises(InventoryError, match="invalid JSON or schema"):
        provider(handler=handler).resolve("core-02")


def test_redirects_are_not_followed_with_authentication() -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(302, headers={"Location": "https://other.example/"})

    with pytest.raises(InventoryError, match="unexpected HTTP status 302"):
        provider(handler=handler).resolve("core-02")
    assert calls == 1


@pytest.mark.parametrize(
    "url",
    [
        "http://netbox.example",
        "ftp://localhost",
        "https://user:pass@localhost",
        "https://netbox.example/netbox",
        "http://localhost:8000/netbox",
    ],
)
def test_unsafe_netbox_url_is_rejected(url: str) -> None:
    with pytest.raises(InventoryError, match="URL rejected"):
        provider(url=url)


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8000",
        "http://localhost",
        "http://[::1]:8000",
        "https://netbox.example",
    ],
)
def test_loopback_http_and_verified_https_are_accepted(url: str) -> None:
    assert provider(url=url).resolve("core-02").name == "core-02"


def test_configuration_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NCDP_NETBOX_URL", raising=False)
    monkeypatch.delenv("NCDP_NETBOX_TOKEN", raising=False)
    with pytest.raises(InventoryError, match="configuration missing"):
        NetBoxInventoryProvider()


def test_unexpected_status_does_not_include_response_body() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, content=json.dumps({"token": TOKEN}).encode())

    with pytest.raises(InventoryError) as caught:
        provider(handler=handler).resolve("core-02")
    assert str(caught.value) == "NetBox returned unexpected HTTP status 500"
    assert TOKEN not in repr(caught.value)
