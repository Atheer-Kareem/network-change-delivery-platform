"""Secret-free typed SNMP provisioning and vendor artifact tests."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from xml.etree import ElementTree

import pytest
from lxml import etree
from pydantic import ValidationError

from network_change_delivery.ansible_adapter import (
    IDENTITY_TASK,
    SNMP_ENGINE_TASK,
    SNMP_EXECUTION_TASK,
    SNMP_GROUP_TASK,
    SNMP_USER_TASK,
    SNMP_VIEW_TASK,
    AnsibleRunnerCiscoAdapter,
    ProviderError,
)
from network_change_delivery.junos_adapter import JunosPyEZAdapter
from network_change_delivery.models import ExecutionDisposition, InventoryDevice
from network_change_delivery.secrets import DeviceCredentials
from network_change_delivery.snmp_credentials import (
    SnmpProvisioningCredentials,
    snmp_username,
)
from network_change_delivery.snmp_mib import APPROVED_DEVICE_VIEW_OIDS
from network_change_delivery.snmp_provisioning import (
    NCDP_SNMP_GROUP,
    NCDP_SNMP_VIEW,
    SnmpOwnedObjectState,
    SnmpOwnedStateDisposition,
    SnmpProvisioningError,
    SnmpV3InterfaceTelemetryIntent,
    build_snmp_provisioning_plan,
    cisco_preflight_commands,
    cisco_recovery_commands,
    junos_recovery_xml,
    junos_snmp_filter,
    parse_cisco_snmp_state,
    parse_junos_snmp_state,
    render_cisco_provisioning,
    render_junos_provisioning,
)
from network_change_delivery.snmp_telemetry import SnmpCredentialReference

AUTH = "auth-secret-sentinel-" + "A" * 27
PRIV = "privacy-secret-sentinel-" + "B" * 24


def credential(device_id: int = 1) -> SnmpCredentialReference:
    return SnmpCredentialReference(
        device=f"netbox:dcim.device:{device_id}",
        reference=f"snmpv3:netbox:dcim.device:{device_id}:generation:v1",
        auth_selector=f"device_{device_id}_v1",
    )


def intent(
    platform: str = "cisco_iosxe", device_id: int = 1
) -> SnmpV3InterfaceTelemetryIntent:
    return SnmpV3InterfaceTelemetryIntent(
        change_id=f"CHG-SNMP-{device_id}",
        target="core-02" if device_id == 1 else "edge-junos-01",
        device=f"netbox:dcim.device:{device_id}",
        platform=platform,
        generation="v1",
        username=snmp_username(device_id),
        credential=credential(device_id),
    )


def device(platform: str = "cisco_iosxe", device_id: int = 1) -> InventoryDevice:
    return InventoryDevice(
        name="core-02" if device_id == 1 else "edge-junos-01",
        host="192.0.2.10",
        port=22 if platform == "cisco_iosxe" else 830,
        platform=platform,
        expected_hostname="core-02" if device_id == 1 else "edge-junos-01",
        inventory_source="netbox",
        inventory_object_id=f"netbox:dcim.device:{device_id}",
    )


def absent(device_id: int = 1) -> SnmpOwnedObjectState:
    return SnmpOwnedObjectState(
        observed_hostname="core-02" if device_id == 1 else "edge-junos-01",
        local_engine_id_present=True,
        view="ABSENT",
        group="ABSENT",
        user="ABSENT",
        foreign_objects_present=True,
    )


def plan(platform: str = "cisco_iosxe", device_id: int = 1):
    return build_snmp_provisioning_plan(
        intent(platform, device_id),
        device(platform, device_id),
        absent(device_id),
        created_at=datetime(2026, 8, 29, tzinfo=UTC),
    )


def test_intent_and_plan_bind_exact_policy_without_secret_fields() -> None:
    value = plan()
    assert value.verify_digest()
    assert value.security_level == "authPriv"
    assert value.authentication_protocol == "SHA256"
    assert value.privacy_protocol == "AES128"
    assert value.view_name == NCDP_SNMP_VIEW
    assert value.group_name == NCDP_SNMP_GROUP
    assert frozenset(value.device_view_oids) == APPROVED_DEVICE_VIEW_OIDS
    serialized = value.model_dump_json()
    for forbidden in (
        AUTH,
        PRIV,
        "authentication_secret",
        "privacy_secret",
        "localized",
    ):
        assert forbidden not in serialized


@pytest.mark.parametrize("field", ["view", "group", "user"])
@pytest.mark.parametrize("disposition", ["EXACT_NCDP_STATE", "CONFLICT"])
def test_preexisting_owned_object_fails_closed(field: str, disposition: str) -> None:
    state = absent().model_copy(update={field: SnmpOwnedStateDisposition(disposition)})
    with pytest.raises((ValidationError, SnmpProvisioningError)):
        build_snmp_provisioning_plan(intent(), device(), state)


def test_foreign_objects_are_preserved_and_do_not_block_absent_owned_names() -> None:
    value = plan()
    assert value.preconditions.foreign_objects_present is True
    assert value.preconditions.safe_to_create is True


def test_cisco_artifact_is_exact_and_recovery_is_dependency_ordered() -> None:
    value = plan()
    secrets = SnmpProvisioningCredentials(snmp_username(1), AUTH, PRIV)
    artifact = render_cisco_provisioning(value, secrets)
    assert isinstance(artifact.payload, tuple)
    commands = artifact.payload
    view_commands = commands[:-2]
    assert len(view_commands) == len(APPROVED_DEVICE_VIEW_OIDS)
    assert {
        command.rsplit(" ", 1)[0].removeprefix(f"snmp-server view {NCDP_SNMP_VIEW} ")
        for command in view_commands
    } == APPROVED_DEVICE_VIEW_OIDS
    assert (
        commands[-2]
        == f"snmp-server group {NCDP_SNMP_GROUP} v3 priv read {NCDP_SNMP_VIEW}"
    )
    assert "auth sha-2 256" in commands[-1]
    assert "priv aes 128" in commands[-1]
    assert AUTH in commands[-1] and PRIV in commands[-1]
    assert AUTH not in repr(artifact) and PRIV not in repr(artifact)
    recovery = cisco_recovery_commands(value)
    assert recovery == (
        f"no snmp-server user {snmp_username(1)} {NCDP_SNMP_GROUP} v3",
        f"no snmp-server group {NCDP_SNMP_GROUP} v3 priv",
        *(
            f"no snmp-server view {NCDP_SNMP_VIEW} {oid} included"
            for oid in reversed(value.device_view_oids)
        ),
    )


def test_junos_artifact_uses_privacy_only_read_view_and_targeted_inverse() -> None:
    value = plan("junos", 2)
    secrets = SnmpProvisioningCredentials(snmp_username(2), AUTH, PRIV)
    artifact = render_junos_provisioning(value, secrets)
    assert isinstance(artifact.payload, str)
    xml = artifact.payload
    root = ElementTree.fromstring(xml)
    assert root.findtext("./snmp/v3/usm/local-engine/user/name") == snmp_username(2)
    assert (
        root.find("./snmp/v3/usm/local-engine/user/authentication-sha256") is not None
    )
    assert root.find("./snmp/v3/usm/local-engine/user/privacy-aes128") is not None
    level = root.find(
        "./snmp/v3/vacm/access/group/default-context-prefix/security-model/security-level"
    )
    assert level is not None
    assert level.findtext("name") == "privacy"
    assert level.findtext("read-view") == NCDP_SNMP_VIEW
    assert level.find("write-view") is None and level.find("notify-view") is None
    assert AUTH not in repr(artifact) and PRIV not in repr(artifact)
    recovery = ElementTree.fromstring(junos_recovery_xml(value))
    deleted = [
        element for element in recovery.iter() if element.get("delete") == "delete"
    ]
    assert len(deleted) == 4


def test_wrong_runtime_principal_is_rejected_before_rendering() -> None:
    with pytest.raises(SnmpProvisioningError, match="runtime identity"):
        render_cisco_provisioning(
            plan(), SnmpProvisioningCredentials("other", AUTH, PRIV)
        )


def test_username_generation_and_oid_expansion_are_fail_closed() -> None:
    values = intent().model_dump()
    values["username"] = "wrong"
    with pytest.raises(ValidationError):
        SnmpV3InterfaceTelemetryIntent.model_validate(values)
    values = intent().model_dump()
    values["device_view_oids"] = (*values["device_view_oids"], "1.3.6.1.2.1.999")
    with pytest.raises((ValidationError, ValueError)):
        SnmpV3InterfaceTelemetryIntent.model_validate(values)


def test_cisco_targeted_preflight_normalizes_exact_or_conflicting_owned_state() -> None:
    value = plan()
    assert cisco_preflight_commands(value) == (
        "show snmp engineID",
        "show snmp view",
        "show snmp group",
        f"show snmp user {snmp_username(1)}",
    )
    view = "\n".join(
        f"{NCDP_SNMP_VIEW} {oid} - included nonvolatile active"
        for oid in value.device_view_oids
    )
    state = parse_cisco_snmp_state(
        value,
        observed_hostname="core-02",
        engine_output="Local SNMP engineID: 8000000903ABCDEF",
        view_output=view,
        group_output=(
            f"groupname: {NCDP_SNMP_GROUP} security model:v3 priv\n"
            f"readview : {NCDP_SNMP_VIEW} writeview: <no writeview specified>\n"
            "notifyview: <no notifyview specified>\n"
        ),
        user_output=(
            f"User name: {snmp_username(1)}\nAuthentication Protocol: SHA-2 256\n"
            f"Privacy Protocol: AES128\nGroup-name: {NCDP_SNMP_GROUP}\n"
        ),
    )
    assert state.view is SnmpOwnedStateDisposition.EXACT_NCDP_STATE
    assert state.group is SnmpOwnedStateDisposition.EXACT_NCDP_STATE
    assert state.user is SnmpOwnedStateDisposition.EXACT_NCDP_STATE
    symbolic_names = {
        "1.3.6.1.2.1.1.3": "SNMPv2-MIB::sysUpTime",
        "1.3.6.1.2.1.2.1": "IF-MIB::ifNumber",
        "1.3.6.1.2.1.31.1.5": "IF-MIB::ifTableLastChange",
        "1.3.6.1.2.1.2.2.1.1": "IF-MIB::ifIndex",
        "1.3.6.1.2.1.2.2.1.7": "IF-MIB::ifAdminStatus",
        "1.3.6.1.2.1.2.2.1.8": "IF-MIB::ifOperStatus",
        "1.3.6.1.2.1.2.2.1.13": "IF-MIB::ifInDiscards",
        "1.3.6.1.2.1.2.2.1.14": "IF-MIB::ifInErrors",
        "1.3.6.1.2.1.2.2.1.19": "IF-MIB::ifOutDiscards",
        "1.3.6.1.2.1.2.2.1.20": "IF-MIB::ifOutErrors",
        "1.3.6.1.2.1.31.1.1.1.1": "IF-MIB::ifName",
        "1.3.6.1.2.1.31.1.1.1.6": "IF-MIB::ifHCInOctets",
        "1.3.6.1.2.1.31.1.1.1.10": "IF-MIB::ifHCOutOctets",
        "1.3.6.1.2.1.31.1.1.1.15": "IF-MIB::ifHighSpeed",
        "1.3.6.1.2.1.31.1.1.1.19": "IF-MIB::ifCounterDiscontinuityTime",
    }
    symbolic_view = "\n".join(
        f"{NCDP_SNMP_VIEW} {symbolic_names[oid]} - included nonvolatile active"
        for oid in value.device_view_oids
    )
    symbolic_state = parse_cisco_snmp_state(
        value,
        observed_hostname="core-02",
        engine_output="Local SNMP engineID: value",
        view_output=symbolic_view,
        group_output=(
            f"groupname: {NCDP_SNMP_GROUP} security model:v3 priv\n"
            f"readview : {NCDP_SNMP_VIEW} writeview: <no writeview specified>\n"
            "notifyview: <no notifyview specified>\n"
        ),
        user_output=(
            f"User name: {snmp_username(1)}\nAuthentication Protocol: SHA-2 256\n"
            f"Privacy Protocol: AES128\nGroup-name: {NCDP_SNMP_GROUP}\n"
        ),
    )
    assert symbolic_state.view is SnmpOwnedStateDisposition.EXACT_NCDP_STATE
    conflict = parse_cisco_snmp_state(
        value,
        observed_hostname="core-02",
        engine_output="Local SNMP engineID: value",
        view_output=view + f"\n{NCDP_SNMP_VIEW} 1.3.6.1.4.1 - included",
        group_output="",
        user_output="",
    )
    assert conflict.view is SnmpOwnedStateDisposition.CONFLICT
    assert conflict.group is SnmpOwnedStateDisposition.ABSENT
    assert conflict.user is SnmpOwnedStateDisposition.ABSENT


def test_cisco_disabled_agent_is_safe_bootstrap_state() -> None:
    value = intent()
    state = parse_cisco_snmp_state(
        value,
        observed_hostname="core-02",
        engine_output="%SNMP agent not enabled",
        view_output="%SNMP agent not enabled",
        group_output="%SNMP agent not enabled",
        user_output="%SNMP agent not enabled",
    )
    assert state.local_engine_id_present is False
    assert state.safe_to_create_for("cisco_iosxe") is True
    assert state.safe_to_create_for("junos") is False
    created = build_snmp_provisioning_plan(value, device(), state)
    assert created.preconditions.local_engine_id_present is False


@pytest.mark.parametrize(
    "engine,view,group,user",
    [
        (
            "",
            "%SNMP agent not enabled",
            "%SNMP agent not enabled",
            "%SNMP agent not enabled",
        ),
        (
            "%SNMP agent unavailable",
            "%SNMP agent not enabled",
            "%SNMP agent not enabled",
            "%SNMP agent not enabled",
        ),
        (
            "%SNMP agent not enabled",
            "% Invalid input",
            "%SNMP agent not enabled",
            "%SNMP agent not enabled",
        ),
    ],
)
def test_cisco_unknown_or_error_disabled_state_fails_closed(
    engine: str, view: str, group: str, user: str
) -> None:
    with pytest.raises(SnmpProvisioningError):
        parse_cisco_snmp_state(
            intent(),
            observed_hostname="core-02",
            engine_output=engine,
            view_output=view,
            group_output=group,
            user_output=user,
        )


def test_junos_targeted_filter_and_parser_drop_localized_secret_bytes() -> None:
    value = plan("junos", 2)
    filter_root = ElementTree.fromstring(junos_snmp_filter(value))
    assert filter_root.find("./snmp/view/name").text == NCDP_SNMP_VIEW
    artifact = render_junos_provisioning(
        value, SnmpProvisioningCredentials(snmp_username(2), AUTH, PRIV)
    )
    assert isinstance(artifact.payload, str)
    root = ElementTree.fromstring(artifact.payload)
    authentication = root.find("./snmp/v3/usm/local-engine/user/authentication-sha256")
    privacy = root.find("./snmp/v3/usm/local-engine/user/privacy-aes128")
    assert authentication is not None and privacy is not None
    password = authentication.find("authentication-password")
    privacy_password = privacy.find("privacy-password")
    assert password is not None and privacy_password is not None
    password.tag = "authentication-key"
    password.text = "localized-auth-sentinel"
    privacy_password.tag = "privacy-key"
    privacy_password.text = "localized-privacy-sentinel"
    state = parse_junos_snmp_state(
        value,
        observed_hostname="edge-junos-01",
        local_engine_id_present=True,
        configuration_xml=ElementTree.tostring(root, encoding="unicode"),
    )
    assert state.view is SnmpOwnedStateDisposition.EXACT_NCDP_STATE
    assert state.group is SnmpOwnedStateDisposition.EXACT_NCDP_STATE
    assert state.user is SnmpOwnedStateDisposition.EXACT_NCDP_STATE
    serialized = state.model_dump_json()
    assert "localized-auth-sentinel" not in serialized
    assert "localized-privacy-sentinel" not in serialized


def test_cisco_adapter_executes_exact_artifact_once_through_no_log_playbook(
    monkeypatch,
) -> None:
    value = plan()
    artifact = render_cisco_provisioning(
        value, SnmpProvisioningCredentials(snmp_username(1), AUTH, PRIV)
    )
    adapter = AnsibleRunnerCiscoAdapter()
    calls: list[tuple[str, dict[str, object]]] = []

    def run(_device, _credentials, playbook, *, extravars=None):
        calls.append((playbook, extravars))
        return SimpleNamespace(status="successful", rc=0), {
            SNMP_EXECUTION_TASK: {"_ncdp_event": "runner_on_ok"}
        }

    monkeypatch.setattr(adapter, "_run", run)
    result = adapter.execute_snmp(
        device(), DeviceCredentials("ssh-user", "ssh-secret"), artifact
    )
    assert result.disposition is ExecutionDisposition.SUCCEEDED
    assert calls == [
        (
            "apply_snmp_provisioning.yml",
            {"ncdp_snmp_commands": list(artifact.payload)},
        )
    ]
    playbook = Path("ansible/apply_snmp_provisioning.yml").read_text()
    assert "no_log: true" in playbook
    assert "save_when: never" in playbook


def test_cisco_preflight_reconstructs_four_single_command_results(monkeypatch) -> None:
    value = plan()
    adapter = AnsibleRunnerCiscoAdapter()
    view = "\n".join(
        f"{NCDP_SNMP_VIEW} {oid} - included" for oid in value.device_view_oids
    )
    results = {
        SNMP_ENGINE_TASK: {"stdout": ["%SNMP agent not enabled"]},
        SNMP_VIEW_TASK: {"stdout": ["%SNMP agent not enabled"]},
        SNMP_GROUP_TASK: {"stdout": ["%SNMP agent not enabled"]},
        SNMP_USER_TASK: {"stdout": ["%SNMP agent not enabled"]},
    }
    results[SNMP_ENGINE_TASK] = {"stdout": ["Local SNMP engineID: value"]}
    results[SNMP_VIEW_TASK] = {"stdout": [view]}
    results[SNMP_GROUP_TASK] = {
        "stdout": [
            f"groupname: {NCDP_SNMP_GROUP} security model:v3 priv\n"
            f"readview : {NCDP_SNMP_VIEW} writeview: <no writeview specified>\n"
            "notifyview: <no notifyview specified>"
        ]
    }
    results[SNMP_USER_TASK] = {
        "stdout": [
            f"User name: {snmp_username(1)}\nAuthentication Protocol: SHA-2 256\n"
            f"Privacy Protocol: AES128\nGroup-name: {NCDP_SNMP_GROUP}"
        ]
    }

    def run(*_args, **_kwargs):
        return SimpleNamespace(status="successful", rc=0), {
            IDENTITY_TASK: {"ansible_facts": {"ansible_net_hostname": "core-02"}},
            **results,
        }

    monkeypatch.setattr(adapter, "_run", run)
    state = adapter.snmp_preflight(device(), DeviceCredentials("u", "p"), value)
    assert state.view is SnmpOwnedStateDisposition.EXACT_NCDP_STATE
    assert state.group is SnmpOwnedStateDisposition.EXACT_NCDP_STATE
    assert state.user is SnmpOwnedStateDisposition.EXACT_NCDP_STATE
    playbook = Path("ansible/inspect_snmp_provisioning.yml").read_text()
    assert playbook.count("cisco.ios.ios_command:") == 4
    assert "ncdp_snmp_disabled_wrapper" in playbook
    assert r"\\r\\\\n%SNMP agent not enabled" in playbook
    assert "is search('%SNMP agent not enabled')" not in playbook


def test_cisco_preflight_rejects_missing_bounded_task(monkeypatch) -> None:
    value = plan()
    adapter = AnsibleRunnerCiscoAdapter()

    def run(*_args, **_kwargs):
        return SimpleNamespace(status="successful", rc=0), {
            IDENTITY_TASK: {"ansible_facts": {"ansible_net_hostname": "core-02"}}
        }

    monkeypatch.setattr(adapter, "_run", run)
    with pytest.raises(ProviderError):
        adapter.snmp_preflight(device(), DeviceCredentials("u", "p"), value)


def test_cisco_preflight_normalizes_wrapped_disabled_failure(monkeypatch) -> None:
    value = plan()
    adapter = AnsibleRunnerCiscoAdapter()
    wrapped = b"show snmp engineID\r\n%SNMP agent not enabled\r\ncore-02#"

    def run(*_args, **_kwargs):
        return SimpleNamespace(status="successful", rc=0), {
            IDENTITY_TASK: {"ansible_facts": {"ansible_net_hostname": "core-02"}},
            **{
                task: {"msg": wrapped, "_ncdp_event": "runner_on_failed"}
                for task in (
                    SNMP_ENGINE_TASK,
                    SNMP_VIEW_TASK,
                    SNMP_GROUP_TASK,
                    SNMP_USER_TASK,
                )
            },
        }

    monkeypatch.setattr(adapter, "_run", run)
    state = adapter.snmp_preflight(device(), DeviceCredentials("u", "p"), value)
    assert state.local_engine_id_present is False
    assert state.safe_to_create_for("cisco_iosxe") is True


def test_cisco_preflight_normalizes_stringified_escaped_runner_wrapper(
    monkeypatch,
) -> None:
    value = plan()
    adapter = AnsibleRunnerCiscoAdapter()
    wrapped = "b'show snmp engineID\\r\\n%SNMP agent not enabled\\r\\ncore-02#'"

    def run(*_args, **_kwargs):
        return SimpleNamespace(status="successful", rc=0), {
            IDENTITY_TASK: {"ansible_facts": {"ansible_net_hostname": "core-02"}},
            **{
                task: {"msg": wrapped, "_ncdp_event": "runner_on_failed"}
                for task in (
                    SNMP_ENGINE_TASK,
                    SNMP_VIEW_TASK,
                    SNMP_GROUP_TASK,
                    SNMP_USER_TASK,
                )
            },
        }

    monkeypatch.setattr(adapter, "_run", run)
    state = adapter.snmp_preflight(device(), DeviceCredentials("u", "p"), value)
    assert state.local_engine_id_present is False


def test_cisco_preflight_rejects_phrase_with_unrelated_failure(monkeypatch) -> None:
    value = plan()
    adapter = AnsibleRunnerCiscoAdapter()
    wrapped = b"fatal timeout: %SNMP agent not enabled"

    def run(*_args, **_kwargs):
        return SimpleNamespace(status="successful", rc=0), {
            IDENTITY_TASK: {"ansible_facts": {"ansible_net_hostname": "core-02"}},
            SNMP_ENGINE_TASK: {"msg": wrapped, "_ncdp_event": "runner_on_failed"},
        }

    monkeypatch.setattr(adapter, "_run", run)
    with pytest.raises(ProviderError):
        adapter.snmp_preflight(device(), DeviceCredentials("u", "p"), value)


@pytest.mark.parametrize(
    "prefix", ["timeout", "timed out", "authentication failure", "ssh failure"]
)
def test_cisco_preflight_rejects_failed_escaped_wrapper(
    monkeypatch, prefix: str
) -> None:
    value = plan()
    adapter = AnsibleRunnerCiscoAdapter()
    wrapped = f"b'{prefix}\\r\\n%SNMP agent not enabled\\r\\ncore-02#'"

    def run(*_args, **_kwargs):
        return SimpleNamespace(status="successful", rc=0), {
            IDENTITY_TASK: {"ansible_facts": {"ansible_net_hostname": "core-02"}},
            SNMP_ENGINE_TASK: {"msg": wrapped, "_ncdp_event": "runner_on_failed"},
        }

    monkeypatch.setattr(adapter, "_run", run)
    with pytest.raises(ProviderError):
        adapter.snmp_preflight(device(), DeviceCredentials("u", "p"), value)


def test_junos_adapter_loads_checks_and_commits_confirmed_exactly_once(
    monkeypatch,
) -> None:
    value = plan("junos", 2)
    artifact = render_junos_provisioning(
        value, SnmpProvisioningCredentials(snmp_username(2), AUTH, PRIV)
    )
    calls: list[object] = []

    class Config:
        def __enter__(self):
            calls.append("enter-exclusive")
            return self

        def __exit__(self, *_args):
            calls.append("exit-exclusive")

        def diff(self):
            return None

        def load(self, payload, **kwargs):
            calls.append(("load", payload, kwargs["format"], kwargs["merge"]))

        def commit_check(self):
            calls.append("commit-check")
            return True

        def commit(self, *, confirm):
            calls.append(("commit", confirm))
            return True

    connection = SimpleNamespace(
        facts={"hostname": "edge-junos-01"},
        rpc=SimpleNamespace(
            get_config=lambda **_kwargs: etree.fromstring(artifact.payload.encode())
        ),
    )
    adapter = JunosPyEZAdapter(config_factory=lambda *_args, **_kwargs: Config())

    @contextmanager
    def session(_device, _credentials):
        yield connection

    monkeypatch.setattr(adapter, "_session", session)
    result = adapter.execute_snmp_confirmed(
        device("junos", 2),
        DeviceCredentials("netconf-user", "netconf-secret"),
        artifact,
        5,
    )
    assert result.disposition is ExecutionDisposition.SUCCEEDED
    assert calls.count(("commit", 5)) == 1
    assert calls.count("commit-check") == 1
    assert calls[0] == "enter-exclusive"
    assert calls[-1] == "exit-exclusive"
