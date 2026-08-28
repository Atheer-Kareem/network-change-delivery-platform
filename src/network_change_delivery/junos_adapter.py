"""Narrow direct-PyEZ Junos collection and transactional execution boundary."""

from __future__ import annotations

import hashlib
import tempfile
from collections.abc import Callable
from contextlib import contextmanager, suppress
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


def _interface_filter(interface: str | None = None) -> str:
    root = ElementTree.Element("configuration")
    interfaces = ElementTree.SubElement(root, "interfaces")
    if interface is not None:
        item = ElementTree.SubElement(interfaces, "interface")
        ElementTree.SubElement(item, "name").text = interface
    return ElementTree.tostring(root, encoding="unicode")


def _configured_ipv4_addresses(interface: Any) -> tuple[str, ...]:
    addresses: set[str] = set()
    for family in interface.iter():
        if _local_name(str(family.tag)) != "family":
            continue
        for inet in family:
            if _local_name(str(inet.tag)) != "inet":
                continue
            for address in inet.iter():
                if _local_name(str(address.tag)) == "address" and (
                    value := _child_text(address, "name")
                ):
                    addresses.add(value)
    return tuple(sorted(addresses))


def _normalized_status(value: str | None) -> str | None:
    normalized = (value or "").strip().casefold()
    return normalized if normalized in {"up", "down"} else None


def _diff_is_scoped(diff: str, artifact: JunosConfigArtifact) -> bool:
    header = f"[edit interfaces {artifact.interface}]"
    headers = [
        line.strip() for line in diff.splitlines() if line.strip().startswith("[edit ")
    ]
    changed = [
        f"{line.lstrip()[0]} {' '.join(line.lstrip()[1:].split())}"
        for line in diff.splitlines()
        if line.lstrip().startswith(("+", "-"))
    ]
    additions = [
        line
        for line in changed
        if line.startswith("+ description ") and line.endswith(";")
    ]
    existing_interface_change = (
        headers == [header]
        and len(additions) == 1
        and all(
            line in additions or line.startswith("- description ") for line in changed
        )
    )
    created_interface_change = (
        headers == ["[edit interfaces]"]
        and len(changed) == 3
        and changed[0] == f"+ {artifact.interface} {{"
        and changed[1].startswith("+ description ")
        and changed[1].endswith(";")
        and changed[2] == "+ }"
    )
    return existing_interface_change or created_interface_change


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
        self._commit_result: ExecutionResult | None = None
        self.close_failed = False

    @property
    def commit_result(self) -> ExecutionResult | None:
        """Return the bounded result once a commit-confirmed attempt is classified."""
        return self._commit_result

    @property
    def commit_attempted(self) -> bool:
        """Return whether the commit-confirmed RPC boundary was crossed."""
        return self._commit_attempted

    def __enter__(self) -> JunosTransaction:
        try:
            self._config.__enter__()
        except Exception:
            raise ProviderError("unable to acquire exclusive Junos candidate") from None
        try:
            existing = self._config.diff()
        except Exception:
            with suppress(Exception):
                self._config.__exit__(None, None, None)
            raise ProviderError("unable to verify clean Junos candidate") from None
        if existing not in {None, ""}:
            try:
                self._config.__exit__(None, None, None)
            except Exception:
                raise ProviderError(
                    "unable to release exclusive Junos candidate"
                ) from None
            raise ProviderError("Junos candidate contains pre-existing changes")
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        cleanup_failed = False
        if self._loaded and not self._commit_attempted:
            try:
                self._config.rollback(0)
            except Exception:
                cleanup_failed = True
        try:
            self._config.__exit__(exc_type, exc, traceback)
        except Exception:
            if self._commit_attempted and self._commit_result is not None:
                self.close_failed = True
                return
            raise ProviderError("Junos candidate cleanup or unlock failed") from None
        if cleanup_failed and self._commit_result is None:
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
            result = ExecutionResult(
                disposition=ExecutionDisposition.FAILED,
                message="Junos confirmed-commit timeout contract is invalid",
                provider="pyez/config-exclusive",
            )
            self._commit_result = result
            return result
        self._commit_attempted = True
        try:
            committed = self._config.commit(confirm=5)
        except (ConnectClosedError, ConnectError, RpcTimeoutError):
            result = ExecutionResult(
                disposition=ExecutionDisposition.AMBIGUOUS,
                message=(
                    "commit-confirmed result is ambiguous; no retry or confirmation"
                ),
                provider="pyez/config-exclusive",
            )
            self._commit_result = result
            return result
        except (CommitError, RpcError):
            result = ExecutionResult(
                disposition=ExecutionDisposition.FAILED,
                message="commit-confirmed failed with known failure",
                provider="pyez/config-exclusive",
            )
            self._commit_result = result
            return result
        except Exception:
            result = ExecutionResult(
                disposition=ExecutionDisposition.AMBIGUOUS,
                message=(
                    "commit-confirmed result is ambiguous; no retry or confirmation"
                ),
                provider="pyez/config-exclusive",
            )
            self._commit_result = result
            return result
        if committed is not True:
            result = ExecutionResult(
                disposition=ExecutionDisposition.FAILED,
                message="commit-confirmed did not report known success",
                provider="pyez/config-exclusive",
            )
            self._commit_result = result
            return result
        result = ExecutionResult(
            disposition=ExecutionDisposition.SUCCEEDED,
            changed=True,
            message="temporary commit confirmed 5 is active",
            provider="pyez/config-exclusive",
        )
        self._commit_result = result
        return result


class JunosPyEZAdapter:
    """Use fresh hardened NETCONF sessions for collection and Junos transactions."""

    def __init__(
        self,
        device_factory: Callable[..., Any] | None = None,
        config_factory: Callable[..., Any] = Config,
        *,
        known_hosts: Path | None = None,
        ssh_keygen: str | Path = "ssh-keygen",
    ) -> None:
        if device_factory is None:
            from jnpr.junos import Device

            device_factory = Device
        self._device_factory = device_factory
        self._config_factory = config_factory
        self._known_hosts = known_hosts
        self._ssh_keygen = ssh_keygen

    @contextmanager
    def _session(self, device: InventoryDevice, credentials: DeviceCredentials) -> Any:
        if device.platform != "junos" or device.port != 830:
            raise ProviderError("Junos requires the approved NETCONF port 830")
        trust_arguments = () if self._known_hosts is None else (self._known_hosts,)
        if self._ssh_keygen == "ssh-keygen":
            verify_existing_host_trust(device, *trust_arguments)
        else:
            verify_existing_host_trust(
                device, *trust_arguments, ssh_keygen=self._ssh_keygen
            )
        with tempfile.TemporaryDirectory(prefix="ncdp-junos-ssh-") as directory:
            ssh_config = Path(directory) / "config"
            config = "Host *\n  ProxyCommand none\n"
            if self._known_hosts is not None:
                config += (
                    "  StrictHostKeyChecking yes\n"
                    f"  UserKnownHostsFile {self._known_hosts}\n"
                )
            ssh_config.write_text(config, encoding="utf-8")
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
        transaction: JunosTransaction | None = None
        try:
            with (
                self._session(device, credentials) as connection,
                JunosTransaction(
                    connection, self._config_factory, artifact
                ) as transaction,
            ):
                yield transaction
        except ProviderError:
            if (
                transaction is not None
                and transaction.commit_attempted
                and transaction.commit_result is not None
            ):
                transaction.close_failed = True
                return
            raise

    def discover(
        self, device: InventoryDevice, credentials: DeviceCredentials
    ) -> tuple[InterfaceState, ...]:
        with self._session(device, credentials) as connection:
            hostname = str(connection.facts.get("hostname") or "")
            version = str(connection.facts.get("version") or "") or None
            try:
                operational_reply = connection.rpc.get_interface_information(terse=True)
                config_reply = connection.rpc.get_config(
                    filter_xml=_interface_filter(), options={"database": "committed"}
                )
            except Exception:
                raise ProviderError("Junos read-only provider request failed") from None
        if not hostname or operational_reply is None or config_reply is None:
            raise ProviderError("Junos read-only provider result was incomplete")
        protected = {
            "".join(name.split()).casefold() for name in device.protected_interfaces
        }
        try:
            configured: dict[str, tuple[str | None, bool, tuple[str, ...]]] = {}
            for element in config_reply.iter():
                if _local_name(str(element.tag)) != "interface":
                    continue
                name = _child_text(element, "name")
                if not name or "." in name:
                    continue
                addresses = _configured_ipv4_addresses(element)
                disabled = any(
                    _local_name(str(descendant.tag)) == "disable"
                    for descendant in element.iter()
                )
                configured[name] = (
                    _child_text(element, "description"),
                    disabled,
                    tuple(sorted(set(addresses))),
                )
            states: list[InterfaceState] = []
            seen: set[str] = set()
            for element in operational_reply.iter():
                if _local_name(str(element.tag)) != "physical-interface":
                    continue
                name = _child_text(element, "name")
                if not name or "." in name or name in seen:
                    continue
                seen.add(name)
                description, disabled, addresses = configured.get(
                    name, (None, False, ())
                )
                admin = _normalized_status(_child_text(element, "admin-status"))
                enabled = True if admin == "up" else False if admin == "down" else None
                if disabled:
                    enabled = False
                states.append(
                    InterfaceState(
                        observed_hostname=hostname,
                        software_version=version,
                        interface=name,
                        exists=True,
                        description=description,
                        protected="".join(name.split()).casefold() in protected,
                        enabled=enabled,
                        operational_status=_normalized_status(
                            _child_text(element, "oper-status")
                        ),
                        ipv4_addresses=addresses,
                    )
                )
        except Exception:
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
        result: ExecutionResult | None = None
        attempted = False
        cleanup_failed = False
        try:
            with self._session(device, credentials) as connection:
                config = None
                entered = False
                try:
                    config = self._config_factory(connection, mode="exclusive")
                    config.__enter__()
                    entered = True
                except Exception:
                    result = _confirmation_failed()
                if entered:
                    attempted = True
                    try:
                        confirmed = config.commit_check()
                    except (ConnectClosedError, ConnectError, RpcTimeoutError):
                        result = _confirmation_ambiguous()
                    except (CommitError, RpcError):
                        result = _confirmation_failed()
                    except Exception:
                        result = _confirmation_ambiguous()
                    else:
                        result = (
                            _confirmation_succeeded()
                            if confirmed is True
                            else _confirmation_failed()
                        )
                    try:
                        config.__exit__(None, None, None)
                    except Exception:
                        cleanup_failed = True
        except ProviderError:
            cleanup_failed = True
            if result is None:
                result = (
                    _confirmation_ambiguous() if attempted else _confirmation_failed()
                )
        if result is None:
            return _confirmation_failed()
        if cleanup_failed and result.disposition is ExecutionDisposition.SUCCEEDED:
            return result.model_copy(
                update={
                    "message": (
                        "pending commit confirmed with known success; "
                        "session cleanup warning"
                    )
                }
            )
        return result


def _confirmation_failed() -> ExecutionResult:
    return ExecutionResult(
        disposition=ExecutionDisposition.FAILED,
        message="confirmation failed; automatic rollback remains expected",
        provider="pyez/config-exclusive",
    )


def _confirmation_ambiguous() -> ExecutionResult:
    return ExecutionResult(
        disposition=ExecutionDisposition.AMBIGUOUS,
        message="confirmation result is ambiguous; final persistence uncertain",
        provider="pyez/config-exclusive",
    )


def _confirmation_succeeded() -> ExecutionResult:
    return ExecutionResult(
        disposition=ExecutionDisposition.SUCCEEDED,
        message="pending commit confirmed with known success",
        provider="pyez/config-exclusive",
    )
