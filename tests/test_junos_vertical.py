"""Safety-focused tests for the first Junos interface-description vertical."""

from __future__ import annotations

import base64
import stat
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from xml.etree import ElementTree

import httpx
import pytest
from jnpr.junos.exception import RpcError, RpcTimeoutError
from pydantic import ValidationError

import network_change_delivery.junos_adapter as junos_module
from network_change_delivery.ansible_adapter import HostTrustError, ProviderError
from network_change_delivery.inventory import NetBoxInventoryProvider
from network_change_delivery.junos_adapter import (
    JunosPyEZAdapter,
    JunosTransaction,
    _interface_filter,
)
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


def test_pyez_interface_filter_is_serialized_xml() -> None:
    assert _interface_filter() == "<configuration><interfaces /></configuration>"
    assert (
        ElementTree.fromstring(_interface_filter("ge-0/0/1")).findtext(
            "./interfaces/interface/name"
        )
        == "ge-0/0/1"
    )


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


@pytest.mark.parametrize("management_interface", ["fxp0", "em0"])
def test_junos_management_interfaces_are_independently_protected(
    management_interface: str,
) -> None:
    protected_intent = intent().model_copy(update={"interface": management_interface})
    protected_state = state().model_copy(update={"interface": management_interface})
    with pytest.raises(ValueError, match="protected as Junos management"):
        build_plan(
            protected_intent,
            device(),
            protected_state,
            credential=credential(),
        )


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
    def __init__(
        self,
        reply: ElementTree.Element | None = None,
        operational: ElementTree.Element | None = None,
        exit_error: Exception | None = None,
    ) -> None:
        self.exit_error = exit_error
        self.exit_calls = 0
        self.facts = {"hostname": "edge-junos-01", "version": "23.2R1"}
        self.rpc = SimpleNamespace(
            get_interface_information=lambda **_kwargs: (
                operational
                if operational is not None
                else ElementTree.fromstring(
                    "<interface-information><physical-interface>"
                    "<name>ge-0/0/1</name><admin-status>up</admin-status>"
                    "<oper-status>up</oper-status></physical-interface>"
                    "</interface-information>"
                )
            ),
            get_config=lambda **_kwargs: (
                reply
                if reply is not None
                else ElementTree.fromstring(
                    "<configuration><interfaces /></configuration>"
                )
            ),
        )

    def __enter__(self):
        return self

    def __exit__(self, *_args: object) -> None:
        self.exit_calls += 1
        if self.exit_error is not None:
            raise self.exit_error
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


def host_key(seed: bytes = b"trusted-junos-host-public-key") -> str:
    return base64.b64encode(seed).decode()


def use_python_endpoint_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    def lookup(target: InventoryDevice, path: Path | None = None) -> str:
        assert path is not None
        query = target.host if target.port == 22 else f"[{target.host}]:{target.port}"
        for line in path.read_text(encoding="ascii").splitlines():
            fields = line.split()
            if len(fields) == 3 and fields[0] == query:
                return "trusted"
        raise HostTrustError("trusted host key is absent")

    monkeypatch.setattr(junos_module, "verify_existing_host_trust", lookup)


def test_existing_port_qualified_trust_is_used_without_projection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_python_endpoint_lookup(monkeypatch)
    trusted = tmp_path / "staging" / "known_hosts"
    trusted.parent.mkdir()
    trusted.write_text(
        f"192.0.2.20 ssh-ed25519 {host_key()}\n"
        f"[192.0.2.20]:830 ssh-ed25519 {host_key()}\n",
        encoding="ascii",
    )
    trusted.chmod(0o600)
    original = trusted.read_bytes()
    captured: dict[str, object] = {}

    def factory(**kwargs: object) -> FakeConnection:
        config = Path(str(kwargs["ssh_config"])).read_text(encoding="utf-8")
        captured["config"] = config
        captured["temporary_files"] = tuple(
            path.name for path in Path(str(kwargs["ssh_config"])).parent.iterdir()
        )
        return FakeConnection()

    JunosPyEZAdapter(device_factory=factory, known_hosts=trusted).discover(
        device(), DeviceCredentials(username="u", password="p")
    )
    assert f"UserKnownHostsFile {trusted}" in str(captured["config"])
    assert captured["temporary_files"] == ("config",)
    assert trusted.read_bytes() == original


def test_unqualified_private_trust_is_projected_for_netconf_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_python_endpoint_lookup(monkeypatch)
    trusted = tmp_path / "persistent" / "known_hosts"
    trusted.parent.mkdir()
    encoded = host_key()
    source_line = f"192.0.2.20 ssh-ed25519 {encoded}\n"
    trusted.write_text(source_line, encoding="ascii")
    trusted.chmod(0o600)
    original = trusted.read_bytes()
    captured: dict[str, object] = {}

    def factory(**kwargs: object) -> FakeConnection:
        config_path = Path(str(kwargs["ssh_config"]))
        config = config_path.read_text(encoding="utf-8")
        projected_line = next(
            line for line in config.splitlines() if "UserKnownHostsFile" in line
        )
        projected = Path(projected_line.split(maxsplit=1)[1])
        captured.update(
            {
                "config": config,
                "projected": projected,
                "content": projected.read_text(encoding="ascii"),
                "mode": stat.S_IMODE(projected.stat().st_mode),
                "hostkey_verify": kwargs["hostkey_verify"],
                "look_for_keys": kwargs["look_for_keys"],
                "allow_agent": kwargs["allow_agent"],
                "proxy_command": kwargs["proxy_command"],
            }
        )
        return FakeConnection()

    JunosPyEZAdapter(device_factory=factory, known_hosts=trusted).discover(
        device(), DeviceCredentials(username="u", password="p")
    )
    assert captured["content"] == f"[192.0.2.20]:830 ssh-ed25519 {encoded}\n"
    assert captured["mode"] == 0o600
    assert "StrictHostKeyChecking yes" in str(captured["config"])
    assert captured["hostkey_verify"] is True
    assert captured["look_for_keys"] is False
    assert captured["allow_agent"] is False
    assert captured["proxy_command"] is None
    assert trusted.read_bytes() == original
    assert not Path(str(captured["projected"])).exists()


def test_netconf_projection_rejects_missing_base_trust(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_python_endpoint_lookup(monkeypatch)
    trusted = tmp_path / "private" / "known_hosts"
    trusted.parent.mkdir()
    trusted.write_text(f"192.0.2.99 ssh-ed25519 {host_key()}\n", encoding="ascii")
    trusted.chmod(0o600)
    adapter = JunosPyEZAdapter(
        device_factory=lambda **_kwargs: pytest.fail(
            "connection must not be attempted"
        ),
        known_hosts=trusted,
    )
    with pytest.raises(HostTrustError, match="base host key is absent"):
        adapter.discover(device(), DeviceCredentials(username="u", password="p"))


@pytest.mark.parametrize(
    "content",
    [
        (
            f"192.0.2.20 ssh-ed25519 {host_key(b'first-trusted-host-key')}\n"
            f"192.0.2.20 ssh-rsa {host_key(b'second-trusted-host-key')}\n"
        ),
        "192.0.2.20 ssh-ed25519 not-base64!\n",
        f"192.0.2.20 ssh-dss {host_key()}\n",
    ],
)
def test_netconf_projection_rejects_ambiguous_or_malformed_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, content: str
) -> None:
    use_python_endpoint_lookup(monkeypatch)
    trusted = tmp_path / "private" / "known_hosts"
    trusted.parent.mkdir()
    trusted.write_text(content, encoding="ascii")
    trusted.chmod(0o600)
    adapter = JunosPyEZAdapter(
        device_factory=lambda **_kwargs: pytest.fail(
            "connection must not be attempted"
        ),
        known_hosts=trusted,
    )
    with pytest.raises(HostTrustError):
        adapter.discover(device(), DeviceCredentials(username="u", password="p"))


def test_projected_endpoint_lookup_failure_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    trusted = tmp_path / "persistent" / "known_hosts"
    trusted.parent.mkdir()
    trusted.write_text(f"192.0.2.20 ssh-ed25519 {host_key()}\n", encoding="ascii")
    trusted.chmod(0o600)
    checked: list[Path] = []

    def reject(_device: InventoryDevice, path: Path | None = None) -> str:
        assert path is not None
        checked.append(path)
        raise HostTrustError("trusted host key is absent")

    monkeypatch.setattr(junos_module, "verify_existing_host_trust", reject)
    adapter = JunosPyEZAdapter(
        device_factory=lambda **_kwargs: pytest.fail(
            "connection must not be attempted"
        ),
        known_hosts=trusted,
    )
    with pytest.raises(HostTrustError):
        adapter.discover(device(), DeviceCredentials(username="u", password="p"))
    assert checked[0] == trusted
    assert checked[1].name == "known_hosts"
    assert checked[1] != trusted
    assert not checked[1].exists()


def test_junos_collection_normalizes_committed_interface_state(monkeypatch) -> None:
    reply = ElementTree.fromstring(
        "<configuration><interfaces><interface><name>ge-0/0/1</name>"
        "<description>connected</description><disable/><unit><family><inet>"
        "<address><name>192.0.2.1/31</name></address></inet>"
        "<inet6><address><name>2001:db8::1/64</name></address></inet6>"
        "</family></unit>"
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
    assert observed.operational_status == "up"
    assert observed.ipv4_addresses == ("192.0.2.1/31",)
    assert observed.protected is True


def test_junos_collection_marks_missing_exact_interface(monkeypatch) -> None:
    monkeypatch.setattr(junos_module, "verify_existing_host_trust", lambda _d: "ok")
    operational = ElementTree.fromstring("<interface-information />")
    adapter = JunosPyEZAdapter(
        device_factory=lambda **_kwargs: FakeConnection(operational=operational)
    )
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
        self.exit_error: Exception | None = None
        self.enter_error: Exception | None = None
        self.check_calls = 0

    def __enter__(self):
        self.calls.append("enter")
        if self.enter_error is not None:
            raise self.enter_error
        return self

    def __exit__(self, *_args: object) -> None:
        self.calls.append("exit")
        if self.exit_error is not None:
            raise self.exit_error

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
        self.check_calls += 1
        if isinstance(self.check_result, Exception):
            raise self.check_result
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


def test_new_interface_stanza_diff_is_narrowly_accepted() -> None:
    connection = FakeConnection(candidate_reply())
    config = FakeConfig(connection, "exclusive")

    def diff():
        config.diff_calls += 1
        if config.diff_calls == 1:
            return None
        return (
            "[edit interfaces]\n"
            "+   ge-0/0/1 {\n"
            "+       description managed-by-network-change-delivery-platform;\n"
            "+   }"
        )

    config.diff = diff
    with JunosTransaction(
        connection, lambda *_a, **_k: config, plan().execution_artifact
    ) as transaction:
        prepared = transaction.prepare()
    assert prepared.diff_sha256.startswith("sha256:")


def test_operational_interface_without_config_still_exists(monkeypatch) -> None:
    monkeypatch.setattr(junos_module, "verify_existing_host_trust", lambda _d: "ok")
    observed = JunosPyEZAdapter(
        device_factory=lambda **_kwargs: FakeConnection()
    ).collect(device(), DeviceCredentials(username="u", password="p"), "ge-0/0/1")
    assert observed.exists is True
    assert observed.description is None
    assert observed.ipv4_addresses == ()
    assert observed.enabled is True


def test_config_only_interface_does_not_establish_physical_existence(
    monkeypatch,
) -> None:
    configured = ElementTree.fromstring(
        "<configuration><interfaces><interface><name>ge-0/0/9</name>"
        "<description>configured-only</description></interface></interfaces>"
        "</configuration>"
    )
    operational = ElementTree.fromstring("<interface-information />")
    monkeypatch.setattr(junos_module, "verify_existing_host_trust", lambda _d: "ok")
    observed = JunosPyEZAdapter(
        device_factory=lambda **_kwargs: FakeConnection(configured, operational)
    ).collect(device(), DeviceCredentials(username="u", password="p"), "ge-0/0/9")
    assert observed.exists is False
    assert observed.description is None


def test_namespaced_operational_state_normalizes_whitespace_and_admin_down(
    monkeypatch,
) -> None:
    operational = ElementTree.fromstring(
        '<rpc-reply xmlns="urn:junos"><interface-information>'
        "<physical-interface><name>  ge-0/0/1  </name>"
        "<admin-status> down </admin-status><oper-status> down </oper-status>"
        "</physical-interface><logical-interface><name>ge-0/0/1.0</name>"
        "</logical-interface></interface-information></rpc-reply>"
    )
    monkeypatch.setattr(junos_module, "verify_existing_host_trust", lambda _d: "ok")
    observed = JunosPyEZAdapter(
        device_factory=lambda **_kwargs: FakeConnection(operational=operational)
    ).collect(device(), DeviceCredentials(username="u", password="p"), "ge-0/0/1")
    assert observed.enabled is False
    assert observed.operational_status == "down"


@pytest.mark.parametrize("failure_point", ["connect", "rpc"])
def test_pyez_errors_are_bounded_without_secret_text(
    monkeypatch, failure_point
) -> None:
    secret_text = "user=lab-secret password=super-secret raw-rpc=<rpc-error/>"
    monkeypatch.setattr(junos_module, "verify_existing_host_trust", lambda _d: "ok")
    if failure_point == "connect":

        def factory(**_kwargs):
            raise RuntimeError(secret_text)
    else:

        def factory(**_kwargs):
            connection = FakeConnection()
            connection.rpc.get_interface_information = lambda **_k: (
                _ for _ in ()
            ).throw(RuntimeError(secret_text))
            return connection

    adapter = JunosPyEZAdapter(device_factory=factory)
    with pytest.raises(ProviderError) as caught:
        adapter.discover(device(), DeviceCredentials(username="u", password="p"))
    assert secret_text not in str(caught.value)
    assert secret_text not in repr(caught.value)


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


@pytest.mark.parametrize(
    "commit_result",
    [False, RpcTimeoutError(None, "commit", 30), True],
)
def test_post_attempt_unlock_failure_is_suppressed_and_phase_recorded(
    commit_result: object,
) -> None:
    connection = FakeConnection(candidate_reply())
    config = FakeConfig(connection, "exclusive")
    config.commit_result = commit_result
    config.exit_error = RuntimeError("username=secret raw unlock RPC")
    transaction = JunosTransaction(
        connection, lambda *_a, **_k: config, plan().execution_artifact
    )
    with transaction as active:
        active.prepare()
        result = active.commit_confirmed(5)
    assert transaction.close_failed is True
    assert result.disposition in {
        ExecutionDisposition.FAILED,
        ExecutionDisposition.AMBIGUOUS,
        ExecutionDisposition.SUCCEEDED,
    }
    assert config.rollback_calls == []


def test_precommit_device_close_failure_is_bounded(monkeypatch) -> None:
    raw = "user=secret password=secret raw device close"
    connection = FakeConnection(exit_error=RuntimeError(raw))
    monkeypatch.setattr(junos_module, "verify_existing_host_trust", lambda _d: "ok")
    adapter = JunosPyEZAdapter(device_factory=lambda **_kwargs: connection)
    with (
        pytest.raises(ProviderError) as caught,
        adapter.transaction(
            device(),
            DeviceCredentials(username="u", password="p"),
            plan().execution_artifact,
        ),
    ):
        pass
    assert raw not in str(caught.value)
    assert raw not in repr(caught.value)


@pytest.mark.parametrize(
    ("commit_result", "disposition"),
    [
        (False, ExecutionDisposition.FAILED),
        (RpcTimeoutError(None, "commit", 30), ExecutionDisposition.AMBIGUOUS),
        (True, ExecutionDisposition.SUCCEEDED),
    ],
)
def test_device_close_failure_preserves_commit_result(
    monkeypatch, commit_result: object, disposition: ExecutionDisposition
) -> None:
    raw = "username=secret password=secret raw NETCONF close"
    connection = FakeConnection(candidate_reply(), exit_error=RuntimeError(raw))
    config = FakeConfig(connection, "exclusive")
    config.commit_result = commit_result
    monkeypatch.setattr(junos_module, "verify_existing_host_trust", lambda _d: "ok")
    adapter = JunosPyEZAdapter(
        device_factory=lambda **_kwargs: connection,
        config_factory=lambda *_args, **_kwargs: config,
    )
    with adapter.transaction(
        device(),
        DeviceCredentials(username="u", password="p"),
        plan().execution_artifact,
    ) as transaction:
        transaction.prepare()
        result = transaction.commit_confirmed(5)
    assert result.disposition is disposition
    assert transaction.commit_result is result
    assert transaction.close_failed is True
    assert raw not in result.message
    assert (
        len(
            [
                call
                for call in config.calls
                if isinstance(call, tuple) and call[0] == "commit"
            ]
        )
        == 1
    )


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        ("enter", ExecutionDisposition.FAILED),
        ("rpc", ExecutionDisposition.FAILED),
        ("transport", ExecutionDisposition.AMBIGUOUS),
        ("unlock_after_success", ExecutionDisposition.SUCCEEDED),
        ("device_close_after_success", ExecutionDisposition.SUCCEEDED),
    ],
)
def test_confirmation_is_phase_aware_and_never_retried(
    monkeypatch, failure: str, expected: ExecutionDisposition
) -> None:
    raw = "user=secret password=secret raw confirmation RPC"
    connection = FakeConnection(
        exit_error=(
            RuntimeError(raw) if failure == "device_close_after_success" else None
        )
    )
    config = FakeConfig(connection, "exclusive")
    if failure == "enter":
        config.enter_error = RuntimeError(raw)
    elif failure == "rpc":
        config.check_result = RpcError(cmd=raw)
    elif failure == "transport":
        config.check_result = RpcTimeoutError(None, raw, 30)
    elif failure == "unlock_after_success":
        config.exit_error = RuntimeError(raw)
    monkeypatch.setattr(junos_module, "verify_existing_host_trust", lambda _d: "ok")
    adapter = JunosPyEZAdapter(
        device_factory=lambda **_kwargs: connection,
        config_factory=lambda *_args, **_kwargs: config,
    )
    result = adapter.confirm(device(), DeviceCredentials(username="u", password="p"))
    assert result.disposition is expected
    assert config.check_calls == (0 if failure == "enter" else 1)
    assert raw not in result.message
    assert raw not in repr(result)


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


def test_precommit_device_close_failure_yields_bounded_blocked_record(
    monkeypatch,
) -> None:
    raw = "user=secret password=secret raw precommit device close"
    connection = FakeConnection(candidate_reply("wrong"), exit_error=RuntimeError(raw))
    config = FakeConfig(connection, "exclusive")
    monkeypatch.setattr(junos_module, "verify_existing_host_trust", lambda _d: "ok")
    adapter = JunosPyEZAdapter(
        device_factory=lambda **_kwargs: connection,
        config_factory=lambda *_args, **_kwargs: config,
    )
    approved = plan()
    record = deploy_plan(
        approved,
        approved.digest,
        FakeInventory(),
        FakeSecrets(),
        FakeCollector(state()),
        adapter,
    )
    assert record.final_outcome is FinalOutcome.BLOCKED
    assert raw not in record.model_dump_json()
    assert not any(
        isinstance(call, tuple) and call[0] == "commit" for call in config.calls
    )


@pytest.mark.parametrize(
    ("commit_result", "outcome"),
    [
        (False, FinalOutcome.EXECUTION_FAILED),
        (RpcTimeoutError(None, "commit", 30), FinalOutcome.AMBIGUOUS),
        (True, FinalOutcome.AUTO_ROLLBACK_PENDING),
    ],
)
def test_device_close_failure_maps_to_honest_workflow_outcome(
    monkeypatch, commit_result: object, outcome: FinalOutcome
) -> None:
    raw = "user=secret password=secret raw postcommit device close"
    connection = FakeConnection(candidate_reply(), exit_error=RuntimeError(raw))
    config = FakeConfig(connection, "exclusive")
    config.commit_result = commit_result
    monkeypatch.setattr(junos_module, "verify_existing_host_trust", lambda _d: "ok")
    adapter = JunosPyEZAdapter(
        device_factory=lambda **_kwargs: connection,
        config_factory=lambda *_args, **_kwargs: config,
    )
    approved = plan()
    collector = FakeCollector(
        state(), state("managed-by-network-change-delivery-platform")
    )
    record = deploy_plan(
        approved,
        approved.digest,
        FakeInventory(),
        FakeSecrets(),
        collector,
        adapter,
    )
    assert record.final_outcome is outcome
    assert collector.calls == 1
    assert config.check_calls == 1
    assert raw not in record.model_dump_json()


class FakeTransaction:
    def __init__(self, commit: ExecutionResult, *, close_failed: bool = False) -> None:
        self.commit = commit
        self.close_failed = close_failed
        self.prepares = 0
        self.commits = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def prepare(self) -> object:
        self.prepares += 1
        return SimpleNamespace(diff_sha256="sha256:" + "a" * 64)

    def commit_confirmed(self, minutes: int) -> ExecutionResult:
        assert minutes == 5
        self.commits += 1
        return self.commit


class FakeJunosProvider:
    def __init__(
        self,
        commit: ExecutionResult,
        confirmation: ExecutionResult,
        *,
        close_failed: bool = False,
    ) -> None:
        self.tx = FakeTransaction(commit, close_failed=close_failed)
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
    close_failed: bool = False,
):
    provider = FakeJunosProvider(
        outcome_result(commit),
        outcome_result(confirmation),
        close_failed=close_failed,
    )
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
    assert record.candidate_diff_digest == "sha256:" + "a" * 64
    assert "[edit interfaces" not in record.model_dump_json()
    invalid_record = record.model_dump(mode="json")
    invalid_record["candidate_diff_digest"] = "raw candidate diff"
    with pytest.raises(ValidationError):
        type(record).model_validate(invalid_record)


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
    ("commit", "expected"),
    [
        (ExecutionDisposition.FAILED, FinalOutcome.EXECUTION_FAILED),
        (ExecutionDisposition.AMBIGUOUS, FinalOutcome.AMBIGUOUS),
        (ExecutionDisposition.SUCCEEDED, FinalOutcome.AUTO_ROLLBACK_PENDING),
    ],
)
def test_transaction_close_failure_preserves_known_commit_disposition(
    commit: ExecutionDisposition, expected: FinalOutcome
) -> None:
    record, provider, collector = run_deploy(
        state("managed-by-network-change-delivery-platform"),
        commit=commit,
        close_failed=True,
    )
    assert record.final_outcome is expected
    assert provider.tx.commits == 1
    assert provider.confirmations == 0
    assert collector.calls == 1


def test_precommit_exit_failure_is_bounded() -> None:
    connection = FakeConnection(candidate_reply("wrong"))
    config = FakeConfig(connection, "exclusive")
    config.exit_error = RuntimeError("password=secret raw unlock reply")
    transaction = JunosTransaction(
        connection, lambda *_a, **_k: config, plan().execution_artifact
    )
    with pytest.raises(ProviderError) as caught, transaction as active:
        active.prepare()
    assert "secret" not in str(caught.value)
    assert "secret" not in repr(caught.value)


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
