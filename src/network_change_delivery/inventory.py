"""Read-only inventory provider boundary and concrete adapters."""

from __future__ import annotations

import ipaddress
import os
from pathlib import Path
from typing import ClassVar, Protocol
from urllib.parse import urlparse

import httpx
import yaml

from network_change_delivery.models import (
    InventoryDevice,
    InventoryDocument,
    NetBoxFleetSelector,
)


class InventoryError(ValueError):
    """Raised when local inventory cannot resolve a safe target."""


class InventoryProvider(Protocol):
    """Boundary for target inventory resolution."""

    def resolve(self, target: str, interface: str | None = None) -> InventoryDevice:
        """Resolve one explicit logical target and optional interface identity."""


class FleetInventoryProvider(Protocol):
    """Boundary for exact deterministic fleet selection."""

    def resolve_fleet(
        self, selector: NetBoxFleetSelector
    ) -> tuple[tuple[InventoryDevice, str], ...]:
        """Resolve every selected device and exactly one tagged interface."""


class FleetPreflightInventoryProvider(
    InventoryProvider, FleetInventoryProvider, Protocol
):
    """Inventory boundary supporting selection and exact member re-resolution."""


class ManagedInventoryProvider(Protocol):
    """Boundary for a complete deterministic managed-device population."""

    def resolve_managed_devices(self) -> tuple[InventoryDevice, ...]:
        """Resolve every active device carrying the ncdp-managed tag."""


class LocalYamlInventoryProvider:
    """Temporary YAML-backed inventory implementation."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def resolve(self, target: str, interface: str | None = None) -> InventoryDevice:
        """Resolve exactly one named device or fail closed."""
        del interface
        try:
            payload = yaml.safe_load(self._path.read_text(encoding="utf-8"))
            document = InventoryDocument.model_validate(payload)
        except (OSError, yaml.YAMLError, ValueError) as error:
            raise InventoryError("local inventory is invalid or unreadable") from error
        matches = [device for device in document.devices if device.name == target]
        if len(matches) != 1:
            raise InventoryError(f"target {target!r} does not resolve exactly once")
        return matches[0].model_copy(
            update={
                "inventory_source": "local_yaml",
                "inventory_object_id": None,
                "inventory_interface_object_id": None,
            }
        )


class NetBoxInventoryProvider:
    """Read-only NetBox REST API inventory adapter."""

    _DEVICE_PATH = "/api/dcim/devices/"
    _INTERFACE_PATH = "/api/dcim/interfaces/"
    _PLATFORM_MAPPING: ClassVar[dict[str, tuple[str, int]]] = {
        "cisco-ios-xe": ("cisco_iosxe", 22),
        "juniper-junos": ("junos", 830),
    }

    def __init__(
        self,
        url: str | None = None,
        token: str | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        configured_url = url or os.environ.get("NCDP_NETBOX_URL")
        configured_token = token or os.environ.get("NCDP_NETBOX_TOKEN")
        if not configured_url or not configured_token:
            raise InventoryError("NetBox configuration missing")
        self._base_url = self._validate_url(configured_url)
        try:
            self._client = httpx.Client(
                base_url=self._base_url,
                headers={"Authorization": f"Bearer {configured_token}"},
                timeout=httpx.Timeout(5.0, connect=3.0),
                follow_redirects=False,
                verify=True,
                trust_env=False,
                transport=transport,
            )
        except (TypeError, ValueError):
            raise InventoryError("NetBox configuration missing") from None

    @staticmethod
    def _validate_url(value: str) -> str:
        try:
            parsed = urlparse(value)
            hostname = parsed.hostname
            _port = parsed.port
        except ValueError:
            raise InventoryError("NetBox URL rejected") from None
        if parsed.scheme not in {"http", "https"} or not hostname:
            raise InventoryError("NetBox URL rejected")
        if (
            parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise InventoryError("NetBox URL rejected")
        if parsed.scheme == "http" and hostname.casefold() not in {
            "127.0.0.1",
            "::1",
            "localhost",
        }:
            raise InventoryError("NetBox URL rejected: HTTP requires loopback")
        return value.rstrip("/")

    def _get(self, path: str, *, params: dict[str, object]) -> dict[str, object]:
        try:
            response = self._client.get(path, params=params)
        except httpx.TimeoutException:
            raise InventoryError("NetBox unavailable or timed out") from None
        except httpx.RequestError:
            raise InventoryError("NetBox unavailable or timed out") from None
        if response.status_code in {401, 403}:
            raise InventoryError("NetBox authentication or authorization failed")
        if response.status_code != 200:
            raise InventoryError(
                f"NetBox returned unexpected HTTP status {response.status_code}"
            )
        try:
            payload = response.json()
        except ValueError:
            raise InventoryError("NetBox returned invalid JSON or schema") from None
        if not isinstance(payload, dict):
            raise InventoryError("NetBox returned invalid JSON or schema")
        return payload

    def _get_all(
        self, path: str, *, params: dict[str, object]
    ) -> list[dict[str, object]]:
        """Read a bounded NetBox result set across validated offset pages."""
        limit = 100
        offset = 0
        expected_count: int | None = None
        results: list[dict[str, object]] = []
        while True:
            payload = self._get(
                path, params={**params, "limit": limit, "offset": offset}
            )
            page = self._results(payload)
            count = payload.get("count")
            if not isinstance(count, int) or isinstance(count, bool) or count < 0:
                raise InventoryError("NetBox returned invalid JSON or schema")
            if expected_count is None:
                expected_count = count
                if expected_count > 10_000:
                    raise InventoryError("NetBox selected population is too large")
            elif count != expected_count:
                raise InventoryError("NetBox pagination changed during resolution")
            results.extend(page)
            next_page = payload.get("next")
            if next_page is None:
                if len(results) != expected_count:
                    raise InventoryError("NetBox pagination is incomplete")
                return results
            if not isinstance(next_page, str) or not next_page or not page:
                raise InventoryError("NetBox pagination is invalid")
            offset += len(page)
            if offset >= expected_count:
                raise InventoryError("NetBox pagination is invalid")

    @staticmethod
    def _results(payload: dict[str, object]) -> list[dict[str, object]]:
        results = payload.get("results")
        count = payload.get("count")
        if (
            not isinstance(results, list)
            or not isinstance(count, int)
            or any(not isinstance(item, dict) for item in results)
        ):
            raise InventoryError("NetBox returned invalid JSON or schema")
        return results

    def resolve(self, target: str, interface: str | None = None) -> InventoryDevice:
        """Resolve one exact eligible device and complete protection metadata."""
        payload = self._get(self._DEVICE_PATH, params={"name": target, "limit": 2})
        devices = self._results(payload)
        exact = [device for device in devices if device.get("name") == target]
        if not exact:
            raise InventoryError("NetBox target not found")
        if len(exact) != 1 or payload.get("count") != 1:
            raise InventoryError("NetBox target is ambiguous")
        device = exact[0]
        status = device.get("status")
        if not isinstance(status, dict) or status.get("value") != "active":
            raise InventoryError("NetBox target is inactive")
        tags = device.get("tags")
        if not isinstance(tags, list) or not any(
            isinstance(tag, dict) and tag.get("slug") == "ncdp-managed" for tag in tags
        ):
            raise InventoryError("NetBox target is missing ncdp-managed tag")
        platform = device.get("platform")
        slug = platform.get("slug") if isinstance(platform, dict) else None
        if slug not in self._PLATFORM_MAPPING:
            raise InventoryError("NetBox target has unsupported or missing platform")
        internal_platform, port = self._PLATFORM_MAPPING[slug]
        primary = device.get("primary_ip4")
        address = primary.get("address") if isinstance(primary, dict) else None
        if not isinstance(address, str):
            raise InventoryError("NetBox target has missing or invalid primary IPv4")
        try:
            host = str(ipaddress.IPv4Interface(address).ip)
        except ValueError as error:
            raise InventoryError(
                "NetBox target has missing or invalid primary IPv4"
            ) from error
        object_id = device.get("id")
        if not isinstance(object_id, int) or isinstance(object_id, bool):
            raise InventoryError("NetBox returned invalid JSON or schema")
        interface_object_id: str | None = None
        if interface is not None:
            requested_payload = self._get(
                self._INTERFACE_PATH,
                params={"device_id": object_id, "name": interface, "limit": 2},
            )
            requested_interfaces = self._results(requested_payload)
            exact_interfaces = [
                item for item in requested_interfaces if item.get("name") == interface
            ]
            if not exact_interfaces:
                raise InventoryError("NetBox requested interface not found")
            if len(exact_interfaces) != 1 or requested_payload.get("count") != 1:
                raise InventoryError("NetBox requested interface is ambiguous")
            requested_id = exact_interfaces[0].get("id")
            if not isinstance(requested_id, int) or isinstance(requested_id, bool):
                raise InventoryError("NetBox requested interface identity is invalid")
            interface_object_id = f"netbox:dcim.interface:{requested_id}"
        interfaces_payload = self._get(
            self._INTERFACE_PATH,
            params={"device_id": object_id, "tag": "ncdp-protected", "limit": 1000},
        )
        try:
            interfaces = self._results(interfaces_payload)
        except InventoryError:
            raise InventoryError(
                "NetBox interface protection data is incomplete"
            ) from None
        if interfaces_payload.get("next") is not None or interfaces_payload.get(
            "count"
        ) != len(interfaces):
            raise InventoryError("NetBox interface protection data is incomplete")
        protected: list[str] = []
        for interface in interfaces:
            name = interface.get("name")
            if not isinstance(name, str) or not name.strip():
                raise InventoryError("NetBox interface protection data is incomplete")
            protected.append(name.strip())
        return InventoryDevice(
            name=target,
            host=host,
            port=port,
            platform=internal_platform,
            expected_hostname=target,
            protected_interfaces=tuple(sorted(set(protected))),
            inventory_source="netbox",
            inventory_object_id=f"netbox:dcim.device:{object_id}",
            inventory_interface_object_id=interface_object_id,
        )

    @staticmethod
    def _tag_slugs(value: object) -> set[str]:
        if not isinstance(value, list) or any(
            not isinstance(tag, dict) for tag in value
        ):
            raise InventoryError("NetBox returned invalid JSON or schema")
        slugs: set[str] = set()
        for tag in value:
            slug = tag.get("slug")
            if not isinstance(slug, str) or not slug:
                raise InventoryError("NetBox returned invalid JSON or schema")
            slugs.add(slug)
        return slugs

    def resolve_fleet(
        self, selector: NetBoxFleetSelector
    ) -> tuple[tuple[InventoryDevice, str], ...]:
        """Resolve a narrow tag-selected active NetBox fleet exactly once."""
        device_payloads = self._get_all(
            self._DEVICE_PATH,
            params={
                "tag": selector.device_tag,
                "status": "active",
                "ordering": "id",
            },
        )
        if not device_payloads:
            raise InventoryError("NetBox fleet selector matched zero devices")
        resolved: list[tuple[InventoryDevice, str]] = []
        names: set[str] = set()
        identities: set[str] = set()
        interface_identities: set[str] = set()
        for payload in device_payloads:
            name = payload.get("name")
            object_id = payload.get("id")
            status = payload.get("status")
            if not isinstance(name, str) or not name.strip():
                raise InventoryError("NetBox fleet device identity is invalid")
            name = name.strip()
            if not isinstance(object_id, int) or isinstance(object_id, bool):
                raise InventoryError("NetBox fleet device identity is invalid")
            identity = f"netbox:dcim.device:{object_id}"
            if name in names or identity in identities:
                raise InventoryError("NetBox fleet contains duplicate device identity")
            names.add(name)
            identities.add(identity)
            if not isinstance(status, dict) or status.get("value") != "active":
                raise InventoryError("NetBox fleet target is inactive")
            tags = self._tag_slugs(payload.get("tags"))
            if "ncdp-managed" not in tags or selector.device_tag not in tags:
                raise InventoryError("NetBox fleet target is missing required tags")
            platform = payload.get("platform")
            slug = platform.get("slug") if isinstance(platform, dict) else None
            if slug not in self._PLATFORM_MAPPING:
                raise InventoryError("NetBox fleet target has unsupported platform")
            internal_platform, port = self._PLATFORM_MAPPING[slug]
            primary = payload.get("primary_ip4")
            address = primary.get("address") if isinstance(primary, dict) else None
            if not isinstance(address, str):
                raise InventoryError("NetBox fleet target has missing primary IPv4")
            try:
                host = str(ipaddress.IPv4Interface(address).ip)
            except ValueError:
                raise InventoryError(
                    "NetBox fleet target has missing primary IPv4"
                ) from None
            interfaces = self._get_all(
                self._INTERFACE_PATH,
                params={
                    "device_id": object_id,
                    "tag": selector.interface_tag,
                    "ordering": "id",
                },
            )
            if not interfaces:
                raise InventoryError("NetBox fleet interface selector matched zero")
            if len(interfaces) != 1:
                raise InventoryError(
                    "NetBox fleet interface selector is not exact for one device"
                )
            interface = interfaces[0]
            interface_name = interface.get("name")
            interface_id = interface.get("id")
            if not isinstance(interface_name, str) or not interface_name.strip():
                raise InventoryError("NetBox fleet interface identity is invalid")
            if not isinstance(interface_id, int) or isinstance(interface_id, bool):
                raise InventoryError("NetBox fleet interface identity is invalid")
            interface_name = interface_name.strip()
            interface_identity = f"netbox:dcim.interface:{interface_id}"
            if interface_identity in interface_identities:
                raise InventoryError(
                    "NetBox fleet contains duplicate interface identity"
                )
            interface_identities.add(interface_identity)
            interface_tags = self._tag_slugs(interface.get("tags"))
            if selector.interface_tag not in interface_tags:
                raise InventoryError("NetBox fleet interface is missing selector tag")
            if "ncdp-protected" in interface_tags:
                raise InventoryError("NetBox fleet target interface is protected")
            device = InventoryDevice(
                name=name,
                host=host,
                port=port,
                platform=internal_platform,
                expected_hostname=name,
                protected_interfaces=(),
                inventory_source="netbox",
                inventory_object_id=identity,
                inventory_interface_object_id=interface_identity,
            )
            resolved.append((device, interface_name))
        return tuple(
            sorted(
                resolved,
                key=lambda item: (
                    item[0].inventory_object_id or "",
                    item[0].name,
                    item[0].inventory_interface_object_id or "",
                ),
            )
        )

    def resolve_managed_devices(self) -> tuple[InventoryDevice, ...]:
        """Resolve the complete active ncdp-managed population without interfaces."""
        payloads = self._get_all(
            self._DEVICE_PATH,
            params={"tag": "ncdp-managed", "status": "active", "ordering": "id"},
        )
        if not payloads:
            raise InventoryError("NetBox managed population matched zero devices")
        resolved: list[tuple[int, InventoryDevice]] = []
        identities: set[str] = set()
        for payload in payloads:
            object_id = payload.get("id")
            name = payload.get("name")
            status = payload.get("status")
            if (
                not isinstance(object_id, int)
                or isinstance(object_id, bool)
                or object_id <= 0
                or not isinstance(name, str)
                or not name.strip()
            ):
                raise InventoryError("NetBox managed device identity is invalid")
            identity = f"netbox:dcim.device:{object_id}"
            if identity in identities:
                raise InventoryError(
                    "NetBox managed population contains duplicate identity"
                )
            identities.add(identity)
            if not isinstance(status, dict) or status.get("value") != "active":
                raise InventoryError("NetBox managed target is inactive")
            if "ncdp-managed" not in self._tag_slugs(payload.get("tags")):
                raise InventoryError("NetBox managed target is missing required tag")
            platform = payload.get("platform")
            slug = platform.get("slug") if isinstance(platform, dict) else None
            if slug not in self._PLATFORM_MAPPING:
                raise InventoryError("NetBox managed target has unsupported platform")
            internal_platform, port = self._PLATFORM_MAPPING[slug]
            primary = payload.get("primary_ip4")
            address = primary.get("address") if isinstance(primary, dict) else None
            if not isinstance(address, str):
                raise InventoryError("NetBox managed target has missing primary IPv4")
            try:
                host = str(ipaddress.IPv4Interface(address).ip)
            except ValueError:
                raise InventoryError(
                    "NetBox managed target has missing primary IPv4"
                ) from None
            resolved.append(
                (
                    object_id,
                    InventoryDevice(
                        name=name.strip(),
                        host=host,
                        port=port,
                        platform=internal_platform,
                        expected_hostname=name.strip(),
                        protected_interfaces=(),
                        inventory_source="netbox",
                        inventory_object_id=identity,
                        inventory_interface_object_id=None,
                    ),
                )
            )
        return tuple(device for _, device in sorted(resolved, key=lambda item: item[0]))
