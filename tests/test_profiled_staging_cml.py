"""Independent GET-only CML admission for profiled staging."""

from __future__ import annotations

import socket
import subprocess
from typing import cast

import httpx
import pytest
from test_profiled_realization import inventory_devices

import network_change_delivery.profiled_staging_cml as staging_cml
from network_change_delivery.architecture_contracts import (
    CML_REALIZATION_PROFILE_CATALOG,
)
from network_change_delivery.profiled_staging import (
    CURRENT_STAGING_TOPOLOGY,
    ProfiledStagingAmbiguousError,
    ProfiledStagingError,
)
from network_change_delivery.profiled_staging_cml import (
    ProfiledStagingCmlProfileRecycler,
    ProfiledStagingCmlReader,
    admit_created_realization,
    admit_no_staging_collision,
    staging_link_slots,
)


@pytest.fixture(autouse=True)
def historical_iosv_recycle_profile(monkeypatch):
    """Keep recycler unit tests exercising the retained historical policy."""
    import network_change_delivery.profiled_staging_cml as staging_cml
    from network_change_delivery.architecture_contracts import (
        CML_REALIZATION_PROFILE_CATALOG,
        CmlBootPolicy,
        CmlRealizationProfileID,
    )

    catalog = dict(CML_REALIZATION_PROFILE_CATALOG)
    profile_id = CmlRealizationProfileID.IOSV_159_3_M12
    catalog[profile_id] = catalog[profile_id].model_copy(
        update={"boot_policy": CmlBootPolicy.IOSV_PERSISTENCE_RECYCLE}
    )
    monkeypatch.setattr(staging_cml, "CML_REALIZATION_PROFILE_CATALOG", catalog)


_LINK_SLOTS = staging_link_slots(inventory_devices(), CURRENT_STAGING_TOPOLOGY)

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
        self.logical_interfaces = {key: f"if-{key}-logical" for key in self.node_ids}

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
            profile = CML_REALIZATION_PROFILE_CATALOG[
                device.effective_staging_cml_realization_profile_id
            ]
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
                self.logical_interfaces[right]
                if self.bad == "logical_link"
                else (
                    "wrong-interface"
                    if self.bad == "link"
                    else self.slots[right][right_slot]
                )
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
        from network_change_delivery.profiled_staging import staging_interface_name

        interface = staging_interface_name(
            device,
            device.management_endpoints.staging.binding.l3_endpoint.interface.name,
        )
        marker = f"interface {interface}" if key != "edge_junos_01" else interface
        if key == "access_sw_01":
            marker += "\n no switchport"
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


def test_precreate_rejects_existing_staging_lab(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from test_profiled_realization import inventory_devices

    devices = inventory_devices()
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

    def timed_out(*_args, **_kwargs):
        raise subprocess.TimeoutExpired("ping", 0.5)

    def inactive(*_args, **_kwargs):
        raise ConnectionRefusedError

    monkeypatch.setattr(subprocess, "run", timed_out)
    monkeypatch.setattr(socket, "create_connection", inactive)
    admit_no_staging_collision(cast(object, Reader(title="")), devices)


def test_precreate_rejects_wrong_scope_before_endpoint_probe(monkeypatch) -> None:
    from test_profiled_realization import inventory_devices

    monkeypatch.setattr(
        staging_cml,
        "_icmp_address_is_active",
        lambda *_a, **_k: pytest.fail("no probe before scope admission"),
    )
    with pytest.raises(ValueError, match="scope"):
        admit_no_staging_collision(
            cast(object, Reader(title="")), inventory_devices()[:-1]
        )


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


def _interface_reader(slots: list[object]) -> ProfiledStagingCmlReader:
    identities = [f"interface-{index}" for index in range(len(slots))]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/interfaces"):
            return httpx.Response(200, json=identities)
        identity = request.url.path.rsplit("/", 1)[1]
        return httpx.Response(200, json={"slot": slots[identities.index(identity)]})

    return ProfiledStagingCmlReader(
        httpx.Client(
            base_url="https://cml.invalid",
            transport=httpx.MockTransport(handler),
            trust_env=False,
        )
    )


def test_logical_interface_is_excluded_from_physical_slot_map() -> None:
    reader = _interface_reader([None, 0, 1, 2, 3])
    assert reader.interfaces(LAB_ID, "node-core") == {
        0: "interface-1",
        1: "interface-2",
        2: "interface-3",
        3: "interface-4",
    }


@pytest.mark.parametrize(
    "slots",
    [
        [0, 0],
        [-1],
        [True],
        ["0"],
        [{"slot": 0}],
    ],
)
def test_physical_slot_map_rejects_invalid_slot_semantics(slots: list[object]) -> None:
    with pytest.raises(ProfiledStagingError, match="interface slot rejected"):
        _interface_reader(slots).interfaces(LAB_ID, "node-core")


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
        "logical_link",
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


class _RecycleClock:
    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def _observed_recycle_fixture():
    from test_profiled_realization import inventory_devices

    devices = inventory_devices()
    reader = Reader(title="NCDP Staging run-001")
    observed = admit_created_realization(
        cast(object, reader),
        "run-001",
        outputs(reader),
        devices,
    )
    return devices, observed


def test_transit_recycler_mutates_only_exact_iosv_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    devices, observed = _observed_recycle_fixture()
    transit = next(
        item for item in devices if str(item.logical_name) == "transit-ios-01"
    )
    profile = CML_REALIZATION_PROFILE_CATALOG[transit.cml_realization_profile_id]

    state = {"value": "BOOTED"}
    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))

        if request.method == "GET" and request.url.path == (f"/api/v0/labs/{LAB_ID}"):
            return httpx.Response(
                200,
                json={"lab_title": "NCDP Staging run-001"},
            )

        if request.method == "GET" and request.url.path == (
            f"/api/v0/labs/{LAB_ID}/nodes/node-transit"
        ):
            return httpx.Response(
                200,
                json={
                    "label": "transit-ios-01",
                    "node_definition": profile.node_definition,
                    "image_definition": profile.image_definition,
                    "state": state["value"],
                },
            )

        if request.method == "PUT" and request.url.path.endswith(
            "/node-transit/state/stop"
        ):
            state["value"] = "STOPPED"
            return httpx.Response(204)

        if request.method == "PUT" and request.url.path.endswith(
            "/node-transit/state/start"
        ):
            state["value"] = "BOOTED"
            return httpx.Response(204)

        return httpx.Response(500)

    clock = _RecycleClock()
    monkeypatch.setattr(staging_cml.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(staging_cml.time, "sleep", clock.sleep)

    client = httpx.Client(
        base_url="https://cml.invalid",
        transport=httpx.MockTransport(handler),
        trust_env=False,
    )
    recycler = ProfiledStagingCmlProfileRecycler(client)

    evidence = recycler.recycle(
        run_id="run-001",
        observed=observed,
        device=devices[2],
    )

    put_paths = [path for method, path in calls if method == "PUT"]

    assert put_paths == [
        f"/api/v0/labs/{LAB_ID}/nodes/node-transit/state/stop",
        f"/api/v0/labs/{LAB_ID}/nodes/node-transit/state/start",
    ]
    assert clock.now == 60
    assert evidence.identity == ("staging-profile-recycle:run-001:transit-ios-01")
    assert evidence.digest.startswith("sha256:")


def test_transit_recycler_rejects_profile_mismatch_before_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    devices, observed = _observed_recycle_fixture()
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)

        if request.url.path == f"/api/v0/labs/{LAB_ID}":
            return httpx.Response(
                200,
                json={"lab_title": "NCDP Staging run-001"},
            )

        return httpx.Response(
            200,
            json={
                "label": "transit-ios-01",
                "node_definition": "wrong",
                "image_definition": "wrong",
                "state": "BOOTED",
            },
        )

    clock = _RecycleClock()
    monkeypatch.setattr(staging_cml.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(staging_cml.time, "sleep", clock.sleep)

    recycler = ProfiledStagingCmlProfileRecycler(
        httpx.Client(
            base_url="https://cml.invalid",
            transport=httpx.MockTransport(handler),
            trust_env=False,
        )
    )

    with pytest.raises(
        ProfiledStagingError,
        match="identity rejected",
    ):
        recycler.recycle(
            run_id="run-001",
            observed=observed,
            device=devices[2],
        )

    assert "PUT" not in calls


def test_transit_recycler_uncertain_stop_is_not_replayed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    devices, observed = _observed_recycle_fixture()
    transit = next(
        item for item in devices if str(item.logical_name) == "transit-ios-01"
    )
    profile = CML_REALIZATION_PROFILE_CATALOG[transit.cml_realization_profile_id]

    stop_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal stop_calls

        if request.method == "GET" and request.url.path == (f"/api/v0/labs/{LAB_ID}"):
            return httpx.Response(
                200,
                json={"lab_title": "NCDP Staging run-001"},
            )

        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "label": "transit-ios-01",
                    "node_definition": profile.node_definition,
                    "image_definition": profile.image_definition,
                    "state": "BOOTED",
                },
            )

        if request.url.path.endswith("/state/stop"):
            stop_calls += 1
            raise httpx.ReadTimeout(
                "uncertain stop",
                request=request,
            )

        return httpx.Response(500)

    clock = _RecycleClock()
    monkeypatch.setattr(staging_cml.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(staging_cml.time, "sleep", clock.sleep)

    recycler = ProfiledStagingCmlProfileRecycler(
        httpx.Client(
            base_url="https://cml.invalid",
            transport=httpx.MockTransport(handler),
            trust_env=False,
        )
    )

    with pytest.raises(
        ProfiledStagingAmbiguousError,
        match="stop outcome is ambiguous",
    ):
        recycler.recycle(
            run_id="run-001",
            observed=observed,
            device=devices[2],
        )

    assert stop_calls == 1


def test_transit_recycler_uncertain_start_is_reconciled_without_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    devices, observed = _observed_recycle_fixture()
    transit = next(
        item for item in devices if str(item.logical_name) == "transit-ios-01"
    )
    profile = CML_REALIZATION_PROFILE_CATALOG[transit.cml_realization_profile_id]

    state = {"value": "BOOTED"}
    start_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal start_calls

        if request.method == "GET" and request.url.path == (f"/api/v0/labs/{LAB_ID}"):
            return httpx.Response(
                200,
                json={"lab_title": "NCDP Staging run-001"},
            )

        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "label": "transit-ios-01",
                    "node_definition": profile.node_definition,
                    "image_definition": profile.image_definition,
                    "state": state["value"],
                },
            )

        if request.url.path.endswith("/state/stop"):
            state["value"] = "STOPPED"
            return httpx.Response(204)

        if request.url.path.endswith("/state/start"):
            start_calls += 1
            state["value"] = "BOOTED"
            raise httpx.ReadTimeout(
                "uncertain start",
                request=request,
            )

        return httpx.Response(500)

    clock = _RecycleClock()
    monkeypatch.setattr(staging_cml.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(staging_cml.time, "sleep", clock.sleep)

    recycler = ProfiledStagingCmlProfileRecycler(
        httpx.Client(
            base_url="https://cml.invalid",
            transport=httpx.MockTransport(handler),
            trust_env=False,
        )
    )

    evidence = recycler.recycle(
        run_id="run-001",
        observed=observed,
        device=devices[2],
    )

    assert start_calls == 1
    assert evidence.identity == ("staging-profile-recycle:run-001:transit-ios-01")


def test_transit_recycler_http_500_is_ambiguous_and_not_replayed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    devices, observed = _observed_recycle_fixture()
    transit = next(
        item for item in devices if str(item.logical_name) == "transit-ios-01"
    )
    profile = CML_REALIZATION_PROFILE_CATALOG[transit.cml_realization_profile_id]

    stop_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal stop_calls

        if request.method == "GET" and request.url.path == (f"/api/v0/labs/{LAB_ID}"):
            return httpx.Response(
                200,
                json={"lab_title": "NCDP Staging run-001"},
            )

        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "label": "transit-ios-01",
                    "node_definition": profile.node_definition,
                    "image_definition": profile.image_definition,
                    "state": "BOOTED",
                },
            )

        if request.url.path.endswith("/state/stop"):
            stop_calls += 1
            return httpx.Response(500)

        return httpx.Response(500)

    clock = _RecycleClock()
    monkeypatch.setattr(staging_cml.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(staging_cml.time, "sleep", clock.sleep)

    recycler = ProfiledStagingCmlProfileRecycler(
        httpx.Client(
            base_url="https://cml.invalid",
            transport=httpx.MockTransport(handler),
            trust_env=False,
        )
    )

    with pytest.raises(
        ProfiledStagingAmbiguousError,
        match="stop outcome is ambiguous",
    ):
        recycler.recycle(
            run_id="run-001",
            observed=observed,
            device=devices[2],
        )

    assert stop_calls == 1


def test_get_only_reader_remains_without_mutation_surface() -> None:
    assert not hasattr(ProfiledStagingCmlReader, "_put_state_once")
    assert not hasattr(ProfiledStagingCmlReader, "recycle")


@pytest.mark.parametrize("first_boot_seconds", [0, 30, 120])
def test_early_recycle_waits_for_transit_not_slow_lab(monkeypatch, first_boot_seconds):
    devices, observed = _observed_recycle_fixture()
    clock = _RecycleClock()
    monkeypatch.setattr(staging_cml.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(staging_cml.time, "sleep", clock.sleep)
    puts = []
    phase = "initial"

    def handler(request):
        nonlocal phase
        if request.method == "PUT":
            puts.append((request.url.path, clock.now))
            if request.url.path.endswith("/stop"):
                phase = "stopped"
            elif request.url.path.endswith("/start"):
                phase = "second"
            else:
                pytest.fail("unexpected mutation")
            return httpx.Response(204)
        if request.url.path == f"/api/v0/labs/{LAB_ID}":
            # The slowest first boot would only finish at t=240. This fact
            # must not delay transit STOP (60 seconds after transit BOOTED).
            return httpx.Response(
                200,
                json={
                    "lab_title": "NCDP Staging run-001",
                    "state": "STARTED",
                    "booted": clock.now >= 240,
                },
            )
        assert request.url.path == f"/api/v0/labs/{LAB_ID}/nodes/node-transit"
        state = "STOPPED" if phase == "stopped" else "BOOTED"
        if phase == "initial" and clock.now < first_boot_seconds:
            state = "QUEUED" if clock.now < 4 else "STARTED"
        return httpx.Response(
            200,
            json={
                "label": "transit-ios-01",
                "node_definition": "iosv",
                "image_definition": "iosv-159-3-m12",
                "state": state,
            },
        )

    recycler = ProfiledStagingCmlProfileRecycler(
        httpx.Client(
            base_url="https://cml.invalid", transport=httpx.MockTransport(handler)
        )
    )
    recycler.recycle(run_id="run-001", observed=observed, device=devices[2])
    assert puts == [
        (
            f"/api/v0/labs/{LAB_ID}/nodes/node-transit/state/stop",
            first_boot_seconds + 60,
        ),
        (
            f"/api/v0/labs/{LAB_ID}/nodes/node-transit/state/start",
            first_boot_seconds + 60,
        ),
    ]
    assert recycler.timings_seconds["recycle_first_boot"] == first_boot_seconds
    assert recycler.timings_seconds["recycle_persistence"] == 60


@pytest.mark.parametrize("state", ["STARTED", "STOPPED", "UNKNOWN", None])
def test_unready_initial_transit_never_gets_recycled(monkeypatch, state):
    devices, observed = _observed_recycle_fixture()
    clock = _RecycleClock()
    monkeypatch.setattr(staging_cml.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(staging_cml.time, "sleep", clock.sleep)

    def handler(request):
        assert request.method == "GET"
        if request.url.path == f"/api/v0/labs/{LAB_ID}":
            return httpx.Response(200, json={"lab_title": "NCDP Staging run-001"})
        return httpx.Response(
            200,
            json={
                "label": "transit-ios-01",
                "node_definition": "iosv",
                "image_definition": "iosv-159-3-m12",
                "state": state,
            },
        )

    recycler = ProfiledStagingCmlProfileRecycler(
        httpx.Client(
            base_url="https://cml.invalid", transport=httpx.MockTransport(handler)
        )
    )
    with pytest.raises(ProfiledStagingError):
        recycler.recycle(run_id="run-001", observed=observed, device=devices[2])
    assert clock.now == (300 if state == "STARTED" else 0)
    assert set(recycler.timings_seconds) == {"recycle_first_boot"}
