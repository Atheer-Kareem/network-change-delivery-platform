"""CML realization admission for management-service reachability telemetry."""

from __future__ import annotations

import hashlib
import os
import ssl
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator

from network_change_delivery.audit import Sha256, canonical_json_bytes
from network_change_delivery.observability_private_paths import (
    ObservabilityPrivatePathError,
    ensure_private_tree,
    validate_observability_root,
    validate_private_file,
)
from network_change_delivery.profiled_live_cml import ACCESS_NODE_ID, TRANSIT_NODE_ID

LIVE_LAB_ID = "09605569-0468-4fc4-8684-beb5a1342b9c"
LIVE_LAB_TITLE = "NCDP Live"
ADMISSION_TTL = timedelta(minutes=15)
EXPECTED_NODES = {
    "netbox:dcim.device:1": {
        "name": "core-02",
        "cml_label": "cat8000v-0",
        "address": "192.168.4.14",
        "definition": "cat8000v",
        "image": "cat8000v-17-18-02",
    },
    "netbox:dcim.device:2": {
        "name": "edge-junos-01",
        "cml_label": "vjunos-router-0",
        "address": "192.168.4.20",
        "definition": "vjunos-router",
        "image": "vjunos-router-23-2r1-15",
    },
}
EXPECTED_PROFILED_NON_TARGET_NODES = {
    TRANSIT_NODE_ID: {
        "name": "transit-ios-01",
        "cml_label": "transit-ios-01",
        "address": "192.168.4.16",
        "definition": "iosv",
        "image": "iosv-159-3-m12",
        "required_configuration": (),
    },
    ACCESS_NODE_ID: {
        "name": "access-sw-01",
        "cml_label": "access-sw-01",
        "address": "192.168.4.17",
        "definition": "iosvl2",
        "image": "iosvl2-2020",
        "required_configuration": ("no switchport",),
    },
}
_UUID_PATTERN = r"^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$"


class ObservabilityRealizationError(ValueError):
    """Bounded CML authority/admission failure."""


class RealizationNode(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    inventory_object_id: Literal["netbox:dcim.device:1", "netbox:dcim.device:2"]
    stable_name: Literal["core-02", "edge-junos-01"]
    cml_node_id: str = Field(pattern=_UUID_PATTERN)
    management_ip: Literal["192.168.4.14", "192.168.4.20"]
    node_definition: Literal["cat8000v", "vjunos-router"]
    image_definition: Literal["cat8000v-17-18-02", "vjunos-router-23-2r1-15"]
    state: Literal["BOOTED"] = "BOOTED"


class RealizationAdmission(BaseModel):
    """Private exact-two target projection from the admitted profiled LIVE lab."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["2"] = "2"
    lab_id: Literal["09605569-0468-4fc4-8684-beb5a1342b9c"] = LIVE_LAB_ID
    lab_title: Literal["NCDP Live"] = LIVE_LAB_TITLE
    lab_state: Literal["STARTED"] = "STARTED"
    admitted_at: datetime
    expires_at: datetime
    nodes: tuple[RealizationNode, RealizationNode]
    digest: Sha256

    @model_validator(mode="after")
    def exact_admission(self) -> RealizationAdmission:
        identities = tuple(item.inventory_object_id for item in self.nodes)
        if (
            self.admitted_at.tzinfo is None
            or self.admitted_at.utcoffset() is None
            or self.expires_at <= self.admitted_at
            or identities != tuple(EXPECTED_NODES)
        ):
            raise ValueError("observability realization admission rejected")
        for node in self.nodes:
            expected = EXPECTED_NODES[node.inventory_object_id]
            if (
                node.stable_name != expected["name"]
                or node.management_ip != expected["address"]
                or node.node_definition != expected["definition"]
                or node.image_definition != expected["image"]
            ):
                raise ValueError("observability realization admission rejected")
        if self.digest != self.calculated_digest():
            raise ValueError("observability realization digest rejected")
        return self

    def calculated_digest(self) -> str:
        content = canonical_json_bytes(self.model_dump(mode="json", exclude={"digest"}))
        return f"sha256:{hashlib.sha256(content).hexdigest()}"


class CmlRealizationAuthority:
    """Read-only exact CML API boundary for the persistent live realization."""

    def __init__(
        self,
        address: str,
        certificate: str,
        username: str,
        password: str,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        try:
            parsed = urlparse(address)
        except ValueError:
            raise ObservabilityRealizationError("CML authority rejected") from None
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
            or not certificate
            or not username
            or not password
        ):
            raise ObservabilityRealizationError("CML authority rejected")
        try:
            context = ssl.create_default_context(cadata=certificate)
            self._client = httpx.Client(
                base_url=address.rstrip("/"),
                verify=context,
                timeout=httpx.Timeout(20, connect=5),
                follow_redirects=False,
                trust_env=False,
                transport=transport,
            )
        except (OSError, ValueError):
            raise ObservabilityRealizationError("CML authority rejected") from None
        try:
            response = self._client.post(
                "/api/v0/authenticate",
                json={"username": username, "password": password},
            )
            if response.status_code != 200:
                raise ObservabilityRealizationError("CML authentication failed")
            payload = response.json()
            token = payload if isinstance(payload, str) else payload.get("token")
        except (httpx.HTTPError, ValueError):
            raise ObservabilityRealizationError("CML authentication failed") from None
        if not isinstance(token, str) or not token:
            raise ObservabilityRealizationError("CML authentication failed")
        self._client.headers["Authorization"] = f"Bearer {token}"

    def close(self) -> None:
        self._client.close()

    def _get(self, path: str) -> Any:
        try:
            response = self._client.get(path)
            if response.status_code != 200 or len(response.content) > 2 * 1024 * 1024:
                raise ObservabilityRealizationError("CML authority unavailable")
            return response.json()
        except (httpx.HTTPError, ValueError):
            raise ObservabilityRealizationError("CML authority unavailable") from None

    def _configuration(self, lab_id: str, node_id: str) -> str:
        for suffix in ("configuration", "configurations"):
            try:
                response = self._client.get(
                    f"/api/v0/labs/{lab_id}/nodes/{node_id}/{suffix}"
                )
            except httpx.HTTPError:
                continue
            if response.status_code != 200:
                continue
            if len(response.content) > 2 * 1024 * 1024:
                raise ObservabilityRealizationError("CML Day-0 identity unavailable")
            try:
                payload = response.json()
            except ValueError:
                continue
            if isinstance(payload, str):
                return payload
            if isinstance(payload, dict):
                value = payload.get("configuration") or payload.get(
                    "config/juniper.conf"
                )
                if isinstance(value, str):
                    return value
            if isinstance(payload, list):
                return self._list_configuration(payload)
        node = self._get(f"/api/v0/labs/{lab_id}/nodes/{node_id}")
        if isinstance(node, dict):
            configuration = node.get("configuration")
            if isinstance(configuration, str):
                return configuration
            if isinstance(configuration, list):
                return self._list_configuration(configuration)
        raise ObservabilityRealizationError("CML Day-0 identity unavailable")

    @staticmethod
    def _list_configuration(payload: list[Any]) -> str:
        """Read the single CML 2.10 stored-configuration entry."""
        if len(payload) != 1 or not isinstance(payload[0], dict):
            raise ObservabilityRealizationError("CML Day-0 identity unavailable")
        content = payload[0].get("content")
        if not isinstance(content, str) or not content:
            raise ObservabilityRealizationError("CML Day-0 identity unavailable")
        return content

    def admit(
        self,
        lab_id: str,
        node_ids: dict[str, str],
        *,
        now: datetime | None = None,
    ) -> RealizationAdmission:
        """Validate exact profiled LIVE identity and legacy target readiness."""
        if lab_id != LIVE_LAB_ID or set(node_ids) != set(EXPECTED_NODES):
            raise ObservabilityRealizationError("CML node population rejected")
        lab_ids = self._get("/api/v0/labs")
        if (
            not isinstance(lab_ids, list)
            or any(not isinstance(item, str) for item in lab_ids)
            or len(lab_ids) != len(set(lab_ids))
        ):
            raise ObservabilityRealizationError("CML lab population rejected")
        live_seen = False
        for candidate in lab_ids:
            lab = self._get(f"/api/v0/labs/{candidate}")
            if not isinstance(lab, dict):
                raise ObservabilityRealizationError("CML lab population rejected")
            title = lab.get("lab_title") or lab.get("title")
            if candidate == LIVE_LAB_ID:
                if title != LIVE_LAB_TITLE or lab.get("state") != "STARTED":
                    raise ObservabilityRealizationError(
                        "persistent live CML realization rejected"
                    )
                live_seen = True
                continue
            foreign_nodes = self._get(f"/api/v0/labs/{candidate}/nodes")
            if not isinstance(foreign_nodes, list):
                raise ObservabilityRealizationError("CML address ownership ambiguous")
            for foreign_node_id in foreign_nodes:
                foreign_node = self._get(
                    f"/api/v0/labs/{candidate}/nodes/{foreign_node_id}"
                )
                if not isinstance(foreign_node, dict):
                    raise ObservabilityRealizationError(
                        "CML address ownership ambiguous"
                    )
                if foreign_node.get("state") not in {"BOOTED", "STARTED"}:
                    continue
                if foreign_node.get("node_definition") in {
                    "external_connector",
                    "unmanaged_switch",
                }:
                    continue
                configuration = self._configuration(candidate, foreign_node_id)
                if any(
                    expected["address"] in configuration
                    for expected in (
                        *EXPECTED_NODES.values(),
                        *EXPECTED_PROFILED_NON_TARGET_NODES.values(),
                    )
                ):
                    raise ObservabilityRealizationError(
                        "CML address ownership ambiguous"
                    )
        if not live_seen:
            raise ObservabilityRealizationError(
                "persistent live CML realization rejected"
            )

        actual_ids = self._get(f"/api/v0/labs/{lab_id}/nodes")
        if not isinstance(actual_ids, list):
            raise ObservabilityRealizationError("CML node population rejected")
        admitted_non_targets: set[str] = set()
        for actual_id in actual_ids:
            if actual_id in node_ids.values():
                continue
            node = self._get(f"/api/v0/labs/{lab_id}/nodes/{actual_id}")
            if not isinstance(node, dict):
                raise ObservabilityRealizationError("CML node population rejected")
            expected_profiled = EXPECTED_PROFILED_NON_TARGET_NODES.get(actual_id)
            if expected_profiled is not None:
                configuration = self._configuration(lab_id, actual_id)
                image = node.get("image_definition") or node.get("image_definition_id")
                if (
                    node.get("label") != expected_profiled["cml_label"]
                    or node.get("node_definition") != expected_profiled["definition"]
                    or image != expected_profiled["image"]
                    or node.get("state") != "BOOTED"
                    or expected_profiled["name"] not in configuration
                    or expected_profiled["address"] not in configuration
                    or any(
                        marker not in configuration
                        for marker in expected_profiled["required_configuration"]
                    )
                ):
                    raise ObservabilityRealizationError(
                        "profiled non-target CML node rejected"
                    )
                admitted_non_targets.add(actual_id)
                continue
            if node.get("node_definition") not in {
                "external_connector",
                "unmanaged_switch",
            }:
                raise ObservabilityRealizationError("CML node population rejected")
        if admitted_non_targets != set(EXPECTED_PROFILED_NON_TARGET_NODES):
            raise ObservabilityRealizationError("CML node population rejected")
        nodes: list[RealizationNode] = []
        for identity, expected in EXPECTED_NODES.items():
            node_id = node_ids[identity]
            if node_id not in actual_ids:
                raise ObservabilityRealizationError("CML node identity rejected")
            node = self._get(f"/api/v0/labs/{lab_id}/nodes/{node_id}")
            if not isinstance(node, dict):
                raise ObservabilityRealizationError("CML node identity rejected")
            configuration = self._configuration(lab_id, node_id)
            image = node.get("image_definition") or node.get("image_definition_id")
            if (
                node.get("label") != expected["cml_label"]
                or node.get("node_definition") != expected["definition"]
                or image != expected["image"]
                or node.get("state") != "BOOTED"
                or expected["name"] not in configuration
                or expected["address"] not in configuration
            ):
                raise ObservabilityRealizationError("CML node admission rejected")
            nodes.append(
                RealizationNode(
                    inventory_object_id=identity,
                    stable_name=expected["name"],
                    cml_node_id=node_id,
                    management_ip=expected["address"],
                    node_definition=expected["definition"],
                    image_definition=expected["image"],
                )
            )
        admitted = (now or datetime.now(UTC)).astimezone(UTC)
        unsigned = RealizationAdmission.model_construct(
            schema_version="2",
            lab_id=lab_id,
            lab_title=LIVE_LAB_TITLE,
            lab_state="STARTED",
            admitted_at=admitted,
            expires_at=admitted + ADMISSION_TTL,
            nodes=tuple(nodes),
            digest="sha256:" + "0" * 64,
        )
        return RealizationAdmission.model_validate(
            {
                **unsigned.model_dump(mode="json", exclude={"digest"}),
                "digest": unsigned.calculated_digest(),
            }
        )


def publish_admission(root: Path, admission: RealizationAdmission) -> Path:
    """Atomically publish one canonical private admission record."""
    validate_observability_root(root)
    ensure_private_tree(root, "operator", "control")
    path = root / "operator/realization.json"
    content = canonical_json_bytes(admission.model_dump(mode="json"))
    descriptor, name = tempfile.mkstemp(prefix=".realization.", dir=path.parent)
    temporary = Path(name)
    replaced = False
    try:
        os.fchmod(descriptor, 0o600)
        os.write(descriptor, content)
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        temporary.replace(path)
        replaced = True
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except OSError as error:
        if replaced:
            raise ObservabilityRealizationError(
                "realization publication outcome ambiguous"
            ) from error
        raise ObservabilityRealizationError("realization publication failed") from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)
    return path


def read_admission(root: Path, *, now: datetime | None = None) -> RealizationAdmission:
    try:
        content = validate_private_file(root / "operator/realization.json")
        assert content is not None
        admission = RealizationAdmission.model_validate_json(content)
    except (ValueError, ObservabilityPrivatePathError):
        raise ObservabilityRealizationError("realization admission rejected") from None
    current = (now or datetime.now(UTC)).astimezone(UTC)
    if admission.expires_at <= current:
        raise ObservabilityRealizationError("realization admission expired")
    return admission


def retire_admission(root: Path) -> None:
    """Remove only the realization authorization after target retirement."""
    path = root / "operator/realization.json"
    path.unlink(missing_ok=True)
    if path.parent.exists():
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
