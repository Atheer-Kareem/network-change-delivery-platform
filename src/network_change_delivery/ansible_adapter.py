"""Narrow Ansible Runner adapter for Cisco IOS XE collection and execution."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import stat
import subprocess
import tempfile
from collections.abc import Mapping
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal

import ansible_runner
import yaml

from network_change_delivery.models import (
    CiscoConfigArtifact,
    ExecutionDisposition,
    ExecutionResult,
    InterfaceState,
    InventoryDevice,
)
from network_change_delivery.read_only_target import (
    ConnectionTarget,
    ReadOnlyConnectionTarget,
)
from network_change_delivery.secrets import DeviceCredentials
from network_change_delivery.snmp_provisioning import (
    SnmpOwnedObjectState,
    SnmpPreflightSubject,
    cisco_preflight_commands,
    parse_cisco_snmp_state,
)

IDENTITY_TASK = "NCDP collect identity"
INTERFACES_TASK = "NCDP collect interfaces"
L3_INTERFACES_TASK = "NCDP collect layer 3 interfaces"
OSPF_READ_TASK = "NCDP inspect exact OSPF configuration"
VLAN_READ_TASK = "NCDP inspect exact VLAN service configuration"
ACL_READ_TASK = "NCDP inspect exact ACL security configuration"
EXECUTION_TASK = "NCDP apply exact approved artifact"
SNMP_PREFLIGHT_TASK = "NCDP inspect exact SNMP owned names"
SNMP_ENGINE_TASK = "NCDP inspect SNMP engine"
SNMP_VIEW_TASK = "NCDP inspect SNMP view"
SNMP_GROUP_TASK = "NCDP inspect SNMP group"
SNMP_USER_TASK = "NCDP inspect SNMP user"


class VlanReadScope(StrEnum):
    """Closed B4-3 Cisco VLAN read-only command scopes."""

    CORE = "core_vlan_service"
    ACCESS = "access_vlan_service"


VLAN_READ_COMMANDS: Mapping[VlanReadScope, tuple[str, ...]] = MappingProxyType(
    {
        VlanReadScope.CORE: (
            "show running-config interface GigabitEthernet3",
            "show running-config | section ^interface GigabitEthernet3\\.",
            "show running-config | section ^router ospf",
        ),
        VlanReadScope.ACCESS: (
            "show vlan brief",
            "show interfaces GigabitEthernet0/1 switchport",
            "show interfaces GigabitEthernet0/2 switchport",
            "show interfaces GigabitEthernet0/3 switchport",
            "show running-config interface GigabitEthernet0/1",
            "show running-config interface GigabitEthernet0/2",
            "show running-config interface GigabitEthernet0/3",
            "show running-config | section ^interface Vlan",
        ),
    }
)


class AclReadScope(StrEnum):
    """Closed B4-4 Cisco ACL read-only command scope."""

    SECURITY_POLICY = "users_servers_security_policy"


ACL_READ_COMMANDS: Mapping[AclReadScope, tuple[str, ...]] = MappingProxyType(
    {
        AclReadScope.SECURITY_POLICY: (
            "show running-config | include ^ip access-list extended NCDP-",
            "show running-config | section ^ip access-list extended "
            "NCDP-SERVERS-PROTECT-OUT",
            "show running-config | section ^interface GigabitEthernet3\\.",
            "show running-config | include ^interface|ip access-group "
            "NCDP-SERVERS-PROTECT-OUT",
        )
    }
)


class ProviderError(RuntimeError):
    """Bounded provider failure that never embeds raw Runner output."""


class ProviderReadinessError(ProviderError):
    """Bounded transient read failure eligible for readiness retry."""


class HostTrustError(ProviderError):
    """Raised when the candidate lacks an existing trusted host-key entry."""


class DeploymentRuntimeError(ProviderError):
    """Fixed non-secret deployment-runtime prerequisite failure."""

    def __init__(self) -> None:
        super().__init__("deployment Ansible runtime prerequisites unavailable")


_DISABLED_SNMP_AGENT = "%SNMP agent not enabled"


def _normalize_disabled_snmp_agent(value: object) -> str | None:
    """Recognize only the bounded IOS XE disabled-agent result shapes."""
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    if not isinstance(value, str):
        return None
    lowered = value.casefold()
    if any(
        marker in lowered
        for marker in (
            "traceback",
            "exception",
            "timeout",
            "timed out",
            "unreachable",
            "authentication failure",
            "ssh failure",
        )
    ):
        return None
    if re.fullmatch(r"b'[^%]*\\r\\n%SNMP agent not enabled\\r\\n[^%]*'", value):
        return _DISABLED_SNMP_AGENT
    lines = value.splitlines()
    if any(line.strip() == _DISABLED_SNMP_AGENT for line in lines) and not any(
        line.lstrip().startswith("%") and line.strip() != _DISABLED_SNMP_AGENT
        for line in lines
    ):
        return _DISABLED_SNMP_AGENT
    return None


def _bounded_read_failure(result: object) -> str:
    """Classify a Runner task failure without exposing its provider message."""
    values = result if isinstance(result, dict) else {}
    message = "\n".join(
        str(values.get(key, "")).lower() for key in ("msg", "exception")
    )
    categories = (
        (("connection type", "not valid"), "Cisco connection type was rejected"),
        (("ssh connection failed",), "Cisco SSH session failed"),
        (("authentication",), "Cisco authentication was rejected"),
        (("permission denied",), "Cisco authentication was rejected"),
        (("host key",), "Cisco host trust was rejected"),
        (("privilege",), "Cisco privileged read access was rejected"),
        (("enable",), "Cisco privileged read access was rejected"),
        (("terminal",), "Cisco terminal initialization failed"),
        (("timeout",), "Cisco read-only command timed out"),
        (("timed out",), "Cisco read-only command timed out"),
        (("couldn't resolve module",), "Cisco collection runtime was unavailable"),
        (("module", "not found"), "Cisco collection runtime was unavailable"),
        (("failed to import",), "Cisco collection runtime import failed"),
        (("modulenotfounderror",), "Cisco collection runtime import failed"),
        (("importerror",), "Cisco collection runtime import failed"),
        (("required", "library"), "Cisco collection runtime import failed"),
        (("ansibleconnectionfailure",), "Cisco SSH session failed"),
        (("connectionreseterror",), "Cisco SSH session failed"),
        (("unsupported parameters",), "Cisco collection parameters were rejected"),
        (("network os", "not supported"), "Cisco network OS plugin was rejected"),
        (
            ("automatically determine", "network os"),
            "Cisco network OS detection failed",
        ),
        (("module failure",), "Cisco facts module execution failed"),
        (("json", "response"), "Cisco facts response decoding failed"),
        (("invalid input",), "Cisco rejected a read-only CLI command"),
    )
    for needles, classification in categories:
        if all(needle in message for needle in needles):
            return classification
    return "Cisco read-only task failed"


SYSTEM_ANSIBLE_COLLECTIONS = Path("/opt/ansible/collections")
_COLLECTION_NAME = re.compile(r"[a-z0-9_]+\.[a-z0-9_]+")
_EXACT_COLLECTION_VERSION = re.compile(r"[0-9]+(?:\.[0-9]+){2}")


def deployment_repository_root(
    repository_root: Path | None = None,
    environment: Mapping[str, str] | None = None,
) -> Path:
    """Resolve the adapter and verifier repository root identically."""
    if repository_root is not None:
        return repository_root
    values = environment if environment is not None else os.environ
    configured = values.get("NCDP_PROJECT_ROOT")
    return Path(configured) if configured else Path.cwd()


def effective_ansible_collection_paths(
    repository_root: Path,
    environment: Mapping[str, str] | None = None,
) -> tuple[Path, ...]:
    """Return one validated effective Ansible collection search path."""
    values = environment if environment is not None else os.environ
    configured = values.get("ANSIBLE_COLLECTIONS_PATH")
    if configured is None:
        return (
            repository_root / ".ansible" / "collections",
            SYSTEM_ANSIBLE_COLLECTIONS,
        )
    entries = configured.split(os.pathsep)
    paths = tuple(Path(entry) for entry in entries)
    if (
        not configured
        or any(
            not entry or not path.is_absolute()
            for entry, path in zip(entries, paths, strict=True)
        )
        or len(set(paths)) != len(paths)
    ):
        raise DeploymentRuntimeError
    return paths


def effective_ansible_collection_path(
    repository_root: Path,
    environment: Mapping[str, str] | None = None,
) -> str:
    """Render the shared collection paths for Ansible Runner."""
    return os.pathsep.join(
        str(path)
        for path in effective_ansible_collection_paths(repository_root, environment)
    )


def _required_ansible_collections(repository_root: Path) -> tuple[tuple[str, str], ...]:
    requirements = repository_root / "ansible" / "requirements.yml"
    try:
        if requirements.is_symlink() or not stat.S_ISREG(requirements.stat().st_mode):
            raise DeploymentRuntimeError
        payload = yaml.safe_load(requirements.read_text(encoding="utf-8"))
        collections = payload["collections"]
        if not isinstance(payload, dict) or set(payload) != {"collections"}:
            raise DeploymentRuntimeError
        if not isinstance(collections, list) or not collections:
            raise DeploymentRuntimeError
        required: list[tuple[str, str]] = []
        for collection in collections:
            if not isinstance(collection, dict) or set(collection) != {
                "name",
                "version",
            }:
                raise DeploymentRuntimeError
            name = collection["name"]
            version = collection["version"]
            if (
                not isinstance(name, str)
                or _COLLECTION_NAME.fullmatch(name) is None
                or not isinstance(version, str)
                or _EXACT_COLLECTION_VERSION.fullmatch(version) is None
            ):
                raise DeploymentRuntimeError
            required.append((name, version))
        if len({name for name, _version in required}) != len(required):
            raise DeploymentRuntimeError
        return tuple(required)
    except (DeploymentRuntimeError, KeyError, OSError, TypeError, yaml.YAMLError):
        raise DeploymentRuntimeError from None


def verify_deployment_ansible_runtime(
    repository_root: Path | None = None,
    environment: Mapping[str, str] | None = None,
) -> tuple[tuple[str, str], ...]:
    """Verify exact repository-pinned collections without network or installation."""
    try:
        root = deployment_repository_root(repository_root, environment)
        paths = effective_ansible_collection_paths(root, environment)
        required = _required_ansible_collections(root)
        for name, expected_version in required:
            namespace, collection = name.split(".")
            manifests = [
                path / "ansible_collections" / namespace / collection / "MANIFEST.json"
                for path in paths
            ]
            installed = [manifest for manifest in manifests if manifest.exists()]
            if len(installed) != 1:
                raise DeploymentRuntimeError
            manifest = installed[0]
            if manifest.is_symlink() or not stat.S_ISREG(manifest.stat().st_mode):
                raise DeploymentRuntimeError
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            information = payload["collection_info"]
            if (
                not isinstance(payload, dict)
                or not isinstance(information, dict)
                or information.get("namespace") != namespace
                or information.get("name") != collection
                or information.get("version") != expected_version
            ):
                raise DeploymentRuntimeError
        return required
    except (
        DeploymentRuntimeError,
        json.JSONDecodeError,
        KeyError,
        OSError,
        TypeError,
        ValueError,
    ):
        raise DeploymentRuntimeError from None


def _known_hosts_query(device: ReadOnlyConnectionTarget) -> str:
    return device.host if device.port == 22 else f"[{device.host}]:{device.port}"


def _known_hosts_path() -> Path:
    return Path.home() / ".ssh" / "known_hosts"


def _fingerprint_from_line(line: str) -> str | None:
    fields = line.split()
    if len(fields) < 3 or fields[0].startswith("#"):
        return None
    try:
        key = base64.b64decode(fields[2], validate=True)
    except ValueError:
        return None
    digest = base64.b64encode(hashlib.sha256(key).digest()).decode().rstrip("=")
    return f"SHA256:{digest}"


def verify_existing_host_trust(
    device: ReadOnlyConnectionTarget, known_hosts: Path | None = None
) -> str:
    """Confirm a known_hosts entry exists without discovering or trusting a key."""
    known_hosts = known_hosts or _known_hosts_path()
    if not known_hosts.is_file():
        raise HostTrustError("known_hosts file is absent; establish trust separately")
    completed = subprocess.run(
        ["ssh-keygen", "-F", _known_hosts_query(device), "-f", str(known_hosts)],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0 or not completed.stdout.strip():
        raise HostTrustError("trusted host key is absent; establish trust separately")
    fingerprints = {
        fingerprint
        for line in completed.stdout.splitlines()
        if (fingerprint := _fingerprint_from_line(line)) is not None
    }
    return ", ".join(sorted(fingerprints)) or "trusted entry present (hashed host)"


class AnsibleRunnerCiscoAdapter:
    """Collect structured state and apply exact artifacts through Runner."""

    def __init__(
        self,
        repository_root: Path | None = None,
        *,
        known_hosts: Path | None = None,
    ) -> None:
        self._root = deployment_repository_root(repository_root)
        self._known_hosts = known_hosts

    @staticmethod
    def _inventory(
        device: ReadOnlyConnectionTarget,
        *,
        ssh_type: Literal["paramiko"] = "paramiko",
    ) -> dict[str, Any]:
        return {
            "all": {
                "hosts": {
                    "ncdp_target": {
                        "ansible_host": device.host,
                        "ansible_port": device.port,
                        "ansible_connection": "ansible.netcommon.network_cli",
                        "ansible_network_os": "cisco.ios.ios",
                        "ansible_network_cli_ssh_type": ssh_type,
                    }
                }
            }
        }

    def _run(
        self,
        device: ReadOnlyConnectionTarget,
        credentials: DeviceCredentials,
        playbook: str,
        *,
        extravars: dict[str, Any] | None = None,
        ssh_type: Literal["paramiko"] = "paramiko",
        profile_bound: bool = False,
    ) -> tuple[object, dict[str, dict[str, Any]]]:
        if self._known_hosts is None:
            verify_existing_host_trust(device)
        else:
            verify_existing_host_trust(device, self._known_hosts)
        selected: dict[str, dict[str, Any]] = {}
        inventory = self._inventory(device, ssh_type=ssh_type)

        def handle_event(event: dict[str, Any]) -> None:
            event_kind = event.get("event")
            if event_kind not in {
                "runner_on_ok",
                "runner_on_failed",
                "runner_on_unreachable",
            }:
                return
            data = event.get("event_data", {})
            task = data.get("task")
            if task in {
                IDENTITY_TASK,
                INTERFACES_TASK,
                L3_INTERFACES_TASK,
                OSPF_READ_TASK,
                VLAN_READ_TASK,
                ACL_READ_TASK,
                EXECUTION_TASK,
                SNMP_PREFLIGHT_TASK,
                SNMP_ENGINE_TASK,
                SNMP_VIEW_TASK,
                SNMP_GROUP_TASK,
                SNMP_USER_TASK,
            }:
                result = data.get("res", {})
                if isinstance(result, dict):
                    selected[str(task)] = {**result, "_ncdp_event": event_kind}

        with tempfile.TemporaryDirectory(prefix="ncdp-runner-") as directory:
            private_data = Path(directory)
            private_data.chmod(0o700)
            runner_home: Path | None = None
            if self._known_hosts is not None:
                runner_home = private_data / "home"
                ssh_directory = runner_home / ".ssh"
                ssh_directory.mkdir(parents=True, mode=0o700)
                projected_known_hosts = ssh_directory / "known_hosts"
                projected_known_hosts.write_bytes(self._known_hosts.read_bytes())
                projected_known_hosts.chmod(0o600)
            result = ansible_runner.run(
                private_data_dir=str(private_data),
                project_dir=str(self._root / "ansible"),
                artifact_dir=str(private_data / "artifacts"),
                playbook=playbook,
                inventory=inventory,
                extravars=extravars or {},
                envvars={
                    "ANSIBLE_CONFIG": str(self._root / "ansible.cfg"),
                    "ANSIBLE_COLLECTIONS_PATH": effective_ansible_collection_path(
                        self._root
                    ),
                    "ANSIBLE_HOST_KEY_CHECKING": "True",
                    "ANSIBLE_PERSISTENT_CONTROL_PATH_DIR": str(private_data / "pc"),
                    "NCDP_DEVICE_USERNAME": credentials.username,
                    "NCDP_DEVICE_PASSWORD": credentials.password,
                    **(
                        {
                            "ANSIBLE_HOST_KEY_AUTO_ADD": "False",
                        }
                        if profile_bound
                        else {}
                    ),
                    **({"HOME": str(runner_home)} if runner_home is not None else {}),
                },
                event_handler=handle_event,
                quiet=True,
                rotate_artifacts=1,
            )
            return result, selected

    def discover(
        self,
        device: InventoryDevice,
        credentials: DeviceCredentials,
    ) -> tuple[InterfaceState, ...]:
        """Collect identity, interface, and bounded L3 state read-only."""
        return self._discover_read_only(
            device,
            credentials,
            ssh_type="paramiko",
            profile_bound=False,
        )

    def discover_read_only(
        self,
        target: ReadOnlyConnectionTarget,
        credentials: DeviceCredentials,
        *,
        ssh_type: Literal["paramiko"],
    ) -> tuple[InterfaceState, ...]:
        """Collect through one explicit B2 profile-bound Cisco SSH backend."""
        return self._discover_read_only(
            target,
            credentials,
            ssh_type=ssh_type,
            profile_bound=True,
        )

    def _discover_read_only(
        self,
        target: ReadOnlyConnectionTarget,
        credentials: DeviceCredentials,
        *,
        ssh_type: Literal["paramiko"],
        profile_bound: bool,
    ) -> tuple[InterfaceState, ...]:
        runner, selected = self._run(
            target,
            credentials,
            "collect_interface_state.yml",
            ssh_type=ssh_type,
            profile_bound=profile_bound,
        )
        if (
            getattr(runner, "status", None) != "successful"
            or getattr(runner, "rc", 1) != 0
        ):
            identity_event = selected.get(IDENTITY_TASK, {}).get("_ncdp_event")
            if identity_event == "runner_on_unreachable":
                raise ProviderReadinessError(
                    "trusted Cisco SSH collection was unreachable"
                )
            if identity_event == "runner_on_failed":
                classification = _bounded_read_failure(selected[IDENTITY_TASK])
                if classification in {
                    "Cisco SSH session failed",
                    "Cisco read-only command timed out",
                }:
                    raise ProviderReadinessError(classification)
                raise ProviderError(classification)
            if IDENTITY_TASK not in selected:
                raise ProviderError(
                    "Cisco collection failed before a bounded identity result"
                )
            raise ProviderError("trusted authenticated read-only collection failed")
        try:
            facts = selected[IDENTITY_TASK]["ansible_facts"]
            hostname = str(facts["ansible_net_hostname"])
            version = str(facts.get("ansible_net_version") or "") or None
            interfaces = selected[INTERFACES_TASK]["gathered"]
            l3_interfaces = selected[L3_INTERFACES_TASK]["gathered"]
        except (KeyError, TypeError) as error:
            raise ProviderError("read-only provider result was incomplete") from error

        addresses_by_name: dict[str, tuple[str, ...]] = {}
        for item in l3_interfaces:
            addresses: list[str] = []
            for ipv4 in item.get("ipv4", []):
                address = ipv4.get("address")
                if isinstance(address, str):
                    addresses.append(address)
            addresses_by_name[str(item.get("name", ""))] = tuple(addresses)

        return tuple(
            InterfaceState(
                observed_hostname=hostname,
                software_version=version,
                interface=str(item["name"]),
                exists=True,
                description=item.get("description"),
                protected=_normalized_name(str(item["name"]))
                in {_normalized_name(name) for name in target.protected_interfaces},
                enabled=item.get("enabled"),
                ipv4_addresses=addresses_by_name.get(str(item["name"]), ()),
            )
            for item in interfaces
            if isinstance(item, dict) and item.get("name")
        )

    def collect(
        self,
        device: InventoryDevice,
        credentials: DeviceCredentials,
        interface: str,
    ) -> InterfaceState:
        """Return normalized fresh state for exactly one requested interface."""
        states = self.discover(device, credentials)
        matches = [state for state in states if state.interface == interface]
        if len(matches) == 1:
            return matches[0]
        hostname = states[0].observed_hostname if states else ""
        version = states[0].software_version if states else None
        return InterfaceState(
            observed_hostname=hostname,
            software_version=version,
            interface=interface,
            exists=False,
            protected=False,
        )

    def collect_read_only(
        self,
        target: ReadOnlyConnectionTarget,
        credentials: DeviceCredentials,
        interface: str,
        *,
        ssh_type: Literal["paramiko"],
    ) -> InterfaceState:
        """Return one exact interface through the selected B2 Cisco backend."""
        states = self.discover_read_only(
            target,
            credentials,
            ssh_type=ssh_type,
        )
        matches = [state for state in states if state.interface == interface]
        if len(matches) == 1:
            return matches[0]
        hostname = states[0].observed_hostname if states else ""
        version = states[0].software_version if states else None
        return InterfaceState(
            observed_hostname=hostname,
            software_version=version,
            interface=interface,
            exists=False,
            protected=False,
        )

    def collect_ospf_read_only(
        self,
        target: ReadOnlyConnectionTarget,
        credentials: DeviceCredentials,
        interfaces: tuple[str, str],
        *,
        ssh_type: Literal["paramiko"],
    ) -> tuple[str, str, str]:
        """Read only the OSPF process and two exact interface configurations."""
        runner, selected = self._run(
            target,
            credentials,
            "collect_ospf_state.yml",
            extravars={"ncdp_ospf_interfaces": list(interfaces)},
            ssh_type=ssh_type,
            profile_bound=True,
        )
        if (
            getattr(runner, "status", None) != "successful"
            or getattr(runner, "rc", 1) != 0
            or OSPF_READ_TASK not in selected
        ):
            raise ProviderError("Cisco OSPF read-only collection failed")
        stdout = selected[OSPF_READ_TASK].get("stdout")
        if (
            not isinstance(stdout, list)
            or len(stdout) != 3
            or any(not isinstance(value, str) for value in stdout)
        ):
            raise ProviderError("Cisco OSPF read-only result was incomplete")
        return tuple(stdout)  # type: ignore[return-value]

    def collect_vlan_read_only(
        self,
        target: ReadOnlyConnectionTarget,
        credentials: DeviceCredentials,
        scope: VlanReadScope,
        *,
        ssh_type: Literal["paramiko"],
    ) -> tuple[str, ...]:
        """Read only one exact B4-3 VLAN service scope."""
        if not isinstance(scope, VlanReadScope):
            raise ProviderError("Cisco VLAN read-only scope is invalid")
        commands = VLAN_READ_COMMANDS[scope]
        runner, selected = self._run(
            target,
            credentials,
            "collect_vlan_state.yml",
            extravars={"ncdp_vlan_commands": list(commands)},
            ssh_type=ssh_type,
            profile_bound=True,
        )
        if (
            getattr(runner, "status", None) != "successful"
            or getattr(runner, "rc", 1) != 0
            or VLAN_READ_TASK not in selected
        ):
            raise ProviderError("Cisco VLAN read-only collection failed")
        stdout = selected[VLAN_READ_TASK].get("stdout")
        if (
            not isinstance(stdout, list)
            or len(stdout) != len(commands)
            or any(not isinstance(value, str) for value in stdout)
        ):
            raise ProviderError("Cisco VLAN read-only result was incomplete")
        return tuple(stdout)

    def collect_acl_read_only(
        self,
        target: ReadOnlyConnectionTarget,
        credentials: DeviceCredentials,
        scope: AclReadScope,
        *,
        ssh_type: Literal["paramiko"],
    ) -> tuple[str, ...]:
        """Read only the exact B4-4 ACL security-policy scope."""
        if not isinstance(scope, AclReadScope):
            raise ProviderError("Cisco ACL read-only scope is invalid")
        commands = ACL_READ_COMMANDS[scope]
        runner, selected = self._run(
            target,
            credentials,
            "collect_acl_state.yml",
            extravars={"ncdp_acl_commands": list(commands)},
            ssh_type=ssh_type,
            profile_bound=True,
        )
        if (
            getattr(runner, "status", None) != "successful"
            or getattr(runner, "rc", 1) != 0
            or ACL_READ_TASK not in selected
        ):
            raise ProviderError("Cisco ACL read-only collection failed")
        stdout = selected[ACL_READ_TASK].get("stdout")
        if (
            not isinstance(stdout, list)
            or len(stdout) != len(commands)
            or any(not isinstance(value, str) for value in stdout)
        ):
            raise ProviderError("Cisco ACL read-only result was incomplete")
        return tuple(stdout)

    @staticmethod
    def _classify_interface_execution(
        runner: object, selected: dict[str, dict[str, Any]]
    ) -> ExecutionResult:
        """Keep v1 and profiled result classification identical."""
        status = str(getattr(runner, "status", "failed"))
        rc = getattr(runner, "rc", None)
        execution_event = selected.get(EXECUTION_TASK, {}).get("_ncdp_event")
        if (
            status in {"timeout", "canceled"}
            or rc in {254, 255}
            or execution_event in {"runner_on_failed", "runner_on_unreachable"}
        ):
            return ExecutionResult(
                disposition=ExecutionDisposition.AMBIGUOUS,
                message=(
                    "network write outcome is ambiguous; "
                    "operator investigation required"
                ),
            )
        if status != "successful" or rc != 0 or EXECUTION_TASK not in selected:
            return ExecutionResult(
                disposition=ExecutionDisposition.FAILED,
                message="configuration task failed before an unambiguous success",
            )
        return ExecutionResult(
            disposition=ExecutionDisposition.SUCCEEDED,
            changed=bool(selected[EXECUTION_TASK].get("changed", False)),
            message="exact approved configuration artifact completed successfully",
        )

    def execute_profiled(
        self,
        target: ConnectionTarget,
        credentials: DeviceCredentials,
        artifact: CiscoConfigArtifact,
    ) -> ExecutionResult:
        """Apply one profiled artifact with explicit strict host trust only."""
        if self._known_hosts is None:
            raise HostTrustError("profiled Cisco write requires explicit known_hosts")
        try:
            runner, selected = self._run(
                target,
                credentials,
                "apply_interface_description.yml",
                extravars={"ncdp_artifact": artifact.model_dump(mode="json")},
                ssh_type="paramiko",
                profile_bound=True,
            )
        except HostTrustError:
            raise
        except Exception:
            return ExecutionResult(
                disposition=ExecutionDisposition.AMBIGUOUS,
                message="profiled write may have been attempted; outcome ambiguous",
            )
        return self._classify_interface_execution(runner, selected)

    def snmp_preflight(
        self,
        device: InventoryDevice,
        credentials: DeviceCredentials,
        plan: SnmpPreflightSubject,
    ) -> SnmpOwnedObjectState:
        """Collect only identity and deterministic SNMP-owned names read-only."""
        commands = cisco_preflight_commands(plan)
        runner, selected = self._run(
            device,
            credentials,
            "inspect_snmp_provisioning.yml",
            extravars={"ncdp_snmp_commands": list(commands)},
        )
        if (
            getattr(runner, "status", None) != "successful"
            or getattr(runner, "rc", 1) != 0
        ):
            raise ProviderError("Cisco SNMP targeted preflight failed")

        def command_output(task: str) -> str:
            result = selected.get(task)
            if not isinstance(result, dict):
                raise ProviderError("Cisco SNMP preflight result rejected")
            output = result.get("stdout")
            if isinstance(output, list) and len(output) == 1:
                return str(output[0])
            message = result.get("msg")
            if isinstance(message, bytes):
                message = message.decode("utf-8", errors="replace")
            if _normalize_disabled_snmp_agent(message) is not None:
                return _DISABLED_SNMP_AGENT
            raise ProviderError("Cisco SNMP preflight result rejected")

        try:
            hostname = str(
                selected[IDENTITY_TASK]["ansible_facts"]["ansible_net_hostname"]
            )
            values = tuple(
                command_output(task)
                for task in (
                    SNMP_ENGINE_TASK,
                    SNMP_VIEW_TASK,
                    SNMP_GROUP_TASK,
                    SNMP_USER_TASK,
                )
            )
        except (KeyError, TypeError):
            raise ProviderError("Cisco SNMP preflight result rejected") from None
        return parse_cisco_snmp_state(
            plan,
            observed_hostname=hostname,
            engine_output=values[0],
            view_output=values[1],
            group_output=values[2],
            user_output=values[3],
        )


def _normalized_name(name: str) -> str:
    return "".join(name.split()).casefold()
