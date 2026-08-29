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
from pathlib import Path
from typing import Any

import ansible_runner
import yaml

from network_change_delivery.models import (
    CiscoConfigArtifact,
    ExecutionDisposition,
    ExecutionResult,
    InterfaceState,
    InventoryDevice,
)
from network_change_delivery.secrets import DeviceCredentials
from network_change_delivery.snmp_provisioning import (
    SecretRenderedArtifact,
    SnmpOwnedObjectState,
    SnmpPreflightSubject,
    cisco_preflight_commands,
    parse_cisco_snmp_state,
)

IDENTITY_TASK = "NCDP collect identity"
INTERFACES_TASK = "NCDP collect interfaces"
L3_INTERFACES_TASK = "NCDP collect layer 3 interfaces"
EXECUTION_TASK = "NCDP apply exact approved artifact"
SNMP_PREFLIGHT_TASK = "NCDP inspect exact SNMP owned names"
SNMP_ENGINE_TASK = "NCDP inspect SNMP engine"
SNMP_VIEW_TASK = "NCDP inspect SNMP view"
SNMP_GROUP_TASK = "NCDP inspect SNMP group"
SNMP_USER_TASK = "NCDP inspect SNMP user"
SNMP_EXECUTION_TASK = "NCDP apply exact SNMP artifact"


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


def _known_hosts_query(device: InventoryDevice) -> str:
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
    device: InventoryDevice, known_hosts: Path | None = None
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
    def _inventory(device: InventoryDevice) -> dict[str, Any]:
        return {
            "all": {
                "hosts": {
                    "ncdp_target": {
                        "ansible_host": device.host,
                        "ansible_port": device.port,
                        "ansible_connection": "ansible.netcommon.network_cli",
                        "ansible_network_os": "cisco.ios.ios",
                        "ansible_network_cli_ssh_type": "paramiko",
                    }
                }
            }
        }

    def _run(
        self,
        device: InventoryDevice,
        credentials: DeviceCredentials,
        playbook: str,
        *,
        extravars: dict[str, Any] | None = None,
    ) -> tuple[object, dict[str, dict[str, Any]]]:
        if self._known_hosts is None:
            verify_existing_host_trust(device)
        else:
            verify_existing_host_trust(device, self._known_hosts)
        selected: dict[str, dict[str, Any]] = {}
        inventory = self._inventory(device)

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
                EXECUTION_TASK,
                SNMP_PREFLIGHT_TASK,
                SNMP_ENGINE_TASK,
                SNMP_VIEW_TASK,
                SNMP_GROUP_TASK,
                SNMP_USER_TASK,
                SNMP_EXECUTION_TASK,
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
        runner, selected = self._run(
            device,
            credentials,
            "collect_interface_state.yml",
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
                in {_normalized_name(name) for name in device.protected_interfaces},
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

    def execute(
        self,
        device: InventoryDevice,
        credentials: DeviceCredentials,
        artifact: CiscoConfigArtifact,
    ) -> ExecutionResult:
        """Apply exactly one artifact once and normalize the bounded result."""
        runner, selected = self._run(
            device,
            credentials,
            "apply_interface_description.yml",
            extravars={"ncdp_artifact": artifact.model_dump(mode="json")},
        )
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
            if isinstance(message, str) and "%SNMP agent not enabled" in message:
                return "%SNMP agent not enabled"
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

    def execute_snmp(
        self,
        device: InventoryDevice,
        credentials: DeviceCredentials,
        artifact: SecretRenderedArtifact,
    ) -> ExecutionResult:
        """Apply one in-memory secret-bearing artifact with Runner no_log."""
        if artifact.platform != "cisco_iosxe" or not isinstance(
            artifact.payload, tuple
        ):
            raise ProviderError("Cisco SNMP artifact rejected")
        runner, selected = self._run(
            device,
            credentials,
            "apply_snmp_provisioning.yml",
            extravars={"ncdp_snmp_commands": list(artifact.payload)},
        )
        status = str(getattr(runner, "status", "failed"))
        rc = getattr(runner, "rc", None)
        event = selected.get(SNMP_EXECUTION_TASK, {}).get("_ncdp_event")
        if (
            status in {"timeout", "canceled"}
            or rc in {254, 255}
            or event
            in {
                "runner_on_failed",
                "runner_on_unreachable",
            }
        ):
            return ExecutionResult(
                disposition=ExecutionDisposition.AMBIGUOUS,
                message="Cisco SNMP write outcome is ambiguous; no retry authorized",
            )
        if status != "successful" or rc != 0 or SNMP_EXECUTION_TASK not in selected:
            return ExecutionResult(
                disposition=ExecutionDisposition.FAILED,
                message="Cisco SNMP write failed before known success",
            )
        return ExecutionResult(
            disposition=ExecutionDisposition.SUCCEEDED,
            changed=True,
            message="exact Cisco SNMP artifact completed once",
        )


def _normalized_name(name: str) -> str:
    return "".join(name.split()).casefold()
