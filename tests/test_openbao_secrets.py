"""OpenBao AppRole and KV-v2 tests at the real HTTP boundary."""

from __future__ import annotations

import json

import httpx
import pytest

import network_change_delivery.secrets as secrets_module
from network_change_delivery.models import InventoryDevice
from network_change_delivery.secrets import (
    ENVIRONMENT_REFERENCE,
    EnvironmentSecretProvider,
    OpenBaoSecretProvider,
    SecretError,
)

ROLE_ID = "sensitive-role-id"
SECRET_ID = "sensitive-secret-id"
CLIENT_TOKEN = "sensitive-client-token"
USERNAME = "sensitive-username"
PASSWORD = "sensitive-password"


def test_http_client_disables_environment_proxy_trust(monkeypatch) -> None:
    options: dict[str, object] = {}

    def client_spy(**kwargs: object) -> object:
        options.update(kwargs)
        return object()

    monkeypatch.setattr(secrets_module.httpx, "Client", client_spy)
    OpenBaoSecretProvider("https://openbao.example", ROLE_ID, SECRET_ID)
    assert options["trust_env"] is False
    assert options["verify"] is True
    assert options["follow_redirects"] is False


def netbox_device(**changes: object) -> InventoryDevice:
    values: dict[str, object] = {
        "name": "core-02",
        "host": "192.168.4.14",
        "platform": "cisco_iosxe",
        "expected_hostname": "core-02",
        "inventory_source": "netbox",
        "inventory_object_id": "netbox:dcim.device:1",
        "inventory_interface_object_id": "netbox:dcim.interface:2",
    }
    values.update(changes)
    return InventoryDevice.model_validate(values)


def login_payload(**auth_changes: object) -> dict[str, object]:
    auth: dict[str, object] = {
        "client_token": CLIENT_TOKEN,
        "lease_duration": 300,
    }
    auth.update(auth_changes)
    return {"auth": auth}


def secret_payload(**changes: object) -> dict[str, object]:
    credentials: dict[str, object] = {"username": USERNAME, "password": PASSWORD}
    credentials.update(changes)
    return {"data": {"data": credentials, "metadata": {"version": 1}}}


def provider(handler=None, *, url: str = "https://openbao.example"):
    if handler is None:

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/v1/auth/approle/login":
                return httpx.Response(200, json=login_payload())
            return httpx.Response(200, json=secret_payload())

    return OpenBaoSecretProvider(
        url,
        ROLE_ID,
        SECRET_ID,
        transport=httpx.MockTransport(handler),
    )


def test_approle_login_then_exact_kv_v2_get() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/v1/auth/approle/login":
            return httpx.Response(200, json=login_payload())
        return httpx.Response(200, json=secret_payload())

    credentials = provider(handler).load(netbox_device())
    assert credentials.username == USERNAME
    assert credentials.password == PASSWORD
    assert [request.method for request in requests] == ["POST", "GET"]
    assert requests[0].url.path == "/v1/auth/approle/login"
    assert requests[0].url.query == b""
    assert json.loads(requests[0].content) == {
        "role_id": ROLE_ID,
        "secret_id": SECRET_ID,
    }
    assert "X-Vault-Token" not in requests[0].headers
    assert requests[1].url.path == "/v1/ncdp/data/devices/1/ssh"
    assert requests[1].url.query == b""
    assert requests[1].headers["X-Vault-Token"] == CLIENT_TOKEN


def test_each_load_performs_a_fresh_login_without_token_caching() -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path == "/v1/auth/approle/login":
            return httpx.Response(200, json=login_payload())
        return httpx.Response(200, json=secret_payload())

    openbao = provider(handler)
    openbao.load(netbox_device())
    openbao.load(netbox_device())
    assert paths == [
        "/v1/auth/approle/login",
        "/v1/ncdp/data/devices/1/ssh",
        "/v1/auth/approle/login",
        "/v1/ncdp/data/devices/1/ssh",
    ]


def test_reference_uses_only_stable_netbox_device_id() -> None:
    first = provider().reference(netbox_device())
    changed_endpoint = provider().reference(
        netbox_device(host="198.51.100.9", expected_hostname="renamed")
    )
    assert first.source == "openbao"
    assert first.reference == "openbao:kv-v2:ncdp/devices/1/ssh"
    assert changed_endpoint == first


@pytest.mark.parametrize(
    "changes",
    [
        {"inventory_source": "local_yaml", "inventory_object_id": None},
        {"inventory_object_id": None},
        {"inventory_object_id": "netbox:dcim.device:0"},
        {"inventory_object_id": "netbox:dcim.device:-1"},
        {"inventory_object_id": "netbox:dcim.device:1/ssh"},
        {"inventory_object_id": "core-02"},
    ],
)
def test_non_netbox_or_malformed_identity_is_rejected(
    changes: dict[str, object],
) -> None:
    with pytest.raises(SecretError, match="requires NetBox-backed"):
        provider().reference(netbox_device(**changes))


@pytest.mark.parametrize("missing", ["url", "role_id", "secret_id"])
def test_configuration_is_required(missing: str) -> None:
    values = {
        "url": "https://openbao.example",
        "role_id": ROLE_ID,
        "secret_id": SECRET_ID,
    }
    values[missing] = ""
    with pytest.raises(SecretError, match="configuration missing"):
        OpenBaoSecretProvider(**values)


@pytest.mark.parametrize(
    "url",
    [
        "http://openbao.example",
        "ftp://localhost",
        "https://user:pass@openbao.example",
        "https://openbao.example/vault",
        "http://localhost:8200/vault",
        "https://openbao.example?query=value",
        "https://openbao.example#fragment",
    ],
)
def test_unsafe_url_is_rejected(url: str) -> None:
    with pytest.raises(SecretError, match="URL rejected"):
        provider(url=url)


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8200",
        "http://localhost:8200/",
        "http://[::1]:8200",
        "https://openbao.example",
    ],
)
def test_loopback_http_and_https_are_accepted(url: str) -> None:
    assert provider(url=url).reference(netbox_device()).source == "openbao"


def test_redirect_is_not_followed() -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(302, headers={"Location": "https://other.example"})

    with pytest.raises(SecretError, match="unexpected HTTP status 302"):
        provider(handler).load(netbox_device())
    assert calls == 1


@pytest.mark.parametrize("error_type", [httpx.ConnectError, httpx.ReadTimeout])
def test_transport_failures_are_bounded(error_type) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise error_type(SECRET_ID, request=request)

    with pytest.raises(SecretError) as caught:
        provider(handler).load(netbox_device())
    assert str(caught.value) == "OpenBao unavailable or timed out"
    assert SECRET_ID not in repr(caught.value)


@pytest.mark.parametrize("status", [400, 401, 403])
def test_approle_authentication_failure_is_bounded(status: int) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, content=SECRET_ID.encode())

    with pytest.raises(SecretError) as caught:
        provider(handler).load(netbox_device())
    assert str(caught.value) == "OpenBao authentication failed"
    assert ROLE_ID not in repr(caught.value)
    assert SECRET_ID not in repr(caught.value)


@pytest.mark.parametrize(
    "payload",
    [
        b"not-json",
        [],
        {},
        {"auth": []},
    ],
)
def test_malformed_login_json_or_schema(payload: object) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        if isinstance(payload, bytes):
            return httpx.Response(200, content=payload)
        return httpx.Response(200, json=payload)

    with pytest.raises(SecretError, match="invalid JSON or schema"):
        provider(handler).load(netbox_device())


@pytest.mark.parametrize(
    "auth_changes",
    [
        {"client_token": None},
        {"client_token": ""},
        {"lease_duration": None},
        {"lease_duration": 0},
        {"lease_duration": -1},
        {"lease_duration": True},
        {"lease_duration": "300"},
        {"lease_duration": 601},
    ],
)
def test_unacceptable_token_response_fails_closed(
    auth_changes: dict[str, object],
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=login_payload(**auth_changes))

    with pytest.raises(SecretError, match="issued unacceptable token"):
        provider(handler).load(netbox_device())


@pytest.mark.parametrize(
    ("status", "message"),
    [
        (403, "secret read unauthorized"),
        (404, "secret not found"),
        (500, "unexpected HTTP status 500"),
    ],
)
def test_kv_read_failures_are_bounded(status: int, message: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/auth/approle/login":
            return httpx.Response(200, json=login_payload())
        return httpx.Response(status, content=CLIENT_TOKEN.encode())

    with pytest.raises(SecretError) as caught:
        provider(handler).load(netbox_device())
    assert message in str(caught.value)
    assert CLIENT_TOKEN not in repr(caught.value)


@pytest.mark.parametrize(
    "payload",
    [
        b"not-json",
        [],
        {},
        {"data": []},
        {"data": {"data": []}},
    ],
)
def test_malformed_kv_response(payload: object) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/auth/approle/login":
            return httpx.Response(200, json=login_payload())
        if isinstance(payload, bytes):
            return httpx.Response(200, content=payload)
        return httpx.Response(200, json=payload)

    with pytest.raises(SecretError, match="invalid JSON or schema"):
        provider(handler).load(netbox_device())


@pytest.mark.parametrize(
    "credentials",
    [
        {"password": PASSWORD},
        {"username": USERNAME},
        {"username": "", "password": PASSWORD},
        {"username": USERNAME, "password": ""},
        {"username": 7, "password": PASSWORD},
        {"username": USERNAME, "password": 7},
        {"username": USERNAME, "password": PASSWORD, "extra": "rejected"},
    ],
)
def test_invalid_credential_payload_is_bounded(
    credentials: dict[str, object],
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/auth/approle/login":
            return httpx.Response(200, json=login_payload())
        return httpx.Response(200, json={"data": {"data": credentials}})

    with pytest.raises(SecretError) as caught:
        provider(handler).load(netbox_device())
    assert str(caught.value) == "OpenBao credential payload invalid"
    for secret in (ROLE_ID, SECRET_ID, CLIENT_TOKEN, USERNAME, PASSWORD):
        assert secret not in repr(caught.value)


def test_device_credentials_repr_hides_values() -> None:
    credentials = provider().load(netbox_device())
    assert USERNAME not in repr(credentials)
    assert PASSWORD not in repr(credentials)


def test_environment_provider_remains_target_aware_and_compatible() -> None:
    environment = {
        "NCDP_DEVICE_USERNAME": USERNAME,
        "NCDP_DEVICE_PASSWORD": PASSWORD,
    }
    environment_provider = EnvironmentSecretProvider(environment)
    reference = environment_provider.reference(netbox_device())
    credentials = environment_provider.load(netbox_device())
    assert reference.source == "environment"
    assert reference.reference == ENVIRONMENT_REFERENCE
    assert credentials.username == USERNAME
    assert credentials.password == PASSWORD
