"""Independent GET-only CML admission for profiled staging."""

from __future__ import annotations

import socket
import subprocess
from typing import cast

import httpx
import pytest

import network_change_delivery.profiled_staging_cml as staging_cml
from network_change_delivery.architecture_contracts import (
    CML_REALIZATION_PROFILE_CATALOG,
)
from network_change_delivery.profiled_staging import ProfiledStagingError
from network_change_delivery.profiled_staging_cml import (
    _LINK_SLOTS,
    ProfiledStagingCmlReader,
    admit_created_realization,
    admit_no_staging_collision,
)

LAB_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


class Reader:
    def __init__(self, *, title: str = "unrelated", bad: str | None = None) -> None:
        self.title = title
        self.bad = bad
        self.node_ids = {
            "system_bridge": "node-system",
            "management_switch": "node-switch",
            "core_02": "node-core",
            "edge_junos_01": "node-junos",
            "transit_ios_01": "node-transit",
            "access_sw_01": "node-access",
        }
        self.link_ids = {key: f"link-{index}" for index, key in enumerate(_LINK_SLOTS)}
        self.slots = {
            key: {slot: f"if-{key}-{slot}" for slot in range(5)}
            for key in self.node_ids
        }

    def lab_ids(self):
        return (LAB_ID,) if self.title else ()

    def lab(self, _lab_id, *, allow_missing: bool = False):
        del allow_missing
        return {"lab_title": self.title}

    def ids(self, _lab_id, kind):
        values = self.node_ids.values() if kind == "nodes" else self.link_ids.values()
        result = tuple(values)
        return result[:-1] if self.bad == f"{kind}_count" else result

    def item(self, _lab_id, kind, identity):
        if kind == "nodes":
            key = next(key for key, value in self.node_ids.items() if value == identity)
            if key in {"system_bridge", "management_switch"}:
                return {
                    "label": key.replace("_", "-"),
                    "node_definition": (
                        "external_connector"
                        if key == "system_bridge"
                        else "unmanaged_switch"
                    ),
                }
            from test_profiled_realization import inventory_devices

            device = next(
                item
                for item in inventory_devices()
                if str(item.logical_name).replace("-", "_") == key
            )
            profile = CML_REALIZATION_PROFILE_CATALOG[device.cml_realization_profile_id]
            return {
                "label": "wrong" if self.bad == "profile" else str(device.logical_name),
                "node_definition": (
                    "wrong" if self.bad == "definition" else profile.node_definition
                ),
                "image_definition": (
                    "wrong" if self.bad == "image" else profile.image_definition
                ),
            }
        key = next(key for key, value in self.link_ids.items() if value == identity)
        ((left, left_slot), (right, right_slot)) = _LINK_SLOTS[key]
        return {
            "interface_a": self.slots[left][left_slot],
            "interface_b": (
                "wrong-interface"
                if self.bad == "link"
                else self.slots[right][right_slot]
            ),
        }

    def configuration(self, _lab_id, node_id):
        key = next(key for key, value in self.node_ids.items() if value == node_id)
        from test_profiled_realization import inventory_devices

        device = next(
            item
            for item in inventory_devices()
            if str(item.logical_name).replace("-", "_") == key
        )
        address = device.management_endpoints.staging.binding.l3_endpoint.address.ip
        marker = {
            "core_02": "interface GigabitEthernet1",
            "edge_junos_01": "fxp0",
            "transit_ios_01": "interface GigabitEthernet0/0",
            "access_sw_01": "interface GigabitEthernet0/0\n no switchport",
        }[key]
        forbidden = "\nrouter ospf 1" if self.bad == "day0" else ""
        return (
            f"hostname {device.expected_hostname}\n{marker}\n"
            f" address {address}{forbidden}\n"
        )

    def interfaces(self, _lab_id, node_id):
        key = next(key for key, value in self.node_ids.items() if value == node_id)
        return self.slots[key]


def outputs(reader: Reader):
    return {
        "lab_id": LAB_ID,
        "lab_title": "NCDP Staging run-001",
        "node_ids": reader.node_ids,
        "link_ids": reader.link_ids,
    }


def _admit_fixture_addresses(monkeypatch, devices) -> None:
    monkeypatch.setattr(
        staging_cml,
        "STAGING_MANAGEMENT_ADDRESSES",
        {
            str(device.logical_name): str(
                device.management_endpoints.staging.binding.l3_endpoint.address.ip
            )
            for device in devices
        },
    )


def test_precreate_rejects_existing_staging_lab(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from test_profiled_realization import inventory_devices

    devices = inventory_devices()
    _admit_fixture_addresses(monkeypatch, devices)
    monkeypatch.setattr(
        staging_cml,
        "_icmp_address_is_active",
        lambda *_args, **_kwargs: pytest.fail("address probe must not run"),
    )
    with pytest.raises(ProfiledStagingError, match="existing NCDP Staging"):
        admit_no_staging_collision(
            cast(object, Reader(title="NCDP Staging existing")), devices
        )


def test_precreate_rejects_icmp_responsive_endpoint_with_closed_tcp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from test_profiled_realization import inventory_devices

    devices = inventory_devices()
    _admit_fixture_addresses(monkeypatch, devices)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess((), 0),
    )
    monkeypatch.setattr(
        socket,
        "create_connection",
        lambda *_args, **_kwargs: pytest.fail("TCP must not run after ICMP success"),
    )
    with pytest.raises(ProfiledStagingError, match="endpoint is occupied"):
        admit_no_staging_collision(cast(object, Reader(title="")), devices)


def test_precreate_rejects_tcp_responsive_staging_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from test_profiled_realization import inventory_devices

    devices = inventory_devices()
    _admit_fixture_addresses(monkeypatch, devices)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess((), 1),
    )

    class Connection:
        def close(self):
            return None

    monkeypatch.setattr(
        socket, "create_connection", lambda *_args, **_kwargs: Connection()
    )
    with pytest.raises(ProfiledStagingError, match="endpoint is occupied"):
        admit_no_staging_collision(cast(object, Reader(title="")), devices)


def test_precreate_accepts_fully_inactive_staging_endpoints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from test_profiled_realization import inventory_devices

    devices = inventory_devices()
    _admit_fixture_addresses(monkeypatch, devices)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess((), 1),
    )

    def inactive(*_args, **_kwargs):
        raise ConnectionRefusedError

    monkeypatch.setattr(socket, "create_connection", inactive)
    admit_no_staging_collision(cast(object, Reader(title="")), devices)


def test_precreate_does_not_treat_icmp_probe_failure_as_occupancy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from test_profiled_realization import inventory_devices

    devices = inventory_devices()
    _admit_fixture_addresses(monkeypatch, devices)

    def timed_out(*_args, **_kwargs):
        raise subprocess.TimeoutExpired("ping", 0.5)

    def inactive(*_args, **_kwargs):
        raise ConnectionRefusedError

    monkeypatch.setattr(subprocess, "run", timed_out)
    monkeypatch.setattr(socket, "create_connection", inactive)
    admit_no_staging_collision(cast(object, Reader(title="")), devices)


def test_precreate_rejects_noncanonical_staging_endpoint() -> None:
    from test_profiled_realization import inventory_devices

    with pytest.raises(ProfiledStagingError, match="endpoint rejected"):
        admit_no_staging_collision(cast(object, Reader(title="")), inventory_devices())


@pytest.mark.parametrize("first_status", [404, 405])
def test_configuration_tries_alternative_after_unsupported_route(
    first_status: int,
) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path.endswith("/configuration"):
            return httpx.Response(first_status, json={"detail": "unsupported"})
        return httpx.Response(200, json={"configuration": "hostname staged\n"})

    client = httpx.Client(
        base_url="https://cml.invalid",
        transport=httpx.MockTransport(handler),
        trust_env=False,
    )
    reader = ProfiledStagingCmlReader(client)
    assert reader.configuration(LAB_ID, "node-core") == "hostname staged\n"
    assert calls == [
        f"/api/v0/labs/{LAB_ID}/nodes/node-core/configuration",
        f"/api/v0/labs/{LAB_ID}/nodes/node-core/configurations",
    ]


def test_configuration_uses_node_fallback_when_routes_are_unsupported() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith(("/configuration", "/configurations")):
            return httpx.Response(405, json={"detail": "unsupported"})
        return httpx.Response(
            200,
            json={"configuration": [{"content": "hostname fallback\n"}]},
        )

    client = httpx.Client(
        base_url="https://cml.invalid",
        transport=httpx.MockTransport(handler),
        trust_env=False,
    )
    assert (
        ProfiledStagingCmlReader(client).configuration(LAB_ID, "node-core")
        == "hostname fallback\n"
    )


def test_configuration_rejects_unexpected_route_status() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"detail": "failed"})

    client = httpx.Client(
        base_url="https://cml.invalid",
        transport=httpx.MockTransport(handler),
        trust_env=False,
    )
    with pytest.raises(ProfiledStagingError, match="observation rejected"):
        ProfiledStagingCmlReader(client).configuration(LAB_ID, "node-core")


def test_ordinary_get_does_not_tolerate_method_not_allowed() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(405, json={"detail": "unsupported"})

    client = httpx.Client(
        base_url="https://cml.invalid",
        transport=httpx.MockTransport(handler),
        trust_env=False,
    )
    with pytest.raises(ProfiledStagingError, match="observation rejected"):
        ProfiledStagingCmlReader(client).lab_ids()


@pytest.mark.parametrize("valid_fallback", [True, False])
def test_configuration_malformed_success_requires_valid_fallback(
    valid_fallback: bool,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith(("/configuration", "/configurations")):
            return httpx.Response(200, content=b"not-json")
        if valid_fallback:
            return httpx.Response(200, json={"configuration": "hostname fallback\n"})
        return httpx.Response(200, json={"configuration": [{"content": 7}]})

    client = httpx.Client(
        base_url="https://cml.invalid",
        transport=httpx.MockTransport(handler),
        trust_env=False,
    )
    reader = ProfiledStagingCmlReader(client)
    if valid_fallback:
        assert reader.configuration(LAB_ID, "node-core") == "hostname fallback\n"
    else:
        with pytest.raises(ProfiledStagingError, match="stored Day-0 unavailable"):
            reader.configuration(LAB_ID, "node-core")


def test_created_realization_is_observed_and_run_specific() -> None:
    from test_profiled_realization import inventory_devices

    reader = Reader(title="NCDP Staging run-001")
    result = admit_created_realization(
        cast(object, reader), "run-001", outputs(reader), inventory_devices()
    )
    assert len(result.node_ids) == 6
    assert len(result.link_ids) == 9
    assert result.topology_evidence.digest.startswith("sha256:")
    assert set(result.cml_anchors) == {
        "core-02",
        "edge-junos-01",
        "transit-ios-01",
        "access-sw-01",
    }


@pytest.mark.parametrize(
    "bad",
    [
        "nodes_count",
        "links_count",
        "profile",
        "definition",
        "image",
        "link",
        "day0",
    ],
)
def test_created_realization_rejects_observed_mismatch(bad: str) -> None:
    from test_profiled_realization import inventory_devices

    reader = Reader(title="NCDP Staging run-001", bad=bad)
    with pytest.raises(ProfiledStagingError):
        admit_created_realization(
            cast(object, reader), "run-001", outputs(reader), inventory_devices()
        )
