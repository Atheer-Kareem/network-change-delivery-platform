"""Safety-focused tests for the first Junos interface-description vertical."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from xml.etree import ElementTree

import httpx
import pytest
from jnpr.junos.exception import RpcTimeoutError
from pydantic import ValidationError

import network_change_delivery.junos_adapter as junos_module
from network_change_delivery.ansible_adapter import ProviderError
from network_change_delivery.inventory import NetBoxInventoryProvider
from network_change_delivery.junos_adapter import JunosPyEZAdapter, JunosTransaction
from network_change_delivery.models import (
    DesiredDescription,
    ExecutionDisposition,
    ExecutionResult,
    FinalOutcome,
    InterfaceDescriptionIntent,
    InterfaceState,
    InventoryDevice,
    JunosConfigArtifact,
    render_junos_interface_description,
)
from network_change_delivery.secrets import (
    ENVIRONMENT_REFERENCE,
    CredentialReference,
    DeviceCredentials,
)
from network_change_delivery.workflow import build_plan, deploy_plan


def device(**changes: object) -> InventoryDevice:
    values: dict[str, object] = {
        "name": "edge-junos-01",
        "host": "192.0.2.20",
        "port": 830,
        "platform": "junos",
        "expected_hostname": "edge-junos-01",
        "inventory_source": "netbox",
        "inventory_object_id": "netbox:dcim.device:7",
        "inventory_interface_object_id": "netbox:dcim.interface:70",
    }
    values.update(changes)
    return InventoryDevice.model_validate(values)


def intent(description: str = "managed-by-network-change-delivery-platform"):
    return InterfaceDescriptionIntent(
        change_id="CHG-JUNOS-001",
        kind="interface_description",
        target="edge-junos-01",
        interface="ge-0/0/1",
        desired=DesiredDescription(description=description),
    )


def state(description: str | None = None) -> InterfaceState:
    return InterfaceState(
        observed_hostname="edge-junos-01",
        software_version="23.2R1",
        interface="ge-0/0/1",
        exists=True,
        description=description,
        protected=False,
    )


def credential() -> CredentialReference:
    return CredentialReference("environment", ENVIRONMENT_REFERENCE)


def plan():
    return build_plan(
        intent(),
        device(),
        state(),
        credential=credential(),
        created_at=datetime(2026, 8, 22, tzinfo=UTC),
    )


@pytest.mark.parametrize(
    "description",
    ["A & B", "less < greater >", "quotes \" and ' remain data"],
)
def test_junos_xml_is_deterministic_and_escaped(description: str) -> None:
    xml = render_junos_interface_description("ge-0/0/1", description)
    artifact = JunosConfigArtifact(
        interface="ge-0/0/1", description=description, xml=xml
    )
    assert (
        ElementTree.fromstring(artifact.xml).findtext(
            "./interfaces/interface/description"
        )
        == description
    )
    assert artifact.xml == render_junos_interface_description("ge-0/0/1", description)


def test_arbitrary_or_control_bearing_junos_xml_is_rejected() -> None:
    with pytest.raises(ValidationError):
        JunosConfigArtifact(
            interface="ge-0/0/1",
            description="safe",
            xml="<configuration><system /></configuration>",
        )
    with pytest.raises(ValidationError):
        intent("line\nbreak")


def test_junos_plan_binds_native_transaction_and_digest() -> None:
    approved = plan()
    assert approved.platform == "junos"
    assert approved.port == 830
    assert approved.transaction_strategy == "junos_commit_confirmed"
    assert approved.confirmed_timeout_minutes == 5
    assert approved.confirmation_operation == "confirm_previous_commit"
    assert isinstance(approved.execution_artifact, JunosConfigArtifact)
    assert approved.recovery_artifact is None
    assert approved.verify_digest()
    for change in (
        {"transaction_strategy": "cisco_targeted_inverse"},
        {"confirmed_timeout_minutes": None},
        {
            "execution_artifact": approved.execution_artifact.model_copy(
                update={"xml": "different"}
            )
        },
    ):
        assert approved.model_copy(update=change).calculated_digest() != approved.digest


@pytest.mark.parametrize(
    "changes",
    [
        {"port": 22},
        {"transaction_strategy": "cisco_targeted_inverse"},
        {"recovery_artifact": {"parent": "interface ge-0/0/1", "lines": []}},
    ],
)
def test_junos_plan_rejects_mixed_vendor_contract(changes: dict[str, object]) -> None:
    payload = plan().model_dump(mode="json")
    payload.update(changes)
    with pytest.raises(ValidationError):
        type(plan()).model_validate(payload)


def test_netbox_maps_juniper_platform_to_port_830_and_preserves_ids() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("devices/"):
            return httpx.Response(
                200,
                json={
                    "count": 1,
                    "next": None,
                    "results": [
                        {
                            "id": 7,
                            "name": "edge-junos-01",
                            "status": {"value": "active"},
                            "tags": [{"slug": "ncdp-managed"}],
                            "platform": {"slug": "juniper-junos"},
                            "primary_ip4": {"address": "192.0.2.20/24"},
                        }
                    ],
                },
            )
        if "name" in request.url.params:
            return httpx.Response(
                200,
                json={
                    "count": 1,
                    "next": None,
                    "results": [{"id": 70, "name": "ge-0/0/1"}],
                },
            )
        return httpx.Response(200, json={"count": 0, "next": None, "results": []})

    resolved = NetBoxInventoryProvider(
        "https://netbox.example",
        "token",
        transport=httpx.MockTransport(handler),
    ).resolve("edge-junos-01", "ge-0/0/1")
    assert (resolved.platform, resolved.port) == ("junos", 830)
    assert resolved.inventory_object_id == "netbox:dcim.device:7"
    assert resolved.inventory_interface_object_id == "netbox:dcim.interface:70"


class FakeConnection:
    def __init__(self, reply: ElementTree.Element | None = None) -> None:
        self.facts = {"hostname": "edge-junos-01", "version": "23.2R1"}
        self.rpc = SimpleNamespace(
            get_config=lambda **_kwargs: (
                reply
                if reply is not None
                else ElementTree.fromstring(
                    "<configuration><interfaces /></configuration>"
                )
            )
        )

    def __enter__(self):
        return self

    def __exit__(self, *_args: object) -> None:
        return None


def test_pyez_session_disables_auth_and_proxy_fallback(monkeypatch) -> None:
    options: dict[str, object] = {}

    def factory(**kwargs: object) -> FakeConnection:
        options.update(kwargs)
        return FakeConnection()

    monkeypatch.setattr(junos_module, "verify_existing_host_trust", lambda _d: "ok")
    adapter = JunosPyEZAdapter(device_factory=factory)
    adapter.discover(device(), DeviceCredentials(username="u", password="p"))
    assert options["port"] == 830
    assert options["hostkey_verify"] is True
    assert options["look_for_keys"] is False
    assert options["allow_agent"] is False
    assert options["ssh_private_key_file"] is None
    assert options["proxy_command"] is None
    assert Path(str(options["ssh_config"])).name == "config"


def test_junos_collection_normalizes_committed_interface_state(monkeypatch) -> None:
    reply = ElementTree.fromstring(
        "<configuration><interfaces><interface><name>ge-0/0/1</name>"
        "<description>connected</description><disable/><unit><family><inet>"
        "<address><name>192.0.2.1/31</name></address></inet></family></unit>"
        "</interface></interfaces></configuration>"
    )
    monkeypatch.setattr(junos_module, "verify_existing_host_trust", lambda _d: "ok")
    adapter = JunosPyEZAdapter(device_factory=lambda **_kwargs: FakeConnection(reply))
    observed = adapter.collect(
        device(protected_interfaces=("ge-0/0/1",)),
        DeviceCredentials(username="u", password="p"),
        "ge-0/0/1",
    )
    assert observed.observed_hostname == "edge-junos-01"
    assert observed.software_version == "23.2R1"
    assert observed.description == "connected"
    assert observed.enabled is False
    assert observed.ipv4_addresses == ("192.0.2.1/31",)
    assert observed.protected is True


def test_junos_collection_marks_missing_exact_interface(monkeypatch) -> None:
    monkeypatch.setattr(junos_module, "verify_existing_host_trust", lambda _d: "ok")
    adapter = JunosPyEZAdapter(device_factory=lambda **_kwargs: FakeConnection())
    observed = adapter.collect(
        device(), DeviceCredentials(username="u", password="p"), "ge-0/0/9"
    )
    assert observed.exists is False
    assert observed.interface == "ge-0/0/9"


class FakeConfig:
    def __init__(self, _connection: object, mode: str, *, existing: str | None = None):
        self.mode = mode
        self.existing = existing
        self.calls: list[object] = []
        self.rollback_calls: list[int] = []
        self.commit_result: object = True
        self.check_result = True
        self.diff_calls = 0

    def __enter__(self):
        self.calls.append("enter")
        return self

    def __exit__(self, *_args: object) -> None:
        self.calls.append("exit")

    def diff(self):
        self.calls.append("diff")
        self.diff_calls += 1
        if self.diff_calls == 1:
            return self.existing
        return (
            "[edit interfaces ge-0/0/1]\n"
            "+ description managed-by-network-change-delivery-platform;"
        )

    def load(self, xml: str, **kwargs: object) -> None:
        self.calls.append(("load", xml, kwargs))

    def commit_check(self) -> bool:
        self.calls.append("commit_check")
        return self.check_result

    def commit(self, **kwargs: object):
        self.calls.append(("commit", kwargs))
        if isinstance(self.commit_result, Exception):
            raise self.commit_result
        return self.commit_result

    def rollback(self, value: int) -> None:
        self.rollback_calls.append(value)


def candidate_reply(description: str = "managed-by-network-change-delivery-platform"):
    return ElementTree.fromstring(
        "<configuration><interfaces><interface><name>ge-0/0/1</name>"
        f"<description>{description}</description></interface></interfaces></configuration>"
    )


def test_same_exclusive_transaction_preserves_candidate_through_commit() -> None:
    connection = FakeConnection(candidate_reply())
    config = FakeConfig(connection, "exclusive")
    transaction = JunosTransaction(
        connection, lambda *_a, **_k: config, plan().execution_artifact
    )
    with transaction as active:
        prepared = active.prepare()
        result = active.commit_confirmed(5)
    assert config.mode == "exclusive"
    assert config.calls[:3] == [
        "enter",
        "diff",
        ("load", plan().execution_artifact.xml, {"format": "xml", "merge": True}),
    ]
    assert config.calls.index("commit_check") < config.calls.index(
        ("commit", {"confirm": 5})
    )
    assert prepared.diff_sha256.startswith("sha256:")
    assert result.disposition is ExecutionDisposition.SUCCEEDED
    assert config.rollback_calls == []


def test_preexisting_candidate_blocks_before_load() -> None:
    config = FakeConfig(object(), "exclusive", existing="[edit system]\n+ services;")
    transaction = JunosTransaction(
        object(), lambda *_a, **_k: config, plan().execution_artifact
    )
    with pytest.raises(ProviderError, match="pre-existing"), transaction:
        pass
    assert not any(
        isinstance(call, tuple) and call[0] == "load" for call in config.calls
    )


def test_invalid_prepared_candidate_discards_only_uncommitted_candidate() -> None:
    connection = FakeConnection(candidate_reply("wrong"))
    config = FakeConfig(connection, "exclusive")
    transaction = JunosTransaction(
        connection, lambda *_a, **_k: config, plan().execution_artifact
    )
    with pytest.raises(ProviderError, match="not the approved"), transaction as active:
        active.prepare()
    assert config.rollback_calls == [0]
    assert 1 not in config.rollback_calls
    assert not any(
        isinstance(call, tuple) and call[0] == "commit" for call in config.calls
    )


def test_commit_check_failure_discards_candidate_without_active_write() -> None:
    connection = FakeConnection(candidate_reply())
    config = FakeConfig(connection, "exclusive")
    config.check_result = False
    transaction = JunosTransaction(
        connection, lambda *_a, **_k: config, plan().execution_artifact
    )
    with pytest.raises(ProviderError, match="commit check"), transaction as active:
        active.prepare()
    assert config.rollback_calls == [0]
    assert not any(
        isinstance(call, tuple) and call[0] == "commit" for call in config.calls
    )


@pytest.mark.parametrize(
    ("commit_result", "disposition"),
    [
        (False, ExecutionDisposition.FAILED),
        (RpcTimeoutError(None, "commit", 30), ExecutionDisposition.AMBIGUOUS),
    ],
)
def test_commit_confirmed_failure_or_ambiguity_never_retries_or_rolls_back(
    commit_result: object, disposition: ExecutionDisposition
) -> None:
    connection = FakeConnection(candidate_reply())
    config = FakeConfig(connection, "exclusive")
    config.commit_result = commit_result
    transaction = JunosTransaction(
        connection, lambda *_a, **_k: config, plan().execution_artifact
    )
    with transaction as active:
        active.prepare()
        result = active.commit_confirmed(5)
    assert result.disposition is disposition
    assert [
        call for call in config.calls if isinstance(call, tuple) and call[0] == "commit"
    ] == [("commit", {"confirm": 5})]
    assert config.rollback_calls == []


class FakeInventory:
    def resolve(self, _target: str, _interface: str | None = None) -> InventoryDevice:
        return device()


class FakeSecrets:
    def reference(self, _device: InventoryDevice) -> CredentialReference:
        return credential()

    def load(self, _device: InventoryDevice) -> DeviceCredentials:
        return DeviceCredentials(username="u", password="p")


class FakeCollector:
    def __init__(self, *states: InterfaceState | Exception) -> None:
        self.states = list(states)
        self.calls = 0

    def collect(self, *_args: object) -> InterfaceState:
        self.calls += 1
        value = self.states.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


class FakeTransaction:
    def __init__(self, commit: ExecutionResult) -> None:
        self.commit = commit
        self.prepares = 0
        self.commits = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def prepare(self) -> object:
        self.prepares += 1
        return object()

    def commit_confirmed(self, minutes: int) -> ExecutionResult:
        assert minutes == 5
        self.commits += 1
        return self.commit


class FakeJunosProvider:
    def __init__(self, commit: ExecutionResult, confirmation: ExecutionResult) -> None:
        self.tx = FakeTransaction(commit)
        self.confirmation = confirmation
        self.confirmations = 0

    def transaction(self, *_args: object) -> FakeTransaction:
        return self.tx

    def confirm(self, *_args: object) -> ExecutionResult:
        self.confirmations += 1
        return self.confirmation


def outcome_result(disposition: ExecutionDisposition) -> ExecutionResult:
    return ExecutionResult(disposition=disposition, message="bounded")


def run_deploy(
    post: InterfaceState | Exception,
    *,
    commit: ExecutionDisposition = ExecutionDisposition.SUCCEEDED,
    confirmation: ExecutionDisposition = ExecutionDisposition.SUCCEEDED,
):
    provider = FakeJunosProvider(outcome_result(commit), outcome_result(confirmation))
    collector = FakeCollector(state(), post)
    approved = plan()
    record = deploy_plan(
        approved,
        approved.digest,
        FakeInventory(),
        FakeSecrets(),
        collector,
        provider,
    )
    return record, provider, collector


def test_successful_fresh_validation_confirms_once() -> None:
    record, provider, collector = run_deploy(
        state("managed-by-network-change-delivery-platform")
    )
    assert record.final_outcome is FinalOutcome.SUCCEEDED
    assert collector.calls == 2
    assert provider.confirmations == 1


@pytest.mark.parametrize(
    "post",
    [
        state("wrong"),
        state().model_copy(update={"observed_hostname": "other"}),
        RuntimeError("failed"),
    ],
)
def test_failed_independent_validation_leaves_auto_rollback_pending(post) -> None:
    record, provider, _collector = run_deploy(post)
    assert record.final_outcome is FinalOutcome.AUTO_ROLLBACK_PENDING
    assert provider.confirmations == 0


def test_ambiguous_commit_is_not_confirmed_or_retried() -> None:
    record, provider, collector = run_deploy(
        state("managed-by-network-change-delivery-platform"),
        commit=ExecutionDisposition.AMBIGUOUS,
    )
    assert record.final_outcome is FinalOutcome.AMBIGUOUS
    assert provider.tx.commits == 1
    assert provider.confirmations == 0
    assert collector.calls == 1


@pytest.mark.parametrize(
    ("disposition", "outcome"),
    [
        (ExecutionDisposition.FAILED, FinalOutcome.CONFIRMATION_FAILED),
        (ExecutionDisposition.AMBIGUOUS, FinalOutcome.CONFIRMATION_AMBIGUOUS),
    ],
)
def test_confirmation_failure_and_ambiguity_are_distinct_and_not_retried(
    disposition: ExecutionDisposition, outcome: FinalOutcome
) -> None:
    record, provider, _collector = run_deploy(
        state("managed-by-network-change-delivery-platform"),
        confirmation=disposition,
    )
    assert record.final_outcome is outcome
    assert provider.confirmations == 1
