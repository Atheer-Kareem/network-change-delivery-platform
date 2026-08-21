"""Narrow Ansible Runner adapter for Cisco IOS XE collection and execution."""

from __future__ import annotations

import base64
import hashlib
import os
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import ansible_runner

from network_change_delivery.models import (
    CiscoConfigArtifact,
    ExecutionDisposition,
    ExecutionResult,
    InterfaceState,
    InventoryDevice,
)
from network_change_delivery.secrets import DeviceCredentials

IDENTITY_TASK = "NCDP collect identity"
INTERFACES_TASK = "NCDP collect interfaces"
L3_INTERFACES_TASK = "NCDP collect layer 3 interfaces"
EXECUTION_TASK = "NCDP apply exact approved artifact"


class ProviderError(RuntimeError):
    """Bounded provider failure that never embeds raw Runner output."""


class HostTrustError(ProviderError):
    """Raised when the candidate lacks an existing trusted host-key entry."""


@contextmanager
def _credential_environment(credentials: DeviceCredentials):
    """Expose credentials only to the child process and restore prior state."""
    names = ("NCDP_DEVICE_USERNAME", "NCDP_DEVICE_PASSWORD")
    previous = {name: os.environ.get(name) for name in names}
    os.environ[names[0]] = credentials.username
    os.environ[names[1]] = credentials.password
    try:
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


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


def verify_existing_host_trust(device: InventoryDevice) -> str:
    """Confirm a known_hosts entry exists without discovering or trusting a key."""
    known_hosts = _known_hosts_path()
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

    def __init__(self, repository_root: Path | None = None) -> None:
        self._root = repository_root or Path(
            os.environ.get("NCDP_PROJECT_ROOT", Path.cwd())
        )

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
                        "ansible_network_cli_ssh_type": "libssh",
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
        verify_existing_host_trust(device)
        selected: dict[str, dict[str, Any]] = {}

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
            }:
                result = data.get("res", {})
                if isinstance(result, dict):
                    selected[str(task)] = {**result, "_ncdp_event": event_kind}

        with tempfile.TemporaryDirectory(prefix="ncdp-runner-") as directory:
            private_data = Path(directory)
            private_data.chmod(0o700)
            with _credential_environment(credentials):
                result = ansible_runner.run(
                    private_data_dir=str(private_data),
                    project_dir=str(self._root / "ansible"),
                    artifact_dir=str(private_data / "artifacts"),
                    playbook=playbook,
                    inventory=self._inventory(device),
                    extravars=extravars or {},
                    envvars={
                        "ANSIBLE_CONFIG": str(self._root / "ansible.cfg"),
                        "ANSIBLE_COLLECTIONS_PATH": os.environ.get(
                            "ANSIBLE_COLLECTIONS_PATH",
                            (
                                f"{self._root / '.ansible' / 'collections'}:"
                                "/opt/ansible/collections"
                            ),
                        ),
                        "ANSIBLE_HOST_KEY_CHECKING": "True",
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
                ios_version=version,
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
        version = states[0].ios_version if states else None
        return InterfaceState(
            observed_hostname=hostname,
            ios_version=version,
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


def _normalized_name(name: str) -> str:
    return "".join(name.split()).casefold()
