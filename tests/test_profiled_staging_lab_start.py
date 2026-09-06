"""MockTransport-only tests for the one-shot initial CML lab START boundary."""

from dataclasses import replace

import httpx
import pytest
from test_profiled_staging_cml import LAB_ID, Reader, _observed_recycle_fixture

from network_change_delivery.profiled_staging import (
    ProfiledStagingAmbiguousError,
    ProfiledStagingError,
)
from network_change_delivery.profiled_staging_cml import (
    ProfiledStagingCmlLabStarter,
    ProfiledStagingCmlReader,
)


class LabApi:
    def __init__(self, responses=(204,), *, crossed=True):
        self.devices, self.observed = _observed_recycle_fixture()
        self.reader = Reader(title=self.observed.lab_title)
        self.responses = iter(responses)
        self.crossed = crossed
        self.state = "DEFINED_ON_CORE"
        self.calls = []
        self.damage = ""

    def handler(self, request):
        self.calls.append((request.method, request.url.path))
        root = f"/api/v0/labs/{LAB_ID}"
        if request.method == "PUT":
            assert request.url.path in {root + "/start", root + "/state/start"}
            response = next(self.responses)  # More than the expected calls fails.
            if response != 404 and self.crossed:
                self.state = "STARTED"
            if response == "timeout":
                raise httpx.ReadTimeout(
                    "synthetic-private-provider-body", request=request
                )
            return httpx.Response(response, text="synthetic-private-provider-body")
        assert request.method == "GET"
        if request.url.path == root:
            payload = {
                "id": LAB_ID,
                "lab_title": self.reader.title,
                "state": self.state,
            }
            if self.damage == "lab_id":
                payload["id"] = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
            elif self.damage == "lab_title":
                payload["lab_title"] = "NCDP Live"
            elif self.damage == "lab_state":
                payload["state"] = "STOPPED"
            return httpx.Response(200, json=payload)
        if request.url.path == root + "/nodes":
            values = list(self.reader.node_ids.values())
            if self.damage == "node_membership":
                values[-1] = "unexpected-node"
            return httpx.Response(200, json=values)
        if request.url.path == root + "/links":
            values = list(self.reader.link_ids.values())
            return httpx.Response(
                200, json=values[:-1] if self.damage == "links" else values
            )
        prefix = root + "/nodes/"
        assert request.url.path.startswith(prefix)
        identity = request.url.path.removeprefix(prefix)
        payload = self.reader.item(LAB_ID, "nodes", identity) | {
            "id": identity,
            "state": self.state,
        }
        if identity == "node-transit":
            for damage, key, value in (
                ("node_id", "id", "other-node"),
                ("node_label", "label", "core-02"),
                ("definition", "node_definition", "cat8000v"),
                ("image", "image_definition", "unexpected-image"),
                ("node_state", "state", "BOOTED"),
            ):
                if self.damage == damage:
                    payload[key] = value
        return httpx.Response(200, json=payload)

    def starter(self):
        return ProfiledStagingCmlLabStarter(
            httpx.Client(
                base_url="https://cml.invalid",
                transport=httpx.MockTransport(self.handler),
                headers={"Authorization": "Bearer synthetic-secret"},
            )
        )

    @property
    def puts(self):
        return [path for method, path in self.calls if method == "PUT"]

    def start(self, starter=None):
        return (starter or self.starter()).start(
            run_id="run-001", observed=self.observed, devices=self.devices
        )


@pytest.mark.parametrize("responses", [(200,), (204,), (404, 204)])
def test_exact_initial_lab_start_and_404_only_endpoint_compatibility(responses):
    api = LabApi(responses)
    starter = api.starter()
    evidence = api.start(starter)
    expected = [f"/api/v0/labs/{LAB_ID}/start"]
    if len(responses) == 2:
        expected.append(f"/api/v0/labs/{LAB_ID}/state/start")
    assert api.puts == expected
    assert len(api.calls) == 9 + len(responses)  # Lab, memberships, six nodes.
    assert all(method == "GET" for method, _ in api.calls[:9])
    assert evidence.identity == "staging-lab-start:run-001"
    assert "synthetic" not in evidence.model_dump_json()
    before = list(api.calls)
    with pytest.raises(ProfiledStagingError, match="cannot be replayed"):
        api.start(starter)
    assert api.calls == before


@pytest.mark.parametrize("response", ["timeout", 408, 500, 503])
@pytest.mark.parametrize("crossed", [False, True])
@pytest.mark.parametrize("legacy", [False, True])
def test_uncertain_start_reconciles_once_and_never_replays(response, crossed, legacy):
    api = LabApi(((404, response) if legacy else (response,)), crossed=crossed)
    starter = api.starter()
    if crossed:
        assert api.start(starter).identity == "staging-lab-start:run-001"
    else:
        with pytest.raises(ProfiledStagingAmbiguousError, match="ambiguous"):
            api.start(starter)
    assert len(api.puts) == (2 if legacy else 1)
    assert len(api.calls) == 18 + len(api.puts)  # Exactly one full readback pass.
    assert all(method == "GET" for method, _ in api.calls[-9:])
    before = list(api.calls)
    with pytest.raises(ProfiledStagingError, match="cannot be replayed"):
        api.start(starter)
    assert api.calls == before


@pytest.mark.parametrize("status", [302, 400, 401, 403, 405, 409])
def test_definitively_rejected_start_has_no_fallback_or_reconciliation(status):
    api = LabApi((status,), crossed=False)
    with pytest.raises(ProfiledStagingError, match="start rejected"):
        api.start()
    assert api.puts == [f"/api/v0/labs/{LAB_ID}/start"]
    assert len(api.calls) == 10


@pytest.mark.parametrize(
    "damage",
    [
        "lab_id",
        "lab_title",
        "lab_state",
        "node_membership",
        "links",
        "node_id",
        "node_label",
        "definition",
        "image",
        "node_state",
    ],
)
def test_lab_start_fresh_realization_admission_rejects_before_any_mutation(damage):
    api = LabApi()
    api.damage = damage
    with pytest.raises(ProfiledStagingError):
        api.start()
    assert api.puts == []


@pytest.mark.parametrize(
    "damage", ["run", "uuid", "population", "profile", "node_ids", "title"]
)
def test_lab_start_requires_exact_run_and_catalog_before_access(damage):
    api = LabApi()
    run_id = "run-001"
    if damage == "run":
        run_id = "wrong-run"
    elif damage == "uuid":
        api.observed = replace(api.observed, lab_id="../other-lab")
    elif damage == "title":
        api.observed = replace(api.observed, lab_title="NCDP Live")
    elif damage == "node_ids":
        api.observed = replace(api.observed, node_ids={})
    else:
        field = "device_identity" if damage == "population" else "automation_profile_id"
        api.devices = (
            api.devices[0].model_copy(update={field: getattr(api.devices[1], field)}),
            *api.devices[1:],
        )
    with pytest.raises(ProfiledStagingError):
        api.starter().start(run_id=run_id, observed=api.observed, devices=api.devices)
    assert api.calls == []


def test_unreadable_uncertain_start_is_ambiguous_without_another_put():
    api = LabApi(("timeout",))

    def handler(request):
        if api.puts and request.method == "GET":
            return httpx.Response(503, text="synthetic-secret")
        return api.handler(request)

    starter = ProfiledStagingCmlLabStarter(
        httpx.Client(
            base_url="https://cml.invalid", transport=httpx.MockTransport(handler)
        )
    )
    with pytest.raises(ProfiledStagingAmbiguousError):
        api.start(starter)
    assert len(api.puts) == 1


@pytest.mark.parametrize(
    "lab_state,node_state,accepted",
    [
        ("STARTED", "DEFINED_ON_CORE", True),
        ("DEFINED_ON_CORE", "QUEUED", True),
        ("DEFINED_ON_CORE", "BOOTING", True),
        ("STARTED", "STOPPED", False),
        ("STARTED", "UNKNOWN", False),
        ({"unexpected": "state"}, "STARTED", False),
    ],
)
def test_reconciliation_requires_exact_safe_states_and_positive_crossing(
    lab_state, node_state, accepted
):
    api = LabApi((408,))

    def handler(request):
        response = api.handler(request)
        if api.puts and request.method == "GET":
            if request.url.path == f"/api/v0/labs/{LAB_ID}":
                return httpx.Response(200, json=response.json() | {"state": lab_state})
            if request.url.path.endswith("/nodes/node-transit"):
                return httpx.Response(200, json=response.json() | {"state": node_state})
            if "/nodes/" in request.url.path:
                return httpx.Response(
                    200, json=response.json() | {"state": "DEFINED_ON_CORE"}
                )
        return response

    starter = ProfiledStagingCmlLabStarter(
        httpx.Client(
            base_url="https://cml.invalid", transport=httpx.MockTransport(handler)
        )
    )
    if accepted:
        api.start(starter)
    else:
        with pytest.raises(ProfiledStagingAmbiguousError):
            api.start(starter)
    assert len(api.puts) == 1
    assert len(api.calls) == 19


def test_both_endpoints_404_is_definitive_failure_without_another_attempt():
    api = LabApi((404, 404))
    with pytest.raises(ProfiledStagingError, match="start rejected"):
        api.start()
    assert len(api.calls) == 11
    assert len(api.puts) == 2


def test_lab_starter_environment_uses_memory_bearer_and_strict_tls(monkeypatch):
    import network_change_delivery.profiled_staging_cml as module

    monkeypatch.setenv("CML2_ADDRESS", "https://cml.invalid")
    monkeypatch.setenv("CML2_CACERT", "synthetic-ca")
    monkeypatch.delenv("CML2_TOKEN", raising=False)
    context = object()
    monkeypatch.setattr(
        module.ssl,
        "create_default_context",
        lambda *, cadata: (
            context if cadata == "synthetic-ca" else pytest.fail("wrong CA")
        ),
    )
    clients = []
    monkeypatch.setattr(module.httpx, "Client", lambda **kwargs: clients.append(kwargs))
    starter = ProfiledStagingCmlLabStarter.from_environment(token="synthetic-bearer")
    assert "synthetic-bearer" not in repr(starter)
    assert clients == [
        {
            "base_url": "https://cml.invalid",
            "headers": {"Authorization": "Bearer synthetic-bearer"},
            "verify": context,
            "timeout": 15,
            "trust_env": False,
            "follow_redirects": False,
        }
    ]


def test_reader_still_has_no_start_mutation():
    assert not hasattr(ProfiledStagingCmlReader, "start")
    assert not hasattr(ProfiledStagingCmlReader, "_put_state_once")


@pytest.mark.parametrize("crossed", [False, True])
def test_start_failure_runs_owned_cleanup_without_a_second_start(crossed):
    from test_profiled_staging import Operations

    from network_change_delivery.profiled_staging import ProfiledStagingLifecycle

    api = LabApi(("timeout",), crossed=crossed)

    class StartedOperations(Operations):
        def create(self):
            self.calls.append("create")
            self.exists = True
            self.create_stage = "succeeded"
            self.start_stage = "attempted"
            self.lab_start_evidence = api.start()
            self.start_stage = "succeeded"
            raise ProfiledStagingError("later read-only stage failure")

    operation = StartedOperations()
    result = ProfiledStagingLifecycle("run-001", "local", operation).run()
    assert result.start_outcome == ("succeeded" if crossed else "attempted")
    assert (
        result.destroy_outcome
        == result.absence_verification
        == result.state_retirement
        == "succeeded"
    )
    assert result.cleanup_failure is None
    assert len(api.puts) == 1
    assert operation.calls[-4:] == ["destroy", "complete=False", "absence", "retire"]
