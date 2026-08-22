"""Narrow direct-PyEZ Junos collection and transactional execution boundary."""

from __future__ import annotations

import hashlib
import tempfile
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from jnpr.junos.exception import (
    CommitError,
    ConnectClosedError,
    ConnectError,
    RpcError,
    RpcTimeoutError,
)
from jnpr.junos.utils.config import Config

from network_change_delivery.ansible_adapter import (
    ProviderError,
    verify_existing_host_trust,
)
from network_change_delivery.models import (
    ExecutionDisposition,
    ExecutionResult,
    InterfaceState,
    InventoryDevice,
    JunosConfigArtifact,
)
from network_change_delivery.secrets import DeviceCredentials


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child_text(element: Any, name: str) -> str | None:
    for child in element:
        if _local_name(str(child.tag)) == name:
            value = child.text
            return value.strip() if isinstance(value, str) and value.strip() else None
    return None


def _interface_filter(interface: str | None = None) -> ElementTree.Element:
    root = ElementTree.Element("configuration")
    interfaces = ElementTree.SubElement(root, "interfaces")
    if interface is not None:
        item = ElementTree.SubElement(interfaces, "interface")
        ElementTree.SubElement(item, "name").text = interface
    return root


def _diff_is_scoped(diff: str, artifact: JunosConfigArtifact) -> bool:
    header = f"[edit interfaces {artifact.interface}]"
    headers = [
        line.strip() for line in diff.splitlines() if line.strip().startswith("[edit ")
    ]
    changed = [
        line.strip()
        for line in diff.splitlines()
        if line.lstrip().startswith(("+", "-"))
    ]
    additions = [
        line
        for line in changed
        if line.startswith("+ description ") and line.endswith(";")
    ]
    return (
        headers == [header]
        and len(additions) == 1
        and all(
            line in additions or line.startswith("- description ") for line in changed
        )
    )


@dataclass(frozen=True)
class PreparedCandidate:
    """Bounded evidence from the still-open exclusive candidate session."""

    diff_sha256: str
    summary: str = "one approved interface-description candidate"


class JunosTransaction:
    """One Device and one exclusive Config session from prepare through commit."""

    def __init__(
        self,
        connection: Any,
        config_factory: Callable[..., Any],
        artifact: JunosConfigArtifact,
    ) -> None:
        self._connection = connection
        self._config = config_factory(connection, mode="exclusive")
        self._artifact = artifact
        self._loaded = False
        self._commit_attempted = False

    def __enter__(self) -> JunosTransaction:
        self._config.__enter__()
        try:
            existing = self._config.diff()
        except Exception:
            self._config.__exit__(None, None, None)
            raise ProviderError("unable to verify clean Junos candidate") from None
        if existing not in {None, ""}:
            self._config.__exit__(None, None, None)
            raise ProviderError("Junos candidate contains pre-existing changes")
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        cleanup_failed = False
        if self._loaded and not self._commit_attempted:
            try:
                self._config.rollback(0)
            except Exception:
                cleanup_failed = True
        self._config.__exit__(exc_type, exc, traceback)
        if cleanup_failed:
            raise ProviderError("Junos uncommitted candidate cleanup failed") from None

    def prepare(self) -> PreparedCandidate:
        """Load, check, and semantically validate the sole approved candidate."""
        try:
            self._config.load(self._artifact.xml, format="xml", merge=True)
            self._loaded = True
            if self._config.commit_check() is not True:
                raise ProviderError("Junos commit check failed")
            diff = self._config.diff()
            candidate = self._connection.rpc.get_config(
                filter_xml=_interface_filter(self._artifact.interface),
                options={"database": "candidate"},
            )
        except ProviderError:
            raise
        except Exception:
            raise ProviderError("Junos candidate preparation failed") from None
        descriptions = [
            _child_text(item, "description")
            for item in candidate.iter()
            if _local_name(str(item.tag)) == "interface"
            and _child_text(item, "name") == self._artifact.interface
        ]
        if (
            not isinstance(diff, str)
            or not diff.strip()
            or not _diff_is_scoped(diff, self._artifact)
            or descriptions != [self._artifact.description]
        ):
            raise ProviderError(
                "prepared Junos candidate is not the approved operation"
            )
        digest = hashlib.sha256(diff.encode()).hexdigest()
        return PreparedCandidate(diff_sha256=f"sha256:{digest}")

    def commit_confirmed(self, minutes: int) -> ExecutionResult:
        """Issue the first active write once, as commit confirmed 5."""
        if minutes != 5:
            return ExecutionResult(
                disposition=ExecutionDisposition.FAILED,
                message="Junos confirmed-commit timeout contract is invalid",
                provider="pyez/config-exclusive",
            )
        self._commit_attempted = True
        try:
            committed = self._config.commit(confirm=5)
        except (ConnectClosedError, ConnectError, RpcTimeoutError):
            return ExecutionResult(
                disposition=ExecutionDisposition.AMBIGUOUS,
                message=(
                    "commit-confirmed result is ambiguous; no retry or confirmation"
                ),
                provider="pyez/config-exclusive",
            )
        except (CommitError, RpcError):
            return ExecutionResult(
                disposition=ExecutionDisposition.FAILED,
                message="commit-confirmed failed with known failure",
                provider="pyez/config-exclusive",
            )
        except Exception:
            return ExecutionResult(
                disposition=ExecutionDisposition.AMBIGUOUS,
                message=(
                    "commit-confirmed result is ambiguous; no retry or confirmation"
                ),
                provider="pyez/config-exclusive",
            )
        if committed is not True:
            return ExecutionResult(
                disposition=ExecutionDisposition.FAILED,
                message="commit-confirmed did not report known success",
                provider="pyez/config-exclusive",
            )
        return ExecutionResult(
            disposition=ExecutionDisposition.SUCCEEDED,
            changed=True,
            message="temporary commit confirmed 5 is active",
            provider="pyez/config-exclusive",
        )


class JunosPyEZAdapter:
    """Use fresh hardened NETCONF sessions for collection and Junos transactions."""

    def __init__(
        self,
        device_factory: Callable[..., Any] | None = None,
        config_factory: Callable[..., Any] = Config,
    ) -> None:
        if device_factory is None:
            from jnpr.junos import Device

            device_factory = Device
        self._device_factory = device_factory
        self._config_factory = config_factory

    @contextmanager
    def _session(self, device: InventoryDevice, credentials: DeviceCredentials) -> Any:
        if device.platform != "junos" or device.port != 830:
            raise ProviderError("Junos requires the approved NETCONF port 830")
        verify_existing_host_trust(device)
        with tempfile.TemporaryDirectory(prefix="ncdp-junos-ssh-") as directory:
            ssh_config = Path(directory) / "config"
            ssh_config.write_text("Host *\n  ProxyCommand none\n", encoding="utf-8")
            ssh_config.chmod(0o600)
            try:
                connection = self._device_factory(
                    host=device.host,
                    port=device.port,
                    user=credentials.username,
                    passwd=credentials.password,
                    gather_facts=True,
                    hostkey_verify=True,
                    look_for_keys=False,
                    allow_agent=False,
                    ssh_private_key_file=None,
                    ssh_config=str(ssh_config),
                    proxy_command=None,
                )
                with connection:
                    yield connection
            except ProviderError:
                raise
            except (ConnectClosedError, ConnectError, RpcError, RpcTimeoutError):
                raise
            except Exception:
                raise ProviderError(
                    "trusted authenticated Junos NETCONF session failed"
                ) from None

    @contextmanager
    def transaction(
        self,
        device: InventoryDevice,
        credentials: DeviceCredentials,
        artifact: JunosConfigArtifact,
    ) -> Any:
        with (
            self._session(device, credentials) as connection,
            JunosTransaction(connection, self._config_factory, artifact) as transaction,
        ):
            yield transaction

    def discover(
        self, device: InventoryDevice, credentials: DeviceCredentials
    ) -> tuple[InterfaceState, ...]:
        with self._session(device, credentials) as connection:
            hostname = str(connection.facts.get("hostname") or "")
            version = str(connection.facts.get("version") or "") or None
            reply = connection.rpc.get_config(
                filter_xml=_interface_filter(), options={"database": "committed"}
            )
        if not hostname or reply is None:
            raise ProviderError("Junos read-only provider result was incomplete")
        protected = {
            "".join(name.split()).casefold() for name in device.protected_interfaces
        }
        states: list[InterfaceState] = []
        try:
            for element in reply.iter():
                if _local_name(str(element.tag)) != "interface":
                    continue
                name = _child_text(element, "name")
                if not name:
                    continue
                addresses = tuple(
                    value
                    for descendant in element.iter()
                    if _local_name(str(descendant.tag)) == "address"
                    and (value := _child_text(descendant, "name")) is not None
                )
                disabled = any(
                    _local_name(str(descendant.tag)) == "disable"
                    for descendant in element.iter()
                )
                states.append(
                    InterfaceState(
                        observed_hostname=hostname,
                        software_version=version,
                        interface=name,
                        exists=True,
                        description=_child_text(element, "description"),
                        protected="".join(name.split()).casefold() in protected,
                        enabled=not disabled,
                        ipv4_addresses=tuple(sorted(set(addresses))),
                    )
                )
        except (AttributeError, TypeError):
            raise ProviderError(
                "Junos read-only provider result was incomplete"
            ) from None
        return tuple(states)

    def collect(
        self,
        device: InventoryDevice,
        credentials: DeviceCredentials,
        interface: str,
    ) -> InterfaceState:
        states = self.discover(device, credentials)
        matches = [state for state in states if state.interface == interface]
        if len(matches) == 1:
            return matches[0]
        return InterfaceState(
            observed_hostname=states[0].observed_hostname if states else "",
            software_version=states[0].software_version if states else None,
            interface=interface,
            exists=False,
            protected=False,
        )

    def confirm(
        self, device: InventoryDevice, credentials: DeviceCredentials
    ) -> ExecutionResult:
        try:
            with (
                self._session(device, credentials) as connection,
                self._config_factory(connection, mode="exclusive") as config,
            ):
                confirmed = config.commit_check()
        except (ConnectClosedError, ConnectError, RpcTimeoutError):
            return ExecutionResult(
                disposition=ExecutionDisposition.AMBIGUOUS,
                message="confirmation result is ambiguous; final persistence uncertain",
                provider="pyez/config-exclusive",
            )
        except (ProviderError, RpcError):
            return ExecutionResult(
                disposition=ExecutionDisposition.FAILED,
                message="confirmation failed; automatic rollback remains expected",
                provider="pyez/config-exclusive",
            )
        if confirmed is not True:
            return ExecutionResult(
                disposition=ExecutionDisposition.FAILED,
                message="confirmation did not report known success",
                provider="pyez/config-exclusive",
            )
        return ExecutionResult(
            disposition=ExecutionDisposition.SUCCEEDED,
            message="pending commit confirmed with known success",
            provider="pyez/config-exclusive",
        )
